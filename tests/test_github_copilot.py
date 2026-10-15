#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for GitHub Copilot account management."""
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import github_copilot


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body or {}
    return r


class TestGithubCopilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "copilot_accounts.json")
        self.patches = [
            patch.object(github_copilot.config, "COPILOT_ACCOUNTS_PATH", self.path),
            patch.object(github_copilot.config, "GITHUB_CLIENT_ID", "cid"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_poll_pending_then_success_hides_token(self):
        with patch.object(github_copilot.requests, "post",
                          return_value=_resp(body={"error": "authorization_pending"})):
            self.assertEqual(github_copilot.poll_device_flow("d")["status"], "pending")
        with patch.object(github_copilot.requests, "post", return_value=_resp(body={"access_token": "gho_x"})), \
                patch.object(github_copilot.requests, "get", return_value=_resp(body={"login": "su", "name": "Su"})):
            result = github_copilot.poll_device_flow("d")
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("token", result["account"])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        accounts = github_copilot.list_accounts()
        self.assertEqual([a["login"] for a in accounts], ["su"])
        self.assertNotIn("token", accounts[0])

    def test_usage_normalized_and_delete(self):
        with patch.object(github_copilot.requests, "get", return_value=_resp(body={"login": "su"})):
            acct = github_copilot.add_account("t")
        raw = {"copilot_plan": "pro", "quota_reset_date": "2026-11-01",
               "quota_snapshots": {"premium_interactions": {"entitlement": 300, "remaining": 100, "percent_remaining": 33.3},
                                   "chat": {"unlimited": True}}}
        with patch.object(github_copilot.requests, "get", return_value=_resp(body=raw)):
            usage = github_copilot.fetch_usage(acct["id"])
        self.assertEqual(usage["plan"], "pro")
        self.assertEqual(usage["quotas"][0]["used"], 200)
        self.assertTrue(github_copilot.delete_account(acct["id"]))
        self.assertFalse(github_copilot.delete_account(acct["id"]))

    def test_missing_client_id(self):
        with patch.object(github_copilot.config, "GITHUB_CLIENT_ID", ""):
            with self.assertRaises(github_copilot.CopilotError):
                github_copilot.start_device_flow()


if __name__ == "__main__":
    unittest.main()
