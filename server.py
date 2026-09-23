#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenRouter 手机看板后端
- 服务端持有 OpenRouter API Key（支持多账户/多 Key），前端只用一个访问口令(token)
- 提供 /api/summary 聚合接口：账户余额/消费 + 近30天每日消费趋势 + 模型调用量排行
- 提供 /api/accounts 账户管理接口：查看/新增/重命名/删除多个 API Key
- 静态页面 /（移动端自适应）
"""
import os
import json
import time
import hashlib
import threading
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ACCOUNTS_PATH = os.path.join(BASE_DIR, "accounts.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
BASELINE_PATH = os.path.join(BASE_DIR, "daily_baseline.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

DASHBOARD_TOKEN = CONFIG["dashboard_token"]
PORT = CONFIG.get("port", 8899)
USD_TO_CNY_RATE = CONFIG.get("usd_to_cny_rate", 7.1)

# ===== 账户（API Key）管理 =====
# 支持在 config.json 中通过 "openrouter_api_keys": [{"name","api_key"}, ...] 预置多个账户；
# 仍兼容旧的单 Key 字段 "openrouter_api_key"。
# 运行时账户列表持久化在 accounts.json（仅服务端可见，绝不返回给前端明文 Key）。
_accounts_lock = threading.Lock()
_baseline_lock = threading.Lock()


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
    accounts = load_accounts()["accounts"]
    if not accounts:
        return None
    if account_id:
        for a in accounts:
            if a["id"] == account_id:
                return a
    return accounts[0]


def public_account(a):
    return {"id": a["id"], "name": a.get("name") or a["id"], "key_masked": mask_key(a.get("api_key", ""))}


def validate_openrouter_key(api_key):
    """调用 /key 校验 Key 是否有效，返回 (ok, message, key_info)。"""
    try:
        resp = requests.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code == 200:
            return True, "", resp.json().get("data", {})
        if resp.status_code in (401, 403):
            return False, "API Key 无效或已被禁用", None
        return False, f"校验失败 (HTTP {resp.status_code})", None
    except Exception as e:
        return False, f"校验失败: {e}", None


# ===== 模型发布新闻缓存（全局，与账户无关）=====
# 变化不频繁，缓存12小时
_models_cache = {"data": None, "ts": 0}
_models_cache_lock = threading.Lock()
MODELS_CACHE_TTL = 3600 * 12

# 关注的主流厂商关键词匹配规则（与前端 getModelIcon 保持一致）
VENDOR_RULES = [
    ("Anthropic", ["claude", "anthropic"]),
    ("OpenAI", ["openai/", "gpt-", " gpt", "o1-", "o3-", "o4-"]),
    ("DeepSeek", ["deepseek"]),
    ("Google", ["google/", "gemini"]),
    ("Meta", ["meta-llama", "llama"]),
    ("Qwen", ["qwen"]),
    ("Mistral", ["mistral"]),
]


def guess_vendor(model_id, model_name):
    text = f"{model_id} {model_name}".lower()
    for vendor, keys in VENDOR_RULES:
        for k in keys:
            if k in text:
                return vendor
    return None


def fetch_latest_models():
    """拉取 OpenRouter 全量模型列表，按关注厂商分组，取每家最新的一个模型作为“新闻”"""
    resp = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])

    latest_by_vendor = {}
    for m in models:
        model_id = m.get("id", "")
        model_name = m.get("name", "")
        created = m.get("created", 0)
        vendor = guess_vendor(model_id, model_name)
        if not vendor:
            continue
        cur = latest_by_vendor.get(vendor)
        if not cur or created > cur["created"]:
            latest_by_vendor[vendor] = {
                "vendor": vendor,
                "model_id": model_id,
                "model_name": model_name,
                "created": created,
            }

    news = sorted(latest_by_vendor.values(), key=lambda x: x["created"], reverse=True)
    for item in news:
        item["date"] = time.strftime("%Y-%m-%d", time.localtime(item["created"]))
    return news


def get_latest_models_cached():
    with _models_cache_lock:
        now = time.time()
        if _models_cache["data"] is not None and now - _models_cache["ts"] < MODELS_CACHE_TTL:
            return _models_cache["data"]
        data = fetch_latest_models()
        _models_cache["data"] = data
        _models_cache["ts"] = now
        return data


def fetch_app_usage(api_key, start=None, end=None, granularity="hour"):
    """调用 OpenRouter 官方 Analytics API，按 App 维度查询消费分布。
    文档: POST /api/v1/analytics/query, dimensions=["app"]，普通推理 Key 即可调用，无需 Management Key。
    不传 start/end 时默认查询近30天（用于首页“App 消费分布”卡片）。

    重要坑点：不传 granularity 参数时，OpenRouter 会把 time_range 的 start/end
    向下取整到「当天(UTC) 00:00:00」再统计，即时分秒会被忽略——例如想查“北京时间今天0点
    (=UTC前一天16:00)至今”，不传 granularity 时服务端会把 start 当成“UTC当天0点”，
    多算了8小时(前一天16:00~24:00)的历史消费，导致弹窗金额明显高于“今日消费”实际值。
    解决方式：显式传 granularity（hour/day），按返回的多个时间桶结果手动按 app 汇总求和，
    这样服务端会精确按 start/end 的具体时分秒切分，不再整天取整。
    """
    now = time.time()
    if start is None:
        start = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(now - 30 * 86400))
    if end is None:
        end = time.strftime("%Y-%m-%dT23:59:59Z", time.gmtime(now))
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/analytics/query",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "metrics": ["total_usage", "request_count", "tokens_total"],
                "dimensions": ["app"],
                "granularity": granularity,
                "time_range": {"start": start, "end": end},
                "limit": 2000,
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("data", [])
        agg = {}
        for r in rows:
            app = r.get("app") or "Unknown"
            item = agg.setdefault(app, {"app": app, "usage": 0.0, "requests": 0, "tokens_total": 0})
            item["usage"] += float(r.get("total_usage") or 0)
            item["requests"] += int(r.get("request_count") or 0)
            item["tokens_total"] += int(r.get("tokens_total") or 0)
        for item in agg.values():
            item["usage"] = round(item["usage"], 4)
        return sorted(agg.values(), key=lambda x: x["usage"], reverse=True)
    except Exception:
        return []


def fetch_app_usage_today(api_key):
    """今日（本地 0 点至现在）各 App 消费分布，用于点击“今日消费”弹窗。
    注意：Analytics API 的 time_range 使用 UTC，这里按本地时区(Asia/Shanghai, UTC+8)推算当天 0 点对应的 UTC 时间。
    """
    now = time.time()
    local_now = time.localtime(now)
    local_date_str = time.strftime("%Y-%m-%d", local_now)
    local_midnight_struct = time.strptime(local_date_str + " 00:00:00", "%Y-%m-%d %H:%M:%S")
    local_midnight_ts = time.mktime(local_midnight_struct)
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local_midnight_ts))
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    return fetch_app_usage(api_key, start=start, end=end, granularity="hour")


def fetch_app_usage_month(api_key):
    """本自然月（本地 1 号 0 点至现在）各 App 消费分布，用于点击“本月累计消费”弹窗。"""
    now = time.time()
    local_now = time.localtime(now)
    month_first_str = time.strftime("%Y-%m-01", local_now)
    local_midnight_struct = time.strptime(month_first_str + " 00:00:00", "%Y-%m-%d %H:%M:%S")
    local_midnight_ts = time.mktime(local_midnight_struct)
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(local_midnight_ts))
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    # 跨月周期可能较长，用小时粒度桶数会很多，改用天粒度即可保证精度（本月开始已是天边界，无截断问题）
    return fetch_app_usage(api_key, start=start, end=end, granularity="day")


def fetch_openrouter_summary(account):
    api_key = account["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}
    credits_resp = requests.get(
        "https://openrouter.ai/api/v1/credits", headers=headers, timeout=15
    ).json()
    key_resp = requests.get(
        "https://openrouter.ai/api/v1/key", headers=headers, timeout=15
    ).json()
    activity_resp = requests.get(
        "https://openrouter.ai/api/v1/activity", headers=headers, timeout=15
    ).json()

    credits = credits_resp.get("data", {}) or {}
    key_info = key_resp.get("data", {}) or {}
    activity = activity_resp.get("data", []) or []

    total_credits = credits.get("total_credits", 0) or 0
    total_usage = credits.get("total_usage", 0) or 0
    remaining = total_credits - total_usage

    # 按日期聚合总消费（用于趋势图）
    daily_totals = {}
    # 按模型聚合（用于排行）
    model_totals = {}

    for item in activity:
        date = item.get("date", "")[:10]
        usage = item.get("usage", 0) or 0
        requests_cnt = item.get("requests", 0) or 0
        prompt_tokens = item.get("prompt_tokens", 0) or 0
        completion_tokens = item.get("completion_tokens", 0) or 0
        model = item.get("model", "unknown")

        daily_totals.setdefault(date, 0.0)
        daily_totals[date] += usage

        m = model_totals.setdefault(
            model,
            {
                "model": model,
                "usage": 0.0,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            },
        )
        m["usage"] += usage
        m["requests"] += requests_cnt
        m["prompt_tokens"] += prompt_tokens
        m["completion_tokens"] += completion_tokens

    daily_series = sorted(
        [{"date": d, "usage": round(v, 4)} for d, v in daily_totals.items()],
        key=lambda x: x["date"],
    )
    model_ranking = sorted(
        model_totals.values(), key=lambda x: x["usage"], reverse=True
    )
    for m in model_ranking:
        m["usage"] = round(m["usage"], 4)

    # 今日消费
    # OpenRouter 的 /activity 接口有 1~2 天延迟，当天数据往往还未生成，直接取 daily_totals 会长期为 0。
    # 优先使用自己记录的“当日 0 点基准额度”推算：今日消费 = 基准额度 - 当前剩余额度
    today = time.strftime("%Y-%m-%d")
    activity_today_usage = round(daily_totals.get(today, 0.0), 4)
    today_usage = activity_today_usage
    today_usage_source = "activity"

    baseline = load_daily_baseline(account["id"])
    if not baseline or baseline.get("date") != today:
        # 当天基准不存在（例如 cron 未及时执行或服务首次启动），自动补写一个基准，以当前累计消费总额作为今日起点
        save_daily_baseline(account["id"], today, total_usage)
        baseline = {"date": today, "total_usage_at_midnight": total_usage}

    if baseline and baseline.get("date") == today:
        # 优先使用 total_usage_at_midnight（累计消费总额基准，只增不减，不受充值干扰）
        # 兼容旧版 baseline 文件（字段为 remaining_at_midnight，基于余额，会被充值干扰）
        if "total_usage_at_midnight" in baseline:
            baseline_total_usage = baseline["total_usage_at_midnight"]
            computed = round(total_usage - baseline_total_usage, 4)
        else:
            remaining_now = total_credits - total_usage
            baseline_remaining = baseline.get("remaining_at_midnight", remaining_now)
            computed = round(baseline_remaining - remaining_now, 4)
        # 取两者中较大的作为今日消费（避免 activity 滞迟导致低估），且不低于0
        today_usage = max(computed, activity_today_usage, 0.0)
        today_usage_source = "baseline" if computed >= activity_today_usage else "activity"

    # 本月累计消费
    # 说明：/activity 接口有 1~2 天延迟，当天（甚至昨天）数据常常尚未生成，
    # 若只聚合 daily_totals，会导致“本月累计”滞后，甚至出现“本月累计 < 今日消费”的倒挂。
    # 做法：优先用每日 0 点基准的历史逐日精确重建，activity 兜底，
    # 今日用实时基准推算值覆盖，最后再兜底保证 本月累计 ≥ 今日消费。
    month_prefix = today[:7]
    month_day_usage = {}
    # 1) activity 里本月已生成的天
    for d, v in daily_totals.items():
        if d.startswith(month_prefix):
            month_day_usage[d] = v
    # 2) 用 0 点基准历史精确覆盖：相邻两天基准之差 = 前一日消费
    for d, v in _history_daily_usage(account["id"]).items():
        if d.startswith(month_prefix):
            month_day_usage[d] = v
    # 3) 今日用实时值覆盖（activity 通常为 0，避免少算今天）
    month_day_usage[today] = max(today_usage, month_day_usage.get(today, 0.0))
    month_usage = round(sum(month_day_usage.values()), 4)
    # 4) 兜底：本月累计不可能小于今日消费
    month_usage = max(month_usage, round(today_usage, 4))

    return {
        "generated_at": int(time.time()),
        "account_id": account["id"],
        "account_name": account.get("name") or account["id"],
        "key_masked": mask_key(api_key),
        "key_info": {
            "label": key_info.get("label"),
            "is_free_tier": key_info.get("is_free_tier"),
            "usage": key_info.get("usage"),
            "limit": key_info.get("limit"),
            "limit_remaining": key_info.get("limit_remaining"),
        },
        "exchange_rate": {
            "usd_to_cny": USD_TO_CNY_RATE,
        },
        "account": {
            "total_credits": round(total_credits, 4),
            "remaining": round(remaining, 4),
            "total_usage": round(total_usage, 4),
            "month_usage": month_usage,
            "today_usage": today_usage,
        },
        "today_usage": today_usage,
        "today_usage_source": today_usage_source,
        "month_usage": month_usage,
        "daily_series": daily_series,
        "model_ranking": model_ranking,
        "app_ranking": fetch_app_usage(api_key),
    }


# ===== 每日基准（按账户区分）=====
# 文件结构: {"accounts": {"<account_id>": {"date","total_usage_at_midnight","captured_at"}}}
# 兼容旧版单账户结构 {"date","total_usage_at_midnight",...}，旧结构归第一个账户所有。


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
        accounts = load_accounts()["accounts"]
        if accounts and accounts[0]["id"] == account_id:
            return raw
    return None


def save_daily_baseline(account_id, date_str, total_usage_at_midnight):
    with _baseline_lock:
        raw = _read_baseline_file()
        if not isinstance(raw.get("accounts"), dict):
            # 旧版单账户格式：迁移时把旧基准归到第一个账户，避免丢失当日基准
            migrated = {"accounts": {}}
            if raw.get("date"):
                accounts = load_accounts()["accounts"]
                if accounts:
                    migrated["accounts"][accounts[0]["id"]] = dict(raw)
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
    """返回本地日期字符串的次日（用于判断基准历史是否连续）。"""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return (d + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _history_daily_usage(account_id):
    """由每日 0 点基准历史推算逐日消费：相邻两连续自然日的基准之差 = 前一日消费。
    仅当两天为连续自然日时才计算，避免中间漏采导致跨多日消费被错误归到某一天。
    """
    entry = load_daily_baseline(account_id) or {}
    hist = entry.get("history") or []
    parsed = []
    for h in hist:
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


# ===== 汇总缓存（按账户区分，60秒）=====
_cache = {}  # {account_id: {"data":..., "ts":...}}
_cache_lock = threading.Lock()
CACHE_TTL = 60


def get_summary_cached(account):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(account["id"])
        if entry and (now - entry["ts"]) < CACHE_TTL:
            return entry["data"]
    data = fetch_openrouter_summary(account)
    with _cache_lock:
        _cache[account["id"]] = {"data": data, "ts": time.time()}
    return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志，避免刷屏

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _authorized(self, qs):
        return qs.get("token", [""])[0] == DASHBOARD_TOKEN

    def _unauthorized(self):
        self._send_json({"error": "unauthorized"}, 401)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/api/accounts":
            if not self._authorized(qs):
                return self._unauthorized()
            data = load_accounts()
            self._send_json(
                {
                    "accounts": [public_account(a) for a in data["accounts"]],
                    "active": data.get("active"),
                }
            )
            return

        if parsed.path == "/api/summary":
            if not self._authorized(qs):
                return self._unauthorized()
            account = get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                self._send_json(get_summary_cached(account))
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/latest_models":
            if not self._authorized(qs):
                return self._unauthorized()
            try:
                data = get_latest_models_cached()
                self._send_json({"news": data})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/app_usage_today":
            if not self._authorized(qs):
                return self._unauthorized()
            account = get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                data = fetch_app_usage_today(account["api_key"])
                self._send_json({"app_ranking": data})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/app_usage_month":
            if not self._authorized(qs):
                return self._unauthorized()
            account = get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                data = fetch_app_usage_month(account["api_key"])
                self._send_json({"app_ranking": data})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
            return

        # 静态资源（支持子目录，如 /logos/xxx.svg）
        safe_path = os.path.normpath(parsed.path).lstrip("/")
        full_path = os.path.join(STATIC_DIR, safe_path)
        if full_path.startswith(STATIC_DIR) and os.path.isfile(full_path):
            ext = os.path.splitext(full_path)[1]
            ctype = {
                ".js": "application/javascript",
                ".css": "text/css",
                ".png": "image/png",
                ".svg": "image/svg+xml",
                ".webp": "image/webp",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".json": "application/json",
            }.get(ext, "application/octet-stream")
            self._send_file(full_path, ctype)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if not self._authorized(qs):
            return self._unauthorized()

        if parsed.path == "/api/accounts":
            # 新增账户
            body = self._read_json_body()
            name = (body.get("name") or "").strip()
            api_key = (body.get("api_key") or "").strip()
            if not api_key:
                self._send_json({"error": "请填写 API Key"}, 400)
                return
            ok, msg, key_info = validate_openrouter_key(api_key)
            if not ok:
                self._send_json({"error": msg}, 400)
                return
            with _accounts_lock:
                data = load_accounts()
                acct_id = account_id_for(api_key)
                if any(a["id"] == acct_id for a in data["accounts"]):
                    self._send_json({"error": "该 API Key 已存在"}, 409)
                    return
                account = {
                    "id": acct_id,
                    "name": name or f"账户 {len(data['accounts']) + 1}",
                    "api_key": api_key,
                }
                data["accounts"].append(account)
                data["active"] = account["id"]
                save_accounts(data)
            resp = public_account(account)
            resp["is_free_tier"] = key_info.get("is_free_tier")
            self._send_json({"ok": True, "account": resp})
            return

        if parsed.path == "/api/accounts/rename":
            body = self._read_json_body()
            acct_id = (body.get("id") or "").strip()
            name = (body.get("name") or "").strip()
            if not acct_id or not name:
                self._send_json({"error": "缺少参数"}, 400)
                return
            with _accounts_lock:
                data = load_accounts()
                found = None
                for a in data["accounts"]:
                    if a["id"] == acct_id:
                        a["name"] = name
                        found = a
                        break
                if not found:
                    self._send_json({"error": "账户不存在"}, 404)
                    return
                save_accounts(data)
            self._send_json({"ok": True, "account": public_account(found)})
            return

        self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if not self._authorized(qs):
            return self._unauthorized()

        if parsed.path == "/api/accounts":
            acct_id = qs.get("id", [""])[0]
            if not acct_id:
                self._send_json({"error": "缺少账户 ID"}, 400)
                return
            with _accounts_lock:
                data = load_accounts()
                if len(data["accounts"]) <= 1:
                    self._send_json({"error": "至少需要保留一个账户"}, 400)
                    return
                before = len(data["accounts"])
                data["accounts"] = [a for a in data["accounts"] if a["id"] != acct_id]
                if len(data["accounts"]) == before:
                    self._send_json({"error": "账户不存在"}, 404)
                    return
                if data.get("active") == acct_id:
                    data["active"] = data["accounts"][0]["id"]
                save_accounts(data)
                result = {
                    "accounts": [public_account(a) for a in data["accounts"]],
                    "active": data.get("active"),
                }
            self._send_json({"ok": True, **result})
            return

        self._send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"OpenRouter dashboard running on http://0.0.0.0:{PORT}")
    server.serve_forever()
