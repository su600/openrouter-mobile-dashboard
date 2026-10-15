#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Copilot OAuth account storage and usage API."""
import hashlib
import json
import os
import secrets
import threading
import time
from urllib.parse import urlencode

import requests

from config import (
    GITHUB_COPILOT_ACCOUNTS_PATH,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
    GITHUB_OAUTH_REDIRECT_URI,
)

SESSION = requests.Session()
_accounts_lock = threading.Lock()
_oauth_lock = threading.Lock()
_oauth_states = {}
OAUTH_STATE_TTL = 600
GITHUB_API = "https://api.github.com"

QUOTA_LABELS = {
    "premium_interactions": "高级请求",
    "chat": "聊天",
    "completions": "代码补全",
}


def oauth_configured():
    return bool(GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET and GITHUB_OAUTH_REDIRECT_URI)


def begin_oauth():
    if not oauth_configured():
        raise RuntimeError("GitHub OAuth 尚未配置")
    state = secrets.token_urlsafe(32)
    now = time.time()
    with _oauth_lock:
        for key, created_at in list(_oauth_states.items()):
            if now - created_at > OAUTH_STATE_TTL:
                del _oauth_states[key]
        _oauth_states[state] = now
    params = {
        "client_id": GITHUB_OAUTH_CLIENT_ID,
        "redirect_uri": GITHUB_OAUTH_REDIRECT_URI,
        "scope": "read:user",
        "state": state,
    }
    return "https://github.com/login/oauth/authorize?" + urlencode(params)


def consume_oauth_state(state):
    if not state:
        return False
    with _oauth_lock:
        created_at = _oauth_states.pop(state, None)
    return created_at is not None and time.time() - created_at <= OAUTH_STATE_TTL


def exchange_oauth_code(code):
    if not oauth_configured():
        raise RuntimeError("GitHub OAuth 尚未配置")
    response = SESSION.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB_OAUTH_CLIENT_ID,
            "client_secret": GITHUB_OAUTH_CLIENT_SECRET,
            "code": code,
            "redirect_uri": GITHUB_OAUTH_REDIRECT_URI,
        },
        timeout=15,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("error") or not result.get("access_token"):
        raise ValueError("GitHub OAuth 授权失败")
    return result["access_token"]


def _github_get(path, token):
    response = SESSION.get(
        GITHUB_API + path,
        headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
            "User-Agent": "openrouter-mobile-dashboard",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _read_accounts():
    try:
        with open(GITHUB_COPILOT_ACCOUNTS_PATH, "r", encoding="utf-8") as source:
            data = json.load(source)
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []


def _save_accounts(accounts):
    path = GITHUB_COPILOT_ACCOUNTS_PATH
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(accounts, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def add_oauth_account(token):
    profile = _github_get("/user", token)
    login = str(profile.get("login") or "").strip()
    github_id = profile.get("id")
    if not login:
        raise ValueError("无法读取 GitHub 用户信息")
    account_id = "github_" + (
        str(github_id) if github_id is not None else hashlib.sha256(login.lower().encode("utf-8")).hexdigest()[:12]
    )
    account = {
        "id": account_id,
        "login": login,
        "name": str(profile.get("name") or login),
        "token": token,
        "connected_at": int(time.time()),
    }
    with _accounts_lock:
        accounts = _read_accounts()
        existing = next((item for item in accounts if item.get("id") == account_id), None)
        if existing:
            existing.update(account)
        else:
            accounts.append(account)
        _save_accounts(accounts)
    return public_account(account)


def public_account(account):
    return {
        "id": account.get("id"),
        "login": account.get("login"),
        "name": account.get("name") or account.get("login"),
        "connected_at": account.get("connected_at"),
    }


def list_accounts():
    return [public_account(item) for item in _read_accounts()]


def remove_account(account_id):
    with _accounts_lock:
        accounts = _read_accounts()
        remaining = [item for item in accounts if item.get("id") != account_id]
        if len(remaining) == len(accounts):
            return False
        _save_accounts(remaining)
    return True


def _number(value):
    try:
        number = float(value)
        if number < 0:
            return None
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_usage(payload):
    snapshots = payload.get("quota_snapshots")
    if not isinstance(snapshots, dict):
        snapshots = payload.get("limited_user_quotas")
    if not isinstance(snapshots, dict):
        snapshots = {}

    quotas = []
    for key, snapshot in snapshots.items():
        if not isinstance(snapshot, dict):
            continue
        entitlement = _number(snapshot.get("entitlement"))
        remaining = _number(snapshot.get("remaining"))
        percent_remaining = _number(snapshot.get("percent_remaining"))
        if percent_remaining is None and entitlement and remaining is not None:
            percent_remaining = round(remaining / entitlement * 100, 1)
        if percent_remaining is not None:
            percent_remaining = min(100, percent_remaining)
        quotas.append({
            "key": str(key),
            "label": QUOTA_LABELS.get(key, str(key).replace("_", " ").title()),
            "entitlement": entitlement,
            "remaining": remaining,
            "percent_remaining": percent_remaining,
            "reset_date": snapshot.get("reset_date"),
            "unlimited": bool(snapshot.get("unlimited", False)),
        })

    quotas.sort(key=lambda item: (item["key"] not in QUOTA_LABELS, item["label"]))
    plan = (
        payload.get("copilot_plan")
        or payload.get("plan_type")
        or payload.get("access_type_sku")
        or payload.get("sku")
    )
    return {
        "plan": str(plan) if plan else None,
        "quotas": quotas,
        "fetched_at": int(time.time()),
    }


def get_usage(account_id):
    account = next((item for item in _read_accounts() if item.get("id") == account_id), None)
    if not account:
        raise KeyError("GitHub Copilot 账户不存在")
    payload = _github_get("/copilot_internal/user", account["token"])
    if not isinstance(payload, dict):
        raise ValueError("GitHub Copilot 返回的数据格式无效")
    return normalize_usage(payload)
