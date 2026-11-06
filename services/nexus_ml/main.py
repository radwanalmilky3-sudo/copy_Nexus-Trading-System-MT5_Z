"""
Nexus ML — FastAPI service (port 8003).

Exposes REST endpoints for prediction, training, and model status.
Runs a background Redis Stream consumer that listens for FeatureEvents,
runs the ensemble, and publishes SignalEvents.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.constants import (
    HEARTBEAT_INTERVAL_SEC,
    ML_FEATURE_HISTORY_PREFIX,
    STREAM_MAX_LEN,
    RedisStream,
    ServiceName,
    Verdict,
)
from shared.events import FeatureEvent, SignalEvent
from shared.security_headers import SecurityHeadersMiddleware

from .ensemble import EnsembleSignal, ModelEnsemble
from .labeling import advance_pending_bar
from .model_promotion import (
    disclose_promotion_family,
    evaluate_promotion,
    metric_records_from_folds,
    preserve_unscored_anomaly,
)
from .model_registry import ModelRegistry
from .internal_auth import verify_internal_service_secret
from .rule_based_signal import RuleBasedSignalGenerator
from .training import WalkForwardConfig, WalkForwardTrainer

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MODEL_DIR = os.getenv("MODEL_DIR", "./models_store")
CONSUMER_GROUP = "nexus_ml_group"
CONSUMER_NAME = "nexus_ml_worker_1"

# ── Pydantic request / response schemas ──────────────────────────────────────


class PredictResponse(BaseModel):
    symbol: str
    direction: str
    confidence: float
    regime: str
    anomaly_score: float
    is_anomaly: bool
    individual_scores: dict[str, float] = Field(default_factory=dict)
    sentiment: dict[str, float] = Field(default_factory=dict)
    top_features: list[str] = Field(default_factory=list)


class TrainRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["EURUSD"])
    train_months: int = 6
    val_months: int = 1
    step_months: int = 1


class TrainResponse(BaseModel):
    status: str
    message: str
    task_id: str = ""


class ModelStatusResponse(BaseModel):
    models: dict[str, bool]
    ensemble_loaded: bool
    rule_based_active: bool = False
    symbol: str = ""
    per_symbol: dict[str, dict[str, bool]] = {}


class HealthResponse(BaseModel):
    service: str
    status: str
    uptime_seconds: float
    models_loaded: dict[str, bool]


# ── Application state ────────────────────────────────────────────────────────

_ensemble: ModelEnsemble | None = None
_rule_based: RuleBasedSignalGenerator | None = None
_redis: aioredis.Redis | None = None
_start_time: float = 0.0
_consumer_task: asyncio.Task[None] | None = None
_heartbeat_task: asyncio.Task[None] | None = None
_auto_retrain_task: asyncio.Task[None] | None = None
_training_in_progress: bool = False
_training_started_ts: float | None = None
_TRAINING_TIMEOUT_SEC = int(os.getenv("NEXUS_ML_TRAINING_TIMEOUT_SEC", "10800"))
_last_signal_ts: dict[str, float] = {}
SIGNAL_COOLDOWN_SEC = int(os.getenv("NEXUS_ML_SIGNAL_COOLDOWN_SEC", "60"))

# Auto-retrain config
_RETRAIN_MIN_SAMPLES = int(os.getenv("NEXUS_RETRAIN_MIN_SAMPLES", "500"))
_RETRAIN_CHECK_INTERVAL = int(os.getenv("NEXUS_RETRAIN_CHECK_INTERVAL_SEC", "3600"))
_RETRAIN_COOLDOWN_HOURS = int(os.getenv("NEXUS_RETRAIN_COOLDOWN_HOURS", "24"))
_RETRAIN_SYMBOLS = [
    s.strip().upper()
    for s in os.getenv("NEXUS_SYMBOLS", os.getenv("STREAM_SYMBOLS", "XAUUSD")).split(",")
    if s.strip()
]
_RETRAIN_LAST_KEY = "nexus:ml:last_retrain_ts"

# ── Per-symbol, per-timeframe model registry ─────────────────────────────────
# Each (symbol, timeframe) trains and loads its own ensemble under
# models_store/<SYMBOL>/timeframes/<TF>/. Symbols have incomparable price scales,
# and models trained on different bar horizons have different target semantics;
# neither dimension may be shared implicitly.

_ensembles: dict[tuple[str, str], ModelEnsemble] = {}
_model_registry = ModelRegistry(MODEL_DIR)


def symbol_model_dir(symbol: str) -> Path:
    return Path(MODEL_DIR) / symbol.strip().upper()


def _model_timeframe_dir(symbol: str, timeframe: str) -> Path:
    return symbol_model_dir(symbol) / "timeframes" / timeframe.strip().upper()


def _get_configured_timeframe() -> str:
    return os.getenv("NEXUS_OPERATIONAL_TF", "M5").strip().upper() or "M5"


def _get_symbol_ensemble(symbol: str, timeframe: str | None = None) -> ModelEnsemble:
    """Load only an ensemble with explicit matching symbol/timeframe provenance."""
    key = symbol.strip().upper()
    selected_timeframe = (timeframe or _get_configured_timeframe()).strip().upper()
    cache_key = (key, selected_timeframe)
    ens = _ensembles.get(cache_key)
    if ens is None:
        try:
            generations = _model_registry.resolve_startup_generation(key, selected_timeframe)
        except Exception:
            generations = []
            logger.critical("Active model pointer is unreadable for %s/%s", key, selected_timeframe, exc_info=True)
        for generation in generations:
            try:
                generation_dir = _model_registry.generation_dir(key, selected_timeframe, generation)
                manifest = _model_registry.read_generation_manifest(key, selected_timeframe, generation)
                expected = [name for name in manifest["artifacts"] if name != "feature_names.json"]
                candidate = ModelEnsemble(model_dir=str(generation_dir))
                candidate.load_all_models(strict=True, expected_artifacts=expected)
                candidate.generation_id = generation
                candidate.trained_at = str(manifest.get("trained_at", ""))
                candidate.data_window = str(manifest.get("data_window", ""))
                _ensembles[cache_key] = candidate
                logger.info("Loaded active model generation symbol=%s timeframe=%s generation=%s", key, selected_timeframe, generation)
                return candidate
            except Exception:
                logger.critical(
                    "Model generation failed startup validation symbol=%s generation=%s",
                    key, selected_timeframe, generation, exc_info=True,
                )
        ens = ModelEnsemble(model_dir=str(_model_timeframe_dir(key, selected_timeframe)))
        try:
            # Strict empty expectation rejects legacy artifacts without touching them.
            ens.load_all_models(strict=True, expected_artifacts=[])
        except ValueError:
            pass
        except Exception:
            logger.warning("Ensemble load failed for %s/%s", key, selected_timeframe, exc_info=True)
        _ensembles[cache_key] = ens
    return ens


def _comparison_records(results: list[Any], incumbent: bool = False) -> dict[str, list[dict[str, Any]]]:
    targets = {
        "xgboost": "direction",
        "lgbm_regime": "regime",
        "rf_importance": "direction",
        "lstm": "direction",
    }
    return metric_records_from_folds(results, targets, incumbent=incumbent)


async def _train_symbol_candidate(
    symbol: str,
    timeframe: str,
    data: tuple[np.ndarray, np.ndarray, np.ndarray, list[str]],
    cfg: WalkForwardConfig,
    task_id: str,
) -> tuple[dict[str, Any], list[Any]]:
    """Train and validate in isolation; only accepted bundles become active."""
    import uuid

    sym = symbol.strip().upper()
    tf = timeframe.strip().upper()
    incumbent = _get_symbol_ensemble(sym, tf)
    X, y, timestamps, feature_names = data
    incumbent_schema = list(getattr(incumbent, "feature_names", []))
    has_scored_incumbent = any(
        getattr(getattr(incumbent, name, None), "is_fitted", False)
        for name in ("xgb", "lgbm", "rf", "lstm")
    )
    if has_scored_incumbent and not incumbent_schema:
        return {
            "symbol": sym, "decision": "rejected", "reason": "incumbent_schema_unavailable",
            "fold_count": 0, "metrics": {},
        }, []
    if has_scored_incumbent and incumbent_schema != list(feature_names):
        return {
            "symbol": sym, "decision": "rejected", "reason": "feature_schema_mismatch",
            "fold_count": 0, "metrics": {},
        }, []
    generation = f"g-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:10]}"
    stage = _model_registry.create_staging(sym, tf, generation)
    cfg.model_dir = str(stage)
    cfg.strict_persistence = True
    trainer = WalkForwardTrainer(cfg)
    try:
        results = trainer.train_all_models(X, y, timestamps, feature_names, incumbent=incumbent)
        artifacts, anomaly_reason = preserve_unscored_anomaly(
            stage, trainer.saved_artifacts, feature_names, incumbent,
        )
        if anomaly_reason:
            return {
                "symbol": sym, "generation": generation, "decision": "rejected",
                "reason": anomaly_reason, "fold_count": 0, "metrics": {},
            }, results
        trainer.saved_artifacts = artifacts
        # Fold-window provenance: first training bar to last validation bar
        # across accepted folds, so promoted signals name their data window.
        trained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        starts = [getattr(r, "train_start", None) for r in results]
        ends = [getattr(r, "val_end", None) for r in results]
        if results and all(s is not None for s in starts) and all(e is not None for e in ends):
            data_window = f"{min(starts)}..{max(ends)}"
        else:
            data_window = ""
        manifest = _model_registry.write_generation_manifest(
            sym, tf, generation, trainer.saved_artifacts, feature_names,
            trained_at=trained_at, data_window=data_window,
        )
        candidate_metrics = _comparison_records(results)
        incumbent_metrics = _comparison_records(results, incumbent=True)
        supervised_models = {
            "xgboost_direction.json": "xgboost",
            "lgbm_regime.txt": "lgbm_regime",
            "rf_features.joblib": "rf_importance",
            "lstm_sequence.pt": "lstm",
        }
        included_supervised = {
            model for artifact, model in supervised_models.items()
            if artifact in manifest["artifacts"]
        }
        if not included_supervised.issubset(candidate_metrics):
            return {
                "symbol": sym, "generation": generation, "decision": "rejected",
                "reason": "incomplete_candidate_metrics", "fold_count": len(results),
                "metrics": {},
            }, results
        # Phase 5ج: disclose this run's hypothesis family (paired sign tests
        # per model over the shared folds) before promotion; a failed
        # disclosure passes None through so the gate fails closed.
        trial_family_id = disclose_promotion_family(
            candidate_metrics, incumbent_metrics,
            f"auto_retrain:{sym}:{tf}:{generation}",
        )
        decision = evaluate_promotion(
            candidate_metrics, incumbent_metrics, min_folds=3,
            trial_family_id=trial_family_id,
        )
        if not decision.accepted:
            return {
                "symbol": sym, "generation": generation, "decision": "rejected",
                "reason": decision.reason, "fold_count": decision.fold_count,
                "metrics": decision.metrics,
            }, results

        model_artifacts = [name for name in manifest["artifacts"] if name != "feature_names.json"]
        candidate = ModelEnsemble(model_dir=str(stage))
        candidate.load_all_models(strict=True, expected_artifacts=model_artifacts)
        candidate.generation_id = generation
        candidate.trained_at = trained_at
        candidate.data_window = data_window
        cache_key = (sym, tf)
        previous_ensemble = _ensembles.get(cache_key)
        try:
            _ensembles[cache_key] = candidate
            _model_registry.activate(sym, tf, generation)
        except Exception:
            if previous_ensemble is None:
                _ensembles.pop(cache_key, None)
            else:
                _ensembles[cache_key] = previous_ensemble
            raise
        logger.info(
            "auto_retrain.promoted symbol=%s generation=%s folds=%d",
            sym, generation, decision.fold_count,
        )
        return {
            "symbol": sym, "generation": generation, "decision": "promoted",
            "reason": decision.reason, "fold_count": decision.fold_count,
            "metrics": decision.metrics,
        }, results
    except Exception as exc:
        logger.error("[%s] Candidate training/promotion failed for %s", task_id, sym, exc_info=True)
        return {
            "symbol": sym, "generation": generation, "decision": "rejected",
            "reason": "candidate_validation_failed", "error_type": type(exc).__name__,
            "fold_count": 0, "metrics": {},
        }, []


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ensemble, _rule_based, _redis, _start_time
    global _consumer_task, _heartbeat_task, _auto_retrain_task

    _start_time = time.time()
    from shared import setup_logger as _setup_logger
    _setup_logger("nexus-ml", level=os.getenv("LOG_LEVEL", "INFO"))

    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Connected to Redis at %s", REDIS_URL)

    # Each (symbol, timeframe) loads only a provenanced ensemble; distinct bar
    # horizons and symbol scales must never share model artifacts.
    startup_tf = await _get_operational_timeframe()
    for sym in _RETRAIN_SYMBOLS:
        ens = _get_symbol_ensemble(sym, startup_tf)
        logger.info("Ensemble[%s] model load status: %s", sym, ens.models_status())
    _ensemble = _get_symbol_ensemble(_RETRAIN_SYMBOLS[0], startup_tf) if _RETRAIN_SYMBOLS else ModelEnsemble(model_dir=MODEL_DIR)
    status = _ensemble.models_status()

    # Rule-based fallback for when no ML models are trained yet
    _rule_based = RuleBasedSignalGenerator(confidence_threshold=0.35)
    any_model_loaded = any(status.values())
    if not any_model_loaded:
        logger.warning(
            "No ML models loaded — using rule-based signal generator (real indicators)"
        )

    await _ensure_consumer_group()
    _consumer_task = asyncio.create_task(_stream_consumer())
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    _auto_retrain_task = asyncio.create_task(_auto_retrain_loop())

    logger.info("nexus-ml service started on port 8003")

    # Start parallel model traders (ML/DL/RL) background scheduler
    try:
        from .traders_api import startup_traders, shutdown_traders
        await startup_traders()
        logger.info("Parallel model traders initialised")
    except Exception as _te:
        logger.warning("Traders startup skipped: %s", _te)

    yield

    # Shutdown traders scheduler
    try:
        from .traders_api import shutdown_traders
        await shutdown_traders()
    except Exception:
        pass

    await _cancel_lifecycle_tasks(
        _consumer_task,
        _heartbeat_task,
        _auto_retrain_task,
    )
    _consumer_task = None
    _heartbeat_task = None
    _auto_retrain_task = None
    if _redis:
        await _redis.aclose()
    logger.info("nexus-ml service shut down")


async def _cancel_lifecycle_tasks(*tasks: asyncio.Task[Any] | None) -> None:
    """Cancel and await every owned lifespan task before releasing resources."""
    active = [task for task in tasks if task is not None]
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)


app = FastAPI(
    title="Nexus ML Pipeline",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)

# ── Parallel Model Traders (ML / DL / RL) ───────────────────────────────────
try:
    from .traders_api import router as traders_router
    app.include_router(traders_router)
    logger.info("Parallel model traders API mounted at /api/traders")
except Exception as _traders_exc:
    logger.warning("Traders API not available: %s", _traders_exc)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        service=ServiceName.ML,
        status="healthy",
        uptime_seconds=round(time.time() - _start_time, 2),
        models_loaded=_ensemble.models_status() if _ensemble else {},
    )


# ── Prediction endpoint ──────────────────────────────────────────────────────


@app.get("/api/ml/predict/{symbol}", response_model=PredictResponse)
async def predict(
    symbol: str,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    operational_tf = await _get_operational_timeframe()
    features = await _get_latest_features(symbol, operational_tf)
    if features is None:
        raise HTTPException(404, f"No cached features for {symbol}/{operational_tf}")

    feature_tf = str(features.get("timeframe", operational_tf)).strip().upper()
    if feature_tf != operational_tf:
        raise HTTPException(409, "Feature timeframe does not match active model timeframe")
    ensemble = _get_symbol_ensemble(symbol, operational_tf)
    any_model_loaded = any(ensemble.models_status().values())

    if any_model_loaded:
        feature_array = ensemble.build_feature_array(features)
        signal = ensemble.predict(feature_array)
    elif _rule_based is not None:
        signal = _rule_based.predict(features)
    else:
        raise HTTPException(503, "No signal generator available")

    return PredictResponse(
        symbol=symbol,
        direction=signal.direction,
        confidence=signal.confidence,
        regime=signal.regime,
        anomaly_score=signal.anomaly_score,
        is_anomaly=signal.is_anomaly,
        individual_scores=signal.individual_scores,
        sentiment=signal.sentiment,
        top_features=signal.top_features,
    )


# ── Training endpoint ────────────────────────────────────────────────────────


@app.post("/api/ml/train", response_model=TrainResponse)
async def train(
    req: TrainRequest,
    background_tasks: BackgroundTasks,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    global _training_in_progress, _training_started_ts

    now_ts = time.time()
    if (
        _training_in_progress
        and _training_started_ts is not None
        and (now_ts - _training_started_ts) > _TRAINING_TIMEOUT_SEC
    ):
        logger.error(
            "Reclaiming stale walk-forward training job running for %.0fs (limit %ds)",
            now_ts - _training_started_ts, _TRAINING_TIMEOUT_SEC,
        )
        _training_in_progress = False
    if _training_in_progress:
        raise HTTPException(409, "Training already in progress")

    import uuid
    task_id = uuid.uuid4().hex[:12]
    _training_in_progress = True
    _training_started_ts = now_ts

    background_tasks.add_task(_run_training, req, task_id)

    return TrainResponse(
        status="started",
        message=f"Walk-forward training initiated for {req.symbols}",
        task_id=task_id,
    )


async def _run_training(req: TrainRequest, task_id: str) -> None:
    """Train each requested symbol as an isolated, acceptance-gated candidate."""
    global _training_in_progress, _training_started_ts
    try:
        timeframe = await _get_operational_timeframe()
        logger.info("[%s] Training started for %s on %s", task_id, req.symbols, timeframe)

        for symbol in req.symbols:
            sym = symbol.strip().upper()
            data = await _fetch_training_data([sym], timeframe=timeframe)
            if data is None:
                logger.error("[%s] No training data for %s — skipped", task_id, sym)
                continue
            cfg = WalkForwardConfig(
                train_months=req.train_months,
                val_months=req.val_months,
                step_months=req.step_months,
            )
            outcome, results = await _train_symbol_candidate(sym, timeframe, data, cfg, task_id)
            logger.info(
                "manual_retrain.candidate_outcome task=%s outcome=%s",
                task_id, json.dumps(outcome, sort_keys=True),
            )

    except Exception:
        logger.error("[%s] Training failed", task_id, exc_info=True)
    finally:
        _training_in_progress = False
        _training_started_ts = None


# ── Model status endpoint ────────────────────────────────────────────────────


@app.get("/api/ml/models/status", response_model=ModelStatusResponse)
async def models_status(
    symbol: str | None = None,
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    """Model status. Without `symbol` reports the first configured symbol;
    `per_symbol` always carries every configured symbol's own ensemble."""
    target = (symbol or (_RETRAIN_SYMBOLS[0] if _RETRAIN_SYMBOLS else "XAUUSD")).upper()
    timeframe = await _get_operational_timeframe()
    status = _get_symbol_ensemble(target, timeframe).models_status()
    any_loaded = any(status.values())
    per_symbol = {
        sym: _get_symbol_ensemble(sym, timeframe).models_status()
        for sym in _RETRAIN_SYMBOLS
    }
    return ModelStatusResponse(
        models=status,
        ensemble_loaded=any_loaded,
        rule_based_active=not any_loaded and _rule_based is not None,
        symbol=target,
        per_symbol=per_symbol,
    )


@app.get("/api/ml/retrain/status")
async def retrain_status(
    x_nexus_internal_secret: str | None = Header(default=None),
):
    verify_internal_service_secret(x_nexus_internal_secret)
    """Auto-retrain state: last run, sample counts, next trigger threshold."""
    if _redis is None:
        raise HTTPException(503, "Redis not connected")

    timeframe = await _get_operational_timeframe()
    total_samples, per_symbol = await _count_timeframe_samples(_RETRAIN_SYMBOLS, timeframe)

    last_result_raw = await _redis.get("nexus:ml:last_retrain_result")
    last_result = json.loads(last_result_raw) if last_result_raw else None

    last_ts_raw = await _redis.get(_RETRAIN_LAST_KEY)
    last_ts = float(last_ts_raw) if last_ts_raw else None

    return {
        "timeframe": timeframe,
        "total_samples": total_samples,
        "per_symbol": per_symbol,
        "min_samples_required": _RETRAIN_MIN_SAMPLES,
        "ready_to_train": total_samples >= _RETRAIN_MIN_SAMPLES and not _training_in_progress,
        "training_in_progress": _training_in_progress,
        "last_retrain_ts": last_ts,
        "last_retrain_result": last_result,
        "retrain_cooldown_hours": _RETRAIN_COOLDOWN_HOURS,
        "check_interval_sec": _RETRAIN_CHECK_INTERVAL,
    }


async def _count_timeframe_samples(
    symbols: list[str],
    timeframe: str,
) -> tuple[int, dict[str, int]]:
    """Count history rows for the active prediction horizon."""
    assert _redis is not None
    counts: dict[str, int] = {}
    for symbol in symbols:
        counts[symbol] = await _redis.llen(_feature_history_key(symbol, timeframe))
    return sum(counts.values()), counts


# ── Redis Stream consumer ────────────────────────────────────────────────────


async def _ensure_consumer_group() -> None:
    assert _redis is not None
    try:
        await _redis.xgroup_create(
            RedisStream.FEATURE_STREAM, CONSUMER_GROUP, id="0", mkstream=True,
        )
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def _stream_consumer() -> None:
    """Continuously read FeatureEvents, run predictions, publish SignalEvents."""
    assert _redis is not None
    assert _ensemble is not None or _rule_based is not None

    logger.info("Stream consumer started — listening on %s", RedisStream.FEATURE_STREAM)

    while True:
        try:
            entries = await _redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={RedisStream.FEATURE_STREAM: ">"},
                count=10,
                block=2000,
            )

            if not entries:
                continue

            for _stream_name, messages in entries:
                for msg_id, raw in messages:
                    await _handle_feature_event(msg_id, raw)

        except asyncio.CancelledError:
            logger.info("Stream consumer cancelled")
            break
        except aioredis.ResponseError as e:
            if "NOGROUP" in str(e):
                # The consumer group (or the stream itself) was deleted
                # externally; recreate it and resume instead of looping forever.
                logger.warning("Consumer group missing on %s — recreating: %s",
                               RedisStream.FEATURE_STREAM, e)
                try:
                    await _ensure_consumer_group()
                except Exception:
                    logger.error("Consumer group recreate failed — retrying in 5s",
                                 exc_info=True)
                    await asyncio.sleep(5)
                continue
            logger.error("Stream consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)
        except Exception:
            logger.error("Stream consumer error — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)


async def _get_operational_timeframe() -> str:
    """Return the active timeframe, falling back to the process setting."""
    operational_tf = os.getenv("NEXUS_OPERATIONAL_TF", "M5").upper()
    if _redis is None:
        return operational_tf
    try:
        dyn_raw = await _redis.get("nexus:dynamic:tf")
        if dyn_raw:
            selected = json.loads(dyn_raw).get("operational_tf")
            if selected:
                return str(selected).upper()
    except Exception:
        logger.debug("dynamic timeframe unavailable; using configured timeframe", exc_info=True)
    return operational_tf


def _feature_history_key(symbol: str, timeframe: str) -> str:
    """Keep next-bar samples isolated by symbol and prediction horizon."""
    return f"{ML_FEATURE_HISTORY_PREFIX}{symbol.strip().upper()}:{timeframe.strip().upper()}"


async def _handle_feature_event(msg_id: str, raw: dict[str, str]) -> None:
    assert _redis is not None and _ensemble is not None
    processed_successfully = False

    try:
        symbol = raw.get("symbol", "")
        timeframe = str(raw.get("timeframe", "")).upper()

        # Features can arrive in two formats:
        # 1. Single JSON blob under key "features"
        # 2. Flat hash keys like "features.ema_9", "features.rsi", etc.
        features_str = raw.get("features")
        if features_str is not None:
            # Format 1: nested JSON string
            if isinstance(features_str, str):
                features_dict = json.loads(features_str.replace("'", '"'))
            else:
                features_dict = features_str
        else:
            # Format 2: extract from flat "features.*" keys
            prefix = "features."
            features_dict = {}
            for k, v in raw.items():
                if k.startswith(prefix):
                    feat_name = k[len(prefix):]
                    try:
                        features_dict[feat_name] = float(v)
                    except (ValueError, TypeError):
                        features_dict[feat_name] = v  # keep strings like trend_direction

        if not features_dict:
            logger.warning("Empty features for %s — skipping event %s", symbol, msg_id)
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        # Recompute dynamic TF on M5 probe bars (scalping anchor)
        if timeframe == "M5":
            try:
                from datetime import datetime, timezone

                from services.nexus_ml.traders.trading_mode import (
                    detect_session,
                    get_current_config,
                    select_operational_tf,
                )

                cfg = get_current_config()
                session = detect_session(datetime.now(timezone.utc).hour)
                spread = float(features_dict.get("spread", features_dict.get("spread_pips", 0)) or 0)
                avg_sp = float(features_dict.get("avg_spread", spread) or spread or 1.0)
                auto = True
                try:
                    from shared import runtime_settings as _rs
                    auto = bool(_rs.get_cached_settings().get("auto_tf_selection", True))
                except Exception:
                    pass
                sel = select_operational_tf(
                    cfg, session, features_dict, auto=auto,
                    current_spread=spread, avg_spread=avg_sp,
                )
                from datetime import timezone as tz
                await _redis.set(
                    "nexus:dynamic:tf",
                    json.dumps({
                        "operational_tf": sel.operational_tf,
                        "confirmation_tfs": sel.confirmation_tfs,
                        "base_tf": sel.base_tf,
                        "reason": sel.reason,
                        "vol_regime": sel.vol_regime,
                        "session": sel.session,
                        "auto_selected": sel.auto_selected,
                        "updated_at": datetime.now(tz.utc).isoformat(),
                    }),
                    ex=180,
                )
            except Exception:
                logger.debug("dynamic_tf update skipped", exc_info=True)

        # Only signal on the live operational TF to avoid triple-firing.
        operational_tf = await _get_operational_timeframe()
        if timeframe and timeframe != operational_tf:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        now = time.time()
        last = _last_signal_ts.get(symbol, 0.0)
        if last and (now - last) < SIGNAL_COOLDOWN_SEC:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        # Decide: this symbol's ML ensemble (if trained) or rule-based fallback
        ensemble = _get_symbol_ensemble(symbol, operational_tf)
        any_model_loaded = any(ensemble.models_status().values())

        if any_model_loaded:
            # Use trained ML models for THIS symbol
            feature_array = ensemble.build_feature_array(features_dict)
            signal: EnsembleSignal = ensemble.predict(feature_array)
            signal_source = "ml_ensemble"
        elif _rule_based is not None:
            # Fallback: rule-based signal from real technical indicators
            signal = _rule_based.predict(features_dict)
            signal_source = "rule_based"
        else:
            # Should never happen — both are None
            logger.error("No signal generator available — skipping event %s", msg_id)
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        direction_map = {"BUY": Verdict.BUY, "SELL": Verdict.SELL}
        verdict = direction_map.get(signal.direction, Verdict.NO_TRADE)

        # Filter to numeric-only for SignalEvent (Pydantic expects dict[str, float])
        numeric_features = {k: v for k, v in features_dict.items() if isinstance(v, (int, float))}

        # Accumulate feature history for model training on EVERY processed bar —
        # not just bars that happen to produce an actionable BUY/SELL verdict.
        # Gating this behind the NO_TRADE return starved the walk-forward
        # trainer's min_train_samples threshold for weeks (rule-based/ensemble
        # signals are NO_TRADE most of the time by design).
        try:
            from datetime import datetime, timezone
            close = float(features_dict.get("close", 0))
            bar_time = raw.get("bar_timestamp") or features_dict.get("bar_timestamp")
            if not bar_time:
                raise ValueError("feature event is missing source bar timestamp")
            if str(bar_time).isdigit():
                timestamp_ms = int(bar_time)
                if timestamp_ms < 10_000_000_000:
                    timestamp_ms *= 1000
            else:
                parsed_time = datetime.fromisoformat(str(bar_time).replace("Z", "+00:00"))
                if parsed_time.tzinfo is None:
                    parsed_time = parsed_time.replace(tzinfo=timezone.utc)
                timestamp_ms = int(parsed_time.timestamp() * 1000)
            ohlcv = {
                "open": float(features_dict.get("open", 0)),
                "high": float(features_dict.get("high", 0)),
                "low": float(features_dict.get("low", 0)),
                "close": close,
                "volume": float(features_dict.get("volume", 0)),
            }
            pending_key = f"nexus:ml:pending_label:{symbol}:{timeframe}"
            history_key = _feature_history_key(symbol, timeframe)
            current_bar = {
                "timestamp": timestamp_ms,
                "timeframe": timeframe,
                "close": close,
                "features": numeric_features,
                "ohlcv": ohlcv,
            }
            previous_raw = await _redis.get(pending_key)
            previous = json.loads(previous_raw) if previous_raw else None
            next_pending, completed = advance_pending_bar(previous, current_bar)
            if completed is not None or next_pending != previous:
                pipe = _redis.pipeline(transaction=True)
                pipe.set(pending_key, json.dumps(next_pending))
                if completed is not None:
                    completed["timestamp"] = datetime.fromtimestamp(
                        completed["timestamp"] / 1000, tz=timezone.utc,
                    ).isoformat()
                    pipe.rpush(history_key, json.dumps(completed))
                    pipe.ltrim(history_key, -10000, -1)
                await pipe.execute()
        except Exception:
            logger.warning("Failed to accumulate next-bar feature history for %s/%s", symbol, timeframe, exc_info=True)

        if verdict == Verdict.NO_TRADE:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)
            return

        model_provenance: dict[str, Any] = {}
        if signal_source == "ml_ensemble":
            model_provenance = {
                "generation_id": getattr(ensemble, "generation_id", None),
                "trained_at": getattr(ensemble, "trained_at", None),
                "data_window": getattr(ensemble, "data_window", None),
            }
        # Optional signal risk fields — populate only when the source feature
        # context actually carries them; never fabricate values.
        def _opt_float(features: dict[str, float], *keys: str) -> float | None:
            for k in keys:
                v = features.get(k)
                if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0:
                    return float(v)
            return None

        _gid_raw = features_dict.get("group_id")
        event = SignalEvent(
            source=ServiceName.ML,
            symbol=symbol,
            timeframe=timeframe,
            direction=verdict,
            confidence=signal.confidence,
            features=numeric_features,
            ml_scores=signal.individual_scores,
            atr=_opt_float(numeric_features, "atr", "atr_14"),
            stop_atr=_opt_float(numeric_features, "stop_atr"),
            target_atr=_opt_float(numeric_features, "target_atr"),
            max_holding_hours=_opt_float(numeric_features, "max_holding_hours"),
            group_id=(str(_gid_raw) if isinstance(_gid_raw, str) and _gid_raw else None),
            data={"model_provenance": model_provenance} if model_provenance else {},
        )

        await _redis.xadd(
            RedisStream.SIGNAL_STREAM,
            event.to_stream_dict(),
            maxlen=STREAM_MAX_LEN,
        )

        _last_signal_ts[symbol] = now
        processed_successfully = True

        logger.info(
            "Signal published [%s]: %s %s conf=%.3f regime=%s anomaly=%s",
            signal_source, symbol, signal.direction, signal.confidence,
            signal.regime, signal.is_anomaly,
        )

    except Exception:
        logger.error("Failed to handle feature event %s", msg_id, exc_info=True)
    finally:
        # Keep failed entries pending for retry/recovery instead of silently
        # discarding them. Expected no-op/drop paths acknowledge explicitly.
        if processed_successfully:
            await _redis.xack(RedisStream.FEATURE_STREAM, CONSUMER_GROUP, msg_id)


# ── Helper functions ──────────────────────────────────────────────────────────


async def _get_latest_features(symbol: str, timeframe: str) -> dict[str, float] | None:
    assert _redis is not None
    cache_key = f"nexus:features:{symbol}:{timeframe.strip().upper()}"
    raw = await _redis.get(cache_key)
    if raw is not None:
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "features" in data:
                declared_timeframe = data.get("timeframe")
                if declared_timeframe and str(declared_timeframe).strip().upper() != timeframe.strip().upper():
                    return None
                return data["features"]
            return data
        except (json.JSONDecodeError, TypeError):
            return None
    return None


async def _fetch_training_data(
    symbols: list[str],
    *,
    timeframe: str | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]] | None:
    """Fetch historical feature data from Redis/DuckDB for training.

    Returns (X, y, timestamps, feature_names) or None if no data.
    """
    assert _redis is not None
    selected_timeframe = (timeframe or await _get_operational_timeframe()).upper()

    all_features: list[list[float]] = []
    all_labels: list[int] = []
    all_timestamps: list[str] = []
    feature_names: list[str] = []

    for symbol in symbols:
        history_key = _feature_history_key(symbol, selected_timeframe)
        raw_list = await _redis.lrange(history_key, 0, -1)

        for raw in raw_list:
            try:
                record = json.loads(raw)
                # Older history rows have no timeframe and cannot be safely
                # assigned to a prediction horizon; keep them stored but out
                # of training rather than mixing them with current samples.
                if str(record.get("timeframe", "")).upper() != selected_timeframe:
                    continue
                feats = record.get("features", {})
                label = record.get("label")
                ts = record.get("timestamp", "")

                if not feats or label is None:
                    continue

                if not feature_names:
                    feature_names = list(feats.keys())

                all_features.append([feats.get(k, 0.0) for k in feature_names])
                all_labels.append(int(label))
                all_timestamps.append(ts)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    if not all_features:
        return None

    X = np.array(all_features, dtype=np.float64)
    y = np.array(all_labels, dtype=np.int64)
    normalized_timestamps = []
    for value in all_timestamps:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        normalized_timestamps.append(
            parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        )
    timestamps = np.array(normalized_timestamps, dtype="datetime64[s]")

    return X, y, timestamps, feature_names


async def _report_training_run(report: dict[str, Any]) -> None:
    """Best-effort: register this training attempt in nexus-data (ml.training_runs).

    Never raises — the training pipeline must not depend on the registry being
    reachable. Dictionary mapping: ml.training_runs / ml.model_registry_events."""
    base=os.getenv("NEXUS_DATA_URL","http://127.0.0.1:9001").rstrip("/")
    secret=os.getenv("NEXUS_INTERNAL_API_SECRET","").strip()
    if not secret:
        logger.info("ml_runs.skipped no internal secret configured")
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp=await client.post(f"{base}/api/data/ml/training-run",
                                   headers={"X-Nexus-Internal-Secret":secret},
                                   json=report)
            if resp.status_code>=400:
                logger.warning("ml_runs.record_failed status=%s body=%s",resp.status_code,resp.text[:200])
            else:
                logger.info("ml_runs.recorded run_id=%s decision=%s",report.get("run_id"),report.get("decision"))
    except Exception:
        logger.warning("ml_runs.report_unreachable",exc_info=True)


async def _auto_retrain_loop() -> None:
    """Background task: trigger ensemble retraining when enough new feature data accumulates.

    Checks every NEXUS_RETRAIN_CHECK_INTERVAL_SEC seconds. Skips if:
    - Less than NEXUS_RETRAIN_MIN_SAMPLES records in feature history
    - Less than NEXUS_RETRAIN_COOLDOWN_HOURS since the last retrain
    - Training is already in progress
    """
    global _training_in_progress, _training_started_ts, _ensemble

    await asyncio.sleep(60)  # Let the service fully start before first check

    while True:
        try:
            if _training_in_progress and _training_started_ts is not None:
                if (time.time() - _training_started_ts) > _TRAINING_TIMEOUT_SEC:
                    logger.error(
                        "auto_retrain.reclaim_stale running_for=%.0fs limit=%ds",
                        time.time() - _training_started_ts, _TRAINING_TIMEOUT_SEC,
                    )
                    _training_in_progress = False
                    _training_started_ts = None
            if _redis is None or _training_in_progress:
                await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                continue

            # Check cooldown
            last_ts_raw = await _redis.get(_RETRAIN_LAST_KEY)
            if last_ts_raw:
                elapsed_h = (time.time() - float(last_ts_raw)) / 3600
                if elapsed_h < _RETRAIN_COOLDOWN_HOURS:
                    await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                    continue

            # Gate retraining on samples from the horizon this run will train.
            timeframe = await _get_operational_timeframe()
            total_samples, _per_symbol = await _count_timeframe_samples(_RETRAIN_SYMBOLS, timeframe)

            if total_samples < _RETRAIN_MIN_SAMPLES:
                logger.info(
                    "auto_retrain.skipped samples=%d/%d",
                    total_samples, _RETRAIN_MIN_SAMPLES,
                )
                await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)
                continue

            logger.info(
                "auto_retrain.triggered samples=%d symbols=%s",
                total_samples, _RETRAIN_SYMBOLS,
            )

            import uuid
            task_id = f"auto_{uuid.uuid4().hex[:8]}"
            _training_in_progress = True
            _training_started_ts = time.time()

            try:
                # Retrain each symbol/timeframe into its own generation directory.
                total_folds = 0
                new_status: dict[str, dict[str, bool]] = {}
                candidate_outcomes: list[dict[str, Any]] = []
                for sym in _RETRAIN_SYMBOLS:
                    data = await _fetch_training_data([sym], timeframe=timeframe)
                    if data is None:
                        logger.warning("auto_retrain.no_data symbol=%s", sym)
                        candidate_outcomes.append({
                            "symbol": sym, "decision": "rejected", "reason": "no_training_data",
                        })
                        import uuid as _uuid
                        await _report_training_run({
                            "run_id": f"mlrun:{task_id}:{sym}:{timeframe}",
                            "symbol": sym, "timeframe": timeframe,
                            "generation": None, "decision": "rejected",
                            "reason": "no_training_data", "fold_count": 0, "metrics": {},
                        })
                        continue
                    cfg = WalkForwardConfig(
                        train_months=6,
                        val_months=1,
                        step_months=2,
                    )
                    outcome, results = await _train_symbol_candidate(sym, timeframe, data, cfg, task_id)
                    total_folds += len(results)
                    candidate_outcomes.append(outcome)
                    import uuid as _uuid
                    await _report_training_run({
                        "run_id": f"mlrun:{task_id}:{sym}:{timeframe}",
                        "symbol": sym, "timeframe": timeframe,
                        "generation": outcome.get("generation"),
                        "decision": outcome.get("decision", "rejected"),
                        "reason": str(outcome.get("reason") or "")[:250] or None,
                        "fold_count": int(outcome.get("fold_count") or 0),
                        "metrics": outcome.get("metrics") or {},
                        "data_window": outcome.get("data_window") or None,
                    })
                    if outcome["decision"] == "promoted":
                        new_status[f"{sym}:{timeframe}"] = _get_symbol_ensemble(sym, timeframe).models_status()
                    logger.info(
                        "auto_retrain.symbol_done symbol=%s decision=%s reason=%s folds=%d",
                        sym, outcome["decision"], outcome["reason"], len(results),
                    )

                logger.info("auto_retrain.complete folds=%d task=%s", total_folds, task_id)
                await _redis.set(_RETRAIN_LAST_KEY, str(time.time()), ex=86_400 * 7)

                # Publish retrain event to Redis for dashboard visibility
                try:
                    await _redis.set(
                        "nexus:ml:last_retrain_result",
                        json.dumps({
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "samples": int(total_samples),
                            "folds": total_folds,
                            "models": new_status,
                            "candidate_outcomes": candidate_outcomes,
                        }),
                        ex=86_400 * 2,
                    )
                except Exception:
                    pass

            finally:
                _training_in_progress = False
                _training_started_ts = None

        except asyncio.CancelledError:
            break
        except Exception:
            logger.error("auto_retrain.error", exc_info=True)

        await asyncio.sleep(_RETRAIN_CHECK_INTERVAL)


async def _heartbeat_loop() -> None:
    assert _redis is not None
    while True:
        try:
            from shared.events import SystemHealthEvent
            import psutil

            event = SystemHealthEvent(
                source=ServiceName.ML,
                service_name=ServiceName.ML,
                status="healthy",
                cpu_pct=psutil.cpu_percent(),
                ram_pct=psutil.virtual_memory().percent,
            )
            await _redis.xadd(
                RedisStream.SYSTEM_HEALTH_STREAM,
                event.to_stream_dict(),
                maxlen=STREAM_MAX_LEN,
            )
        except Exception:
            logger.debug("Heartbeat failed", exc_info=True)

        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.nexus_ml.main:app",
        host="127.0.0.1",
        port=8003,
        reload=False,
        log_level="info",
    )
