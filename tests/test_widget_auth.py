#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the widget's scoped read-only credential."""
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import widget_auth


class TestWidgetAuth(unittest.TestCase):
    def test_creates_stable_owner_only_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "widget-token")
            first = widget_auth.get_or_create_widget_token(path)
            second = widget_auth.get_or_create_widget_token(path)

            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 40)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_widget_token_uses_bearer_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "widget-token")
            token = widget_auth.get_or_create_widget_token(path)
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(widget_auth.widget_authorized(f"Bearer {token}", path))
                self.assertFalse(widget_auth.widget_authorized("Bearer wrong", path))
                self.assertFalse(widget_auth.widget_authorized(token, path))

    def test_admin_exchange_requires_configured_bearer_token(self):
        self.assertTrue(widget_auth.dashboard_authorized("Bearer admin", "admin"))
        self.assertFalse(widget_auth.dashboard_authorized("Bearer wrong", "admin"))
        self.assertFalse(widget_auth.dashboard_authorized("admin", "admin"))
        self.assertFalse(widget_auth.dashboard_authorized("Bearer changeme", "changeme"))

    def test_environment_readonly_token_is_supported(self):
        with patch.dict(os.environ, {"OR_WIDGET_TOKEN": "env-readonly-token"}, clear=True):
            self.assertEqual(widget_auth.get_or_create_widget_token("/unused"), "env-readonly-token")
            self.assertTrue(widget_auth.widget_authorized("Bearer env-readonly-token", "/unused"))
            self.assertFalse(widget_auth.widget_authorized("Bearer other", "/unused"))


if __name__ == "__main__":
    unittest.main()
