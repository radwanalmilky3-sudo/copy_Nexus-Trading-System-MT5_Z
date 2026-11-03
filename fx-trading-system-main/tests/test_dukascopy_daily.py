from __future__ import annotations

import hashlib
import json
import lzma
import sqlite3
import struct
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pandas.testing as pdt
import pytest

from fx_system.data import DUKASCOPY_PRICE_DIVISORS, QUOTE_COLUMNS
from fx_system.dukascopy_daily import (
    build_common_daily_data,
    build_portfolio_close_inputs,
    ny_close_session_start_dates,
    run_dukascopy_daily_from_sqlite,
)
from fx_system.dukascopy_daily_cache import (
    DukascopyDailyCacheError,
    load_dukascopy_daily_cache,
    write_dukascopy_daily_cache,
)
from fx_system.dukascopy_event_data import (
    BASE_URL,
    PARSER_VERSION,
    TransferIntegrityError,
    verify_database_transfer,
)
from fx_system.intraday_calendar import fx_session_bounds
from fx_system.long_horizon import build_long_horizon_labels, to_daily_market_data
from fx_system.long_horizon_config import LongHorizonSettings

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


def _expected_hours(session_date: date) -> list[pd.Timestamp]:
    bounds = fx_session_bounds(session_date)
    start = pd.Timestamp(bounds.start_utc)
    end = pd.Timestamp(bounds.end_utc)
    return list(pd.date_range(start.floor("h"), end.ceil("h"), freq="1h", inclusive="left"))


def _write_databases(
    root: Path,
    symbols: tuple[str, ...],
    session_dates: tuple[date, ...],
    *,
    omit: tuple[str, pd.Timestamp] | None = None,
    no_data: set[tuple[str, pd.Timestamp]] | None = None,
    stale_open: set[tuple[str, pd.Timestamp]] | None = None,
    stale_close: set[tuple[str, pd.Timestamp]] | None = None,
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
        ok_count = 0
        no_data_count = 0
        with sqlite3.connect(path) as connection:
            connection.executescript(DATABASE_SQL)
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
            for sequence, hour in enumerate(hours):
                if omit is not None and (symbol, hour) == omit:
                    continue
                common = (
                    int(hour.timestamp()),
                    "2026-01-01T00:00:00+00:00",
                    "https://example.test/hour.bi5",
                )
                if no_data is not None and (symbol, hour) in no_data:
                    connection.execute(
                        "INSERT INTO hours VALUES (?, 'no_data', NULL, NULL, 0, 0, "
                        "NULL, NULL, 404, ?, ?)",
                        common,
                    )
                    no_data_count += 1
                    continue
                base = int((1.10 + symbol_number * 0.10 + sequence * 0.0001) * divisor)
                last_offset_ms = (
                    3_590_000
                    if stale_close is not None and (symbol, hour) in stale_close
                    else 3_599_000
                )
                first_offset_ms = (
                    10_000
                    if stale_open is not None and (symbol, hour) in stale_open
                    else 1_000
                )
                records = [
                    (first_offset_ms, base + 2, base, 2.0, 3.0),
                    (last_offset_ms, base + 4, base + 1, 5.0, 7.0),
                ]
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
                        common[1],
                        common[2],
                    ),
                )
                ok_count += 1

        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "integrity": "ok",
            "metadata": metadata,
            "counts": {"ok": ok_count, "no_data": no_data_count},
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
    manifest_path = root / "_sqlite_manifest.json"
    manifest_path.write_text(
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
    return manifest_path


def test_daily_sqlite_runner_builds_new_york_close_bid_ask_bars_and_adapters(
    tmp_path: Path,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5), date(2025, 1, 6))
    root = tmp_path / "sqlite"
    manifest = _write_databases(root, symbols, session_dates)

    result = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 7),
        transfer_manifest_path=manifest,
    )

    assert result.requested_session_start_dates == session_dates
    assert len(result.transfer_audit) == 2
    assert result.transfer_audit["transfer_verified"].all()
    assert len(result.session_audit) == 4
    assert result.session_audit["source_window_complete"].all()
    assert result.session_audit["daily_bar_emitted"].all()
    assert (result.session_audit["expected_hour_count"] == 24).all()
    assert (result.session_audit["payload_hashes_verified"] == 24).all()
    assert (result.session_audit["open_quote_delay_seconds"] == 1).all()
    assert (result.session_audit["close_quote_age_seconds"] == 1).all()

    eur = result.daily_data["EURUSD"]
    assert list(eur.columns) == [
        "open",
        "high",
        "low",
        "close",
        *QUOTE_COLUMNS,
        "session_open_quote_time",
        "session_close_quote_time",
        "volume",
        "tick_count",
    ]
    assert list(eur.index) == [
        pd.Timestamp(fx_session_bounds(value).end_utc) for value in session_dates
    ]
    assert (eur["ask_open"] >= eur["bid_open"]).all()
    assert (eur["ask_close"] >= eur["bid_close"]).all()
    assert (eur["tick_count"] == 48).all()
    assert (eur["volume"] == 24 * (2 + 3 + 5 + 7)).all()
    assert (
        eur["session_open_quote_time"].iloc[0]
        == pd.Timestamp(fx_session_bounds(session_dates[0]).start_utc)
        + timedelta(seconds=1)
    )
    assert (
        eur["session_close_quote_time"].iloc[0]
        == pd.Timestamp(fx_session_bounds(session_dates[0]).end_utc)
        - timedelta(seconds=1)
    )
    assert eur.attrs["source_database_transfer_verified"] is True
    assert eur.attrs["source_daily_session_boundary"] == "17:00"
    assert eur.attrs["source_failed_hours"] == 0
    assert eur.attrs["source_forward_filled"] is False

    daily = to_daily_market_data(result.daily_data)
    pdt.assert_frame_equal(daily["EURUSD"], eur)

    common_daily = build_common_daily_data(result)
    pdt.assert_frame_equal(common_daily["EURUSD"], eur)
    assert common_daily["EURUSD"].attrs["source_exact_common_sessions"] is True
    assert all(timestamp.hour in {21, 22} for timestamp in common_daily["EURUSD"].index)
    labels = build_long_horizon_labels(
        pd.DataFrame(
            {"_feature_time": eur.index, "_symbol": "EURUSD"}
        ),
        {"EURUSD": eur},
        LongHorizonSettings(),
    )
    first_label = labels.loc[labels["_feature_time"] == eur.index[0]].iloc[0]
    assert first_label["_entry_time"] == eur["session_open_quote_time"].iloc[1]
    assert first_label["_entry_time"] > first_label["_feature_time"]

    portfolio = build_portfolio_close_inputs(result)
    assert tuple(portfolio.calendar.symbols) == symbols
    assert list(portfolio.calendar.sessions) == [
        pd.Timestamp("2025-01-06", tz="UTC"),
        pd.Timestamp("2025-01-07", tz="UTC"),
    ]
    pdt.assert_series_equal(
        portfolio.mid_prices["EURUSD"],
        eur["close"].rename_axis("session").set_axis(portfolio.calendar.sessions),
        check_names=False,
    )
    assert (portfolio.asks >= portfolio.bids).all(axis=None)


def test_daily_sqlite_runner_suppresses_a_session_with_one_missing_hour(
    tmp_path: Path,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5), date(2025, 1, 6))
    missing_hour = pd.Timestamp("2025-01-07 05:00:00+00:00")
    root = tmp_path / "sqlite"
    manifest = _write_databases(
        root,
        symbols,
        session_dates,
        omit=("EURUSD", missing_hour),
    )

    result = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 7),
        transfer_manifest_path=manifest,
    )

    eur_audit = result.session_audit.loc[result.session_audit["symbol"] == "EURUSD"]
    failed = eur_audit.loc[
        eur_audit["session_start_local_date"] == date(2025, 1, 6)
    ].iloc[0]
    assert not bool(failed["source_window_complete"])
    assert not bool(failed["daily_bar_emitted"])
    assert failed["suppression_reason"] == "missing_source_hours"
    assert failed["missing_hour_count"] == 1
    assert missing_hour.isoformat() in failed["missing_hours"]
    assert len(result.daily_data["EURUSD"]) == 1
    assert len(result.daily_data["GBPUSD"]) == 2
    assert result.daily_data["EURUSD"].attrs["source_failed_hours"] == 1
    assert result.daily_data["EURUSD"].attrs["source_manifest_complete"] is False
    with pytest.raises(ValueError, match="reject missing SQLite source hours"):
        build_portfolio_close_inputs(result)
    with pytest.raises(ValueError, match="reject missing SQLite source hours"):
        build_common_daily_data(result)


def test_confirmed_no_data_hour_suppresses_ohlc_but_common_holiday_can_be_excluded(
    tmp_path: Path,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5), date(2025, 1, 6))
    no_data_hour = pd.Timestamp("2025-01-06 05:00:00+00:00")
    root = tmp_path / "sqlite"
    manifest = _write_databases(
        root,
        symbols,
        session_dates,
        no_data={("EURUSD", no_data_hour)},
    )

    result = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 7),
        transfer_manifest_path=manifest,
    )

    first = result.session_audit.iloc[0]
    assert bool(first["source_window_complete"])
    assert not bool(first["daily_bar_emitted"])
    assert first["suppression_reason"] == "confirmed_no_data_hours"
    assert first["no_data_hour_count"] == 1
    assert first["tick_count"] == 46
    assert result.daily_data["EURUSD"].attrs["source_no_data_hours"] == 1
    assert result.daily_data["EURUSD"].attrs["source_failed_hours"] == 0
    with pytest.raises(ValueError, match="symbol-specific incomplete sessions"):
        build_portfolio_close_inputs(result)
    with pytest.raises(ValueError, match="symbol-specific incomplete sessions"):
        build_common_daily_data(result)

    # A session containing a confirmed no-data hour for every symbol is not a
    # complete OHLC day and is removed as a common holiday, never filled.
    common_root = tmp_path / "common_sqlite"
    _write_databases(
        common_root,
        symbols,
        session_dates,
        no_data={(symbol, no_data_hour) for symbol in symbols},
    )
    common = run_dukascopy_daily_from_sqlite(
        common_root,
        symbols,
        session_dates[0],
        date(2025, 1, 7),
    )
    portfolio = build_portfolio_close_inputs(common)
    assert list(portfolio.calendar.sessions) == [pd.Timestamp("2025-01-07", tz="UTC")]
    common_daily = build_common_daily_data(common)
    assert all(len(frame) == 1 for frame in common_daily.values())
    assert all(frame.index[0].hour in {21, 22} for frame in common_daily.values())


def test_session_date_generator_excludes_weekend_fragments() -> None:
    assert ny_close_session_start_dates("2025-01-03", "2025-01-08") == (
        date(2025, 1, 5),
        date(2025, 1, 6),
        date(2025, 1, 7),
    )


def test_daily_sqlite_runner_rejects_stale_open_and_close_boundary_quotes(
    tmp_path: Path,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_date = date(2025, 1, 5)
    last_hour = _expected_hours(session_date)[-1]
    root = tmp_path / "sqlite"
    _write_databases(
        root,
        symbols,
        (session_date,),
        stale_open={("EURUSD", _expected_hours(session_date)[0])},
        stale_close={("GBPUSD", last_hour)},
    )

    result = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_date,
        date(2025, 1, 6),
    )

    eur = result.session_audit.loc[result.session_audit["symbol"] == "EURUSD"].iloc[0]
    gbp = result.session_audit.loc[result.session_audit["symbol"] == "GBPUSD"].iloc[0]
    assert eur["open_quote_delay_seconds"] == 10
    assert gbp["close_quote_age_seconds"] == 10
    assert not bool(eur["daily_bar_emitted"])
    assert not bool(gbp["daily_bar_emitted"])
    assert eur["suppression_reason"] == "boundary_quote_outside_threshold"
    assert gbp["suppression_reason"] == "boundary_quote_outside_threshold"
    assert result.daily_data["EURUSD"].empty
    assert result.daily_data["GBPUSD"].empty
    with pytest.raises(ValueError, match="reject non-holiday daily suppressions"):
        build_common_daily_data(result)


def test_daily_sqlite_runner_preserves_summer_21_utc_new_york_close(
    tmp_path: Path,
) -> None:
    symbol = "EURUSD"
    session_date = date(2025, 6, 1)
    root = tmp_path / "sqlite"
    _write_databases(root, (symbol,), (session_date,))

    result = run_dukascopy_daily_from_sqlite(
        root,
        (symbol,),
        session_date,
        date(2025, 6, 2),
    )

    assert result.daily_data[symbol].index[0] == pd.Timestamp("2025-06-02 21:00:00Z")
    common = build_common_daily_data(result)
    assert common[symbol].index[0] == pd.Timestamp("2025-06-02 21:00:00Z")


def test_daily_cache_round_trip_preserves_bars_audits_and_outcome_blind_receipt(
    tmp_path: Path,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5), date(2025, 1, 6))
    root = tmp_path / "sqlite"
    manifest = _write_databases(root, symbols, session_dates)
    run = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 7),
        transfer_manifest_path=manifest,
    )

    cache = tmp_path / "daily.sqlite"
    written = write_dukascopy_daily_cache(run, cache)
    loaded, verified = load_dukascopy_daily_cache(
        cache,
        root,
        transfer_manifest_path=manifest,
    )

    assert written == verified
    assert written.symbols == symbols
    assert written.session_count == 2
    assert written.daily_bar_count == 4
    receipt = json.loads(Path(f"{cache}.json").read_text(encoding="utf-8"))
    contract = receipt["contract"]
    assert contract["contains_returns"] is False
    assert contract["contains_labels"] is False
    assert contract["contains_positions"] is False
    assert contract["return_labels_opened"] is False
    assert contract["factor_outcome_evaluations_added"] == 0
    assert contract["trading_approval"] is False
    assert loaded.requested_session_start_dates == run.requested_session_start_dates
    pdt.assert_frame_equal(loaded.session_audit, run.session_audit)
    pdt.assert_frame_equal(loaded.transfer_audit, run.transfer_audit)
    for symbol in symbols:
        pdt.assert_frame_equal(loaded.daily_data[symbol], run.daily_data[symbol])
        assert loaded.daily_data[symbol].attrs == run.daily_data[symbol].attrs
    portfolio = build_portfolio_close_inputs(loaded)
    assert len(portfolio.calendar.sessions) == 2


def test_daily_cache_reuses_transfer_receipts_without_rehashing_source_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5),)
    root = tmp_path / "sqlite"
    manifest = _write_databases(root, symbols, session_dates)
    run = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 6),
        transfer_manifest_path=manifest,
    )
    cache = tmp_path / "daily.sqlite"
    write_dukascopy_daily_cache(run, cache)
    receipts = {
        symbol: verify_database_transfer(root / f"{symbol}.sqlite", manifest, symbol=symbol)
        for symbol in symbols
    }

    def unexpected_full_verification(*args, **kwargs):
        raise AssertionError("verified source receipts must be reused")

    monkeypatch.setattr(
        "fx_system.dukascopy_daily_cache.verify_database_transfer",
        unexpected_full_verification,
    )
    loaded, _ = load_dukascopy_daily_cache(
        cache,
        root,
        transfer_manifest_path=manifest,
        transfer_receipts=receipts,
    )

    assert sum(len(frame) for frame in loaded.daily_data.values()) == 2


def test_daily_cache_fails_closed_on_cache_or_source_receipt_change(tmp_path: Path) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5),)
    root = tmp_path / "sqlite"
    manifest = _write_databases(root, symbols, session_dates)
    run = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        date(2025, 1, 6),
        transfer_manifest_path=manifest,
    )
    cache = tmp_path / "daily.sqlite"
    write_dukascopy_daily_cache(run, cache)

    with cache.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(DukascopyDailyCacheError, match="hash/size"):
        load_dukascopy_daily_cache(cache, root, transfer_manifest_path=manifest)

    # Rebuild the cache, then prove a changed source cannot silently retain the
    # earlier aggregation receipt.
    write_dukascopy_daily_cache(run, cache, overwrite=True)
    with sqlite3.connect(root / "EURUSD.sqlite") as connection:
        connection.execute("INSERT INTO metadata VALUES ('post_cache_change', '1')")
    with pytest.raises(TransferIntegrityError, match="size|SHA-256"):
        load_dukascopy_daily_cache(cache, root, transfer_manifest_path=manifest)


def test_daily_checkpoint_resumes_and_matches_full_run(tmp_path: Path) -> None:
    symbols = ("EURUSD", "GBPUSD")
    session_dates = (date(2025, 1, 5), date(2025, 1, 6))
    root = tmp_path / "sqlite"
    manifest = _write_databases(root, symbols, session_dates)
    end = date(2025, 1, 7)

    full = run_dukascopy_daily_from_sqlite(
        root, symbols, session_dates[0], end, transfer_manifest_path=manifest
    )

    checkpoint = tmp_path / "daily_checkpoint.sqlite"
    run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        end,
        transfer_manifest_path=manifest,
        checkpoint_path=checkpoint,
    )
    assert checkpoint.is_file()
    # Second run with the same checkpoint must not re-decode: same result, fast.
    import sqlite3 as _sqlite3

    rows_before = _sqlite3.connect(checkpoint).execute(
        "SELECT COUNT(*) FROM session_checkpoint"
    ).fetchone()[0]
    assert rows_before == len(symbols) * len(session_dates)

    resumed = run_dukascopy_daily_from_sqlite(
        root,
        symbols,
        session_dates[0],
        end,
        transfer_manifest_path=manifest,
        checkpoint_path=checkpoint,
    )
    rows_after = _sqlite3.connect(checkpoint).execute(
        "SELECT COUNT(*) FROM session_checkpoint"
    ).fetchone()[0]
    assert rows_after == rows_before  # no new decoding happened

    # Resumed audit/daily must equal the no-checkpoint full run.
    pdt.assert_frame_equal(
        resumed.session_audit.reset_index(drop=True),
        full.session_audit.reset_index(drop=True),
        check_exact=False,
    )
    for symbol in symbols:
        pdt.assert_frame_equal(
            resumed.daily_data[symbol].sort_index(),
            full.daily_data[symbol].sort_index(),
            check_exact=False,
        )

    # A changed source SHA invalidates the cached session for that symbol.
    with _sqlite3.connect(root / "EURUSD.sqlite") as connection:
        connection.execute("INSERT INTO metadata VALUES ('source_change', '1')")
    with pytest.raises(TransferIntegrityError, match="size|SHA-256"):
        run_dukascopy_daily_from_sqlite(
            root,
            symbols,
            session_dates[0],
            end,
            transfer_manifest_path=manifest,
            checkpoint_path=checkpoint,
        )
