#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日 0 点余额基准捕获脚本（支持多账户）
- 由 cron 在每天 00:01 (本地时区) 触发
- 遍历 accounts.json 中的所有 API Key，分别拉取 OpenRouter /credits 接口，
  记录当天 0 点的累计消费总额(total_usage)作为该账户的基准
- 供 server.py 计算"今日消费" = 当前累计消费总额 - 今日0点基准
- 注意：记录 total_usage（只增不减）而非 remaining(剩余额度)，充值不会干扰计算结果
"""
import time
import requests

import server


def capture_one(account):
    headers = {"Authorization": f"Bearer {account['api_key']}"}
    r = requests.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    total_usage = data.get("total_usage", 0) or 0

    today = time.strftime("%Y-%m-%d")
    server.save_daily_baseline(account["id"], today, total_usage)
    print(
        f"[{today}] {account.get('name') or account['id']}: "
        f"total_usage_at_midnight={total_usage}"
    )


def capture():
    accounts = server.load_accounts()["accounts"]
    if not accounts:
        print("no accounts configured, skip")
        return
    for account in accounts:
        try:
            capture_one(account)
        except Exception as e:
            print(f"[error] {account.get('name') or account.get('id')}: {e}")


if __name__ == "__main__":
    capture()
