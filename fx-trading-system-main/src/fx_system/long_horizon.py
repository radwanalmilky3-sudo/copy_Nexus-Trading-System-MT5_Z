from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .cftc import validate_currency_positioning
from .long_horizon_config import LongHorizonConfig, LongHorizonSettings
from .models import CurrencyPair
from .reporting import data_fingerprint

LONG_HORIZON_IMPLEMENTATION_VERSION = "long-horizon-v6"

TIME_SERIES_EXCLUDED_FACTOR_FAMILIES = frozenset(
    {"currency_graph", "cross_sectional", "value_trend"}
)

REER_SERIES = {
    "USD": "RBUSBIS",
    "EUR": "RBXMBIS",
    "GBP": "RBGBBIS",
    "JPY": "RBJPBIS",
    "CHF": "RBCHBIS",
    "CAD": "RBCABIS",
    "AUD": "RBAUBIS",
    "NZD": "RBNZBIS",
}

RISK_SERIES = {
    "VIXCLS": "risk_vix",
    "DTWEXBGS": "risk_usd_index",
    "NFCI": "risk_nfci",
    "STLFSI4": "risk_stlfsi",
}

COMMODITY_CURRENCY_SERIES = {
    "CAD": ("WB_CRUDE_OIL_AVG", 1.0),
    "AUD": ("WB_COMMODITY_BASE_METALS", 1.0),
    "NZD": ("WB_COMMODITY_AGRICULTURE", 1.0),
    "JPY": ("WB_COMMODITY_ENERGY", -1.0),
}


@dataclass(frozen=True)
class LongHorizonFactorDefinition:
    name: str
    family: str
    directional: bool
    strict_eligibility: str
    description: str
    data_dependencies: tuple[str, ...] = ("price",)
    minimum_symbols: int = 1
    requires_graph_cycle: bool = False
    requires_cross_section: bool = False
    requires_external_data: bool = False
    price_only_eligible: bool = True


@dataclass
class LongHorizonBuildResult:
    daily_data: dict[str, pd.DataFrame]
    panel: pd.DataFrame
    dataset: pd.DataFrame
    catalog: pd.DataFrame
    folds: pd.DataFrame
    audit: dict[str, Any]
    external_files: list[Path]


def factor_definitions(settings: LongHorizonSettings) -> list[LongHorizonFactorDefinition]:
    definitions: list[LongHorizonFactorDefinition] = []

    def add(
        name: str,
        family: str,
        directional: bool,
        description: str,
        strict_eligibility: str = "price_history_required",
        *,
        data_dependencies: tuple[str, ...] = ("price",),
        minimum_symbols: int = 1,
        requires_graph_cycle: bool = False,
        requires_cross_section: bool = False,
        requires_external_data: bool = False,
    ) -> None:
        # Outcome-blind derivation: a factor is price-only eligible when it needs no
        # external data, no redundant currency-graph cycle, and no cross-sectional rank.
        # This reads only the factor's structural data dependencies, never any return,
        # IC, p-value or backtest result.
        price_only_eligible = not (
            requires_external_data or requires_graph_cycle or requires_cross_section
        )
        definitions.append(
            LongHorizonFactorDefinition(
                name,
                family,
                directional,
                strict_eligibility,
                description,
                data_dependencies=data_dependencies,
                minimum_symbols=minimum_symbols,
                requires_graph_cycle=requires_graph_cycle,
                requires_cross_section=requires_cross_section,
                requires_external_data=requires_external_data,
                price_only_eligible=price_only_eligible,
            )
        )

    for window in settings.momentum_windows:
        add(f"momentum_{window}d", "momentum", True, f"Trailing {window}-trading-day log return")
        add(
            f"currency_relative_{window}d",
            "currency_graph",
            True,
            f"Least-squares base-minus-quote currency strength over {window} trading days",
            data_dependencies=("price", "currency_graph"),
            minimum_symbols=3,
            requires_graph_cycle=True,
        )
    longest = max(settings.momentum_windows)
    add(
        f"momentum_{longest}d_skip_{settings.momentum_skip_days}d",
        "momentum",
        True,
        "Long-horizon momentum excluding the most recent configured trading days",
    )
    for window in settings.trend_windows:
        add(
            f"trend_tstat_{window}d",
            "trend",
            True,
            f"T-statistic of log price on time over {window} trading days",
        )
        add(
            f"ma_gap_{window}d",
            "trend",
            True,
            f"Close minus {window}-day mean normalized by trailing volatility",
        )
    for window in settings.volatility_windows:
        add(
            f"realized_vol_{window}d",
            "volatility",
            False,
            f"Annualized close-to-close volatility over {window} trading days",
        )
    add("vol_ratio_21_126", "volatility", False, "21-day to 126-day volatility ratio")
    add(
        "currency_dispersion_63d",
        "currency_graph",
        False,
        "Cross-currency dispersion of 63-day graph strengths",
        requires_graph_cycle=True,
        minimum_symbols=3,
    )
    add(
        "cross_sectional_momentum_252d_skip_21d",
        "cross_sectional",
        True,
        "Cross-pair percentile rank of 12-1 momentum",
        requires_cross_section=True,
        minimum_symbols=3,
    )
    for window in settings.reer_windows_months:
        add(
            f"reer_value_{window}m",
            "value",
            True,
            f"Base-minus-quote negative trailing {window}-month BIS REER z-score",
            "exploratory_current_vintage",
            data_dependencies=("price", "bis_reer"),
            requires_external_data=True,
        )
    add(
        "reer_change_12m",
        "value_state",
        True,
        "Base-minus-quote 12-month BIS REER change",
        "exploratory_current_vintage",
        data_dependencies=("price", "bis_reer"),
        requires_external_data=True,
    )
    for name, description in (
        ("cftc_dealer_net", "Base-minus-quote CFTC dealer net ratio"),
        ("cftc_asset_manager_net", "Base-minus-quote CFTC asset-manager net ratio"),
        ("cftc_leveraged_net", "Base-minus-quote CFTC leveraged-money net ratio"),
        ("cftc_leveraged_change_4w", "Four-week leveraged-position change difference"),
        ("cftc_leveraged_z_156", "Three-year leveraged-position z-score difference"),
    ):
        add(
            name,
            "positioning",
            True,
            description,
            "approximate_release_current_revised_archive",
            data_dependencies=("price", "cftc_positioning"),
            requires_external_data=True,
        )
    for name, description in (
        ("risk_vix_z_252", "VIX trailing 252-observation z-score"),
        ("risk_vix_change_21", "VIX 21-observation change"),
        ("risk_nfci", "Chicago Fed National Financial Conditions Index"),
        ("risk_stlfsi", "St. Louis Fed Financial Stress Index"),
    ):
        add(
            name,
            "risk",
            False,
            description,
            "exploratory_current_vintage",
            data_dependencies=("price", "fred_risk"),
            requires_external_data=True,
        )
    add(
        "global_fx_vol_21",
        "risk",
        False,
        "Median annualized 21-day volatility across pairs",
        data_dependencies=("price",),
        minimum_symbols=2,
    )
    add(
        "usd_index_momentum_63",
        "usd_regime",
        True,
        "Broad USD-index momentum signed by pair USD exposure",
        "exploratory_current_vintage",
        data_dependencies=("price", "fred_usd_index"),
        requires_external_data=True,
    )
    add(
        "overnight_rate_differential_public",
        "rate_reference",
        True,
        "Base-minus-quote free official overnight-reference rate differential",
        "exploratory_not_ois",
        data_dependencies=("official_rate_observations",),
        requires_external_data=True,
    )
    add(
        "policy_rate_differential_public",
        "rate_reference",
        True,
        "Base-minus-quote free official policy-rate differential where available",
        "exploratory_not_ois",
        data_dependencies=("official_rate_observations",),
        requires_external_data=True,
    )
    add(
        "commodity_currency_alignment_12m",
        "commodity",
        True,
        "Base-minus-quote preregistered commodity-currency exposure score",
        "exploratory_current_vintage",
        data_dependencies=("commodity_price_index",),
        requires_external_data=True,
    )
    add(
        "value_trend_agreement",
        "value_trend",
        True,
        "Equal-weight value and 12-1 momentum ranks when their signs agree",
        "exploratory_current_vintage",
        data_dependencies=("price", "bis_reer"),
        minimum_symbols=3,
        requires_cross_section=True,
        requires_external_data=True,
    )
    add(
        "positioning_crowding_reversal",
        "positioning_interaction",
        True,
        "Contrarian score when trend and leveraged positioning are crowded in one direction",
        "approximate_release_current_revised_archive",
        data_dependencies=("price", "cftc_positioning"),
        requires_external_data=True,
    )
    add(
        "global_policy_uncertainty_risk",
        "risk",
        False,
        "Five-year rolling z-score of log global economic policy uncertainty",
        "exploratory_current_vintage",
        data_dependencies=("global_policy_uncertainty",),
        requires_external_data=True,
    )
    add(
        "global_geopolitical_risk_state",
        "risk",
        False,
        "Five-year rolling z-score of log global geopolitical risk",
        "exploratory_current_vintage",
        data_dependencies=("geopolitical_risk_index",),
        requires_external_data=True,
    )
    add(
        "gscpi_risk_state_pit",
        "risk",
        False,
        "Latest released GSCPI level plus six-release change using preserved vintages",
        "verified_vintage_from_2022",
        data_dependencies=("gscpi_vintages",),
        requires_external_data=True,
    )
    return definitions


def _daily_aggregation(column: str) -> str:
    if column == "open" or column.endswith("_open"):
        return "first"
    if column == "high" or column.endswith("_high"):
        return "max"
    if column == "low" or column.endswith("_low"):
        return "min"
    if column in {"volume", "tick_count"}:
        return "sum"
    return "last"


def to_daily_market_data(data: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Convert bars to closed UTC-day observations without filling missing market days."""
    output: dict[str, pd.DataFrame] = {}
    for symbol, source in sorted(data.items()):
        if source.empty or "close" not in source:
            raise ValueError(f"{symbol}: long-horizon market data requires close prices")
        frame = source.sort_index().copy()
        if frame.index.tz is None:
            frame.index = frame.index.tz_localize("UTC")
        else:
            frame.index = frame.index.tz_convert("UTC")
        if frame.index.has_duplicates:
            raise ValueError(f"{symbol}: duplicate market timestamps")
        median_seconds = (
            float(frame.index.to_series().diff().dropna().dt.total_seconds().median())
            if len(frame) > 1
            else 86400.0
        )
        if median_seconds < 20 * 3600:
            aggregation = {column: _daily_aggregation(column) for column in frame.columns}
            frame = frame.resample("1D").agg(aggregation)
        frame = frame.dropna(subset=["close"])
        if len(frame) < 2 or (frame["close"] <= 0).any():
            raise ValueError(f"{symbol}: invalid daily close history")
        frame.attrs.update(source.attrs)
        frame.attrs["long_horizon_daily_conversion"] = True
        output[CurrencyPair.parse(symbol).symbol] = frame
    return output


def _trend_tstat(log_close: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    centered_x = x - x.mean()
    x_sum_squares = float(centered_x @ centered_x)

    def calculate(values: np.ndarray) -> float:
        if not np.isfinite(values).all():
            return float("nan")
        centered_y = values - values.mean()
        slope = float(centered_x @ centered_y) / x_sum_squares
        residuals = centered_y - slope * centered_x
        residual_variance = float(residuals @ residuals) / (window - 2)
        if residual_variance <= 1e-20:
            return 0.0
        return float(np.clip(slope / np.sqrt(residual_variance / x_sum_squares), -25, 25))

    return log_close.rolling(window, min_periods=window).apply(calculate, raw=True)


def _currency_graph_features(
    data: Mapping[str, pd.DataFrame], windows: list[int]
) -> dict[str, pd.DataFrame]:
    symbols = sorted(data)
    pairs = [CurrencyPair.parse(symbol) for symbol in symbols]
    currencies = sorted({item for pair in pairs for item in (pair.base, pair.quote)})
    currency_index = {currency: location for location, currency in enumerate(currencies)}
    incidence = np.zeros((len(symbols), len(currencies)))
    for row, pair in enumerate(pairs):
        incidence[row, currency_index[pair.base]] = 1
        incidence[row, currency_index[pair.quote]] = -1
    if np.linalg.matrix_rank(incidence) != len(currencies) - 1:
        raise ValueError("FX symbol graph is disconnected; currency strengths are unidentified")
    pseudo_inverse = np.linalg.pinv(incidence)
    closes = pd.concat({symbol: data[symbol]["close"] for symbol in symbols}, axis=1).sort_index()
    closes = closes.ffill(limit=1)
    log_closes = np.log(closes)
    output = {symbol: pd.DataFrame(index=data[symbol].index) for symbol in symbols}
    for window in windows:
        pair_returns = log_closes.diff(window)
        strengths = pair_returns.to_numpy() @ pseudo_inverse.T
        strength_frame = pd.DataFrame(strengths, index=pair_returns.index, columns=currencies)
        dispersion = strength_frame.std(axis=1, ddof=0)
        for symbol, pair in zip(symbols, pairs, strict=True):
            target = data[symbol].index
            output[symbol][f"currency_relative_{window}d"] = (
                strength_frame[pair.base] - strength_frame[pair.quote]
            ).reindex(target)
            if window == 63:
                output[symbol]["currency_dispersion_63d"] = dispersion.reindex(target)
    return output


def _read_fred_series(path: Path, series_id: str) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float, name=series_id)
    frame = pd.read_csv(path)
    if list(frame.columns) != ["observation_date", series_id]:
        raise ValueError(f"{path}: unexpected FRED schema")
    index = pd.to_datetime(frame["observation_date"], utc=True, errors="coerce")
    values = pd.to_numeric(frame[series_id], errors="coerce")
    if index.isna().any() or values.notna().sum() == 0:
        raise ValueError(f"{path}: invalid or empty FRED observations")
    series = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(index), name=series_id)
    if series.index.has_duplicates or not series.index.is_monotonic_increasing:
        raise ValueError(f"{path}: FRED dates must be unique and sorted")
    return series


def _asof_frame(
    timestamps: pd.DatetimeIndex,
    source: pd.DataFrame,
    columns: list[str],
    maximum_staleness_days: int,
) -> pd.DataFrame:
    if source.empty:
        return pd.DataFrame(index=timestamps, columns=columns, dtype=float)
    left = pd.DataFrame({"_feature_time": timestamps}).sort_values("_feature_time")
    right = source[["available_time", *columns]].sort_values("available_time")
    merged = pd.merge_asof(
        left,
        right,
        left_on="_feature_time",
        right_on="available_time",
        direction="backward",
        tolerance=timedelta(days=maximum_staleness_days),
        allow_exact_matches=True,
    ).set_index("_feature_time")
    return merged[columns].reindex(timestamps)


def _load_reer(
    config: LongHorizonConfig,
) -> tuple[dict[str, pd.DataFrame], list[Path]]:
    output: dict[str, pd.DataFrame] = {}
    files: list[Path] = []
    for currency, series_id in REER_SERIES.items():
        path = config.external.raw_directory / "fred" / "value" / f"{series_id}.csv"
        series = _read_fred_series(path, series_id)
        if series.empty:
            output[currency] = pd.DataFrame()
            continue
        files.append(path)
        frame = pd.DataFrame({"reer": series})
        for window in config.research.reer_windows_months:
            minimum = max(24, int(np.ceil(window * 2 / 3)))
            mean = frame["reer"].rolling(window, min_periods=minimum).mean()
            std = frame["reer"].rolling(window, min_periods=minimum).std(ddof=0)
            frame[f"reer_value_{window}m"] = -(frame["reer"] - mean) / std.replace(0, np.nan)
        frame["reer_change_12m"] = np.log(frame["reer"]).diff(12)
        frame["available_time"] = frame.index + timedelta(
            days=config.external.reer_release_lag_days
        )
        output[currency] = frame.reset_index(names="observation_time")
    return output, files


def _load_positioning(
    config: LongHorizonConfig,
) -> tuple[dict[str, pd.DataFrame], list[Path]]:
    path = config.external.cftc_file
    if not path.exists():
        return {}, []
    positioning = validate_currency_positioning(pd.read_csv(path))
    output: dict[str, pd.DataFrame] = {}
    for currency, group in positioning.groupby("currency", sort=True):
        weekly = group.sort_values("available_time").copy()
        leveraged = weekly["leveraged_money_net_ratio"]
        weekly["leveraged_change_4w"] = leveraged.diff(4)
        mean = leveraged.rolling(156, min_periods=52).mean()
        std = leveraged.rolling(156, min_periods=52).std(ddof=0)
        weekly["leveraged_z_156"] = (leveraged - mean) / std.replace(0, np.nan)
        output[str(currency)] = weekly
    return output, [path]


def _load_risk(
    config: LongHorizonConfig,
) -> tuple[dict[str, tuple[pd.DataFrame, int]], list[Path]]:
    root = config.external.raw_directory / "fred" / "risk"
    output: dict[str, tuple[pd.DataFrame, int]] = {}
    files: list[Path] = []
    for series_id in RISK_SERIES:
        path = root / f"{series_id}.csv"
        series = _read_fred_series(path, series_id)
        if series.empty:
            continue
        files.append(path)
        frame = pd.DataFrame({"value": series}).dropna()
        if series_id == "VIXCLS":
            mean = frame["value"].rolling(252, min_periods=126).mean()
            std = frame["value"].rolling(252, min_periods=126).std(ddof=0)
            frame["risk_vix_z_252"] = (frame["value"] - mean) / std.replace(0, np.nan)
            frame["risk_vix_change_21"] = frame["value"].diff(21)
            columns = ["risk_vix_z_252", "risk_vix_change_21"]
            lag = config.external.risk_daily_release_lag_days
        elif series_id == "DTWEXBGS":
            frame["usd_index_momentum_63"] = np.log(frame["value"]).diff(63)
            columns = ["usd_index_momentum_63"]
            lag = config.external.risk_daily_release_lag_days
        elif series_id == "NFCI":
            frame["risk_nfci"] = frame["value"]
            columns = ["risk_nfci"]
            lag = config.external.risk_weekly_release_lag_days
        else:
            frame["risk_stlfsi"] = frame["value"]
            columns = ["risk_stlfsi"]
            lag = config.external.risk_weekly_release_lag_days
        frame["available_time"] = frame.index + timedelta(days=lag)
        output[series_id] = (frame.reset_index(names="observation_time"), lag)
        output[series_id][0].attrs["factor_columns"] = columns
    return output, files


def _load_official_rates(
    config: LongHorizonConfig,
) -> tuple[dict[str, pd.DataFrame], list[Path]]:
    path = config.external.official_rates_file
    if not path.exists():
        return {}, []
    frame = pd.read_csv(path)
    required = {
        "observation_time",
        "available_time",
        "currency",
        "series_id",
        "rate_percent",
        "series_role",
        "quality",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"official rate observations are missing {sorted(missing)}")
    for column in ("observation_time", "available_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        if frame[column].isna().any():
            raise ValueError(f"official rate observations contain invalid {column}")
    frame["rate_percent"] = pd.to_numeric(frame["rate_percent"], errors="coerce")
    if frame["rate_percent"].isna().any() or not np.isfinite(frame["rate_percent"]).all():
        raise ValueError("official rate observations contain invalid rates")
    frame["currency"] = frame["currency"].astype(str).str.upper()
    output: dict[str, pd.DataFrame] = {}
    for currency, currency_rows in frame.groupby("currency", sort=True):
        parts: list[pd.DataFrame] = []
        for role, target in (
            ("overnight_reference", "overnight_rate_percent"),
            ("policy_rate", "policy_rate_percent"),
        ):
            selected = currency_rows.loc[currency_rows["series_role"] == role].copy()
            if selected.empty:
                continue
            selected = selected.sort_values(["available_time", "observation_time", "series_id"])
            selected = selected.drop_duplicates("available_time", keep="last")
            selected = selected[["observation_time", "available_time", "rate_percent"]].rename(
                columns={"rate_percent": target}
            )
            parts.append(selected)
        if not parts:
            continue
        combined = parts[0]
        for part in parts[1:]:
            combined = pd.merge(
                combined,
                part,
                on=["observation_time", "available_time"],
                how="outer",
            )
        combined = combined.sort_values("available_time")
        for target in ("overnight_rate_percent", "policy_rate_percent"):
            if target not in combined:
                combined[target] = np.nan
        combined[["overnight_rate_percent", "policy_rate_percent"]] = combined[
            ["overnight_rate_percent", "policy_rate_percent"]
        ].ffill()
        output[str(currency)] = combined
    return output, [path]


def _rolling_zscore(values: pd.Series, window: int, minimum: int) -> pd.Series:
    mean = values.rolling(window, min_periods=minimum).mean()
    scale = values.rolling(window, min_periods=minimum).std(ddof=0).replace(0, np.nan)
    return (values - mean) / scale


def _load_supplemental(
    config: LongHorizonConfig,
) -> tuple[dict[str, pd.DataFrame], list[Path]]:
    sources: dict[str, pd.DataFrame] = {}
    files: list[Path] = []
    path = config.external.supplemental_file
    if path.exists():
        frame = pd.read_csv(path)
        required = {
            "observation_time",
            "available_time",
            "series_id",
            "value",
            "quality",
        }
        missing = required - set(frame)
        if missing:
            raise ValueError(f"supplemental observations are missing {sorted(missing)}")
        for column in ("observation_time", "available_time"):
            frame[column] = pd.to_datetime(
                frame[column], utc=True, errors="coerce", format="mixed"
            )
            if frame[column].isna().any():
                raise ValueError(f"supplemental observations contain invalid {column}")
        if not (frame["available_time"] > frame["observation_time"]).all():
            raise ValueError("supplemental observations violate availability ordering")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        if frame["value"].isna().any() or not np.isfinite(frame["value"]).all():
            raise ValueError("supplemental observations contain invalid values")
        if frame.duplicated(["observation_time", "series_id"]).any():
            raise ValueError("supplemental observations contain duplicate series keys")
        files.append(path)
        definitions = {
            "GEPU_CURRENT": "global_policy_uncertainty_risk",
            "GPR_GLOBAL": "global_geopolitical_risk_state",
        }
        for series_id, target in definitions.items():
            selected = frame.loc[frame["series_id"] == series_id].sort_values(
                "observation_time"
            ).reset_index(drop=True)
            if selected.empty:
                continue
            transformed = np.log1p(selected["value"].clip(lower=0))
            selected = selected[["observation_time", "available_time"]].copy()
            selected[target] = _rolling_zscore(transformed.reset_index(drop=True), 60, 36)
            sources[target] = selected
        for series_id, _sign in COMMODITY_CURRENCY_SERIES.values():
            selected = frame.loc[frame["series_id"] == series_id].sort_values(
                "observation_time"
            ).reset_index(drop=True)
            if selected.empty:
                continue
            values = selected["value"].reset_index(drop=True)
            momentum = np.log(values.where(values > 0)).diff(12)
            target = f"commodity__{series_id}"
            selected = selected[["observation_time", "available_time"]].copy()
            selected[target] = _rolling_zscore(momentum, 60, 36)
            sources[target] = selected

    vintage_path = config.external.gscpi_vintages_file
    if vintage_path.exists():
        vintages = pd.read_csv(vintage_path)
        required = {
            "observation_time",
            "available_time",
            "vintage_label",
            "series_id",
            "value",
            "quality",
        }
        missing = required - set(vintages)
        if missing:
            raise ValueError(f"GSCPI vintages are missing {sorted(missing)}")
        for column in ("observation_time", "available_time"):
            vintages[column] = pd.to_datetime(
                vintages[column], utc=True, errors="coerce", format="mixed"
            )
            if vintages[column].isna().any():
                raise ValueError(f"GSCPI vintages contain invalid {column}")
        vintages["value"] = pd.to_numeric(vintages["value"], errors="coerce")
        if vintages["value"].isna().any() or not np.isfinite(vintages["value"]).all():
            raise ValueError("GSCPI vintages contain invalid values")
        if not (vintages["observation_time"] < vintages["available_time"]).all():
            raise ValueError("GSCPI vintages violate availability ordering")
        key = ["observation_time", "available_time", "series_id"]
        if vintages.duplicated(key).any():
            raise ValueError("GSCPI vintages contain duplicate keys")
        latest = (
            vintages.sort_values(["available_time", "observation_time"])
            .groupby("available_time", as_index=False, sort=True)
            .tail(1)
            .sort_values("available_time")
        )
        latest["gscpi_risk_state_pit"] = latest["value"] + latest["value"].diff(6)
        sources["gscpi_risk_state_pit"] = latest[
            ["observation_time", "available_time", "gscpi_risk_state_pit"]
        ]
        files.append(vintage_path)
    return sources, files


def _currency_external_values(
    currency: str,
    timestamps: pd.DatetimeIndex,
    sources: dict[str, pd.DataFrame],
    columns: list[str],
    staleness_days: int,
    *,
    usd_zero: bool,
) -> pd.DataFrame:
    if usd_zero and currency == "USD":
        return pd.DataFrame(0.0, index=timestamps, columns=columns)
    source = sources.get(currency, pd.DataFrame())
    return _asof_frame(timestamps, source, columns, staleness_days)


def _external_pair_features(
    symbol: str,
    timestamps: pd.DatetimeIndex,
    config: LongHorizonConfig,
    reer: dict[str, pd.DataFrame],
    positioning: dict[str, pd.DataFrame],
    risk: dict[str, tuple[pd.DataFrame, int]],
    official_rates: dict[str, pd.DataFrame],
    supplemental: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    pair = CurrencyPair.parse(symbol)
    output = pd.DataFrame(index=timestamps)
    reer_columns = [
        *(f"reer_value_{window}m" for window in config.research.reer_windows_months),
        "reer_change_12m",
    ]
    base_reer = _currency_external_values(
        pair.base,
        timestamps,
        reer,
        reer_columns,
        config.external.reer_maximum_staleness_days,
        usd_zero=False,
    )
    quote_reer = _currency_external_values(
        pair.quote,
        timestamps,
        reer,
        reer_columns,
        config.external.reer_maximum_staleness_days,
        usd_zero=False,
    )
    for column in reer_columns:
        output[column] = base_reer[column] - quote_reer[column]

    positioning_source_columns = [
        "dealer_net_ratio",
        "asset_manager_net_ratio",
        "leveraged_money_net_ratio",
        "leveraged_change_4w",
        "leveraged_z_156",
    ]
    base_positioning = _currency_external_values(
        pair.base,
        timestamps,
        positioning,
        positioning_source_columns,
        config.external.positioning_maximum_staleness_days,
        usd_zero=True,
    )
    quote_positioning = _currency_external_values(
        pair.quote,
        timestamps,
        positioning,
        positioning_source_columns,
        config.external.positioning_maximum_staleness_days,
        usd_zero=True,
    )
    positioning_names = {
        "dealer_net_ratio": "cftc_dealer_net",
        "asset_manager_net_ratio": "cftc_asset_manager_net",
        "leveraged_money_net_ratio": "cftc_leveraged_net",
        "leveraged_change_4w": "cftc_leveraged_change_4w",
        "leveraged_z_156": "cftc_leveraged_z_156",
    }
    for source_column, factor_name in positioning_names.items():
        output[factor_name] = (
            base_positioning[source_column] - quote_positioning[source_column]
        )

    for column in (
        "risk_vix_z_252",
        "risk_vix_change_21",
        "risk_nfci",
        "risk_stlfsi",
        "usd_index_momentum_63",
    ):
        output[column] = np.nan
    for series_id, (source, _lag) in risk.items():
        columns = list(source.attrs.get("factor_columns", []))
        aligned = _asof_frame(
            timestamps,
            source,
            columns,
            config.external.risk_maximum_staleness_days,
        )
        for column in columns:
            if series_id == "DTWEXBGS":
                usd_exposure = int(pair.base == "USD") - int(pair.quote == "USD")
                output[column] = aligned[column] * usd_exposure
            else:
                output[column] = aligned[column]
    rate_columns = ["overnight_rate_percent", "policy_rate_percent"]
    base_rates = _currency_external_values(
        pair.base,
        timestamps,
        official_rates,
        rate_columns,
        config.external.rate_reference_maximum_staleness_days,
        usd_zero=False,
    )
    quote_rates = _currency_external_values(
        pair.quote,
        timestamps,
        official_rates,
        rate_columns,
        config.external.rate_reference_maximum_staleness_days,
        usd_zero=False,
    )
    output["overnight_rate_differential_public"] = (
        base_rates["overnight_rate_percent"] - quote_rates["overnight_rate_percent"]
    ) / 100
    output["policy_rate_differential_public"] = (
        base_rates["policy_rate_percent"] - quote_rates["policy_rate_percent"]
    ) / 100
    for factor_name in (
        "global_policy_uncertainty_risk",
        "global_geopolitical_risk_state",
    ):
        source = supplemental.get(factor_name, pd.DataFrame())
        output[factor_name] = _asof_frame(
            timestamps,
            source,
            [factor_name],
            config.external.supplemental_maximum_staleness_days,
        )[factor_name]
    gscpi_source = supplemental.get("gscpi_risk_state_pit", pd.DataFrame())
    output["gscpi_risk_state_pit"] = _asof_frame(
        timestamps,
        gscpi_source,
        ["gscpi_risk_state_pit"],
        config.external.gscpi_maximum_staleness_days,
    )["gscpi_risk_state_pit"]

    def commodity_currency_score(currency: str) -> pd.Series:
        definition = COMMODITY_CURRENCY_SERIES.get(currency)
        if definition is None:
            return pd.Series(0.0, index=timestamps)
        series_id, sign = definition
        target = f"commodity__{series_id}"
        source = supplemental.get(target, pd.DataFrame())
        aligned = _asof_frame(
            timestamps,
            source,
            [target],
            config.external.supplemental_maximum_staleness_days,
        )
        return aligned[target] * sign

    output["commodity_currency_alignment_12m"] = commodity_currency_score(
        pair.base
    ) - commodity_currency_score(pair.quote)
    return output


def build_long_horizon_panel(
    data: Mapping[str, pd.DataFrame], config: LongHorizonConfig
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, list[Path]]:
    daily = to_daily_market_data(data)
    graph = _currency_graph_features(daily, config.research.momentum_windows)
    if config.external.enabled:
        reer, reer_files = _load_reer(config)
        positioning, positioning_files = _load_positioning(config)
        risk, risk_files = _load_risk(config)
        official_rates, rate_files = _load_official_rates(config)
        supplemental, supplemental_files = _load_supplemental(config)
        external_files = [
            *reer_files,
            *positioning_files,
            *risk_files,
            *rate_files,
            *supplemental_files,
        ]
    else:
        reer, positioning, risk, official_rates, supplemental, external_files = (
            {},
            {},
            {},
            {},
            {},
            [],
        )

    pair_volatility = pd.concat(
        {
            symbol: np.log(frame["close"]).diff().rolling(21, min_periods=21).std(ddof=0)
            * np.sqrt(260)
            for symbol, frame in daily.items()
        },
        axis=1,
    )
    global_fx_volatility = pair_volatility.median(axis=1, skipna=True)
    panels: list[pd.DataFrame] = []
    for symbol, frame in sorted(daily.items()):
        close = frame["close"].astype(float)
        log_close = np.log(close)
        returns = log_close.diff()
        factors = pd.DataFrame(index=frame.index)
        for window in config.research.momentum_windows:
            factors[f"momentum_{window}d"] = log_close.diff(window)
        longest = max(config.research.momentum_windows)
        skip = config.research.momentum_skip_days
        factors[f"momentum_{longest}d_skip_{skip}d"] = log_close.shift(skip) - log_close.shift(
            longest
        )
        for window in config.research.trend_windows:
            factors[f"trend_tstat_{window}d"] = _trend_tstat(log_close, window)
            mean = close.rolling(window, min_periods=window).mean()
            scale = returns.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(window)
            factors[f"ma_gap_{window}d"] = np.log(close / mean) / scale.replace(0, np.nan)
        for window in config.research.volatility_windows:
            factors[f"realized_vol_{window}d"] = (
                returns.rolling(window, min_periods=window).std(ddof=0) * np.sqrt(260)
            )
        if {21, 126}.issubset(config.research.volatility_windows):
            factors["vol_ratio_21_126"] = factors["realized_vol_21d"] / factors[
                "realized_vol_126d"
            ].replace(0, np.nan)
        else:
            factors["vol_ratio_21_126"] = np.nan
        factors = factors.join(graph[symbol])
        factors["global_fx_vol_21"] = global_fx_volatility.reindex(frame.index)
        factors = factors.join(
            _external_pair_features(
                symbol,
                frame.index,
                config,
                reer,
                positioning,
                risk,
                official_rates,
                supplemental,
            )
        )
        factors["_close"] = close
        factors["_symbol"] = symbol
        factors.index.name = "_feature_time"
        panels.append(factors.reset_index())
    panel = pd.concat(panels, ignore_index=True)
    rank_source = (
        f"momentum_{max(config.research.momentum_windows)}d_"
        f"skip_{config.research.momentum_skip_days}d"
    )
    panel["cross_sectional_momentum_252d_skip_21d"] = (
        2
        * panel.groupby("_feature_time")[rank_source].rank(
            method="average", pct=True, na_option="keep"
        )
        - 1
    )
    value_rank = (
        2
        * panel.groupby("_feature_time")["reer_value_60m"].rank(
            method="average", pct=True, na_option="keep"
        )
        - 1
    )
    trend_rank = (
        2
        * panel.groupby("_feature_time")[rank_source].rank(
            method="average", pct=True, na_option="keep"
        )
        - 1
    )
    agreement = np.sign(value_rank) == np.sign(trend_rank)
    panel["value_trend_agreement"] = ((value_rank + trend_rank) / 2).where(
        agreement, 0.0
    ).where(value_rank.notna() & trend_rank.notna())
    crowded = (
        np.sign(panel["momentum_63d"]) == np.sign(panel["cftc_leveraged_z_156"])
    ) & (panel["cftc_leveraged_z_156"].abs() >= 1)
    panel["positioning_crowding_reversal"] = (
        -np.sign(panel["momentum_63d"]) * panel["cftc_leveraged_z_156"].abs()
    ).where(crowded, 0.0).where(
        panel["momentum_63d"].notna() & panel["cftc_leveraged_z_156"].notna()
    )
    panel["_feature_time"] = pd.to_datetime(panel["_feature_time"], utc=True)
    return (
        daily,
        panel.sort_values(["_feature_time", "_symbol"]).reset_index(drop=True),
        sorted(set(external_files)),
    )


def build_long_horizon_labels(
    panel: pd.DataFrame,
    daily_data: Mapping[str, pd.DataFrame],
    settings: LongHorizonSettings,
) -> pd.DataFrame:
    datasets: list[pd.DataFrame] = []
    for symbol, frame in sorted(daily_data.items()):
        factors = panel.loc[panel["_symbol"] == symbol].set_index("_feature_time")
        factors = factors.reindex(frame.index)
        result = factors.copy()
        feature_time = pd.Series(frame.index, index=frame.index)
        if "session_open_quote_time" in frame:
            entry_times = pd.to_datetime(
                frame["session_open_quote_time"], utc=True, errors="coerce"
            )
        else:
            entry_times = pd.Series(frame.index, index=frame.index)
        result["_entry_time"] = entry_times.shift(-1)
        # Fail closed BEFORE any outcome is computed: the entry (next open) must
        # be strictly later than the feature time (signal before next open).
        _enforce_entry_after_feature(symbol, feature_time, result["_entry_time"])
        mid_entry = frame["open"].shift(-1) if "open" in frame else frame["close"].shift(-1)
        long_entry = frame["ask_open"].shift(-1) if "ask_open" in frame else mid_entry
        short_entry = frame["bid_open"].shift(-1) if "bid_open" in frame else mid_entry
        if "session_close_quote_time" in frame:
            close_times = pd.to_datetime(
                frame["session_close_quote_time"], utc=True, errors="coerce"
            )
        else:
            close_times = pd.Series(frame.index, index=frame.index)
        for horizon in settings.horizons:
            exit_time = close_times.shift(-horizon)
            # Fail closed BEFORE computing this horizon's return: the label end
            # must be strictly later than the entry.
            _enforce_label_end_after_entry(symbol, result["_entry_time"], exit_time, horizon)
            mid_exit = frame["close"].shift(-horizon)
            long_exit = frame["bid_close"].shift(-horizon) if "bid_close" in frame else mid_exit
            short_exit = frame["ask_close"].shift(-horizon) if "ask_close" in frame else mid_exit
            result[f"_label_end_time_{horizon}d"] = exit_time
            result[f"_forward_mid_return_{horizon}d"] = np.log(mid_exit / mid_entry)
            result[f"_forward_long_return_{horizon}d"] = np.log(long_exit / long_entry)
            result[f"_forward_short_return_{horizon}d"] = np.log(short_entry / short_exit)
        result["_symbol"] = symbol
        result.index.name = "_feature_time"
        datasets.append(result.reset_index())
    dataset = pd.concat(datasets, ignore_index=True)
    dates = pd.Index(sorted(dataset["_feature_time"].dropna().unique()))
    eligible_dates = set(dates[:: settings.rebalance_interval_days])
    dataset["_rebalance_eligible"] = dataset["_feature_time"].isin(eligible_dates)
    return dataset.sort_values(["_feature_time", "_symbol"]).reset_index(drop=True)


def _enforce_entry_after_feature(
    symbol: str,
    feature_time: pd.Series,
    entry_time: pd.Series,
) -> None:
    """Halt before any outcome is opened if entry is not strictly after feature."""
    feature = pd.to_datetime(feature_time, utc=True, errors="coerce")
    entry = pd.to_datetime(entry_time, utc=True, errors="coerce")
    bad = feature.notna() & entry.notna() & (entry <= feature)
    if bad.any():
        idx = bad[bad].index[:5]
        sample = ", ".join(
            f"{feature.loc[i]} -> entry {entry.loc[i]}" for i in idx
        )
        raise ValueError(
            f"{symbol}: label temporal order violated before outcome computation: "
            f"_entry_time must be strictly after _feature_time ({int(bad.sum())} rows). "
            f"sample: {sample}"
        )


def _enforce_label_end_after_entry(
    symbol: str,
    entry_time: pd.Series,
    exit_time: pd.Series,
    horizon: int,
) -> None:
    """Halt before computing a horizon's return if its label end is not after entry."""
    entry = pd.to_datetime(entry_time, utc=True, errors="coerce")
    exit_t = pd.to_datetime(exit_time, utc=True, errors="coerce")
    bad = entry.notna() & exit_t.notna() & (exit_t <= entry)
    if bad.any():
        idx = bad[bad].index[:5]
        sample = ", ".join(
            f"entry {entry.loc[i]} -> end {exit_t.loc[i]}" for i in idx
        )
        raise ValueError(
            f"{symbol}: label temporal order violated before outcome computation: "
            f"_label_end_time_{horizon}d must be strictly after _entry_time "
            f"({int(bad.sum())} rows). sample: {sample}"
        )


def build_long_horizon_folds(
    dataset: pd.DataFrame, settings: LongHorizonSettings
) -> pd.DataFrame:
    maximum = settings.maximum_horizon
    label_end = f"_label_end_time_{maximum}d"
    complete = dataset.loc[dataset[label_end].notna()].copy()
    if complete.empty:
        return pd.DataFrame()
    first_date = pd.Timestamp(complete["_feature_time"].min())
    last_date = pd.Timestamp(complete["_feature_time"].max())
    test_start = first_date + pd.DateOffset(years=settings.train_years)
    rows: list[dict[str, object]] = []
    fold = 0
    while test_start + pd.DateOffset(years=settings.test_years) <= last_date:
        test_end = test_start + pd.DateOffset(years=settings.test_years)
        train_start = test_start - pd.DateOffset(years=settings.train_years)
        raw_train = complete.loc[
            (complete["_feature_time"] >= train_start)
            & (complete["_feature_time"] < test_start)
        ]
        train = raw_train.loc[raw_train[label_end] < test_start]
        test = complete.loc[
            (complete["_feature_time"] >= test_start)
            & (complete["_feature_time"] < test_end)
        ]
        if not train.empty and not test.empty:
            rows.append(
                {
                    "fold": fold,
                    "train_start": train_start,
                    "train_end_exclusive": test_start,
                    "test_start": test_start,
                    "test_end_exclusive": test_end,
                    "train_rows": len(train),
                    "purged_train_rows": len(raw_train) - len(train),
                    "test_rows": len(test),
                    "train_rebalance_rows": int(train["_rebalance_eligible"].sum()),
                    "test_rebalance_rows": int(test["_rebalance_eligible"].sum()),
                }
            )
            fold += 1
        test_start += pd.DateOffset(years=settings.step_years)
    return pd.DataFrame(rows)


def audit_long_horizon_data(
    daily_data: Mapping[str, pd.DataFrame],
    panel: pd.DataFrame,
    dataset: pd.DataFrame,
    catalog: pd.DataFrame,
    folds: pd.DataFrame,
    config: LongHorizonConfig,
    external_files: list[Path],
) -> dict[str, Any]:
    history_years = {
        symbol: float((frame.index[-1] - frame.index[0]).days / 365.25)
        for symbol, frame in daily_data.items()
    }
    timestamp_sets = [set(frame.index.asi8) for frame in daily_data.values()]
    union = set().union(*timestamp_sets)
    common = set.intersection(*timestamp_sets) if timestamp_sets else set()
    expected_per_year = 260
    coverage = {
        symbol: min(1.0, len(frame) / max(history_years[symbol] * expected_per_year, 1))
        for symbol, frame in daily_data.items()
    }
    factor_names = catalog["name"].tolist()
    factor_coverage = {
        factor: float(panel[factor].replace([np.inf, -np.inf], np.nan).notna().mean())
        for factor in factor_names
    }
    label_coverage = {
        f"{horizon}d": float(dataset[f"_forward_mid_return_{horizon}d"].notna().mean())
        for horizon in config.research.horizons
    }
    maximum = config.research.maximum_horizon
    complete = dataset[f"_label_end_time_{maximum}d"].notna() & dataset[
        "_entry_time"
    ].notna()
    temporal_order_valid = bool(
        (
            dataset.loc[complete, "_entry_time"]
            > dataset.loc[complete, "_feature_time"]
        ).all()
        and (
            dataset.loc[complete, f"_label_end_time_{maximum}d"]
            > dataset.loc[complete, "_entry_time"]
        ).all()
    )
    strict_factors = catalog.loc[
        catalog["strict_eligibility"] == "price_history_required", "name"
    ].tolist()
    minimum_strict_coverage = min(
        (factor_coverage[name] for name in strict_factors), default=0.0
    )
    allowed_execution_sources = {"dukascopy", "oanda_fxpractice"}
    source_provider = {
        symbol: frame.attrs.get("source_provider") for symbol, frame in daily_data.items()
    }
    source_manifest_complete = {
        symbol: bool(frame.attrs.get("source_manifest_complete", False))
        for symbol, frame in daily_data.items()
    }
    source_failed_hours = {
        symbol: int(frame.attrs.get("source_failed_hours", 0))
        for symbol, frame in daily_data.items()
    }
    csv_hash_verified = {
        symbol: bool(
            frame.attrs.get("source_csv_hash_verified", config.data.provider != "csv")
        )
        for symbol, frame in daily_data.items()
    }
    manifest_schema_valid = {
        symbol: (
            int(frame.attrs.get("source_manifest_schema_version", 0)) >= 2
            if config.data.provider == "csv"
            else True
        )
        for symbol, frame in daily_data.items()
    }
    sources_are_execution_grade = all(
        provider in allowed_execution_sources for provider in source_provider.values()
    )
    empirical_ready = (
        config.data.provider in {"dukascopy", "oanda", "csv"}
        and sources_are_execution_grade
        and config.data.price_mode == "bid_ask"
        and all(source_manifest_complete.values())
        and sum(source_failed_hours.values()) == 0
        and all(csv_hash_verified.values())
        and all(manifest_schema_valid.values())
        and len(folds) >= config.research.minimum_walk_forward_folds
        and min(history_years.values()) >= config.research.minimum_history_years
        and min(coverage.values()) >= config.research.minimum_market_coverage
        and (len(common) / len(union) if union else 0.0)
        >= config.research.minimum_cross_symbol_coverage
        and minimum_strict_coverage >= config.research.minimum_factor_coverage
        and temporal_order_valid
    )
    return {
        "tier": (
            "execution_grade_candidate_input" if empirical_ready else "software_or_exploratory"
        ),
        "empirical_ready": empirical_ready,
        "provider": config.data.provider,
        "price_mode": config.data.price_mode,
        "symbols": sorted(daily_data),
        "history_years_by_symbol": history_years,
        "minimum_history_years": min(history_years.values()),
        "market_coverage_by_symbol": coverage,
        "minimum_market_coverage": min(coverage.values()),
        "cross_symbol_common_coverage": len(common) / len(union) if union else 0.0,
        "factor_coverage": factor_coverage,
        "minimum_strict_factor_coverage": minimum_strict_coverage,
        "source_provider_by_symbol": source_provider,
        "source_manifest_complete_by_symbol": source_manifest_complete,
        "all_source_manifests_complete": all(source_manifest_complete.values()),
        "source_failed_hours_by_symbol": source_failed_hours,
        "total_source_failed_hours": sum(source_failed_hours.values()),
        "csv_hash_verified_by_symbol": csv_hash_verified,
        "all_csv_hashes_verified": all(csv_hash_verified.values()),
        "manifest_schema_valid_by_symbol": manifest_schema_valid,
        "all_manifest_schemas_valid": all(manifest_schema_valid.values()),
        "sources_are_execution_grade": sources_are_execution_grade,
        "complete_walk_forward_folds": len(folds),
        "minimum_required_walk_forward_folds": config.research.minimum_walk_forward_folds,
        "label_coverage": label_coverage,
        "label_temporal_order_valid": temporal_order_valid,
        "external_files_found": [str(path) for path in external_files],
        "external_quality": config.external.current_vintage_quality,
        "research_mode": config.research.research_mode,
        "excluded_factor_families": (
            sorted(TIME_SERIES_EXCLUDED_FACTOR_FAMILIES)
            if config.research.research_mode == "time_series_panel"
            else []
        ),
        "limitations": [
            "BIS/FRED macro series are current-vintage rather than revision-aware snapshots.",
            "CFTC uses a conservative approximate publication lag and the public historical "
            "compressed file is a current revised archive, not an as-published vintage.",
            "Forward labels exclude broker financing until account-compatible conversion exists.",
            "Yahoo or synthetic prices can validate software but cannot prove executable returns.",
            "Execution-grade readiness requires an allowed source, complete manifests, "
            "and verified CSV hashes.",
        ],
    }


def eligible_factor_catalog(
    config: LongHorizonConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Return the outcome-blind eligible factor catalog and per-factor exclusion reasons.

    Filtering reads only the factor definitions and the config's research_mode /
    external.enabled flags. It never inspects returns, IC, p-values or backtest
    results, so it is safe to run before any outcome label is opened.
    """
    catalog = pd.DataFrame([asdict(item) for item in factor_definitions(config.research)])
    keep = pd.Series(True, index=catalog.index)
    reasons: list[dict[str, Any]] = []
    time_series = config.research.research_mode == "time_series_panel"
    external_enabled = config.external.enabled
    for position, definition in catalog.iterrows():
        family = str(definition["family"])
        if time_series and family in TIME_SERIES_EXCLUDED_FACTOR_FAMILIES:
            keep[position] = False
            reasons.append(
                {
                    "name": definition["name"],
                    "family": family,
                    "exclusion_reason": (
                        "time_series_panel_excludes_currency_graph_cross_sectional_"
                        "and_value_trend_families"
                    ),
                }
            )
            continue
        if time_series and not external_enabled and bool(definition["requires_external_data"]):
            keep[position] = False
            reasons.append(
                {
                    "name": definition["name"],
                    "family": family,
                    "exclusion_reason": "external_data_disabled_requires_external_data",
                }
            )
    eligible = catalog.loc[keep].reset_index(drop=True)
    return eligible, reasons


def build_long_horizon_research(
    data: Mapping[str, pd.DataFrame], config: LongHorizonConfig
) -> LongHorizonBuildResult:
    daily, panel, external_files = build_long_horizon_panel(data, config)
    catalog, _exclusions = eligible_factor_catalog(config)
    missing = set(catalog["name"]) - set(panel)
    if missing:
        raise RuntimeError(f"long-horizon panel is missing catalog factors {sorted(missing)}")
    dataset = build_long_horizon_labels(panel, daily, config.research)
    folds = build_long_horizon_folds(dataset, config.research)
    audit = audit_long_horizon_data(
        daily, panel, dataset, catalog, folds, config, external_files
    )
    return LongHorizonBuildResult(daily, panel, dataset, catalog, folds, audit, external_files)


def _file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_long_horizon_artifacts(
    result: LongHorizonBuildResult,
    config: LongHorizonConfig,
    output_directory: str | Path | None = None,
) -> Path:
    output = Path(output_directory or config.research.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    result.panel.replace([np.inf, -np.inf], np.nan).to_csv(
        output / "factor_panel.csv.gz", index=False, compression="gzip"
    )
    result.dataset.replace([np.inf, -np.inf], np.nan).to_csv(
        output / "research_dataset.csv.gz", index=False, compression="gzip"
    )
    result.catalog.to_csv(output / "factor_catalog.csv", index=False)
    result.folds.to_csv(output / "walk_forward_folds.csv", index=False)
    (output / "data_audit.json").write_text(
        json.dumps(result.audit, indent=2, allow_nan=False), encoding="utf-8"
    )
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "uncommitted"
    manifest = {
        "schema_version": 1,
        "implementation_version": LONG_HORIZON_IMPLEMENTATION_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "git_revision": revision,
        "config": config.model_dump(mode="json"),
        "market_data_fingerprint_sha256": data_fingerprint(result.daily_data),
        "external_files": [
            {"path": str(path), "sha256": _file_sha256(path)}
            for path in result.external_files
        ],
        "rows": {"panel": len(result.panel), "dataset": len(result.dataset)},
        "factor_count": len(result.catalog),
        "fold_count": len(result.folds),
        "empirical_ready": result.audit["empirical_ready"],
        "note": "This command builds research inputs only; it does not fit or approve a model.",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8"
    )
    return output
