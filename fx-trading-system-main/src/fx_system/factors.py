from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .indicators import atr, ema, rolling_zscore, rsi
from .models import CurrencyPair
from .point_in_time import PointInTimeData, build_carry_factors

FACTOR_IMPLEMENTATION_VERSION = "2"


@dataclass(frozen=True)
class FactorDefinition:
    name: str
    family: str
    directional: bool
    description: str


def _definitions() -> list[FactorDefinition]:
    result: list[FactorDefinition] = []

    def add(name: str, family: str, directional: bool, description: str) -> None:
        result.append(FactorDefinition(name, family, directional, description))

    for window in (1, 3, 6, 12, 24):
        add(f"momentum_{window}", "momentum", True, f"{window}-bar log return")
    for window in (10, 20, 60):
        add(f"close_z_{window}", "reversal", True, f"Close z-score over {window} bars")
    add("rsi_14_centered", "reversal", True, "RSI(14) centered and scaled around 50")
    for fast, slow in ((5, 20), (10, 30), (20, 60)):
        add(
            f"ema_spread_{fast}_{slow}",
            "trend",
            True,
            f"EMA({fast}) minus EMA({slow}), normalized by ATR",
        )
    for window in (6, 12, 24, 60):
        add(f"realized_vol_{window}", "volatility", False, f"{window}-bar return volatility")
    add("vol_ratio_6_24", "volatility", False, "Short/medium realized volatility ratio")
    add("vol_ratio_12_60", "volatility", False, "Medium/slow realized volatility ratio")
    add("atr_percent", "volatility", False, "ATR as a fraction of close")
    for window in (10, 20, 60):
        add(
            f"channel_position_{window}",
            "market_structure",
            True,
            f"Close location within the trailing {window}-bar range",
        )
    add("candle_body_atr", "market_structure", True, "Candle body normalized by ATR")
    add("wick_balance_atr", "market_structure", True, "Lower minus upper wick normalized by ATR")
    add("range_expansion", "market_structure", False, "Current true range versus trailing median")
    for window in (12, 24):
        add(
            f"efficiency_{window}",
            "regime",
            False,
            f"Directional efficiency ratio over {window} bars",
        )
        add(
            f"autocorrelation_{window}",
            "regime",
            False,
            f"Lag-one return autocorrelation over {window} bars",
        )
    add("return_skew_24", "distribution", True, "Rolling 24-bar return skew")
    add("return_kurtosis_24", "distribution", False, "Rolling 24-bar excess kurtosis")
    add(
        "semivariance_asymmetry_24",
        "distribution",
        True,
        "Downside versus upside realized semivariance over 24 bars",
    )
    add("sign_entropy_24", "distribution", False, "Binary return-sign entropy over 24 bars")
    add(
        "variance_ratio_5_60",
        "regime",
        False,
        "Five-bar variance ratio estimated over 60 bars",
    )
    add(
        "parkinson_vol_ratio_20",
        "volatility",
        False,
        "Range-based Parkinson volatility versus close-to-close volatility",
    )
    add("close_location_value", "market_structure", True, "Close location within current bar")
    add("gap_atr", "market_structure", True, "Open gap from prior close normalized by ATR")
    add(
        "breakout_distance_20",
        "market_structure",
        True,
        "Distance beyond the prior 20-bar channel normalized by ATR",
    )
    for window in (20, 60):
        add(
            f"trend_tstat_{window}",
            "trend",
            True,
            f"T-statistic of the log-price trend over {window} bars",
        )
    add(
        "cross_sectional_momentum_12",
        "cross_sectional",
        True,
        "Cross-pair percentile rank of 12-bar momentum",
    )
    add("hour_sin", "calendar", False, "Cyclical UTC hour encoding")
    add("hour_cos", "calendar", False, "Cyclical UTC hour encoding")
    add("weekday_sin", "calendar", False, "Cyclical weekday encoding")
    add("weekday_cos", "calendar", False, "Cyclical weekday encoding")
    for window in (1, 3, 6, 12):
        add(
            f"base_strength_{window}",
            "currency_graph",
            True,
            f"Least-squares base-currency strength over {window} bars",
        )
        add(
            f"quote_strength_{window}",
            "currency_graph",
            True,
            f"Least-squares quote-currency strength over {window} bars",
        )
        add(
            f"currency_relative_{window}",
            "currency_graph",
            True,
            f"Base minus quote graph strength over {window} bars",
        )
        add(
            f"pair_residual_{window}",
            "relative_value",
            True,
            f"Pair return unexplained by the currency graph over {window} bars",
        )
    add(
        "currency_dispersion_12",
        "currency_graph",
        False,
        "Cross-currency dispersion of gauge-invariant graph strengths",
    )
    add(
        "pair_residual_z_12",
        "relative_value",
        True,
        "Cross-pair standardized 12-bar currency-graph residual",
    )
    add(
        "rate_differential",
        "carry",
        True,
        "Point-in-time base minus quote policy-rate differential",
    )
    add(
        "curve_slope_differential",
        "carry",
        True,
        "Point-in-time base minus quote OIS curve-slope differential",
    )
    add(
        "forward_discount_1m",
        "carry",
        True,
        "Annualized one-month forward discount known at feature time",
    )
    add(
        "carry_to_vol_20",
        "carry",
        True,
        "Policy-rate differential divided by 20-bar annualized volatility",
    )
    add(
        "cftc_dealer_net",
        "positioning",
        True,
        "Point-in-time base minus quote CFTC dealer net ratio",
    )
    add(
        "cftc_asset_manager_net",
        "positioning",
        True,
        "Point-in-time base minus quote CFTC asset-manager net ratio",
    )
    add(
        "cftc_leveraged_net",
        "positioning",
        True,
        "Point-in-time base minus quote CFTC leveraged-money net ratio",
    )
    add(
        "cftc_leveraged_change_4w",
        "positioning",
        True,
        "Four-week change in base minus quote leveraged-money net ratio",
    )
    add(
        "cftc_leveraged_z_156",
        "positioning",
        True,
        "Three-year rolling z-score of base minus quote leveraged positioning",
    )
    add(
        "spread_atr",
        "execution_state",
        False,
        "Observed close bid/ask spread normalized by ATR",
    )
    add(
        "spread_z_20",
        "execution_state",
        False,
        "Observed close bid/ask spread z-score over 20 bars",
    )
    return result


FACTOR_DEFINITIONS = {item.name: item for item in _definitions()}


def factor_catalog() -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in FACTOR_DEFINITIONS.values()])


def factor_columns() -> list[str]:
    return list(FACTOR_DEFINITIONS)


def directional_factor_columns() -> set[str]:
    return {name for name, definition in FACTOR_DEFINITIONS.items() if definition.directional}


def _efficiency(close: pd.Series, window: int) -> pd.Series:
    displacement = close.diff(window).abs()
    path = close.diff().abs().rolling(window, min_periods=window).sum().replace(0, np.nan)
    return displacement / path


def _autocorrelation(returns: pd.Series, window: int) -> pd.Series:
    return returns.rolling(window, min_periods=window).corr(returns.shift(1))


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
        standard_error = np.sqrt(residual_variance / x_sum_squares)
        return float(np.clip(slope / standard_error, -25.0, 25.0))

    return log_close.rolling(window, min_periods=window).apply(calculate, raw=True)


def _currency_graph(
    data: Mapping[str, pd.DataFrame], windows: tuple[int, ...] = (1, 3, 6, 12)
) -> dict[str, pd.DataFrame]:
    symbols = sorted(data)
    pairs = [CurrencyPair.parse(symbol) for symbol in symbols]
    currencies = sorted({currency for pair in pairs for currency in (pair.base, pair.quote)})
    currency_index = {currency: i for i, currency in enumerate(currencies)}
    incidence = np.zeros((len(symbols), len(currencies)))
    for row, pair in enumerate(pairs):
        incidence[row, currency_index[pair.base]] = 1.0
        incidence[row, currency_index[pair.quote]] = -1.0
    pseudo_inverse = np.linalg.pinv(incidence)
    has_graph_cycles = np.linalg.matrix_rank(incidence) < len(symbols)
    closes = pd.concat({symbol: data[symbol]["close"] for symbol in symbols}, axis=1).sort_index()
    closes = closes.ffill(limit=1)
    log_closes = np.log(closes)
    output = {symbol: pd.DataFrame(index=data[symbol].index) for symbol in symbols}
    for window in windows:
        pair_returns = log_closes.diff(window)
        strengths = pair_returns.to_numpy() @ pseudo_inverse.T
        fitted = strengths @ incidence.T
        residuals = (
            pair_returns.to_numpy() - fitted
            if has_graph_cycles
            else np.full_like(pair_returns.to_numpy(), np.nan)
        )
        strength_frame = pd.DataFrame(strengths, index=pair_returns.index, columns=currencies)
        fitted_frame = pd.DataFrame(
            fitted if has_graph_cycles else np.full_like(fitted, np.nan),
            index=pair_returns.index,
            columns=symbols,
        )
        residual_frame = pd.DataFrame(residuals, index=pair_returns.index, columns=symbols)
        currency_dispersion = strength_frame.std(axis=1, ddof=0)
        pair_scale = pair_returns.std(axis=1, ddof=0)
        residual_scale = residual_frame.std(axis=1, ddof=0)
        # A graph-consistent cross set leaves only floating-point residuals. Do not turn that
        # numerical noise into an apparently unit-scale factor through standardization.
        residual_scale = residual_scale.where(
            residual_scale > np.maximum(1e-12, pair_scale * 1e-6)
        )
        residual_z = residual_frame.div(residual_scale, axis=0)
        for symbol, pair in zip(symbols, pairs, strict=True):
            target_index = data[symbol].index
            output[symbol][f"base_strength_{window}"] = strength_frame[pair.base].reindex(
                target_index
            )
            output[symbol][f"quote_strength_{window}"] = strength_frame[pair.quote].reindex(
                target_index
            )
            output[symbol][f"currency_relative_{window}"] = fitted_frame[symbol].reindex(
                target_index
            )
            output[symbol][f"pair_residual_{window}"] = residual_frame[symbol].reindex(target_index)
            if window == 12:
                output[symbol]["currency_dispersion_12"] = currency_dispersion.reindex(
                    target_index
                )
                output[symbol]["pair_residual_z_12"] = residual_z[symbol].reindex(target_index)
    return output


def build_factor_panel(
    data: Mapping[str, pd.DataFrame],
    point_in_time: PointInTimeData | None = None,
) -> pd.DataFrame:
    """Build close-of-bar factors; every rolling calculation ends at the feature timestamp."""
    graph_features = _currency_graph(data)
    panels: list[pd.DataFrame] = []
    for symbol, frame in sorted(data.items()):
        close = frame["close"].astype(float)
        log_close = np.log(close)
        returns = log_close.diff()
        current_atr = atr(frame, 14)
        factors = pd.DataFrame(index=frame.index)
        for window in (1, 3, 6, 12, 24):
            factors[f"momentum_{window}"] = log_close.diff(window)
        for window in (10, 20, 60):
            factors[f"close_z_{window}"] = rolling_zscore(close, window)
        factors["rsi_14_centered"] = (rsi(close, 14) - 50) / 50
        for fast, slow in ((5, 20), (10, 30), (20, 60)):
            factors[f"ema_spread_{fast}_{slow}"] = (
                ema(close, fast) - ema(close, slow)
            ) / current_atr.replace(0, np.nan)
        for window in (6, 12, 24, 60):
            factors[f"realized_vol_{window}"] = returns.rolling(window, min_periods=window).std(
                ddof=0
            )
        factors["vol_ratio_6_24"] = factors["realized_vol_6"] / factors["realized_vol_24"].replace(
            0, np.nan
        )
        factors["vol_ratio_12_60"] = factors["realized_vol_12"] / factors[
            "realized_vol_60"
        ].replace(0, np.nan)
        factors["atr_percent"] = current_atr / close
        for window in (10, 20, 60):
            trailing_high = frame["high"].rolling(window, min_periods=window).max()
            trailing_low = frame["low"].rolling(window, min_periods=window).min()
            width = (trailing_high - trailing_low).replace(0, np.nan)
            factors[f"channel_position_{window}"] = 2 * (close - trailing_low) / width - 1
        body = close - frame["open"]
        upper_wick = frame["high"] - pd.concat([frame["open"], close], axis=1).max(axis=1)
        lower_wick = pd.concat([frame["open"], close], axis=1).min(axis=1) - frame["low"]
        factors["candle_body_atr"] = body / current_atr.replace(0, np.nan)
        factors["wick_balance_atr"] = (lower_wick - upper_wick) / current_atr.replace(0, np.nan)
        true_range = pd.concat(
            [
                frame["high"] - frame["low"],
                (frame["high"] - close.shift(1)).abs(),
                (frame["low"] - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        factors["range_expansion"] = true_range / true_range.rolling(20).median().replace(0, np.nan)
        for window in (12, 24):
            factors[f"efficiency_{window}"] = _efficiency(close, window)
            factors[f"autocorrelation_{window}"] = _autocorrelation(returns, window)
        factors["return_skew_24"] = returns.rolling(24, min_periods=24).skew()
        factors["return_kurtosis_24"] = returns.rolling(24, min_periods=24).kurt()
        upside_variance = returns.clip(lower=0).pow(2).rolling(24, min_periods=24).mean()
        downside_variance = returns.clip(upper=0).pow(2).rolling(24, min_periods=24).mean()
        upside_volatility = np.sqrt(upside_variance)
        downside_volatility = np.sqrt(downside_variance)
        factors["semivariance_asymmetry_24"] = (downside_volatility - upside_volatility) / (
            downside_volatility + upside_volatility
        ).replace(0, np.nan)
        positive_fraction = returns.gt(0).rolling(24, min_periods=24).mean().clip(1e-12, 1 - 1e-12)
        factors["sign_entropy_24"] = -(
            positive_fraction * np.log(positive_fraction)
            + (1 - positive_fraction) * np.log(1 - positive_fraction)
        ) / np.log(2)
        one_bar_variance = returns.rolling(60, min_periods=60).var(ddof=0)
        five_bar_variance = log_close.diff(5).rolling(60, min_periods=60).var(ddof=0)
        factors["variance_ratio_5_60"] = five_bar_variance / (
            5 * one_bar_variance.replace(0, np.nan)
        )
        parkinson_volatility = np.sqrt(
            np.log(frame["high"] / frame["low"])
            .pow(2)
            .rolling(20, min_periods=20)
            .mean()
            / (4 * np.log(2))
        )
        close_volatility_20 = returns.rolling(20, min_periods=20).std(ddof=0)
        factors["parkinson_vol_ratio_20"] = parkinson_volatility / close_volatility_20.replace(
            0, np.nan
        )
        bar_range = (frame["high"] - frame["low"]).replace(0, np.nan)
        factors["close_location_value"] = (
            2 * close - frame["high"] - frame["low"]
        ) / bar_range
        factors["gap_atr"] = (frame["open"] - close.shift(1)) / current_atr.replace(0, np.nan)
        prior_high_20 = frame["high"].shift(1).rolling(20, min_periods=20).max()
        prior_low_20 = frame["low"].shift(1).rolling(20, min_periods=20).min()
        breakout = (close - prior_high_20).clip(lower=0) + (close - prior_low_20).clip(upper=0)
        factors["breakout_distance_20"] = breakout / current_atr.replace(0, np.nan)
        for window in (20, 60):
            factors[f"trend_tstat_{window}"] = _trend_tstat(log_close, window)
        factors["hour_sin"] = np.sin(2 * np.pi * frame.index.hour / 24)
        factors["hour_cos"] = np.cos(2 * np.pi * frame.index.hour / 24)
        factors["weekday_sin"] = np.sin(2 * np.pi * frame.index.dayofweek / 5)
        factors["weekday_cos"] = np.cos(2 * np.pi * frame.index.dayofweek / 5)
        if point_in_time is not None:
            median_seconds = (
                float(np.median(np.diff(frame.index.view("int64"))) / 1e9)
                if len(frame) > 1
                else 86400
            )
            if median_seconds >= 20 * 3600:
                periods_per_year = 260
            elif median_seconds >= 3 * 3600:
                periods_per_year = 6 * 260
            else:
                periods_per_year = 24 * 260
            factors = factors.join(
                build_carry_factors(symbol, frame, point_in_time, periods_per_year)
            )
        else:
            for carry_factor in (
                "rate_differential",
                "curve_slope_differential",
                "forward_discount_1m",
                "carry_to_vol_20",
                "cftc_dealer_net",
                "cftc_asset_manager_net",
                "cftc_leveraged_net",
                "cftc_leveraged_change_4w",
                "cftc_leveraged_z_156",
            ):
                factors[carry_factor] = np.nan
        if "spread_close" in frame:
            factors["spread_atr"] = frame["spread_close"] / current_atr.replace(0, np.nan)
            factors["spread_z_20"] = rolling_zscore(frame["spread_close"], 20)
        else:
            factors["spread_atr"] = np.nan
            factors["spread_z_20"] = np.nan
        factors = factors.join(graph_features[symbol])
        factors["_close"] = close
        factors["_atr"] = current_atr
        factors["_symbol"] = symbol
        factors.index.name = "_feature_time"
        panels.append(factors.reset_index())
    panel = pd.concat(panels, ignore_index=True)
    panel["cross_sectional_momentum_12"] = (
        2
        * panel.groupby("_feature_time")["momentum_12"].rank(
            method="average", pct=True, na_option="keep"
        )
        - 1
    )
    expected = set(factor_columns())
    missing = expected - set(panel)
    if missing:
        raise RuntimeError(f"Factor implementation is missing catalog entries: {sorted(missing)}")
    panel["_feature_time"] = pd.to_datetime(panel["_feature_time"], utc=True)
    return panel.sort_values(["_feature_time", "_symbol"]).reset_index(drop=True)
