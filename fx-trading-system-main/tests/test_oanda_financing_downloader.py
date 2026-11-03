from __future__ import annotations

import csv
import importlib.util
import json
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _load_downloader():
    path = Path(__file__).parents[1] / "scripts" / "download_oanda_financing_history.py"
    spec = importlib.util.spec_from_file_location("download_oanda_financing_history", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


downloader = _load_downloader()


def _payload(requested_date, *, division_id=1, trading_group_id=1) -> bytes:
    return json.dumps(
        {
            "financingRates": [
                {
                    "currency": "USD",
                    "days": 1,
                    "instrument": "EUR/USD",
                    "longCharge": "-7.67",
                    "longRate": "-0.0245",
                    "shortCharge": "1.35",
                    "shortRate": "0.0043",
                    "units": 100000,
                },
                {
                    "currency": "USD",
                    "days": 1,
                    "instrument": "USD/JPY",
                    "longCharge": "6.68",
                    "longRate": "0.0183",
                    "shortCharge": "-14.03",
                    "shortRate": "-0.0384",
                    "units": 100000,
                },
            ],
            "divisionId": division_id,
            "tradingGroupId": trading_group_id,
            "timestamp": f"{requested_date.isoformat()}T21:00:00Z",
        }
    ).encode()


def test_validate_response_selects_symbols_and_preserves_source_units() -> None:
    requested_date = datetime.now(UTC).date() - timedelta(days=2)

    document, rows = downloader.validate_response(
        _payload(requested_date),
        requested_date=requested_date,
        division_id=1,
        trading_group_id=1,
        required_symbols={"EURUSD"},
    )

    assert document["timestamp"].startswith(requested_date.isoformat())
    assert rows == [
        {
            "requested_date": requested_date.isoformat(),
            "effective_time": f"{requested_date.isoformat()}T21:00:00+00:00",
            "instrument": "EUR/USD",
            "symbol": "EURUSD",
            "days": 1,
            "annualized_long_rate": "-0.0245",
            "annualized_short_rate": "0.0043",
            "long_charge": "-7.67",
            "short_charge": "1.35",
            "charge_currency": "USD",
            "units": 100000,
        }
    ]


def test_validate_response_rejects_wrong_division_date_and_missing_symbol() -> None:
    requested_date = datetime.now(UTC).date() - timedelta(days=2)
    arguments = {
        "requested_date": requested_date,
        "division_id": 1,
        "trading_group_id": 1,
        "required_symbols": {"EURUSD"},
    }
    with pytest.raises(ValueError, match="divisionId"):
        downloader.validate_response(_payload(requested_date, division_id=2), **arguments)
    with pytest.raises(ValueError, match="timestamp"):
        downloader.validate_response(_payload(requested_date - timedelta(days=1)), **arguments)
    with pytest.raises(ValueError, match="missing required symbols"):
        downloader.validate_response(
            _payload(requested_date), **{**arguments, "required_symbols": {"GBPUSD"}}
        )


def test_validate_response_accepts_verified_long_holiday_rollover() -> None:
    requested_date = datetime.now(UTC).date() - timedelta(days=2)
    document = json.loads(_payload(requested_date))
    document["financingRates"][0]["days"] = 11

    _source, rows = downloader.validate_response(
        json.dumps(document).encode(),
        requested_date=requested_date,
        division_id=1,
        trading_group_id=1,
        required_symbols={"EURUSD"},
    )

    assert rows[0]["days"] == 11


def test_main_downloads_atomically_and_reuses_valid_cache(tmp_path, monkeypatch) -> None:
    requested_date = datetime.now(UTC).date() - timedelta(days=2)
    calls = 0

    def fake_fetch(url, *, timeout, retries):
        nonlocal calls
        calls += 1
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        date_text = query["time"][0].split("T", maxsplit=1)[0]
        return _payload(datetime.fromisoformat(date_text).date())

    monkeypatch.setattr(downloader, "_fetch", fake_fetch)
    arguments = [
        "--output",
        str(tmp_path),
        "--start-date",
        requested_date.isoformat(),
        "--end-date",
        requested_date.isoformat(),
        "--symbols",
        "EURUSD,USDJPY",
        "--delay-seconds",
        "0",
    ]

    assert downloader.main(arguments) == 0
    assert downloader.main(arguments) == 0
    assert calls == 1

    raw_path = tmp_path / "raw" / str(requested_date.year) / f"{requested_date}.json"
    assert json.loads(raw_path.read_text())["divisionId"] == 1
    with (tmp_path / "normalized/financing_history.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["symbol"] for row in rows} == {"EURUSD", "USDJPY"}
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["successful_dates"] == 1
    assert manifest["failed_dates"] == 0
    assert manifest["rows"] == 2
