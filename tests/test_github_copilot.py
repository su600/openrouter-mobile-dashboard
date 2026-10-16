#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Copilot OAuth storage and usage normalization."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import github_copilot


class TestGitHubCopilot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(
            github_copilot, "GITHUB_COPILOT_ACCOUNTS_PATH",
            os.path.join(self.temp_dir.name, "copilot-accounts.json"),
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_oauth_state_is_random_single_use_and_expiring(self):
        config_patches = [
            patch.object(github_copilot, "GITHUB_OAUTH_CLIENT_ID", "client-id"),
            patch.object(github_copilot, "GITHUB_OAUTH_CLIENT_SECRET", "client-secret"),
            patch.object(github_copilot, "GITHUB_OAUTH_REDIRECT_URI", "https://dashboard.example/callback"),
        ]
        for item in config_patches:
            item.start()
        try:
            authorization_url = github_copilot.begin_oauth()
        finally:
            for item in reversed(config_patches):
                item.stop()
        params = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertEqual(params["scope"], ["read:user"])
        state = params["state"][0]
        self.assertTrue(github_copilot.consume_oauth_state(state))
        self.assertFalse(github_copilot.consume_oauth_state(state))

    def test_oauth_account_is_saved_private_and_public_list_redacts_token(self):
        profile = {"id": 123, "login": "copilot-user", "name": "Copilot User"}
        with patch.object(github_copilot, "_github_get", return_value=profile):
            account = github_copilot.add_oauth_account("oauth-secret-token")
        self.assertEqual(account["login"], "copilot-user")
        self.assertNotIn("token", account)
        self.assertNotIn("oauth-secret-token", json.dumps(github_copilot.list_accounts()))
        mode = os.stat(github_copilot.GITHUB_COPILOT_ACCOUNTS_PATH).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_normalizes_usage_and_missing_optional_fields(self):
        usage = github_copilot.normalize_usage({
            "plan_type": "individual",
            "quota_snapshots": {
                "premium_interactions": {
                    "entitlement": 300,
                    "remaining": 240,
                    "reset_date": "2026-11-01T00:00:00Z",
                },
                "chat": {"percent_remaining": 80},
            },
        })
        self.assertEqual(usage["plan"], "individual")
        premium = usage["quotas"][0]
        self.assertEqual(premium["label"], "高级请求")
        self.assertEqual(premium["percent_remaining"], 80)
        self.assertEqual(premium["reset_date"], "2026-11-01T00:00:00Z")
        self.assertIsNone(usage["quotas"][1]["entitlement"])

    def test_normalizes_limited_quota_counts_and_payload_reset_date(self):
        usage = github_copilot.normalize_usage({
            "limited_user_quotas": {"chat": 35, "completions": 10},
            "monthly_quotas": {"chat": 100, "completions": 50},
            "quota_reset_date": "2026-12-01T00:00:00Z",
        })
        quotas = {quota["key"]: quota for quota in usage["quotas"]}
        self.assertEqual(quotas["chat"]["remaining"], 35)
        self.assertEqual(quotas["chat"]["entitlement"], 100)
        self.assertEqual(quotas["chat"]["percent_remaining"], 35)
        self.assertEqual(quotas["chat"]["reset_date"], "2026-12-01T00:00:00Z")
        self.assertEqual(quotas["completions"]["remaining"], 10)
        self.assertEqual(quotas["completions"]["entitlement"], 50)

    def test_snapshot_reset_date_takes_precedence_over_payload_reset_date(self):
        usage = github_copilot.normalize_usage({
            "quota_snapshots": {
                "chat": {"remaining": 20, "reset_date": "2026-11-01T00:00:00Z"},
            },
            "quota_reset_date_utc": "2026-12-01T00:00:00Z",
        })
        self.assertEqual(usage["quotas"][0]["reset_date"], "2026-11-01T00:00:00Z")

    def test_token_billed_usage_reads_and_aggregates_ai_credits_by_model(self):
        payload = {"usageItems": [
            {"model": "Model A", "grossQuantity": 1.25, "grossAmount": 0.12, "netAmount": 0.0},
            {"model": "Model A", "grossQuantity": 0.75, "grossAmount": 0.08, "netAmount": 0.0},
            {"model": "Model B", "grossQuantity": 3.0, "grossAmount": 0.30, "netAmount": 0.1},
        ]}
        with patch.object(github_copilot, "_github_get", return_value=payload) as get:
            usage = github_copilot._model_usage("usage-user", "stored-oauth-token", token_based_billing=True)
        self.assertIn("/billing/ai_credit/usage?", get.call_args.args[0])
        self.assertEqual(usage["unit_label"], "AI Credits")
        self.assertEqual(usage["total_usage"], 5.0)
        self.assertEqual(usage["items"][0]["model"], "Model B")
        self.assertEqual(usage["items"][0]["quantity"], 3.0)
        self.assertEqual(usage["items"][1]["quantity"], 2.0)

    def test_request_billed_usage_reads_premium_request_endpoint(self):
        with patch.object(github_copilot, "_github_get", return_value={"usageItems": []}) as get:
            usage = github_copilot._model_usage("usage-user", "stored-oauth-token")
        self.assertIn("/billing/premium_request/usage?", get.call_args.args[0])
        self.assertEqual(usage["unit_label"], "高级请求")
        self.assertEqual(usage["total_usage"], 0)

    def test_usage_uses_stored_account_token(self):
        with patch.object(github_copilot, "_github_get", side_effect=[
            {"id": 456, "login": "usage-user"},
            {"quota_snapshots": {"premium_interactions": {"remaining": 10}}},
        ]) as get:
            account = github_copilot.add_oauth_account("stored-oauth-token")
            usage = github_copilot.get_usage(account["id"])
        self.assertEqual(usage["quotas"][0]["remaining"], 10)
        get.assert_any_call("/copilot_internal/user", "stored-oauth-token")


if __name__ == "__main__":
    unittest.main()
