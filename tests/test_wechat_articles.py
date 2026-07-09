import os
import tempfile
import unittest
from pathlib import Path

from services.api.app.database import get_connection, init_db
from services.api.app.wechat_articles import (
    build_browser_search_urls,
    discover_sogou,
    ingest_html,
    is_wechat_article_url,
    normalize_wechat_url,
    parse_sogou_results,
    parse_wechat_article_html,
    search_articles,
)


SAMPLE_ARTICLE_HTML = """
<html>
<head>
<meta property="og:url" content="https://mp.weixin.qq.com/s/test-campus-2027?chksm=ignored" />
<meta property="og:description" content="官方招聘公告摘要" />
</head>
<body>
<h1 id="activity-name">  云狸科技 2027 届秋招提前批启动  </h1>
<span id="js_name">公司官方招聘</span>
<em id="publish_time">2026-07-08</em>
<div id="js_content">
  <p>云狸科技 2027 届校园招聘提前批启动。</p>
  <p>面向海内外应届毕业生，海外毕业时间为 2026 年 9 月至 2027 年 8 月。</p>
  <p>本项目不设置统一笔试，部分技术岗位可能安排在线题。</p>
  <img data-src="//mmbiz.qpic.cn/test-cover.png" />
</div>
<script>
var msg_desc = '面向海内外应届毕业生';
var msg_cdn_url = '//mmbiz.qpic.cn/test-cover.png';
var biz = 'MzTestBiz';
</script>
</body>
</html>
"""


SOGOU_HTML = """
<html><body>
<ul class="news-list">
<li id="sogou_vr_11002601_box_0">
  <div class="img-box"><img src="//mmbiz.qpic.cn/cover.jpg" /></div>
  <div class="txt-box">
    <h3><a href="/link?url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Ftest-campus-2027">云狸科技 2027 届秋招提前批启动</a></h3>
    <p>面向海内外应届毕业生，官方招聘公告。</p>
    <span t="1783443600">2026-07-08</span>
  </div>
</li>
<li id="sogou_vr_11002601_box_1">
  <h3><a href="/link?url=https%3A%2F%2Fmp.weixin.qq.com%2Fs%2Fold-campus-2024">旧文章</a></h3>
  <span t="1719792000">2024-07-01</span>
</li>
</ul>
</body></html>
"""


class WechatArticlePipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_RADAR_DB"] = str(Path(self.tmp.name) / "job_radar.sqlite3")
        init_db()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("JOB_RADAR_DB", None)

    def test_normalize_wechat_url(self):
        normalized = normalize_wechat_url("https://mp.weixin.qq.com/s/test-campus-2027?chksm=ignored#wechat_redirect")
        self.assertEqual(normalized, "https://mp.weixin.qq.com/s/test-campus-2027")
        self.assertTrue(is_wechat_article_url(normalized))

    def test_parse_wechat_article_html(self):
        article = parse_wechat_article_html(SAMPLE_ARTICLE_HTML, "https://mp.weixin.qq.com/s/test-campus-2027")
        self.assertEqual(article.title, "云狸科技 2027 届秋招提前批启动")
        self.assertEqual(article.account_name, "公司官方招聘")
        self.assertEqual(article.publish_at, "2026-07-08 00:00:00")
        self.assertIn("不设置统一笔试", article.content_text)
        self.assertEqual(article.images[0], "https://mmbiz.qpic.cn/test-cover.png")

    def test_ingest_and_search_articles(self):
        item = ingest_html("https://mp.weixin.qq.com/s/test-campus-2027", SAMPLE_ARTICLE_HTML, source="manual_html", source_query="2027 秋招", max_age_days=45)
        self.assertEqual(item["source_level"], "S")
        results = search_articles(q="秋招 海外", freshness_days=45, trusted_only=True)
        self.assertGreaterEqual(results["count"], 1)
        self.assertIn("云狸科技", results["items"][0]["title"])

    def test_sogou_parser_rejects_old_candidates(self):
        candidates = parse_sogou_results(SOGOU_HTML, source_query="秋招")
        self.assertEqual(len(candidates), 2)
        result = discover_sogou("秋招", freshness_days=45, html_text=SOGOU_HTML)
        statuses = {item["canonical_url"]: item["status"] for item in result["items"]}
        self.assertEqual(statuses["https://mp.weixin.qq.com/s/test-campus-2027"], "found")
        self.assertEqual(statuses["https://mp.weixin.qq.com/s/old-campus-2024"], "stale")
        self.assertEqual(result["stale_rejected"], 1)

    def test_sogou_antispider_is_not_bypassed(self):
        with self.assertRaises(RuntimeError):
            parse_sogou_results("<html>weixin.sogou.com 验证码 antispider</html>", source_query="秋招")

    def test_browser_search_urls_are_plain_google_and_bing_links(self):
        urls = build_browser_search_urls("秋招 海外", freshness_days=45)
        self.assertIn("google.com/search", urls["google"])
        self.assertIn("bing.com/search", urls["bing"])
        self.assertIn("mp.weixin.qq.com", urls["google"])
        self.assertIn("mp.weixin.qq.com", urls["bing"])


if __name__ == "__main__":
    unittest.main()
