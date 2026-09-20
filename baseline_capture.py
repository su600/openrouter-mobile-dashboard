#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日 0 点余额基准捕获脚本
- 由 cron 在每天 00:01 (本地时区) 触发
- 拉取 OpenRouter /credits 接口，记录当天 0 点的累计消费总额(total_usage)作为基准
- 供 server.py 计算"今日消费" = 当前累计消费总额 - 今日0点基准
- 注意：之前版本记录的是 remaining(剩余额度)，会被充值干扰导致计算出负数，改为记录 total_usage 后不受充值影响（因为累计消费只增不减）
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
    total_usage = data.get("total_usage", 0) or 0

    today = time.strftime("%Y-%m-%d")
    payload = {
        "date": today,
        "total_usage_at_midnight": total_usage,
        "captured_at": int(time.time()),
    }
    tmp = BASELINE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BASELINE_PATH)
    print(f"[{today}] baseline captured: total_usage_at_midnight={total_usage}")


if __name__ == "__main__":
    capture()
