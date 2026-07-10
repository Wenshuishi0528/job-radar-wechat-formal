# Job Radar 校招雷达

版本：0.8.0
日期：2026-07-09

Job Radar 是面向个人本地使用的校招机会聚合工具。输入“秋招”“实习”“国家能源集团”等条件后，页面会先显示本地已有结果，再自动联网刷新，并把具体岗位和只能确认到招聘项目的公告统一整理成可筛选、可排序的“网申表格”。

普通使用不需要 Google、Bing、搜狗或第三方搜索 API 密钥，也不需要手动导入数据。手动导入只作为特殊页面无法自动解析时的备用入口。

## 一键启动

在 macOS Finder 中双击：

```text
START_HERE.command
```

脚本会自动创建 Python 环境、安装依赖、开启个人本地模式、选择可用端口并打开浏览器。默认地址通常是：

```text
http://127.0.0.1:8000
```

保持启动脚本打开的 Terminal 窗口运行；关闭窗口或按 `Control-C` 会停止服务。

## 使用方式

1. 在左侧输入关键词。可使用公司、行业、城市、届别、秋招、春招或实习等条件。
2. 点击“搜索并刷新”。本地结果会立即出现，联网结果完成后自动合并。
3. 在右侧“网申机会”表格中排序、筛选并打开官网或公告。
4. 展开“个人匹配设置”，粘贴简历文本即可按本地规则给全部机会排序，不上传简历、不需要 AI API。
5. 点击每条机会的“记录”，保存收藏、准备中、已投递、测评、面试、Offer 等进度和备注。
6. 拖动左右区域之间的分隔条调整宽度；需要离线整理时可导出 CSV。
7. “公众号文章”页只显示已经成功采集并校验的公开文章；搜不到时会明确显示空状态，不生成假数据。

页面还提供“24h 最新”“27届热门秋招”“国企央企”“实习”等快捷筛选。默认每天自动刷新一次最近使用的搜索条件。

## 搜索与数据来源

当前主流程按以下顺序工作：

1. 查询本地结构化岗位和招聘项目。
2. 公司名搜索匹配对应官网；“秋招”“校招”“实习”等泛词会遍历内置的 58 个企业官网、政府招聘页和招聘平台入口。
3. 使用 Google News RSS 发现近期中文招聘公告，不需要 API 密钥。
4. 根据用户选择，用 Google 或 Bing 普通网页搜索补充企业官网、招聘平台、高校就业网、社区和开源来源。
5. 使用搜狗微信新版结果页保留公众号专项发现能力，并读取标题、摘要、公众号名和发布时间。
6. 抓取公开页面并抽取公司、岗位、招聘批次、届别、城市、截止日期、官网和公告证据。
7. 依据公司、届别和招聘类型去重，避免同一公告被多个媒体重复占满表格。

搜索结果分为两类：

- `岗位`：页面中已经抽取到明确岗位名称和公司。
- `招聘项目`：能够确认公司正在招聘，但原页面尚未公开或无法稳定抽取岗位明细。

系统不会把招聘项目伪造成具体岗位。已过截止日期的记录默认隐藏；没有截止日期且没有届别依据的旧记录显示为“待确认”。

Google、Bing 和搜狗可能因为地区、验证码、动态页面或搜索服务限制返回较少结果。系统不会绕过验证码、登录或网站访问控制；失败时保留本地结果，并在页面显示具体来源错误。Bing 公共搜索若返回无关页面会直接标记为通道异常，不把垃圾链接计入结果数。

## 主要能力

- 单一搜索入口，同时完成本地查询和联网刷新。
- 网申表格展示公司、岗位/项目、批次、城市、截止日期、来源等级和操作入口。
- 关键词、城市、届别、批次、企业类型、行业、岗位方向、专业、来源等级、新鲜度、投递状态和过期状态筛选。
- 表格列排序、分页、CSV 导出、左右面板拖拽、桌面与手机响应式布局。
- 本地简历文本匹配，以及毕业时间、学历、目标城市和笔试偏好的具体岗位资格判断。
- 收藏、准备中、已投递、测评、面试、Offer、未通过、放弃、备注和下一步日期跟踪。
- 招聘公告文本结构化导入，作为自动搜索失败时的备用工具。
- 公众号公开文章解析、去重、质量分、新鲜度和搜狗微信发现。
- 来源证据、招聘变更记录和过期状态维护。
- 启动时清理旧版演示数据，不再自动生成示例岗位或示例公众号文章。

## 手动启动

```bash
cd /Users/apple/Downloads/job-radar-wechat-formal
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
JOB_RADAR_PERSONAL_MODE=1 \
ENABLE_WEB_SEARCH_IMPORT=1 \
ENABLE_WECHAT_PUBLIC_FETCH=1 \
ENABLE_SOGOU_DISCOVERY=1 \
uvicorn services.api.main:app --host 127.0.0.1 --port 8000
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

运行测试：

```bash
.venv/bin/python -m unittest discover -s tests
node --check apps/web/app.js
```

## 主要 API

```text
GET  /api/health
GET  /api/opportunities
GET  /api/jobs
GET  /api/jobs/{job_id}
POST /api/jobs/auto-search
POST /api/match
POST /api/opportunities/match
PUT  /api/tracker/{record_type}/{record_id}
DELETE /api/tracker/{record_type}/{record_id}
POST /api/admin/import-text
GET  /api/changes
GET  /api/sources/registry

GET  /api/wechat/articles
GET  /api/wechat/articles/{article_id}
POST /api/wechat/ingest-url
POST /api/wechat/auto-search-import
GET  /api/wechat/search-links
GET  /api/wechat/config
```

## 项目结构

```text
apps/web/                               静态前端
services/api/main.py                    FastAPI 入口
services/api/app/repository.py          岗位、项目、证据和统一查询
services/api/app/source_registry.py     官方来源注册表
services/api/app/web_search_importer.py 联网发现、解析、导入和去重
services/api/app/wechat_articles.py     公众号文章索引
services/worker/                        后续定时监控任务
tests/                                  单元测试
HANDOFF.md                              维护说明
CHANGELOG.md                            版本记录
```

## 本地数据与边界

数据默认保存在：

```text
services/api/data/job_radar.sqlite3
```

当前版本适合个人本地使用，不是高并发招聘平台。全网招聘信息没有统一开放接口，搜索覆盖率会受到网页可访问性、动态渲染、搜索收录和来源更新速度影响，因此“全网”应理解为多来源尽量覆盖，而不是保证抓到互联网中的每一个岗位。

与求职方舟 AI 相比，0.8.0 已具备相近的网申表格主流程、复合来源、简历排序和投递跟踪，但不具备其公开宣称的大规模长期岗位库、数千站点持续扫描、浏览器自动网申、公司信用数据或大模型服务。Job Radar 的定位是免费、无 API、数据留在本机的个人工具；招聘项目和具体岗位严格区分，不能解析出的岗位不会补造。

不要向程序提供个人微信 Cookie、登录令牌、验证码或招聘网站账号。公众号与普通网页内容都作为可追溯信息源，最终投递前应以企业官网为准。

## 许可证

本项目以 Creative Commons Attribution-NonCommercial 4.0 International（CC BY-NC 4.0）发布。

你可以复制、分享、修改和继续开发，但必须保留署名，并且不得用于商业用途。完整条款见 `LICENSE`。
