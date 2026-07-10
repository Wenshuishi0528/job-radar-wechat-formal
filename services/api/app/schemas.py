from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class UserProfileIn(BaseModel):
    graduation_date: Optional[str] = Field(default=None, description="YYYY-MM")
    school_region: str = Field(default="overseas", description="domestic, overseas, hmt, unknown")
    degree: str = Field(default="bachelor", description="associate, bachelor, master, phd")
    target_cities: list[str] = Field(default_factory=list)
    max_written_test_burden: Optional[int] = Field(default=None, ge=0, le=5)


class MatchRequest(BaseModel):
    profile: UserProfileIn
    job_ids: Optional[list[int]] = None
    filters: dict = Field(default_factory=dict)


class ResumeOpportunityMatchRequest(BaseModel):
    resume_text: str = Field(min_length=20, max_length=100_000)
    target_cities: list[str] = Field(default_factory=list)
    preferred_job_families: list[str] = Field(default_factory=list)
    degree: Optional[str] = None
    filters: dict = Field(default_factory=dict)


class TrackerRequest(BaseModel):
    status: str = Field(default="saved", max_length=40)
    is_favorite: bool = False
    note: str = Field(default="", max_length=2_000)
    next_action_at: Optional[str] = Field(default=None, max_length=40)


class ImportTextRequest(BaseModel):
    company_name: str
    job_title: str = "待命名岗位"
    source_url: Optional[str] = None
    source_level: str = "C"
    text: str = Field(min_length=20)


class WechatIngestHtmlRequest(BaseModel):
    url: str = Field(description="Public mp.weixin.qq.com article URL")
    html: str = Field(min_length=20, description="Raw public article HTML")
    source: str = Field(default="manual_html", description="manual_html, wechat_public_article, wechat_official_api, etc.")
    source_query: str = Field(default="")
    max_age_days: int = Field(default=45, ge=0, le=3650)


class WechatIngestUrlRequest(BaseModel):
    url: str = Field(description="Public mp.weixin.qq.com article URL")
    source: str = Field(default="wechat_public_article")
    source_query: str = Field(default="")
    max_age_days: int = Field(default=45, ge=0, le=3650)


class WechatDiscoverRequest(BaseModel):
    keyword: str = Field(min_length=1)
    provider: str = Field(default="sogou_weixin_search", description="sogou_weixin_search")
    page: int = Field(default=1, ge=1, le=10)
    freshness_days: int = Field(default=45, ge=0, le=3650)
    html: Optional[str] = Field(default=None, description="Optional supplied search-result HTML. Used for tests, manual imports, and compliance-safe dry runs.")


class WechatAutoSearchImportRequest(BaseModel):
    keyword: str = Field(min_length=1)
    provider: str = Field(default="all", description="all, google, bing, sogou, or both")
    source_scope: str = Field(default="all", description="all, official, job_boards, open_web, university, or wechat")
    freshness_days: int = Field(default=45, ge=0, le=3650)
    max_results: int = Field(default=30, ge=1, le=100)
