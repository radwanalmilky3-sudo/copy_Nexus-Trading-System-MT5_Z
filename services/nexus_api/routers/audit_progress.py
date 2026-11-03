"""Read-only progress and evidence view backed by ``project_audit`` files."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, status

from .admin import require_permission

router = APIRouter(prefix="/api/audit", tags=["audit"])
_audit_view = require_permission("trading.view")

_AUDIT_ROOT = Path(__file__).resolve().parents[3] / "project_audit"
_STATE_FILE = "DASHBOARD_STATE.json"
_MAX_FILES = 512
_MAX_FILE_BYTES = 8 * 1024 * 1024


def _iter_evidence_files(root: Path) -> Iterator[Path]:
    """Yield regular files below root without following symlinks."""
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path)
            except OSError:
                continue


def _sha256(path: Path) -> tuple[str | None, int | None, str | None]:
    try:
        stat = path.stat()
        if stat.st_size > _MAX_FILE_BYTES:
            return None, stat.st_size, "file_too_large"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest(), stat.st_size, None
    except (OSError, ValueError):
        return None, None, "unreadable"


def _read_state(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        if path.is_symlink() or not path.is_file():
            return {}, "unreadable_or_invalid"
        raw = path.read_bytes()
        if len(raw) > _MAX_FILE_BYTES:
            return {}, "file_too_large"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            return {}, "invalid_shape"
        return value, None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, "unreadable_or_invalid"


def _progress_summary(state: dict[str, Any]) -> dict[str, Any]:
    items = state.get("items")
    counts: dict[str, int] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                key = str(item.get("status") or "unknown")
                counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    done = counts.get("done", 0)
    return {
        "total": total,
        "done": done,
        "completion_percent": round(done * 100 / total, 2) if total else 0.0,
        "by_status": counts,
    }


@router.get("/progress", dependencies=[Depends(_audit_view)])
async def audit_progress() -> dict[str, Any]:
    """Return current progress plus immutable hashes for audit evidence."""
    root = _AUDIT_ROOT
    if not root.is_dir() or root.is_symlink():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "audit evidence unavailable")

    state_path = root / _STATE_FILE
    state, state_error = _read_state(state_path)
    files: list[dict[str, Any]] = []
    for path in _iter_evidence_files(root):
        if len(files) >= _MAX_FILES:
            break
        digest, size, error = _sha256(path)
        try:
            relative = path.relative_to(root).as_posix()
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except (OSError, ValueError):
            continue
        files.append(
            {
                "path": relative,
                "sha256": digest,
                "size_bytes": size,
                "modified_at": modified_at,
                **({"error": error} if error else {}),
            }
        )

    state_hash, state_size, hash_error = _sha256(state_path)
    if hash_error and state_error is None:
        state_error = hash_error

    return {
        "status": "available" if not state_error else "degraded",
        "source": "project_audit",
        "state": {
            "file": _STATE_FILE,
            "last_updated": state.get("last_updated"),
            "current_task": state.get("current_task"),
            "progress": _progress_summary(state),
            "sha256": state_hash,
            "size_bytes": state_size,
            **({"error": state_error} if state_error else {}),
        },
        "evidence": {"count": len(files), "files": files},
    }


