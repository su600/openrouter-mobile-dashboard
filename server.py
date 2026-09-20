#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenRouter 手机看板后端
- 服务端持有 OpenRouter API Key，前端只用一个访问口令(token)
- 提供 /api/summary 聚合接口：账户余额/消费 + 近30天每日消费趋势 + 模型调用量排行
- 静态页面 /（移动端自适应）
"""
import os
import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")
BASELINE_PATH = os.path.join(BASE_DIR, "daily_baseline.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

OPENROUTER_KEY = CONFIG["openrouter_api_key"]
DASHBOARD_TOKEN = CONFIG["dashboard_token"]
PORT = CONFIG.get("port", 8899)
USD_TO_CNY_RATE = CONFIG.get("usd_to_cny_rate", 7.1)

HEADERS = {"Authorization": f"Bearer {OPENROUTER_KEY}"}

# 简单的内存缓存，避免频繁打 OpenRouter API（60秒缓存）
_cache = {"data": None, "ts": 0}
_cache_lock = threading.Lock()
CACHE_TTL = 60

# 模型发布新闻满三方缓存（变化不频繁，缓存1小时）
_models_cache = {"data": None, "ts": 0}
_models_cache_lock = threading.Lock()
MODELS_CACHE_TTL = 3600 * 12  # 12小时缓存

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


def fetch_app_usage():
    """调用 OpenRouter 官方 Analytics API，按 App 维度查询近30天消费分布。
    文档: POST /api/v1/analytics/query, dimensions=["app"]，普通推理 Key 即可调用，无需 Management Key。
    """
    now = time.time()
    start = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(now - 30 * 86400))
    end = time.strftime("%Y-%m-%dT23:59:59Z", time.gmtime(now))
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/analytics/query",
            headers={**HEADERS, "Content-Type": "application/json"},
            json={
                "metrics": ["total_usage", "request_count", "tokens_total"],
                "dimensions": ["app"],
                "order_by": {"field": "total_usage", "direction": "desc"},
                "time_range": {"start": start, "end": end},
                "limit": 20,
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json().get("data", {}).get("data", [])
        result = []
        for r in rows:
            result.append({
                "app": r.get("app") or "Unknown",
                "usage": round(float(r.get("total_usage") or 0), 4),
                "requests": int(r.get("request_count") or 0),
                "tokens_total": int(r.get("tokens_total") or 0),
            })
        return result
    except Exception:
        return []


def fetch_openrouter_summary():
    credits_resp = requests.get(
        "https://openrouter.ai/api/v1/credits", headers=HEADERS, timeout=15
    ).json()
    key_resp = requests.get(
        "https://openrouter.ai/api/v1/key", headers=HEADERS, timeout=15
    ).json()
    activity_resp = requests.get(
        "https://openrouter.ai/api/v1/activity", headers=HEADERS, timeout=15
    ).json()

    credits = credits_resp.get("data", {})
    key_info = key_resp.get("data", {})
    activity = activity_resp.get("data", [])

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

    baseline = load_daily_baseline()
    if not baseline or baseline.get("date") != today:
        # 当天基准不存在（例如 cron 未及时执行或服务首次启动），自动补写一个基准，以当前累计消费总额作为今日起点
        save_daily_baseline(today, total_usage)
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

    # 本月累计消费（按当前自然月聚合 daily_totals）
    month_prefix = time.strftime("%Y-%m")
    month_usage = round(
        sum(v for d, v in daily_totals.items() if d.startswith(month_prefix)), 4
    )

    return {
        "generated_at": int(time.time()),
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
        "app_ranking": fetch_app_usage(),
    }


def load_daily_baseline():
    if os.path.exists(BASELINE_PATH):
        try:
            with open(BASELINE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_daily_baseline(date_str, total_usage_at_midnight):
    tmp = BASELINE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {
                "date": date_str,
                "total_usage_at_midnight": total_usage_at_midnight,
                "captured_at": int(time.time()),
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    os.replace(tmp, BASELINE_PATH)


def get_summary_cached():
    with _cache_lock:
        now = time.time()
        if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
            return _cache["data"]
    data = fetch_openrouter_summary()
    with _cache_lock:
        _cache["data"] = data
        _cache["ts"] = time.time()
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

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/api/summary":
            token = qs.get("token", [""])[0]
            if token != DASHBOARD_TOKEN:
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                data = get_summary_cached()
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/latest_models":
            token = qs.get("token", [""])[0]
            if token != DASHBOARD_TOKEN:
                self._send_json({"error": "unauthorized"}, 401)
                return
            try:
                data = get_latest_models_cached()
                self._send_json({"news": data})
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


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"OpenRouter dashboard running on http://0.0.0.0:{PORT}")
    server.serve_forever()
