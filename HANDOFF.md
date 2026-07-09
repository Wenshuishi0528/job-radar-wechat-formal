# Handoff 交接说明

日期：2026-07-09
版本：0.6.0
项目：Job Radar MVP + Multi-source Search

## 当前状态

本仓库已经包含一个可以本地运行的 MVP。它不是完整招聘平台，也不是完整爬虫系统。当前目标是验证三组能力：

1. 校招雷达：招聘信号、岗位搜索、毕业时间匹配、笔试负担分、来源可信度、证据展示、手动导入公告文本和变更记录。
2. 多来源自动搜索：先匹配内置官方招聘目录，再通过普通 Google / Bing / 搜狗微信通道发现企业官网、招聘平台、开源/社区、高校就业网和公众号文章；公开招聘页会被抓取并抽取岗位，普通网页兜底进入招聘信号库，公众号文章进入文章索引。
3. 个人本地启动：`START_HERE.command` 可双击运行，默认只监听本机 `127.0.0.1`。



## 如何运行

最简单：

```text
双击 START_HERE.command
```

手动：

```bash
cd job-radar-wechat-formal
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ENABLE_WECHAT_PUBLIC_FETCH=1 JOB_RADAR_PERSONAL_MODE=1 uvicorn services.api.main:app --reload --host 127.0.0.1 --port 8000
```

打开 `http://localhost:8000`。

测试：

```bash
python -m unittest discover -s tests
```

## 重要文件

`services/api/main.py` 是 FastAPI 入口，负责 API 和静态前端挂载。

`services/api/app/database.py` 定义 SQLite schema 和数据库初始化。0.2.0 新增了公众号文章相关表。

`services/api/app/repository.py` 负责读写公司、招聘项目、岗位、证据、信号和变更事件。启动时也会 seed 公众号文章演示数据。

`services/api/app/wechat_articles.py` 是公众号文章源主模块，包含 URL 规范化、HTML 解析、图片提取、质量评分、新鲜度评分、入库、搜索、搜狗搜索结果 HTML 解析和发现运行记录。

`services/api/app/web_search_importer.py` 是普通 Google/Bing/搜狗微信复合搜索自动导入模块。它不使用第三方搜索 API；会先按公司别名匹配内置官方招聘目录，例如国家能源集团 `zhaopin.chnenergy.com.cn`，再让 Google/Bing 按 `source_scope` 搜企业官网、招聘平台、开源/社区、高校就业网和公众号。公开招聘页会尝试抽取岗位并写入 `jobs`；抽不出岗位的非公众号网页写入 `signals` 并保持 `pending_review`；公众号文章调用公众号文章抓取入库。搜狗微信保留为公众号专项通道。遇到验证码、登录确认或异常流量页面会停止并记录失败，不做绕过。

`services/api/app/wechat_official_api.py` 是授权公众号官方 API 适配器。它只用于自己授权的公众号，不是全网搜索接口。

`services/api/app/external_search_adapters.py` 是 Firecrawl / Tavily 的可选发现器骨架。当前个人版主流程不使用第三方搜索 API；Google、Bing 和搜狗微信都走普通搜索自动导入。

`docs/wechat-article-source.md` 是公众号文章源的设计说明和生产化路线。

`apps/web/index.html`、`apps/web/app.js`、`apps/web/styles.css` 是静态前端。

`services/worker/monitor.py` 是后续做数据源监控的骨架，目前没有接真实调度。

## 已完成的产品能力

1. 三层数据模型：Company、RecruitmentCampaign、JobPosting。
2. 信号库：Signal 与正式岗位分离。
3. 证据库：Evidence 记录字段、原文、URL 和置信度。
4. 变更记录：ChangeEvent 记录关键字段的新旧值。
5. 笔试分类：免笔试、无统一笔试、岗位特定、在线测评、明确笔试、未知。
6. 笔试负担分：0 到 5 分。
7. 用户画像匹配：学校地区、毕业时间、学历、城市、笔试偏好。
8. 手动导入公告文本：用于冷启动和编辑后台雏形。
9. 微信公众号文章源：文章解析、入库、搜索、质量分、新鲜度分、候选发现记录。
10. 个人启动脚本：自动建环境、装依赖、开启本地个人模式。
11. Google/Bing/搜狗微信自动搜索导入：不需要 API 密钥，支持综合、企业官网、招聘平台、开源/社区、高校就业网和公众号范围。
12. 可拖拽前端工作区：左侧集中设置，右侧集中显示招聘信号、岗位和公众号文章。
13. 岗位级自动抽取：官方招聘页可抽取岗位名、单位、城市、学历、专业和截止日期并进入岗位库。
14. 单元测试：覆盖笔试分类、用户匹配、公众号文章解析、入库、搜索、旧文章过滤、普通搜索结果解析、非公众号网页转信号、岗位抽取和反验证码绕过边界。

## 当前限制

1. 没有接入真实招聘网站后台监控，只是按用户触发做普通搜索导入。
2. 没有登录、收藏、投递管理、保存搜索和提醒。
3. 没有真正的编辑后台，目前只有简化导入表单。
4. 没有 LLM 结构化提取，只有规则提取。
5. 没有公司别名合并和复杂去重。
6. 没有 OpenSearch / Elasticsearch，公众号文章搜索仍然是 SQLite LIKE。
7. 搜狗微信、Google 和 Bing 已进入个人版普通搜索自动导入流程；Firecrawl、Tavily 和微信官方 API 仍只是安全骨架。
8. 前端是纯静态页面，不是 Next.js。
9. SQLite schema 适合 MVP，不适合高并发生产环境。

## 公众号文章源边界

不要使用个人微信 Cookie、appmsg_token、抓包参数、验证码识别、代理池或 MITM。

搜狗微信、Google 和 Bing 搜到的公众号文章只作为情报来源。Google/Bing 搜到的企业官网、招聘平台、高校和社区页面也只是招聘信号。文章或网页都不等于正式岗位事实，进入岗位库前必须有来源等级、发布时间、新鲜度、可信度和人工复核。

授权公众号官方 API 只适合企业或博主合作后同步自己账号的已发布文章。它不是全网公众号文章搜索。

默认搜索只看近 45 天的已知发布时间文章。历史文章必须显式 include_stale。

## 下一批开发任务

P0：

1. Source Registry 后台化，覆盖企业官网、招聘平台、高校就业网、公众号和社区来源。
2. 公众号账号 allowlist / blocklist 管理后台。
3. OpenSearch / Elasticsearch 索引适配器。
4. 编辑后台：新信号、公众号候选、低质量文章、冲突信息、疑似关闭队列。
5. 保存原始 HTML 快照和解析版本。
6. 真实 worker 调度、频控、失败重试和内容 hash。
7. 用户保存搜索和提醒。
8. 投递管理。

P1：

1. 接 5 到 10 个稳定公开来源，优先公司官网、高校就业网和官方公众号。
2. 接授权公众号官方 API 的同步任务。
3. 接 Firecrawl/Tavily 作为可选补充发现器。
4. 增加公众号文章到招聘信号的转换审核流。
5. 增加公司页、招聘项目页和岗位生命周期。
6. 增加冲突检测和去重合并。

P2：

1. 社区匿名进度墙。
2. 博主表格导入工具。
3. 学校页面。
4. 导出 CSV 和日历订阅。
5. 多画像。
6. 简历版本名称管理，暂不上传简历文件。

## 给下一位开发者的建议

先跑测试，再启动服务。先理解 `wechat_articles.py` 的边界，再接任何外部搜索或抓取源。这个模块的核心不是“多抓”，而是“新鲜、可信、可追溯、可审核”。
