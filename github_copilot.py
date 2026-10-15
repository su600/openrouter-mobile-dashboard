#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Copilot 账户管理：OAuth Device Flow 登录 + 订阅用量查询。

OAuth token 仅保存在服务器本地文件（0600），不会返回给前端。
"""
import json
import os
import tempfile
import threading
import time
import uuid

import requests

import config
from logging_setup import get_logger

logger = get_logger(__name__)

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
COPILOT_USER_URL = "https://api.github.com/copilot_internal/user"
OAUTH_SCOPE = "read:user"

_lock = threading.Lock()


class CopilotError(Exception):
    pass


def _client_id():
    client_id = config.GITHUB_CLIENT_ID
    if not client_id:
        raise CopilotError("未配置 github_client_id（或环境变量 OR_GITHUB_CLIENT_ID）")
    return client_id


def _load():
    try:
        with open(config.COPILOT_ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return {"accounts": []}
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        return {"accounts": []}
    return data


def _save(data):
    path = config.COPILOT_ACCOUNTS_PATH
    directory = os.path.dirname(path) or "."
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, prefix=".copilot-", delete=False
        ) as f:
            temp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def start_device_flow():
    """申请 device code，返回前端展示所需信息（含 device_code，用于轮询）。"""
    resp = requests.post(
        DEVICE_CODE_URL,
        data={"client_id": _client_id(), "scope": OAUTH_SCOPE},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if "device_code" not in body:
        raise CopilotError(body.get("error_description") or "GitHub 授权请求失败")
    return {
        "device_code": body["device_code"],
        "user_code": body.get("user_code"),
        "verification_uri": body.get("verification_uri") or "https://github.com/login/device",
        "expires_in": body.get("expires_in", 900),
        "interval": body.get("interval", 5),
    }


def poll_device_flow(device_code):
    """轮询授权结果。返回 {"status": "pending"|"slow_down"|"ok", ...}。"""
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": _client_id(),
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    error = body.get("error")
    if error in ("authorization_pending", "slow_down"):
        return {"status": "pending" if error == "authorization_pending" else "slow_down"}
    if error:
        raise CopilotError(body.get("error_description") or error)
    token = body.get("access_token")
    if not token:
        raise CopilotError("GitHub 未返回 access_token")
    return {"status": "ok", "account": add_account(token)}


def _gh_headers(token):
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": "openrouter-mobile-dashboard",
    }


def add_account(token):
    resp = requests.get(USER_URL, headers=_gh_headers(token), timeout=15)
    if resp.status_code != 200:
        raise CopilotError("无法获取 GitHub 用户信息")
    user = resp.json()
    login = user.get("login") or ""
    with _lock:
        data = _load()
        account = next((a for a in data["accounts"] if a.get("login") == login), None)
        if account is None:
            account = {"id": uuid.uuid4().hex[:12], "login": login}
            data["accounts"].append(account)
        account["token"] = token
        account["name"] = user.get("name") or login
        account["added_at"] = int(time.time())
        _save(data)
    return public_account(account)


def public_account(account):
    return {k: account.get(k) for k in ("id", "login", "name", "added_at")}


def list_accounts():
    with _lock:
        return [public_account(a) for a in _load()["accounts"]]


def delete_account(account_id):
    with _lock:
        data = _load()
        before = len(data["accounts"])
        data["accounts"] = [a for a in data["accounts"] if a.get("id") != account_id]
        if len(data["accounts"]) == before:
            return False
        _save(data)
        return True


def normalize_usage(raw):
    """将 copilot_internal/user 响应整理为精简的前端结构。"""
    quotas = []
    snapshots = raw.get("quota_snapshots") if isinstance(raw, dict) else None
    for name, q in (snapshots or {}).items():
        if not isinstance(q, dict):
            continue
        entitlement = q.get("entitlement")
        remaining = q.get("remaining")
        unlimited = bool(q.get("unlimited"))
        used = None
        if isinstance(entitlement, (int, float)) and isinstance(remaining, (int, float)):
            used = max(entitlement - remaining, 0)
        percent_remaining = q.get("percent_remaining")
        quotas.append({
            "name": name,
            "unlimited": unlimited,
            "entitlement": entitlement,
            "remaining": remaining,
            "used": used,
            "percent_remaining": percent_remaining,
            "overage_count": q.get("overage_count"),
        })
    return {
        "plan": raw.get("copilot_plan") or raw.get("access_type_sku"),
        "reset_date": raw.get("quota_reset_date") or raw.get("limited_user_reset_date"),
        "quotas": quotas,
    }


def fetch_usage(account_id):
    with _lock:
        account = next((a for a in _load()["accounts"] if a.get("id") == account_id), None)
    if account is None:
        raise CopilotError("账户不存在")
    resp = requests.get(COPILOT_USER_URL, headers=_gh_headers(account["token"]), timeout=15)
    if resp.status_code in (401, 403):
        raise CopilotError("授权已失效或该账户没有 Copilot 订阅，请重新登录")
    if resp.status_code == 404:
        raise CopilotError("该账户没有 Copilot 订阅")
    resp.raise_for_status()
    usage = normalize_usage(resp.json())
    usage["id"] = account["id"]
    usage["login"] = account.get("login")
    return usage
