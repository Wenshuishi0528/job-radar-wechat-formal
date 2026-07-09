import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.api.app.database import init_db
from services.api.app.repository import import_scraped_job, list_jobs
from services.api.app.web_search_importer import (
    WebSearchCandidate,
    WebSearchImportError,
    auto_search_and_import,
    build_plain_search_url,
    extract_jobs_from_html,
    fetch_curated_official_results,
    fetch_sogou_results,
    parse_search_results,
)


GOOGLE_HTML = """
<html><body>
  <a href="/url?q=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fcampus-2027&sa=U">校园招聘</a>
  <a href="/url?q=https%3A%2F%2Fexample.com%2Fnot-wechat&sa=U">忽略</a>
</body></html>
"""


BING_HTML = """
<html><body>
  <li class="b_algo">
    <h2><a href="https://mp.weixin.qq.com/s/bing-campus-2027?chksm=ignored">秋招启动</a></h2>
  </li>
</body></html>
"""


OFFICIAL_HTML = """
<html><body>
  <a href="/url?q=https%3A%2F%2Fjobs.bytedance.com%2Fcampus%2Fposition%2F123&sa=U">字节跳动校园招聘</a>
  <a href="https://career.huawei.com/reccampportal/portal5/campus-recruitment.html">华为校园招聘官网</a>
  <a href="https://example.com/campus/notice.pdf">招聘公告 PDF</a>
</body></html>
"""


GOOGLE_NOISE_HTML = """
<html><body>
  <a href="https://support.google.com/websearch">反馈</a>
  <a href="https://accounts.google.com/">登录</a>
</body></html>
"""


SOGOU_HTML = """
<html><body>
<ul class="news-list">
<li id="sogou_vr_11002601_box_0">
  <h3><a href="/link?url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fsogou-campus-2027">搜狗秋招启动</a></h3>
  <span t="1783443600">2026-07-08</span>
</li>
</ul>
</body></html>
"""


CHNENERGY_JOBS_HTML = """
<html><body>
<div>搜索</div>
<div>人力专责</div>
<div>人力专责</div>
<div>硕士研究生</div>
<div>|</div>
<div>人力资源管理,劳动关系,劳动与社会保障,医疗保险</div>
<div>中国神华煤制油化工有限公司销售分公司</div>
<div>内蒙古包头</div>
<div>招聘人数：1</div>
<div>申请</div>
<div>报名截止日期：2026-05-21</div>
<div>人工智能技术开发</div>
<div>人工智能技术开发</div>
<div>硕士研究生</div>
<div>|</div>
<div>电子信息工程,人工智能,计算机科学与技术,智能科学与技术</div>
<div>国能基石化工科技（上海）有限公司</div>
<div>上海</div>
<div>招聘人数：1</div>
<div>申请</div>
<div>报名截止日期：2026-05-21</div>
</body></html>
"""

CHNENERGY_ANNC_LIST_HTML = """
<html><body>
<ul class="list-group">
  <li class="list-group-item"><a href="/annc/showgg?id=notice">国家能源集团2026年度高校毕业生春季招聘笔试通知</a></li>
  <li class="list-group-item"><a href="/annc/showgg?id=direct">国家能源投资集团有限责任公司2026年高校毕业生直招公告</a></li>
</ul>
</body></html>
"""

CHNENERGY_ANNC_DETAIL_HTML = """
<html><body>
<p class="lead text-center">国家能源投资集团有限责任公司2026年高校毕业生直招公告</p>
<div id="anncTxt"><p>面向国家能源集团所属单位招聘高校毕业生。</p></div>
<a href="/annc/showggStationList?id=direct">招聘职位列表</a>
</body></html>
"""

CHNENERGY_STATION_LIST_HTML = """
<html><body>
<ul class="list-group">
  <li class="list-group-item">
    <h4 class="list-group-item-heading">
      <a href="/annc/showgw?id=job1" target="_self" class="showNewpage" title="AI算法研究员">AI算法研究员</a>
      <span class="pull-right"><small>科研</small></span>
    </h4>
    <p class="list-group-item-text">
      <span title="国能数智科技开发（北京）有限公司本部">国能数智科技开发（北京）有限公司本部</span>
      &nbsp;|&nbsp; <span title="电子信息类相关专业,计算机类相关专业,信息与通信工程类相关专业">电子信息类相关专业,计算机类相关专业,信...</span>
      &nbsp;|&nbsp; 博士研究生 &nbsp;|&nbsp; 北京 &nbsp;|&nbsp; 2人
    </p>
  </li>
</ul>
</body></html>
"""


class FakeResponse:
    def __init__(self, body):
        self.body = body.encode("utf-8")
        self.headers = self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body

    def get_content_charset(self):
        return "utf-8"


class PlainWebSearchImporterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_RADAR_DB"] = str(Path(self.tmp.name) / "job_radar.sqlite3")
        os.environ["JOB_RADAR_PERSONAL_MODE"] = "1"
        init_db()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("JOB_RADAR_DB", None)
        os.environ.pop("JOB_RADAR_PERSONAL_MODE", None)

    def test_build_plain_search_url_uses_regular_search_pages(self):
        google = build_plain_search_url("google", "秋招 海外", freshness_days=45, source_scope="wechat")
        bing = build_plain_search_url("bing", "秋招 海外", freshness_days=45, source_scope="wechat")
        self.assertIn("google.com/search", google)
        self.assertIn("bing.com/search", bing)
        self.assertIn("site%3Amp.weixin.qq.com", google)
        self.assertIn("site%3Amp.weixin.qq.com", bing)

    def test_build_plain_search_url_can_target_company_sites(self):
        google = build_plain_search_url("google", "秋招 产品", source_scope="official")
        self.assertIn("jobs.bytedance.com", google)
        self.assertIn("career.huawei.com", google)
        self.assertIn("zhaopin.chnenergy.com.cn", google)

    def test_curated_official_results_cover_china_energy_group(self):
        items = fetch_curated_official_results("中国能源集团 校招", source_scope="official", max_results=10)
        urls = {item.canonical_url for item in items}
        self.assertIn("https://zhaopin.chnenergy.com.cn/", urls)
        self.assertIn("https://zhaopin.chnenergy.com.cn/recTypeSerch?kinds=1", urls)
        self.assertEqual(items[0].provider, "official_catalog")

    def test_parse_google_and_bing_results(self):
        google_items = parse_search_results("google", GOOGLE_HTML, keyword="秋招")
        bing_items = parse_search_results("bing", BING_HTML, keyword="秋招")
        self.assertEqual(google_items[0].canonical_url, "https://mp.weixin.qq.com/s/campus-2027")
        self.assertEqual(bing_items[0].canonical_url, "https://mp.weixin.qq.com/s/bing-campus-2027")

    def test_parse_regular_recruiting_pages_as_signals(self):
        items = parse_search_results("google", OFFICIAL_HTML, keyword="秋招", source_scope="official")
        urls = {item.canonical_url: item for item in items}
        self.assertIn("https://jobs.bytedance.com/campus/position/123", urls)
        self.assertIn("https://career.huawei.com/reccampportal/portal5/campus-recruitment.html", urls)
        self.assertIn("https://example.com/campus/notice.pdf", urls)
        self.assertEqual(urls["https://jobs.bytedance.com/campus/position/123"].candidate_type, "web_signal")
        self.assertEqual(urls["https://jobs.bytedance.com/campus/position/123"].title, "字节跳动校园招聘")

    def test_parse_ignores_search_engine_support_links(self):
        items = parse_search_results("google", GOOGLE_NOISE_HTML, keyword="中国能源集团", source_scope="official")
        self.assertEqual(items, [])

    def test_extract_jobs_from_recruiting_page_html(self):
        jobs = extract_jobs_from_html(
            CHNENERGY_JOBS_HTML,
            source_url="https://zhaopin.chnenergy.com.cn/recTypeSerch?kinds=1",
            default_company="国家能源集团",
            max_jobs=10,
        )
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0]["title"], "人力专责")
        self.assertEqual(jobs[0]["company_name"], "中国神华煤制油化工有限公司销售分公司")
        self.assertEqual(jobs[0]["cities"], ["内蒙古包头"])
        self.assertEqual(jobs[0]["degree_min"], "master")
        self.assertEqual(jobs[0]["deadline"], "2026-05-21")

    def test_extract_jobs_from_chnenergy_station_list(self):
        jobs = extract_jobs_from_html(
            CHNENERGY_STATION_LIST_HTML,
            source_url="https://zhaopin.chnenergy.com.cn/annc/showggStationList?id=direct",
            default_company="国家能源集团",
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "AI算法研究员")
        self.assertEqual(jobs[0]["company_name"], "国能数智科技开发（北京）有限公司本部")
        self.assertEqual(jobs[0]["degree_min"], "phd")
        self.assertEqual(jobs[0]["cities"], ["北京"])

    def test_job_search_expands_china_energy_alias(self):
        import_scraped_job({
            "company_name": "国能数智科技开发（北京）有限公司本部",
            "title": "AI算法研究员",
            "campaign_name": "国家能源集团 校园招聘",
            "recruitment_type": "校招",
            "cities": ["北京"],
            "degree_min": "phd",
            "source_url": "https://zhaopin.chnenergy.com.cn/annc/showgw?id=job1",
            "apply_url": "https://zhaopin.chnenergy.com.cn/annc/showgw?id=job1",
        })
        jobs = list_jobs({"query": "中国能源集团", "limit": 10})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "AI算法研究员")

    def test_parse_rejects_verification_pages(self):
        with self.assertRaises(WebSearchImportError):
            parse_search_results("google", "<html>Our systems have detected unusual traffic captcha</html>")

    def test_auto_search_and_import_records_imported_items(self):
        candidates = [
            WebSearchCandidate(
                url="https://mp.weixin.qq.com/s/campus-2027",
                canonical_url="https://mp.weixin.qq.com/s/campus-2027",
                provider="google",
                source_query="秋招",
                candidate_type="wechat_article",
            )
        ]
        with patch("services.api.app.web_search_importer.fetch_search_results", return_value=candidates):
            with patch("services.api.app.web_search_importer.ingest_url", return_value={"id": 123}):
                result = auto_search_and_import("秋招", provider="google", freshness_days=45, max_results=5)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["items"][0]["article_id"], 123)

    def test_fetch_sogou_results_uses_sogou_parser(self):
        with patch("urllib.request.urlopen", return_value=FakeResponse(SOGOU_HTML)):
            with patch("time.sleep", return_value=None):
                items = fetch_sogou_results("秋招", freshness_days=45, max_results=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].provider, "sogou")
        self.assertEqual(items[0].canonical_url, "https://mp.weixin.qq.com/s/sogou-campus-2027")

    def test_all_provider_keeps_google_bing_and_sogou(self):
        def fake_fetch(provider, keyword, freshness_days=45, max_results=10, source_scope="all"):
            return [
                WebSearchCandidate(
                    url=f"https://mp.weixin.qq.com/s/{provider}-campus-2027",
                    canonical_url=f"https://mp.weixin.qq.com/s/{provider}-campus-2027",
                    provider=provider,
                    source_query=keyword,
                    source_scope=source_scope,
                    candidate_type="wechat_article",
                )
            ]

        with patch("services.api.app.web_search_importer.fetch_search_results", side_effect=fake_fetch):
            with patch("services.api.app.web_search_importer.ingest_url", return_value={"id": 123}):
                result = auto_search_and_import("秋招", provider="all", freshness_days=45, max_results=5)
        self.assertEqual([p["provider"] for p in result["providers"]], ["google", "bing", "sogou"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["imported"], 3)

    def test_non_wechat_results_create_signals(self):
        candidates = [
            WebSearchCandidate(
                url="https://jobs.bytedance.com/campus/position",
                canonical_url="https://jobs.bytedance.com/campus/position",
                title="字节跳动校园招聘",
                snippet="2027届校园招聘岗位开放",
                provider="google",
                source_query="秋招",
                source_scope="official",
                candidate_type="web_signal",
            )
        ]
        with patch("services.api.app.web_search_importer.fetch_search_results", return_value=candidates):
            with patch("services.api.app.web_search_importer._import_jobs_from_candidate", return_value=[]):
                result = auto_search_and_import("秋招", provider="google", source_scope="official", freshness_days=45, max_results=5)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["items"][0]["signal_id"], 1)

    def test_auto_search_import_adds_curated_official_signals_first(self):
        with patch("services.api.app.web_search_importer.fetch_search_results", return_value=[]):
            with patch("services.api.app.web_search_importer._import_jobs_from_candidate", return_value=[]):
                result = auto_search_and_import("中国能源集团 校招", provider="google", source_scope="official", freshness_days=45, max_results=5)
        self.assertEqual(result["providers"][0]["provider"], "official_catalog")
        self.assertGreaterEqual(result["providers"][0]["imported"], 1)
        urls = {item["canonical_url"] for item in result["providers"][0]["items"]}
        self.assertIn("https://zhaopin.chnenergy.com.cn/", urls)

    def test_auto_search_import_extracts_jobs_from_curated_page(self):
        def fake_open(request, timeout=15):
            return FakeResponse(CHNENERGY_JOBS_HTML)

        with patch("services.api.app.web_search_importer.fetch_search_results", return_value=[]):
            with patch("services.api.app.web_search_importer._open_url", side_effect=fake_open):
                result = auto_search_and_import("中国能源集团 校招", provider="google", source_scope="official", freshness_days=45, max_results=5)
        self.assertGreaterEqual(result["jobs_imported"], 2)
        imported_items = [item for item in result["providers"][0]["items"] if item["job_ids"]]
        self.assertTrue(imported_items)
        self.assertGreaterEqual(len(result["jobs"]), 2)
        self.assertEqual(result["jobs"][0]["title"], "人力专责")
        self.assertEqual(result["jobs"][0]["company_name"], "中国神华煤制油化工有限公司销售分公司")
        self.assertEqual(result["jobs"][0]["cities"], ["内蒙古包头"])
        self.assertEqual(result["jobs"][0]["deadline"], "2026-05-21")

    def test_auto_search_import_follows_chnenergy_announcement_to_station_list(self):
        def fake_open(request, timeout=15):
            url = request.full_url
            if "annclist" in url:
                return FakeResponse(CHNENERGY_ANNC_LIST_HTML)
            if "showggStationList" in url:
                return FakeResponse(CHNENERGY_STATION_LIST_HTML)
            if "showgg?id=direct" in url:
                return FakeResponse(CHNENERGY_ANNC_DETAIL_HTML)
            return FakeResponse("<html></html>")

        with patch("services.api.app.web_search_importer.fetch_search_results", return_value=[]):
            with patch("services.api.app.web_search_importer._open_url", side_effect=fake_open):
                result = auto_search_and_import("中国能源集团 校招", provider="google", source_scope="official", freshness_days=45, max_results=3)
        self.assertGreaterEqual(result["jobs_imported"], 1)
        self.assertEqual(result["jobs"][0]["title"], "AI算法研究员")
        self.assertEqual(result["jobs"][0]["company_name"], "国能数智科技开发（北京）有限公司本部")


if __name__ == "__main__":
    unittest.main()
