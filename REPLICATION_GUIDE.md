# OpenRouter 账户看板：完整复刻指南

本文面向希望从空目录重建本项目的开发者，说明系统架构、数据流、关键计算逻辑、接口契约、前端行为、测试与部署。目标不是只复刻页面外观，而是复刻一个可以安全部署、持续运行的 OpenRouter 账户监控看板。

> 本文中的域名、目录、口令和 API Key 都是占位值。不要把真实 OpenRouter Key、访问口令、`config.json`、`accounts.json`、`runtime_keys.json`、`daily_baseline.json` 或 `widget_readonly_token` 提交到 Git。

## 1. 项目目标与功能范围

本项目是一个无数据库、可安装为 PWA 的 OpenRouter 账户看板：

- 展示账户余额、累计消费、本月消费、今日消费。
- 展示近 30 天消费趋势、按 App 的消费分布、模型消费排行和完整模型消费明细。
- 管理多个 OpenRouter 账户查询 Key：新增前校验、切换、重命名、删除；浏览器只能看到 Key 脱敏掩码。
- 为每个账户单独管理模型推理 Key；可检查 Pi Agent 与 Gateway 当前配置所匹配的账户和 Key 类型，并可一键注入到 Pi Agent、Gateway 全局上游或两者，实现 API Key 的快速更新/切换。
- 展示主流厂商最新模型新闻滚动条，以及 GPT / Claude 最新一代模型的价格对比。
- 展示 OpenRouter 模型目录中 Artificial Analysis 的 `Intelligence Index`；上游未提供时显示“—”。
- 支持 USD/CNY 切换、深浅主题、余额与消费预警、自动刷新、手机响应式布局及 PWA 安装。

### 技术选型

- 后端：Python 3 + 标准库 `http.server`，唯一第三方依赖为 `requests`。
- 前端：单页 HTML/CSS/原生 JavaScript，图表使用本地静态资源 Chart.js 4.4.4，无前端构建系统。
- 持久化：JSON 文件；无 SQL/NoSQL 数据库。
- 进程管理：systemd；HTTPS 由 Caddy、Nginx 或其他反向代理提供。

## 2. 系统结构与请求流

```text
手机 / 桌面浏览器
  ├─ HTML、PWA 文件、图标 ───────────────> Python HTTP 服务
  └─ /api/*?token=<看板访问口令> ────────> Python HTTP 服务
                                                ├─ 本地 JSON：accounts.json / daily_baseline.json
                                                └─ HTTPS ─> OpenRouter API
                                                             credits / key / activity
                                                             analytics/query / models
```

浏览器只持有看板访问口令，不持有 OpenRouter Key。普通看板请求由后端读取账户查询 Key 并调用 OpenRouter，再把聚合数据返回浏览器。推理 Key 是另一类凭证，单独保存在服务器 `runtime_keys.json` 中，不返回前端明文。

推理 Key 的管理与部署数据流如下：

```text
管理界面（Bearer 鉴权）
  ├─ 保存/覆盖 Key ─> 后端调用 OpenRouter /key 校验（不发模型请求）
  │                    └─> runtime_keys.json（权限 600）
  ├─ 检查当前 Key ──> 读取 Pi auth.json / 服务环境与 Gateway 容器环境
  │                    └─> 与账户查询 Key、已保存推理 Key 比对，只返回账户名/类型/掩码
  └─ 一键注入 ──────> Pi auth.json + 重启 pi-agent.service
                       Gateway .env + 重建 gateway 容器 + 健康检查
```

Gateway 当前只有一个全局 `OPENROUTER_API_KEY`，因此切换 Gateway 目标会影响所有经由它调用的客户端；Gateway 的 `CLIENT_API_KEYS` 不变。注入不会验证模型调用是否成功，也不会创建或撤销 OpenRouter 平台上的 Key。

`server.py` 直接监听 `0.0.0.0:<PORT>`，自身不提供 TLS。公网部署时应由 HTTPS 反向代理转发到本机 Python 端口，并通过安全组/防火墙阻止外部直接访问该端口。

## 3. 文件职责

| 路径 | 职责 |
|---|---|
| `server.py` | HTTP 路由、访问口令校验、静态资源发送、JSON 响应与 gzip |
| `openrouter_api.py` | OpenRouter 上游请求、消费聚合、模型筛选、缓存与降级 |
| `accounts.py` | 多账户查询 Key 初始化、JSON 持久化、脱敏和稳定账户 ID |
| `runtime_keys.py` | 按账户 ID 单独保管模型推理 Key；原子写入、权限 600、只向界面提供掩码 |
| `key_injection.py` | 检查运行中 Pi/Gateway 配置并匹配账户；安全替换目标凭证、重启服务、失败时回滚 |
| `baseline.py` | 每账户每日累计消费基准及历史差分计算 |
| `baseline_capture.py` | 定时读取每个账户的累计消费并记录 UTC 日界基准 |
| `config.py` | 读取配置、计算数据文件绝对路径和默认值 |
| `logging_setup.py` | 统一输出到 stderr，便于 journald 收集 |
| `config.json.example` | 无真实密钥的配置模板；复制为本地 `config.json` 后填写 |
| `static/index.html` | 完整单页界面、样式、图表和前端交互逻辑 |
| `static/manifest.json` | PWA 名称、显示模式、图标等元数据 |
| `static/sw.js` | 注册 Service Worker；当前仅透传网络，不做离线缓存 |
| `static/logos/` | 模型厂商及 App 图标 |
| `tests/` | 账户/推理 Key 脱敏、Key 匹配与注入回滚、管理 API 鉴权、基准历史和模型筛选等离线测试 |

`config.json`、`accounts.json`、`runtime_keys.json`、`daily_baseline.json` 和 `widget_readonly_token` 都是运行时数据并已列入 `.gitignore`。其中账户查询 Key 与推理 Key 都以明文保存在服务器文件中；首次启动后确认文件由服务用户拥有，权限限制为仅服务用户可读写（密钥文件为 `0600`）。

## 4. 从零实现的推荐顺序

1. 建立配置模块和 JSON 路径常量。
2. 完成账户查询凭证存取、脱敏和账户 ID 派生。
3. 完成推理 Key 独立保管、覆盖、删除和脱敏列表。
4. 完成基准历史的原子写入、迁移与纯函数日期差分。
5. 完成 OpenRouter API 客户端、单账户汇总和缓存。
6. 编写普通看板 API、推理 Key 管理/检查/注入接口及静态文件安全路径校验。
7. 完成响应式 HTML 界面、账户管理、当前 Key 检查和一键注入交互。
8. 编写 Pi/Gateway 凭证检查、固定目标更新、服务重启、健康检查和回滚逻辑。
9. 添加 PWA manifest、图标与 Service Worker。
10. 为账户、Key 脱敏/权限、检查/注入、基准计算和模型筛选编写测试。
11. 在 HTTPS 反向代理或可信 VPN 后部署，并设置 systemd 与基准定时任务。

## 5. 配置与初始化

### 配置文件

```bash
cp config.json.example config.json
chmod 600 config.json
```

模板结构：

```json
{
  "openrouter_api_keys": [
    { "name": "主账户", "api_key": "YOUR_OPENROUTER_API_KEY" }
  ],
  "dashboard_token": "替换为高熵随机访问口令",
  "port": 8080,
  "usd_to_cny_rate": 7.1
}
```

配置项：

- `openrouter_api_keys`：可选账户数组，元素可为 `{ "name", "api_key" }`；也接受字符串 Key 数组。
- `openrouter_api_key`：兼容旧版的单 Key 字段；只有未提供有效 `openrouter_api_keys` 时才使用。
- `openrouter_api_key_name`：旧版单 Key 的可选名称。
- `dashboard_token`：所有受保护看板 API 共用的口令。生产环境必须替换默认值 `changeme`。
- `port`：监听端口；模板使用 `8080`，无配置时 `config.py` 默认 `8899`。
- `usd_to_cny_rate`：美元兑人民币展示汇率，默认 `7.1`。金额内部仍以 USD 计算，前端转换展示。

也可使用环境变量 `OR_DASHBOARD_TOKEN` 设置看板访问口令；它优先于默认值，但 `config.json` 中非空的 `dashboard_token` 优先级更高。配置文件中的 `config.json` 由 `config.py` 在进程启动时读取，修改后要重启服务。

### 账户初始化与存储

首次读取账户列表时，`accounts.py` 会按顺序：

1. 若 `accounts.json` 存在且格式有效，直接使用它。
2. 否则从 `config.json` 的 Key 配置生成账户列表并写入 `accounts.json`。
3. 每个账户的 ID 为 `acct_` 加 API Key 的 SHA-1 前 10 位十六进制摘要；它只用于稳定标识，不是认证凭据。
4. API 返回账户的 `id`、`name`、`key_masked`，绝不返回 `api_key`。

第一次导入后，`accounts.json` 成为运行时账户查询凭证的主存储。之后仅修改 `config.json` 不会覆盖已有账户文件；新增/删除/重命名应通过看板账户管理功能完成。`accounts.json` 含明文 Key，不可公开或提交。

### 推理 Key 的独立保管

推理 Key 不覆盖 `accounts.json` 中用于查询余额/消费的 Key，而是存入独立的 `runtime_keys.json`，以稳定的看板账户 ID 关联：

```json
{
  "version": 1,
  "keys": {
    "acct_0123456789": {
      "api_key": "YOUR_OPENROUTER_INFERENCE_KEY",
      "updated_at": 1790470000
    }
  }
}
```

首次保存时文件自动创建，使用原子替换写入并设为 `0600`；文件已加入 `.gitignore`。API 只向浏览器返回 `present`、掩码和更新时间，不返回 Key 明文。覆盖只替换本地保管值；删除只删本地副本，不调用 OpenRouter 撤销接口。新增/覆盖前调用 `GET /api/v1/key` 校验凭证，不发起计费模型请求。

推理 Key 管理接口默认关闭。仅在确认受信任访问路径后，通过环境变量 `OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1` 显式启用；`config.py` 在服务启动时读取该开关，修改后需要重启服务。

### 数据文件格式

`accounts.json` 的简化示意（Key 为占位符）：

```json
{
  "accounts": [
    { "id": "acct_0123456789", "name": "主账户", "api_key": "YOUR_OPENROUTER_API_KEY" }
  ],
  "active": "acct_0123456789"
}
```

`daily_baseline.json` 按账户保留当前日基准和最近最多 70 条历史：

```json
{
  "accounts": {
    "acct_0123456789": {
      "date": "2026-09-27",
      "total_usage_at_midnight": 123.45,
      "captured_at": 1790470000,
      "history": [
        { "date": "2026-09-26", "total_usage": 120.00 },
        { "date": "2026-09-27", "total_usage": 123.45 }
      ]
    }
  }
}
```

账户、推理 Key 与基准存储模块都先写入同目录临时文件，再用 `os.replace` 替换目标文件，避免进程中断时留下半份 JSON；密钥文件保持 `0600`。基准模块还能把旧单账户格式迁移到多账户格式。

## 6. 后端 API 契约

普通看板业务 API 使用 `?token=<dashboard_token>`；推理 Key 保存、删除、检查和注入接口使用 `Authorization: Bearer <dashboard_token>`，并要求显式启用 `OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1`。查询参数中的口令会出现在 URL 中；浏览器提交 Key 的请求正文即使改用 Bearer 鉴权，HTTP 仍是明文传输，因此公网部署必须使用 HTTPS 或可信 VPN，并避免代理记录完整查询字符串。

| 方法与路径 | 鉴权 | 作用 |
|---|---|---|
| `GET /healthz` | 无 | 返回 `{"ok": true, "time": <Unix 秒>}` |
| `GET /`、`GET /index.html` | 无 | 返回 `static/index.html`，`Cache-Control: no-cache` |
| `GET /api/accounts?token=…` | 是 | 返回脱敏账户列表和活动账户 ID |
| `POST /api/accounts?token=…` | 是 | 校验 OpenRouter Key 后新增账户，JSON body 为 `{ "name": "…", "api_key": "…" }` |
| `POST /api/accounts/rename?token=…` | 是 | JSON body 为 `{ "id": "acct_…", "name": "新名称" }` |
| `DELETE /api/accounts?id=…&token=…` | 查询口令 | 删除账户；至少保留一个账户，并删除其本地关联推理 Key |
| `POST /api/accounts/inference-key` | Bearer + 功能开关 | 校验并新增/覆盖账户推理 Key；只调用 OpenRouter `/key`，不发模型请求 |
| `DELETE /api/accounts/inference-key?id=…` | Bearer + 功能开关 | 删除该账户本地推理 Key；不撤销 OpenRouter 上的 Key |
| `GET /api/accounts/injection-status` | Bearer + 功能开关 | 读取 Pi Agent 与运行中 Gateway 的凭证配置，与账户查询/推理 Key 比对；只返回账户名、类型和掩码 |
| `POST /api/accounts/inject` | Bearer + 功能开关 | JSON body `{ "account_id": "acct_…", "target": "pi" | "gateway" | "both" }`；更新凭证并重启/健康检查 |
| `GET /api/summary?token=…[&account=…]` | 查询口令 | 返回余额、今日/月消费、趋势、App 和模型排行 |
| `GET /api/app_usage_today?token=…[&account=…]` | 是 | 返回今日按 App 汇总的调用/Token/消费，用于弹窗 |
| `GET /api/app_usage_month?token=…[&account=…]` | 是 | 返回本月按 App 汇总的数据 |
| `GET /api/latest_models?token=…` | 是 | 返回按厂商归类的最新模型新闻 |
| `GET /api/model_prices?token=…[&refresh=1]` | 是 | 返回 GPT/Claude 新一代模型价格、上下文及 Intelligence Index；`refresh=1` 强制更新 |

API 错误使用 JSON `{ "error": "…" }` 和适当 HTTP 状态码，例如未授权 `401`、参数或业务错误 `400`、重复账户 `409`、不存在 `404`。HTTP 服务禁用了默认访问日志；应用日志仅记录失败原因，不应自行记录 API Key、口令或请求正文。

### `/api/summary` 的主要返回结构

```json
{
  "generated_at": 1790470000,
  "account_id": "acct_0123456789",
  "account_name": "主账户",
  "key_masked": "sk-or-v1-a...1234",
  "key_info": { "label": "…", "is_free_tier": false, "usage": 0, "limit": null, "limit_remaining": null },
  "exchange_rate": { "usd_to_cny": 7.1 },
  "account": { "total_credits": 150, "remaining": 120, "total_usage": 30, "month_usage": 4, "today_usage": 0.5 },
  "today_usage": 0.5,
  "today_usage_source": "analytics",
  "month_usage": 4,
  "degraded": [],
  "daily_series": [{ "date": "2026-09-27", "usage": 0.5 }],
  "model_ranking": [{ "model": "vendor/model", "usage": 0.5, "requests": 2, "prompt_tokens": 100, "completion_tokens": 50 }],
  "app_ranking": [{ "app": "Claude Code", "usage": 0.5, "requests": 2, "tokens_total": 150 }]
}
```

此 JSON 只用于说明字段，真实值由账户和 OpenRouter API 决定。上游部分接口失败时，`degraded` 列出失败项；无法计算的金额使用 `null`，不能把“取数失败”伪装成 0。

## 7. OpenRouter 数据获取与关键计算

### 上游接口

所有请求经全局复用的 `requests.Session` 发送，挂载连接池（10 个连接池、每池最大 20 个连接），HTTP 请求超时默认 15 秒。

| OpenRouter API | 用途 |
|---|---|
| `GET /api/v1/credits` | `total_credits` 与累计 `total_usage`；计算余额 `total_credits - total_usage`，并提供日基准兜底 |
| `GET /api/v1/key` | Key 标签、额度/免费档等信息及新增账户时的 Key 校验 |
| `GET /api/v1/activity` | 近 30 天逐日消费、模型调用次数、输入/输出 Token 和模型排行 |
| `POST /api/v1/analytics/query` | 账户总消费及按 App 的消费、请求数、Token 汇总 |
| `GET /api/v1/models` | 新闻栏、模型价格、上下文长度及 `benchmarks.artificial_analysis.intelligence_index` |

`/api/summary` 在最多 6 个线程中并发请求 credits、key、activity、近 30 天 App Analytics、今日 Analytics、本月 Analytics。任一独立上游失败时尽量返回仍可用的数据，而不是整体报错。

### 今日与本月消费

项目采用 OpenRouter 的 UTC 自然日/月：UTC 每日 00:00 切日，对应北京时间每日 08:00；UTC 每月 1 日 00:00 切月。

- 今日消费：优先 Analytics，区间为当日 UTC 00:00 至当前 UTC 时间；失败时使用每日基准差值，最后退回 `/activity` 当日值。
- 基准值保存累计 `total_usage`，每日消费兜底为 `当前 total_usage - 当日 00:00 基准`。不使用剩余额度作基准，因此充值不会改变差值逻辑。
- 本月消费：优先 Analytics；失败时用 `/activity` 与每日基准历史重建各日消费，并确保本月累计不低于今日消费。
- Analytics 查询必须显式设置 `granularity`（按小时或按天）。该项目这样做是为避免自定义起止时间被服务端隐式取整到 UTC 日界，造成跨时段重复计入。
- 定时基准每个账户独立记录。连续两日基准差值才作为前一日消费；有日期缺口时跳过，不把多日消费误归到一天。

若服务器时区为 UTC，定时任务建议在 UTC 00:01 运行；若时区为 Asia/Shanghai，可在当地 08:01 运行。两者均是在 UTC 日界后约一分钟采样。示例：

```cron
# 主机使用 UTC
1 0 * * * /path/to/openrouter-dashboard/.venv/bin/python /path/to/openrouter-dashboard/baseline_capture.py >> /var/log/or-dashboard-baseline.log 2>&1

# 或主机使用 Asia/Shanghai；二选一，不要同时配置
# 1 8 * * * /path/to/openrouter-dashboard/.venv/bin/python /path/to/openrouter-dashboard/baseline_capture.py >> /var/log/or-dashboard-baseline.log 2>&1
```

即使任务漏运行，当天首次生成 summary 时也会尝试补写当前基准，因此该日剩余时间仍有兜底；但漏掉日界采样可能影响跨日/月历史的精确回补。

### 趋势、模型、App 数据

- 趋势图以 `/activity` 按日期聚合 `usage`，按日期排序后输出近月时间序列。
- 模型排行把 `/activity` 各模型的 usage、请求数、prompt/completion tokens 聚合，按消费排序；首页 Top 5 柱图只画消费大于 0 的模型，明细列表保留全部模型。
- App Analytics 请求使用 `metrics`（`total_usage`、`request_count`、`tokens_total`）、`dimensions: ["app"]`、显式 `granularity` 和自定义 `time_range`，后端对多个时间桶按 App 汇总。
- App 名称缺失时归类为 `Unknown`。厂商/App 图标在前端按名称匹配，找不到时回退默认图标。

### 旗舰模型价格及 Intelligence Index

`/api/model_prices` 从 OpenRouter 官方模型目录中筛选：

1. GPT 家族取 `openai/` 前缀中符合 GPT 版本号的模型；Claude 家族取 `anthropic/` 中符合 Claude 系列版本号的模型。
2. 排除 `~` 别名、带 `:` 的变体；GPT 名称含 Pro 的变体不参与。
3. 只保留检测到的最高主版本，再按同一产品线取发布时间最新者，例如 Opus 同系列只显示最新小版本。
4. OpenRouter 的每 token 价格乘以 1,000,000，统一转换为 USD / 百万 tokens；价格卡始终显示美元，不参与右上角 USD/CNY 切换。全局币种切换只影响账户消费、余额及图表展示。
5. 返回 `context_length` 及 `benchmarks.artificial_analysis.intelligence_index`。分数为可选数据，不进行本地估算、不用模型名称推测；缺失、非数字或非有限值时返回 `null`，前端显示“—”。
6. 每个家族按输出价、输入价、发布时间排序，首项标记为「旗舰」。

OpenRouter 模型目录缓存 1 小时；标题上的刷新按钮通过 `refresh=1` 绕过缓存。`Intelligence Index` 代表上游提供的 Artificial Analysis 指标，并非本项目自行测评，也不保证所有模型都有分数。

### 缓存与并发

| 数据 | 缓存策略 | 备注 |
|---|---|---|
| summary | 每账户 60 秒 | 后端内存缓存；进程重启即清除 |
| 最新模型新闻 | 全局 12 小时 | 不依赖账户 |
| 价格 / benchmarks | 全局 1 小时 | 支持强制刷新 |
| 浏览器汇率/主题/币种/访问口令/账户选择 | `localStorage` | 不包含服务端 OpenRouter Key |

新闻和价格缓存的锁会串行化同一进程中的刷新；summary 缓存锁只保护字典读写，冷缓存时并发请求仍可能重复访问上游。所有缓存仅保存在进程内，不同 worker/多实例之间不共享。部署成多个 Python 实例时，需接受每实例独立缓存或自行引入共享缓存。

## 8. 前端设计规格、视觉与交互

前端集中在 `static/index.html`，无前端构建步骤。复刻时应把这一节当作 UI 验收规格，而不只是“做一个深色数据面板”：布局层级、玻璃材质、字号、间距、各色含义、加载占位和窄屏行为都属于设计的一部分。

### 8.1 整体视觉语言与设计变量

- **整体气质：**克制、简洁、偏原生系统风格的暗色数据看板；使用炭灰玻璃层与细描边，不用大面积高饱和蓝色背景，也不做重渐变/霓虹风格。
- **字体：**`-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", Arial, sans-serif`。数字使用较强字重和固定行高；价格、Token 等数值适合采用 tabular numerals。
- **深色底色：**`--bg: #0f1117`；主文字 `#e6e8ec`，标题白色，说明文字灰紫 `#8b8fa3`，次级文字 `#6b7085`。
- **绿色强调：**`--accent: #4ade80`、`--accent-strong: #22c55e`，用于可用余额、主要操作、近期新品模型名和选中状态；强调色要点到为止。
- **语义色：**消费警告橙 `#ffb347`，危险红 `#ff6b6b`；输入价格沿用绿色，输出价格用橙色。模型 Intelligence Index 使用单独的紫色变量：深色 `#c084fc`、浅色 `#7e22ce`，不与绿/橙/蓝语义撞色。蓝色 `#60a5fa` 只用于模型排行柱图等少量数据图形。
- **玻璃卡片：**半透明炭灰层 `rgba(26,29,41,0.01)`，不支持模糊时回退为 `#1a1d29`；细描边 `rgba(190,194,207,0.14)`，叠加克制的高光渐层、内沿高光与暗色投影；`backdrop-filter: blur(34px) saturate(165%)`，顶部栏模糊强度约 170%。不要用不透明蓝色卡片替代玻璃效果。
- **浅色主题：**底色 `#f3f5f9`，正文 `#232733`，卡片白色半透明，边框 `rgba(174,184,204,0.48)`，绿色强调改为 `#22c55e`，警告色改为 `#d97706`；所有指标都要在浅色背景下有足够对比度。
- **圆角/边框：**标准卡片 18px、窄屏 16px；输入框/小按钮多为 8–10px；边框细而中性，不给每个元素额外加粗描边。

### 8.2 页面从上到下的结构

1. **固定顶部栏（sticky）：**标题“💳 OpenRouter 账户看板”在左；主题和 USD/CNY 切换在右。第二行是账户标签、账户下拉框和“⚙️ 管理”；其后展示账户名、更新时间和接口降级提示。顶部栏吸顶，滚动时保留，使用半透明背景和底部分隔线。
2. **账户余额概览卡：**卡片标题左对齐；右侧并排“一键充值”和轻量“刷新”按钮。下方是一条小号手续费提示，再下方用 2×2/4 列网格展示剩余额度、累计消费、本月累计、今日消费。金额字号约 22px/行高 28px，标签 12px/固定 16px 行高；余额绿色、累计消费橙色，其余金额使用正文色。今日/月金额可点击，点击区域要有 hover/active 反馈和小型点击提示图标。
3. **新品新闻栏：**紧跟概览卡，左右横向滚动；左侧固定绿色圆角“🆕 新品”标签，右侧为单行文字轨道。必须在首次请求前就占据固定高度并显示轻量加载占位；成功、无数据、失败都在原位置替换文字/内容，不能异步插入或移除整个栏造成页面跳动。
4. **近 30 天消费趋势 + App 消费分布：**桌面并排两列，手机纵向堆叠。趋势卡是约 200px 高的 Chart.js 平滑折线图，绿色线和点、透明绿色填充、低对比网格；Y 轴/日期文字随主题变色，直接在曲线附近显示抽样金额标签。App 卡按客户端列出图标、App 名称、消费额、请求数、Token 数和占比。
5. **模型调用排行 Top 5：**单独的横向柱状图卡，仅画消费大于 0 的前五模型；模型名省略长尾，图表高度根据条数增长（每条约 36px，最小 120px），容器最高 420px。
6. **模型消费明细：**全模型清单按消费降序；每行包含模型图标/名、金额、调用次数、输入/输出/总 Token。列表最多约 420px 高，超出后在卡片内滚动，底部使用渐隐遮罩提示尚有内容。
7. **旗舰模型价格对比：**页面底部两列 GPT/Claude 家族，列间有竖向细分隔线。列头显示最新代数胶囊标签；模型行左侧是图标、名称、首位“旗舰”徽标，下面显示 `Intelligence Index` 紫色分数和上下文长度；右侧对齐输入/输出单价，始终以 USD / 百万 tokens 显示，不随全局币种按钮改变。手机端仍保持两列，模型名在上、价格在下，精简字号而不把两家模型改为纵向单列。
8. **页脚：**居中、较淡的小号文字，显示构建维护信息、模型切换历史“Claude Sonnet 5 → DeepSeek V4.1 Flash → GPT-6 Luna”和 GitHub 链接。

### 8.3 间距、尺寸与断点

- 正文字体整体 12–14px；卡片标题 13px；顶部标题手机端 17px、普通视口约 18px；辅助文字 10–12px。
- 基础容器 `max-width: 1100px`，页面水平居中；`>=1200px` 容器最大宽度 1280px。基础容器内边距 12px 16px，卡片之间统一 `gap: 14px`，不要叠加卡片 margin 形成双重间距。
- 一般卡片内边距 16px、圆角 18px；手机 `<=767px` 使用 14px 内边距、16px 圆角，页面左右内边距 12px、纵向卡片间距 10px，趋势图高度 188px，新闻栏约 42px 高。
- `>=768px`：账户统计改为 4 列；趋势和 App 卡并排；桌面页面水平空间增大。`>=1200px` 容器再扩至 1280px。
- **注意现有 CSS 级联细节：**`@media (min-width: 768px)` 中的 header padding/标题字号、卡片 `20px 22px`、登录框宽度/外边距，以及 `@media (min-width: 1200px)` 中的金额字号 `26px` 声明都位于对应基础样式之前，后面的基础规则会覆盖它们。忠实还原当前实际页面时按有效样式复刻；若希望启用这些较大尺寸，应把断点规则移到基础规则之后并重新做截图验收，不要假设它们当前已生效。

### 8.4 各交互组件的细节

- **顶部控件：**主题按钮为无底色、无边框的圆形轻量图标；币种按钮无框、短标签，CNY 激活时使用绿色。汇率说明保留固定高度，USD 时仅隐藏可见性而不是移除空间，防止标题栏跳动。币种按钮只切换账户统计与相关图表，旗舰价格卡始终保持 USD。
- **按钮：**充值按钮用绿色渐层与深色对比文字；刷新按钮为中性半透明小胶囊。hover 轻微提亮/上浮，active 轻微缩放，不出现浏览器默认厚重 3D 按钮样式。
- **余额/警告：**剩余额度低于 USD 9 标红；今日消费超过 USD 50 时金额转警告色并配轻微呼吸感的感叹号。无效/暂缺数据显示“—”，不可显示伪造的 0。
- **点击统计弹窗：**背景用约 55% 黑色遮罩，居中玻璃卡片最大宽约 420px、最高视口高度 80vh；标题栏下有分割线，主体独立纵向滚动，点击遮罩空白处或关闭按钮退出，Esc 也关闭。弹入动画约 0.18 秒。
- **账户管理弹窗：**沿用同一模态框外观；每行区分账户查询 Key 与推理 Key，两者都只显示掩码。推理 Key 表单选择账户后可新增/覆盖，另有本地删除操作。新增的「检查当前 Key」区域读取 Pi/Gateway 当前凭证配置，与账户 Key 比对并显示账户名、Key 类型、来源和掩码；不发模型请求。注入区选择 Pi Agent、Gateway 全局上游或两者，再确认后执行一键注入；需明确展示重启影响及 HTTP 明文测试警告。

**典型操作流程：**「管理」→ 选择账户 → 输入并保存/覆盖推理 Key → 点击「检查当前 Key」确认当前 Pi/Gateway 所属账户 → 选择 Pi Agent、Gateway 或两者 → 点击「注入已保存 Key」并确认。保存时只调用 `/api/v1/key` 校验；注入后 Pi Agent 重启，Gateway 重建并等待健康检查。若本地删除 Key，已注入到服务中的凭证不会自动撤销或清除。
- **登录框：**最大宽 320px、居中玻璃卡片；输入框与绿色全宽按钮上下排列。桌面可加大外边距，不改变手机阅读顺序。
- **新闻交互：**新品项目单行排列、间距约 40px；最近 7 天项目显示 🎉，模型名绿色并链接到 OpenRouter。轨道无可见滚动条；自动滚动约 50px/秒，用户触屏/滚轮/拖拽/键盘交互后停约 1 秒再继续；鼠标可抓取拖动，键盘焦点有绿色 outline。
- **模型名字与图标：**图标默认约 20×20px，圆角 6px，图像 `object-fit: contain` 并留少量内边距；窄屏价格卡图标缩至 18×18px。模型名超宽时单行省略，不能撑破列宽。

### 8.5 加载、动画与无障碍

- 页面主要卡片轻微淡入上移：约 0.35 秒，顶部卡、新闻栏、双列区及其后卡片错开约 0.04–0.2 秒；不要让异步数据返回再触发整块卡片从无到有。
- `prefers-reduced-motion: reduce` 时关闭入场动画、弹窗弹入、警告 pulse 和按钮 transition。
- 列表要区分“加载中…”、“暂无数据”和“加载失败”；上游失败时使用淡色占位或危险色错误，不留空白大洞。
- 可交互统计项、滚动新闻轨道和模型链接提供 hover、active、focus-visible 状态；键盘至少可 Tab 聚焦、Enter 激活、Esc 关闭弹窗。
- `backdrop-filter` 不支持时回退成纯色卡片，保持文字与描边对比。

### 8.6 前端状态与验收清单

- 登录口令键：`or_dashboard_token`；账户选择：`or_dashboard_account`；币种：`or_dashboard_currency`；主题：`or_dashboard_theme`。币种偏好不影响固定以 USD 显示的旗舰模型价格卡。推理 Key 输入仅在提交时留在内存中，发送后清空；任何服务器 OpenRouter Key 都不得写入 `localStorage`、Service Worker 缓存或 API 响应明文。
- 页面初始化先加载账户列表，再启动 summary、新闻和模型价格请求；summary 每 60 秒刷新。页面隐藏时暂停，重新可见时立即刷新一次。
- 图表主题色根据 `html[data-theme]` 更新。折线用单调三次插值避免拐角与过冲，标签 16px，自适应抽样但始终标出最高点与最新点。
- 窄屏需实际检查 390px 宽视口：顶部账户控件不挤出屏幕、统计卡保持两列、新闻栏不撑高、价格卡仍两列、模型长名省略、滚动列表可操作。
- 至少在深色/浅色、手机（约 390px）、平板断点（768px）、大屏（1200px）各截图一次；另外检查新闻加载成功/失败、模型分数缺失、列表为空、弹窗打开和 reduced-motion 状态。对照原页面验证卡片顺序、宽度、颜色语义、边距和滚动行为，而不只检查“能显示”。

PWA 使用 portrait / standalone manifest 和 192/512 图标；页面加载后注册 `/sw.js`。当前 Service Worker 不缓存离线页面，只透传网络，避免旧 HTML/数据长期滞留。

## 9. 本地开发与测试

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install requests
cp config.json.example config.json
# 编辑 config.json：填写 API Key、强访问口令、端口和汇率
python server.py
```

访问 `http://127.0.0.1:8080/`（若配置的端口不同，以 `config.json` 为准）。本地需要测试推理 Key 管理时，先在 `config.json` 中设置非默认 `dashboard_token`，再临时用 `OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1 python server.py` 启动；功能默认关闭，且只能使用临时、低额度测试 Key。无需 API Key 的健康检查：

```bash
curl -fsS http://127.0.0.1:8080/healthz
```

运行纯本地单元测试：

```bash
python -m unittest discover -s tests -t . -v
```

当前测试覆盖：账户与推理 Key 脱敏、权限和账户关联、查询/推理 Key 匹配、注入配置更新与失败回滚、管理接口鉴权、日期边界、基准差分、模型版本/产品线筛选、价格单位转换及 Intelligence Index 缺失值。单元测试不访问 OpenRouter、不使用真实账户 Key，也不会重启实际 Pi/Gateway 服务。提交前建议同时执行：

```bash
python -m compileall -q .
python -m unittest discover -s tests -t . -v
git diff --check
```

如果改了 `static/index.html` 中的内联 JavaScript，可从 HTML 提取脚本后用 `node --check` 做语法检查；Node 仅用于可选的开发校验，不是运行依赖。

## 10. Linux 部署复刻

### 安装代码与依赖

```bash
sudo useradd --system --create-home --home-dir /opt/or-dashboard or-dashboard
sudo install -d -o or-dashboard -g or-dashboard /opt/or-dashboard/app
# 将 Git checkout 或发布文件复制到 /opt/or-dashboard/app
sudo chown -R or-dashboard:or-dashboard /opt/or-dashboard/app
cd /opt/or-dashboard/app
sudo -u or-dashboard python3 -m venv .venv
sudo -u or-dashboard .venv/bin/pip install requests
sudo cp config.json.example config.json
sudo chown or-dashboard:or-dashboard config.json
sudo chmod 600 config.json
```

编辑 `config.json` 后再启动。确保 `or-dashboard` 用户可写项目运行目录，因为账户和基准 JSON 会保存在其中；更严格的部署可将数据目录单独挂载并在代码中调整对应路径常量。

### systemd

创建 `/etc/systemd/system/or-dashboard.service`：

```ini
[Unit]
Description=OpenRouter Account Dashboard
After=network.target

[Service]
Type=simple
User=or-dashboard
Group=or-dashboard
WorkingDirectory=/opt/or-dashboard/app
ExecStart=/opt/or-dashboard/app/.venv/bin/python /opt/or-dashboard/app/server.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

配置文件中存有上游 API Key，建议限制为服务用户可读，并确保 systemd 服务用户可信。上面的 `or-dashboard` 非 root 示例仅适用于普通看板功能；当前推理 Key 注入实现还要写入 Pi/Gateway 的 root 配置并重启目标服务，因此未经权限适配时，非 root 服务不能执行注入。

### 可选：启用推理 Key 检查与一键注入

管理接口默认关闭。仅在完成 HTTPS/可信 VPN 和访问控制后，在 systemd `[Service]` 中显式配置：

```ini
Environment=OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1
```

之后执行 `systemctl daemon-reload` 并重启看板。这个开关只启用 HTTP API，不授予文件或服务权限。

当前 `key_injection.py` 的参考部署目标是：

- Pi 凭证：`/root/.pi/agent/auth.json`；重启 `pi-agent.service`。
- Gateway 凭证：`/root/openrouter-api-gateway/.env` 中的 `OPENROUTER_API_KEY`；用 `docker-compose up -d --force-recreate gateway` 重建并等待健康检查。

在其他机器复刻时，先调整 `key_injection.py` 顶部的路径与服务名，并明确授权运行账户访问这些目标。当前检查可识别 Pi 进程环境中的 `OPENROUTER_API_KEY`，但注入器只更新 `auth.json`；若检查显示 Key 来源为进程环境，应先协调该环境变量，否则环境中的 Key 仍会被检查到。不要为图方便给公网 HTTP 处理进程开放任意 root/shell 权限；生产部署应把固定的“写入指定凭证 + 重启白名单服务”拆到受限 helper/sudoers 规则中，或使用等价的最小权限方案。Pi Agent 或 Gateway 重启时会短暂中断服务；选择 Gateway 目标会切换所有 Gateway 客户端共用的上游账户，不修改 `CLIENT_API_KEYS`。

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now or-dashboard.service
sudo systemctl status or-dashboard.service
sudo journalctl -u or-dashboard.service -f
```

### HTTPS 反向代理

推荐用 Caddy 自动签发证书。示例 `Caddyfile`：

```caddyfile
dashboard.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

前提是域名 A/AAAA 记录指向服务器且 TCP 80/443 可达。由于 Python 服务当前监听所有接口，应在云安全组/主机防火墙阻止公网直接访问 8080，仅开放 SSH 与代理所需的 80/443；如有条件，也可修改服务器监听地址为 `127.0.0.1`。登录口令放在 URL 查询参数中，TLS 和代理日志脱敏尤其重要。

### 防火墙与验证

- 仅对可信来源开放 SSH。
- 推荐公网只开放 TCP 80/443；不需要把 Python 服务端口暴露到公网。
- 确认 `https://dashboard.example.com/healthz` 返回 `ok: true`，再从手机浏览器登录。
- PWA 的 Service Worker 需要安全上下文；公网使用 HTTPS，localhost 本地开发例外。

## 11. 复刻者常见问题

| 现象 | 排查方向 |
|---|---|
| 登录总是 401 | 检查 `dashboard_token` 与 URL token 是否一致；配置改动后重启服务；不要使用默认口令上线 |
| `/api/accounts` 返回空列表 | 检查 config 中 Key 字段拼写；确认 `accounts.json` 是否已经创建并成为运行时主数据 |
| 推理 Key 管理接口返回 401 | 检查请求使用 `Authorization: Bearer`、dashboard token 是否为非默认值，以及 `OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1` 是否已配置并重启 |
| 检查结果显示未匹配账户 | 比对只覆盖 `accounts.json` 查询 Key 与 `runtime_keys.json` 推理 Key；确认要找的 Key 已登记。响应只显示掩码，不执行模型请求 |
| 注入时 Pi/Gateway 重启失败 | 检查 `key_injection.py` 中服务名/路径、看板服务用户权限、systemd 与 Docker Compose 可用性；失败会尝试恢复原配置 |
| Gateway 切换后其他客户端额度也变化 | Gateway 使用单个全局 `OPENROUTER_API_KEY`；切换影响所有客户端，`CLIENT_API_KEYS` 只是客户端鉴权 Key |
| 看板金额显示 `—` | 检查 Key 权限、OpenRouter API 连通性与 `degraded`；查看 `journalctl` 中对应上游警告 |
| 今日金额与本地午夜不同 | 项目使用 UTC 日界，即北京时间 08:00；确认服务器/cron 时区配置和 Analytics 区间 |
| 今日/本月 App 弹窗与总额不一致 | 确认调用 Analytics 时显式传入 `granularity` 和准确 `time_range` |
| 余额充值后今日消费异常 | 基准必须记录 `total_usage`，不能用 `remaining` 差值 |
| 新闻栏加载失败 | 检查 `/api/latest_models`、服务器出站访问 `openrouter.ai` 和 12 小时缓存；失败时保留占位，不应让布局跳动 |
| Intelligence Index 显示“—” | OpenRouter 官方模型对象可能没有该 benchmark；不要用其他测评或估算值冒充该指标 |
| 首页可开但 PWA 不可安装 | 检查 HTTPS、manifest、图标路径和浏览器 Service Worker 控制台错误 |
| 代理能访问、直连端口也可访问 | Python 默认监听 `0.0.0.0`；用云安全组/主机防火墙限制应用端口或改为 loopback 绑定 |

## 12. 安全与维护清单

- 用强随机访问口令替换 `changeme`；不要复用 OpenRouter API Key 作为看板口令。
- Key 与口令只放在服务器配置/运行时存储；`.gitignore` 是防误提交措施，不是访问控制。
- `accounts.json` 和 `runtime_keys.json` 都含明文 Key；设为 `0600`，限制所有者，备份时加密，不要提交 Git。
- 仅通过 HTTPS 或可信 VPN 使用。HTTP 会明文传输访问口令和新提交的推理 Key；测试只用临时、低额度 Key，禁止在公网 HTTP 输入生产 Key。
- 推理 Key 管理接口默认关闭；启用 `OR_ENABLE_RUNTIME_KEY_MANAGEMENT=1` 前确认访问路径与最小权限。当前参考服务以 root 部署，仅为能写入既有 Pi/Gateway 配置；不要直接复制到公网生产环境而不做权限隔离。
- 检查接口仅对本机凭证配置做匹配，不验证 OpenRouter 模型调用；注入只替换本地配置，不会撤销远端 Key。Gateway 是全局上游，切换将影响所有 Gateway 客户端。
- 不把 `accounts.json`、`runtime_keys.json`、`config.json`、`daily_baseline.json` 或任何包含密钥的备份上传到公开仓库。
- 定期更新 Python 与 `requests`；对外发布代码时也检查依赖和图标授权。
- 修改接口或计算逻辑后运行离线测试，保留实际 API 错误时的 `null` / degraded 状态，不要把错误静默改成零值。
- 避免在日志、截图、issue、聊天记录中粘贴真实 Key 或访问口令；一旦暴露立即撤销/轮换。

## 13. License 与第三方资源

README 当前带有 MIT License 徽章，但仓库快照中没有单独跟踪的 `LICENSE` 文件；如需公开分发复刻版本，应先确认并补齐明确的许可证文本。无论项目代码采用何种许可证，仍需分别核对图标、字体或其他第三方资源的授权与来源要求。
