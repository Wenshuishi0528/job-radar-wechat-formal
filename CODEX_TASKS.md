# Codex 后续任务清单

建议一次只做一个任务。每次改完都运行：

```bash
python -m unittest discover -s tests
```

## Task 1：OpenSearch / Elasticsearch 多来源索引

目标：替换 SQLite LIKE 搜索，统一支持招聘信号、岗位和公众号文章检索。

要求：

1. 新增 `services/api/app/search_index.py`。
2. 支持 signal 索引字段：title、description、source_url、source_level、status、detected_at、evidence_text、signal_type。
3. 支持文章索引字段：title、account_name、digest、content_text、publish_at、source_level、quality_score、freshness_score、is_stale、is_blocked_source。
4. 中文分词使用 IK analyzer 或可替换 analyzer 配置。
5. API 查询仍然优先走现有 `/api/signals`、`/api/jobs`、`/api/wechat/articles`，内部可切换 SQLite 或 OpenSearch。
6. 支持按发布时间、新鲜度、来源等级、质量分和状态排序。
7. 增加测试，至少验证三类索引 payload 生成。

## Task 2：多来源 Source Registry 后台

目标：把企业官网、招聘平台、高校就业网、公众号和社区来源从 seed 数据改成后台可维护。

要求：

1. 增加来源列表、创建、编辑、禁用、屏蔽 API。
2. 字段包括 source_name、source_type、base_url、aliases、trust_level、is_allowlisted、is_blocked、rate_limit、notes。
3. 前端增加简易管理页面或 Admin 面板。
4. 搜索结果必须显示来源类型、等级和屏蔽原因。
5. 增加测试。

## Task 3：搜索线索到岗位的审核流

目标：把公众号文章和普通网页信号变成可审核的招聘项目或岗位，但不直接自动发布。

要求：

1. 新增 API：`POST /api/wechat/articles/{id}/create-signal`。
2. 新增 API：`POST /api/signals/{id}/promote`，把 `pending_review` 信号转成招聘项目或岗位草稿。
3. 只有 source_level S/A/B 且未被屏蔽的来源可以进入 promote 流程。
4. 草稿必须保留 source_url、evidence_text、source_level 和人工审核状态。
5. 前端信号卡和文章卡增加审核动作。
6. 增加测试。

## Task 4：真实调度器

目标：让 worker 按 discovery query 定时运行。

要求：

1. 扩展 `services/worker/monitor.py`。
2. 读取 `wechat_discovery_queries`。
3. 支持 check interval、rate limit、失败重试、last_run_at。
4. 默认不要访问外部网络，只有开关启用后运行。
5. 遇到验证码或反自动化页面必须停止该任务并记录失败。
6. 增加测试或 dry-run 模式。

## Task 5：授权公众号官方 API 同步

目标：同步自己授权的公众号已发布文章。

要求：

1. 读取 `wechat_authorized_accounts` 表。
2. 从 `appsecret_env` 对应环境变量取 secret。
3. 调用 access token 和 freepublish/batchget。
4. 转成 ParsedArticle 并写入 wechat_articles。
5. source 设置为 `wechat_official_api`，source_level 应为 S。
6. 不要用于非授权公众号。
7. 增加 mock 测试，不做真实网络调用。

## Task 6：Firecrawl / Tavily 可选发现器

目标：把第三方搜索 API 做成补充来源，不替代当前无 API 的个人搜索流。

要求：

1. 新增 `services/api/app/external_search_adapters.py`。
2. Firecrawl 和 Tavily 都从环境变量读取 API key。
3. 查询必须支持 `source_scope`，可限制企业官网、招聘平台、高校就业网或 `mp.weixin.qq.com`。
4. 支持 time_range 或 freshness 参数。
5. 结果只进入 candidate 或 signal，不直接入正式岗位库。
6. 增加测试，使用 mock response。

## Task 7：公众号文章去重和冲突合并

目标：处理同一文章多个 URL 或多个来源重复发现。

要求：

1. 规范化 `/s/{hash}` 和 `/s?__biz=&mid=&idx=&sn=` 两类 URL。
2. 对 canonical_url 做唯一索引。
3. 对 content_hash 相同但 URL 不同的文章写入重复关系。
4. 主记录优先级：S > A > B > C。
5. 保留所有来源作为 evidence 或 sources。
6. 增加测试。

## Task 8：旧文章和低质来源策略升级

目标：减少搜狗旧结果和营销号污染。

要求：

1. 默认只显示 45 天内文章。
2. 高峰期支持近 7 天、近 30 天、近 45 天。
3. 低质关键词命中进入审核队列，不进主搜索结果。
4. 账号 blocklist 优先于关键词。
5. 未知发布时间文章降低排名，并在前端提示“发布时间未知”。
6. 增加质量分解释字段。

## Task 9：保存原始 HTML 快照

目标：让解析结果可追溯。

要求：

1. 新增 `raw_snapshots` 表或对象存储抽象。
2. 保存 source_url、content_hash、fetched_at、parser_version、storage_path。
3. `wechat_articles` 记录 snapshot_id。
4. 前端详情页可显示解析版本和快照时间。
5. 不要在前端直接展示完整 HTML。

## Task 10：SavedSearch

目标：用户可以保存搜索条件。

要求：

1. 在数据库增加 `saved_searches` 表。
2. 字段包含 name、profile_json、filters_json、source_type、created_at、updated_at。
3. source_type 支持 signals、jobs 和 wechat_articles。
4. 新增 API：列表、新增、删除。
5. 前端增加保存搜索按钮。
6. 增加测试。

## Task 11：Application 投递管理

目标：用户可以把岗位加入投递池。

要求：

1. 在数据库增加 `applications` 表。
2. 状态包括 saved、to_apply、applied、assessment、written_test、interview、offer、rejected、withdrawn。
3. 新增 API：列表、新增、更新状态、删除。
4. 前端岗位卡增加“加入投递池”。
5. 增加按截止日期排序。

## Task 12：编辑后台

目标：替代当前简单导入表单。

要求：

1. 新增 `/admin.html`。
2. 页面包含新信号、公众号候选、普通网页候选、低置信度、冲突、疑似关闭、低质来源七个队列。
3. 支持修改字段、确认、驳回、发布。
4. 所有人工修改都写入 audit_logs 表。
5. 增加测试。
