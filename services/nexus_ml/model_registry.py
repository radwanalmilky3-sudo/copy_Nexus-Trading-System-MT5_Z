"""Filesystem registry for immutable per-symbol ML model generations."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ModelRegistry:
    """Store candidate bundles and switch the active generation atomically."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @staticmethod
    def _component(value: str, label: str) -> str:
        if not isinstance(value, str) or not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError(f"invalid {label}")
        return value

    def symbol_dir(self, symbol: str, timeframe: str) -> Path:
        symbol_key = self._component(symbol.strip().upper(), "symbol")
        timeframe_key = self._component(timeframe.strip().upper(), "timeframe")
        return self.root / symbol_key / "timeframes" / timeframe_key

    def generation_dir(self, symbol: str, timeframe: str, generation_id: str) -> Path:
        generation = self._component(generation_id, "generation id")
        return self.symbol_dir(symbol, timeframe) / "versions" / generation

    def active_manifest_path(self, symbol: str, timeframe: str) -> Path:
        return self.symbol_dir(symbol, timeframe) / "active.json"

    def create_staging(self, symbol: str, timeframe: str, generation_id: str) -> Path:
        path = self.generation_dir(symbol, timeframe, generation_id)
        path.mkdir(parents=True, exist_ok=False)
        return path

    def write_generation_manifest(
        self,
        symbol: str,
        timeframe: str,
        generation_id: str,
        artifacts: Iterable[str],
        feature_names: Iterable[str],
        trained_at: str = "",
        data_window: str = "",
    ) -> dict[str, Any]:
        directory = self.generation_dir(symbol, timeframe, generation_id)
        if not directory.is_dir():
            raise ValueError("generation directory does not exist")
        names = list(artifacts)
        features = list(feature_names)
        if not names or any(not isinstance(name, str) or Path(name).name != name for name in names):
            raise ValueError("artifact names must be non-empty safe filenames")
        for name in names:
            artifact = directory / name
            if not artifact.is_file() or artifact.stat().st_size == 0:
                raise ValueError(f"artifact missing or empty: {name}")
        if not features or any(not isinstance(item, str) or not item for item in features):
            raise ValueError("feature schema must contain non-empty names")
        manifest = {
            "symbol": symbol.strip().upper(),
            "timeframe": timeframe.strip().upper(),
            "generation_id": generation_id,
            "artifacts": sorted(set(names)),
            "feature_names": features,
            "trained_at": trained_at,
            "data_window": data_window,
        }
        self._atomic_json(directory / "bundle.json", manifest)
        return manifest

    def read_generation_manifest(self, symbol: str, timeframe: str, generation_id: str) -> dict[str, Any]:
        path = self.generation_dir(symbol, timeframe, generation_id) / "bundle.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("symbol") != symbol.strip().upper()
            or payload.get("timeframe") != timeframe.strip().upper()
            or payload.get("generation_id") != generation_id
        ):
            raise ValueError("generation manifest identity mismatch")
        artifacts = payload.get("artifacts")
        features = payload.get("feature_names")
        if not isinstance(artifacts, list) or not artifacts or not isinstance(features, list) or not features:
            raise ValueError("generation manifest is incomplete")
        for name in artifacts:
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("unsafe artifact path in manifest")
            artifact = path.parent / name
            if not artifact.is_file() or artifact.stat().st_size == 0:
                raise ValueError(f"artifact missing or empty: {name}")
        return payload

    def read_active(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        path = self.active_manifest_path(symbol, timeframe)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        active = payload.get("active_generation")
        if not isinstance(active, str):
            raise ValueError("active manifest is malformed")
        self._component(active, "generation id")
        return payload

    def activate(self, symbol: str, timeframe: str, generation_id: str) -> dict[str, Any]:
        self.read_generation_manifest(symbol, timeframe, generation_id)
        previous = self.read_active(symbol, timeframe)
        payload: dict[str, Any] = {"active_generation": generation_id}
        payload["symbol"] = symbol.strip().upper()
        payload["timeframe"] = timeframe.strip().upper()
        if previous:
            payload["previous_generation"] = previous["active_generation"]
            if previous.get("previous_generation"):
                payload["fallback_generation"] = previous["previous_generation"]
        self._atomic_json(self.active_manifest_path(symbol, timeframe), payload)
        return payload

    def resolve_startup_generation(self, symbol: str, timeframe: str) -> list[str]:
        """Return only generations explicitly proven to match symbol and timeframe."""
        active = self.read_active(symbol, timeframe)
        if not active:
            return []
        if active.get("symbol") != symbol.strip().upper() or active.get("timeframe") != timeframe.strip().upper():
            raise ValueError("active manifest has no matching symbol/timeframe provenance")
        candidates = [
            active.get("active_generation"),
            active.get("previous_generation"),
            active.get("fallback_generation"),
        ]
        resolved: list[str] = []
        for generation in candidates:
            if not generation or generation in resolved:
                continue
            try:
                self.read_generation_manifest(symbol, timeframe, generation)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            resolved.append(generation)
        return resolved

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, sort_keys=True))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
