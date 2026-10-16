#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub Copilot OAuth account storage and usage API."""
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import date, datetime, timezone
from urllib.parse import urlencode

import requests

from config import (
    GITHUB_COPILOT_ACCOUNTS_PATH,
    GITHUB_OAUTH_CLIENT_ID,
    GITHUB_OAUTH_CLIENT_SECRET,
    GITHUB_OAUTH_REDIRECT_URI,
    GITHUB_OAUTH_SCOPE,
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
        "scope": GITHUB_OAUTH_SCOPE,
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
    # 解析符号链接到真实位置（容器中为 /data），避免在只读的 /app 下写临时文件
    path = os.path.realpath(GITHUB_COPILOT_ACCOUNTS_PATH)
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
    monthly_quotas = payload.get("monthly_quotas")
    if not isinstance(monthly_quotas, dict):
        monthly_quotas = {}
    reset_date = (
        payload.get("quota_reset_date_utc")
        or payload.get("quota_reset_date")
        or payload.get("limited_user_reset_date")
    )

    quotas = []
    for key, snapshot in snapshots.items():
        if not isinstance(snapshot, dict):
            snapshot = {
                "remaining": snapshot,
                "entitlement": monthly_quotas.get(key),
            }
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
            "reset_date": snapshot.get("reset_date") or reset_date,
            "unlimited": bool(snapshot.get("unlimited", False)),
        })

    quota_order = {key: index for index, key in enumerate(QUOTA_LABELS)}
    quotas.sort(key=lambda item: (quota_order.get(item["key"], len(quota_order)), item["label"]))
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


def _plan_details(payload):
    """订阅计划、重置日期、高级请求配额与超额、功能开关。"""
    reset = payload.get("quota_reset_date_utc") or payload.get("quota_reset_date")
    days_to_reset = None
    if reset:
        try:
            reset_day = date.fromisoformat(str(reset)[:10])
            days_to_reset = (reset_day - datetime.now(timezone.utc).date()).days
        except ValueError:
            days_to_reset = None
    snapshots = payload.get("quota_snapshots") if isinstance(payload.get("quota_snapshots"), dict) else {}
    premium = snapshots.get("premium_interactions")
    premium_info = None
    if isinstance(premium, dict):
        entitlement = _number(premium.get("entitlement"))
        remaining = _number(premium.get("remaining"))
        used = max(0, entitlement - remaining) if entitlement is not None and remaining is not None else None
        percent_used = round(used / entitlement * 100, 1) if used is not None and entitlement else None
        premium_info = {
            "entitlement": entitlement,
            "remaining": remaining,
            "used": used,
            "percent_used": min(100, percent_used) if percent_used is not None else None,
            "unlimited": bool(premium.get("unlimited", False)),
            "overage_permitted": bool(premium.get("overage_permitted", False)),
            "overage_count": _number(premium.get("overage_count")) or 0,
            "overage_limit": _number(premium.get("overage_entitlement")),
            "credits_used": _number(premium.get("credits_used")),
        }
    organizations = payload.get("organization_login_list")
    return {
        "sku": payload.get("access_type_sku"),
        "reset_date": reset,
        "days_to_reset": days_to_reset,
        "premium": premium_info,
        "features": {
            "chat": bool(payload.get("chat_enabled")),
            "cli": bool(payload.get("cli_enabled")),
            "token_based_billing": bool(payload.get("token_based_billing")),
        },
        "organizations": [str(item) for item in organizations] if isinstance(organizations, list) else [],
    }


def _model_usage(login, token, token_based_billing=False):
    """按模型读取本月 AI Credits 或高级请求用量。"""
    now = datetime.now(timezone.utc)
    period = f"{now.year}-{now.month:02d}"
    unit_label = "AI Credits" if token_based_billing else "高级请求"
    if not login:
        return {"available": False, "reason": "缺少账户登录名", "period": period, "unit_label": unit_label, "items": []}
    billing_kind = "ai_credit" if token_based_billing else "premium_request"
    try:
        payload = _github_get(
            f"/users/{login}/settings/billing/{billing_kind}/usage?year={now.year}&month={now.month}",
            token,
        )
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403, 404):
            reason = f"GitHub 拒绝读取{unit_label}账单（HTTP {status}）。请确认账号有权查看个人账单，并重新连接 GitHub。"
        else:
            reason = f"GitHub 账单接口返回 HTTP {status}"
        return {"available": False, "reason": reason, "period": period, "unit_label": unit_label, "items": []}
    except Exception:
        return {"available": False, "reason": "账单接口请求失败，请稍后刷新", "period": period, "unit_label": unit_label, "items": []}

    by_model = {}
    for item in payload.get("usageItems") or []:
        if not isinstance(item, dict):
            continue
        model = str(item.get("model") or item.get("sku") or "未知")
        row = by_model.setdefault(model, {"model": model, "quantity": 0.0, "gross_amount": 0.0, "net_amount": 0.0})
        row["quantity"] += _number(item.get("grossQuantity")) or 0
        row["gross_amount"] += _number(item.get("grossAmount")) or 0
        row["net_amount"] += _number(item.get("netAmount")) or 0
    total = sum(row["quantity"] for row in by_model.values())
    items = sorted(by_model.values(), key=lambda row: row["quantity"], reverse=True)
    for row in items:
        row["share_percent"] = round(row["quantity"] / total * 100, 1) if total else 0
        row["quantity"] = round(row["quantity"], 6 if token_based_billing else 2)
        row["gross_amount"] = round(row["gross_amount"], 4)
        row["net_amount"] = round(row["net_amount"], 4)
    return {
        "available": True,
        "reason": None if items else f"本月暂无按模型的{unit_label}记录",
        "period": period,
        "unit_label": unit_label,
        "total_usage": round(total, 6 if token_based_billing else 2),
        "total_net_amount": round(sum(row["net_amount"] for row in items), 4),
        "items": items,
    }


def get_usage(account_id):
    account = next((item for item in _read_accounts() if item.get("id") == account_id), None)
    if not account:
        raise KeyError("GitHub Copilot 账户不存在")
    token = account["token"]
    payload = _github_get("/copilot_internal/user", token)
    if not isinstance(payload, dict):
        raise ValueError("GitHub Copilot 返回的数据格式无效")
    usage = normalize_usage(payload)
    usage.update(_plan_details(payload))
    usage["account"] = public_account(account)
    usage["models"] = _model_usage(
        account.get("login"), token,
        token_based_billing=usage["features"]["token_based_billing"],
    )
    return usage
