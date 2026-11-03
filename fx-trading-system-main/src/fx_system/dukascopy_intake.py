"""Dukascopy SQLite receive ledger and range/sidecar/manifest validators.

Local-only intake. Does not contact VPS. Formal acceptance requires the unified
range, both sidecars, and a batch ``_sqlite_manifest.json``. Partial local files
are recorded; they never silently shrink the research universe.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from .dukascopy_event_data import (
    BASE_URL,
    DATABASE_SCHEMA_VERSION,
    PARSER_VERSION,
    PROVIDER,
    TransferIntegrityError,
    verify_database_transfer,
)

UNIFIED_START = "2016-01-01T00:00:00Z"
UNIFIED_END_EXCLUSIVE = "2026-01-01T00:00:00Z"
BATCH_MANIFEST_NAME = "_sqlite_manifest.json"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

RECEIVE_UNIVERSE: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "EURGBP",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "CADJPY",
    "USDNOK",
    "USDSEK",
)
SLOW_HORIZON_UNIVERSE: tuple[str, ...] = RECEIVE_UNIVERSE[:12]
FIX_W_EXTRA_LEGS: tuple[str, ...] = ("USDNOK", "USDSEK")
FIX_W_UNIVERSE: tuple[str, ...] = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "USDNOK",
    "USDSEK",
)

SymbolStatus = Literal[
    "pending",
    "present_incomplete",
    "legacy_range_mismatch",
    "transfer_failed",
    "formal_ready",
]
LedgerVerdict = Literal["intake_incomplete", "formal_ready"]


@dataclass(frozen=True)
class SymbolIntakeRecord:
    symbol: str
    role: Literal["slow_horizon", "fix_w_extra", "both"]
    status: SymbolStatus
    database_path: str | None
    sidecar_sha256_path: str | None
    sidecar_json_path: str | None
    bytes: int | None
    sha256: str | None
    program_version: str | None
    parser_version: str | None
    requested_start: str | None
    requested_end_exclusive: str | None
    range_matches_unified: bool | None
    has_sidecars: bool
    in_batch_manifest: bool | None
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntakeLedger:
    schema_version: int
    generated_at_utc: str
    database_directory: str
    unified_start: str
    unified_end_exclusive: str
    batch_manifest_path: str | None
    batch_manifest_present: bool
    receive_universe: tuple[str, ...]
    slow_horizon_universe: tuple[str, ...]
    fix_w_universe: tuple[str, ...]
    fix_w_extra_legs: tuple[str, ...]
    symbols: tuple[SymbolIntakeRecord, ...]
    formal_ready_symbols: tuple[str, ...]
    slow_horizon_formal_ready_symbols: tuple[str, ...]
    fix_w_formal_ready_symbols: tuple[str, ...]
    pending_symbols: tuple[str, ...]
    blocked_symbols: tuple[str, ...]
    slow_horizon_ready: bool
    fix_w_ready: bool
    full_intake_ready: bool
    verdict: LedgerVerdict
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["symbols"] = [record.to_dict() for record in self.symbols]
        return payload


class IntakeContractError(ValueError):
    """Intake universe config or ledger contract is invalid."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _role(symbol: str) -> Literal["slow_horizon", "fix_w_extra", "both"]:
    in_slow = symbol in SLOW_HORIZON_UNIVERSE
    in_fix = symbol in FIX_W_EXTRA_LEGS
    if in_slow and in_fix:
        return "both"
    if in_fix:
        return "fix_w_extra"
    return "slow_horizon"


def _normalize_symbol(value: str) -> str:
    return value.upper().replace("/", "").strip()


def _read_sha256_sidecar(path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, "missing .sha256 sidecar"
    try:
        parts = path.read_text(encoding="utf-8").strip().split(maxsplit=1)
    except (OSError, UnicodeError) as error:
        return None, f"unreadable .sha256 sidecar: {error}"
    if len(parts) != 2 or _SHA256_PATTERN.fullmatch(parts[0]) is None:
        return None, "malformed .sha256 sidecar"
    return parts[0], None


def _read_json_sidecar(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "missing .json sidecar"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, f"unreadable .json sidecar: {error}"
    if not isinstance(payload, dict):
        return None, ".json sidecar must be an object"
    return payload, None


def _metadata_range(
    info: dict[str, Any] | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    if info is None:
        return None, None, None, None
    metadata = info.get("metadata")
    program_raw = info.get("program_version")
    program = program_raw if isinstance(program_raw, str) else None
    if not isinstance(metadata, dict):
        return None, None, program, None
    start = metadata.get("requested_start")
    end = metadata.get("requested_end_exclusive")
    parser = metadata.get("parser_version")
    return (
        str(start) if start is not None else None,
        str(end) if end is not None else None,
        program,
        str(parser) if parser is not None else None,
    )


def _sqlite_metadata_range(database_path: Path) -> tuple[str | None, str | None, str | None]:
    """Best-effort read of requested range from SQLite metadata (no full audit)."""
    try:
        uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = {
                str(key): str(value)
                for key, value in connection.execute("SELECT key, value FROM metadata")
            }
    except sqlite3.Error:
        return None, None, None
    return (
        rows.get("requested_start"),
        rows.get("requested_end_exclusive"),
        rows.get("parser_version"),
    )


def load_intake_universe_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load intake config, or return the frozen in-code contract if path is None."""
    if path is None:
        return {
            "schema_version": 1,
            "unified_range": {
                "start": UNIFIED_START,
                "end_exclusive": UNIFIED_END_EXCLUSIVE,
            },
            "receive_universe": list(RECEIVE_UNIVERSE),
            "slow_horizon_universe": list(SLOW_HORIZON_UNIVERSE),
            "fix_w_universe": list(FIX_W_UNIVERSE),
            "fix_w_extra_legs": list(FIX_W_EXTRA_LEGS),
            "parser_version": PARSER_VERSION,
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "provider": PROVIDER,
            "required_batch_manifest": BATCH_MANIFEST_NAME,
        }
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise IntakeContractError(f"{config_path}: intake config must be a mapping")
    validate_intake_universe_config(payload)
    return payload


def validate_intake_universe_config(config: dict[str, Any]) -> None:
    receive = tuple(_normalize_symbol(s) for s in config.get("receive_universe", []))
    if receive != RECEIVE_UNIVERSE:
        raise IntakeContractError(
            "receive_universe must exactly match the frozen 14-symbol order"
        )
    slow = tuple(_normalize_symbol(s) for s in config.get("slow_horizon_universe", []))
    if slow != SLOW_HORIZON_UNIVERSE:
        raise IntakeContractError("slow_horizon_universe must be the first 12 receive symbols")
    fix_w = tuple(_normalize_symbol(s) for s in config.get("fix_w_universe", []))
    if fix_w != FIX_W_UNIVERSE:
        raise IntakeContractError("fix_w_universe must exactly match the frozen nine G9 legs")
    extra = tuple(_normalize_symbol(s) for s in config.get("fix_w_extra_legs", []))
    if extra != FIX_W_EXTRA_LEGS:
        raise IntakeContractError("fix_w_extra_legs must be (USDNOK, USDSEK)")
    unified = config.get("unified_range") or {}
    start_ok = unified.get("start") == UNIFIED_START
    end_ok = unified.get("end_exclusive") == UNIFIED_END_EXCLUSIVE
    if not start_ok or not end_ok:
        raise IntakeContractError(
            f"unified_range must be [{UNIFIED_START}, {UNIFIED_END_EXCLUSIVE})"
        )


def validate_range_contract(
    *,
    requested_start: str | None,
    requested_end_exclusive: str | None,
    expected_start: str = UNIFIED_START,
    expected_end_exclusive: str = UNIFIED_END_EXCLUSIVE,
) -> list[str]:
    issues: list[str] = []
    if requested_start != expected_start:
        issues.append(
            f"requested_start={requested_start!r} != unified {expected_start!r}"
        )
    if requested_end_exclusive != expected_end_exclusive:
        issues.append(
            "requested_end_exclusive="
            f"{requested_end_exclusive!r} != unified {expected_end_exclusive!r}"
        )
    return issues


def validate_sidecar_pair(database_path: Path) -> list[str]:
    issues: list[str] = []
    hash_path = Path(f"{database_path}.sha256")
    info_path = Path(f"{database_path}.json")
    digest, hash_issue = _read_sha256_sidecar(hash_path)
    if hash_issue:
        issues.append(hash_issue)
    info, info_issue = _read_json_sidecar(info_path)
    if info_issue:
        issues.append(info_issue)
        return issues
    assert info is not None
    expected_name = database_path.name
    if info.get("file") != expected_name:
        issues.append(f"json sidecar file={info.get('file')!r} != {expected_name!r}")
    if digest is not None and info.get("sha256") != digest:
        issues.append("json sidecar sha256 disagrees with .sha256 sidecar")
    if info.get("integrity") != "ok":
        issues.append(f"json sidecar integrity={info.get('integrity')!r}")
    if info.get("schema_version") != 1:
        issues.append("json sidecar schema_version must be 1")
    metadata = info.get("metadata")
    if not isinstance(metadata, dict):
        issues.append("json sidecar metadata missing")
        return issues
    required_meta = {
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "provider": PROVIDER,
        "base_url": BASE_URL,
    }
    for key, expected in required_meta.items():
        if str(metadata.get(key)) != expected:
            issues.append(f"json sidecar metadata {key}={metadata.get(key)!r}")
    return issues


def load_batch_manifest_symbols(manifest_path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not manifest_path.is_file():
        return None, [f"missing batch manifest: {manifest_path.name}"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, [f"unreadable batch manifest: {error}"]
    if not isinstance(payload, dict):
        return None, ["batch manifest must be an object"]
    if payload.get("schema_version") != 1:
        return None, ["batch manifest schema_version must be 1"]
    databases = payload.get("databases")
    if not isinstance(databases, dict):
        return None, ["batch manifest databases must be an object"]
    return payload, []


def inspect_symbol_intake(
    database_directory: Path,
    symbol: str,
    *,
    batch_manifest: dict[str, Any] | None,
    unified_start: str = UNIFIED_START,
    unified_end_exclusive: str = UNIFIED_END_EXCLUSIVE,
) -> SymbolIntakeRecord:
    symbol = _normalize_symbol(symbol)
    db_path = database_directory / f"{symbol}.sqlite"
    hash_path = Path(f"{db_path}.sha256")
    info_path = Path(f"{db_path}.json")
    issues: list[str] = []

    if not db_path.is_file():
        return SymbolIntakeRecord(
            symbol=symbol,
            role=_role(symbol),
            status="pending",
            database_path=None,
            sidecar_sha256_path=None,
            sidecar_json_path=None,
            bytes=None,
            sha256=None,
            program_version=None,
            parser_version=None,
            requested_start=None,
            requested_end_exclusive=None,
            range_matches_unified=None,
            has_sidecars=False,
            in_batch_manifest=(
                None
                if batch_manifest is None
                else symbol in (batch_manifest.get("databases") or {})
            ),
            issues=("database absent",),
        )

    has_hash = hash_path.is_file()
    has_info = info_path.is_file()
    has_sidecars = has_hash and has_info
    if not has_sidecars:
        issues.append("sidecars incomplete")
    issues.extend(validate_sidecar_pair(db_path) if has_sidecars else [])

    info, _ = _read_json_sidecar(info_path) if has_info else (None, None)
    start, end, program, parser = _metadata_range(info)
    if start is None or end is None or parser is None:
        db_start, db_end, db_parser = _sqlite_metadata_range(db_path)
        start = start or db_start
        end = end or db_end
        parser = parser or db_parser

    range_issues = validate_range_contract(
        requested_start=start,
        requested_end_exclusive=end,
        expected_start=unified_start,
        expected_end_exclusive=unified_end_exclusive,
    )
    issues.extend(range_issues)
    range_ok = not range_issues and start is not None and end is not None

    digest, _ = _read_sha256_sidecar(hash_path) if has_hash else (None, None)
    size = db_path.stat().st_size
    in_manifest: bool | None
    if batch_manifest is None:
        in_manifest = None
        issues.append("batch manifest absent")
    else:
        databases = batch_manifest.get("databases") or {}
        in_manifest = symbol in databases
        if not in_manifest:
            issues.append("symbol missing from batch manifest")

    # Status priority: range mismatch > transfer fail > incomplete > formal_ready.
    status: SymbolStatus
    if range_issues:
        status = "legacy_range_mismatch"
    elif has_sidecars and batch_manifest is not None and range_ok and in_manifest:
        manifest_path = database_directory / BATCH_MANIFEST_NAME
        try:
            receipt = verify_database_transfer(db_path, manifest_path, symbol=symbol)
            digest = receipt.sha256
            size = receipt.bytes
        except (TransferIntegrityError, FileNotFoundError, OSError) as error:
            issues.append(f"transfer verification failed: {error}")
            status = "transfer_failed"
        else:
            status = "formal_ready" if not issues else "present_incomplete"
    else:
        status = "present_incomplete"

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_issues: list[str] = []
    for item in issues:
        if item not in seen:
            seen.add(item)
            unique_issues.append(item)

    return SymbolIntakeRecord(
        symbol=symbol,
        role=_role(symbol),
        status=status,
        database_path=str(db_path.resolve()),
        sidecar_sha256_path=str(hash_path.resolve()) if has_hash else None,
        sidecar_json_path=str(info_path.resolve()) if has_info else None,
        bytes=size,
        sha256=digest,
        program_version=program,
        parser_version=parser,
        requested_start=start,
        requested_end_exclusive=end,
        range_matches_unified=range_ok,
        has_sidecars=has_sidecars,
        in_batch_manifest=in_manifest,
        issues=tuple(unique_issues),
    )


def build_intake_ledger(
    database_directory: str | Path,
    *,
    config_path: str | Path | None = None,
) -> IntakeLedger:
    directory = Path(database_directory)
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    config = load_intake_universe_config(config_path)
    validate_intake_universe_config(config)
    unified = config["unified_range"]
    manifest_path = directory / BATCH_MANIFEST_NAME
    batch_manifest, manifest_issues = load_batch_manifest_symbols(manifest_path)

    records = tuple(
        inspect_symbol_intake(
            directory,
            symbol,
            batch_manifest=batch_manifest,
            unified_start=str(unified["start"]),
            unified_end_exclusive=str(unified["end_exclusive"]),
        )
        for symbol in RECEIVE_UNIVERSE
    )
    formal = tuple(r.symbol for r in records if r.status == "formal_ready")
    formal_set = set(formal)
    slow_formal = tuple(symbol for symbol in SLOW_HORIZON_UNIVERSE if symbol in formal_set)
    fix_w_formal = tuple(symbol for symbol in FIX_W_UNIVERSE if symbol in formal_set)
    pending = tuple(r.symbol for r in records if r.status == "pending")
    blocked = tuple(r.symbol for r in records if r.status not in {"formal_ready", "pending"})
    issues = list(manifest_issues)
    if formal != RECEIVE_UNIVERSE:
        issues.append(
            f"formal_ready {len(formal)}/14; universe not complete"
        )
    verdict: LedgerVerdict = (
        "formal_ready" if formal == RECEIVE_UNIVERSE and not issues else "intake_incomplete"
    )
    return IntakeLedger(
        schema_version=1,
        generated_at_utc=_utc_now(),
        database_directory=str(directory.resolve()),
        unified_start=str(unified["start"]),
        unified_end_exclusive=str(unified["end_exclusive"]),
        batch_manifest_path=str(manifest_path.resolve()) if manifest_path.is_file() else None,
        batch_manifest_present=manifest_path.is_file(),
        receive_universe=RECEIVE_UNIVERSE,
        slow_horizon_universe=SLOW_HORIZON_UNIVERSE,
        fix_w_universe=FIX_W_UNIVERSE,
        fix_w_extra_legs=FIX_W_EXTRA_LEGS,
        symbols=records,
        formal_ready_symbols=formal,
        slow_horizon_formal_ready_symbols=slow_formal,
        fix_w_formal_ready_symbols=fix_w_formal,
        pending_symbols=pending,
        blocked_symbols=blocked,
        slow_horizon_ready=slow_formal == SLOW_HORIZON_UNIVERSE,
        fix_w_ready=fix_w_formal == FIX_W_UNIVERSE,
        full_intake_ready=formal == RECEIVE_UNIVERSE,
        verdict=verdict,
        issues=tuple(issues),
    )


def write_intake_ledger(ledger: IntakeLedger, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path.resolve()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
