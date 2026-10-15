#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP route tests for GitHub Copilot account and OAuth endpoints."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.request import HTTPRedirectHandler
from unittest.mock import patch

import server


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class TestCopilotRoutes(unittest.TestCase):
    def setUp(self):
        self.auth_patch = patch.object(server, "DASHBOARD_TOKEN", "test-dashboard-token")
        self.auth_patch.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.auth_patch.stop()

    def request(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        opener = urllib.request.build_opener(NoRedirectHandler)
        try:
            with opener.open(req, timeout=3) as response:
                body = response.read().decode("utf-8")
                return response.status, response.headers, json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            return error.code, error.headers, json.loads(body) if body else {}

    def test_account_and_usage_routes_require_dashboard_token(self):
        status, _, _ = self.request("/api/copilot/accounts")
        self.assertEqual(status, 401)
        status, _, _ = self.request("/api/copilot/usage?account=github_1")
        self.assertEqual(status, 401)

    def test_account_route_returns_only_public_account_fields(self):
        with patch.object(server.github_copilot, "list_accounts", return_value=[
            {"id": "github_1", "login": "demo", "name": "Demo", "token": "must-not-be-returned"}
        ]):
            status, headers, body = self.request(
                "/api/copilot/accounts?token=test-dashboard-token"
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertNotIn("must-not-be-returned", json.dumps(body))

    def test_usage_route_returns_normalized_data_without_token(self):
        usage = {"plan": "individual", "quotas": [], "fetched_at": 123}
        with patch.object(server.github_copilot, "get_usage", return_value=usage) as get_usage:
            status, headers, body = self.request(
                "/api/copilot/usage?token=test-dashboard-token&account=github_1"
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(body, usage)
        get_usage.assert_called_once_with("github_1")

    def test_oauth_callback_rejects_invalid_state(self):
        with patch.object(server.github_copilot, "consume_oauth_state", return_value=False):
            status, headers, _ = self.request("/api/copilot/oauth/callback?state=bad&code=test")
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/?copilot_oauth=invalid")

    def test_oauth_start_requires_dashboard_token_and_redirects(self):
        status, _, body = self.request("/api/copilot/oauth/start")
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")
        with patch.object(server.github_copilot, "begin_oauth", return_value="https://github.com/authorize"):
            status, headers, _ = self.request(
                "/api/copilot/oauth/start?token=test-dashboard-token"
            )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "https://github.com/authorize")

    def test_oauth_callback_completes_only_with_valid_state(self):
        with patch.object(server.github_copilot, "consume_oauth_state", return_value=True), \
                patch.object(server.github_copilot, "exchange_oauth_code", return_value="oauth-token"), \
                patch.object(server.github_copilot, "add_oauth_account") as add_account:
            status, headers, _ = self.request(
                "/api/copilot/oauth/callback?state=valid&code=github-code"
            )
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/?copilot_oauth=connected")
        add_account.assert_called_once_with("oauth-token")


if __name__ == "__main__":
    unittest.main()
