# Changelog

## 0.6.1 - 2026-07-09

把岗位结果从“测试卡片”改成可扫读的正式岗位列表，并修复国家能源集团链路。

### Added

- 自动搜索响应新增岗位摘要，导入完成后直接显示“岗位名｜公司｜城市｜截止”，不再只显示岗位 ID。
- 新增国家能源集团公告页到“招聘职位列表”的跟随抓取，可从 `showggStationList` 抽取岗位名、用人单位、专业、学历和城市。
- 新增“中国能源集团”到“国家能源集团/国能”等别名扩展，普通岗位搜索和自动搜索口径一致。

### Changed

- 岗位列表改为岗位名、公司、截止日期和操作按钮优先的行式布局，匹配原因和证据入口保留在同一行内。
- 普通“搜索岗位”不再被“笔试负担上限”硬过滤；笔试负担只在“按画像匹配岗位”里作为匹配判断。
- 学历枚举在前端显示为中文。

### Fixed

- 修复 `data.items.map(jobCard)` 把数组下标当成匹配结果导致的 `undefined NaN%` 显示问题。
- 过滤国家能源旧入口里缺少用人单位的残缺岗位块，避免生成只有岗位名、没有公司和城市的脏数据。

## 0.6.0 - 2026-07-09

把自动搜索从“招聘信号导入”升级为“岗位级自动搜索、抽取、入库和匹配”。

### Added

- 新增公开招聘页面岗位抽取器，可从页面文本中抽取岗位名、单位、城市、学历、专业和报名截止日期。
- 新增 `import_scraped_job()`，自动抽取岗位会直接进入 `jobs` 并标记为 `open`，右侧岗位列表可直接展示。
- 新增 `/api/jobs/auto-search` 正式入口；旧 `/api/wechat/auto-search-import` 保留兼容。
- 自动搜索结果新增 `jobs_imported` 和每条候选的 `job_ids`。
- 前端自动搜索生成岗位后会直接按当前用户画像运行匹配，并切换到“岗位”tab。
- 新增国家能源集团招聘页样式的岗位抽取和入库测试。

### Changed

- 国家能源集团等官方目录候选不再只是 signal，会进一步抓取公开招聘页并尝试生成岗位。
- 搜索引擎自身帮助/反馈页被过滤，不再污染招聘信号。

## 0.5.1 - 2026-07-09

修复“输入央企/国企公司名但搜不到官方校招入口”的问题。

### Added

- 新增官方招聘目录候选，自动搜索会先匹配国家能源集团等已知正式招聘入口，再跑 Google/Bing/搜狗。
- 官方搜索域名扩展到国家能源集团、国家电网、南方电网、中国能建、中国大唐、中国电建等常见央企/国企招聘站点。
- 新增“中国能源集团/国家能源集团校招”覆盖测试，确保会生成 `zhaopin.chnenergy.com.cn` 招聘信号。

### Changed

- 综合搜索查询增加“官方招聘、招聘官网、招聘公告、报名入口、简历投递”等关键词，减少只搜公众号或泛网页导致的漏搜。
- 前端自动导入摘要会把内置官网候选显示为“官方目录”。

## 0.5.0 - 2026-07-09

把搜索思路从“公众号文章发现”扩展为“多来源招聘信号雷达”。

### Added

- 新增自动搜索信息源范围：综合、企业官网、招聘平台、开源/社区、高校就业网、公众号。
- Google/Bing 搜到的非公众号招聘相关网页会写入 `signals`，状态为 `pending_review`。
- 公众号文章结果继续进入公众号文章索引，保留搜狗微信专项搜索能力。
- 前端改为左侧设置、右侧结果列表，结果区支持招聘信号、岗位、公众号文章三类 tab。
- 左右两栏之间新增可拖拽分隔条，宽度会保存在本地浏览器。

### Changed

- 自动搜索文案从“查公众号文章”改成“查招聘线索”。
- 官方来源搜索不再只盯公众号，默认覆盖多家企业招聘官网和常见招聘系统。
- 普通网页 PDF 招聘公告不再被过滤为静态资源。
- `/api/wechat/search-links` 对错误的 `source_scope` 返回 400。

### Verified

- 新增非公众号网页解析为招聘信号的单元测试。
- 新增企业官网搜索范围构造测试。

## 0.4.1 - 2026-07-09

恢复并强化搜狗微信搜索在复合搜索中的位置。

### Changed

- 自动导入默认来源改为 `全部来源`：Google + Bing + 搜狗微信。
- 搜索来源下拉新增 `搜狗微信` 和 `Google + Bing` 单独选项。
- 搜狗微信候选会进入同一套自动抓取、解析和入库流程。
- 结果摘要会分别显示 Google、Bing、搜狗微信的发现和导入数量。

### Verified

- 确认原有 `discover_sogou`、`parse_sogou_results`、搜狗反验证码停止逻辑仍在。
- 新增复合搜索覆盖 Google、Bing、搜狗微信三源的单元测试。

## 0.4.0 - 2026-07-09

把公众号搜索改成真正的自动化导入：不用第三方搜索 API，也不用手动复制 URL。

### Added

- 新增 `services/api/app/web_search_importer.py`。
- 新增 `POST /api/wechat/auto-search-import`。
- 支持普通 Google/Bing 网页搜索来源：`google`、`bing`、`both`。
- 自动从搜索结果页解析公开 `mp.weixin.qq.com/s/...` 文章链接。
- 自动抓取公开公众号文章、解析并写入本地索引。
- 新增搜索引擎验证码、登录确认和异常流量页面检测；遇到后停止并提示，不绕过。
- 新增自动搜索导入单元测试。

### Changed

- 前端主流程改为“搜索词 + 来源 + 范围 + 数量 + 自动搜索并导入”。
- Google/Bing 打开按钮保留为查看搜索结果的备用入口，不再是主流程。
- `START_HERE.command` 和 `scripts/dev.sh` 默认开启 `ENABLE_WEB_SEARCH_IMPORT=1`。

## 0.3.0 - 2026-07-09

面向个人本地使用，把公众号线索发现做成更傻瓜式的操作流。

### Added

- 新增 `START_HERE.command`，macOS 双击即可创建虚拟环境、安装依赖、开启个人本地模式并启动服务。
- 新增 `/api/wechat/config`，前端可显示 URL 抓取和搜狗联网状态。
- 新增 `/api/wechat/search-links`，为 Google、Bing 和搜狗生成限制到 `mp.weixin.qq.com/s` 的搜索链接。
- 前端新增普通 Google/Bing 网页搜索按钮和公众号文章自动导入区。

### Changed

- `scripts/dev.sh` 默认只监听 `127.0.0.1`，并默认开启个人本地模式和公开文章 URL 抓取。
- 公众号来源 seed 逻辑会为已有数据库补充新来源，不需要删库重建。
- README 和 `.env.example` 更新个人启动方式；Google/Bing 普通网页搜索不需要 API 密钥。

### Notes

- Google 和 Bing 都作为普通网页搜索入口使用，不要求第三方搜索 API。
- 仍不使用个人微信 Cookie、验证码绕过、代理池或抓包参数。

## 0.2.0 - 2026-07-09

新增微信公众号文章源模块。

### Added

- 新增 `wechat_accounts`、`wechat_article_sources`、`wechat_authorized_accounts`、`wechat_articles`、`wechat_article_images`、`wechat_discovery_queries`、`wechat_discovery_runs`、`wechat_discovery_candidates` 表。
- 新增 `services/api/app/wechat_articles.py`。
- 新增 `services/api/app/wechat_official_api.py`。
- 新增 `services/api/app/external_search_adapters.py`，提供 Firecrawl 和 Tavily 可选候选发现骨架。
- 新增公众号公开文章 URL 规范化。
- 新增公众号文章 HTML 解析。
- 新增标题、公众号名、发布时间、摘要、封面、正文、图片、canonical URL 提取。
- 新增文章入库、去重、content_hash、质量分、新鲜度分、低质来源屏蔽。
- 新增本地文章搜索 API。
- 新增搜狗微信搜索结果 HTML 解析器。
- 新增发现运行记录和候选文章记录。
- 新增授权公众号官方 API 骨架，支持 access token、freepublish/batchget 和记录转换。
- 新增前端“微信公众号文章源”面板。
- 新增 `docs/wechat-article-source.md`。
- 新增环境变量开关：`ENABLE_WECHAT_PUBLIC_FETCH`、`ENABLE_SOGOU_DISCOVERY`、`SOGOU_REQUEST_DELAY_SECONDS`。
- 新增公众号文章单元测试。

### Changed

- API 版本从 0.1.0 升到 0.2.0。
- `ensure_seed_data()` 启动时会同时 seed 公众号文章源演示数据。
- 前端首页新增公众号文章搜索、HTML 导入和发现调试区域。
- README、HANDOFF、CODEX_TASKS 更新到 0.2.0。

### Safety boundaries

- 真实访问搜狗微信搜索默认关闭。
- 真实抓取 mp.weixin.qq.com 公开文章默认关闭。
- 搜狗验证码或反自动化页面会直接报错，不会尝试绕过。
- 不使用个人微信 Cookie、appmsg_token、抓包参数、验证码识别、代理池或 MITM。
- 默认搜索排除已知过期文章和低质来源。

### Known limitations

- 当前仍使用 SQLite LIKE，不是正式全文检索。
- 外部搜索和抓取适配器只是骨架，没有内置生产调度。
- 未接真实 OpenSearch / Elasticsearch。
- 未接真实授权公众号账号。
- 未实现完整编辑后台、去重合并和冲突审核。

## 0.1.0 - 2026-07-09

初始 MVP。

### Added

- 新增 FastAPI 服务入口。
- 新增 SQLite 数据库 schema。
- 新增 Company、RecruitmentCampaign、JobPosting、ProcessRule、Evidence、Signal、ChangeEvent 数据表。
- 新增演示数据 seed。
- 新增岗位搜索 API。
- 新增岗位详情 API。
- 新增招聘信号 API。
- 新增用户画像匹配 API。
- 新增公告文本导入 API。
- 新增变更记录 API。
- 新增毕业时间匹配逻辑。
- 新增学历等级匹配逻辑。
- 新增城市偏好匹配逻辑。
- 新增笔试状态分类器。
- 新增笔试负担分。
- 新增证据字段。
- 新增变更检测工具。
- 新增静态前端页面。
- 新增 worker 监控骨架。
- 新增单元测试。
- 新增 README、HANDOFF 和 CODEX_TASKS。
- 新增 `.gitignore`、`scripts/dev.sh` 和 `scripts/test.sh`。
