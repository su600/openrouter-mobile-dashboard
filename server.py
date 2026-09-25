#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenRouter 手机看板 —— HTTP 服务入口。

- 服务端持有 OpenRouter API Key（支持多账户/多 Key），前端只用一个访问口令(token)
- 提供 /api/summary 聚合接口：账户余额/消费 + 近30天每日消费趋势 + 模型调用量排行
- 提供 /api/accounts 账户管理接口：查看/新增/重命名/删除多个 API Key
- 提供 /api/model_prices 旗舰模型价格对比、/api/latest_models 新品新闻
- 提供 /healthz 健康检查（无需鉴权，供 systemd / 监控探活）
- 静态页面 /（移动端自适应）

上游调用与数据聚合见 openrouter_api.py；账户与基准的持久化见 accounts.py / baseline.py。
"""
import os
import json
import time
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from config import DASHBOARD_TOKEN, PORT, STATIC_DIR
import accounts as accounts_store
import openrouter_api as api
from logging_setup import setup_logging, get_logger

logger = get_logger(__name__)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默访问日志，避免刷屏（异常另有 logger 记录）

    # ===== 响应输出 =====
    def _write_body(self, body, content_type, code=200, cache_control=None):
        """统一写出响应体：对可压缩的文本类内容按需 gzip，并设置可选的缓存策略。"""
        body = body or b""
        compressible = any(k in content_type for k in ("text/", "json", "javascript", "svg"))
        gzip_ok = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        extra = {}
        if compressible and gzip_ok and len(body) >= 1024:
            gz = gzip.compress(body, 6)
            if len(gz) < len(body):
                body = gz
                extra["Content-Encoding"] = "gzip"
                extra["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, code=200):
        self._write_body(
            json.dumps(obj, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            code=code,
        )

    def _send_file(self, path, content_type, cache_control=None):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self._write_body(body, content_type, cache_control=cache_control)

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

    # ===== 鉴权 =====
    def _authorized(self, qs):
        return qs.get("token", [""])[0] == DASHBOARD_TOKEN

    def _unauthorized(self):
        self._send_json({"error": "unauthorized"}, 401)

    # ===== GET =====
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        # 健康检查：无需鉴权，供探活使用
        if parsed.path == "/healthz":
            self._send_json({"ok": True, "time": int(time.time())})
            return

        if parsed.path == "/api/accounts":
            if not self._authorized(qs):
                return self._unauthorized()
            data = accounts_store.load_accounts()
            self._send_json(
                {
                    "accounts": [accounts_store.public_account(a) for a in data["accounts"]],
                    "active": data.get("active"),
                }
            )
            return

        if parsed.path == "/api/summary":
            if not self._authorized(qs):
                return self._unauthorized()
            account = accounts_store.get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                self._send_json(api.get_summary_cached(account))
            except Exception as e:
                logger.warning("生成 summary 失败: %s", e)
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/latest_models":
            if not self._authorized(qs):
                return self._unauthorized()
            try:
                self._send_json({"news": api.get_latest_models_cached()})
            except Exception as e:
                logger.warning("拉取最新模型失败: %s", e)
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/model_prices":
            if not self._authorized(qs):
                return self._unauthorized()
            try:
                # refresh=1 时跳过服务端缓存，强制重新抓取最新价格
                force = qs.get("refresh", ["0"])[0].lower() in ("1", "true", "yes")
                self._send_json(api.get_flagship_prices_cached(force=force))
            except Exception as e:
                logger.warning("拉取模型价格失败: %s", e)
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/app_usage_today":
            if not self._authorized(qs):
                return self._unauthorized()
            account = accounts_store.get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                self._send_json({"app_ranking": api.fetch_app_usage_today(account["api_key"])})
            except Exception as e:
                logger.warning("拉取今日 App 消费失败: %s", e)
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/api/app_usage_month":
            if not self._authorized(qs):
                return self._unauthorized()
            account = accounts_store.get_account(qs.get("account", [None])[0])
            if not account:
                self._send_json({"error": "未配置任何 API Key"}, 400)
                return
            try:
                self._send_json({"app_ranking": api.fetch_app_usage_month(account["api_key"])})
            except Exception as e:
                logger.warning("拉取本月 App 消费失败: %s", e)
                self._send_json({"error": str(e)}, 500)
            return

        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_file(
                os.path.join(STATIC_DIR, "index.html"),
                "text/html; charset=utf-8",
                cache_control="no-cache",
            )
            return

        # 静态资源（支持子目录，如 /logos/xxx.svg）
        safe_path = os.path.normpath(parsed.path).lstrip("/")
        full_path = os.path.abspath(os.path.join(STATIC_DIR, safe_path))
        # 用 commonpath 严格限定在 STATIC_DIR 内，防止路径穿越 / 前缀绕过
        try:
            inside = os.path.commonpath([STATIC_DIR, full_path]) == STATIC_DIR
        except ValueError:
            inside = False
        if inside and os.path.isfile(full_path):
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
            # 图片等静态资源可长缓存；js/json 不缓存，便于更新
            cache_control = "no-cache" if ext in (".js", ".json") else "public, max-age=86400"
            self._send_file(full_path, ctype, cache_control=cache_control)
            return

        self.send_response(404)
        self.end_headers()

    # ===== POST =====
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
            ok, msg, key_info = api.validate_openrouter_key(api_key)
            if not ok:
                self._send_json({"error": msg}, 400)
                return
            with accounts_store._accounts_lock:
                data = accounts_store.load_accounts()
                acct_id = accounts_store.account_id_for(api_key)
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
                accounts_store.save_accounts(data)
            resp = accounts_store.public_account(account)
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
            with accounts_store._accounts_lock:
                data = accounts_store.load_accounts()
                found = None
                for a in data["accounts"]:
                    if a["id"] == acct_id:
                        a["name"] = name
                        found = a
                        break
                if not found:
                    self._send_json({"error": "账户不存在"}, 404)
                    return
                accounts_store.save_accounts(data)
            self._send_json({"ok": True, "account": accounts_store.public_account(found)})
            return

        self._send_json({"error": "not found"}, 404)

    # ===== DELETE =====
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
            with accounts_store._accounts_lock:
                data = accounts_store.load_accounts()
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
                accounts_store.save_accounts(data)
                result = {
                    "accounts": [accounts_store.public_account(a) for a in data["accounts"]],
                    "active": data.get("active"),
                }
            self._send_json({"ok": True, **result})
            return

        self._send_json({"error": "not found"}, 404)


def main():
    setup_logging()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logger.info("OpenRouter dashboard running on http://0.0.0.0:%s", PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()