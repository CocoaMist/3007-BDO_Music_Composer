"""Crash-aware single-executable update staging and Windows replacement."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Any

from bdo_common.atomic_io import atomic_write_json
from bdo_music_composer.app.application_metadata import (
    UPDATE_APP_ID,
    UPDATE_PROTOCOL_VERSION,
)
from bdo_music_composer.core.project_paths import USER_DATA_DIR
from bdo_music_composer.update.manifest import EXPECTED_EXECUTABLE_NAME


APPLY_UPDATE_ARGUMENT = "--apply-update-v1"
POST_UPDATE_ARGUMENT = "--post-update-v1"
POST_UPDATE_STATE_ENVIRONMENT = "BDO_POST_UPDATE_STATE"
POST_UPDATE_TOKEN_ENVIRONMENT = "BDO_POST_UPDATE_TOKEN"
UPDATE_ROOT = USER_DATA_DIR / "updates"
PLAN_NAME = "update-plan-v1.json"
STATE_NAME = "update-state-v1.json"
READY_NAME = "ready-update-v1.json"
HEALTH_TIMEOUT_SECONDS = 45.0
MAX_PLAN_BYTES = 32 * 1024


class UpdateInstallError(RuntimeError):
    pass


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_PLAN_BYTES:
        raise UpdateInstallError("update plan is too large")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateInstallError("update plan is invalid") from exc
    if not isinstance(parsed, dict):
        raise UpdateInstallError("update plan is invalid")
    return parsed


def create_install_plan(
    staged_executable: str | Path,
    *,
    version: str,
    sha256: str,
    target_executable: str | Path | None = None,
    parent_pid: int | None = None,
) -> tuple[Path, str]:
    staged = Path(staged_executable).resolve(strict=True)
    target = Path(target_executable or sys.executable).resolve(strict=True)
    if staged.name != EXPECTED_EXECUTABLE_NAME:
        raise UpdateInstallError("unexpected staged executable name")
    if target.name != EXPECTED_EXECUTABLE_NAME:
        raise UpdateInstallError("unexpected target executable name")
    if staged == target:
        raise UpdateInstallError("staged and target executables must differ")
    if not target.is_file():
        raise UpdateInstallError("target executable is missing")
    normalized_digest = str(sha256).casefold()
    if file_sha256(staged) != normalized_digest:
        raise UpdateInstallError("staged executable digest mismatch")
    token = secrets.token_hex(32)
    plan = {
        "schema_version": 1,
        "app_id": UPDATE_APP_ID,
        "protocol": UPDATE_PROTOCOL_VERSION,
        "version": str(version),
        "sha256": normalized_digest,
        "staged_executable": str(staged),
        "target_executable": str(target),
        "parent_pid": int(parent_pid if parent_pid is not None else os.getpid()),
        "token": token,
    }
    plan_path = staged.parent / PLAN_NAME
    atomic_write_json(plan_path, plan)
    return plan_path, token


def record_ready_update(
    staged_executable: str | Path,
    *,
    version: str,
    sha256: str,
) -> Path:
    staged = Path(staged_executable).resolve(strict=True)
    if staged.name != EXPECTED_EXECUTABLE_NAME or file_sha256(staged) != str(sha256):
        raise UpdateInstallError("prepared update is invalid")
    ready_path = UPDATE_ROOT / READY_NAME
    atomic_write_json(ready_path, {
        "schema_version": 1,
        "app_id": UPDATE_APP_ID,
        "protocol": UPDATE_PROTOCOL_VERSION,
        "version": str(version),
        "sha256": str(sha256),
        "staged_executable": str(staged),
    })
    return ready_path


def launch_ready_update_on_startup() -> bool:
    """Hand a prepared update to its own updater mode before GUI startup."""

    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    ready_path = UPDATE_ROOT / READY_NAME
    if not ready_path.is_file():
        return False
    try:
        ready = _load_json_object(ready_path)
        if set(ready) != {
            "schema_version", "app_id", "protocol", "version", "sha256", "staged_executable",
        } or (
            ready["schema_version"] != 1
            or ready["app_id"] != UPDATE_APP_ID
            or ready["protocol"] != UPDATE_PROTOCOL_VERSION
        ):
            raise UpdateInstallError("prepared update schema is invalid")
        from bdo_music_composer.app.application_metadata import APP_VERSION
        from bdo_music_composer.app.update_check import SemanticVersion

        if SemanticVersion.parse(str(ready["version"])) <= SemanticVersion.parse(APP_VERSION):
            ready_path.unlink(missing_ok=True)
            return False
        staged = Path(str(ready["staged_executable"])).resolve(strict=True)
        plan_path, token = create_install_plan(
            staged,
            version=str(ready["version"]),
            sha256=str(ready["sha256"]),
        )
        subprocess.Popen(
            [str(staged), APPLY_UPDATE_ARGUMENT, str(plan_path), token],
            close_fds=True,
        )
        return True
    except (OSError, ValueError, UpdateInstallError):
        return False


def _validated_plan(
    plan_path: str | Path,
    token: str,
    *,
    running_executable: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(plan_path).resolve(strict=True)
    plan = _load_json_object(path)
    if set(plan) != {
        "schema_version", "app_id", "protocol", "version", "sha256",
        "staged_executable", "target_executable", "parent_pid", "token",
    }:
        raise UpdateInstallError("update plan schema is invalid")
    if (
        plan["schema_version"] != 1
        or plan["app_id"] != UPDATE_APP_ID
        or plan["protocol"] != UPDATE_PROTOCOL_VERSION
        or not secrets.compare_digest(str(plan["token"]), str(token))
    ):
        raise UpdateInstallError("update plan identity is invalid")
    staged = Path(str(plan["staged_executable"])).resolve(strict=True)
    target = Path(str(plan["target_executable"])).resolve(strict=True)
    running = Path(running_executable or sys.executable).resolve(strict=True)
    if staged != running or staged.parent != path.parent:
        raise UpdateInstallError("update plan does not describe this executable")
    if staged.name != EXPECTED_EXECUTABLE_NAME or target.name != EXPECTED_EXECUTABLE_NAME:
        raise UpdateInstallError("update executable name is invalid")
    if staged == target or not target.is_file():
        raise UpdateInstallError("update target is invalid")
    digest = str(plan["sha256"]).casefold()
    if len(digest) != 64 or file_sha256(staged) != digest:
        raise UpdateInstallError("update executable digest mismatch")
    if isinstance(plan["parent_pid"], bool) or not isinstance(plan["parent_pid"], int):
        raise UpdateInstallError("parent process id is invalid")
    plan["_plan_path"] = path
    plan["_staged"] = staged
    plan["_target"] = target
    return plan


def _wait_for_process_exit(pid: int, timeout_seconds: float = 60.0) -> bool:
    if pid <= 0 or pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        synchronize = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            return True
        try:
            wait_ms = max(0, min(int(timeout_seconds * 1000), 0xFFFFFFFE))
            return ctypes.windll.kernel32.WaitForSingleObject(handle, wait_ms) == 0
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.1)
    return False


def _state_payload(plan: dict[str, Any], status: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "app_id": UPDATE_APP_ID,
        "protocol": UPDATE_PROTOCOL_VERSION,
        "version": str(plan["version"]),
        "sha256": str(plan["sha256"]),
        "target_executable": str(plan["_target"]),
        "backup_executable": str(Path(plan["_target"]).with_suffix(".exe.old")),
        "token": str(plan["token"]),
        "status": status,
    }
    payload.update(extra)
    return payload


def apply_update_plan(
    plan_path: str | Path,
    token: str,
    *,
    running_executable: str | Path | None = None,
    launch: bool = True,
    health_timeout_seconds: float = HEALTH_TIMEOUT_SECONDS,
) -> int:
    """Run from the staged new EXE, replace the old EXE, and supervise health."""

    plan = _validated_plan(
        plan_path,
        token,
        running_executable=running_executable,
    )
    if not _wait_for_process_exit(int(plan["parent_pid"])):
        raise UpdateInstallError("old application did not exit")
    staged = Path(plan["_staged"])
    target = Path(plan["_target"])
    pending = target.with_name(f".{target.name}.new")
    backup = target.with_suffix(".exe.old")
    state_path = staged.parent / STATE_NAME
    pending.unlink(missing_ok=True)
    if backup.exists():
        raise UpdateInstallError("an earlier update backup still exists")
    try:
        shutil.copy2(staged, pending)
        with pending.open("rb+") as stream:
            os.fsync(stream.fileno())
        if file_sha256(pending) != str(plan["sha256"]):
            raise UpdateInstallError("copied executable digest mismatch")
        os.replace(target, backup)
        try:
            os.replace(pending, target)
        except BaseException:
            os.replace(backup, target)
            raise
        try:
            atomic_write_json(state_path, _state_payload(plan, "installed"))
            if not launch:
                return 0
            child = subprocess.Popen(
                [str(target), POST_UPDATE_ARGUMENT, str(state_path), str(token)],
                close_fds=True,
            )
        except (OSError, UpdateInstallError):
            target.unlink(missing_ok=True)
            os.replace(backup, target)
            try:
                atomic_write_json(state_path, _state_payload(plan, "rolled_back"))
            except OSError:
                pass
            return 2
        deadline = time.monotonic() + max(1.0, float(health_timeout_seconds))
        healthy = False
        while time.monotonic() < deadline:
            if child.poll() is not None:
                break
            try:
                state = _load_json_object(state_path)
            except (OSError, UpdateInstallError):
                state = {}
            if (
                state.get("status") == "healthy"
                and secrets.compare_digest(str(state.get("token", "")), str(token))
            ):
                healthy = True
                break
            time.sleep(0.2)
        if healthy:
            backup.unlink(missing_ok=True)
            atomic_write_json(state_path, _state_payload(plan, "committed"))
            return 0
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5.0)
        target.unlink(missing_ok=True)
        os.replace(backup, target)
        atomic_write_json(state_path, _state_payload(plan, "rolled_back"))
        subprocess.Popen([str(target)], close_fds=True)
        return 2
    except OSError:
        if backup.is_file():
            target.unlink(missing_ok=True)
            try:
                os.replace(backup, target)
            except OSError:
                pass
        (UPDATE_ROOT / READY_NAME).unlink(missing_ok=True)
        if target.is_file():
            try:
                subprocess.Popen([str(target)], close_fds=True)
            except OSError:
                pass
        return 2
    finally:
        pending.unlink(missing_ok=True)


def confirm_post_update(state_path: str | Path, token: str) -> bool:
    try:
        path = Path(state_path).resolve(strict=True)
        state = _load_json_object(path)
        valid = (
            state.get("schema_version") == 1
            and state.get("app_id") == UPDATE_APP_ID
            and state.get("protocol") == UPDATE_PROTOCOL_VERSION
            and state.get("status") == "installed"
            and secrets.compare_digest(str(state.get("token", "")), str(token))
            and Path(str(state.get("target_executable", ""))).resolve()
            == Path(sys.executable).resolve()
        )
    except (OSError, UpdateInstallError):
        return False
    if not valid:
        return False
    state["status"] = "healthy"
    atomic_write_json(path, state)
    return True


def cleanup_committed_updates(root: str | Path = UPDATE_ROOT) -> None:
    update_root = Path(root)
    if not update_root.is_dir():
        return
    for state_path in update_root.glob(f"*/{STATE_NAME}"):
        try:
            state = _load_json_object(state_path)
            if state.get("status") not in {"committed", "rolled_back"}:
                continue
            shutil.rmtree(state_path.parent)
        except (OSError, UpdateInstallError):
            continue
    ready_path = update_root / READY_NAME
    if ready_path.is_file():
        try:
            ready = _load_json_object(ready_path)
            staged = Path(str(ready.get("staged_executable", "")))
            if not staged.is_file():
                ready_path.unlink(missing_ok=True)
        except (OSError, UpdateInstallError):
            pass


__all__ = [
    "APPLY_UPDATE_ARGUMENT",
    "POST_UPDATE_ARGUMENT",
    "POST_UPDATE_STATE_ENVIRONMENT",
    "POST_UPDATE_TOKEN_ENVIRONMENT",
    "PLAN_NAME",
    "READY_NAME",
    "STATE_NAME",
    "UPDATE_ROOT",
    "UpdateInstallError",
    "apply_update_plan",
    "cleanup_committed_updates",
    "confirm_post_update",
    "create_install_plan",
    "file_sha256",
    "launch_ready_update_on_startup",
    "record_ready_update",
]
