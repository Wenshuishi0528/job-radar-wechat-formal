from __future__ import annotations

import os
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "services" / "api" / "data" / "job_radar.sqlite3"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    company_type TEXT NOT NULL DEFAULT 'unknown',
    industry TEXT NOT NULL DEFAULT 'unknown',
    official_site TEXT,
    recruit_site TEXT,
    source_level TEXT NOT NULL DEFAULT 'C',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    trust_level TEXT NOT NULL DEFAULT 'C',
    priority INTEGER NOT NULL DEFAULT 50,
    check_interval_minutes INTEGER NOT NULL DEFAULT 360,
    parser_type TEXT NOT NULL DEFAULT 'generic',
    last_checked_at TEXT,
    last_content_hash TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    recruitment_type TEXT NOT NULL DEFAULT 'unknown',
    target_cohort TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    start_date TEXT,
    deadline TEXT,
    domestic_grad_start TEXT,
    domestic_grad_end TEXT,
    overseas_grad_start TEXT,
    overseas_grad_end TEXT,
    accepts_overseas INTEGER,
    degree_min TEXT NOT NULL DEFAULT 'bachelor',
    cities_json TEXT NOT NULL DEFAULT '[]',
    job_families_json TEXT NOT NULL DEFAULT '[]',
    majors_json TEXT NOT NULL DEFAULT '[]',
    application_rules TEXT,
    apply_url TEXT,
    source_url TEXT,
    source_level TEXT NOT NULL DEFAULT 'C',
    source_published_at TEXT,
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    campaign_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    job_family TEXT NOT NULL DEFAULT 'unknown',
    cities_json TEXT NOT NULL DEFAULT '[]',
    degree_min TEXT NOT NULL DEFAULT 'bachelor',
    majors_json TEXT NOT NULL DEFAULT '[]',
    description TEXT,
    apply_url TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    source_url TEXT,
    source_level TEXT NOT NULL DEFAULT 'C',
    quality_score REAL NOT NULL DEFAULT 0.5,
    risk_level TEXT NOT NULL DEFAULT 'unknown',
    last_verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(company_id) REFERENCES companies(id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS process_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER,
    job_id INTEGER,
    written_test_status TEXT NOT NULL DEFAULT 'unknown',
    written_test_burden INTEGER NOT NULL DEFAULT 5,
    process_text TEXT,
    confidence REAL NOT NULL DEFAULT 0.2,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id),
    FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    value_text TEXT,
    evidence_text TEXT NOT NULL,
    source_url TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    campaign_id INTEGER,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    source_url TEXT,
    source_level TEXT NOT NULL DEFAULT 'C',
    status TEXT NOT NULL DEFAULT 'unverified',
    detected_at TEXT NOT NULL,
    evidence_text TEXT,
    FOREIGN KEY(company_id) REFERENCES companies(id),
    FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS change_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    detected_at TEXT NOT NULL,
    source_url TEXT
);

CREATE TABLE IF NOT EXISTS application_tracker (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'saved',
    is_favorite INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    applied_at TEXT,
    next_action_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(record_type, record_id)
);



CREATE TABLE IF NOT EXISTS wechat_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL,
    account_biz TEXT DEFAULT '',
    account_aliases_json TEXT NOT NULL DEFAULT '[]',
    account_type TEXT NOT NULL DEFAULT 'unknown',
    trust_level TEXT NOT NULL DEFAULT 'C',
    is_allowlisted INTEGER NOT NULL DEFAULT 0,
    is_blocked INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(account_name, account_biz)
);

CREATE TABLE IF NOT EXISTS wechat_article_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    base_url TEXT,
    trust_level TEXT NOT NULL DEFAULT 'C',
    enabled INTEGER NOT NULL DEFAULT 1,
    requires_api_key INTEGER NOT NULL DEFAULT 0,
    supports_freshness INTEGER NOT NULL DEFAULT 0,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 10,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wechat_authorized_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT NOT NULL,
    appid TEXT NOT NULL UNIQUE,
    appsecret_env TEXT NOT NULL,
    trust_level TEXT NOT NULL DEFAULT 'S',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wechat_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT NOT NULL UNIQUE,
    original_url TEXT,
    title TEXT NOT NULL,
    account_name TEXT DEFAULT '',
    account_biz TEXT DEFAULT '',
    digest TEXT DEFAULT '',
    cover_url TEXT DEFAULT '',
    publish_at TEXT,
    content_text TEXT DEFAULT '',
    content_html TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'unknown',
    source_query TEXT DEFAULT '',
    source_level TEXT NOT NULL DEFAULT 'C',
    quality_score REAL NOT NULL DEFAULT 0.0,
    freshness_score REAL NOT NULL DEFAULT 0.0,
    is_stale INTEGER NOT NULL DEFAULT 0,
    is_blocked_source INTEGER NOT NULL DEFAULT 0,
    block_reason TEXT DEFAULT '',
    content_hash TEXT DEFAULT '',
    parser_version TEXT NOT NULL DEFAULT 'wechat_parser_v1',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    fetched_at TEXT,
    created_signal_id INTEGER REFERENCES signals(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS wechat_article_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL REFERENCES wechat_articles(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    image_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(article_id, image_url)
);

CREATE TABLE IF NOT EXISTS wechat_discovery_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL UNIQUE,
    providers_json TEXT NOT NULL DEFAULT '["sogou_weixin_search"]',
    max_age_days INTEGER NOT NULL DEFAULT 45,
    enabled INTEGER NOT NULL DEFAULT 1,
    strict_quality INTEGER NOT NULL DEFAULT 1,
    last_run_at TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wechat_discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER REFERENCES wechat_discovery_queries(id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    provider TEXT NOT NULL,
    freshness_days INTEGER NOT NULL DEFAULT 45,
    status TEXT NOT NULL DEFAULT 'running',
    results_found INTEGER NOT NULL DEFAULT 0,
    articles_ingested INTEGER NOT NULL DEFAULT 0,
    stale_rejected INTEGER NOT NULL DEFAULT 0,
    low_quality_rejected INTEGER NOT NULL DEFAULT 0,
    error TEXT DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS wechat_discovery_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES wechat_discovery_runs(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    candidate_url TEXT NOT NULL,
    canonical_url TEXT DEFAULT '',
    title TEXT DEFAULT '',
    account_name TEXT DEFAULT '',
    digest TEXT DEFAULT '',
    cover_url TEXT DEFAULT '',
    publish_at TEXT,
    status TEXT NOT NULL DEFAULT 'found',
    reject_reason TEXT DEFAULT '',
    score REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    UNIQUE(provider, query, candidate_url)
);

CREATE INDEX IF NOT EXISTS idx_wechat_articles_publish ON wechat_articles(publish_at);
CREATE INDEX IF NOT EXISTS idx_wechat_articles_account ON wechat_articles(account_name);
CREATE INDEX IF NOT EXISTS idx_wechat_articles_quality ON wechat_articles(quality_score);
CREATE INDEX IF NOT EXISTS idx_wechat_articles_source_level ON wechat_articles(source_level);
CREATE INDEX IF NOT EXISTS idx_wechat_discovery_runs_query ON wechat_discovery_runs(query, provider);
CREATE INDEX IF NOT EXISTS idx_wechat_candidates_run ON wechat_discovery_candidates(run_id);

CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(title);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_cohort ON campaigns(target_cohort);
CREATE INDEX IF NOT EXISTS idx_campaigns_deadline ON campaigns(deadline);
CREATE INDEX IF NOT EXISTS idx_signals_detected_at ON signals(detected_at);
CREATE INDEX IF NOT EXISTS idx_tracker_status ON application_tracker(status, updated_at);
"""


MIGRATION_COLUMNS = {
    "campaigns": {
        "cities_json": "TEXT NOT NULL DEFAULT '[]'",
        "job_families_json": "TEXT NOT NULL DEFAULT '[]'",
        "majors_json": "TEXT NOT NULL DEFAULT '[]'",
        "source_published_at": "TEXT",
    },
    "application_tracker": {
        "is_favorite": "INTEGER NOT NULL DEFAULT 0",
        "applied_at": "TEXT",
        "next_action_at": "TEXT",
    },
}


def db_path() -> Path:
    configured = os.getenv("JOB_RADAR_DB")
    path = Path(configured) if configured else DEFAULT_DB_PATH
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        for table, columns in MIGRATION_COLUMNS.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        conn.commit()
