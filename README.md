# OpenRouter 手机看板 (OpenRouter Mobile Dashboard)

一个轻量级、支持 PWA 安装的移动端看板，用于监控 [OpenRouter](https://openrouter.ai) 账户的消费情况和各模型调用量。仅依赖 Python 标准库 + 一个第三方 HTTP 库，无需 Node.js / 数据库，几分钟即可部署到任意 Linux 服务器。

![Dashboard Preview](https://img.shields.io/badge/PWA-Installable-4ade80) ![Python](https://img.shields.io/badge/Python-3.7+-blue) ![License](https://img.shields.io/badge/License-MIT-lightgrey) ![Built with](https://img.shields.io/badge/Built%20with-Pi%20Coding%20Agent-8b5cf6) ![Model](https://img.shields.io/badge/Model-DeepSeek%20V4.1%20Flash-4D6BFE)

> 🤖 本仓库由 **[Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent)** 驱动 **`deepseek/deepseek-v4.1-flash`**（通过 [OpenRouter](https://openrouter.ai) 调用）自动生成与维护，从需求沟通、代码编写到部署上线全流程由 AI Agent 完成。
>
> 📌 **当前使用模型**：`deepseek/deepseek-v4.1-flash`（OpenRouter）——模型可随版本迭代更换，此处标注的是撰写/维护本仓库时实际调用的模型。

## ✨ 功能特性

- 📊 **账户概览**：剩余额度、累计消费、本月累计消费、今日消费（本月/今日消费数值可点击，弹窗展示对应时间范围内各 App 的消费分布）
- 💳 **一键充值**：账户概览卡片直接跳转充值页面，并提示信用卡手续费规则（5.5%，最低收 $0.8，建议单次充值 ≥ $20 以避免最低费抬高实际费率）
- 💻 **响应式布局**：手机、平板、PC 全尺寸自适应（≥768px 多列网格、≥1200px 大屏优化），修复了多处布局问题（图表在不同尺寸下的卡片高度异常、PC 端账户余额概览因 CSS 层叠顺序 bug 导致实际只显示 2 列而非预期 4 列、卡片与卡片之间因多套间距方案混用导致间距忽大忽小甚至贴合重叠等，现已统一为 `flex + gap` 单一间距模型）
- 🆕 **新品新闻滚动条**：账户概览下方自动无缝滚动展示 Claude / GPT / DeepSeek / Gemini / Llama / Qwen / Mistral 等主流厂商最新发布的模型及发布日期，数据来自 OpenRouter 官方模型列表接口（12 小时缓存）
- 📈 **消费趋势图**：近 30 天每日消费折线图
- 🧩 **App 消费分布**：按调用客户端（如 Claude Code、Codex、pi 等）拆分统计消费金额、调用次数、Token 用量及占比，并自动匹配各 App 官方图标；数据来自 OpenRouter 官方 Analytics API（`dimension=app`），支持点击「今日消费」「本月累计消费」弹窗查看该时间范围内的 App 拆分明细（查询时显式指定 `granularity` 参数，避免 Analytics API 在未指定粒度时把自定义时间范围隐式取整到 UTC 自然日、导致金额虚高的问题）
- 🏆 **模型调用排行**：按消费金额排序的横向柱状图，只展示消费 > 0 的 Top 5 模型，避免无意义的零消费条目占位
- 🔍 **模型消费明细**：展示全部模型（不限制数量），包含调用次数、Token 用量（输入/输出/总计），并自动匹配各大厂商官方 Logo，超过 420px 高度时容器内部纵向滚动
- 💱 **汇率一键切换**：USD ⇄ CNY，汇率可在配置文件中自定义（默认 7.1，含手续费预留空间），切换时数值区域固定行高，无任何布局跳动
- 🌙 **深色 / 浅色双主题**：右上角一键切换，基于 CSS 变量驱动，图表配色、网格线、文字颜色均自动跟随主题切换，选择会持久化保存
- 🎛️ **极简右上角控件**：主题切换（🌙/☀️）与币种切换（USD/CNY）均为无边框、透明背景的极简图标/文字按钮，仅在 hover/激活时给出轻微反馈，与整体扁平化视觉风格保持一致
- ✨ **克制的交互动效**：卡片 hover 轻微上浮+阴影加深、页面加载时卡片错开淡入、按钮点击缩放反馈，并适配 `prefers-reduced-motion` 尊重系统减动画设置
- 🚨 **智能预警**：剩余额度低于 $9 自动标红；今日消费超过 $50 自动标黄并显示感叹号提醒
- 🕛 **今日消费精准计算**：OpenRouter 官方 `/activity` 接口有 1~2 天数据延迟，本项目通过每日 0 点记录“累计消费总额(total_usage)”作为基准，实时计算 `今日消费 = 当前累计消费 - 0点基准`，因 total_usage 只增不减，不会因中途充值导致计算异常（早期版本曾使用“剩余余额”作为基准，存在充值当天会导致今日消费误计为 0 的 bug，已修复）
- 📱 **PWA 支持**：可直接“添加到主屏幕”，像原生 App 一样使用
- 🔒 **访问口令保护**：前端仅使用访问口令（Token），真实的 OpenRouter API Key 只保存在服务端，不会暴露
- 🔑 **多账户 / 多 API Key 管理**：可在看板内添加多个 OpenRouter API Key，顶部下拉一键切换，分别查看不同账户的余额、消费、App 分布与模型排行；添加时自动调用官方接口校验 Key 有效性，支持重命名与删除；Key 仅保存在服务端 `accounts.json`，前端只能看到脱敏掩码（如 `sk-or-v1-b...d416`）
- ⚡ **零依赖前端**：纯 HTML + Chart.js（CDN），无需构建工具

## 📸 界面预览

深色/浅色双主题简约风格，专为手机浏览器优化，同时兼顾平板/PC大屏，支持自动横竖屏适配。

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/<your-username>/openrouter-dashboard.git
cd openrouter-dashboard
```

### 2. 安装依赖

```bash
pip3 install requests
```

### 3. 配置

复制示例配置文件并填入你自己的信息：

```bash
cp config.json.example config.json
```

编辑 `config.json`：

```json
{
  "openrouter_api_keys": [
    { "name": "主账户", "api_key": "sk-or-v1-你的第一个OpenRouter密钥" },
    { "name": "备用账户", "api_key": "sk-or-v1-你的第二个OpenRouter密钥" }
  ],
  "dashboard_token": "自定义一个访问口令，用于手机端登录看板",
  "port": 8080,
  "usd_to_cny_rate": 7.1
}
```

| 字段 | 说明 |
|---|---|
| `openrouter_api_keys` | 可选，预置的多个账户列表，每项为 `{"name": 备注名, "api_key": 密钥}`；也可启动后在看板内直接添加 |
| `openrouter_api_key` | 可选，兼容旧版的单 Key 字段；当未配置 `openrouter_api_keys` 时作为默认账户导入 |
| `dashboard_token` | 手机端访问看板时输入的口令，请自行设置一个不易猜测的字符串 |
| `port` | 服务监听端口 |
| `usd_to_cny_rate` | USD → CNY 汇率，可自行调整（建议把手续费也计入这个数值里） |

> 首次启动时会把 `config.json` 中的 Key 导入到 `accounts.json`（运行时账户存储，已加入 `.gitignore`）。之后在看板「⚙️ 管理」中添加/删除/重命名账户都会写入该文件，不会回写 `config.json`。

⚠️ **`config.json` 已加入 `.gitignore`，不会被提交，请务必不要把真实的 API Key 提交到任何公开仓库。**

### 4. 启动

```bash
python3 server.py
```

启动后访问 `http://<你的服务器IP>:<端口>/`，输入 `dashboard_token` 中设置的口令即可查看看板。

### 5. （推荐）配置每日余额基准定时任务

OpenRouter 官方的 `/activity` 接口存在延迟，无法准确反映"今日消费"。本项目通过 `baseline_capture.py` 脚本在每天 0 点记录一次基准，再用「基准 - 当前累计消费」实时推算当日消费。脚本会自动遍历 `accounts.json` 中的所有账户，逐个记录基准。请配置 cron 让其每天自动运行一次：

```bash
crontab -e
```

添加一行（建议 0 点 01 分执行，避开整点高峰）：

```
1 0 * * * /usr/bin/python3 /path/to/openrouter-dashboard/baseline_capture.py >> /path/to/logs/baseline.log 2>&1
```

> 即使 cron 未及时执行，`server.py` 也会在当天首次访问时自动补写一个基准值兜底，保证功能不中断。

### 6. （推荐）设置开机自启

Linux (systemd) 示例：

```ini
# /etc/systemd/system/or-dashboard.service
[Unit]
Description=OpenRouter Mobile Dashboard
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/openrouter-dashboard
ExecStart=/usr/bin/python3 /path/to/openrouter-dashboard/server.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now or-dashboard.service
```

### 7. 手机安装为 PWA

- **iOS Safari**：打开网页 → 点击分享按钮 → "添加到主屏幕"
- **Android Chrome**：打开网页后会自动提示"安装应用"，或手动通过浏览器菜单安装

安装后即可像原生 App 一样在主屏幕直接打开，无浏览器地址栏。

## 🗂️ 项目结构

```
openrouter-dashboard/
├── server.py              # 后端服务（Python 标准库 http.server，无框架依赖）
├── baseline_capture.py    # 每日 0 点余额基准捕获脚本（遍历所有账户，配合 cron 使用）
├── config.json.example    # 配置文件示例（真实配置请自行创建 config.json，不会被提交）
├── accounts.json          # 运行时多账户存储（自动生成，含明文 Key，不会被提交）
├── .gitignore
├── README.md
└── static/
    ├── index.html          # 前端页面（含所有逻辑，纯原生 JS + Chart.js CDN）
    ├── manifest.json       # PWA manifest
    ├── sw.js               # Service Worker（仅用于满足可安装条件，不做离线缓存）
    ├── icon-192.png        # PWA 图标
    ├── icon-512.png        # PWA 图标
    └── logos/              # 各种图标资源
        ├── anthropic.svg       # 模型厂商 Logo（来自 openrouter.ai）
        ├── openai.svg
        ├── deepseek.png
        ├── google.svg
        ├── meta.png
        ├── qwen.png
        ├── mistral.png
        └── apps/               # App 调用客户端官方图标
            ├── claude-code.png
            ├── codex.webp
            └── pi.jpg
```

## 🔧 工作原理

1. 后端 `server.py` 启动一个纯 Python HTTP 服务，暴露以下接口：
   - `GET /` ：返回前端页面
   - `GET /api/accounts?token=xxx` ：返回账户列表（含脱敏后的 Key 掩码），供前端下拉切换
   - `POST /api/accounts?token=xxx` ：新增账户（body: `{"name", "api_key"}`），会先调用 OpenRouter `/key` 校验 Key 有效性
   - `POST /api/accounts/rename?token=xxx` ：重命名账户（body: `{"id", "name"}`）
   - `DELETE /api/accounts?id=xxx&token=xxx` ：删除账户（至少保留一个）
   - `GET /api/summary?token=xxx&account=xxx` ：聚合指定账户的 OpenRouter 官方 API（`/credits`、`/key`、`/activity`、`/analytics/query`）数据后返回 JSON（按账户分别缓存 60 秒）
   - `GET /api/latest_models?token=xxx` ：拉取 OpenRouter 全量模型列表，按厂商分组取每家最新发布的模型，供首页新闻滚动条展示（12 小时缓存，与账户无关）
   - App 消费分布数据通过 `POST https://openrouter.ai/api/v1/analytics/query`（`dimensions: ["app"]`）获取，普通推理 API Key 即可调用，无需 Management Key
2. 服务端持有真实的 OpenRouter API Key，通过环境隔离保证密钥不会暴露给浏览器/前端
3. 前端仅需要一个自定义的访问口令（`dashboard_token`），存储在浏览器 `localStorage`，避免每次重新输入
4. 前端内置预警阈值逻辑（剩余额度/今日消费）与响应式布局断点，均可在 `static/index.html` 中直接修改对应 JS 常量/CSS `@media` 断点
5. 主题切换基于 CSS 变量（`:root` 与 `html[data-theme="light"]`）实现，选择保存在 `localStorage`，刷新后保持上次选择

## ⚠️ 安全提示

- 请勿将填好真实 Key 的 `config.json` 或运行时生成的 `accounts.json` 提交到任何 Git 仓库（本仓库已在 `.gitignore` 中屏蔽）
- 建议将 `dashboard_token` 设置为足够随机、不易猜测的字符串
- 如果部署在公网服务器，建议额外配置 HTTPS（可用 Nginx/Caddy 反向代理）以及防火墙限制访问来源

## 🤖 关于本项目的构建方式

本项目完全由 AI Agent 自主开发完成：

| 项目 | 信息 |
|---|---|
| Agent 框架 | [Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent)（CLI 编码智能体） |
| 使用模型 | `deepseek/deepseek-v4.1-flash`（当前使用） |
| 模型提供方 | [OpenRouter](https://openrouter.ai) |
| 开发方式 | 通过自然语言对话，逐步迭代完成需求分析、前后端开发、PWA 适配、Logo 爬取、服务器部署（systemd 自启）、GitHub 仓库创建与发布 |

## 📄 License

MIT
