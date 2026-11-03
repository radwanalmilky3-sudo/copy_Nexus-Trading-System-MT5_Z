from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from fx_system.config import DataConfig, RiskConfig
from fx_system.data import SyntheticFXProvider
from fx_system.factor_config import FactorMiningConfig, PointInTimeConfig
from fx_system.factor_research import audit_factor_data
from fx_system.point_in_time import (
    build_carry_factors,
    load_point_in_time_data,
    validate_currency_rates,
    validate_forward_points,
)


def _rate_rows(quality: str = "historical_market_ois_quote") -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "2025-01-01T16:00:00Z",
                "2025-01-01T16:00:01Z",
                "EUR",
                2.0,
                2.1,
                2.2,
                "licensed_rates_vendor",
                "vendor_ois_archive/v1",
                quality,
            ),
            (
                "2025-01-01T16:00:00Z",
                "2025-01-01T16:00:01Z",
                "USD",
                4.0,
                4.1,
                4.2,
                "licensed_rates_vendor",
                "vendor_ois_archive/v1",
                quality,
            ),
        ],
        columns=[
            "observation_time",
            "available_time",
            "currency",
            "policy_rate",
            "ois_1m",
            "ois_3m",
            "ois_source",
            "ois_provenance",
            "ois_quote_quality",
        ],
    )


def _forward_rows(quality: str = "historical_market_quote") -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "2025-01-01T16:00:00Z",
                "2025-01-01T16:00:01Z",
                "EURUSD",
                0.001,
                0.003,
                1.1,
                "licensed_forward_vendor",
                "vendor_fx_forward_archive/v2",
                quality,
            )
        ],
        columns=[
            "observation_time",
            "available_time",
            "symbol",
            "forward_points_1m",
            "forward_points_3m",
            "spot_reference",
            "source",
            "provenance",
            "quote_quality",
        ],
    )


def _write_csv_and_manifest(
    root: Path,
    filename: str,
    dataset_kind: str,
    frame: pd.DataFrame,
    metadata_columns: tuple[str, str, str],
) -> None:
    path = root / filename
    frame.to_csv(path, index=False)
    source_column, provenance_column, quality_column = metadata_columns
    source_catalog = [
        {
            "source": source,
            "provenance": provenance,
            "quote_quality": quality,
        }
        for source, provenance, quality in frame[
            [source_column, provenance_column, quality_column]
        ]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    ]
    manifest = {
        "schema_version": 1,
        "dataset_kind": dataset_kind,
        "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_catalog": source_catalog,
    }
    path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _write_contract(
    root: Path,
    *,
    rate_quality: str = "historical_market_ois_quote",
    forward_quality: str = "historical_market_quote",
) -> None:
    _write_csv_and_manifest(
        root,
        "currency_rates.csv",
        "currency_rates",
        _rate_rows(rate_quality),
        ("ois_source", "ois_provenance", "ois_quote_quality"),
    )
    _write_csv_and_manifest(
        root,
        "forward_points.csv",
        "forward_points",
        _forward_rows(forward_quality),
        ("source", "provenance", "quote_quality"),
    )


def test_csv_carry_rows_require_explicit_row_provenance() -> None:
    legacy_rates = _rate_rows().drop(
        columns=["ois_source", "ois_provenance", "ois_quote_quality"]
    )
    legacy_forwards = _forward_rows().drop(
        columns=["source", "provenance", "quote_quality"]
    )
    with pytest.raises(ValueError, match="per-row provenance"):
        validate_currency_rates(legacy_rates)
    with pytest.raises(ValueError, match="per-row provenance"):
        validate_forward_points(legacy_forwards)

    rates = validate_currency_rates(legacy_rates, allow_legacy_unverified=True)
    forwards = validate_forward_points(legacy_forwards, allow_legacy_unverified=True)
    assert rates["ois_quote_quality"].eq("unknown_unverified").all()
    assert forwards["quote_quality"].eq("unknown_unverified").all()
    assert not rates["_ois_row_historical_market"].any()
    assert not forwards["_forward_row_historical_market"].any()


def test_verified_manifests_and_row_quality_are_both_required(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    config = PointInTimeConfig(
        enabled=True,
        provider="csv",
        directory=tmp_path,
        require_verified_carry_manifests=True,
    )
    point_in_time = load_point_in_time_data(config)
    assert point_in_time is not None
    assert point_in_time.carry_contract_audit() == {
        "currency_rates_manifest_verified": True,
        "forward_points_manifest_verified": True,
        "market_ois_row_fraction": 1.0,
        "historical_market_forward_row_fraction": 1.0,
        "verified_historical_market_contract": True,
    }

    index = pd.DatetimeIndex(["2025-01-02T16:00:00Z"])
    factors = build_carry_factors(
        "EURUSD", pd.DataFrame({"close": [1.1]}, index=index), point_in_time, 260
    )
    assert factors["_market_ois_verified"].all()
    assert factors["_market_forward_verified"].all()


def test_policy_and_synthetic_proxies_cannot_self_certify_with_a_manifest(
    tmp_path: Path,
) -> None:
    _write_contract(
        tmp_path,
        rate_quality="policy_rate_proxy",
        forward_quality="synthetic_interest_parity",
    )
    config = PointInTimeConfig(
        enabled=True,
        provider="csv",
        directory=tmp_path,
        require_verified_carry_manifests=True,
    )
    point_in_time = load_point_in_time_data(config)
    assert point_in_time is not None
    audit = point_in_time.carry_contract_audit()
    assert audit["currency_rates_manifest_verified"] is True
    assert audit["forward_points_manifest_verified"] is True
    assert audit["market_ois_row_fraction"] == 0.0
    assert audit["historical_market_forward_row_fraction"] == 0.0
    assert audit["verified_historical_market_contract"] is False

    data = SyntheticFXProvider(seed=911).generate(
        ["EURUSD"], 30, "1d", start="2025-01-02", price_mode="bid_ask"
    )
    mining_config = FactorMiningConfig(
        data=DataConfig(
            provider="synthetic",
            symbols=["EURUSD"],
            interval="1d",
            start="2025-01-02",
            synthetic_bars=30,
            price_mode="bid_ask",
        ),
        risk=RiskConfig(close_before_weekend=False),
        point_in_time=config,
    )
    readiness = audit_factor_data(data, mining_config, point_in_time)
    assert readiness["exploratory_carry_value_coverage"] > 0
    assert readiness["carry_coverage"] == 0.0
    assert readiness["historical_market_ois_coverage"] == 0.0
    assert readiness["historical_market_forward_coverage"] == 0.0
    assert readiness["broker_ready"] is False


def test_manifest_hash_and_declared_row_sources_are_enforced(tmp_path: Path) -> None:
    _write_contract(tmp_path)
    forward_path = tmp_path / "forward_points.csv"
    forward_path.write_text(forward_path.read_text() + "\n", encoding="utf-8")
    config = PointInTimeConfig(
        enabled=True,
        provider="csv",
        directory=tmp_path,
        require_verified_carry_manifests=True,
    )
    with pytest.raises(ValueError, match="does not match its source manifest"):
        load_point_in_time_data(config)

    _write_contract(tmp_path)
    manifest_path = tmp_path / "forward_points.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_catalog"][0]["provenance"] = "different_archive"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="row-level source.*undeclared"):
        load_point_in_time_data(config)


def test_config_cannot_mix_legacy_rows_with_verified_manifests() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        PointInTimeConfig(
            enabled=True,
            provider="csv",
            allow_legacy_unverified_carry_rows=True,
            require_verified_carry_manifests=True,
        )


def test_verified_positioning_requires_actual_release_and_as_published_values(
    tmp_path: Path,
) -> None:
    _write_contract(tmp_path)
    positioning = pd.DataFrame(
        {
            "observation_time": ["2025-01-07T00:00:00Z"],
            "available_time": ["2025-01-10T20:30:00Z"],
            "currency": ["EUR"],
            "open_interest": [1000.0],
            "dealer_net_ratio": [-0.1],
            "asset_manager_net_ratio": [0.2],
            "leveraged_money_net_ratio": [0.1],
            "availability_quality": ["verified_actual_publication"],
            "value_vintage_quality": [
                "current_revised_historical_archive_not_as_published_vintage"
            ],
        }
    )
    path = tmp_path / "currency_positioning.csv"

    def write_positioning_contract() -> None:
        positioning.to_csv(path, index=False)
        path.with_suffix(".manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    write_positioning_contract()
    config = PointInTimeConfig(
        enabled=True,
        provider="csv",
        directory=tmp_path,
        positioning_enabled=True,
        positioning_release_quality="verified",
    )
    with pytest.raises(ValueError, match="as-published vintages"):
        load_point_in_time_data(config)

    positioning["value_vintage_quality"] = "verified_as_published_vintage"
    write_positioning_contract()
    point_in_time = load_point_in_time_data(config)
    assert point_in_time is not None
    assert point_in_time.currency_positioning is not None
    assert point_in_time.currency_positioning["value_vintage_quality"].eq(
        "verified_as_published_vintage"
    ).all()
