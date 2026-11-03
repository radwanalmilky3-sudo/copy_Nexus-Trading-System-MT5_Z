from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from fx_system.broker_cost_contract import load_cost_dataset


def _load_converter():
    path = Path(__file__).parents[1] / "scripts" / "convert_oanda_financing_to_cost_contract.py"
    spec = importlib.util.spec_from_file_location("convert_oanda_financing_to_cost_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


converter = _load_converter()


def _write_source(tmp_path: Path, *, zero_day_charge: str = "0.00") -> tuple[Path, Path]:
    root = tmp_path / "oanda"
    csv_path = root / "normalized" / "financing_history.csv"
    csv_path.parent.mkdir(parents=True)
    raw_path = root / "raw" / "2025" / "2025-12-22.json"
    raw_path.parent.mkdir(parents=True)
    raw_payload = b'{"divisionId":1,"tradingGroupId":1}\n'
    raw_path.write_bytes(raw_payload)
    raw_sha = hashlib.sha256(raw_payload).hexdigest()
    columns = [
        "requested_date",
        "effective_time",
        "instrument",
        "symbol",
        "days",
        "annualized_long_rate",
        "annualized_short_rate",
        "long_charge",
        "short_charge",
        "charge_currency",
        "units",
        "retrieved_at",
        "raw_sha256",
    ]
    shared = {
        "requested_date": "2025-12-22",
        "effective_time": "2025-12-22T22:00:00+00:00",
        "annualized_long_rate": "0",
        "annualized_short_rate": "0",
        "charge_currency": "USD",
        "units": "100000",
        "retrieved_at": "2026-07-15T08:22:27+00:00",
        "raw_sha256": raw_sha,
    }
    rows = [
        {
            **shared,
            "instrument": "EUR/USD",
            "symbol": "EURUSD",
            "days": "5",
            "long_charge": "-50.00",
            "short_charge": "25.00",
        },
        {
            **shared,
            "instrument": "GBP/USD",
            "symbol": "GBPUSD",
            "days": "0",
            "long_charge": zero_day_charge,
            "short_charge": "0.00",
        },
        {
            **shared,
            "instrument": "USD/JPY",
            "symbol": "USDJPY",
            "days": "1",
            "long_charge": "1.00",
            "short_charge": "-2.00",
        },
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "source_page": converter.SOURCE_PAGE,
        "api_endpoint": converter.SOURCE_ENDPOINT,
        "division_id": 1,
        "trading_group_id": 1,
        "symbols": ["EURUSD", "GBPUSD", "USDJPY"],
        "failed_dates": 0,
        "rows": len(rows),
        "normalized_csv": "normalized/financing_history.csv",
        "normalized_csv_sha256": csv_sha,
        "files": [
            {
                "requested_date": "2025-12-22",
                "path": "raw/2025/2025-12-22.json",
                "bytes": len(raw_payload),
                "sha256": raw_sha,
            }
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return csv_path, manifest_path


def test_converter_normalizes_event_totals_without_double_counting(tmp_path: Path) -> None:
    source_csv, source_manifest = _write_source(tmp_path)
    output = tmp_path / "converted" / "oanda_costs.csv"

    conversion = converter.convert_oanda_financing(source_csv, source_manifest, output)

    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["symbol"] for row in rows} == {"EURUSD", "GBPUSD"}
    eur = next(row for row in rows if row["symbol"] == "EURUSD")
    assert float(eur["long_financing"]) == pytest.approx(-0.0001)
    assert float(eur["short_financing"]) == pytest.approx(0.00005)
    assert eur["rollover_multiplier"] == "5"
    assert eur["triple_swap_weekday"] == "wednesday"
    assert float(eur["long_financing"]) * 100000 * 5 == pytest.approx(-50.0)
    assert eur["available_time"] == "2026-07-15T08:22:27+00:00"
    assert eur["quote_quality"] == converter.QUOTE_QUALITY

    gbp = next(row for row in rows if row["symbol"] == "GBPUSD")
    assert gbp["rollover_multiplier"] == "0"
    assert float(gbp["long_financing"]) == 0
    assert float(gbp["short_financing"]) == 0

    imported = load_cost_dataset(output, dataset_kind="broker_financing_schedule")
    assert imported.manifest_verified is True
    assert imported.frame["quote_quality"].eq(converter.QUOTE_QUALITY).all()
    assert imported.frame["broker_entity"].eq("OANDA Corporation").all()
    assert imported.frame["account_currency"].eq("USD").all()

    source_sidecar = json.loads(output.with_suffix(".manifest.json").read_text())
    assert source_sidecar["formal_cost_eligible"] is False
    assert source_sidecar["license_confirmed"] is False
    assert source_sidecar["redistribution_allowed"] is False
    assert source_sidecar["conversion_scope"].startswith("offline transformation")
    assert source_sidecar["raw_source_verification"] == {
        "files_verified": 1,
        "existence_bytes_and_sha256_verified": True,
    }
    assert "authoritative" in source_sidecar["rollover_semantics"]
    assert set(source_sidecar["blockers"]) == {
        "license",
        "point_in_time",
        "account_specific",
        "history",
    }
    assert conversion["output"]["csv_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert conversion["amount_semantics"]["double_count_prevented"] is True
    assert conversion["amount_semantics"]["rollover_multiplier_is_authoritative"] is True
    assert "Monday, Tuesday, or Thursday" in conversion["amount_semantics"][
        "triple_swap_weekday"
    ]
    assert conversion["source"]["raw_existence_bytes_and_sha256_verified"] is True
    assert conversion["network_accessed"] is False
    assert conversion["license_confirmed"] is False
    assert conversion["redistribution_allowed"] is False
    assert "no permission confirmed" in conversion["blockers"]["license"]
    assert conversion["formal_net_returns_ready"] is False
    assert conversion["trading_approval"] is False


def test_converter_rejects_nonzero_charge_on_zero_day(tmp_path: Path) -> None:
    source_csv, source_manifest = _write_source(tmp_path, zero_day_charge="-1.00")

    with pytest.raises(converter.OandaCostConversionError, match="days=0 requires zero"):
        converter.convert_oanda_financing(
            source_csv,
            source_manifest,
            tmp_path / "converted.csv",
        )


def test_converter_rejects_source_csv_hash_mismatch(tmp_path: Path) -> None:
    source_csv, source_manifest = _write_source(tmp_path)
    source_csv.write_text(source_csv.read_text() + "\n", encoding="utf-8")

    with pytest.raises(converter.OandaCostConversionError, match="hash"):
        converter.convert_oanda_financing(
            source_csv,
            source_manifest,
            tmp_path / "converted.csv",
        )


def test_converter_rejects_raw_file_hash_mismatch(tmp_path: Path) -> None:
    source_csv, source_manifest = _write_source(tmp_path)
    raw_path = source_manifest.parent / "raw/2025/2025-12-22.json"
    raw_path.write_bytes(raw_path.read_bytes() + b"tampered")

    with pytest.raises(converter.OandaCostConversionError, match="byte count mismatch"):
        converter.convert_oanda_financing(
            source_csv,
            source_manifest,
            tmp_path / "converted.csv",
        )
