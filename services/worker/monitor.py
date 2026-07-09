from __future__ import annotations

"""Source monitor skeleton.

This file intentionally does not implement aggressive crawling. The production worker should:

1. Read sources from the Source Registry.
2. Respect source priority, refresh interval, robots policy and platform terms.
3. Fetch only public pages that do not require login, CAPTCHA bypass or private tokens.
4. Store raw HTML snapshots and content hashes.
5. Run change detection before extraction.
6. Send low-confidence or conflicting data to the editing queue.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256


@dataclass
class FetchResult:
    source_id: int
    url: str
    status_code: int
    content_hash: str
    fetched_at: str
    text: str


def hash_content(content: str) -> str:
    return sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


class SourceMonitor:
    def should_fetch(self, source: dict) -> bool:
        if source.get("robots_policy") == "disallow":
            return False
        if source.get("failure_count", 0) >= 5 and source.get("priority", 50) < 80:
            return False
        return True

    def fetch_public_page(self, source: dict) -> FetchResult:
        raise NotImplementedError("Add an HTTP client here after source policies are finalized.")

    def process(self, source: dict) -> dict:
        if not self.should_fetch(source):
            return {"skipped": True, "reason": "source policy or failure count"}
        return {"skipped": True, "reason": "fetcher not implemented in MVP"}
