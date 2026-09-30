#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy a saved OpenRouter inference key to the local Pi and Gateway runtimes."""
import hmac
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import accounts as accounts_store
import runtime_keys

PI_AUTH_PATH = Path("/root/.pi/agent/auth.json")
PI_SERVICE = "pi-agent.service"
GATEWAY_DIR = Path("/root/openrouter-api-gateway")
GATEWAY_ENV_PATH = GATEWAY_DIR / ".env"
GATEWAY_SERVICE = "gateway"
_injection_lock = threading.Lock()


class InjectionError(RuntimeError):
    pass


def _atomic_write(path, data, mode=None):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except FileNotFoundError:
            mode = 0o600
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        os.chmod(path, mode)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _replace_pi_auth(original, api_key):
    try:
        auth = json.loads(original.decode("utf-8"))
    except Exception as exc:
        raise InjectionError("Pi auth.json 无法解析；未执行注入") from exc
    if not isinstance(auth, dict):
        raise InjectionError("Pi auth.json 格式无效；未执行注入")
    provider = auth.get("openrouter")
    if not isinstance(provider, dict):
        provider = {}
    provider["type"] = "api_key"
    provider["key"] = api_key
    auth["openrouter"] = provider
    return (json.dumps(auth, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _replace_gateway_env(original, api_key):
    text = original.decode("utf-8")
    result = []
    found = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("OPENROUTER_API_KEY="):
            if not found:
                newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                result.append(f"OPENROUTER_API_KEY={api_key}{newline}")
                found = True
            # Drop duplicate assignments so the effective key is unambiguous.
        else:
            result.append(line)
    if not found:
        if result and not result[-1].endswith(("\n", "\r")):
            result[-1] += "\n"
        result.append(f"OPENROUTER_API_KEY={api_key}\n")
    return "".join(result).encode("utf-8")


def _run(args, cwd=None, timeout=60):
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        raise InjectionError("无法执行本地服务操作") from exc
    if result.returncode != 0:
        raise InjectionError("本地服务操作失败")


def _restart_pi_agent():
    _run(["systemctl", "restart", PI_SERVICE], timeout=60)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", PI_SERVICE],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise InjectionError("Pi Agent 重启后未进入 active 状态")


def _restart_gateway():
    _run(["docker-compose", "up", "-d", "--force-recreate", GATEWAY_SERVICE], cwd=GATEWAY_DIR, timeout=180)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker-compose", "ps", "-q", GATEWAY_SERVICE],
            cwd=str(GATEWAY_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
        container_id = result.stdout.strip()
        if container_id:
            health = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
            if health.returncode == 0 and health.stdout.strip() == "healthy":
                return
        time.sleep(2)
    raise InjectionError("OpenRouter Gateway 重建后健康检查未通过")


def _read_snapshot(path):
    path = Path(path)
    if not path.exists():
        return None
    return path.read_bytes(), path.stat().st_mode & 0o777


def _restore(path, snapshot):
    path = Path(path)
    if snapshot is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    data, mode = snapshot
    _atomic_write(path, data, mode)


def _target_paths(target):
    if target == "pi":
        return ["pi"]
    if target == "gateway":
        return ["gateway"]
    if target == "both":
        return ["pi", "gateway"]
    raise ValueError("注入目标无效")


def inject(account_id, target):
    """Write a saved key into selected runtime config(s), restart, and verify.

    On failure, configuration snapshots are restored and the previous runtime
    is restarted best-effort. No secret is included in return values or errors.
    """
    if not _injection_lock.acquire(blocking=False):
        raise InjectionError("另一个注入操作正在运行")
    try:
        return _inject_locked(account_id, target)
    finally:
        _injection_lock.release()


def _inject_locked(account_id, target):
    api_key = runtime_keys.get_key(account_id)
    if not api_key:
        raise ValueError("该账户尚未保存推理 API Key")
    targets = _target_paths(target)
    paths = {"pi": PI_AUTH_PATH, "gateway": GATEWAY_ENV_PATH}
    snapshots = {name: _read_snapshot(paths[name]) for name in targets}
    if any(snapshot is None for snapshot in snapshots.values()):
        raise InjectionError("目标服务配置文件不存在；未执行注入")

    try:
        if "pi" in targets:
            old_data, mode = snapshots["pi"]
            _atomic_write(PI_AUTH_PATH, _replace_pi_auth(old_data, api_key), mode)
        if "gateway" in targets:
            old_data, mode = snapshots["gateway"]
            _atomic_write(GATEWAY_ENV_PATH, _replace_gateway_env(old_data, api_key), mode)

        if "pi" in targets:
            _restart_pi_agent()
        if "gateway" in targets:
            _restart_gateway()
    except Exception as exc:
        rollback_errors = []
        for name in targets:
            try:
                _restore(paths[name], snapshots[name])
            except Exception:
                rollback_errors.append(name)
        # Restore the previous runtime state best-effort. Errors remain redacted.
        for name in targets:
            try:
                if name == "pi":
                    _restart_pi_agent()
                else:
                    _restart_gateway()
            except Exception:
                rollback_errors.append(name + "_restart")
        suffix = "；回滚时另有服务恢复错误" if rollback_errors else "；已尝试回滚"
        if isinstance(exc, (ValueError, InjectionError)):
            raise InjectionError(str(exc) + suffix) from None
        raise InjectionError("注入失败" + suffix) from None

    return {"ok": True, "account_id": account_id, "target": target}


def _service_is_active(service):
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _service_main_pid(service):
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", service],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
        )
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _process_env_value(pid, name):
    if pid <= 0:
        return None
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        prefix = name.encode("ascii") + b"="
        for entry in entries:
            if entry.startswith(prefix):
                return entry[len(prefix):].decode("utf-8", "replace")
    except (OSError, UnicodeError):
        return None
    return None


def _pi_runtime_credential():
    active = _service_is_active(PI_SERVICE)
    pid = _service_main_pid(PI_SERVICE)
    env_key = _process_env_value(pid, "OPENROUTER_API_KEY")
    if env_key:
        return {
            "status": "active" if active else "not_running",
            "source": "pi-agent.service process environment",
            "service_active": active,
            "key": env_key,
        }

    try:
        auth = json.loads(PI_AUTH_PATH.read_text(encoding="utf-8"))
        provider = auth.get("openrouter") if isinstance(auth, dict) else None
        key = provider.get("key") if isinstance(provider, dict) else None
        if isinstance(key, str) and key:
            if key.startswith("!"):
                return {
                    "status": "command_credential",
                    "source": "Pi auth.json command credential",
                    "service_active": active,
                    "key": None,
                }
            return {
                "status": "active" if active else "not_running",
                "source": "Pi auth.json",
                "service_active": active,
                "key": key,
            }
    except (OSError, ValueError, TypeError):
        return {
            "status": "unavailable",
            "source": "Pi auth.json unreadable",
            "service_active": active,
            "key": None,
        }
    return {
        "status": "missing",
        "source": "Pi Agent OpenRouter credential",
        "service_active": active,
        "key": None,
    }


def _gateway_runtime_credential():
    try:
        listed = subprocess.run(
            ["docker-compose", "ps", "-q", GATEWAY_SERVICE],
            cwd=str(GATEWAY_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
        container_id = listed.stdout.strip().splitlines()[0] if listed.returncode == 0 and listed.stdout.strip() else None
        if container_id:
            running = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
            env = subprocess.run(
                ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", container_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
            if running.returncode != 0 or env.returncode != 0:
                return {"status": "unavailable", "source": "Gateway container environment unreadable", "service_active": None, "key": None}
            key = None
            for line in env.stdout.splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    key = line.split("=", 1)[1]
            is_running = running.stdout.strip().lower() == "true"
            return {
                "status": ("active" if is_running else "not_running") if key else "missing",
                "source": "Gateway container environment",
                "service_active": is_running,
                "key": key or None,
            }
    except (OSError, subprocess.SubprocessError):
        pass

    # If no running container is discoverable, report the .env value as
    # configured-but-not-loaded, never as an active runtime credential.
    try:
        for line in GATEWAY_ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                return {
                    "status": "not_running" if key else "missing",
                    "source": "Gateway .env (container not detected)",
                    "service_active": False,
                    "key": key or None,
                }
    except OSError:
        pass
    return {
        "status": "unavailable",
        "source": "Gateway credential unavailable",
        "service_active": False,
        "key": None,
    }


def _describe_credential(credential, managed_accounts):
    key = credential.get("key") if isinstance(credential, dict) else None
    matches = {}
    if isinstance(key, str) and key:
        for account in managed_accounts:
            account_id = account.get("id")
            if not isinstance(account_id, str):
                continue
            query_key = account.get("api_key")
            if isinstance(query_key, str) and query_key and hmac.compare_digest(key, query_key):
                item = matches.setdefault(account_id, {
                    "account_id": account_id,
                    "account_name": account.get("name") or account_id,
                    "key_types": [],
                })
                item["key_types"].append("account_query")
            inference_key = runtime_keys.get_key(account_id)
            if inference_key and hmac.compare_digest(key, inference_key):
                item = matches.setdefault(account_id, {
                    "account_id": account_id,
                    "account_name": account.get("name") or account_id,
                    "key_types": [],
                })
                item["key_types"].append("inference")
    return {
        "status": credential.get("status", "unavailable"),
        "source": credential.get("source", "unknown"),
        "service_active": credential.get("service_active"),
        "key_masked": accounts_store.mask_key(key) if isinstance(key, str) and key else "",
        "matches": list(matches.values()),
    }


def check_current_keys(managed_accounts=None):
    """Inspect local runtime credentials and return account matches plus masks only."""
    if managed_accounts is None:
        managed_accounts = accounts_store.load_accounts()["accounts"]
    return {
        "checked_at": int(time.time()),
        "pi_agent": _describe_credential(_pi_runtime_credential(), managed_accounts),
        "gateway": _describe_credential(_gateway_runtime_credential(), managed_accounts),
    }
