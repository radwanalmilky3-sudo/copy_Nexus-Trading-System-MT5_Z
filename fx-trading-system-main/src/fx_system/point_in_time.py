from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .cftc import validate_currency_positioning
from .factor_config import PointInTimeConfig
from .models import CurrencyPair

RATE_COLUMNS = ("policy_rate", "ois_1m", "ois_3m")
FORWARD_COLUMNS = ("forward_points_1m", "forward_points_3m", "spot_reference")
RATE_METADATA_COLUMNS = ("ois_source", "ois_provenance", "ois_quote_quality")
FORWARD_METADATA_COLUMNS = ("source", "provenance", "quote_quality")

HISTORICAL_MARKET_OIS_QUALITY = "historical_market_ois_quote"
HISTORICAL_MARKET_FORWARD_QUALITY = "historical_market_quote"
OIS_QUOTE_QUALITIES = frozenset(
    {
        HISTORICAL_MARKET_OIS_QUALITY,
        "policy_rate_proxy",
        "overnight_rate_proxy",
        "synthetic_curve",
        "software_synthetic",
        "unknown_unverified",
    }
)
FORWARD_QUOTE_QUALITIES = frozenset(
    {
        HISTORICAL_MARKET_FORWARD_QUALITY,
        "current_market_snapshot",
        "synthetic_interest_parity",
        "broker_financing_proxy",
        "policy_rate_proxy",
        "software_synthetic",
        "unknown_unverified",
    }
)


@dataclass(frozen=True)
class PointInTimeData:
    currency_rates: pd.DataFrame
    forward_points: pd.DataFrame
    maximum_staleness_days: int = 45
    currency_positioning: pd.DataFrame | None = None
    maximum_positioning_staleness_days: int = 14
    currency_rates_manifest_verified: bool = False
    forward_points_manifest_verified: bool = False

    def carry_contract_audit(self) -> dict[str, object]:
        rate_rows = self.currency_rates.get("_ois_row_historical_market")
        forward_rows = self.forward_points.get("_forward_row_historical_market")
        market_ois_fraction = float(rate_rows.mean()) if rate_rows is not None else 0.0
        market_forward_fraction = (
            float(forward_rows.mean()) if forward_rows is not None else 0.0
        )
        return {
            "currency_rates_manifest_verified": self.currency_rates_manifest_verified,
            "forward_points_manifest_verified": self.forward_points_manifest_verified,
            "market_ois_row_fraction": market_ois_fraction,
            "historical_market_forward_row_fraction": market_forward_fraction,
            "verified_historical_market_contract": bool(
                self.currency_rates_manifest_verified
                and self.forward_points_manifest_verified
                and market_ois_fraction > 0
                and market_forward_fraction > 0
            ),
        }

    def fingerprint(self, available_through: pd.Timestamp | None = None) -> str:
        digest = hashlib.sha256()
        digest.update(
            json.dumps(
                {
                    "currency_rates_manifest_verified": self.currency_rates_manifest_verified,
                    "forward_points_manifest_verified": self.forward_points_manifest_verified,
                },
                sort_keys=True,
            ).encode()
        )
        for name, frame in (
            ("currency_rates", self.currency_rates),
            ("forward_points", self.forward_points),
        ):
            digest.update(name.encode())
            selected = (
                frame.loc[frame["available_time"] <= available_through]
                if available_through is not None
                else frame
            )
            ordered = selected.sort_values(list(frame.columns[:3])).reset_index(drop=True)
            digest.update(pd.util.hash_pandas_object(ordered, index=True).values.tobytes())
        if self.currency_positioning is not None:
            digest.update(b"currency_positioning")
            selected = (
                self.currency_positioning.loc[
                    self.currency_positioning["available_time"] <= available_through
                ]
                if available_through is not None
                else self.currency_positioning
            )
            ordered = selected.sort_values(
                ["currency", "available_time"]
            ).reset_index(drop=True)
            digest.update(pd.util.hash_pandas_object(ordered, index=True).values.tobytes())
        return digest.hexdigest()


def _normalize_timestamp_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        raise ValueError(f"point-in-time data is missing {column!r}")
    values = pd.to_datetime(
        frame[column], utc=True, errors="coerce", format="mixed"
    )
    if values.isna().any():
        raise ValueError(f"point-in-time data contains invalid {column!r} values")
    return values


def _validate_point_in_time_frame(
    frame: pd.DataFrame,
    *,
    entity_column: str,
    value_columns: tuple[str, ...],
) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    result["observation_time"] = _normalize_timestamp_column(result, "observation_time")
    result["available_time"] = _normalize_timestamp_column(result, "available_time")
    if (result["observation_time"] > result["available_time"]).any():
        raise ValueError("observation_time cannot be later than available_time")
    if entity_column not in result:
        raise ValueError(f"point-in-time data is missing {entity_column!r}")
    result[entity_column] = result[entity_column].astype(str).str.upper()
    if entity_column == "currency":
        invalid = ~result[entity_column].str.fullmatch(r"[A-Z]{3}")
        if invalid.any():
            raise ValueError("currency must contain three-letter ISO codes")
    else:
        result[entity_column] = result[entity_column].map(
            lambda value: CurrencyPair.parse(value).symbol
        )
    missing = set(value_columns) - set(result)
    if missing:
        raise ValueError(f"point-in-time data is missing values {sorted(missing)}")
    for column in value_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if not np.isfinite(result[column].dropna()).all():
            raise ValueError(f"point-in-time data contains invalid {column!r} values")
    if result.duplicated([entity_column, "available_time"]).any():
        raise ValueError(f"duplicate {entity_column}/available_time point-in-time rows")
    return result.sort_values([entity_column, "available_time", "observation_time"]).reset_index(
        drop=True
    )


def _validate_quality_metadata(
    frame: pd.DataFrame,
    *,
    metadata_columns: tuple[str, str, str],
    allowed_qualities: frozenset[str],
    allow_legacy_unverified: bool,
) -> pd.DataFrame:
    source_column, provenance_column, quality_column = metadata_columns
    result = frame.copy()
    missing = set(metadata_columns) - set(result)
    if missing and not allow_legacy_unverified:
        raise ValueError(
            "point-in-time carry data is missing per-row provenance metadata "
            f"{sorted(missing)}"
        )
    legacy_defaults = {
        source_column: "legacy_unspecified",
        provenance_column: "legacy_unverified",
        quality_column: "unknown_unverified",
    }
    for column in metadata_columns:
        if column not in result:
            result[column] = legacy_defaults[column]
        result[column] = result[column].astype("string").str.strip()
        if result[column].isna().any() or result[column].eq("").any():
            raise ValueError(f"point-in-time carry data contains blank {column!r}")
    result[quality_column] = result[quality_column].str.lower()
    invalid = ~result[quality_column].isin(allowed_qualities)
    if invalid.any():
        values = sorted(result.loc[invalid, quality_column].unique().tolist())
        raise ValueError(f"unsupported {quality_column} values: {values}")
    return result


def validate_currency_rates(
    frame: pd.DataFrame, *, allow_legacy_unverified: bool = False
) -> pd.DataFrame:
    """Validate rates; OIS values require their own row-level market provenance."""
    result = _validate_point_in_time_frame(
        frame,
        entity_column="currency",
        value_columns=RATE_COLUMNS,
    )
    result = _validate_quality_metadata(
        result,
        metadata_columns=RATE_METADATA_COLUMNS,
        allowed_qualities=OIS_QUOTE_QUALITIES,
        allow_legacy_unverified=allow_legacy_unverified,
    )
    result["_ois_row_historical_market"] = result["ois_quote_quality"].eq(
        HISTORICAL_MARKET_OIS_QUALITY
    ) & result[["ois_1m", "ois_3m"]].notna().all(axis=1)
    return result


def validate_forward_points(
    frame: pd.DataFrame, *, allow_legacy_unverified: bool = False
) -> pd.DataFrame:
    """Validate forwards; only sourced historical quotes qualify for promotion."""
    result = _validate_point_in_time_frame(
        frame,
        entity_column="symbol",
        value_columns=FORWARD_COLUMNS,
    )
    result = _validate_quality_metadata(
        result,
        metadata_columns=FORWARD_METADATA_COLUMNS,
        allowed_qualities=FORWARD_QUOTE_QUALITIES,
        allow_legacy_unverified=allow_legacy_unverified,
    )
    result["_forward_row_historical_market"] = result["quote_quality"].eq(
        HISTORICAL_MARKET_FORWARD_QUALITY
    ) & result[list(FORWARD_COLUMNS)].notna().all(axis=1)
    return result


def _verify_source_manifest(
    csv_path: Path,
    *,
    dataset_kind: str,
    frame: pd.DataFrame,
    metadata_columns: tuple[str, str, str],
) -> tuple[bool, str]:
    manifest_path = csv_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        return False, f"source manifest is missing at {manifest_path}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"invalid carry source manifest at {manifest_path}") from exc
    with csv_path.open("rb") as handle:
        actual_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual_hash != manifest.get("csv_sha256"):
        raise ValueError(f"{dataset_kind} CSV does not match its source manifest")
    if manifest.get("schema_version") != 1:
        return False, "source manifest schema_version must be 1"
    if manifest.get("dataset_kind") != dataset_kind:
        return False, f"source manifest dataset_kind must be {dataset_kind!r}"
    source_catalog = manifest.get("source_catalog")
    if not isinstance(source_catalog, list) or not source_catalog:
        return False, "source manifest must contain a non-empty source_catalog"
    source_column, provenance_column, quality_column = metadata_columns
    declared: set[tuple[str, str, str]] = set()
    for item in source_catalog:
        if not isinstance(item, dict):
            return False, "source_catalog entries must be objects"
        try:
            declared.add(
                (
                    str(item["source"]).strip(),
                    str(item["provenance"]).strip(),
                    str(item["quote_quality"]).strip().lower(),
                )
            )
        except KeyError:
            return False, "source_catalog entries require source/provenance/quote_quality"
    observed = set(
        frame[[source_column, provenance_column, quality_column]]
        .itertuples(index=False, name=None)
    )
    if not observed.issubset(declared):
        return False, "one or more row-level source/provenance/quality triples are undeclared"
    return True, "verified"


def _synthetic_point_in_time_data(
    data: Mapping[str, pd.DataFrame], config: PointInTimeConfig
) -> PointInTimeData:
    """Deterministic PIT fixtures for software validation, never empirical evidence."""
    generator = np.random.default_rng(config.synthetic_seed)
    symbols = sorted(data)
    pairs = [CurrencyPair.parse(symbol) for symbol in symbols]
    currencies = sorted({currency for pair in pairs for currency in (pair.base, pair.quote)})
    common = sorted(set().union(*(frame.index for frame in data.values())))
    release_times = common[::20]
    base_rates = {
        "USD": 3.0,
        "EUR": 1.5,
        "GBP": 2.5,
        "JPY": 0.1,
        "CHF": 0.5,
        "CAD": 2.0,
        "AUD": 2.2,
        "NZD": 2.4,
    }
    rate_rows: list[dict[str, object]] = []
    for currency_number, currency in enumerate(currencies):
        innovations = generator.normal(0, 0.03, len(release_times)).cumsum()
        for location, (timestamp, innovation) in enumerate(
            zip(release_times, innovations, strict=True)
        ):
            timestamp = pd.Timestamp(timestamp)
            policy = base_rates.get(currency, 1.0) + innovation
            rate_rows.append(
                {
                    "observation_time": timestamp,
                    "available_time": timestamp + timedelta(microseconds=1),
                    "currency": currency,
                    "policy_rate": policy,
                    "ois_1m": policy + 0.02 * np.sin((location + currency_number) / 4),
                    "ois_3m": policy + 0.05 * np.cos((location + currency_number) / 6),
                    "ois_source": "fx_system.synthetic_point_in_time",
                    "ois_provenance": f"software_fixture_seed:{config.synthetic_seed}",
                    "ois_quote_quality": "software_synthetic",
                }
            )
    rates = validate_currency_rates(pd.DataFrame(rate_rows))
    rate_lookup = pd.DataFrame(rate_rows).pivot(
        index="available_time", columns="currency", values="policy_rate"
    )
    forward_rows: list[dict[str, object]] = []
    for pair in pairs:
        frame = data[pair.symbol]
        for timestamp in release_times:
            timestamp = pd.Timestamp(timestamp)
            prior = frame.loc[frame.index <= timestamp, "close"]
            if prior.empty:
                continue
            available_time = timestamp + timedelta(microseconds=1)
            base_rate = float(rate_lookup.loc[available_time, pair.base]) / 100
            quote_rate = float(rate_lookup.loc[available_time, pair.quote]) / 100
            spot = float(prior.iloc[-1])
            one_month_points = -(base_rate - quote_rate) * spot * (30 / 365)
            forward_rows.append(
                {
                    "observation_time": timestamp,
                    "available_time": available_time,
                    "symbol": pair.symbol,
                    "forward_points_1m": one_month_points,
                    "forward_points_3m": one_month_points * 3,
                    "spot_reference": spot,
                    "source": "fx_system.synthetic_point_in_time",
                    "provenance": f"software_fixture_seed:{config.synthetic_seed}",
                    "quote_quality": "software_synthetic",
                }
            )
    forwards = validate_forward_points(pd.DataFrame(forward_rows))
    return PointInTimeData(rates, forwards, config.maximum_staleness_days)


def load_point_in_time_data(
    config: PointInTimeConfig,
    data: Mapping[str, pd.DataFrame] | None = None,
) -> PointInTimeData | None:
    if not config.enabled:
        return None
    if config.provider == "synthetic":
        if not data:
            raise ValueError("synthetic point-in-time data requires market data")
        return _synthetic_point_in_time_data(data, config)
    root = Path(config.directory)
    rates_path = root / config.currency_rates_file
    forwards_path = root / config.forward_points_file
    if not rates_path.exists():
        raise FileNotFoundError(f"No point-in-time currency rates found at {rates_path}")
    if not forwards_path.exists():
        raise FileNotFoundError(f"No point-in-time forward points found at {forwards_path}")
    rates = validate_currency_rates(
        pd.read_csv(rates_path),
        allow_legacy_unverified=config.allow_legacy_unverified_carry_rows,
    )
    forwards = validate_forward_points(
        pd.read_csv(forwards_path),
        allow_legacy_unverified=config.allow_legacy_unverified_carry_rows,
    )
    rates_manifest_verified, rates_manifest_reason = _verify_source_manifest(
        rates_path,
        dataset_kind="currency_rates",
        frame=rates,
        metadata_columns=RATE_METADATA_COLUMNS,
    )
    forwards_manifest_verified, forwards_manifest_reason = _verify_source_manifest(
        forwards_path,
        dataset_kind="forward_points",
        frame=forwards,
        metadata_columns=FORWARD_METADATA_COLUMNS,
    )
    if config.require_verified_carry_manifests and not rates_manifest_verified:
        raise ValueError(f"currency rates source manifest is not verified: {rates_manifest_reason}")
    if config.require_verified_carry_manifests and not forwards_manifest_verified:
        raise ValueError(
            f"forward points source manifest is not verified: {forwards_manifest_reason}"
        )
    positioning = None
    if config.positioning_enabled:
        positioning_path = root / config.currency_positioning_file
        if not positioning_path.exists():
            raise FileNotFoundError(
                f"No point-in-time currency positioning found at {positioning_path}"
            )
        manifest_path = positioning_path.with_suffix(".manifest.json")
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            with positioning_path.open("rb") as handle:
                actual_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual_hash != manifest.get("csv_sha256"):
                raise ValueError("currency positioning CSV does not match its source manifest")
        elif config.positioning_release_quality == "verified":
            raise FileNotFoundError(
                f"Verified positioning requires a source manifest at {manifest_path}"
            )
        positioning = validate_currency_positioning(pd.read_csv(positioning_path))
        if config.positioning_release_quality == "verified":
            quality = positioning.get("availability_quality")
            if quality is None or not quality.eq("verified_actual_publication").all():
                raise ValueError(
                    "Verified positioning requires per-row verified_actual_publication quality"
                )
            vintage_quality = positioning.get("value_vintage_quality")
            if vintage_quality is None or not vintage_quality.eq(
                "verified_as_published_vintage"
            ).all():
                raise ValueError(
                    "Verified positioning requires per-row verified as-published vintages; "
                    "a current revised historical archive is not point-in-time data"
                )
    return PointInTimeData(
        rates,
        forwards,
        config.maximum_staleness_days,
        positioning,
        config.maximum_positioning_staleness_days,
        rates_manifest_verified,
        forwards_manifest_verified,
    )


def _asof_entity_values(
    timestamps: pd.DatetimeIndex,
    frame: pd.DataFrame,
    entity_column: str,
    entity: str,
    value_columns: tuple[str, ...],
    maximum_staleness_days: int,
) -> pd.DataFrame:
    left = pd.DataFrame({"_feature_time": timestamps}).sort_values("_feature_time")
    available = frame.loc[frame[entity_column] == entity, ["available_time", *value_columns]].copy()
    if available.empty:
        return pd.DataFrame(index=timestamps, columns=value_columns, dtype=float)
    available = available.sort_values("available_time")
    merged = pd.merge_asof(
        left,
        available,
        left_on="_feature_time",
        right_on="available_time",
        direction="backward",
        tolerance=timedelta(days=maximum_staleness_days),
        allow_exact_matches=True,
    ).set_index("_feature_time")
    return merged[list(value_columns)].reindex(timestamps)


def build_carry_factors(
    symbol: str,
    frame: pd.DataFrame,
    point_in_time: PointInTimeData,
    periods_per_year: int,
) -> pd.DataFrame:
    """Build only-as-known-then carry factors aligned to close-of-bar timestamps."""
    pair = CurrencyPair.parse(symbol)
    staleness = point_in_time.maximum_staleness_days
    rate_asof_columns = (*RATE_COLUMNS, "_ois_row_historical_market")
    forward_asof_columns = (*FORWARD_COLUMNS, "_forward_row_historical_market")
    base = _asof_entity_values(
        frame.index,
        point_in_time.currency_rates,
        "currency",
        pair.base,
        rate_asof_columns,
        staleness,
    )
    quote = _asof_entity_values(
        frame.index,
        point_in_time.currency_rates,
        "currency",
        pair.quote,
        rate_asof_columns,
        staleness,
    )
    forwards = _asof_entity_values(
        frame.index,
        point_in_time.forward_points,
        "symbol",
        symbol,
        forward_asof_columns,
        staleness,
    )
    output = pd.DataFrame(index=frame.index)
    output["rate_differential"] = (base["policy_rate"] - quote["policy_rate"]) / 100
    base_slope = base["ois_3m"] - base["ois_1m"]
    quote_slope = quote["ois_3m"] - quote["ois_1m"]
    output["curve_slope_differential"] = (base_slope - quote_slope) / 100
    close = frame["close"].astype(float)
    output["forward_discount_1m"] = (
        -forwards["forward_points_1m"] / forwards["spot_reference"] * (365 / 30)
    )
    annualized_volatility = (
        np.log(close).diff().rolling(20, min_periods=20).std(ddof=0) * np.sqrt(periods_per_year)
    )
    output["carry_to_vol_20"] = output["rate_differential"] / annualized_volatility.replace(
        0, np.nan
    )
    output["_market_ois_verified"] = (
        base["_ois_row_historical_market"].astype("boolean").fillna(False)
        & quote["_ois_row_historical_market"].astype("boolean").fillna(False)
        & point_in_time.currency_rates_manifest_verified
    )
    output["_market_forward_verified"] = (
        forwards["_forward_row_historical_market"].astype("boolean").fillna(False)
        & point_in_time.forward_points_manifest_verified
    )
    positioning_columns = (
        "dealer_net_ratio",
        "asset_manager_net_ratio",
        "leveraged_money_net_ratio",
        "leveraged_change_4w",
        "leveraged_z_156",
    )

    def positioning_for(currency: str) -> pd.DataFrame:
        if currency == "USD":
            return pd.DataFrame(0.0, index=frame.index, columns=positioning_columns)
        if point_in_time.currency_positioning is None:
            return pd.DataFrame(np.nan, index=frame.index, columns=positioning_columns)
        weekly = point_in_time.currency_positioning.loc[
            point_in_time.currency_positioning["currency"] == currency
        ].copy()
        if weekly.empty:
            return pd.DataFrame(np.nan, index=frame.index, columns=positioning_columns)
        weekly = weekly.sort_values("available_time")
        leveraged = weekly["leveraged_money_net_ratio"]
        weekly["leveraged_change_4w"] = leveraged.diff(4)
        rolling_mean = leveraged.rolling(156, min_periods=52).mean()
        rolling_std = leveraged.rolling(156, min_periods=52).std(ddof=0).replace(0, np.nan)
        weekly["leveraged_z_156"] = (leveraged - rolling_mean) / rolling_std
        return _asof_entity_values(
            frame.index,
            weekly,
            "currency",
            currency,
            positioning_columns,
            point_in_time.maximum_positioning_staleness_days,
        )

    base_positioning = positioning_for(pair.base)
    quote_positioning = positioning_for(pair.quote)
    output["cftc_dealer_net"] = (
        base_positioning["dealer_net_ratio"] - quote_positioning["dealer_net_ratio"]
    )
    output["cftc_asset_manager_net"] = (
        base_positioning["asset_manager_net_ratio"]
        - quote_positioning["asset_manager_net_ratio"]
    )
    output["cftc_leveraged_net"] = (
        base_positioning["leveraged_money_net_ratio"]
        - quote_positioning["leveraged_money_net_ratio"]
    )
    output["cftc_leveraged_change_4w"] = (
        base_positioning["leveraged_change_4w"]
        - quote_positioning["leveraged_change_4w"]
    )
    output["cftc_leveraged_z_156"] = (
        base_positioning["leveraged_z_156"] - quote_positioning["leveraged_z_156"]
    )
    return output
