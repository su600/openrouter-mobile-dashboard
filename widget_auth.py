#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scoped read-only credential for the Android home-screen widget."""
import hmac
import os
import secrets
import threading

from config import WIDGET_TOKEN_PATH

_lock = threading.Lock()


def _bearer_value(header):
    if not header:
        return ""
    scheme, separator, value = header.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return ""
    return value.strip()


def dashboard_authorized(header, expected_token):
    """Only a configured dashboard token may mint a widget read-only token."""
    provided = _bearer_value(header)
    if not provided or not expected_token or expected_token == "changeme":
        return False
    return hmac.compare_digest(provided, expected_token)


def get_or_create_widget_token(path=None):
    """Return a persistent random token, stored locally with owner-only access."""
    env_token = os.environ.get("OR_WIDGET_TOKEN")
    if env_token:
        return env_token

    token_path = path or WIDGET_TOKEN_PATH
    directory = os.path.dirname(token_path)
    os.makedirs(directory, exist_ok=True)

    with _lock:
        try:
            with open(token_path, "r", encoding="utf-8") as token_file:
                token = token_file.read().strip()
            if token:
                os.chmod(token_path, 0o600)
                return token
        except FileNotFoundError:
            pass

        token = secrets.token_urlsafe(32)
        try:
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            with open(token_path, "r", encoding="utf-8") as token_file:
                token = token_file.read().strip()
            if not token:
                raise RuntimeError("Widget token file exists but is empty")
            os.chmod(token_path, 0o600)
            return token

        with os.fdopen(fd, "w", encoding="utf-8") as token_file:
            token_file.write(token + "\n")
            token_file.flush()
            os.fsync(token_file.fileno())
        os.chmod(token_path, 0o600)
        return token


def widget_authorized(header, path=None):
    provided = _bearer_value(header)
    if not provided:
        return False
    expected = os.environ.get("OR_WIDGET_TOKEN") or get_or_create_widget_token(path)
    return bool(expected) and hmac.compare_digest(provided, expected)
