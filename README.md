# Job Radar MVP 校招雷达 MVP

版本：0.6.0
日期：2026-07-09

这是一个可运行的个人本地校招信息雷达。当前版本把搜索范围从“微信公众号文章源”扩展为多来源岗位搜索：企业招聘官网、招聘平台、开源/社区讨论、高校就业网和公众号文章都可以进入同一套本地流程。系统会先发现来源，再抓取公开招聘页面，抽取岗位字段，写入岗位库，并按用户画像匹配排序。Google、Bing 和搜狗微信只是搜索通道，不需要第三方搜索 API。

当前数据仍然是演示数据，不代表实时招聘信息。真实上线时，需要把 Source Registry、账号白名单、编辑后台、OpenSearch 索引和抓取限速补齐。

## 傻瓜式启动

在 macOS Finder 里双击：

```text
START_HERE.command
```

它会自动：

1. 创建 `.venv`。
2. 安装依赖。
3. 开启个人本地模式。
4. 开启公开 `mp.weixin.qq.com` 文章 URL 抓取。
5. 开启普通 Google / Bing / 搜狗微信复合搜索自动导入。
6. 开启企业官网、招聘平台、开源社区、高校就业网和公众号等多来源发现入口。
7. 开启搜狗微信发现开关；遇到验证码或反自动化页面会停止，不会绕过。
8. 自动打开 `http://127.0.0.1:8000` 或下一个可用端口。

使用时保持弹出的 Terminal 窗口打开；关闭窗口或按 `Control-C` 会停止服务。

## 手动启动

```bash
cd job-radar-wechat-formal
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ENABLE_WECHAT_PUBLIC_FETCH=1 JOB_RADAR_PERSONAL_MODE=1 uvicorn services.api.main:app --reload --host 127.0.0.1 --port 8000
```

打开：

```text
http://localhost:8000
```

API 文档：

```text
http://localhost:8000/docs
```

运行测试：

```bash
python -m unittest discover -s tests
```

## 已实现功能

### 校招雷达

1. 岗位搜索。支持关键词、城市、届别、是否接受海外、笔试负担上限等条件。
2. 用户画像匹配。输入毕业年月、学校地区、学历、目标城市和笔试偏好后，返回可投、可能可投、不适合或未知。
3. 笔试状态分类。支持免笔试、无统一笔试、岗位特定笔试、在线测评、明确笔试和未知。
4. 招聘信号雷达。信号和正式岗位分开，避免把“有动静”误写成“已开放”。
5. 证据字段。每个关键判断可以绑定原文片段、来源 URL 和置信度。
6. 文本导入。后台可以粘贴公告文本，系统做基础结构化提取并生成招聘项目和岗位。
7. 变更检测。导入同一公司项目时，会记录截止日期、毕业时间、笔试规则等关键字段变化。
8. 静态前端。左侧是自动搜索、画像和筛选设置，右侧是招聘信号、岗位和公众号文章结果列表；左右宽度可以用鼠标拖拽调整。

### 多来源自动搜索与岗位匹配

1. 支持信息源范围：综合、企业官网、招聘平台、开源/社区、高校就业网、公众号。
2. 支持搜索通道：全部通道、Google + Bing、Google、Bing、搜狗微信。
3. 内置一批常见央企/国企官方招聘入口候选，例如国家能源集团、国家电网、南方电网、中国能建、中国大唐和中国电建。
4. 公开招聘页面会被抓取并抽取岗位名、公司/单位、城市、学历、专业、截止日期和来源证据。
5. 抽取出的岗位会写入 `jobs` 并进入右侧“岗位”列表，前端会自动按用户画像跑匹配。
6. 没有抽出岗位的网页仍进入 `signals`，状态为 `pending_review`，不会直接伪造成正式岗位。
7. 公众号文章结果会进入公众号文章索引，保留来源、质量分、新鲜度分和规范化 URL。
8. Google/Bing 走普通网页搜索结果页；搜狗微信只作为公众号专项补充通道。
9. 遇到验证码、登录确认或异常流量页面会停止并提示，不做绕过。

### 微信公众号文章源

1. 新增公众号文章表、来源表、账号信任表、发现任务表和候选表。
2. 支持解析已知公开文章 HTML，提取标题、公众号名、发布时间、摘要、封面、正文、图片和规范化 URL。
3. 支持文章入库、URL 去重、内容 hash、来源等级、质量分、新鲜度分和低质来源屏蔽。
4. 支持本地文章搜索 API，默认过滤已知过期文章。
5. 支持解析搜狗微信搜索结果 HTML，生成候选 URL，并对旧文章标记 stale。
6. 支持授权公众号官方 API 的代码骨架。该路径只用于同步自己授权公众号的已发布文章，不是全网搜索。
7. 前端保留“公众号文章”结果页，可查看被导入的公开公众号文章索引。
8. 外部网络访问默认关闭。需要显式设置环境变量后才会抓公开文章或访问搜狗搜索。
9. 个人启动脚本会为本机使用开启公开文章 URL 抓取、网页搜索自动导入和搜狗发现开关；Google/Bing/搜狗微信都不需要搜索 API。

## 项目结构

```text
job-radar-wechat-formal/
  apps/web/                         # 静态前端
  docs/wechat-article-source.md      # 公众号文章源设计说明
  services/api/                      # FastAPI 服务
  services/api/app/                  # 核心业务代码
  services/api/app/wechat_articles.py
  services/api/app/wechat_official_api.py
  services/api/app/external_search_adapters.py
  services/worker/                   # 数据源监控 worker 骨架
  tests/                             # 单元测试
  HANDOFF.md                         # 交接说明
  CHANGELOG.md                       # 更新记录
  CODEX_TASKS.md                     # 后续给 Codex 的任务清单
```

## API 入口

```text
GET  /api/health
GET  /api/signals
GET  /api/jobs
GET  /api/jobs/{job_id}
POST /api/jobs/auto-search
POST /api/match
POST /api/admin/import-text
GET  /api/changes

GET  /api/wechat/articles
GET  /api/wechat/articles/{article_id}
POST /api/wechat/ingest-html
POST /api/wechat/ingest-url
POST /api/wechat/auto-search-import
GET  /api/wechat/search-links
GET  /api/wechat/config
GET  /api/wechat/discovery-runs
GET  /api/wechat/sources
```

## 环境变量

默认情况下，公众号外部访问都关闭。

```text
JOB_RADAR_DB=services/api/data/job_radar.sqlite3
JOB_RADAR_PERSONAL_MODE=1
ENABLE_WECHAT_PUBLIC_FETCH=0
ENABLE_WEB_SEARCH_IMPORT=1
ENABLE_SOGOU_DISCOVERY=0
SOGOU_REQUEST_DELAY_SECONDS=2.0
WEB_SEARCH_REQUEST_DELAY_SECONDS=1.0
JOB_RADAR_USER_AGENT=JobRadar/0.6 personal-local-use no-login-cookie contact=operator
```

Google、Bing 和搜狗微信都走普通搜索，不需要 API 密钥。页面会自动提取搜索结果中的公开招聘相关页面和公众号文章：普通网页进入招聘信号库，公众号文章进入文章索引。遇到验证码、登录确认或异常流量页面时会停止并提示，不做绕过。

开启联网抓取前应先确认目标站点规则、访问频控、错误重试和人工审核流程。

## 数据设计原则

不要把“发现信号”直接标成“岗位开放”。Signal 只代表有动静，JobPosting 才代表可展示岗位。

不要只保存一个“接受海外留学生”布尔值。海外毕业时间范围、国内毕业时间范围和证据都要保存。

不要只保存“是否笔试”。要保存 written_test_status、written_test_burden、process_text、confidence 和 evidence。

公众号文章不要直接当招聘事实。文章是线索，进入招聘项目和岗位库前需要来源等级、发布时间、新鲜度、账号可信度和人工复核。

## 下一步建议

第一步接入真实数据源时，不要从全网爬虫开始。先接 50 到 100 个高价值官方公众号、公司招聘官网、高校就业网和公共就业平台。

第二步做编辑后台。新信号、低置信度解析、冲突信息、用户反馈、疑似关闭岗位和低质文章都应该进入人工审核队列。

第三步接 OpenSearch 或 Elasticsearch。SQLite 的 LIKE 搜索只能做本地 MVP，正式版需要中文分词、时间排序、账号权重和来源质量排序。

## 许可证

本项目以 Creative Commons Attribution-NonCommercial 4.0 International（CC BY-NC 4.0）发布。

你可以复制、分享、修改和基于本项目继续开发，但必须保留署名，并且不得用于商业用途。完整条款见 `LICENSE`。
