#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import runtime_keys


class TestRuntimeKeys(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "runtime_keys.json")
        self.patch_path = patch.object(runtime_keys, "RUNTIME_KEYS_PATH", self.path)
        self.patch_path.start()
        self.addCleanup(self.patch_path.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def test_store_is_private_and_public_listing_never_contains_secret(self):
        key = "sk-or-v1-" + "a" * 64
        runtime_keys.set_key("acct_one", key)
        public = runtime_keys.public_keys()
        self.assertEqual(public["acct_one"]["key_masked"], runtime_keys.mask_key(key))
        self.assertNotIn(key, json.dumps(public))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        with open(self.path, encoding="utf-8") as f:
            stored = json.load(f)
        self.assertEqual(stored["keys"]["acct_one"]["api_key"], key)

    def test_replace_and_delete_are_account_scoped(self):
        first = "sk-or-v1-" + "a" * 64
        second = "sk-or-v1-" + "b" * 64
        runtime_keys.set_key("acct_one", first)
        runtime_keys.set_key("acct_one", second)
        self.assertEqual(runtime_keys.get_key("acct_one"), second)
        self.assertEqual(runtime_keys.account_for_key(second), "acct_one")
        self.assertTrue(runtime_keys.delete_key("acct_one"))
        self.assertIsNone(runtime_keys.get_key("acct_one"))
        self.assertFalse(runtime_keys.delete_key("acct_one"))

    def test_same_key_cannot_be_assigned_to_another_account(self):
        key = "sk-or-v1-" + "c" * 64
        runtime_keys.set_key("acct_one", key)
        with self.assertRaisesRegex(ValueError, "另一个账户"):
            runtime_keys.set_key("acct_two", key)

    def test_corrupt_store_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not-json")
        with self.assertRaises(runtime_keys.RuntimeKeyStoreError):
            runtime_keys.set_key("acct_one", "sk-or-v1-" + "d" * 64)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "not-json")


if __name__ == "__main__":
    unittest.main()
