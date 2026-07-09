# Handoff 维护说明

日期：2026-07-09
版本：0.7.0
项目：Job Radar 校招雷达

## 当前状态

仓库已经是可直接使用的个人本地版，而不是演示数据页面。主界面采用左侧设置、右侧网申表格的工作区，支持拖拽改变两侧宽度。用户只需输入条件并点击“搜索并刷新”，系统会先展示本地数据，再运行无 API 密钥的多来源搜索并合并结果。

当前主链路：

1. `/api/opportunities` 统一返回具体岗位和招聘项目。
2. `source_registry.py` 提供 58 个已知官方来源及公司别名。
3. Google News RSS 负责稳定发现近期中文校招公告。
4. Google、Bing 普通网页搜索负责补充官网、招聘平台、高校、社区和开源来源。
5. 搜狗微信作为公众号专项通道保留。
6. `web_search_importer.py` 做相关性过滤、公司识别、字段抽取、来源匹配和跨媒体去重。
7. `repository.py` 负责入库、状态维护、统一筛选和过期处理。

旧版示例岗位和示例公众号文章会在启动时定向清理，不再自动 seed。

## 运行与验证

最简单的启动方式是双击：

```text
START_HERE.command
```

手动启动：

```bash
cd /Users/apple/Downloads/job-radar-wechat-formal
source .venv/bin/activate
JOB_RADAR_PERSONAL_MODE=1 \
ENABLE_WEB_SEARCH_IMPORT=1 \
ENABLE_WECHAT_PUBLIC_FETCH=1 \
ENABLE_SOGOU_DISCOVERY=1 \
uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

验证命令：

```bash
.venv/bin/python -m unittest discover -s tests
node --check apps/web/app.js
curl -fsS http://127.0.0.1:8000/api/health
```

## 关键文件

- `services/api/main.py`：FastAPI 路由、启动清理和静态前端挂载。
- `services/api/app/source_registry.py`：公司别名、企业类型、行业和官方招聘地址。
- `services/api/app/web_search_importer.py`：Google News、Google、Bing、搜狗微信发现和导入。
- `services/api/app/repository.py`：公司、项目、岗位、证据、信号、变更和统一机会查询。
- `services/api/app/wechat_articles.py`：公众号文章解析、去重、质量和新鲜度。
- `apps/web/index.html`：工作区和语义化网申表格。
- `apps/web/app.js`：统一搜索、筛选、排序、画像匹配和自动刷新。
- `apps/web/styles.css`：桌面、手机和可拖拽布局。
- `tests/test_opportunities.py`：过期过滤、项目去重和统一表格测试。
- `tests/test_web_search_importer.py`：联网结果解析、相关性过滤和导入测试。

## 数据规则

`JobPosting` 只用于已经抽取到明确岗位名称的结果。只能确认招聘活动时使用 `RecruitmentCampaign`，前端标为“招聘项目”，不得补造岗位名。

状态口径：

- 截止日期早于今天：`closed`。
- 有明确开放依据：`open`。
- 没有截止日期且没有届别依据：`pending_review`。
- 默认列表隐藏 `closed` 和 `expired`，用户可手动显示过期记录。

Google News 的同一公司、届别和招聘类型会跨发布媒体合并。匹配到官方来源时优先提供官网入口；未匹配到官方来源时只保留原公告链接和较低来源等级。

## 公众号边界

搜狗微信发现功能仍在，但不会使用个人微信 Cookie、`appmsg_token`、验证码识别、代理池或中间人抓包。遇到验证码、登录确认、异常流量或访问拒绝时停止该来源，并把错误显示给用户。

授权公众号 API 只用于同步自己或合作方授权的公众号，不是全网搜索接口。公众号文章是可追溯线索，不能直接替代企业官网的投递结论。

## 已知限制

1. 全网招聘没有统一开放接口，无法保证互联网中每个岗位都被发现。
2. 动态渲染、登录墙、验证码和搜索引擎地区差异会影响 Google、Bing、搜狗的覆盖率。
3. 规则抽取对复杂表格、图片公告和附件 PDF 的岗位明细识别有限。
4. 目前是用户触发加每日本机刷新，没有常驻后台调度和系统通知。
5. SQLite 适合个人本地使用，不适合多用户并发部署。
6. 公众号结果取决于搜狗微信当前可访问性；为空时前端显示真实空状态。
7. 尚未提供收藏、投递进度、截止提醒、CSV 导出和日历订阅。

## 下一步优先级

P0：

1. 为官方来源增加自动健康检查和失效地址替换。
2. 增加收藏、投递状态、备注和截止提醒。
3. 增加 CSV/Excel 导出和日历订阅。
4. 增加 PDF、图片 OCR 与复杂职位表解析。

P1：

1. 增加可配置的定时刷新 worker 和失败重试。
2. 增加来源审核、公司别名合并和冲突处理界面。
3. 增加多个用户画像和保存搜索。
4. 在数据量明显超过 SQLite 能力后再评估全文搜索引擎。

维护原则是优先保证结果真实、来源可追溯、过期可识别，再扩大覆盖率。不要以增加结果数量为理由放松相关性和证据约束。
