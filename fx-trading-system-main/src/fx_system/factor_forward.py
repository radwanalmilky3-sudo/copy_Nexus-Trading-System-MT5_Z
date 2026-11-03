from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .factor_config import FactorMiningConfig
from .factor_dsl import generate_discovery_factors
from .factors import FACTOR_DEFINITIONS, FACTOR_IMPLEMENTATION_VERSION, build_factor_panel
from .models import Signal
from .point_in_time import PointInTimeData
from .reporting import data_fingerprint

MODEL_VERSION = 2


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item() if np.isfinite(value) else None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _contract_hash(payload: dict[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key != "contract_sha256"}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def fit_frozen_factor_model(
    mining: Any,
    config: FactorMiningConfig,
    *,
    allow_rejected_for_testing: bool = False,
) -> dict[str, Any]:
    """Refit a frozen linear model after gates pass; never called for rejected research."""
    candidate_verdicts = {
        "research_candidate_requires_new_holdout",
        "research_candidate_requires_paper",
    }
    if mining.summary["verdict"] not in candidate_verdicts and not allow_rejected_for_testing:
        raise ValueError("Rejected factor research cannot be frozen for forward use")
    development = [fold for fold in mining.folds if fold.kind == "development"]
    if not development:
        raise ValueError("At least one development fold is required to freeze a model")
    selection_counts = Counter(
        feature for fold in development for feature in set(fold.selected_features)
    )
    required = math.ceil(len(development) * config.factor.freeze_minimum_selection_fraction)
    selected = sorted(feature for feature, count in selection_counts.items() if count >= required)
    if not selected:
        if not allow_rejected_for_testing:
            raise ValueError("No factor met the frozen-model selection-frequency gate")
        selected = sorted(selection_counts, key=selection_counts.get, reverse=True)[:5]
    if not selected:
        raise ValueError("No selected factor is available to freeze")

    include_holdout = mining.summary["verdict"] == "research_candidate_requires_paper"
    eligible_folds = mining.folds if include_holdout else development
    cutoff = max(fold.test_end for fold in eligible_folds)
    freeze_available_time = max(fold.evaluation_end for fold in eligible_folds)
    train = mining.dataset.loc[
        (mining.dataset["_feature_time"] <= cutoff)
        & (mining.dataset["_label_end_time"] <= freeze_available_time)
    ].copy()
    times = sorted(train["_feature_time"].unique())
    split_location = int(len(times) * (1 - config.factor.calibration_fraction))
    if split_location <= 0 or split_location >= len(times):
        raise ValueError("Frozen model cannot create a chronological calibration split")
    calibration_start = pd.Timestamp(times[split_location])
    model_train = train.loc[
        (train["_feature_time"] < calibration_start)
        & (train["_label_end_time"] < calibration_start)
    ]
    calibration = train.loc[train["_feature_time"] >= calibration_start]
    if model_train["_label"].nunique() < 2 or calibration["_label"].nunique() < 2:
        raise ValueError("Frozen model fit/calibration data lacks both target classes")

    from .factor_research import _build_model, _fit_probability_calibrator

    model = _build_model(config.factor)
    model.fit(model_train[selected], model_train["_label"])
    calibrator = _fit_probability_calibrator(
        model, calibration, selected, config.factor.random_state
    )
    imputer = model.named_steps["imputer"]
    scaler = model.named_steps["scaler"]
    classifier = model.named_steps["classifier"]
    catalog = mining.catalog.set_index("name")
    selected_catalog = [
        _json_value({"name": feature, **catalog.loc[feature].to_dict()})
        for feature in selected
    ]
    payload: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "created_from_verdict": mining.summary["verdict"],
        "selected_features": selected,
        "selected_feature_catalog": selected_catalog,
        "directional_features": [
            feature for feature in selected if bool(catalog.loc[feature, "directional"])
        ],
        "imputer_statistics": imputer.statistics_.tolist(),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "classifier_coefficients": classifier.coef_[0].tolist(),
        "classifier_intercept": float(classifier.intercept_[0]),
        "calibrator_coefficient": float(calibrator.coef_[0][0]),
        "calibrator_intercept": float(calibrator.intercept_[0]),
        "target_mean_r": float(
            calibration.loc[calibration["_label"] == 1, "_realized_r"].mean()
        ),
        "non_target_mean_r": float(
            calibration.loc[calibration["_label"] == 0, "_realized_r"].mean()
        ),
        "feature_cutoff": cutoff,
        "freeze_available_time": freeze_available_time,
        "minimum_forward_days": config.factor.forward_minimum_days,
        "factor_settings": config.factor.model_dump(mode="json"),
        "discovery_settings": config.discovery.model_dump(mode="json"),
        "cost_settings": config.costs.model_dump(mode="json"),
        "risk_settings": config.risk.model_dump(mode="json"),
        "point_in_time_settings": config.point_in_time.model_dump(mode="json"),
        "factor_implementation_version": FACTOR_IMPLEMENTATION_VERSION,
        "market_contract": {
            "provider": config.data.provider,
            "interval": config.data.interval,
            "price_mode": config.data.price_mode,
        },
        "symbols": sorted(mining.dataset["_symbol"].unique()),
        "research_data_end": mining.summary["research_data_end"],
        "research_data_end_by_symbol": mining.summary["research_data_end_by_symbol"],
        "market_data_prefix_sha256": mining.summary["market_data_fingerprint_sha256"],
        "point_in_time_prefix_sha256": mining.summary[
            "point_in_time_prefix_fingerprint_sha256"
        ],
        "market_source_provider_by_symbol": mining.summary["data_readiness"][
            "source_provider_by_symbol"
        ],
        "market_source_parser_version_by_symbol": mining.summary["data_readiness"][
            "source_parser_version_by_symbol"
        ],
        "market_data_fingerprint_sha256": mining.summary.get(
            "market_data_fingerprint_sha256"
        ),
        "point_in_time_fingerprint_sha256": mining.summary.get(
            "point_in_time_fingerprint_sha256"
        ),
    }
    payload = _json_value(payload)
    payload["contract_sha256"] = _contract_hash(payload)
    return payload


def validate_frozen_model(model: dict[str, Any], config: FactorMiningConfig) -> None:
    if model.get("model_version") != MODEL_VERSION:
        raise ValueError(f"Unsupported frozen factor model version: {model.get('model_version')}")
    if model.get("contract_sha256") != _contract_hash(model):
        raise ValueError("Frozen factor model contract hash does not match its contents")
    if model.get("discovery_settings") != config.discovery.model_dump(mode="json"):
        raise ValueError("Frozen model discovery settings do not match the forward config")
    if model.get("factor_settings") != config.factor.model_dump(mode="json"):
        raise ValueError("Frozen model factor settings do not match the forward config")
    if model.get("cost_settings") != config.costs.model_dump(mode="json"):
        raise ValueError("Frozen model cost settings do not match the forward config")
    if model.get("risk_settings") != config.risk.model_dump(mode="json"):
        raise ValueError("Frozen model risk settings do not match the forward config")
    if model.get("point_in_time_settings") != config.point_in_time.model_dump(mode="json"):
        raise ValueError("Frozen model point-in-time settings do not match the forward config")
    if model.get("factor_implementation_version") != FACTOR_IMPLEMENTATION_VERSION:
        raise ValueError("Frozen model factor implementation version is no longer supported")
    expected_market_contract = {
        "provider": config.data.provider,
        "interval": config.data.interval,
        "price_mode": config.data.price_mode,
    }
    if model.get("market_contract") != expected_market_contract:
        raise ValueError("Frozen model market-data contract does not match the forward config")
    lengths = {
        len(model[key])
        for key in (
            "selected_features",
            "imputer_statistics",
            "scaler_mean",
            "scaler_scale",
            "classifier_coefficients",
        )
    }
    if len(lengths) != 1 or next(iter(lengths)) == 0:
        raise ValueError("Frozen factor model parameter dimensions are inconsistent")


def load_frozen_model(path: str | Path, config: FactorMiningConfig) -> dict[str, Any]:
    model = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_frozen_model(model, config)
    return model


def _predict_probability(model: dict[str, Any], frame: pd.DataFrame) -> np.ndarray:
    features = model["selected_features"]
    values = frame[features].to_numpy(dtype=float)
    imputer = np.asarray(model["imputer_statistics"], dtype=float)
    values = np.where(np.isfinite(values), values, imputer)
    scale = np.asarray(model["scaler_scale"], dtype=float)
    scale = np.where(scale == 0, 1.0, scale)
    standardized = (values - np.asarray(model["scaler_mean"], dtype=float)) / scale
    raw = standardized @ np.asarray(model["classifier_coefficients"], dtype=float)
    raw += float(model["classifier_intercept"])
    calibrated = raw * float(model["calibrator_coefficient"])
    calibrated += float(model["calibrator_intercept"])
    return 1 / (1 + np.exp(-np.clip(calibrated, -40, 40)))


def build_forward_predictions(
    data: Mapping[str, pd.DataFrame],
    config: FactorMiningConfig,
    model: dict[str, Any],
    point_in_time: PointInTimeData | None = None,
) -> tuple[pd.DataFrame, list[Signal]]:
    """Apply a frozen model to strictly later features without labels, fitting, or selection."""
    validate_frozen_model(model, config)
    if sorted(data) != sorted(model["symbols"]):
        raise ValueError("Forward market symbols do not match the frozen model contract")
    end_by_symbol = {
        symbol: pd.Timestamp(value)
        for symbol, value in model["research_data_end_by_symbol"].items()
    }
    prefix = {
        symbol: frame.loc[frame.index <= end_by_symbol[symbol]]
        for symbol, frame in data.items()
    }
    if data_fingerprint(prefix) != model["market_data_prefix_sha256"]:
        raise ValueError("Forward market data changed inside the frozen research prefix")
    research_data_end = pd.Timestamp(model["research_data_end"])
    expected_point_prefix = model.get("point_in_time_prefix_sha256")
    actual_point_prefix = (
        point_in_time.fingerprint(research_data_end) if point_in_time is not None else None
    )
    if actual_point_prefix != expected_point_prefix:
        raise ValueError("Forward point-in-time data changed inside the frozen research prefix")
    current_source_provider = {
        symbol: frame.attrs.get("source_provider") for symbol, frame in data.items()
    }
    if current_source_provider != model["market_source_provider_by_symbol"]:
        raise ValueError("Forward market source providers changed from the frozen contract")
    current_parser_version = {
        symbol: frame.attrs.get("source_parser_version") for symbol, frame in data.items()
    }
    if current_parser_version != model["market_source_parser_version_by_symbol"]:
        raise ValueError("Forward market parser versions changed from the frozen contract")
    panel = build_factor_panel(data, point_in_time)
    panel, _ = generate_discovery_factors(panel, dict(FACTOR_DEFINITIONS), config.discovery)
    missing = set(model["selected_features"]) - set(panel)
    if missing:
        raise ValueError(f"Forward panel is missing frozen factors: {sorted(missing)}")
    common_forward_end = min(frame.index[-1] for frame in data.values())
    forward = panel.loc[
        (panel["_feature_time"] > research_data_end)
        & (panel["_feature_time"] <= common_forward_end)
    ].copy()
    if forward.empty:
        columns = [
            "_feature_time",
            "_entry_time",
            "_symbol",
            "_direction",
            "_atr",
            "probability",
            "estimated_swap_r",
            "estimated_cost_r",
            "estimated_scenario_cost_r",
            "financing_cost_known",
            "financing_source",
            "expected_gross_r",
            "expected_scenario_r",
            "expected_net_r",
        ]
        return pd.DataFrame(columns=columns), []
    external_families = {"carry", "positioning"}
    external_primitives = {
        name
        for name, definition in FACTOR_DEFINITIONS.items()
        if definition.family in external_families
    }
    external_selected: list[str] = []
    for item in model["selected_feature_catalog"]:
        raw_parents = item.get("parents")
        parents = set(raw_parents) if isinstance(raw_parents, list | tuple) else set()
        if item.get("family") in external_families or parents & external_primitives:
            external_selected.append(str(item["name"]))
    external_coverage = (
        float(forward[external_selected].notna().all(axis=1).mean())
        if external_selected
        else 1.0
    )
    if external_coverage < config.factor.minimum_forward_external_feature_coverage:
        raise ValueError(
            "Forward external-factor coverage is below the frozen minimum: "
            f"{external_coverage:.1%}"
        )
    if external_selected:
        forward = forward.dropna(subset=external_selected)
    rows: list[pd.DataFrame] = []
    directional = set(model["directional_features"])
    for direction in (-1, 1):
        side = forward.copy()
        for feature in directional:
            side[feature] = side[feature] * direction
        side["_direction"] = direction
        rows.append(side)
    predictions = pd.concat(rows, ignore_index=True)
    entry_times: list[pd.Timestamp | pd.NaT] = []
    for symbol, feature_time in zip(
        predictions["_symbol"], predictions["_feature_time"], strict=True
    ):
        index = data[str(symbol)].index
        location = index.searchsorted(feature_time, side="right")
        entry_times.append(index[location] if location < len(index) else pd.NaT)
    predictions["_entry_time"] = entry_times
    predictions = predictions.dropna(subset=["_entry_time"]).reset_index(drop=True)
    predictions["probability"] = _predict_probability(model, predictions)

    from .factor_research import _add_economic_scores, _signals_from_predictions

    scored = _add_economic_scores(
        predictions,
        data,
        config,
        float(model["target_mean_r"]),
        float(model["non_target_mean_r"]),
    )
    scored.attrs["external_feature_coverage"] = external_coverage
    scored.attrs["external_selected_features"] = external_selected
    scored.attrs["selected_feature_coverage"] = {
        feature: float(forward[feature].notna().mean())
        for feature in model["selected_features"]
    }
    signals = _signals_from_predictions(scored, config.factor, fold=0)
    return scored, signals
