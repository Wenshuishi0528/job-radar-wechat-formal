from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from .change_detector import detect_changes
from .database import get_connection, init_db
from .extraction import ExtractedNotice, infer_job_family
from .source_registry import ensure_source_registry
from .wechat_articles import ensure_wechat_seed_data


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def loads_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def row_to_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def ensure_seed_data() -> None:
    init_db()
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        ensure_source_registry(conn)
        conn.commit()


def remove_demo_data() -> None:
    init_db()
    with get_connection() as conn:
        demo_company_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM companies WHERE name LIKE '示例%' OR official_site LIKE 'https://example.com/%' OR recruit_site LIKE 'https://example.com/%'"
            ).fetchall()
        ]
        demo_campaign_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM campaigns WHERE source_url LIKE 'https://example.com/%' OR apply_url LIKE 'https://example.com/%'"
            ).fetchall()
        ]
        demo_job_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM jobs WHERE source_url LIKE 'https://example.com/%' OR apply_url LIKE 'https://example.com/%'"
            ).fetchall()
        ]
        if demo_job_ids:
            placeholders = ",".join("?" for _ in demo_job_ids)
            conn.execute(f"DELETE FROM evidence WHERE entity_type='job' AND entity_id IN ({placeholders})", demo_job_ids)
            conn.execute(f"DELETE FROM process_rules WHERE job_id IN ({placeholders})", demo_job_ids)
            conn.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", demo_job_ids)
        if demo_campaign_ids:
            placeholders = ",".join("?" for _ in demo_campaign_ids)
            conn.execute(f"DELETE FROM evidence WHERE entity_type='campaign' AND entity_id IN ({placeholders})", demo_campaign_ids)
            conn.execute(f"DELETE FROM change_events WHERE entity_type='campaign' AND entity_id IN ({placeholders})", demo_campaign_ids)
            conn.execute(f"DELETE FROM process_rules WHERE campaign_id IN ({placeholders})", demo_campaign_ids)
            conn.execute(f"DELETE FROM jobs WHERE campaign_id IN ({placeholders})", demo_campaign_ids)
            conn.execute(f"DELETE FROM campaigns WHERE id IN ({placeholders})", demo_campaign_ids)
        conn.execute("DELETE FROM signals WHERE source_url LIKE 'https://example.com/%'")
        if demo_company_ids:
            placeholders = ",".join("?" for _ in demo_company_ids)
            conn.execute(f"DELETE FROM signals WHERE company_id IN ({placeholders})", demo_company_ids)
            conn.execute(f"DELETE FROM jobs WHERE company_id IN ({placeholders})", demo_company_ids)
            conn.execute(f"DELETE FROM campaigns WHERE company_id IN ({placeholders})", demo_company_ids)
            conn.execute(f"DELETE FROM companies WHERE id IN ({placeholders})", demo_company_ids)
        demo_article_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM wechat_articles WHERE canonical_url='https://mp.weixin.qq.com/s/demo-campus-recruit-2027' OR source='seed_demo'"
            ).fetchall()
        ]
        if demo_article_ids:
            placeholders = ",".join("?" for _ in demo_article_ids)
            conn.execute(f"DELETE FROM wechat_article_images WHERE article_id IN ({placeholders})", demo_article_ids)
            conn.execute(f"DELETE FROM wechat_articles WHERE id IN ({placeholders})", demo_article_ids)
        conn.commit()


def refresh_expired_statuses(today: str | None = None) -> int:
    cutoff = today or date.today().isoformat()
    with get_connection() as conn:
        campaigns = conn.execute(
            "UPDATE campaigns SET status='closed', updated_at=? WHERE deadline IS NOT NULL AND deadline < ? AND status IN ('open','closing_soon')",
            (now_iso(), cutoff),
        ).rowcount
        jobs = conn.execute(
            """
            UPDATE jobs SET status='closed', updated_at=?
            WHERE status IN ('open','closing_soon') AND campaign_id IN (
                SELECT id FROM campaigns WHERE deadline IS NOT NULL AND deadline < ?
            )
            """,
            (now_iso(), cutoff),
        ).rowcount
        conn.commit()
    return int(campaigns or 0) + int(jobs or 0)


def refresh_job_families() -> int:
    """Reclassify jobs after rule improvements without erasing useful manual labels."""
    changed = 0
    with get_connection() as conn:
        rows = conn.execute("SELECT id, title, description, job_family FROM jobs").fetchall()
        for row in rows:
            current = row["job_family"] or "unknown"
            inferred = infer_job_family(row["title"] or "", row["description"] or "")
            if inferred != "unknown":
                updated = inferred
            elif current in {"产品", "金融"}:
                # These two labels previously used overly broad words ("产品" and "研究").
                updated = "unknown"
            else:
                updated = current
            if updated != current:
                conn.execute(
                    "UPDATE jobs SET job_family=?, updated_at=? WHERE id=?",
                    (updated, now_iso(), int(row["id"])),
                )
                changed += 1
        conn.commit()
    return changed


def get_company_id_by_name(conn: Any, name: str) -> int | None:
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def upsert_company(conn: Any, company: dict[str, Any]) -> int:
    existing = get_company_id_by_name(conn, company["name"])
    ts = now_iso()
    if existing:
        conn.execute(
            """UPDATE companies SET aliases_json=?, company_type=?, industry=?, official_site=?, recruit_site=?, source_level=?, updated_at=? WHERE id=?""",
            (
                dumps_json(company.get("aliases", [])),
                company.get("company_type", "unknown"),
                company.get("industry", "unknown"),
                company.get("official_site"),
                company.get("recruit_site"),
                company.get("source_level", "C"),
                ts,
                existing,
            ),
        )
        return existing
    cur = conn.execute(
        """INSERT INTO companies (name, aliases_json, company_type, industry, official_site, recruit_site, source_level, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company["name"],
            dumps_json(company.get("aliases", [])),
            company.get("company_type", "unknown"),
            company.get("industry", "unknown"),
            company.get("official_site"),
            company.get("recruit_site"),
            company.get("source_level", "C"),
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid)


def insert_campaign(conn: Any, company_id: int, campaign: dict[str, Any]) -> int:
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO campaigns (
            company_id, name, recruitment_type, target_cohort, status, start_date, deadline,
            domestic_grad_start, domestic_grad_end, overseas_grad_start, overseas_grad_end,
            accepts_overseas, degree_min, cities_json, job_families_json, majors_json,
            application_rules, apply_url, source_url, source_level, source_published_at,
            last_verified_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            campaign.get("name", "未知招聘项目"),
            campaign.get("recruitment_type", "unknown"),
            campaign.get("target_cohort"),
            campaign.get("status", "pending_review"),
            campaign.get("start_date"),
            campaign.get("deadline"),
            campaign.get("domestic_grad_start"),
            campaign.get("domestic_grad_end"),
            campaign.get("overseas_grad_start"),
            campaign.get("overseas_grad_end"),
            _bool_to_db(campaign.get("accepts_overseas")),
            campaign.get("degree_min", "bachelor"),
            dumps_json(campaign.get("cities", [])),
            dumps_json(campaign.get("job_families", [])),
            dumps_json(campaign.get("majors", [])),
            campaign.get("application_rules"),
            campaign.get("apply_url"),
            campaign.get("source_url"),
            campaign.get("source_level", "C"),
            campaign.get("source_published_at"),
            ts,
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid)


def insert_job(conn: Any, company_id: int, campaign_id: int, job: dict[str, Any]) -> int:
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO jobs (
            company_id, campaign_id, title, job_family, cities_json, degree_min, majors_json,
            description, apply_url, status, source_url, source_level, quality_score, risk_level,
            last_verified_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            campaign_id,
            job.get("title", "待命名岗位"),
            job.get("job_family", "unknown"),
            dumps_json(job.get("cities", [])),
            job.get("degree_min", "bachelor"),
            dumps_json(job.get("majors", [])),
            job.get("description"),
            job.get("apply_url"),
            job.get("status", "open"),
            job.get("source_url"),
            job.get("source_level", "C"),
            float(job.get("quality_score", 0.5)),
            job.get("risk_level", "unknown"),
            ts,
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid)


def insert_process_rule(conn: Any, campaign_id: int | None, job_id: int | None, rule: dict[str, Any]) -> int:
    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO process_rules (campaign_id, job_id, written_test_status, written_test_burden, process_text, confidence, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            campaign_id,
            job_id,
            rule.get("written_test_status", "unknown"),
            int(rule.get("written_test_burden", 5)),
            rule.get("process_text"),
            float(rule.get("confidence", 0.2)),
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid)


def insert_evidence(conn: Any, entity_type: str, entity_id: int, field_name: str, value_text: str | None, evidence_text: str, source_url: str | None, confidence: float) -> int:
    cur = conn.execute(
        """INSERT INTO evidence (entity_type, entity_id, field_name, value_text, evidence_text, source_url, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (entity_type, entity_id, field_name, value_text, evidence_text, source_url, float(confidence), now_iso()),
    )
    return int(cur.lastrowid)


def insert_signal(conn: Any, company_id: int | None, campaign_id: int | None, signal: dict[str, Any]) -> int:
    cur = conn.execute(
        """INSERT INTO signals (company_id, campaign_id, signal_type, title, description, source_url, source_level, status, detected_at, evidence_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company_id,
            campaign_id,
            signal.get("signal_type", "notice_imported"),
            signal.get("title", "新招聘信号"),
            signal.get("description"),
            signal.get("source_url"),
            signal.get("source_level", "C"),
            signal.get("status", "unverified"),
            signal.get("detected_at", now_iso()),
            signal.get("evidence_text"),
        ),
    )
    return int(cur.lastrowid)


def _bool_to_db(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _db_to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _status_for_deadline(deadline: str | None, requested: str = "open") -> str:
    if deadline and str(deadline)[:10] < date.today().isoformat():
        return "closed"
    return requested


def _campaign_signature(value: str) -> str:
    value = re.sub(r"^[【\[].*?[】\]]\s*", "", (value or "").lower())
    compact = re.sub(r"[\s【】\[\]（）()，,。.!！:：·|_-]+", "", value)
    return compact.replace("正式", "")


def hydrate_job(row: Any) -> dict[str, Any]:
    data = row_to_dict(row)
    if not data:
        return {}
    job = {
        "id": data["job_id"],
        "title": data["title"],
        "job_family": data["job_family"],
        "cities": loads_json(data.get("cities_json"), []),
        "degree_min": data["job_degree_min"],
        "majors": loads_json(data.get("majors_json"), []),
        "description": data.get("description"),
        "apply_url": data.get("job_apply_url") or data.get("campaign_apply_url"),
        "status": data["job_status"],
        "source_url": data.get("job_source_url") or data.get("campaign_source_url"),
        "source_level": data.get("job_source_level") or data.get("campaign_source_level"),
        "quality_score": data.get("quality_score"),
        "risk_level": data.get("risk_level"),
        "last_verified_at": data.get("job_last_verified_at"),
        "company": {
            "id": data["company_id"],
            "name": data["company_name"],
            "company_type": data["company_type"],
            "industry": data["industry"],
            "source_level": data["company_source_level"],
        },
        "campaign": {
            "id": data["campaign_id"],
            "name": data["campaign_name"],
            "recruitment_type": data["recruitment_type"],
            "target_cohort": data.get("target_cohort"),
            "status": data["campaign_status"],
            "deadline": data.get("deadline"),
            "domestic_grad_start": data.get("domestic_grad_start"),
            "domestic_grad_end": data.get("domestic_grad_end"),
            "overseas_grad_start": data.get("overseas_grad_start"),
            "overseas_grad_end": data.get("overseas_grad_end"),
            "accepts_overseas": _db_to_bool(data.get("accepts_overseas")),
            "degree_min": data.get("campaign_degree_min"),
            "apply_url": data.get("campaign_apply_url"),
            "source_url": data.get("campaign_source_url"),
            "source_level": data.get("campaign_source_level"),
        },
        "process_rule": {
            "written_test_status": data.get("written_test_status") or "unknown",
            "written_test_burden": data.get("written_test_burden") if data.get("written_test_burden") is not None else 5,
            "process_text": data.get("process_text"),
            "confidence": data.get("process_confidence") if data.get("process_confidence") is not None else 0.2,
        },
    }
    return job


def _base_job_query() -> str:
    return """
        SELECT
            j.id AS job_id, j.title, j.job_family, j.cities_json, j.degree_min AS job_degree_min,
            j.majors_json, j.description, j.apply_url AS job_apply_url, j.status AS job_status,
            j.source_url AS job_source_url, j.source_level AS job_source_level, j.quality_score,
            j.risk_level, j.last_verified_at AS job_last_verified_at,
            c.id AS company_id, c.name AS company_name, c.company_type, c.industry, c.source_level AS company_source_level,
            ca.id AS campaign_id, ca.name AS campaign_name, ca.recruitment_type, ca.target_cohort,
            ca.status AS campaign_status, ca.deadline, ca.domestic_grad_start, ca.domestic_grad_end,
            ca.overseas_grad_start, ca.overseas_grad_end, ca.accepts_overseas,
            ca.degree_min AS campaign_degree_min, ca.apply_url AS campaign_apply_url,
            ca.source_url AS campaign_source_url, ca.source_level AS campaign_source_level,
            pr.written_test_status, pr.written_test_burden, pr.process_text, pr.confidence AS process_confidence
        FROM jobs j
        JOIN companies c ON j.company_id = c.id
        JOIN campaigns ca ON j.campaign_id = ca.id
        LEFT JOIN process_rules pr ON pr.campaign_id = ca.id AND pr.job_id IS NULL
    """


def _expand_job_query_terms(query: str) -> list[str]:
    terms = [query]
    compact = "".join(str(query).split()).lower()
    energy_aliases = ["中国能源集团", "国家能源集团", "国家能源投资集团", "国能集团", "国能"]
    if any(alias.lower() in compact for alias in ["中国能源集团", "国家能源集团", "国家能源投资集团", "国能集团"]):
        terms.extend(energy_aliases)
    deduped: list[str] = []
    for term in terms:
        if term and term not in deduped:
            deduped.append(term)
    return deduped


def list_jobs(filters: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_seed_data()
    clauses = ["1=1"]
    params: list[Any] = []
    query = filters.get("query")
    if query:
        query_clauses = []
        for term in _expand_job_query_terms(str(query)):
            like = f"%{term}%"
            query_clauses.append("(j.title LIKE ? OR c.name LIKE ? OR j.description LIKE ? OR ca.name LIKE ?)")
            params.extend([like, like, like, like])
        clauses.append("(" + " OR ".join(query_clauses) + ")")
    city = filters.get("city")
    if city:
        clauses.append("j.cities_json LIKE ?")
        params.append(f"%{city}%")
    cohort = filters.get("cohort")
    if cohort:
        if not str(cohort).endswith("届"):
            cohort = f"{cohort}届"
        clauses.append("ca.target_cohort = ?")
        params.append(cohort)
    accepts_overseas = filters.get("accepts_overseas")
    if accepts_overseas is not None:
        clauses.append("ca.accepts_overseas = ?")
        params.append(1 if coerce_bool(accepts_overseas) else 0)
    max_written_burden = filters.get("max_written_test_burden")
    if max_written_burden is not None:
        clauses.append("COALESCE(pr.written_test_burden, 5) <= ?")
        params.append(int(max_written_burden))
    if coerce_bool(filters.get("only_open"), default=True):
        clauses.append("j.status IN ('open', 'closing_soon')")
        clauses.append("(ca.deadline IS NULL OR date(ca.deadline) >= date('now'))")
    sql = _base_job_query() + " WHERE " + " AND ".join(clauses) + " ORDER BY ca.deadline IS NULL, ca.deadline ASC, j.quality_score DESC LIMIT ?"
    params.append(int(filters.get("limit", 100)))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [hydrate_job(row) for row in rows]


def get_job(job_id: int) -> dict[str, Any] | None:
    ensure_seed_data()
    sql = _base_job_query() + " WHERE j.id = ?"
    with get_connection() as conn:
        row = conn.execute(sql, (job_id,)).fetchone()
        if not row:
            return None
        job = hydrate_job(row)
        evidence_rows = conn.execute(
            "SELECT field_name, value_text, evidence_text, source_url, confidence, created_at FROM evidence WHERE entity_type IN ('campaign', 'job') AND entity_id IN (?, ?) ORDER BY created_at DESC",
            (job["campaign"]["id"], job["id"]),
        ).fetchall()
        job["evidence"] = [row_to_dict(r) for r in evidence_rows]
        change_rows = conn.execute(
            "SELECT field_name, old_value, new_value, detected_at, source_url FROM change_events WHERE entity_type='campaign' AND entity_id=? ORDER BY detected_at DESC LIMIT 20",
            (job["campaign"]["id"],),
        ).fetchall()
        job["changes"] = [row_to_dict(r) for r in change_rows]
        return job


def import_discovered_campaign(item: dict[str, Any]) -> dict[str, int]:
    ensure_seed_data()
    with get_connection() as conn:
        company_id = upsert_company(conn, {
            "name": item.get("company_name") or "未知公司",
            "aliases": item.get("company_aliases", []),
            "company_type": item.get("company_type", "unknown"),
            "industry": item.get("industry", "unknown"),
            "official_site": item.get("official_site"),
            "recruit_site": item.get("recruit_site") or item.get("apply_url"),
            "source_level": item.get("company_source_level", item.get("source_level", "B")),
        })
        campaign_name = item.get("campaign_name") or item.get("title") or "招聘公告"
        cohort = item.get("target_cohort")
        source_url = item.get("source_url")
        existing = None
        if source_url:
            existing = conn.execute(
                "SELECT id FROM campaigns WHERE company_id=? AND source_url=? ORDER BY id DESC LIMIT 1",
                (company_id, source_url),
            ).fetchone()
        if not existing:
            existing = conn.execute(
                """SELECT id FROM campaigns WHERE company_id=? AND name=?
                AND COALESCE(target_cohort, '')=COALESCE(?, '') ORDER BY id DESC LIMIT 1""",
                (company_id, campaign_name, cohort),
            ).fetchone()
        if not existing:
            signature = _campaign_signature(campaign_name)
            comparable = conn.execute(
                """SELECT id, name FROM campaigns WHERE company_id=?
                AND COALESCE(target_cohort, '')=COALESCE(?, '')""",
                (company_id, cohort),
            ).fetchall()
            existing = next((row for row in comparable if _campaign_signature(row["name"]) == signature), None)
        if not existing and source_url and "news.google.com/" in source_url:
            existing = conn.execute(
                """
                SELECT id FROM campaigns WHERE company_id=?
                AND COALESCE(target_cohort, '')=COALESCE(?, '')
                AND recruitment_type=? AND source_url LIKE 'https://news.google.com/%'
                ORDER BY updated_at DESC LIMIT 1
                """,
                (company_id, cohort, item.get("recruitment_type", "校招")),
            ).fetchone()
        if not existing and source_url and "news.google.com/" in source_url:
            existing = conn.execute(
                """
                SELECT id FROM campaigns WHERE company_id=? AND recruitment_type=?
                AND source_url LIKE 'https://news.google.com/%'
                AND (target_cohort IS NULL OR ? IS NULL)
                ORDER BY target_cohort IS NOT NULL DESC, updated_at DESC LIMIT 1
                """,
                (company_id, item.get("recruitment_type", "校招"), cohort),
            ).fetchone()
        existing_campaign = None
        if existing:
            existing_campaign = conn.execute(
                """SELECT name, target_cohort, degree_min, cities_json,
                    job_families_json, majors_json FROM campaigns WHERE id=?""",
                (int(existing["id"]),),
            ).fetchone()
            if existing_campaign and re.search(r"20\d{2}\s*届", existing_campaign["name"] or "") and not re.search(r"20\d{2}\s*届", campaign_name):
                campaign_name = existing_campaign["name"]
        status = _status_for_deadline(item.get("deadline"), item.get("status", "pending_review"))
        campaign_data = {
            "name": campaign_name,
            "recruitment_type": item.get("recruitment_type", "校招"),
            "target_cohort": cohort,
            "status": status,
            "start_date": item.get("start_date"),
            "deadline": item.get("deadline"),
            "accepts_overseas": item.get("accepts_overseas"),
            "degree_min": item.get("degree_min", "unknown"),
            "cities": item.get("cities", []),
            "job_families": item.get("job_families", []),
            "majors": item.get("majors", []),
            "apply_url": item.get("apply_url"),
            "source_url": source_url,
            "source_level": item.get("source_level", "B"),
            "source_published_at": item.get("source_published_at"),
        }
        if existing_campaign:
            for key, column in (
                ("cities", "cities_json"),
                ("job_families", "job_families_json"),
                ("majors", "majors_json"),
            ):
                previous_values = loads_json(existing_campaign[column], [])
                campaign_data[key] = list(dict.fromkeys([*previous_values, *campaign_data[key]]))
            if campaign_data["degree_min"] == "unknown":
                campaign_data["degree_min"] = existing_campaign["degree_min"] or "unknown"
        ts = now_iso()
        if existing:
            campaign_id = int(existing["id"])
            conn.execute(
                """
                UPDATE campaigns SET name=?, recruitment_type=?, target_cohort=COALESCE(?, target_cohort),
                    status=?, start_date=COALESCE(?, start_date), deadline=COALESCE(?, deadline),
                    degree_min=?, cities_json=?, job_families_json=?, majors_json=?,
                    apply_url=COALESCE(?, apply_url), source_url=COALESCE(?, source_url),
                    source_level=?, source_published_at=COALESCE(?, source_published_at),
                    last_verified_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    campaign_name,
                    campaign_data["recruitment_type"],
                    cohort,
                    status,
                    campaign_data["start_date"],
                    campaign_data["deadline"],
                    campaign_data["degree_min"],
                    dumps_json(campaign_data["cities"]),
                    dumps_json(campaign_data["job_families"]),
                    dumps_json(campaign_data["majors"]),
                    campaign_data["apply_url"],
                    source_url,
                    campaign_data["source_level"],
                    campaign_data["source_published_at"],
                    ts,
                    ts,
                    campaign_id,
                ),
            )
        else:
            campaign_id = insert_campaign(conn, company_id, campaign_data)
        evidence_text = item.get("evidence_text") or campaign_name
        existing_evidence = conn.execute(
            "SELECT id FROM evidence WHERE entity_type='campaign' AND entity_id=? AND field_name='announcement' AND COALESCE(source_url, '')=COALESCE(?, '') LIMIT 1",
            (campaign_id, source_url),
        ).fetchone()
        if not existing_evidence:
            insert_evidence(
                conn,
                "campaign",
                campaign_id,
                "announcement",
                campaign_name,
                evidence_text,
                source_url,
                float(item.get("confidence", 0.75)),
            )
        signal = conn.execute(
            "SELECT id FROM signals WHERE signal_type='recruitment_announcement' AND source_url=? LIMIT 1",
            (source_url,),
        ).fetchone() if source_url else None
        if signal:
            signal_id = int(signal["id"])
            conn.execute(
                "UPDATE signals SET company_id=?, campaign_id=?, title=?, description=?, source_level=?, status=?, detected_at=?, evidence_text=? WHERE id=?",
                (
                    company_id,
                    campaign_id,
                    campaign_name,
                    item.get("description"),
                    campaign_data["source_level"],
                    status,
                    ts,
                    evidence_text,
                    signal_id,
                ),
            )
        else:
            signal_id = insert_signal(conn, company_id, campaign_id, {
                "signal_type": "recruitment_announcement",
                "title": campaign_name,
                "description": item.get("description"),
                "source_url": source_url,
                "source_level": campaign_data["source_level"],
                "status": status,
                "detected_at": ts,
                "evidence_text": evidence_text,
            })
        conn.commit()
        return {"company_id": company_id, "campaign_id": campaign_id, "signal_id": signal_id}


def _current_campus_year() -> int:
    today = date.today()
    return today.year + 1 if today.month >= 6 else today.year


def _expand_opportunity_query_terms(query: str) -> list[str]:
    query = (query or "").strip()
    terms = [query, *[part for part in query.replace("，", " ").split() if part]]
    compact = "".join(query.split()).lower()
    if "秋招" in compact:
        terms.extend(["秋招", "校园招聘", "校招", "提前批", "高校毕业生", f"{_current_campus_year()}届"])
    if "春招" in compact:
        terms.extend(["春招", "春季招聘", "校园招聘", "高校毕业生"])
    if "实习" in compact:
        terms.extend(["实习", "暑期实习", "实习生"])
    if "央企" in compact or "国企" in compact:
        terms.extend(["央企", "国企", "国资", "中央企业"])
    deduped: list[str] = []
    for term in terms:
        normalized = term.strip().lower()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def list_opportunities(filters: dict[str, Any]) -> dict[str, Any]:
    ensure_seed_data()
    with get_connection() as conn:
        job_rows = conn.execute(
            """
            SELECT 'job' AS record_type, j.id AS record_id, j.id AS job_id, ca.id AS campaign_id,
                j.title, ca.name AS campaign_name, c.name AS company_name, c.company_type, c.industry,
                CASE WHEN j.cities_json='[]' THEN ca.cities_json ELSE j.cities_json END AS cities_json,
                j.degree_min, j.job_family, ca.job_families_json, j.majors_json,
                ca.recruitment_type, ca.target_cohort, ca.deadline,
                ca.accepts_overseas, j.status AS job_status, ca.status AS campaign_status,
                COALESCE(j.apply_url, ca.apply_url) AS apply_url,
                COALESCE(j.source_url, ca.source_url) AS source_url,
                COALESCE(j.source_level, ca.source_level) AS source_level,
                j.quality_score, j.risk_level, COALESCE(ca.source_published_at, j.updated_at) AS updated_at,
                ca.source_published_at,
                pr.written_test_status, pr.written_test_burden
            FROM jobs j
            JOIN campaigns ca ON ca.id=j.campaign_id
            JOIN companies c ON c.id=j.company_id
            LEFT JOIN process_rules pr ON pr.campaign_id=ca.id AND pr.job_id IS NULL
            """
        ).fetchall()
        campaign_rows = conn.execute(
            """
            SELECT 'campaign' AS record_type, ca.id AS record_id, NULL AS job_id, ca.id AS campaign_id,
                ca.name AS title, ca.name AS campaign_name, c.name AS company_name, c.company_type, c.industry,
                ca.cities_json, ca.degree_min, 'unknown' AS job_family, ca.job_families_json,
                ca.majors_json, ca.recruitment_type, ca.target_cohort, ca.deadline,
                ca.accepts_overseas, ca.status AS job_status, ca.status AS campaign_status,
                ca.apply_url, ca.source_url, ca.source_level, 0.68 AS quality_score,
                'campaign_only' AS risk_level, COALESCE(ca.source_published_at, ca.updated_at) AS updated_at,
                ca.source_published_at,
                'unknown' AS written_test_status, 5 AS written_test_burden
            FROM campaigns ca
            JOIN companies c ON c.id=ca.company_id
            WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.campaign_id=ca.id)
            """
        ).fetchall()
        tracker_rows = conn.execute(
            """SELECT record_type, record_id, status, is_favorite, note,
                applied_at, next_action_at, created_at, updated_at
            FROM application_tracker"""
        ).fetchall()
    tracker = {
        (row["record_type"], int(row["record_id"])): row_to_dict(row)
        for row in tracker_rows
    }
    today = date.today().isoformat()
    items: list[dict[str, Any]] = []
    for row in [*job_rows, *campaign_rows]:
        data = dict(row)
        deadline = data.get("deadline")
        status = data.get("job_status") or data.get("campaign_status") or "pending_review"
        if deadline and str(deadline)[:10] < today:
            status = "closed"
        elif status == "open" and not deadline and not data.get("target_cohort"):
            status = "pending_review"
        source_url = data.get("source_url") or ""
        tracker_item = tracker.get((data["record_type"], int(data["record_id"])), {})
        job_families = loads_json(data.get("job_families_json"), [])
        if data.get("job_family") and data["job_family"] != "unknown" and data["job_family"] not in job_families:
            job_families.insert(0, data["job_family"])
        items.append({
            "id": f"{data['record_type']}-{data['record_id']}",
            "record_type": data["record_type"],
            "job_id": data.get("job_id"),
            "campaign_id": data.get("campaign_id"),
            "updated_at": data.get("updated_at"),
            "company_name": data.get("company_name") or "未知公司",
            "company_type": data.get("company_type") or "unknown",
            "industry": data.get("industry") or "unknown",
            "title": data.get("title") or "待确认招聘项目",
            "campaign_name": data.get("campaign_name") or "",
            "recruitment_type": data.get("recruitment_type") or "unknown",
            "target_cohort": data.get("target_cohort"),
            "cities": loads_json(data.get("cities_json"), []),
            "job_families": job_families,
            "majors": loads_json(data.get("majors_json"), []),
            "degree_min": data.get("degree_min"),
            "deadline": deadline,
            "accepts_overseas": _db_to_bool(data.get("accepts_overseas")),
            "status": status,
            "apply_url": data.get("apply_url"),
            "source_url": source_url or None,
            "source_domain": urlparse(source_url).netloc.lower().removeprefix("www."),
            "source_level": data.get("source_level") or "C",
            "quality_score": float(data.get("quality_score") or 0),
            "risk_level": data.get("risk_level") or "unknown",
            "source_published_at": data.get("source_published_at"),
            "written_test_status": data.get("written_test_status") or "unknown",
            "written_test_burden": int(data.get("written_test_burden") if data.get("written_test_burden") is not None else 5),
            "tracker_status": tracker_item.get("status"),
            "is_favorite": bool(tracker_item.get("is_favorite")),
            "tracker_note": tracker_item.get("note") or "",
            "applied_at": tracker_item.get("applied_at"),
            "next_action_at": tracker_item.get("next_action_at"),
            "tracker_updated_at": tracker_item.get("updated_at"),
        })
    query = str(filters.get("query") or "").strip()
    if query:
        terms = _expand_opportunity_query_terms(query)
        items = [
            item for item in items
            if any(term in " ".join([
                item["company_name"], item["company_type"], item["industry"], item["title"],
                item["campaign_name"], item["recruitment_type"], item.get("target_cohort") or "",
                " ".join(item["cities"]), " ".join(item["job_families"]), " ".join(item["majors"]),
            ]).lower() for term in terms)
        ]
    city = str(filters.get("city") or "").strip()
    if city:
        items = [item for item in items if any(city in value for value in item["cities"])]
    cohort = str(filters.get("cohort") or "").strip()
    if cohort:
        normalized_cohort = cohort if cohort.endswith("届") else f"{cohort}届"
        items = [item for item in items if item.get("target_cohort") == normalized_cohort]
    recruitment_type = str(filters.get("recruitment_type") or "").strip()
    if recruitment_type:
        items = [item for item in items if recruitment_type in item["recruitment_type"] or recruitment_type in item["campaign_name"]]
    company_type = str(filters.get("company_type") or "").strip()
    if company_type == "国央企":
        items = [item for item in items if item["company_type"] in {"央企", "国企", "政府"} or "国企" in item["industry"] or "央企" in item["industry"]]
    elif company_type:
        items = [item for item in items if company_type in item["company_type"]]
    industry = str(filters.get("industry") or "").strip()
    if industry:
        items = [item for item in items if industry in item["industry"]]
    job_family = str(filters.get("job_family") or "").strip()
    if job_family:
        items = [item for item in items if any(job_family in value for value in item["job_families"]) or job_family in item["title"]]
    major = str(filters.get("major") or "").strip()
    if major:
        items = [item for item in items if not item["majors"] or any(major in value for value in item["majors"])]
    source_level = str(filters.get("source_level") or "").strip()
    if source_level:
        ranks = {"S": 4, "A": 3, "B": 2, "C": 1, "D": 0}
        items = [item for item in items if ranks.get(item["source_level"], 0) >= ranks.get(source_level, 0)]
    if not coerce_bool(filters.get("include_expired")):
        items = [item for item in items if item["status"] not in {"closed", "expired"}]
    freshness_days = int(filters.get("freshness_days") or 0)
    if freshness_days > 0:
        cutoff = (date.today() - timedelta(days=freshness_days)).isoformat()
        items = [item for item in items if not item.get("updated_at") or str(item["updated_at"])[:10] >= cutoff]
    tracker_status = str(filters.get("tracker_status") or "").strip()
    if tracker_status:
        items = [item for item in items if item.get("tracker_status") == tracker_status]
    elif coerce_bool(filters.get("tracked_only")):
        items = [item for item in items if item.get("tracker_status") or item.get("is_favorite")]
    items.sort(key=lambda item: (item.get("updated_at") or "", item.get("quality_score") or 0), reverse=True)
    total = len(items)
    offset = max(0, int(filters.get("offset") or 0))
    limit = min(500, max(1, int(filters.get("limit") or 200)))
    page = items[offset:offset + limit]
    return {
        "items": page,
        "count": total,
        "job_count": len([item for item in items if item["record_type"] == "job"]),
        "campaign_count": len([item for item in items if item["record_type"] == "campaign"]),
        "offset": offset,
        "limit": limit,
    }


TRACKER_STATUSES = {"saved", "preparing", "applied", "assessment", "interview", "offer", "rejected", "withdrawn"}
ACTIVE_APPLICATION_STATUSES = {"applied", "assessment", "interview", "offer", "rejected", "withdrawn"}


def save_tracker(
    record_type: str,
    record_id: int,
    status: str,
    note: str = "",
    is_favorite: bool = False,
    next_action_at: str | None = None,
) -> dict[str, Any]:
    ensure_seed_data()
    if record_type not in {"job", "campaign"}:
        raise ValueError("record_type must be job or campaign")
    if status not in TRACKER_STATUSES:
        raise ValueError("invalid tracker status")
    table = "jobs" if record_type == "job" else "campaigns"
    ts = now_iso()
    with get_connection() as conn:
        exists = conn.execute(f"SELECT id FROM {table} WHERE id=?", (record_id,)).fetchone()
        if not exists:
            raise LookupError("opportunity not found")
        previous = conn.execute(
            "SELECT applied_at, created_at FROM application_tracker WHERE record_type=? AND record_id=?",
            (record_type, record_id),
        ).fetchone()
        applied_at = previous["applied_at"] if previous else None
        if status in ACTIVE_APPLICATION_STATUSES and not applied_at:
            applied_at = ts
        created_at = previous["created_at"] if previous else ts
        conn.execute(
            """
            INSERT INTO application_tracker(
                record_type, record_id, status, is_favorite, note,
                applied_at, next_action_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_type, record_id) DO UPDATE SET
                status=excluded.status, is_favorite=excluded.is_favorite,
                note=excluded.note, applied_at=excluded.applied_at,
                next_action_at=excluded.next_action_at, updated_at=excluded.updated_at
            """,
            (
                record_type,
                record_id,
                status,
                int(is_favorite),
                note.strip()[:2000],
                applied_at,
                next_action_at,
                created_at,
                ts,
            ),
        )
        row = conn.execute(
            """SELECT record_type, record_id, status, is_favorite, note,
                applied_at, next_action_at, created_at, updated_at
            FROM application_tracker WHERE record_type=? AND record_id=?""",
            (record_type, record_id),
        ).fetchone()
        conn.commit()
    result = row_to_dict(row)
    result["is_favorite"] = bool(result.get("is_favorite"))
    return result


def remove_tracker(record_type: str, record_id: int) -> bool:
    ensure_seed_data()
    if record_type not in {"job", "campaign"}:
        raise ValueError("record_type must be job or campaign")
    with get_connection() as conn:
        deleted = conn.execute(
            "DELETE FROM application_tracker WHERE record_type=? AND record_id=?",
            (record_type, record_id),
        ).rowcount
        conn.commit()
    return bool(deleted)


def list_signals(limit: int = 50) -> list[dict[str, Any]]:
    ensure_seed_data()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT s.*, c.name AS company_name FROM signals s LEFT JOIN companies c ON s.company_id = c.id ORDER BY s.detected_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_changes(limit: int = 50) -> list[dict[str, Any]]:
    ensure_seed_data()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM change_events ORDER BY detected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def import_notice(extracted: ExtractedNotice) -> dict[str, Any]:
    ensure_seed_data()
    with get_connection() as conn:
        company_id = upsert_company(conn, {
            "name": extracted.company_name,
            "aliases": [],
            "company_type": "unknown",
            "industry": "unknown",
            "official_site": None,
            "recruit_site": None,
            "source_level": extracted.source_level,
        })
        existing_campaign = conn.execute(
            """SELECT * FROM campaigns WHERE company_id=? AND name=? AND COALESCE(target_cohort, '')=COALESCE(?, '') ORDER BY id DESC LIMIT 1""",
            (company_id, extracted.campaign_name, extracted.target_cohort),
        ).fetchone()
        campaign_data = {
            "name": extracted.campaign_name,
            "recruitment_type": extracted.recruitment_type,
            "target_cohort": extracted.target_cohort,
            "status": "pending_review",
            "deadline": extracted.deadline,
            "domestic_grad_start": extracted.domestic_grad_start,
            "domestic_grad_end": extracted.domestic_grad_end,
            "overseas_grad_start": extracted.overseas_grad_start,
            "overseas_grad_end": extracted.overseas_grad_end,
            "accepts_overseas": extracted.accepts_overseas,
            "degree_min": extracted.degree_min,
            "apply_url": extracted.apply_url or extracted.source_url,
            "source_url": extracted.source_url,
            "source_level": extracted.source_level,
        }
        if existing_campaign:
            campaign_id = int(existing_campaign["id"])
            old = row_to_dict(existing_campaign)
            changes = detect_changes(old, {
                **campaign_data,
                "accepts_overseas": _bool_to_db(campaign_data.get("accepts_overseas")),
            }, [
                "deadline", "domestic_grad_start", "domestic_grad_end", "overseas_grad_start", "overseas_grad_end", "accepts_overseas", "apply_url", "source_url"
            ])
            ts = now_iso()
            conn.execute(
                """UPDATE campaigns SET recruitment_type=?, deadline=?, domestic_grad_start=?, domestic_grad_end=?, overseas_grad_start=?, overseas_grad_end=?, accepts_overseas=?, degree_min=?, apply_url=?, source_url=?, source_level=?, last_verified_at=?, updated_at=? WHERE id=?""",
                (
                    campaign_data["recruitment_type"], campaign_data["deadline"], campaign_data["domestic_grad_start"], campaign_data["domestic_grad_end"],
                    campaign_data["overseas_grad_start"], campaign_data["overseas_grad_end"], _bool_to_db(campaign_data["accepts_overseas"]), campaign_data["degree_min"],
                    campaign_data["apply_url"], campaign_data["source_url"], campaign_data["source_level"], ts, ts, campaign_id,
                ),
            )
            for change in changes:
                conn.execute(
                    """INSERT INTO change_events (entity_type, entity_id, field_name, old_value, new_value, detected_at, source_url) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    ("campaign", campaign_id, change["field_name"], change["old_value"], change["new_value"], ts, extracted.source_url),
                )
        else:
            campaign_id = insert_campaign(conn, company_id, campaign_data)
            changes = []
        insert_process_rule(conn, campaign_id, None, {
            "written_test_status": extracted.written_test_status,
            "written_test_burden": extracted.written_test_burden,
            "process_text": extracted.written_test_evidence,
            "confidence": extracted.written_test_confidence,
        })
        job_id = insert_job(conn, company_id, campaign_id, {
            "title": extracted.job_title,
            "job_family": extracted.job_family,
            "cities": extracted.cities,
            "degree_min": extracted.degree_min,
            "majors": [],
            "description": "由公告文本导入生成，需人工复核。",
            "apply_url": extracted.apply_url or extracted.source_url,
            "source_url": extracted.source_url,
            "source_level": extracted.source_level,
            "status": "pending_review",
            "quality_score": 0.55,
            "risk_level": "unknown",
        })
        for field_name, field in extracted.evidence.items():
            insert_evidence(conn, "campaign", campaign_id, field_name, str(field.value), field.evidence, extracted.source_url, field.confidence)
        insert_signal(conn, company_id, campaign_id, {
            "signal_type": "notice_imported",
            "title": f"导入公告：{extracted.company_name} {extracted.campaign_name}",
            "description": "通过后台文本导入生成的新招聘信号，默认待复核。",
            "source_url": extracted.source_url,
            "source_level": extracted.source_level,
            "status": "pending_review",
            "evidence_text": extracted.written_test_evidence or next(iter(extracted.evidence.values())).evidence if extracted.evidence else None,
        })
        conn.commit()
        return {"company_id": company_id, "campaign_id": campaign_id, "job_id": job_id, "changes": changes}


def import_scraped_job(job: dict[str, Any]) -> dict[str, Any]:
    ensure_seed_data()
    with get_connection() as conn:
        company_id = upsert_company(conn, {
            "name": job.get("company_name") or "未知公司",
            "aliases": job.get("company_aliases", []),
            "company_type": job.get("company_type", "unknown"),
            "industry": job.get("industry", "unknown"),
            "official_site": job.get("official_site"),
            "recruit_site": job.get("recruit_site"),
            "source_level": job.get("source_level", "A"),
        })
        campaign_name = job.get("campaign_name") or "自动搜索招聘项目"
        target_cohort = job.get("target_cohort")
        existing_campaign = conn.execute(
            """SELECT * FROM campaigns WHERE company_id=? AND name=? AND COALESCE(target_cohort, '')=COALESCE(?, '') ORDER BY id DESC LIMIT 1""",
            (company_id, campaign_name, target_cohort),
        ).fetchone()
        campaign_data = {
            "name": campaign_name,
            "recruitment_type": job.get("recruitment_type", "校招"),
            "target_cohort": target_cohort,
            "status": _status_for_deadline(job.get("deadline")),
            "deadline": job.get("deadline"),
            "domestic_grad_start": job.get("domestic_grad_start"),
            "domestic_grad_end": job.get("domestic_grad_end"),
            "overseas_grad_start": job.get("overseas_grad_start"),
            "overseas_grad_end": job.get("overseas_grad_end"),
            "accepts_overseas": job.get("accepts_overseas"),
            "degree_min": job.get("degree_min", "bachelor"),
            "apply_url": job.get("apply_url") or job.get("source_url"),
            "source_url": job.get("source_url"),
            "source_level": job.get("source_level", "A"),
        }
        ts = now_iso()
        if existing_campaign:
            campaign_id = int(existing_campaign["id"])
            conn.execute(
                """UPDATE campaigns SET recruitment_type=?, status=?, deadline=COALESCE(?, deadline), degree_min=?, apply_url=?, source_url=?, source_level=?, last_verified_at=?, updated_at=? WHERE id=?""",
                (
                    campaign_data["recruitment_type"],
                    campaign_data["status"],
                    campaign_data["deadline"],
                    campaign_data["degree_min"],
                    campaign_data["apply_url"],
                    campaign_data["source_url"],
                    campaign_data["source_level"],
                    ts,
                    ts,
                    campaign_id,
                ),
            )
        else:
            campaign_id = insert_campaign(conn, company_id, campaign_data)
        existing_rule = conn.execute(
            "SELECT id FROM process_rules WHERE campaign_id=? AND job_id IS NULL ORDER BY id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        rule = {
            "written_test_status": job.get("written_test_status", "unknown"),
            "written_test_burden": int(job.get("written_test_burden", 5)),
            "process_text": job.get("process_text") or "由自动搜索页面抽取，需打开原文确认流程。",
            "confidence": float(job.get("process_confidence", 0.35)),
        }
        if existing_rule:
            conn.execute(
                """UPDATE process_rules SET written_test_status=?, written_test_burden=?, process_text=?, confidence=?, updated_at=? WHERE id=?""",
                (
                    rule["written_test_status"],
                    rule["written_test_burden"],
                    rule["process_text"],
                    rule["confidence"],
                    ts,
                    int(existing_rule["id"]),
                ),
            )
        else:
            insert_process_rule(conn, campaign_id, None, rule)
        existing_job = conn.execute(
            """SELECT id FROM jobs WHERE company_id=? AND title=? AND COALESCE(source_url, '')=COALESCE(?, '') ORDER BY id DESC LIMIT 1""",
            (company_id, job.get("title") or "待命名岗位", job.get("source_url")),
        ).fetchone()
        job_payload = {
            "title": job.get("title") or "待命名岗位",
            "job_family": job.get("job_family", "unknown"),
            "cities": job.get("cities", []),
            "degree_min": job.get("degree_min", "bachelor"),
            "majors": job.get("majors", []),
            "description": job.get("description") or "由自动搜索从公开招聘页面抽取，建议打开原文确认。",
            "apply_url": job.get("apply_url") or job.get("source_url"),
            "source_url": job.get("source_url"),
            "source_level": job.get("source_level", "A"),
            "status": _status_for_deadline(job.get("deadline")),
            "quality_score": float(job.get("quality_score", 0.72)),
            "risk_level": job.get("risk_level", "needs_review"),
        }
        if existing_job:
            job_id = int(existing_job["id"])
            conn.execute(
                """UPDATE jobs SET job_family=?, cities_json=?, degree_min=?, majors_json=?, description=?, apply_url=?, status=?, source_level=?, quality_score=?, risk_level=?, last_verified_at=?, updated_at=? WHERE id=?""",
                (
                    job_payload["job_family"],
                    dumps_json(job_payload["cities"]),
                    job_payload["degree_min"],
                    dumps_json(job_payload["majors"]),
                    job_payload["description"],
                    job_payload["apply_url"],
                    job_payload["status"],
                    job_payload["source_level"],
                    job_payload["quality_score"],
                    job_payload["risk_level"],
                    ts,
                    ts,
                    job_id,
                ),
            )
        else:
            job_id = insert_job(conn, company_id, campaign_id, job_payload)
        evidence_text = job.get("evidence_text") or job_payload["description"]
        conn.execute(
            """INSERT INTO evidence (entity_type, entity_id, field_name, value_text, evidence_text, source_url, confidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("job", job_id, "auto_extracted", job_payload["title"], evidence_text, job.get("source_url"), float(job.get("confidence", 0.65)), ts),
        )
        conn.commit()
        return {"company_id": company_id, "campaign_id": campaign_id, "job_id": job_id}
