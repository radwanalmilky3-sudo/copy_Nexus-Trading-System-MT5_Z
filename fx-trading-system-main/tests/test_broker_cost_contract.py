"""Broker-neutral cost ingestion, provenance and fail-closed coverage audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from fx_system.broker_cost_contract import (
    BrokerCostContractError,
    assert_formal_cost_ready,
    audit_cost_coverage,
    load_cost_dataset,
    load_swap_directory,
    validate_forward_schedule,
    validate_swap_schedule,
    write_cost_coverage_report,
)


def _swap_rows(
    symbols: tuple[str, ...] = ("EURUSD", "GBPUSD"),
    dates: tuple[str, ...] = (
        "2020-01-01T22:00:00Z",
        "2020-02-01T22:00:00Z",
        "2020-03-01T22:00:00Z",
    ),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for date in dates:
            rows.append(
                {
                    "symbol": symbol,
                    "effective_time": date,
                    "available_time": date,
                    "long_financing": -0.7,
                    "short_financing": 0.3,
                    "unit": "pips",
                    "day_count": "broker_schedule",
                    "source": "broker_secure_export",
                    "provenance": "ticket-123/export.csv",
                    "quote_quality": "historical_target_broker_schedule",
                    "version": "export-v1",
                    "broker_entity": "Example Broker Legal Entity Ltd",
                    "account_currency": "USD",
                    "triple_swap_weekday": "wednesday",
                    "rollover_multiplier": 1.0,
                }
            )
    return pd.DataFrame(rows)


def _forward_rows(
    symbols: tuple[str, ...] = ("EURUSD", "GBPUSD"),
    dates: tuple[str, ...] = (
        "2020-01-01T16:00:00Z",
        "2020-02-01T16:00:00Z",
        "2020-03-01T16:00:00Z",
    ),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for date in dates:
            observation = pd.Timestamp(date)
            rows.append(
                {
                    "symbol": symbol,
                    "observation_time": date,
                    "available_time": (observation + pd.Timedelta(1, unit="s")).isoformat(),
                    "tenor": "1M",
                    "bid_points": 0.0010,
                    "ask_points": 0.0012,
                    "points_unit": "absolute_price",
                    "source": "broker_secure_export",
                    "provenance": "ticket-123/forwards.csv",
                    "quote_quality": "historical_tradable_bid_ask",
                    "version": "export-v1",
                    "broker_entity": "Example Broker Legal Entity Ltd",
                }
            )
    return pd.DataFrame(rows)


def _write_manifest(path: Path, dataset_kind: str, frame: pd.DataFrame) -> Path:
    if dataset_kind == "broker_financing_schedule":
        columns = (
            "source",
            "provenance",
            "quote_quality",
            "version",
            "broker_entity",
            "account_currency",
        )
    else:
        columns = ("source", "provenance", "quote_quality", "version", "broker_entity")
    catalog = [
        dict(zip(columns, row, strict=True))
        for row in frame[list(columns)].drop_duplicates().itertuples(index=False, name=None)
    ]
    manifest = {
        "schema_version": 1,
        "dataset_kind": dataset_kind,
        "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_catalog": catalog,
    }
    manifest_path = path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_swap_and_forward_schema_validation() -> None:
    swaps = validate_swap_schedule(_swap_rows())
    forwards = validate_forward_schedule(_forward_rows())
    assert list(swaps["symbol"].unique()) == ["EURUSD", "GBPUSD"]
    assert (forwards["ask_points"] >= forwards["bid_points"]).all()
    assert swaps["triple_swap_weekday"].eq("wednesday").all()
    assert swaps["account_currency"].eq("USD").all()


def test_zero_rollover_requires_zero_financing() -> None:
    no_rollover = _swap_rows(symbols=("EURUSD",), dates=("2020-01-01T22:00:00Z",))
    no_rollover.loc[0, ["long_financing", "short_financing", "rollover_multiplier"]] = 0
    validated = validate_swap_schedule(no_rollover)
    assert validated.loc[0, "rollover_multiplier"] == 0

    nonzero_charge = no_rollover.copy()
    nonzero_charge.loc[0, "long_financing"] = -0.1
    with pytest.raises(BrokerCostContractError, match="zero only when"):
        validate_swap_schedule(nonzero_charge)

    negative = no_rollover.copy()
    negative.loc[0, "rollover_multiplier"] = -1
    with pytest.raises(BrokerCostContractError, match="non-negative"):
        validate_swap_schedule(negative)


def test_crossed_forward_and_naive_available_time_are_rejected() -> None:
    crossed = _forward_rows()
    crossed.loc[0, "ask_points"] = -1.0
    with pytest.raises(BrokerCostContractError, match="ask_points"):
        validate_forward_schedule(crossed)

    naive = _swap_rows()
    naive.loc[0, "available_time"] = "2020-01-01 22:00:00"
    with pytest.raises(BrokerCostContractError, match="timezone-naive"):
        validate_swap_schedule(naive)


def test_missing_target_identity_and_source_evidence_fail_closed() -> None:
    report = audit_cost_coverage(
        swap_frame=_swap_rows(),
        forward_frame=_forward_rows(),
        required_symbols=("EURUSD", "GBPUSD"),
        coverage_start="2020-01-01T00:00:00Z",
        coverage_end_exclusive="2020-04-01T00:00:00Z",
        broker_entity=None,
        account_currency=None,
        swap_manifest_verified=True,
        forward_manifest_verified=True,
        max_swap_gap_days=40,
        max_forward_gap_days=40,
        minimum_coverage_fraction=1.0,
    )
    assert report.verdict == "cost_incomplete_research_only"
    assert report.formal_net_returns_ready is False
    assert report.trading_approval is False
    assert report.return_labels_opened is False
    assert report.factor_outcome_evaluations_added == 0
    assert report.product_profile == "spot_plus_forward"
    assert any("broker_entity" in issue for issue in report.issues)
    assert any("account_currency" in issue for issue in report.issues)
    assert any("authenticity" in issue for issue in report.issues)
    with pytest.raises(BrokerCostContractError, match="formal cost gate closed"):
        assert_formal_cost_ready(report)


def test_rolling_spot_product_gate_does_not_require_forward_quotes() -> None:
    swaps = _swap_rows()
    swaps.loc[swaps["effective_time"].eq("2020-02-01T22:00:00Z"), "rollover_multiplier"] = 3
    report = audit_cost_coverage(
        swap_frame=swaps,
        forward_frame=None,
        required_symbols=("EURUSD", "GBPUSD"),
        coverage_start="2020-01-01T00:00:00Z",
        coverage_end_exclusive="2020-04-01T00:00:00Z",
        broker_entity="Example Broker Legal Entity Ltd",
        account_currency="USD",
        swap_manifest_verified=True,
        swap_source_evidence_verified=True,
        max_swap_gap_days=40,
        minimum_coverage_fraction=1.0,
        product_profile="rolling_spot_margin",
    )

    assert report.product_profile == "rolling_spot_margin"
    assert report.historical_market_swap is True
    assert report.historical_market_forward is False
    assert report.verdict == "historical_market_cost_ready"
    assert "forward schedule missing" not in report.issues
    assert report.formal_net_returns_ready is False
    assert report.trading_approval is False
    with pytest.raises(BrokerCostContractError, match="formal cost gate closed"):
        assert_formal_cost_ready(report)


def test_spot_plus_forward_remains_default_and_invalid_profile_is_rejected() -> None:
    default_report = audit_cost_coverage(
        swap_frame=None,
        forward_frame=None,
        required_symbols=("EURUSD",),
    )
    assert default_report.product_profile == "spot_plus_forward"
    assert "forward schedule missing" in default_report.issues

    with pytest.raises(BrokerCostContractError, match="product_profile"):
        audit_cost_coverage(
            swap_frame=None,
            forward_frame=None,
            required_symbols=("EURUSD",),
            product_profile="unsupported",  # type: ignore[arg-type]
        )


def test_coverage_is_calculated_per_symbol_not_concatenated() -> None:
    sparse_gbp = _swap_rows(
        symbols=("GBPUSD",),
        dates=("2020-01-01T22:00:00Z",),
    )
    swaps = pd.concat([_swap_rows(symbols=("EURUSD",)), sparse_gbp], ignore_index=True)
    report = audit_cost_coverage(
        swap_frame=swaps,
        forward_frame=None,
        required_symbols=("EURUSD", "GBPUSD"),
        coverage_start="2020-01-01T00:00:00Z",
        coverage_end_exclusive="2020-04-01T00:00:00Z",
        broker_entity="Example Broker Legal Entity Ltd",
        account_currency="USD",
        max_swap_gap_days=40,
        minimum_coverage_fraction=1.0,
    )
    assert report.swap_coverage_by_symbol["EURUSD"]["coverage_fraction"] == 1.0
    assert report.swap_coverage_by_symbol["GBPUSD"]["coverage_fraction"] == pytest.approx(
        1 / 3
    )
    assert report.swap_coverage_fraction == pytest.approx(1 / 3)
    assert any("GBPUSD" in issue for issue in report.issues)


def test_legacy_inputs_are_readable_but_cannot_become_market_ready(tmp_path: Path) -> None:
    path = tmp_path / "EURUSD.csv"
    path.write_text(
        "available_time,swap_long_pips,swap_short_pips\n"
        "2020-01-01T22:00:00Z,-0.7,0.3\n",
        encoding="utf-8",
    )
    frame = load_swap_directory(tmp_path)
    assert frame.loc[0, "symbol"] == "EURUSD"
    assert frame.loc[0, "quote_quality"] == "unknown_unverified"
    report = audit_cost_coverage(
        swap_frame=frame,
        forward_frame=None,
        required_symbols=("EURUSD",),
        broker_entity="Example Broker Legal Entity Ltd",
        account_currency="USD",
    )
    assert report.verdict == "cost_incomplete_research_only"
    assert report.historical_market_swap is False


def test_canonical_import_verifies_hash_and_row_source_catalog(tmp_path: Path) -> None:
    frame = _swap_rows(symbols=("EURUSD",))
    path = tmp_path / "broker_financing.csv"
    frame.to_csv(path, index=False)
    _write_manifest(path, "broker_financing_schedule", frame)
    imported = load_cost_dataset(path, dataset_kind="broker_financing_schedule")
    assert imported.manifest_verified is True
    assert imported.csv_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(BrokerCostContractError, match="hash"):
        load_cost_dataset(path, dataset_kind="broker_financing_schedule")


def test_manifest_integrity_does_not_self_verify_source_authenticity(tmp_path: Path) -> None:
    swaps = _swap_rows()
    forwards = _forward_rows()
    swap_path = tmp_path / "broker_financing.csv"
    forward_path = tmp_path / "tradable_forwards.csv"
    swaps.to_csv(swap_path, index=False)
    forwards.to_csv(forward_path, index=False)
    _write_manifest(swap_path, "broker_financing_schedule", swaps)
    _write_manifest(forward_path, "tradable_forward_quotes", forwards)
    imported_swaps = load_cost_dataset(
        swap_path, dataset_kind="broker_financing_schedule"
    )
    imported_forwards = load_cost_dataset(
        forward_path, dataset_kind="tradable_forward_quotes"
    )

    report = audit_cost_coverage(
        swap_frame=imported_swaps.frame,
        forward_frame=imported_forwards.frame,
        required_symbols=("EURUSD", "GBPUSD"),
        coverage_start="2020-01-01T00:00:00Z",
        coverage_end_exclusive="2020-04-01T00:00:00Z",
        broker_entity="Example Broker Legal Entity Ltd",
        account_currency="USD",
        swap_manifest_verified=imported_swaps.manifest_verified,
        forward_manifest_verified=imported_forwards.manifest_verified,
        max_swap_gap_days=40,
        max_forward_gap_days=40,
        minimum_coverage_fraction=1.0,
    )
    assert report.verdict == "cost_incomplete_research_only"
    assert report.historical_market_swap is False
    assert report.historical_market_forward is False
    assert any("authenticity" in issue for issue in report.issues)
    output = write_cost_coverage_report(report, tmp_path / "cost_audit.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "cost_incomplete_research_only"
    assert payload["return_labels_opened"] is False
