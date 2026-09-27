#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Summary cache force-refresh behavior tests; no network access."""
import unittest
from unittest.mock import patch

import openrouter_api


class TestSummaryCacheForce(unittest.TestCase):
    def setUp(self):
        with openrouter_api._cache_lock:
            self.saved_cache = dict(openrouter_api._cache)
            openrouter_api._cache.clear()

    def tearDown(self):
        with openrouter_api._cache_lock:
            openrouter_api._cache.clear()
            openrouter_api._cache.update(self.saved_cache)

    def test_force_refresh_bypasses_fresh_cached_summary(self):
        account = {"id": "unit-summary-force", "api_key": "not-a-real-key"}
        with patch.object(openrouter_api, "fetch_openrouter_summary",
                          side_effect=[{"sequence": 1}, {"sequence": 2}]) as fetch:
            first = openrouter_api.get_summary_cached(account)
            cached = openrouter_api.get_summary_cached(account)
            forced = openrouter_api.get_summary_cached(account, force=True)

        self.assertEqual(first["sequence"], 1)
        self.assertEqual(cached["sequence"], 1)
        self.assertEqual(forced["sequence"], 2)
        self.assertEqual(fetch.call_count, 2)


if __name__ == "__main__":
    unittest.main()
