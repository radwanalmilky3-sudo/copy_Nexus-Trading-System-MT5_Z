"""Intake ledger and unified range/sidecar/manifest validators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from fx_system.dukascopy_event_data import PARSER_VERSION
from fx_system.dukascopy_intake import (
    FIX_W_EXTRA_LEGS,
    FIX_W_UNIVERSE,
    RECEIVE_UNIVERSE,
    SLOW_HORIZON_UNIVERSE,
    UNIFIED_END_EXCLUSIVE,
    UNIFIED_START,
    IntakeContractError,
    build_intake_ledger,
    load_intake_universe_config,
    validate_intake_universe_config,
    validate_range_contract,
    write_intake_ledger,
)
from fx_system.intraday_research import FIX_W_G9_LEGS


def test_frozen_universe_splits_slow_and_fix_w() -> None:
    assert len(RECEIVE_UNIVERSE) == 14
    assert SLOW_HORIZON_UNIVERSE == RECEIVE_UNIVERSE[:12]
    assert FIX_W_EXTRA_LEGS == ("USDNOK", "USDSEK")
    assert len(FIX_W_UNIVERSE) == 9
    assert set(FIX_W_EXTRA_LEGS).issubset(FIX_W_UNIVERSE)
    assert set(FIX_W_UNIVERSE).issubset(RECEIVE_UNIVERSE)
    assert {market_symbol for market_symbol, _ in FIX_W_G9_LEGS.values()} == set(
        FIX_W_UNIVERSE
    )
    assert "USDNOK" not in SLOW_HORIZON_UNIVERSE
    assert "USDSEK" not in SLOW_HORIZON_UNIVERSE


def test_unified_range_contract_rejects_legacy_end() -> None:
    issues = validate_range_contract(
        requested_start=UNIFIED_START,
        requested_end_exclusive="2025-09-15T00:00:00Z",
    )
    assert any("2025-09-15" in item for item in issues)
    assert not validate_range_contract(
        requested_start=UNIFIED_START,
        requested_end_exclusive=UNIFIED_END_EXCLUSIVE,
    )


def test_config_file_matches_frozen_contract() -> None:
    config = load_intake_universe_config("configs/dukascopy_intake_universe.yaml")
    validate_intake_universe_config(config)
    assert config["unified_range"]["end_exclusive"] == UNIFIED_END_EXCLUSIVE


def test_config_rejects_reordered_universe(tmp_path: Path) -> None:
    bad = {
        "schema_version": 1,
        "unified_range": {
            "start": UNIFIED_START,
            "end_exclusive": UNIFIED_END_EXCLUSIVE,
        },
        "receive_universe": list(reversed(RECEIVE_UNIVERSE)),
        "slow_horizon_universe": list(SLOW_HORIZON_UNIVERSE),
        "fix_w_universe": list(FIX_W_UNIVERSE),
        "fix_w_extra_legs": list(FIX_W_EXTRA_LEGS),
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(IntakeContractError, match="receive_universe"):
        load_intake_universe_config(path)


def _write_legacy_gbpusd_sidecars(directory: Path) -> None:
    db = directory / "GBPUSD.sqlite"
    db.write_bytes(b"not-a-real-db-but-present")
    digest = "a" * 64
    (directory / "GBPUSD.sqlite.sha256").write_text(f"{digest}  GBPUSD.sqlite\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "program_version": "1.0.0",
        "symbol": "GBPUSD",
        "file": "GBPUSD.sqlite",
        "bytes": db.stat().st_size,
        "sha256": digest,
        "integrity": "ok",
        "metadata": {
            "database_schema_version": "1",
            "parser_version": PARSER_VERSION,
            "provider": "dukascopy",
            "base_url": "https://datafeed.dukascopy.com/datafeed",
            "symbol": "GBPUSD",
            "price_divisor": "100000",
            "requested_start": "2016-01-01T00:00:00Z",
            "requested_end_exclusive": "2025-09-15T00:00:00Z",
        },
    }
    (directory / "GBPUSD.sqlite.json").write_text(json.dumps(payload), encoding="utf-8")


def test_ledger_marks_missing_symbols_pending_and_legacy_gbpusd(tmp_path: Path) -> None:
    _write_legacy_gbpusd_sidecars(tmp_path)
    ledger = build_intake_ledger(tmp_path)
    assert ledger.verdict == "intake_incomplete"
    assert ledger.slow_horizon_ready is False
    assert ledger.fix_w_ready is False
    assert ledger.full_intake_ready is False
    assert ledger.slow_horizon_formal_ready_symbols == ()
    assert ledger.fix_w_formal_ready_symbols == ()
    assert len(ledger.pending_symbols) == 13
    by_symbol = {record.symbol: record for record in ledger.symbols}
    gbpusd = by_symbol["GBPUSD"]
    assert gbpusd.status == "legacy_range_mismatch"
    assert gbpusd.range_matches_unified is False
    assert gbpusd.has_sidecars is True
    assert by_symbol["EURUSD"].status == "pending"
    assert by_symbol["USDNOK"].role == "fix_w_extra"
    assert by_symbol["EURUSD"].role == "slow_horizon"
    out = write_intake_ledger(ledger, tmp_path / "ledger.json")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["verdict"] == "intake_incomplete"
    assert loaded["formal_ready_symbols"] == []
    assert loaded["slow_horizon_ready"] is False
    assert loaded["fix_w_ready"] is False
    assert loaded["full_intake_ready"] is False
