"""Source-path allowlist for deserializing model artifacts.

Pickle/joblib payloads can execute arbitrary reducers on load; restrict
every load path to files that live under a ``models_store`` directory so a
swapped-in artifact elsewhere on disk is never deserialized.
"""
from __future__ import annotations

from pathlib import Path

_ALLOWED_ROOT = "models_store"


def ensure_trusted_artifact_path(path: str | Path) -> Path:
    """Return the resolved artifact path, rejecting sources outside models_store."""
    resolved = Path(path).resolve()
    if _ALLOWED_ROOT not in resolved.parts:
        raise ValueError(
            f"refusing to load model artifact outside {_ALLOWED_ROOT}: {resolved}"
        )
    if not resolved.is_file():
        raise FileNotFoundError(f"model artifact not found: {resolved}")
    return resolved
