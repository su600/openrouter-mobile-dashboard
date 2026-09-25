#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日 0 点余额基准捕获脚本（支持多账户）
- 由 cron 在每天 UTC 00:01（= 北京时间 08:01）触发
- 遍历 accounts.json 中的所有 API Key，分别拉取 OpenRouter /credits 接口，
  记录当天 0 点的累计消费总额(total_usage)作为该账户的基准
- 供 server 计算"今日消费" = 当前累计消费总额 - 今日0点基准（仅作兜底）
- 注意：日界采用 UTC，与 OpenRouter 官方口径一致；记录 total_usage（只增不减）而非 remaining，充值不会干扰计算
"""
import time

import accounts as accounts_store
import baseline as baseline_store
from logging_setup import get_logger
from openrouter_api import SESSION

logger = get_logger("baseline_capture")


def capture_one(account):
    headers = {"Authorization": f"Bearer {account['api_key']}"}
    r = SESSION.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json().get("data", {}) or {}
    total_usage = data.get("total_usage", 0) or 0

    today = time.strftime("%Y-%m-%d", time.gmtime())
    baseline_store.save_daily_baseline(account["id"], today, total_usage)
    print(
        f"[{today}] {account.get('name') or account['id']}: "
        f"total_usage_at_midnight={total_usage}"
    )


def capture():
    all_accounts = accounts_store.load_accounts()["accounts"]
    if not all_accounts:
        print("no accounts configured, skip")
        return
    for account in all_accounts:
        try:
            capture_one(account)
        except Exception as e:
            logger.warning("账户 %s 基准捕获失败: %s", account.get("name") or account.get("id"), e)


if __name__ == "__main__":
    capture()