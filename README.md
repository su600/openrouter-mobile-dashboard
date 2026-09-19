# OpenRouter 手机看板 (OpenRouter Mobile Dashboard)

一个轻量级、支持 PWA 安装的移动端看板，用于监控 [OpenRouter](https://openrouter.ai) 账户的消费情况和各模型调用量。仅依赖 Python 标准库 + 一个第三方 HTTP 库，无需 Node.js / 数据库，几分钟即可部署到任意 Linux 服务器。

![Dashboard Preview](https://img.shields.io/badge/PWA-Installable-4ade80) ![Python](https://img.shields.io/badge/Python-3.7+-blue) ![License](https://img.shields.io/badge/License-MIT-lightgrey) ![Built with](https://img.shields.io/badge/Built%20with-Pi%20Coding%20Agent-8b5cf6) ![Model](https://img.shields.io/badge/Model-Claude%20Sonnet%205-d97757)

> 🤖 本仓库由 **[Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent)** 驱动 **`anthropic/claude-sonnet-5`**（通过 [OpenRouter](https://openrouter.ai) 调用）自动生成与维护，从需求沟通、代码编写到部署上线全流程由 AI Agent 完成。

## ✨ 功能特性

- 📊 **账户概览**：剩余额度、累计消费、本月累计消费、今日消费
- 📈 **消费趋势图**：近 30 天每日消费折线图
- 🏆 **模型调用排行**：按消费金额排序的柱状图（Top 8）
- 🔍 **模型消费明细**：包含调用次数、Token 用量（输入/输出/总计），并自动匹配 Claude / GPT / DeepSeek / Gemini / Llama / Qwen / Mistral 等厂商官方 Logo
- 💱 **汇率一键切换**：USD ⇄ CNY，汇率可在配置文件中自定义（默认 7.1，含手续费预留空间）
- 📱 **PWA 支持**：可直接"添加到主屏幕"，像原生 App 一样使用，深色主题
- 🔒 **访问口令保护**：前端仅使用访问口令（Token），真实的 OpenRouter API Key 只保存在服务端，不会暴露
- ⚡ **零依赖前端**：纯 HTML + Chart.js（CDN），无需构建工具

## 📸 界面预览

深色简约风格，专为手机浏览器优化，支持自动横竖屏适配。

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
  "openrouter_api_key": "sk-or-v1-你的OpenRouter密钥",
  "dashboard_token": "自定义一个访问口令，用于手机端登录看板",
  "port": 8080,
  "usd_to_cny_rate": 7.1
}
```

| 字段 | 说明 |
|---|---|
| `openrouter_api_key` | 你的 OpenRouter API Key，可在 [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) 获取 |
| `dashboard_token` | 手机端访问看板时输入的口令，请自行设置一个不易猜测的字符串 |
| `port` | 服务监听端口 |
| `usd_to_cny_rate` | USD → CNY 汇率，可自行调整（建议把手续费也计入这个数值里） |

⚠️ **`config.json` 已加入 `.gitignore`，不会被提交，请务必不要把真实的 API Key 提交到任何公开仓库。**

### 4. 启动

```bash
python3 server.py
```

启动后访问 `http://<你的服务器IP>:<端口>/`，输入 `dashboard_token` 中设置的口令即可查看看板。

### 5. （推荐）设置开机自启

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

### 6. 手机安装为 PWA

- **iOS Safari**：打开网页 → 点击分享按钮 → "添加到主屏幕"
- **Android Chrome**：打开网页后会自动提示"安装应用"，或手动通过浏览器菜单安装

安装后即可像原生 App 一样在主屏幕直接打开，无浏览器地址栏。

## 🗂️ 项目结构

```
openrouter-dashboard/
├── server.py              # 后端服务（Python 标准库 http.server，无框架依赖）
├── config.json.example    # 配置文件示例（真实配置请自行创建 config.json，不会被提交）
├── .gitignore
├── README.md
└── static/
    ├── index.html          # 前端页面（含所有逻辑，纯原生 JS + Chart.js CDN）
    ├── manifest.json       # PWA manifest
    ├── sw.js               # Service Worker（仅用于满足可安装条件，不做离线缓存）
    ├── icon-192.png        # PWA 图标
    ├── icon-512.png        # PWA 图标
    └── logos/              # 各 AI 厂商官方 Logo（来自 openrouter.ai）
        ├── anthropic.svg
        ├── openai.svg
        ├── deepseek.png
        ├── google.svg
        ├── meta.png
        ├── qwen.png
        └── mistral.png
```

## 🔧 工作原理

1. 后端 `server.py` 启动一个纯 Python HTTP 服务，暴露两个核心接口：
   - `GET /` ：返回前端页面
   - `GET /api/summary?token=xxx` ：聚合 OpenRouter 官方 API（`/credits`、`/key`、`/activity`）数据后返回 JSON，供前端渲染
2. 服务端持有真实的 OpenRouter API Key，通过环境隔离保证密钥不会暴露给浏览器/前端
3. 前端仅需要一个自定义的访问口令（`dashboard_token`），存储在浏览器 `localStorage`，避免每次重新输入
4. 数据接口内置 60 秒缓存，避免频繁请求 OpenRouter 官方 API 触发限流

## ⚠️ 安全提示

- 请勿将填好真实 Key 的 `config.json` 提交到任何 Git 仓库（本仓库已在 `.gitignore` 中屏蔽）
- 建议将 `dashboard_token` 设置为足够随机、不易猜测的字符串
- 如果部署在公网服务器，建议额外配置 HTTPS（可用 Nginx/Caddy 反向代理）以及防火墙限制访问来源

## 🤖 关于本项目的构建方式

本项目完全由 AI Agent 自主开发完成：

| 项目 | 信息 |
|---|---|
| Agent 框架 | [Pi Coding Agent](https://github.com/earendil-works/pi-coding-agent)（CLI 编码智能体） |
| 使用模型 | `anthropic/claude-sonnet-5` |
| 模型提供方 | [OpenRouter](https://openrouter.ai) |
| 开发方式 | 通过自然语言对话，逐步迭代完成需求分析、前后端开发、PWA 适配、Logo 爬取、服务器部署（systemd 自启）、GitHub 仓库创建与发布 |

## 📄 License

MIT
