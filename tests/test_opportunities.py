import os
import tempfile
import unittest
from pathlib import Path

from services.api.app.database import init_db
from services.api.app.repository import import_discovered_campaign, import_scraped_job, list_jobs, list_opportunities


class OpportunityRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_RADAR_DB"] = str(Path(self.tmp.name) / "job_radar.sqlite3")
        init_db()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("JOB_RADAR_DB", None)

    def test_expired_job_is_not_returned_as_open(self):
        import_scraped_job({
            "company_name": "过期测试公司",
            "title": "测试岗位",
            "campaign_name": "2025届校园招聘",
            "target_cohort": "2025届",
            "deadline": "2025-01-01",
            "source_url": "https://jobs.example.org/expired",
        })
        self.assertEqual(list_jobs({"query": "测试岗位", "limit": 10}), [])
        self.assertEqual(list_opportunities({"query": "测试岗位", "limit": 10})["count"], 0)
        expired = list_opportunities({"query": "测试岗位", "include_expired": True, "limit": 10})
        self.assertEqual(expired["count"], 1)
        self.assertEqual(expired["items"][0]["status"], "closed")

    def test_news_campaigns_are_deduplicated_across_publishers(self):
        base = {
            "company_name": "百度",
            "company_aliases": ["百度", "baidu"],
            "company_type": "民企",
            "industry": "互联网",
            "campaign_name": "百度2027届校招正式启动",
            "recruitment_type": "校招",
            "target_cohort": "2027届",
            "status": "open",
            "apply_url": "https://talent.baidu.com/",
            "source_level": "B",
        }
        import_discovered_campaign({**base, "source_url": "https://news.google.com/rss/articles/a"})
        import_discovered_campaign({**base, "campaign_name": "【校招】百度2027届校招正式启动！", "source_url": "https://news.google.com/rss/articles/b"})
        result = list_opportunities({"query": "百度", "limit": 10})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["record_type"], "campaign")


if __name__ == "__main__":
    unittest.main()
