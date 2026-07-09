# WeChat Official Account Article Source 设计说明

日期：2026-07-09
版本：0.2.0

## 目标

这个模块用于把公开微信公众号文章变成招聘情报数据源。它不承诺全网历史文章，也不依赖个人微信 Cookie、抓包参数、验证码识别或代理池。

目标数据流程：

```text
keyword / account / supplied HTML
  -> public discovery candidate
  -> mp.weixin.qq.com article URL
  -> article HTML parser
  -> SQLite article store
  -> local search API
  -> later PostgreSQL + OpenSearch
```

## 关键判断

1. 搜狗微信搜索适合做候选发现，但不适合当唯一主数据源。它会有验证码和反自动化页面，也可能返回旧文章。代码默认关闭真实访问，只支持解析已提供的 HTML。
2. Google Custom Search JSON API 已不适合作为新增项目的正式主路径。它对新客户关闭，并要求已有客户在 2027-01-01 前迁移。
3. 旧的 Bing Search API 已在 2025-08-11 退役，不能写进正式主架构。
4. 微信官方接口只能同步自己授权公众号的已发布文章，不能做全网公众号文章搜索。它适合企业或博主合作后的第一方数据接入。
5. Firecrawl、Tavily 这类搜索和抓取 API 可以作为可选补充，但不能替代自己的质量控制和去重。

## 当前实现

### 数据表

新增表：

```text
wechat_accounts
wechat_article_sources
wechat_authorized_accounts
wechat_articles
wechat_article_images
wechat_discovery_queries
wechat_discovery_runs
wechat_discovery_candidates
```

### 后端模块

```text
services/api/app/wechat_articles.py
services/api/app/wechat_official_api.py
```

`wechat_articles.py` 负责 URL 规范化、HTML 解析、图片提取、质量评分、新鲜度评分、入库、搜索、搜狗结果 HTML 解析和发现运行记录。

`wechat_official_api.py` 是可选授权公众号适配器。它只包含 access token、freepublish/batchget 和数据转换函数，不会访问任何非授权公众号。

### API

```text
GET  /api/wechat/articles
GET  /api/wechat/articles/{article_id}
POST /api/wechat/ingest-html
POST /api/wechat/ingest-url
POST /api/wechat/discover
GET  /api/wechat/discovery-runs
GET  /api/wechat/sources
```

`POST /api/wechat/ingest-url` 默认会返回 403，因为公网抓取开关关闭。需要明确设置：

```text
ENABLE_WECHAT_PUBLIC_FETCH=1
```

`POST /api/wechat/discover` 在没有传入 `html` 时也默认返回 403。需要明确设置：

```text
ENABLE_SOGOU_DISCOVERY=1
```

## 新鲜度策略

默认搜索只显示 45 天内的已知发布时间文章。缺少发布时间的文章不会被直接删除，但会降低新鲜度分。发现层会把超过 freshness_days 的候选标为 stale，不进入推荐主结果。

建议上线配置：

```text
秋招高峰期：7 天、30 天、45 天三个索引视图
日常监控：45 天为默认
历史研究：include_stale=true 单独开启
```

## 来源质量策略

来源等级：

```text
S 授权官方公众号、企业官方招聘号
A 高校就业中心、认证公众号、官方媒体号
B 搜狗微信搜索候选、Firecrawl/Tavily 搜索候选、主流聚合平台线索
C 用户投稿、未完全核验公众号
D 已屏蔽来源、低质营销号、保录/收费内推/培训贷相关来源
```

质量分会考虑：

```text
来源等级
招聘相关关键词
发布时间是否存在
正文长度
低质关键词
账号是否在 allowlist / blocklist
```

低质关键词命中后会标记 `is_blocked_source=1`。搜索默认排除它们。

## 不做的事情

```text
不使用个人微信 Cookie
不使用 appmsg_token 抓历史列表
不做验证码识别
不做代理池绕风控
不做 MITM 抓包
不抓需要登录的文章页面
不把搜狗候选直接当官方事实
不使用百度百家号等低质量站点作为招聘事实来源
```

## 生产化改造

SQLite 只适合本地 MVP。正式版建议：

```text
PostgreSQL 存结构化数据
OpenSearch / Elasticsearch 做全文索引
IK analyzer 或 jieba/自定义词典做中文分词
对象存储保存原始 HTML 快照
任务队列做发现、抓取、解析、审核
编辑后台做人审、去重、冲突处理
```

优先生产任务：

1. Source Registry 后台化。
2. 账号 allowlist / blocklist 管理。
3. 按账号主体、公众号认证、官方链接交叉核验。
4. 发现候选和文章正文分开入库。
5. 支持 OpenSearch 批量索引。
6. 支持保存原始 HTML 快照和解析版本。
7. 对每个搜索结果显示来源、发布时间、首次发现、最后抓取、质量分和是否过期。
8. 给用户默认使用“近 45 天 + S/A/B 来源 + 低质屏蔽”的搜索模式。

## Codex 接手提示

先运行：

```bash
python -m unittest discover -s tests
```

再改：

```text
services/api/app/wechat_articles.py
services/api/app/wechat_official_api.py
services/api/main.py
apps/web/app.js
apps/web/index.html
```

不要一次性替换整个爬虫方案。先保持“自建索引优先、发现层可插拔、外部访问默认关闭”的边界。
