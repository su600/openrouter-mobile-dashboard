#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP tests ensuring widget endpoints expose only read-only dashboard data."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import server


class TestWidgetRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.temp_dir.name, "widget-token")
        self.account = {
            "id": "acct_test",
            "name": "测试账户",
            "api_key": "sk-or-v1-do-not-expose-this",
            "access_status": {"state": "healthy", "source": "user_reported"},
        }
        self.patches = [
            patch.object(server, "DASHBOARD_TOKEN", "unit-test-admin-token"),
            patch.object(server.widget_auth, "WIDGET_TOKEN_PATH", self.token_path),
            patch.dict(os.environ, {"OR_WIDGET_TOKEN": ""}),
            patch.object(server.accounts_store, "load_accounts", return_value={
                "accounts": [self.account], "active": "acct_test"
            }),
            patch.object(server.accounts_store, "get_account", return_value=self.account),
            patch.object(server.api, "get_latest_models_cached", return_value=[
                {
                    "vendor": "Anthropic",
                    "model_id": "anthropic/claude-opus-5",
                    "model_name": "Anthropic: Claude Opus 5",
                    "created": 1790000000,
                    "date": "2026-09-21",
                    "api_key": "must-not-appear",
                }
            ]),
            patch.object(server.api, "get_summary_cached", return_value={
                "generated_at": 1234567890,
                "account_id": "acct_test",
                "account_name": "测试账户",
                "key_masked": "sk-or-v1-should-not-be-in-widget-response",
                "key_info": {"limit": 100, "usage": 12},
                "account": {
                    "remaining": 88.0,
                    "total_credits": 100.0,
                    "today_usage": 2.0,
                    "month_usage": 12.0,
                    "total_usage": 12.0,
                },
                "exchange_rate": {"usd_to_cny": 7.1},
                "daily_series": [{"date": "2026-09-27", "usage": 2}],
                "model_ranking": [{"model": "secret-model-detail"}],
                "app_ranking": [
                    {"app": "Codex", "usage": 1.2},
                    {"app": "Claude Code", "usage": 2.3},
                    {"app": "Pi Coding Agent", "usage": 3.4},
                    {"app": "Unrequested App", "usage": 99.0},
                ],
            }),
        ]
        for item in self.patches:
            item.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def request(self, path, method="GET", token=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        data = b"{}" if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_local_chart_bundle_is_served_with_cache_header(self):
        request = urllib.request.Request(self.base + "/vendor/chart.umd.min.js")
        with urllib.request.urlopen(request, timeout=3) as response:
            body = response.read()
            self.assertEqual(response.status, 200)
            self.assertIn("javascript", response.headers.get("Content-Type", ""))
            self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=86400")
            self.assertGreater(len(body), 100_000)

    def test_session_requires_dashboard_token_and_returns_scoped_token(self):
        status, _ = self.request("/api/widget/session", method="POST")
        self.assertEqual(status, 401)
        status, _ = self.request("/api/widget/session", method="POST", token="wrong")
        self.assertEqual(status, 401)
        status, response = self.request(
            "/api/widget/session", method="POST", token="unit-test-admin-token"
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(response["widget_token"]), 40)
        self.widget_token = response["widget_token"]

    def test_widget_manual_refresh_bypasses_summary_cache(self):
        token = server.widget_auth.get_or_create_widget_token(self.token_path)
        summary = {
            "generated_at": 123,
            "account": {"remaining": 88.0, "total_usage": 12.0, "today_usage": 2.0, "month_usage": 12.0},
            "exchange_rate": {"usd_to_cny": 7.1},
            "app_ranking": [],
        }
        with patch.object(server.api, "get_summary_cached", return_value=summary) as get_summary:
            status, _ = self.request("/api/widget/summary?account=acct_test&refresh=1", token=token)
        self.assertEqual(status, 200)
        get_summary.assert_called_once_with(self.account, force=True)

    def test_widget_accounts_redact_key_fields(self):
        token = server.widget_auth.get_or_create_widget_token(self.token_path)
        status, response = self.request("/api/widget/accounts", token=token)
        self.assertEqual(status, 200)
        account = response["accounts"][0]
        self.assertEqual(account["name"], "测试账户")
        self.assertEqual(account["access_status"]["state"], "healthy")
        self.assertNotIn("api_key", account)
        self.assertNotIn("key_masked", account)

    def test_widget_news_is_readonly_and_redacts_unrequested_fields(self):
        token = server.widget_auth.get_or_create_widget_token(self.token_path)
        status, response = self.request("/api/widget/news", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(response["news"][0]["vendor"], "Anthropic")
        self.assertEqual(response["news"][0]["model_id"], "anthropic/claude-opus-5")
        self.assertNotIn("api_key", response["news"][0])
        self.assertNotIn("must-not-appear", json.dumps(response))

    def test_widget_summary_returns_only_compact_safe_fields(self):
        token = server.widget_auth.get_or_create_widget_token(self.token_path)
        status, response = self.request("/api/widget/summary?account=acct_test", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(response["account"]["remaining"], 88.0)
        self.assertEqual(response["account"]["total_usage"], 12.0)
        self.assertEqual(response["account"]["today_usage"], 2.0)
        self.assertNotIn("total_credits", response["account"])
        self.assertEqual(response["access_status"]["source"], "user_reported")
        self.assertEqual(
            [(app["name"], app["usage"]) for app in response["apps_last_30_days"]],
            [("Pi", 3.4), ("Claude", 2.3), ("Codex", 1.2)],
        )
        self.assertNotIn("key_masked", response)
        self.assertNotIn("key_info", response)
        self.assertNotIn("daily_series", response)
        self.assertNotIn("model_ranking", response)
        self.assertNotIn("sk-or-v1", json.dumps(response))

    def test_manual_dashboard_refresh_bypasses_summary_cache(self):
        fresh = {
            "generated_at": 123,
            "account": {"remaining": 1.0},
            "exchange_rate": {"usd_to_cny": 7.1},
        }
        with patch.object(server.api, "get_summary_cached", return_value=fresh) as get_summary:
            status, response = self.request(
                "/api/summary?token=unit-test-admin-token&account=acct_test&refresh=1"
            )
        self.assertEqual(status, 200)
        self.assertEqual(response["generated_at"], 123)
        get_summary.assert_called_once_with(self.account, force=True)

    def test_dashboard_manual_refresh_bypasses_summary_cache(self):
        summary = {"generated_at": 321, "account": {}, "exchange_rate": {}}
        with patch.object(server.api, "get_summary_cached", return_value=summary) as get_summary:
            status, response = self.request(
                "/api/summary?token=unit-test-admin-token&account=acct_test&refresh=1"
            )
        self.assertEqual(status, 200)
        self.assertEqual(response["generated_at"], 321)
        get_summary.assert_called_once_with(self.account, force=True)

    def test_widget_endpoints_reject_admin_token_as_read_token(self):
        status, _ = self.request("/api/widget/accounts", token="unit-test-admin-token")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
