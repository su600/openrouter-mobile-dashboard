#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全局配置与路径常量。

`config.json` 缺失时不再直接崩溃：回退到默认值 / 环境变量，方便在无真实密钥的
环境（CI、单元测试）中导入本项目。
"""
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "accounts.json")
RUNTIME_KEYS_PATH = os.path.join(BASE_DIR, "runtime_keys.json")
WIDGET_TOKEN_PATH = os.path.join(BASE_DIR, "widget_readonly_token")
GITHUB_COPILOT_ACCOUNTS_PATH = os.path.join(BASE_DIR, "github_copilot_accounts.json")
BASELINE_PATH = os.path.join(BASE_DIR, "daily_baseline.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    CONFIG = {}

DASHBOARD_TOKEN = (
    CONFIG.get("dashboard_token")
    or os.environ.get("OR_DASHBOARD_TOKEN")
    or "changeme"
)
RUNTIME_KEY_MANAGEMENT_ENABLED = os.environ.get("OR_ENABLE_RUNTIME_KEY_MANAGEMENT") == "1"
GITHUB_OAUTH_CLIENT_ID = CONFIG.get("github_oauth_client_id") or os.environ.get("GH_COPILOT_OAUTH_CLIENT_ID", "")
GITHUB_OAUTH_CLIENT_SECRET = CONFIG.get("github_oauth_client_secret") or os.environ.get("GH_COPILOT_OAUTH_CLIENT_SECRET", "")
GITHUB_OAUTH_REDIRECT_URI = CONFIG.get("github_oauth_redirect_uri") or os.environ.get("GH_COPILOT_OAUTH_REDIRECT_URI", "")
# 默认只读；如需按模型的账单用量，需设为 user（重新授权后生效）
GITHUB_OAUTH_SCOPE = os.environ.get("GH_COPILOT_OAUTH_SCOPE", "read:user")
PORT = int(CONFIG.get("port", 8899))
USD_TO_CNY_RATE = CONFIG.get("usd_to_cny_rate", 7.1)