from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .app.extraction import extract_notice
from .app.matchers import match_job
from .app.opportunity_matcher import match_opportunity
from .app.repository import (
    ensure_seed_data,
    get_job,
    import_notice,
    list_changes,
    list_jobs,
    list_opportunities,
    list_signals,
    refresh_expired_statuses,
    refresh_job_families,
    remove_demo_data,
    remove_tracker,
    save_tracker,
)
from .app.schemas import (
    ImportTextRequest,
    MatchRequest,
    ResumeOpportunityMatchRequest,
    TrackerRequest,
    WechatAutoSearchImportRequest,
    WechatDiscoverRequest,
    WechatIngestHtmlRequest,
    WechatIngestUrlRequest,
)

from .app.web_search_importer import auto_search_and_import, build_plain_search_url
from .app.source_registry import registry_items
from .app.wechat_articles import (
    build_sogou_search_url,
    discover_sogou,
    get_article_by_id,
    ingest_html,
    ingest_url,
    list_discovery_runs,
    list_sources,
    search_articles,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "apps" / "web"
APP_VERSION = "0.8.0"

app = FastAPI(title="Job Radar 校招雷达", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    ensure_seed_data()
    remove_demo_data()
    refresh_job_families()
    refresh_expired_statuses()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": APP_VERSION}


@app.get("/api/signals")
def api_signals(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return {"items": list_signals(limit=limit)}


@app.get("/api/jobs")
def api_jobs(
    query: Optional[str] = None,
    city: Optional[str] = None,
    cohort: Optional[str] = None,
    accepts_overseas: Optional[bool] = None,
    max_written_test_burden: Optional[int] = Query(default=None, ge=0, le=5),
    only_open: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    jobs = list_jobs({
        "query": query,
        "city": city,
        "cohort": cohort,
        "accepts_overseas": accepts_overseas,
        "max_written_test_burden": max_written_test_burden,
        "only_open": only_open,
        "limit": limit,
    })
    return {"items": jobs, "count": len(jobs)}


@app.get("/api/opportunities")
def api_opportunities(
    query: Optional[str] = None,
    city: Optional[str] = None,
    cohort: Optional[str] = None,
    recruitment_type: Optional[str] = None,
    company_type: Optional[str] = None,
    industry: Optional[str] = None,
    job_family: Optional[str] = None,
    major: Optional[str] = None,
    source_level: Optional[str] = Query(default=None, pattern="^[SABCD]?$"),
    tracker_status: Optional[str] = None,
    tracked_only: bool = False,
    freshness_days: int = Query(default=0, ge=0, le=3650),
    include_expired: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    return list_opportunities({
        "query": query,
        "city": city,
        "cohort": cohort,
        "recruitment_type": recruitment_type,
        "company_type": company_type,
        "industry": industry,
        "job_family": job_family,
        "major": major,
        "source_level": source_level,
        "tracker_status": tracker_status,
        "tracked_only": tracked_only,
        "freshness_days": freshness_days,
        "include_expired": include_expired,
        "offset": offset,
        "limit": limit,
    })


@app.post("/api/opportunities/match")
def api_match_opportunities(request: ResumeOpportunityMatchRequest) -> dict:
    filters = {**(request.filters or {}), "offset": 0, "limit": 500}
    data = list_opportunities(filters)
    items = []
    for opportunity in data["items"]:
        items.append({
            **opportunity,
            "match": match_opportunity(
                request.resume_text,
                opportunity,
                target_cities=request.target_cities,
                preferred_job_families=request.preferred_job_families,
                degree=request.degree,
            ),
        })
    items.sort(key=lambda item: (item["match"]["score"], item.get("updated_at") or ""), reverse=True)
    return {"items": items, "count": len(items)}


@app.put("/api/tracker/{record_type}/{record_id}")
def api_save_tracker(record_type: str, record_id: int, request: TrackerRequest) -> dict:
    try:
        return save_tracker(
            record_type,
            record_id,
            request.status,
            note=request.note,
            is_favorite=request.is_favorite,
            next_action_at=request.next_action_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/tracker/{record_type}/{record_id}")
def api_remove_tracker(record_type: str, record_id: int) -> dict:
    try:
        return {"removed": remove_tracker(record_type, record_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def api_job(job_id: int) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/api/match")
def api_match(request: MatchRequest) -> dict:
    profile = request.profile.model_dump()
    if request.job_ids:
        jobs = []
        for job_id in request.job_ids:
            job = get_job(job_id)
            if job:
                jobs.append(job)
    else:
        filters = request.filters or {}
        jobs = list_jobs({**filters, "limit": filters.get("limit", 100)})
    items = []
    for job in jobs:
        items.append({"job": job, "match": match_job(profile, job)})
    return {"items": items, "count": len(items)}


@app.post("/api/admin/import-text")
def api_import_text(request: ImportTextRequest) -> dict:
    extracted = extract_notice(
        company_name=request.company_name,
        job_title=request.job_title,
        text=request.text,
        source_url=request.source_url,
        source_level=request.source_level,
    )
    result = import_notice(extracted)
    return {"imported": result, "extracted": extracted}


@app.get("/api/changes")
def api_changes(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return {"items": list_changes(limit=limit)}


@app.get("/api/wechat/articles")
def api_wechat_articles(
    q: Optional[str] = None,
    freshness_days: int = Query(default=45, ge=0, le=3650),
    trusted_only: bool = False,
    include_stale: bool = False,
    min_source_level: str = Query(default="", pattern="^[SABCD]?$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return search_articles(
        q=q or "",
        freshness_days=freshness_days,
        trusted_only=trusted_only,
        include_stale=include_stale,
        min_source_level=min_source_level,
        limit=limit,
    )


@app.get("/api/wechat/articles/{article_id}")
def api_wechat_article(article_id: int) -> dict:
    article = get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="wechat article not found")
    return article


@app.post("/api/wechat/ingest-html")
def api_wechat_ingest_html(request: WechatIngestHtmlRequest) -> dict:
    try:
        item = ingest_html(
            original_url=request.url,
            html_text=request.html,
            source=request.source,
            source_query=request.source_query,
            max_age_days=request.max_age_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@app.post("/api/wechat/ingest-url")
def api_wechat_ingest_url(request: WechatIngestUrlRequest) -> dict:
    try:
        item = ingest_url(
            url=request.url,
            source=request.source,
            source_query=request.source_query,
            max_age_days=request.max_age_days,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item}


@app.post("/api/wechat/discover")
def api_wechat_discover(request: WechatDiscoverRequest) -> dict:
    try:
        if request.provider == "sogou_weixin_search":
            return discover_sogou(
                keyword=request.keyword,
                page=request.page,
                freshness_days=request.freshness_days,
                html_text=request.html,
            )
        raise HTTPException(status_code=400, detail="only sogou_weixin_search is implemented")
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/wechat/search-links")
def api_wechat_search_links(
    keyword: str = Query(min_length=1),
    freshness_days: int = Query(default=45, ge=0, le=3650),
    source_scope: str = Query(default="all"),
) -> dict:
    try:
        urls = {
            "google": build_plain_search_url("google", keyword, freshness_days=freshness_days, source_scope=source_scope),
            "bing": build_plain_search_url("bing", keyword, freshness_days=freshness_days, source_scope=source_scope),
            "sogou": build_sogou_search_url(keyword, freshness_days=freshness_days),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"keyword": keyword, "source_scope": source_scope, "urls": urls}


@app.post("/api/wechat/auto-search-import")
def api_wechat_auto_search_import(request: WechatAutoSearchImportRequest) -> dict:
    return _auto_search_jobs(request)


@app.post("/api/jobs/auto-search")
def api_jobs_auto_search(request: WechatAutoSearchImportRequest) -> dict:
    return _auto_search_jobs(request)


def _auto_search_jobs(request: WechatAutoSearchImportRequest) -> dict:
    try:
        return auto_search_and_import(
            keyword=request.keyword,
            provider=request.provider,
            source_scope=request.source_scope,
            freshness_days=request.freshness_days,
            max_results=request.max_results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/wechat/config")
def api_wechat_config() -> dict:
    return {
        "personal_mode": os.getenv("JOB_RADAR_PERSONAL_MODE", "0") == "1",
        "public_fetch_enabled": os.getenv("ENABLE_WECHAT_PUBLIC_FETCH", "0") == "1",
        "web_search_import_enabled": os.getenv("ENABLE_WEB_SEARCH_IMPORT", "0") == "1" or os.getenv("JOB_RADAR_PERSONAL_MODE", "0") == "1",
        "sogou_discovery_enabled": os.getenv("ENABLE_SOGOU_DISCOVERY", "0") == "1",
    }


@app.get("/api/wechat/discovery-runs")
def api_wechat_discovery_runs(limit: int = Query(default=30, ge=1, le=200)) -> dict:
    return list_discovery_runs(limit=limit)


@app.get("/api/wechat/sources")
def api_wechat_sources() -> dict:
    return list_sources()


@app.get("/api/sources/registry")
def api_source_registry() -> dict:
    items = registry_items()
    return {"items": items, "count": len(items)}


if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIR)), name="assets")


@app.get("/")
def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="web app not found")
    return FileResponse(index_path)
