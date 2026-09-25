#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账户（API Key）管理。

- 支持在 config.json 中用 `openrouter_api_keys: [{name, api_key}, ...]` 预置多个账户；
  兼容旧的单 Key 字段 `openrouter_api_key`。
- 运行时账户列表持久化在 accounts.json（仅服务端可见，绝不返回给前端明文 Key）。
"""
import os
import json
import hashlib
import threading

from config import ACCOUNTS_PATH, CONFIG

_accounts_lock = threading.Lock()


def mask_key(api_key):
    """返回脱敏后的 Key，用于前端展示。"""
    if not api_key:
        return ""
    if len(api_key) <= 12:
        return api_key[:4] + "****"
    return api_key[:10] + "..." + api_key[-4:]


def account_id_for(api_key):
    """由 Key 派生稳定的账户 ID，重复添加同一 Key 会得到同一 ID。"""
    return "acct_" + hashlib.sha1(api_key.encode("utf-8")).hexdigest()[:10]


def _read_accounts_file():
    if os.path.exists(ACCOUNTS_PATH):
        try:
            with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("accounts"), list):
                return data
        except Exception:
            return None
    return None


def _seed_accounts_from_config():
    seed = []
    raw_list = CONFIG.get("openrouter_api_keys")
    if isinstance(raw_list, list):
        for item in raw_list:
            if isinstance(item, str):
                api_key, name = item, ""
            elif isinstance(item, dict):
                api_key = item.get("api_key") or item.get("key") or ""
                name = item.get("name") or ""
            else:
                continue
            if not api_key:
                continue
            if any(a["id"] == account_id_for(api_key) for a in seed):
                continue
            seed.append(
                {
                    "id": account_id_for(api_key),
                    "name": name or f"账户 {len(seed) + 1}",
                    "api_key": api_key,
                }
            )
    if not seed and CONFIG.get("openrouter_api_key"):
        api_key = CONFIG["openrouter_api_key"]
        seed.append(
            {
                "id": account_id_for(api_key),
                "name": CONFIG.get("openrouter_api_key_name") or "默认账户",
                "api_key": api_key,
            }
        )
    return {"accounts": seed, "active": seed[0]["id"] if seed else None}


def load_accounts():
    data = _read_accounts_file()
    if data is None:
        data = _seed_accounts_from_config()
        save_accounts(data)
    return data


def save_accounts(data):
    tmp = ACCOUNTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ACCOUNTS_PATH)


def get_account(account_id=None):
    """按 ID 取账户；ID 为空或不存在时回退到第一个账户。"""
    all_accounts = load_accounts()["accounts"]
    if not all_accounts:
        return None
    if account_id:
        for a in all_accounts:
            if a["id"] == account_id:
                return a
    return all_accounts[0]


def public_account(a):
    return {
        "id": a["id"],
        "name": a.get("name") or a["id"],
        "key_masked": mask_key(a.get("api_key", "")),
    }