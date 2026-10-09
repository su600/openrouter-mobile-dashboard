#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for the shared dashboard note store."""
import os
import tempfile
import unittest
from unittest.mock import patch

import note_store


class TestNoteStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.note_path = os.path.join(self.temp_dir.name, "dashboard_note.txt")
        self.patch = patch.object(note_store, "NOTE_PATH", self.note_path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def test_missing_note_is_empty_and_saved_note_round_trips(self):
        self.assertEqual(note_store.load_note(), "")
        note_store.save_note("记事内容\n第二行")
        self.assertEqual(note_store.load_note(), "记事内容\n第二行")
        self.assertEqual(os.stat(self.note_path).st_mode & 0o777, 0o600)

    def test_rejects_oversized_note(self):
        with self.assertRaises(ValueError):
            note_store.save_note("x" * (note_store.NOTE_MAX_LENGTH + 1))
        self.assertFalse(os.path.exists(self.note_path))


if __name__ == "__main__":
    unittest.main()
