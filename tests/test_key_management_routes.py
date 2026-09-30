#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP route tests for server-side inference-key management."""
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


class TestInferenceKeyRoutes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.key_path = os.path.join(self.temp_dir.name, "runtime_keys.json")
        self.account = {
            "id": "acct_test",
            "name": "Test account",
            "api_key": "management-key-never-return-this",
            "access_status": {"state": "unknown", "source": "manual"},
        }
        self.patches = [
            patch.object(server, "DASHBOARD_TOKEN", "test-admin-token"),
            patch.object(server, "RUNTIME_KEY_MANAGEMENT_ENABLED", True),
            patch.object(server.runtime_keys, "RUNTIME_KEYS_PATH", self.key_path),
            patch.object(server.accounts_store, "load_accounts", return_value={
                "accounts": [self.account], "active": "acct_test"
            }),
            patch.object(server.api, "validate_openrouter_key", return_value=(True, "", {"usage": 0})),
            patch.object(server.key_injection, "check_current_keys", return_value={
                "pi_agent": {"status": "active", "matches": [], "key_masked": ""},
                "gateway": {"status": "active", "matches": [], "key_masked": ""},
            }),
        ]
        for item in self.patches:
            item.start()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        if getattr(self, "httpd", None):
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=2)
            self.httpd = None
        for item in reversed(getattr(self, "patches", [])):
            item.stop()
        if getattr(self, "temp_dir", None):
            self.temp_dir.cleanup()
            self.temp_dir = None

    def request(self, path, method="GET", token=None, body=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.headers, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read().decode("utf-8"))

    def test_saving_key_requires_header_auth_and_never_returns_secret(self):
        key = "sk-or-v1-" + "h" * 64
        status, _, _ = self.request(
            "/api/accounts/inference-key", method="POST", body={"account_id": "acct_test", "api_key": key}
        )
        self.assertEqual(status, 401)
        status, headers, response = self.request(
            "/api/accounts/inference-key", method="POST", token="test-admin-token",
            body={"account_id": "acct_test", "api_key": key},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertNotIn(key, json.dumps(response))
        self.assertEqual(server.runtime_keys.get_key("acct_test"), key)

    def test_account_list_exposes_only_masked_inference_key_metadata(self):
        key = "sk-or-v1-" + "i" * 64
        server.runtime_keys.set_key("acct_test", key)
        status, headers, response = self.request("/api/accounts?token=test-admin-token")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        public = response["accounts"][0]
        self.assertTrue(public["inference_key_present"])
        self.assertEqual(public["inference_key_masked"], server.accounts_store.mask_key(key))
        self.assertNotIn(key, json.dumps(response))
        self.assertNotIn("management-key-never-return-this", json.dumps(response))

    def test_delete_local_key_requires_header_auth(self):
        server.runtime_keys.set_key("acct_test", "sk-or-v1-" + "j" * 64)
        status, _, _ = self.request("/api/accounts/inference-key?id=acct_test", method="DELETE")
        self.assertEqual(status, 401)
        status, _, response = self.request(
            "/api/accounts/inference-key?id=acct_test", method="DELETE", token="test-admin-token"
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["deleted"])
        self.assertIsNone(server.runtime_keys.get_key("acct_test"))

    def test_injection_requires_auth_and_uses_fixed_target_argument(self):
        key = "sk-or-v1-" + "k" * 64
        server.runtime_keys.set_key("acct_test", key)
        with patch.object(server.key_injection, "inject", return_value={
            "ok": True, "account_id": "acct_test", "target": "gateway"
        }) as inject:
            status, _, _ = self.request(
                "/api/accounts/inject", method="POST", body={"account_id": "acct_test", "target": "gateway"}
            )
            self.assertEqual(status, 401)
            status, headers, response = self.request(
                "/api/accounts/inject", method="POST", token="test-admin-token",
                body={"account_id": "acct_test", "target": "gateway"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertNotIn(key, json.dumps(response))
        inject.assert_called_once_with("acct_test", "gateway")

    def test_injection_status_is_read_only_and_returns_masked_account_match(self):
        masked = "sk-or-v1-ab...cdef"
        report = {
            "checked_at": 123,
            "pi_agent": {
                "status": "active", "source": "Pi auth.json", "service_active": True,
                "key_masked": masked,
                "matches": [{"account_id": "acct_test", "account_name": "Test account", "key_types": ["account_query"]}],
            },
            "gateway": {"status": "missing", "source": "Gateway container", "service_active": True, "key_masked": "", "matches": []},
        }
        with patch.object(server.key_injection, "check_current_keys", return_value=report) as check:
            status, headers, response = self.request(
                "/api/accounts/injection-status", token="test-admin-token"
            )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(response["pi_agent"]["matches"][0]["key_types"], ["account_query"])
        self.assertNotIn("api_key", json.dumps(response))
        check.assert_called_once_with([self.account])

    def test_feature_flag_keeps_secret_management_disabled_by_default(self):
        with patch.object(server, "RUNTIME_KEY_MANAGEMENT_ENABLED", False):
            status, _, _ = self.request(
                "/api/accounts/injection-status", token="test-admin-token"
            )
        self.assertEqual(status, 401)

    def test_bad_origin_is_rejected(self):
        key = "sk-or-v1-" + "l" * 64
        data = json.dumps({"account_id": "acct_test", "api_key": key}).encode()
        req = urllib.request.Request(
            self.base + "/api/accounts/inference-key",
            data=data,
            headers={
                "Authorization": "Bearer test-admin-token",
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        self.assertEqual(status, 401)
        self.assertIsNone(server.runtime_keys.get_key("acct_test"))


if __name__ == "__main__":
    unittest.main()
