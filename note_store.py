#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe persistent storage for the shared dashboard note."""
import os
import tempfile
import threading

from config import BASE_DIR

NOTE_PATH = os.path.join(BASE_DIR, "dashboard_note.txt")
NOTE_MAX_LENGTH = 100_000
_note_lock = threading.Lock()


def load_note():
    with _note_lock:
        try:
            with open(NOTE_PATH, "r", encoding="utf-8") as note_file:
                return note_file.read()
        except FileNotFoundError:
            return ""


def save_note(note):
    if not isinstance(note, str):
        raise ValueError("note must be text")
    if len(note) > NOTE_MAX_LENGTH:
        raise ValueError("note is too long")

    directory = os.path.dirname(NOTE_PATH) or "."
    with _note_lock:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, prefix=".dashboard-note-", delete=False
            ) as note_file:
                temp_path = note_file.name
                note_file.write(note)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, NOTE_PATH)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

    return note
