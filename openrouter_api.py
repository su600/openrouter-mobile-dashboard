#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenRouter 上游 API 调用与数据聚合。

包含：
- 复用连接池的全局 Session 与并发小工具
- 账户 Key 校验
- 模型列表 / 旗舰模型价格（带缓存）
- 消费分析（Analytics API：按 App / 按时间区间）
- /api/summary 的聚合逻辑（含上游异常优雅降级）

本模块不依赖 HTTP 服务层，可单独导入使用 / 单元测试。
"""
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter

from config import USD_TO_CNY_RATE
from accounts import mask_key
from baseline import load_daily_baseline, save_daily_baseline, history_daily_usage
from logging_setup import get_logger

logger = get_logger(__name__)

# ===== 全局 Session（连接池）=====
# 复用一个 requests.Session，减少每次上游请求的 TCP/TLS 握手开销
SESSION = requests.Session()
_HTTP_ADAPTER = HTTPAdapter(pool_connections=10, pool_maxsize=20)
SESSION.mount("https://", _HTTP_ADAPTER)
SESSION.mount("http://", _HTTP_ADAPTER)


def _http_get_json(url, headers=None, timeout=15):
    """GET 并解析 JSON；失败时抛出异常（由调用方决定兜底策略）。"""
    resp = SESSION.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _future_or_default(future, default, label="upstream"):
    """等待并发任务结果；若该上游失败则记录日志并返回默认值（用于优雅降级）。"""
    try:
        return future.result(), True
    except Exception as e:
        logger.warning("%s 上游获取失败: %s", label, e)
        return default, False


def validate_openrouter_key(api_key):
    """调用 /key 校验 Key 是否有效，返回 (ok, message, key_info)。"""
    try:
        resp = SESSION.get(
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
    resp = SESSION.get("https://openrouter.ai/api/v1/models", timeout=15)
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
        try:
            data = fetch_latest_models()
        except Exception as e:
            logger.warning("拉取模型列表失败: %s", e)
            raise
        _models_cache["data"] = data
        _models_cache["ts"] = now
        return data


# ===== 旗舰模型价格对比（全局，与账户无关）=====
# 提取 GPT 家族 / Claude 家族「最新一代」的旗舰模型价格，缓存1小时
_prices_cache = {"data": None, "ts": 0}
_prices_cache_lock = threading.Lock()
PRICES_CACHE_TTL = 3600

# 参与对比的家族
PRICE_FAMILIES = [
    {"key": "gpt", "label": "GPT 家族", "prefix": "openai/", "keyword": "gpt"},
    {"key": "claude", "label": "Claude 家族", "prefix": "anthropic/", "keyword": "claude"},
]


def _price_per_million(value):
    """OpenRouter 的价格是「每 token 的美元数」，统一换算成 USD / 百万 tokens。"""
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def _model_major_version(model_id, family):
    """从模型 ID 解析大版本号：gpt-6-astra -> 6；claude-opus-5.5 -> 5。"""
    if family == "gpt":
        m = re.search(r"gpt-(\d+)", model_id)
    else:
        m = re.search(r"claude-[a-z]+-(\d+)", model_id)
    return int(m.group(1)) if m else None


def _model_series(model_id, family):
    """提取模型「产品线」标识，用于同一系列只保留最新版本。
    例：openai/gpt-6-astra -> astra；anthropic/claude-opus-5.5 -> opus。
    """
    if family == "gpt":
        m = re.match(r"openai/gpt-\d+(?:\.\d+)?-(.+)$", model_id)
        return m.group(1) if m else model_id
    m = re.match(r"anthropic/claude-([a-z]+)-\d", model_id)
    return m.group(1) if m else model_id


def build_flagship_families(models):
    """从 OpenRouter 模型列表构造「最新一代」旗舰模型对比数据（纯函数，便于测试）。"""
    result = []
    for fam in PRICE_FAMILIES:
        key, label, prefix, keyword = fam["key"], fam["label"], fam["prefix"], fam["keyword"]
        bucket = []
        for m in models:
            mid = m.get("id", "")
            if not mid.startswith(prefix) or keyword not in mid:
                continue
            # 排除别名（~ 前缀）与 :batch 等变体
            if mid.startswith("~") or ":" in mid:
                continue
            # GPT 家族的 Pro 变体与基础版同价且实用价值低，不展示
            if key == "gpt" and "pro" in m.get("name", "").lower():
                continue
            ver = _model_major_version(mid, key)
            if ver is None:
                continue
            bucket.append((ver, m))
        if not bucket:
            continue
        latest = max(v for v, _ in bucket)
        rows = []
        for ver, m in bucket:
            if ver != latest:
                continue
            pricing = m.get("pricing", {}) or {}
            full_name = m.get("name", m["id"])
            rows.append(
                {
                    "id": m["id"],
                    "name": full_name.split(": ", 1)[-1],
                    "input": _price_per_million(pricing.get("prompt")),
                    "output": _price_per_million(pricing.get("completion")),
                    "cache_read": _price_per_million(pricing.get("input_cache_read")),
                    "context_length": m.get("context_length"),
                    "created": m.get("created", 0),
                }
            )
        # 同一系列只保留最新版本（created 最大者），如 Opus 5 与 5.5 只留 5.5
        newest_by_series = {}
        for r in rows:
            series = _model_series(r["id"], key)
            cur = newest_by_series.get(series)
            if cur is None or (r["created"] or 0) > (cur["created"] or 0):
                newest_by_series[series] = r
        rows = list(newest_by_series.values())
        # 旗舰在前：输出价高者优先，同价按发布时间新→旧
        rows.sort(
            key=lambda r: (
                -(r["output"] or 0),
                -(r["input"] or 0),
                -(r["created"] or 0),
                r["name"],
            )
        )
        result.append({"key": key, "label": label, "generation": latest, "models": rows})
    return result


def fetch_flagship_prices():
    """抓取 OpenRouter 模型清单，抽取 GPT / Claude 两大家族「最新一代」的旗舰模型价格，
    统一换算为 USD / 百万 tokens，供看板底部对比卡片使用。
    """
    resp = SESSION.get("https://openrouter.ai/api/v1/models", timeout=15)
    resp.raise_for_status()
    models = resp.json().get("data", [])
    return {"updated_at": int(time.time()), "families": build_flagship_families(models)}


def get_flagship_prices_cached(force=False):
    with _prices_cache_lock:
        now = time.time()
        if (
            not force
            and _prices_cache["data"] is not None
            and now - _prices_cache["ts"] < PRICES_CACHE_TTL
        ):
            return _prices_cache["data"]
        data = fetch_flagship_prices()
        _prices_cache["data"] = data
        _prices_cache["ts"] = now
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
        resp = SESSION.post(
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
    except Exception as e:
        logger.warning("按 App 统计消费失败: %s", e)
        return []


def fetch_analytics_usage(api_key, start, end, granularity):
    """返回 [start, end] 区间内的总消费金额；接口失败返回 None（区别于真实的 0）。
    用于「今日/本月」取数：Analytics API 实时性好，且天然以 UTC 自然日为界，
    与 OpenRouter 官方口径一致（对应北京时间每天 08:00 重置）。
    """
    try:
        resp = SESSION.post(
            "https://openrouter.ai/api/v1/analytics/query",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "metrics": ["total_usage"],
                "dimensions": ["app"],
                "granularity": granularity,
                "time_range": {"start": start, "end": end},
                "limit": 2000,
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("data", [])
        return round(sum(float(r.get("total_usage") or 0) for r in rows), 4)
    except Exception as e:
        logger.warning("Analytics 区间消费查询失败 [%s, %s]: %s", start, end, e)
        return None


def fetch_app_usage_today(api_key):
    """今日（UTC 自然日 0 点至现在）各 App 消费分布，用于点击“今日消费”弹窗。
    日界采用 UTC 以与 OpenRouter 官方一致（北京时间每天 08:00 重置）。
    """
    now = time.time()
    utc_date_str = time.strftime("%Y-%m-%d", time.gmtime(now))
    start = utc_date_str + "T00:00:00Z"
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    return fetch_app_usage(api_key, start=start, end=end, granularity="hour")


def fetch_app_usage_month(api_key):
    """本自然月（UTC 1 号 0 点至现在）各 App 消费分布，用于点击“本月累计消费”弹窗。"""
    now = time.time()
    utc_month = time.strftime("%Y-%m", time.gmtime(now))
    start = utc_month + "-01T00:00:00Z"
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    # 跨月周期可能较长，用天粒度即可保证精度（月起为天边界，无截断问题）
    return fetch_app_usage(api_key, start=start, end=end, granularity="day")


def fetch_openrouter_summary(account):
    """聚合单个账户的余额、消费、趋势与排行数据。

    上游接口并发拉取；任一上游失败时优雅降级（缺失字段回 None，并在 degraded 中标记）。
    """
    api_key = account["api_key"]
    headers = {"Authorization": f"Bearer {api_key}"}

    # 时间边界（UTC，与 OpenRouter 官方一致，对应北京时间 08:00 重置）
    now_ts = time.time()
    utc_today = time.strftime("%Y-%m-%d", time.gmtime(now_ts))
    utc_month = utc_today[:7]
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))

    # 并发拉取所有上游数据，总耗时由最慢的一个请求决定，而非逐个相加
    with ThreadPoolExecutor(max_workers=6) as pool:
        f_credits = pool.submit(_http_get_json, "https://openrouter.ai/api/v1/credits", headers)
        f_key = pool.submit(_http_get_json, "https://openrouter.ai/api/v1/key", headers)
        f_activity = pool.submit(_http_get_json, "https://openrouter.ai/api/v1/activity", headers)
        f_app = pool.submit(fetch_app_usage, api_key)
        f_today = pool.submit(
            fetch_analytics_usage, api_key, utc_today + "T00:00:00Z", now_iso, "hour"
        )
        f_month = pool.submit(
            fetch_analytics_usage, api_key, utc_month + "-01T00:00:00Z", now_iso, "day"
        )
        credits_resp, credits_ok = _future_or_default(f_credits, {}, "credits")
        key_resp, key_ok = _future_or_default(f_key, {}, "key")
        activity_resp, activity_ok = _future_or_default(f_activity, {}, "activity")
        app_ranking = f_app.result()
        analytics_today = f_today.result()
        analytics_month = f_month.result()

    credits = credits_resp.get("data", {}) or {}
    key_info = key_resp.get("data", {}) or {}
    activity = activity_resp.get("data", []) or []

    # 上游部分失败时优雅降级：缺失字段置 None（前端显示 “—”），而不是误报为 0
    raw_credits = credits.get("total_credits")
    raw_usage = credits.get("total_usage")
    total_credits = float(raw_credits) if raw_credits is not None else None
    total_usage = float(raw_usage) if raw_usage is not None else None
    if total_credits is not None and total_usage is not None:
        remaining = total_credits - total_usage
    else:
        remaining = None
    degraded = []
    if not credits_ok:
        degraded.append("credits")
    if not key_ok:
        degraded.append("key")
    if not activity_ok:
        degraded.append("activity")
    if analytics_today is None and analytics_month is None:
        degraded.append("analytics")

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

    # 今日 / 本月消费
    # 日界口径：与 OpenRouter 官方保持一致——以 UTC 自然日为界（对应北京时间每天 08:00 重置）。
    # 取数优先用 Analytics API（实时性远好于 /activity），避免用 total_usage 差值：
    # total_usage 结算有延迟，会在跨日瞬间把前一天的消费错记到当天，出现“今日消费不清零”的假象。
    activity_today_usage = round(daily_totals.get(utc_today, 0.0), 4)

    if analytics_today is not None:
        today_usage = analytics_today
        today_usage_source = "analytics"
    elif total_usage is not None:
        # 兜底：每日 0 点基准差值（天界同为 UTC）
        baseline = load_daily_baseline(account["id"])
        if not baseline or baseline.get("date") != utc_today:
            save_daily_baseline(account["id"], utc_today, total_usage)
            baseline = {"date": utc_today, "total_usage_at_midnight": total_usage}
        if "total_usage_at_midnight" in baseline:
            computed = round(total_usage - baseline["total_usage_at_midnight"], 4)
        else:
            remaining_now = (total_credits or 0) - total_usage
            computed = round(baseline.get("remaining_at_midnight", remaining_now) - remaining_now, 4)
        today_usage = max(computed, activity_today_usage, 0.0)
        today_usage_source = "baseline"
    else:
        # 连累计消费都取不到：退回用 /activity 的今日值（可能略滞后）
        today_usage = activity_today_usage
        today_usage_source = "activity"

    # 本月累计消费：优先 Analytics（UTC 月界）；失败时兜底用 activity + 基准历史重建
    if analytics_month is not None:
        month_usage = max(round(analytics_month, 4), round(today_usage or 0, 4))
    else:
        month_prefix = utc_month
        month_day_usage = {}
        for d, v in daily_totals.items():
            if d.startswith(month_prefix):
                month_day_usage[d] = v
        for d, v in history_daily_usage(account["id"]).items():
            if d.startswith(month_prefix):
                month_day_usage[d] = v
        month_day_usage[utc_today] = max(today_usage or 0.0, month_day_usage.get(utc_today, 0.0))
        month_usage = max(round(sum(month_day_usage.values()), 4), round(today_usage or 0, 4))

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
            "total_credits": round(total_credits, 4) if total_credits is not None else None,
            "remaining": round(remaining, 4) if remaining is not None else None,
            "total_usage": round(total_usage, 4) if total_usage is not None else None,
            "month_usage": month_usage,
            "today_usage": today_usage,
        },
        "today_usage": today_usage,
        "today_usage_source": today_usage_source,
        "month_usage": month_usage,
        "degraded": degraded,
        "daily_series": daily_series,
        "model_ranking": model_ranking,
        "app_ranking": app_ranking,
    }


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