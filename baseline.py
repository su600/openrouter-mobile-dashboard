#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日 0 点余额基准（按账户区分）。

文件结构: {"accounts": {"<account_id>": {"date", "total_usage_at_midnight", "captured_at", "history": [...]}}}
兼容旧版单账户结构 {"date", "total_usage_at_midnight", ...}，旧结构归第一个账户所有。

日界采用 UTC，与 OpenRouter 官方一致（对应北京时间每天 08:00 重置）；
记录 total_usage（只增不减）而非 remaining，充值不会干扰计算。
"""
import os
import json
import time
import datetime
import threading

from config import BASELINE_PATH
import accounts as accounts_store

_baseline_lock = threading.Lock()


def _read_baseline_file():
    if os.path.exists(BASELINE_PATH):
        try:
            with open(BASELINE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}
    return {}


def load_daily_baseline(account_id):
    raw = _read_baseline_file()
    if isinstance(raw.get("accounts"), dict):
        return raw["accounts"].get(account_id)
    # 旧版单账户格式：仅对第一个账户生效
    if raw.get("date"):
        all_accounts = accounts_store.load_accounts()["accounts"]
        if all_accounts and all_accounts[0]["id"] == account_id:
            return raw
    return None


def save_daily_baseline(account_id, date_str, total_usage_at_midnight):
    with _baseline_lock:
        raw = _read_baseline_file()
        if not isinstance(raw.get("accounts"), dict):
            # 旧版单账户格式：迁移时把旧基准归到第一个账户，避免丢失当日基准
            migrated = {"accounts": {}}
            if raw.get("date"):
                all_accounts = accounts_store.load_accounts()["accounts"]
                if all_accounts:
                    migrated["accounts"][all_accounts[0]["id"]] = dict(raw)
            raw = migrated
        # 维护每日 0 点基准的滚动历史（近 70 天），供“本月/昨日”等在 activity 延迟时精确重建
        entry = raw["accounts"].get(account_id) or {}
        hist = entry.get("history")
        if not isinstance(hist, list):
            hist = []
        hist = [h for h in hist if isinstance(h, dict) and h.get("date")]
        old_date = entry.get("date")
        old_total = entry.get("total_usage_at_midnight")
        if old_date and old_total is not None and old_date != date_str:
            # 把即将被覆盖的旧基准并入历史（仅不同日期才并入）
            if not any(h["date"] == old_date for h in hist):
                hist.append({"date": old_date, "total_usage": old_total})
        hist = [h for h in hist if h["date"] != date_str]
        hist.append({"date": date_str, "total_usage": total_usage_at_midnight})
        hist.sort(key=lambda h: h["date"])
        raw["accounts"][account_id] = {
            "date": date_str,
            "total_usage_at_midnight": total_usage_at_midnight,
            "captured_at": int(time.time()),
            "history": hist[-70:],
        }
        tmp = BASELINE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        os.replace(tmp, BASELINE_PATH)


def _next_local_date(date_str):
    """返回日期字符串的次日（用于判断基准历史是否连续）。"""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def daily_usage_from_history(hist):
    """由每日 0 点基准历史推算逐日消费：相邻两连续自然日的基准之差 = 前一日消费。
    仅当两天为连续自然日时才计算，避免中间漏采导致跨多日消费被错误归到某一天。

    纯函数，便于单元测试。
    """
    parsed = []
    for h in hist or []:
        if not isinstance(h, dict):
            continue
        d = h.get("date")
        try:
            t = float(h.get("total_usage") or 0)
        except (TypeError, ValueError):
            continue
        if d:
            parsed.append((d, t))
    parsed.sort(key=lambda x: x[0])
    out = {}
    for i in range(len(parsed) - 1):
        d1, t1 = parsed[i]
        d2, t2 = parsed[i + 1]
        if _next_local_date(d1) == d2:
            out[d1] = max(round(t2 - t1, 4), 0.0)
    return out


def history_daily_usage(account_id):
    """读取该账户的基准历史并推算逐日消费。"""
    entry = load_daily_baseline(account_id) or {}
    return daily_usage_from_history(entry.get("history") or [])