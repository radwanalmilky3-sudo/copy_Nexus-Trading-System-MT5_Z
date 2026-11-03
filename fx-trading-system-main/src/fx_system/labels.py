from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

import numpy as np
import pandas as pd

from .factor_config import FactorSettings
from .factors import directional_factor_columns, factor_columns
from .models import Side


def _executable_price(
    frame: pd.DataFrame,
    location: int,
    field: str,
    direction: int,
    is_entry: bool,
) -> float:
    buying = (direction > 0 and is_entry) or (direction < 0 and not is_entry)
    column = f"{'ask' if buying else 'bid'}_{field}"
    if column in frame:
        return float(frame[column].iloc[location])
    return float(frame[field].iloc[location])


def _label_symbol(
    frame: pd.DataFrame,
    atr_values: pd.Series,
    direction: int,
    settings: FactorSettings,
) -> pd.DataFrame:
    index = frame.index
    records: list[dict[str, object]] = []
    for feature_location in range(len(frame) - 1):
        current_atr = float(atr_values.iloc[feature_location])
        if not np.isfinite(current_atr) or current_atr <= 0:
            continue
        entry_location = feature_location + 1
        entry_time = index[entry_location]
        entry_mid = float(frame["open"].iloc[entry_location])
        entry_price = _executable_price(frame, entry_location, "open", direction, True)
        stop_distance = settings.stop_atr * current_atr
        target_distance = settings.target_atr * current_atr
        stop_price = entry_mid - direction * stop_distance
        target_price = entry_mid + direction * target_distance
        deadline = entry_time + timedelta(hours=settings.max_holding_hours)
        if index[-1] < deadline:
            # Do not train on a right-censored observation with an incomplete future horizon.
            continue
        event = "timeout"
        label = 0
        label_end_time = entry_time
        realized_r = 0.0
        last_location = entry_location
        timed_out_at_open = False
        for future_location in range(entry_location, len(frame)):
            timestamp = index[future_location]
            if timestamp >= deadline:
                event = "timeout"
                label = 0
                label_end_time = timestamp
                exit_price = _executable_price(frame, future_location, "open", direction, False)
                realized_r = direction * (exit_price - entry_price) / stop_distance
                realized_r = float(np.clip(realized_r, -2, settings.reward_risk))
                timed_out_at_open = True
                break
            last_location = future_location
            exit_side = "bid" if direction > 0 else "ask"
            high_column = f"{exit_side}_high"
            low_column = f"{exit_side}_low"
            high = float(
                frame[high_column].iloc[future_location]
                if high_column in frame
                else frame["high"].iloc[future_location]
            )
            low = float(
                frame[low_column].iloc[future_location]
                if low_column in frame
                else frame["low"].iloc[future_location]
            )
            stop_hit = low <= stop_price if direction > 0 else high >= stop_price
            target_hit = high >= target_price if direction > 0 else low <= target_price
            # Intrabar order is unknowable; a simultaneous touch is scored as a stop.
            if stop_hit:
                event = "stop"
                label = 0
                label_end_time = timestamp
                realized_r = (
                    direction * (stop_price - entry_price) / stop_distance
                    if "bid_open" in frame
                    else -1.0
                )
                break
            if target_hit:
                event = "target"
                label = 1
                label_end_time = timestamp
                realized_r = (
                    direction * (target_price - entry_price) / stop_distance
                    if "bid_open" in frame
                    else settings.reward_risk
                )
                break
        else:
            last_location = len(frame) - 1
        if event == "timeout" and not timed_out_at_open:
            label_end_time = index[last_location]
            exit_price = _executable_price(frame, last_location, "close", direction, False)
            realized_r = direction * (exit_price - entry_price) / stop_distance
            realized_r = float(np.clip(realized_r, -2, settings.reward_risk))
        records.append(
            {
                "_feature_time": index[feature_location],
                "_entry_time": entry_time,
                "_label_end_time": label_end_time,
                "_direction": direction,
                "_label": label,
                "_event": event,
                "_entry_price": entry_price,
                "_entry_mid": entry_mid,
                "_realized_r": realized_r,
            }
        )
    return pd.DataFrame(records)


def build_directional_dataset(
    factor_panel: pd.DataFrame,
    data: Mapping[str, pd.DataFrame],
    settings: FactorSettings,
    features: list[str] | None = None,
    directional: set[str] | None = None,
) -> pd.DataFrame:
    """Create symmetric long/short observations with future barriers kept as metadata."""
    directional = directional if directional is not None else directional_factor_columns()
    features = features if features is not None else factor_columns()
    datasets: list[pd.DataFrame] = []
    for symbol, frame in sorted(data.items()):
        symbol_factors = (
            factor_panel.loc[factor_panel["_symbol"] == symbol]
            .set_index("_feature_time")
            .reindex(frame.index)
        )
        symbol_factors.index.name = "_feature_time"
        for direction in (int(Side.LONG), int(Side.SHORT)):
            labels = _label_symbol(frame, symbol_factors["_atr"], direction, settings)
            if labels.empty:
                continue
            observations = labels.merge(
                symbol_factors.reset_index(), on="_feature_time", how="left", validate="one_to_one"
            )
            for feature in directional:
                observations[feature] = observations[feature] * direction
            observations["_symbol"] = symbol
            datasets.append(observations)
    if not datasets:
        return pd.DataFrame(columns=features)
    dataset = pd.concat(datasets, ignore_index=True)
    dataset = dataset.sort_values(["_feature_time", "_symbol", "_direction"]).reset_index(drop=True)
    return dataset
