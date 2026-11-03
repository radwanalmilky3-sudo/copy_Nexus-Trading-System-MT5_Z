from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from fx_system.config import DataConfig
from fx_system.data import DUKASCOPY_PRICE_DIVISORS
from fx_system.dukascopy_daily import ny_close_session_start_dates
from fx_system.dukascopy_event_data import BASE_URL, PARSER_VERSION
from fx_system.intraday_calendar import fx_session_bounds
from fx_system.long_horizon_config import (
    LongHorizonConfig,
    LongHorizonExternalConfig,
    LongHorizonSettings,
)
from fx_system.long_horizon_runner import (
    FormalPortfolioNotReadyError,
    LongHorizonCandidateDeclaration,
    LongHorizonFactorOnlyBuildResult,
    _validate_registry_contract,
    assert_formal_portfolio_ready,
    build_frozen_candidate_schedule,
    run_long_horizon_candidate_freeze_from_sqlite,
    verify_long_horizon_candidate_freeze_artifacts,
    write_long_horizon_candidate_freeze_artifacts,
)

ROOT = Path(__file__).parents[1]
REGISTRY = ROOT / "configs/factor_research_registry.yaml"
CANDIDATES = ROOT / "configs/long_horizon_dukascopy_candidates.yaml"

DATABASE_SQL = """
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE hours (
    hour_utc INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    payload BLOB,
    payload_sha256 TEXT,
    compressed_bytes INTEGER NOT NULL,
    tick_count INTEGER NOT NULL,
    first_offset_ms INTEGER,
    last_offset_ms INTEGER,
    http_status INTEGER,
    retrieved_at TEXT NOT NULL,
    source_url TEXT NOT NULL
);
CREATE INDEX idx_hours_status ON hours(status);
"""
TICK_RECORD = struct.Struct(">iiiff")
SYMBOLS = (
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
)


def _expected_hours(session_date: date) -> list[pd.Timestamp]:
    bounds = fx_session_bounds(session_date)
    return list(
        pd.date_range(
            pd.Timestamp(bounds.start_utc).floor("h"),
            pd.Timestamp(bounds.end_utc).ceil("h"),
            freq="1h",
            inclusive="left",
        )
    )


def _write_synthetic_sqlite(
    root: Path,
    symbols: tuple[str, ...],
    session_dates: tuple[date, ...],
) -> Path:
    root.mkdir()
    manifest_entries: dict[str, object] = {}
    for symbol_number, symbol in enumerate(symbols):
        divisor = DUKASCOPY_PRICE_DIVISORS[symbol]
        path = root / f"{symbol}.sqlite"
        metadata = {
            "database_schema_version": "1",
            "parser_version": PARSER_VERSION,
            "provider": "dukascopy",
            "base_url": BASE_URL,
            "symbol": symbol,
            "price_divisor": str(divisor),
        }
        hours = sorted({hour for value in session_dates for hour in _expected_hours(value)})
        with sqlite3.connect(path) as connection:
            connection.executescript(DATABASE_SQL)
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            for sequence, hour in enumerate(hours):
                base_price = (
                    (1.0 + symbol_number * 0.02 + sequence * 0.00001)
                    if "JPY" not in symbol
                    else (100.0 + symbol_number + sequence * 0.001)
                )
                base = int(base_price * divisor)
                records = (
                    (1_000, base + 2, base, 2.0, 3.0),
                    (3_599_000, base + 4, base + 1, 5.0, 7.0),
                )
                raw = b"".join(TICK_RECORD.pack(*record) for record in records)
                payload = lzma.compress(raw, format=lzma.FORMAT_ALONE)
                connection.execute(
                    "INSERT INTO hours VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, 200, ?, ?)",
                    (
                        int(hour.timestamp()),
                        payload,
                        hashlib.sha256(payload).hexdigest(),
                        len(payload),
                        len(records),
                        records[0][0],
                        records[-1][0],
                        "2026-01-01T00:00:00+00:00",
                        "https://example.test/hour.bi5",
                    ),
                )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "integrity": "ok",
            "metadata": metadata,
            "counts": {"ok": len(hours), "no_data": 0},
            "first_hour": hours[0].isoformat(),
            "last_hour": hours[-1].isoformat(),
        }
        Path(f"{path}.sha256").write_text(f"{digest}  {path.name}\n", encoding="utf-8")
        Path(f"{path}.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "program_version": "1.1.0",
                    "symbol": symbol,
                    **entry,
                }
            ),
            encoding="utf-8",
        )
        manifest_entries[symbol] = entry
    manifest = root / "_sqlite_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "program_version": "1.1.0",
                "created_at": "2026-01-02T00:00:00+00:00",
                "parser_version": PARSER_VERSION,
                "databases": manifest_entries,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _config(symbols: tuple[str, ...]) -> LongHorizonConfig:
    return LongHorizonConfig(
        data=DataConfig(
            provider="dukascopy",
            symbols=list(symbols),
            interval="1d",
            price_mode="bid_ask",
            start="2025-01-05",
            end="2025-01-08",
        ),
        external=LongHorizonExternalConfig(enabled=False),
        research=LongHorizonSettings(),
    )


def test_sqlite_freeze_is_factor_only_hash_verified_and_fail_closed(tmp_path: Path) -> None:
    session_dates = ny_close_session_start_dates("2025-01-05", "2025-01-08")
    database_directory = tmp_path / "sqlite"
    manifest = _write_synthetic_sqlite(database_directory, SYMBOLS, session_dates)
    declaration = LongHorizonCandidateDeclaration.from_yaml(CANDIDATES)

    result = run_long_horizon_candidate_freeze_from_sqlite(
        database_directory=database_directory,
        config=_config(SYMBOLS),
        declaration=declaration,
        start="2025-01-05",
        end="2025-01-08",
        registry_path=REGISTRY,
        transfer_manifest_path=manifest,
    )

    assert len(result.daily_run.transfer_audit) == len(SYMBOLS)
    assert result.daily_run.transfer_audit["transfer_verified"].all()
    assert result.build.audit["factor_only"] is True
    assert result.build.audit["future_labels_generated"] is False
    assert not any(
        str(column).startswith(("_forward_", "_label_"))
        for column in result.build.panel
    )
    assert set(result.candidate_schedule["horizon_sessions"]) == {21, 42, 63}
    assert set(result.candidate_schedule["status"]) == {
        "flat_insufficient_common_sessions_for_horizon"
    }
    assert result.manifest["research_registry"]["candidate_contract_matched"] is True
    assert result.manifest["historical_financing_treatment"] == "missing_not_zero_filled"
    assert result.manifest["portfolio_execution_attempted"] is False
    assert result.manifest["portfolio_validation_attempted"] is False
    assert result.manifest["portfolio_target_weights_emitted"] is False
    assert "single-candidate, single-vintage" in result.manifest["schedule_semantics"]
    assert (
        "overlapping_sleeve_capital_conservation_not_integrated"
        in result.manifest["formal_portfolio_blockers"]
    )
    assert result.manifest["trading_approval"] is False
    with pytest.raises(FormalPortfolioNotReadyError, match="next_open_execution"):
        assert_formal_portfolio_ready(result)

    stale_output = tmp_path / "stale_freeze"
    stale_output.mkdir()
    (stale_output / "daily_net_returns.csv").write_text("forbidden\n", encoding="utf-8")
    with pytest.raises(ValueError, match="absent or empty"):
        write_long_horizon_candidate_freeze_artifacts(result, stale_output)

    output = write_long_horizon_candidate_freeze_artifacts(result, tmp_path / "freeze")
    written = verify_long_horizon_candidate_freeze_artifacts(output)
    assert written["future_labels_generated"] is False
    assert "factor_only_build/factor_panel.csv.gz" in written["artifacts"]
    assert not (output / "long_horizon_build/research_dataset.csv.gz").exists()
    assert not (output / "daily_net_returns.csv").exists()

    forbidden = output / "dsr_results.json"
    forbidden.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared, or forbidden"):
        verify_long_horizon_candidate_freeze_artifacts(output)
    forbidden.unlink()

    target_path = output / "frozen_candidate_signal_schedule.csv"
    target_path.write_text(target_path.read_text(encoding="utf-8") + "tamper\n")
    with pytest.raises(ValueError, match="byte count changed"):
        verify_long_horizon_candidate_freeze_artifacts(output)


def test_target_schedule_uses_declared_direction_and_next_open_without_outcomes() -> None:
    symbols = ("EURUSD", "GBPUSD", "USDJPY")
    config = _config(symbols)
    times = pd.bdate_range("2024-01-02 22:00:00", periods=100, tz="UTC")
    panel_rows = []
    daily = {}
    for symbol_number, symbol in enumerate(symbols):
        panel_rows.extend(
            {
                "_feature_time": timestamp,
                "_symbol": symbol,
                "momentum_21d": float(symbol_number + 1),
            }
            for timestamp in times
        )
        daily[symbol] = pd.DataFrame(
            {
                "session_open_quote_time": times - pd.to_timedelta(23, unit="h"),
                "session_close_quote_time": times - pd.to_timedelta(1, unit="s"),
            },
            index=times,
        )
    build = LongHorizonFactorOnlyBuildResult(
        daily_data=daily,
        panel=pd.DataFrame(panel_rows),
        catalog=pd.DataFrame(
            [
                {
                    "name": "momentum_21d",
                    "family": "momentum",
                    "directional": True,
                    "strict_eligibility": "price_history_required",
                    "description": "test factor",
                }
            ]
        ),
        audit={"factor_only": True},
        external_files=[],
    )
    declaration = LongHorizonCandidateDeclaration.model_validate(
        {
            "schema_version": 1,
            "declaration_id": "outcome_blind_unit_test",
            "frozen_at": "2023-12-31T00:00:00+00:00",
            "registration_market_data_cutoff": "2026-07-13",
            "candidate_set_is_complete": True,
            "candidate_universe_scope": (
                "implemented_active_directional_slow_hypotheses_"
                "excluding_deferred_missing_data"
            ),
            "directions_selected_from_dukascopy_outcomes": False,
            "fresh_forward_required": True,
            "inference_eligibility": "exploratory_reused_history_requires_new_forward",
            "selected_candidate_for_future_dsr_diagnostic": "momentum__21d",
            "total_trials_evaluated": 3,
            "candidates": [
                {
                    "name": f"momentum__{horizon}d",
                    "hypothesis_id": "synthetic_momentum",
                    "factor": "momentum_21d",
                    "expected_sign": "positive",
                    "horizon_sessions": horizon,
                    "eligible_symbols": list(symbols),
                }
                for horizon in (21, 42, 63)
            ],
        }
    )

    schedule, audit = build_frozen_candidate_schedule(build, declaration, config)
    ready = schedule.loc[schedule["status"] == "ready_next_open"]
    assert not ready.empty
    assert (ready["entry_quote_time"] > ready["decision_time"]).all()
    assert (ready["exit_quote_time"] > ready["entry_quote_time"]).all()
    first = ready.loc[
        (ready["candidate"] == "momentum__21d")
        & (ready["decision_time"] == times[0])
    ].set_index("symbol")
    assert first.loc["EURUSD", "proposed_tranche_weight"] == pytest.approx(-0.5)
    assert first.loc["GBPUSD", "proposed_tranche_weight"] == pytest.approx(0.0)
    assert first.loc["USDJPY", "proposed_tranche_weight"] == pytest.approx(0.5)
    gross = ready.groupby(["candidate", "decision_time"])[
        "proposed_tranche_weight"
    ].apply(lambda values: values.abs().sum())
    assert np.allclose(gross.to_numpy(dtype=float), 1.0)
    assert audit["all_missing_legs_flatten_complete_vector"].all()
    assert not any(
        str(column).startswith(("_forward_", "_label_")) for column in schedule
    )


def test_registry_contract_rejects_understated_trials_and_sign_drift() -> None:
    declaration = LongHorizonCandidateDeclaration.from_yaml(CANDIDATES)
    understated = declaration.model_copy(update={"total_trials_evaluated": 3311})
    with pytest.raises(ValueError, match="understates disclosed"):
        _validate_registry_contract(understated, REGISTRY)

    candidates = list(declaration.candidates)
    candidates[0] = candidates[0].model_copy(update={"expected_sign": "negative"})
    sign_drift = declaration.model_copy(update={"candidates": candidates})
    with pytest.raises(ValueError, match="expected_sign differs"):
        _validate_registry_contract(sign_drift, REGISTRY)

    candidates = list(declaration.candidates)
    candidates[0] = candidates[0].model_copy(update={"factor": "momentum_21d"})
    factor_drift = declaration.model_copy(update={"candidates": candidates})
    with pytest.raises(ValueError, match="factor differs from frozen"):
        _validate_registry_contract(factor_drift, REGISTRY)

    candidates = list(declaration.candidates)
    candidates[0] = candidates[0].model_copy(update={"name": "renamed_candidate"})
    name_drift = declaration.model_copy(update={"candidates": candidates})
    with pytest.raises(ValueError, match="candidate name must equal"):
        _validate_registry_contract(name_drift, REGISTRY)
