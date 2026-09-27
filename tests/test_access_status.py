#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工维护的账户模型访问状态标签测试，不访问模型接口。"""
import unittest

import accounts


class TestBuildAccessStatus(unittest.TestCase):
    def test_reported_restriction_uses_stop_emoji(self):
        status = accounts.build_access_status("restricted", "user_reported")
        self.assertEqual(status["emoji"], "🚫")
        self.assertEqual(status["label"], "受限")
        self.assertEqual(status["source"], "user_reported")

    def test_healthy_uses_check_emoji(self):
        status = accounts.build_access_status("healthy")
        self.assertEqual(status["emoji"], "✅")
        self.assertEqual(status["source"], "manual")

    def test_partial_and_unknown_have_distinct_emojis(self):
        self.assertEqual(accounts.build_access_status("partial")["emoji"], "⚠️")
        self.assertEqual(accounts.build_access_status("unknown")["emoji"], "❓")

    def test_invalid_state_falls_back_to_unknown(self):
        self.assertEqual(accounts.build_access_status("not-a-state")["state"], "unknown")


class TestPublicAccountStatus(unittest.TestCase):
    def test_access_status_is_public_but_api_key_is_redacted(self):
        account = {
            "id": "acct_test",
            "name": "主账户",
            "api_key": "sk-or-v1-abcdefghijklmnopqrstuvwxyz",
            "access_status": {"state": "restricted", "source": "user_reported"},
        }
        public = accounts.public_account(account)
        self.assertNotIn("api_key", public)
        self.assertEqual(public["access_status"]["emoji"], "🚫")
        self.assertEqual(public["access_status"]["source"], "user_reported")

    def test_missing_status_defaults_to_unmarked(self):
        public = accounts.public_account({"id": "acct_test", "api_key": ""})
        self.assertEqual(public["access_status"]["state"], "unknown")
        self.assertEqual(public["access_status"]["emoji"], "❓")


if __name__ == "__main__":
    unittest.main()
