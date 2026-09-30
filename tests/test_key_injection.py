#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import key_injection
import runtime_keys


class TestKeyInjection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.auth_path = root / "auth.json"
        self.env_path = root / ".env"
        self.key_path = root / "runtime_keys.json"
        self.auth_path.write_text(json.dumps({"openrouter": {"type": "api_key", "key": "old-pi"}, "other": {"type": "api_key", "key": "keep"}}))
        self.auth_path.chmod(0o600)
        self.env_path.write_text("DOMAIN=test.example\nOPENROUTER_API_KEY=old-gateway\nCLIENT_API_KEYS=keep-client\n")
        self.env_path.chmod(0o600)
        self.patches = [
            patch.object(key_injection, "PI_AUTH_PATH", self.auth_path),
            patch.object(key_injection, "GATEWAY_ENV_PATH", self.env_path),
            patch.object(runtime_keys, "RUNTIME_KEYS_PATH", str(self.key_path)),
            patch.object(key_injection, "_restart_pi_agent"),
            patch.object(key_injection, "_restart_gateway"),
        ]
        for item in self.patches:
            item.start()
        self.addCleanup(self.temp_dir.cleanup)
        self.addCleanup(self._stop_patches)

    def _stop_patches(self):
        for item in reversed(self.patches):
            item.stop()

    def test_inject_both_updates_only_upstream_credentials_and_preserves_permissions(self):
        key = "sk-or-v1-" + "e" * 64
        runtime_keys.set_key("acct_test", key)
        result = key_injection.inject("acct_test", "both")
        auth = json.loads(self.auth_path.read_text())
        self.assertEqual(auth["openrouter"]["key"], key)
        self.assertEqual(auth["other"]["key"], "keep")
        env = self.env_path.read_text()
        self.assertIn("OPENROUTER_API_KEY=" + key, env)
        self.assertIn("CLIENT_API_KEYS=keep-client", env)
        self.assertEqual(self.auth_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result, {"ok": True, "account_id": "acct_test", "target": "both"})

    def test_gateway_env_replaces_duplicate_assignments(self):
        data = b"OPENROUTER_API_KEY=first\nOTHER=value\nOPENROUTER_API_KEY=second\n"
        result = key_injection._replace_gateway_env(data, "sk-or-v1-new")
        self.assertEqual(result.decode().count("OPENROUTER_API_KEY="), 1)
        self.assertIn("OPENROUTER_API_KEY=sk-or-v1-new", result.decode())
        self.assertIn("OTHER=value", result.decode())

    def test_failed_second_target_rolls_back_both_files(self):
        key = "sk-or-v1-" + "f" * 64
        runtime_keys.set_key("acct_test", key)
        old_auth = self.auth_path.read_bytes()
        old_env = self.env_path.read_bytes()
        with patch.object(key_injection, "_restart_pi_agent", side_effect=[None, None]) as restart_pi, \
             patch.object(key_injection, "_restart_gateway", side_effect=[key_injection.InjectionError("gateway failed"), None]) as restart_gateway:
            with self.assertRaises(key_injection.InjectionError):
                key_injection.inject("acct_test", "both")
        self.assertEqual(self.auth_path.read_bytes(), old_auth)
        self.assertEqual(self.env_path.read_bytes(), old_env)
        self.assertEqual(restart_pi.call_count, 2)
        self.assertEqual(restart_gateway.call_count, 2)

    def test_current_key_check_matches_query_and_inference_keys_without_returning_secrets(self):
        import json

        query_key = "sk-or-v1-" + "m" * 64
        inference_key = "sk-or-v1-" + "n" * 64
        runtime_keys.set_key("acct_test", inference_key)
        accounts = [{"id": "acct_test", "name": "Test account", "api_key": query_key}]
        with patch.object(key_injection, "_pi_runtime_credential", return_value={
            "status": "active", "source": "Pi auth.json", "service_active": True, "key": query_key
        }), patch.object(key_injection, "_gateway_runtime_credential", return_value={
            "status": "active", "source": "Gateway container environment", "service_active": True, "key": inference_key
        }):
            result = key_injection.check_current_keys(accounts)
        self.assertEqual(result["pi_agent"]["matches"][0]["account_name"], "Test account")
        self.assertEqual(result["pi_agent"]["matches"][0]["key_types"], ["account_query"])
        self.assertEqual(result["gateway"]["matches"][0]["key_types"], ["inference"])
        self.assertEqual(result["pi_agent"]["key_masked"], runtime_keys.mask_key(query_key))
        serialized = json.dumps(result)
        self.assertNotIn(query_key, serialized)
        self.assertNotIn(inference_key, serialized)

    def test_missing_key_and_invalid_target_do_not_touch_configs(self):
        old_auth = self.auth_path.read_bytes()
        old_env = self.env_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "尚未保存"):
            key_injection.inject("acct_missing", "pi")
        runtime_keys.set_key("acct_test", "sk-or-v1-" + "g" * 64)
        with self.assertRaisesRegex(ValueError, "目标"):
            key_injection.inject("acct_test", "shell")
        self.assertEqual(self.auth_path.read_bytes(), old_auth)
        self.assertEqual(self.env_path.read_bytes(), old_env)


if __name__ == "__main__":
    unittest.main()
