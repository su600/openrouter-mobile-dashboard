#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Server-side storage for per-account OpenRouter inference keys.

These keys are deliberately separate from accounts.json's dashboard/management
credentials. Plaintext is stored only in a mode-0600, git-ignored file and is
never returned from this module's public listing API.
"""
import hmac
import json
import os
import tempfile
import threading
import time

from accounts import mask_key
from config import RUNTIME_KEYS_PATH

_lock = threading.RLock()


class RuntimeKeyStoreError(RuntimeError):
    pass


def _load_unlocked():
    if not os.path.exists(RUNTIME_KEYS_PATH):
        return {"version": 1, "keys": {}}
    try:
        with open(RUNTIME_KEYS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        # Fail closed: don't overwrite a malformed file containing secrets.
        raise RuntimeKeyStoreError("推理 Key 存储文件无法读取") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
        raise RuntimeKeyStoreError("推理 Key 存储文件格式无效")
    return data


def _save_unlocked(data):
    directory = os.path.dirname(RUNTIME_KEYS_PATH) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".runtime_keys.", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, RUNTIME_KEYS_PATH)
        os.chmod(RUNTIME_KEYS_PATH, 0o600)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def get_key(account_id):
    with _lock:
        record = _load_unlocked()["keys"].get(account_id)
        if not isinstance(record, dict):
            return None
        key = record.get("api_key")
        return key if isinstance(key, str) and key else None


def public_keys():
    """Return metadata only; never return the underlying secret."""
    with _lock:
        keys = _load_unlocked()["keys"]
        result = {}
        for account_id, record in keys.items():
            if not isinstance(record, dict):
                continue
            key = record.get("api_key")
            if not isinstance(key, str) or not key:
                continue
            result[account_id] = {
                "present": True,
                "key_masked": mask_key(key),
                "updated_at": record.get("updated_at"),
            }
        return result


def set_key(account_id, api_key):
    if not isinstance(account_id, str) or not account_id.startswith("acct_"):
        raise ValueError("账户 ID 无效")
    if not isinstance(api_key, str) or not api_key:
        raise ValueError("API Key 不能为空")
    with _lock:
        data = _load_unlocked()
        for other_id, record in data["keys"].items():
            other_key = record.get("api_key") if isinstance(record, dict) else None
            if other_id != account_id and other_key == api_key:
                raise ValueError("该推理 Key 已关联到另一个账户")
        data["keys"][account_id] = {"api_key": api_key, "updated_at": int(time.time())}
        _save_unlocked(data)


def account_for_key(api_key):
    """Return the linked account ID for a configured key, without exposing keys."""
    if not isinstance(api_key, str) or not api_key:
        return None
    with _lock:
        for account_id, record in _load_unlocked()["keys"].items():
            stored = record.get("api_key") if isinstance(record, dict) else None
            if isinstance(stored, str) and hmac.compare_digest(stored, api_key):
                return account_id
    return None


def delete_key(account_id):
    with _lock:
        data = _load_unlocked()
        if account_id not in data["keys"]:
            return False
        del data["keys"][account_id]
        _save_unlocked(data)
        return True
