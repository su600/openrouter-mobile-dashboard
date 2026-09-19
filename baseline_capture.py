#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日 0 点余额基准捕获脚本
- 由 cron 在每天 00:01 (本地时区) 触发
- 拉取 OpenRouter /credits 接口，记录当天 0 点的剩余额度作为基准
- 供 server.py 计算"今日消费" = 今日0点基准 - 当前剩余额度
"""
import os
import json
import time
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
BASELINE_PATH = os.path.join(BASE_DIR, "daily_baseline.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

HEADERS = {"Authorization": f"Bearer {CONFIG['openrouter_api_key']}"}


def capture():
    r = requests.get("https://openrouter.ai/api/v1/credits", headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {})
    total_credits = data.get("total_credits", 0) or 0
    total_usage = data.get("total_usage", 0) or 0
    remaining = total_credits - total_usage

    today = time.strftime("%Y-%m-%d")
    payload = {
        "date": today,
        "remaining_at_midnight": remaining,
        "captured_at": int(time.time()),
    }
    tmp = BASELINE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BASELINE_PATH)
    print(f"[{today}] baseline captured: remaining={remaining}")


if __name__ == "__main__":
    capture()
