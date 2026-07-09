from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .change_detector import detect_changes
from .database import get_connection, init_db
from .extraction import ExtractedNotice
from .sample_data import DEMO_COMPANIES, DEMO_SIGNALS
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


def ensure_seed_data() -> None:
    init_db()
    with get_connection() as conn:
        ensure_wechat_seed_data(conn)
        count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        if count:
            conn.commit()
            return
        for company in DEMO_COMPANIES:
            company_id = upsert_company(conn, company)
            for campaign in company["campaigns"]:
                process_rule = campaign.pop("process_rule")
                jobs = campaign.pop("jobs")
                campaign_id = insert_campaign(conn, company_id, campaign)
                insert_process_rule(conn, campaign_id, None, process_rule)
                for job in jobs:
                    insert_job(conn, company_id, campaign_id, {
                        **job,
                        "apply_url": campaign.get("apply_url"),
                        "source_url": campaign.get("source_url"),
                        "source_level": campaign.get("source_level", company.get("source_level", "C")),
                    })
                campaign["process_rule"] = process_rule
                campaign["jobs"] = jobs
        for signal in DEMO_SIGNALS:
            company_id = get_company_id_by_name(conn, signal["company_name"])
            insert_signal(conn, company_id, None, signal)
        conn.commit()


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
            accepts_overseas, degree_min, application_rules, apply_url, source_url, source_level,
            last_verified_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            campaign.get("application_rules"),
            campaign.get("apply_url"),
            campaign.get("source_url"),
            campaign.get("source_level", "C"),
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


def list_jobs(filters: dict[str, Any]) -> list[dict[str, Any]]:
    ensure_seed_data()
    clauses = ["1=1"]
    params: list[Any] = []
    query = filters.get("query")
    if query:
        like = f"%{query}%"
        clauses.append("(j.title LIKE ? OR c.name LIKE ? OR j.description LIKE ? OR ca.name LIKE ?)")
        params.extend([like, like, like, like])
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
        params.append(1 if accepts_overseas else 0)
    max_written_burden = filters.get("max_written_test_burden")
    if max_written_burden is not None:
        clauses.append("COALESCE(pr.written_test_burden, 5) <= ?")
        params.append(int(max_written_burden))
    if filters.get("only_open", True):
        clauses.append("j.status IN ('open', 'closing_soon')")
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
            "status": "open",
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
            "status": "open",
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
