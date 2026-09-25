#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账户脱敏 / ID 派生等纯函数测试（不写文件、不联网）。"""
import unittest

import accounts


class TestMaskKey(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(accounts.mask_key(""), "")

    def test_short(self):
        self.assertEqual(accounts.mask_key("short"), "shor****")

    def test_long(self):
        key = "sk-or-v1-abcdefghijklmnopqrstuvwxyz"
        masked = accounts.mask_key(key)
        self.assertEqual(masked, key[:10] + "..." + key[-4:])
        self.assertNotIn("mnop", masked)  # 中间部分被隐藏


class TestAccountId(unittest.TestCase):
    def test_stable_and_unique(self):
        self.assertEqual(accounts.account_id_for("abc"), accounts.account_id_for("abc"))
        self.assertNotEqual(accounts.account_id_for("abc"), accounts.account_id_for("abd"))

    def test_prefix(self):
        self.assertTrue(accounts.account_id_for("abc").startswith("acct_"))


class TestPublicAccount(unittest.TestCase):
    def test_masks_key(self):
        a = {"id": "acct_x", "name": "主账户", "api_key": "sk-or-v1-1234567890abcdef"}
        p = accounts.public_account(a)
        self.assertEqual(p["id"], "acct_x")
        self.assertEqual(p["name"], "主账户")
        self.assertNotIn("api_key", p)
        self.assertIn("key_masked", p)

    def test_missing_name_falls_back_to_id(self):
        p = accounts.public_account({"id": "acct_y", "api_key": ""})
        self.assertEqual(p["name"], "acct_y")


if __name__ == "__main__":
    unittest.main()