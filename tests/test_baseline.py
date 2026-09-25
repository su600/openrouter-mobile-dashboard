#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基准历史 / 逐日消费推算的逻辑测试（纯函数，无需网络）。"""
import unittest

import baseline


class TestNextLocalDate(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(baseline._next_local_date("2026-09-25"), "2026-09-26")
        self.assertEqual(baseline._next_local_date("2026-09-30"), "2026-10-01")

    def test_month_and_leap_year(self):
        self.assertEqual(baseline._next_local_date("2026-02-28"), "2026-03-01")  # 2026 非闰年
        self.assertEqual(baseline._next_local_date("2024-02-28"), "2024-02-29")  # 2024 闰年

    def test_invalid(self):
        self.assertEqual(baseline._next_local_date("not-a-date"), "")
        self.assertEqual(baseline._next_local_date(""), "")


class TestDailyUsageFromHistory(unittest.TestCase):
    def test_consecutive_days(self):
        hist = [
            {"date": "2026-09-01", "total_usage": 100.0},
            {"date": "2026-09-02", "total_usage": 103.5},
            {"date": "2026-09-03", "total_usage": 110.0},
        ]
        out = baseline.daily_usage_from_history(hist)
        self.assertEqual(out["2026-09-01"], 3.5)
        self.assertEqual(out["2026-09-02"], 6.5)
        self.assertNotIn("2026-09-03", out)  # 最后一天没有次日基准，无法推算

    def test_gap_is_skipped(self):
        hist = [
            {"date": "2026-09-01", "total_usage": 100.0},
            {"date": "2026-09-03", "total_usage": 120.0},
        ]
        self.assertEqual(baseline.daily_usage_from_history(hist), {})

    def test_out_of_order_is_sorted(self):
        hist = [
            {"date": "2026-09-02", "total_usage": 103.5},
            {"date": "2026-09-01", "total_usage": 100.0},
        ]
        self.assertEqual(baseline.daily_usage_from_history(hist)["2026-09-01"], 3.5)

    def test_non_monotonic_is_clamped(self):
        hist = [
            {"date": "2026-09-01", "total_usage": 100.0},
            {"date": "2026-09-02", "total_usage": 90.0},
        ]
        self.assertEqual(baseline.daily_usage_from_history(hist)["2026-09-01"], 0.0)

    def test_bad_entries_ignored(self):
        hist = ["x", None, {"date": "2026-09-01"}, {"date": "2026-09-02", "total_usage": "abc"}]
        self.assertEqual(baseline.daily_usage_from_history(hist), {})

    def test_empty(self):
        self.assertEqual(baseline.daily_usage_from_history([]), {})
        self.assertEqual(baseline.daily_usage_from_history(None), {})


if __name__ == "__main__":
    unittest.main()