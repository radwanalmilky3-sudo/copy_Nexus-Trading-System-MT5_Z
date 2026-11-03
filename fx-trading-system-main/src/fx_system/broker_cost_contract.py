"""Broker-neutral historical financing and forward-quote data contract.

The contract separates three claims which must not be conflated:

* a CSV is structurally valid;
* a sidecar manifest proves which exact CSV bytes were reviewed;
* an external review established that the source is genuine target-broker or
  tradable-market history.

Neither a quality label nor a locally generated hash proves the third claim.
Consequently every public entry point fails closed when the target legal
entity, account currency, source evidence, or historical coverage is missing.
No function in this module approves trading or formal net returns.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

CostVerdict = Literal[
    "cost_incomplete_research_only",
    "software_fixture_only",
    "historical_market_cost_ready",
]
CostDatasetKind = Literal["broker_financing_schedule", "tradable_forward_quotes"]
CostProductProfile = Literal["rolling_spot_margin", "spot_plus_forward"]

SWAP_REQUIRED_COLUMNS: tuple[str, ...] = (
    "symbol",
    "effective_time",
    "available_time",
    "long_financing",
    "short_financing",
    "unit",
    "day_count",
    "source",
    "provenance",
    "quote_quality",
    "version",
    "broker_entity",
    "account_currency",
    "triple_swap_weekday",
    "rollover_multiplier",
)
FORWARD_REQUIRED_COLUMNS: tuple[str, ...] = (
    "symbol",
    "observation_time",
    "available_time",
    "tenor",
    "bid_points",
    "ask_points",
    "points_unit",
    "source",
    "provenance",
    "quote_quality",
    "version",
    "broker_entity",
)
ALLOWED_SWAP_UNITS = frozenset(
    {"account_currency_per_unit", "pips", "quote_currency_per_unit"}
)
ALLOWED_DAY_COUNTS = frozenset({"actual_360", "actual_365", "broker_schedule"})
ALLOWED_TENORS = frozenset({"1M", "3M"})
ALLOWED_POINTS_UNITS = frozenset({"absolute_price", "pips"})
ALLOWED_TRIPLE_SWAP_WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "varies_by_symbol"}
)
ALLOWED_SWAP_QUALITIES = frozenset(
    {
        "historical_target_broker_schedule",
        "vendor_historical_schedule",
        "public_broker_history_retrieved_later_research_only",
        "software_fixture",
        "unknown_unverified",
    }
)
ALLOWED_FORWARD_QUALITIES = frozenset(
    {
        "historical_tradable_bid_ask",
        "historical_mid_only",
        "software_fixture",
        "unknown_unverified",
    }
)
HISTORICAL_SWAP_QUALITY = "historical_target_broker_schedule"
HISTORICAL_FORWARD_QUALITY = "historical_tradable_bid_ask"
RESEARCH_ONLY_PUBLIC_BROKER_SWAP_QUALITY = (
    "public_broker_history_retrieved_later_research_only"
)
ALLOWED_PRODUCT_PROFILES: frozenset[str] = frozenset(
    {"rolling_spot_margin", "spot_plus_forward"}
)
DEFAULT_PRODUCT_PROFILE: CostProductProfile = "spot_plus_forward"

DEFAULT_COVERAGE_START = "2016-01-01T00:00:00Z"
DEFAULT_COVERAGE_END_EXCLUSIVE = "2026-01-01T00:00:00Z"

_SYMBOL_PATTERN = re.compile(r"^[A-Z]{6}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_EXPLICIT_ZONE_PATTERN = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$", re.IGNORECASE)


class BrokerCostContractError(ValueError):
    """Raised when cost inputs violate the broker-neutral contract."""


@dataclass(frozen=True)
class ImportedCostDataset:
    """Validated CSV plus byte-integrity metadata; not proof of source authenticity."""

    dataset_kind: CostDatasetKind
    frame: pd.DataFrame
    csv_path: Path
    csv_sha256: str
    manifest_path: Path | None
    manifest_verified: bool
    manifest_reason: str


@dataclass(frozen=True)
class CostCoverageReport:
    schema_version: int
    generated_at_utc: str
    coverage_start: str
    coverage_end_exclusive: str
    broker_entity: str | None
    account_currency: str | None
    product_profile: CostProductProfile
    swap_symbols_present: tuple[str, ...]
    forward_symbols_present: tuple[str, ...]
    required_symbols: tuple[str, ...]
    swap_row_count: int
    forward_row_count: int
    swap_coverage_fraction: float
    forward_coverage_fraction: float
    swap_stale_gaps: int
    forward_stale_gaps: int
    swap_coverage_by_symbol: dict[str, dict[str, float | int]]
    forward_coverage_by_symbol: dict[str, dict[str, float | int]]
    swap_manifest_verified: bool
    forward_manifest_verified: bool
    swap_source_evidence_verified: bool
    forward_source_evidence_verified: bool
    historical_market_swap: bool
    historical_market_forward: bool
    issues: tuple[str, ...]
    verdict: CostVerdict
    formal_net_returns_ready: bool = False
    trading_approval: bool = False
    return_labels_opened: bool = False
    factor_outcome_evaluations_added: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise BrokerCostContractError(f"{label} missing columns: {missing}")


def _require_nonblank(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    for column in columns:
        values = frame[column].astype("string").str.strip()
        if values.isna().any() or values.eq("").any():
            raise BrokerCostContractError(f"{label} contains blank {column}")


def _normalize_utc(series: pd.Series, label: str) -> pd.Series:
    """Require explicit timezone information before normalizing to UTC."""
    for value in series:
        if isinstance(value, str) and not _EXPLICIT_ZONE_PATTERN.search(value.strip()):
            raise BrokerCostContractError(f"{label} contains timezone-naive timestamps")
        if isinstance(value, (pd.Timestamp, datetime)) and value.tzinfo is None:
            raise BrokerCostContractError(f"{label} contains timezone-naive timestamps")
    values = pd.to_datetime(series, utc=True, errors="coerce")
    if values.isna().any():
        raise BrokerCostContractError(f"{label} contains invalid timestamps")
    return values


def _normalize_symbols(series: pd.Series, label: str) -> pd.Series:
    symbols = series.astype("string").str.strip().str.upper().str.replace("/", "", regex=False)
    symbols_valid = symbols.map(lambda value: bool(_SYMBOL_PATTERN.fullmatch(value))).all()
    if symbols.isna().any() or not symbols_valid:
        raise BrokerCostContractError(f"{label} must contain six-letter currency pairs")
    return symbols


def _normalize_currency(series: pd.Series, label: str) -> pd.Series:
    values = series.astype("string").str.strip().str.upper()
    if values.isna().any() or not values.map(
        lambda value: bool(_CURRENCY_PATTERN.fullmatch(value))
    ).all():
        raise BrokerCostContractError(f"{label} must contain three-letter currency codes")
    return values


def _numeric_finite(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[column].isna().any() or not np.isfinite(frame[column]).all():
            raise BrokerCostContractError(f"{label} {column} must be finite numeric values")


def _upgrade_legacy_swap(result: pd.DataFrame) -> pd.DataFrame:
    if "long_financing" in result.columns or "swap_long_pips" not in result.columns:
        return result
    result = result.rename(
        columns={
            "swap_long_pips": "long_financing",
            "swap_short_pips": "short_financing",
        }
    )
    defaults: dict[str, object] = {
        "effective_time": result.get("available_time"),
        "unit": "pips",
        "day_count": "broker_schedule",
        "source": "legacy_unspecified",
        "provenance": "legacy_unverified",
        "quote_quality": "unknown_unverified",
        "version": "legacy",
        "broker_entity": "UNCONFIRMED",
        "account_currency": "USD",
        "triple_swap_weekday": "varies_by_symbol",
        "rollover_multiplier": 1.0,
    }
    for column, value in defaults.items():
        if column not in result.columns:
            result[column] = value
    return result


def validate_swap_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate broker-neutral historical swap/financing rows.

    Legacy ``swap_*_pips`` files remain readable for software compatibility but
    are explicitly downgraded to ``unknown_unverified`` and cannot pass audit.
    """
    if frame.empty:
        raise BrokerCostContractError("swap schedule is empty")
    result = frame.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    result = _upgrade_legacy_swap(result)
    _require_columns(result, SWAP_REQUIRED_COLUMNS, "swap schedule")
    _require_nonblank(
        result,
        (
            "source",
            "provenance",
            "quote_quality",
            "version",
            "broker_entity",
            "account_currency",
            "triple_swap_weekday",
        ),
        "swap schedule",
    )
    result["symbol"] = _normalize_symbols(result["symbol"], "swap symbol")
    result["effective_time"] = _normalize_utc(result["effective_time"], "swap effective_time")
    result["available_time"] = _normalize_utc(result["available_time"], "swap available_time")
    _numeric_finite(
        result,
        ("long_financing", "short_financing", "rollover_multiplier"),
        "swap",
    )
    negative_multiplier = result["rollover_multiplier"].lt(0)
    if negative_multiplier.any():
        raise BrokerCostContractError("swap rollover_multiplier must be non-negative")
    zero_multiplier = result["rollover_multiplier"].eq(0)
    nonzero_financing = result["long_financing"].ne(0) | result["short_financing"].ne(0)
    if (zero_multiplier & nonzero_financing).any():
        raise BrokerCostContractError(
            "swap rollover_multiplier may be zero only when long/short financing are both zero"
        )
    result["unit"] = result["unit"].astype("string").str.strip().str.lower()
    if not set(result["unit"]).issubset(ALLOWED_SWAP_UNITS):
        raise BrokerCostContractError(f"swap unit must be one of {sorted(ALLOWED_SWAP_UNITS)}")
    result["day_count"] = result["day_count"].astype("string").str.strip().str.lower()
    if not set(result["day_count"]).issubset(ALLOWED_DAY_COUNTS):
        raise BrokerCostContractError(
            f"swap day_count must be one of {sorted(ALLOWED_DAY_COUNTS)}"
        )
    result["quote_quality"] = (
        result["quote_quality"].astype("string").str.strip().str.lower()
    )
    if not set(result["quote_quality"]).issubset(ALLOWED_SWAP_QUALITIES):
        raise BrokerCostContractError(
            f"swap quote_quality must be one of {sorted(ALLOWED_SWAP_QUALITIES)}"
        )
    result["triple_swap_weekday"] = (
        result["triple_swap_weekday"].astype("string").str.strip().str.lower()
    )
    if not set(result["triple_swap_weekday"]).issubset(ALLOWED_TRIPLE_SWAP_WEEKDAYS):
        raise BrokerCostContractError(
            "triple_swap_weekday must be a weekday or varies_by_symbol"
        )
    result["account_currency"] = _normalize_currency(
        result["account_currency"], "swap account_currency"
    )
    duplicate_key = ["symbol", "effective_time", "available_time"]
    if result.duplicated(duplicate_key).any():
        raise BrokerCostContractError(f"duplicate swap rows for {duplicate_key}")
    return result.sort_values(duplicate_key).reset_index(drop=True)


def _upgrade_legacy_forward(result: pd.DataFrame) -> pd.DataFrame:
    if "bid_points" in result.columns or "forward_points_1m" not in result.columns:
        return result
    result = result.rename(columns={"forward_points_1m": "mid_points_1m"})
    defaults: dict[str, object] = {
        "tenor": "1M",
        "bid_points": result["mid_points_1m"],
        "ask_points": result["mid_points_1m"],
        "points_unit": "absolute_price",
        "source": "legacy_unspecified",
        "provenance": "legacy_unverified",
        "quote_quality": "historical_mid_only",
        "version": "legacy_mid_only",
        "broker_entity": "UNCONFIRMED",
        "_legacy_mid_only": True,
    }
    for column, value in defaults.items():
        if column not in result.columns:
            result[column] = value
    # A legacy quality label may say unknown; mid-only is still the strongest
    # admissible interpretation and never qualifies as tradable bid/ask.
    result["quote_quality"] = "historical_mid_only"
    return result


def validate_forward_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate historical tradable forward-point bid/ask rows."""
    if frame.empty:
        raise BrokerCostContractError("forward schedule is empty")
    result = frame.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    result = _upgrade_legacy_forward(result)
    _require_columns(result, FORWARD_REQUIRED_COLUMNS, "forward schedule")
    _require_nonblank(
        result,
        ("source", "provenance", "quote_quality", "version", "broker_entity"),
        "forward schedule",
    )
    result["symbol"] = _normalize_symbols(result["symbol"], "forward symbol")
    result["observation_time"] = _normalize_utc(
        result["observation_time"], "forward observation_time"
    )
    result["available_time"] = _normalize_utc(
        result["available_time"], "forward available_time"
    )
    if (result["available_time"] < result["observation_time"]).any():
        raise BrokerCostContractError("forward available_time cannot precede observation_time")
    result["tenor"] = result["tenor"].astype("string").str.strip().str.upper()
    if not set(result["tenor"]).issubset(ALLOWED_TENORS):
        raise BrokerCostContractError(f"forward tenor must be one of {sorted(ALLOWED_TENORS)}")
    _numeric_finite(result, ("bid_points", "ask_points"), "forward")
    if (result["ask_points"] < result["bid_points"]).any():
        raise BrokerCostContractError("forward ask_points cannot be below bid_points")
    result["points_unit"] = result["points_unit"].astype("string").str.strip().str.lower()
    if not set(result["points_unit"]).issubset(ALLOWED_POINTS_UNITS):
        raise BrokerCostContractError(
            f"points_unit must be one of {sorted(ALLOWED_POINTS_UNITS)}"
        )
    result["quote_quality"] = (
        result["quote_quality"].astype("string").str.strip().str.lower()
    )
    if not set(result["quote_quality"]).issubset(ALLOWED_FORWARD_QUALITIES):
        raise BrokerCostContractError(
            f"forward quote_quality must be one of {sorted(ALLOWED_FORWARD_QUALITIES)}"
        )
    if {"spot_bid", "spot_ask"}.issubset(result.columns):
        _numeric_finite(result, ("spot_bid", "spot_ask"), "forward")
        if (result["spot_ask"] < result["spot_bid"]).any():
            raise BrokerCostContractError("forward spot_ask cannot be below spot_bid")
    duplicate_key = ["symbol", "observation_time", "tenor", "available_time"]
    if result.duplicated(duplicate_key).any():
        raise BrokerCostContractError(f"duplicate forward rows for {duplicate_key}")
    return result.sort_values(duplicate_key).reset_index(drop=True)


def _manifest_catalog_columns(dataset_kind: CostDatasetKind) -> tuple[str, ...]:
    if dataset_kind == "broker_financing_schedule":
        return (
            "source",
            "provenance",
            "quote_quality",
            "version",
            "broker_entity",
            "account_currency",
        )
    return ("source", "provenance", "quote_quality", "version", "broker_entity")


def _catalog_records(frame: pd.DataFrame, columns: tuple[str, ...]) -> set[tuple[str, ...]]:
    return {
        tuple(str(value).strip() for value in row)
        for row in frame[list(columns)].drop_duplicates().itertuples(index=False, name=None)
    }


def _verify_manifest(
    *,
    csv_path: Path,
    dataset_kind: CostDatasetKind,
    frame: pd.DataFrame,
    manifest_path: Path,
) -> tuple[bool, str]:
    if not manifest_path.is_file():
        return False, "source manifest missing"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BrokerCostContractError(f"invalid source manifest {manifest_path}") from exc
    if payload.get("schema_version") != 1:
        raise BrokerCostContractError("cost source manifest schema_version must be 1")
    if payload.get("dataset_kind") != dataset_kind:
        raise BrokerCostContractError("cost source manifest dataset_kind mismatch")
    actual_hash = _sha256(csv_path)
    if payload.get("csv_sha256") != actual_hash:
        raise BrokerCostContractError("cost CSV hash does not match its source manifest")
    columns = _manifest_catalog_columns(dataset_kind)
    catalog = payload.get("source_catalog")
    if not isinstance(catalog, list) or not catalog:
        raise BrokerCostContractError("cost source manifest requires non-empty source_catalog")
    try:
        declared = {
            tuple(str(item[column]).strip() for column in columns)
            for item in catalog
            if isinstance(item, dict)
        }
    except KeyError as exc:
        raise BrokerCostContractError(
            f"cost source manifest catalog missing {exc.args[0]}"
        ) from exc
    actual = _catalog_records(frame, columns)
    undeclared = actual - declared
    if undeclared:
        raise BrokerCostContractError("cost rows contain source metadata absent from manifest")
    return True, "csv hash and row-level source catalog verified"


def load_cost_dataset(
    csv_path: str | Path,
    *,
    dataset_kind: CostDatasetKind,
    manifest_path: str | Path | None = None,
) -> ImportedCostDataset:
    """Load one canonical CSV and verify its adjacent source manifest when present."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = pd.read_csv(path)
    if dataset_kind == "broker_financing_schedule":
        frame = validate_swap_schedule(raw)
    elif dataset_kind == "tradable_forward_quotes":
        frame = validate_forward_schedule(raw)
    else:  # pragma: no cover - guarded by Literal for typed callers
        raise BrokerCostContractError(f"unsupported cost dataset kind: {dataset_kind}")
    sidecar = (
        Path(manifest_path)
        if manifest_path is not None
        else path.with_suffix(".manifest.json")
    )
    verified, reason = _verify_manifest(
        csv_path=path,
        dataset_kind=dataset_kind,
        frame=frame,
        manifest_path=sidecar,
    )
    return ImportedCostDataset(
        dataset_kind=dataset_kind,
        frame=frame,
        csv_path=path.resolve(),
        csv_sha256=_sha256(path),
        manifest_path=sidecar.resolve() if sidecar.is_file() else None,
        manifest_verified=verified,
        manifest_reason=reason,
    )


def _coverage_fraction(
    times: pd.Series,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_gap_days: int,
) -> tuple[float, int, float]:
    if times.empty:
        return 0.0, 1, float((end - start).total_seconds() / 86400.0)
    ordered = times.sort_values().drop_duplicates()
    in_range = ordered[(ordered >= start) & (ordered < end)]
    if in_range.empty:
        return 0.0, 1, float((end - start).total_seconds() / 86400.0)
    start_naive = start.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
    end_naive = (end - pd.Timedelta(1, unit="D")).tz_convert("UTC").to_pydatetime().replace(
        tzinfo=None
    )
    months = pd.period_range(start=start_naive, end=end_naive, freq="M")
    observed = {
        pd.Period(pd.Timestamp(stamp).tz_convert("UTC").date(), freq="M") for stamp in in_range
    }
    fraction = len(observed & set(months)) / max(len(months), 1)
    gaps = 0
    max_gap = 0.0
    previous = start
    for stamp in [*list(in_range), end]:
        delta_days = (stamp - previous).total_seconds() / 86400.0
        max_gap = max(max_gap, delta_days)
        if delta_days > max_gap_days:
            gaps += 1
        previous = stamp
    return float(fraction), gaps, float(max_gap)


def _coverage_by_symbol(
    frame: pd.DataFrame,
    *,
    time_column: str,
    required_symbols: tuple[str, ...],
    start: pd.Timestamp,
    end: pd.Timestamp,
    max_gap_days: int,
) -> tuple[float, int, dict[str, dict[str, float | int]]]:
    details: dict[str, dict[str, float | int]] = {}
    for symbol in required_symbols:
        fraction, gaps, max_gap = _coverage_fraction(
            frame.loc[frame["symbol"].eq(symbol), time_column],
            start=start,
            end=end,
            max_gap_days=max_gap_days,
        )
        details[symbol] = {
            "coverage_fraction": fraction,
            "stale_gap_count": gaps,
            "maximum_gap_days": max_gap,
        }
    return (
        min(item["coverage_fraction"] for item in details.values()),
        sum(int(item["stale_gap_count"]) for item in details.values()),
        details,
    )


def _entity_matches(series: pd.Series, expected: str) -> bool:
    return series.astype("string").str.strip().eq(expected.strip()).all()


def audit_cost_coverage(
    *,
    swap_frame: pd.DataFrame | None,
    forward_frame: pd.DataFrame | None,
    required_symbols: tuple[str, ...] | list[str],
    coverage_start: str = DEFAULT_COVERAGE_START,
    coverage_end_exclusive: str = DEFAULT_COVERAGE_END_EXCLUSIVE,
    broker_entity: str | None = None,
    account_currency: str | None = None,
    swap_manifest_verified: bool = False,
    forward_manifest_verified: bool = False,
    swap_source_evidence_verified: bool = False,
    forward_source_evidence_verified: bool = False,
    max_swap_gap_days: int = 8,
    max_forward_gap_days: int = 45,
    minimum_coverage_fraction: float = 0.90,
    product_profile: CostProductProfile = DEFAULT_PRODUCT_PROFILE,
) -> CostCoverageReport:
    """Audit every required symbol and fail closed on unverified provenance.

    ``*_manifest_verified`` proves byte integrity only. The separate
    ``*_source_evidence_verified`` flags must be supplied by a future external
    review workflow; this module never infers authenticity from labels.
    """
    if product_profile not in ALLOWED_PRODUCT_PROFILES:
        raise BrokerCostContractError(
            f"product_profile must be one of {sorted(ALLOWED_PRODUCT_PROFILES)}"
        )
    issues: list[str] = []
    normalized_entity = str(broker_entity).strip() if broker_entity else None
    normalized_account = str(account_currency).strip().upper() if account_currency else None
    if normalized_entity is None:
        issues.append("broker_entity unset; formal cost gate closed")
    if normalized_account is None:
        issues.append("account_currency unset; formal cost gate closed")
    elif not _CURRENCY_PATTERN.fullmatch(normalized_account):
        raise BrokerCostContractError("account_currency must be a three-letter currency code")
    required = tuple(
        dict.fromkeys(str(symbol).upper().replace("/", "") for symbol in required_symbols)
    )
    if not required:
        raise BrokerCostContractError("required_symbols cannot be empty")
    if not all(_SYMBOL_PATTERN.fullmatch(symbol) for symbol in required):
        raise BrokerCostContractError("required_symbols must be six-letter currency pairs")
    if not 0 <= minimum_coverage_fraction <= 1:
        raise BrokerCostContractError("minimum_coverage_fraction must be between 0 and 1")
    if max_swap_gap_days <= 0 or max_forward_gap_days <= 0:
        raise BrokerCostContractError("maximum gap days must be positive")

    start = pd.Timestamp(coverage_start)
    end = pd.Timestamp(coverage_end_exclusive)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    if end <= start:
        raise BrokerCostContractError("coverage end must be after start")

    swap_symbols: tuple[str, ...] = ()
    forward_symbols: tuple[str, ...] = ()
    swap_rows = 0
    forward_rows = 0
    swap_fraction = 0.0
    forward_fraction = 0.0
    swap_gaps = 0
    forward_gaps = 0
    swap_details: dict[str, dict[str, float | int]] = {}
    forward_details: dict[str, dict[str, float | int]] = {}
    historical_swap = False
    historical_forward = False

    if swap_frame is None:
        issues.append("swap schedule missing")
    else:
        swaps = validate_swap_schedule(swap_frame)
        swap_rows = len(swaps)
        swap_symbols = tuple(sorted(str(value) for value in swaps["symbol"].unique()))
        missing = [symbol for symbol in required if symbol not in set(swap_symbols)]
        if missing:
            issues.append(f"swap missing symbols: {missing}")
        swap_fraction, swap_gaps, swap_details = _coverage_by_symbol(
            swaps,
            time_column="effective_time",
            required_symbols=required,
            start=start,
            end=end,
            max_gap_days=max_swap_gap_days,
        )
        below = [
            symbol
            for symbol, detail in swap_details.items()
            if detail["coverage_fraction"] < minimum_coverage_fraction
        ]
        stale = [
            symbol for symbol, detail in swap_details.items() if detail["stale_gap_count"] > 0
        ]
        if below:
            issues.append(f"swap coverage below threshold for symbols: {below}")
        if stale:
            issues.append(f"swap stale gaps for symbols: {stale}")
        if not swap_manifest_verified:
            issues.append("swap source manifest not verified")
        if not swap_source_evidence_verified:
            issues.append("swap source authenticity not externally verified")
        entity_ok = bool(
            normalized_entity and _entity_matches(swaps["broker_entity"], normalized_entity)
        )
        if normalized_entity and not entity_ok:
            issues.append("swap broker_entity rows do not match requested legal entity")
        account_ok = bool(
            normalized_account and swaps["account_currency"].eq(normalized_account).all()
        )
        if normalized_account and not account_ok:
            issues.append("swap account_currency rows do not match requested account currency")
        quality_ok = swaps["quote_quality"].eq(HISTORICAL_SWAP_QUALITY).all()
        if not quality_ok:
            issues.append("swap rows are not verified target-broker historical schedules")
        triple_weekday_ok = not swaps["triple_swap_weekday"].eq("varies_by_symbol").any()
        if not triple_weekday_ok:
            issues.append("swap triple_swap_weekday is not explicit for every symbol")
        multi_day_symbols = set(
            swaps.loc[swaps["rollover_multiplier"].gt(1), "symbol"].astype(str)
        )
        missing_multi_day = [symbol for symbol in required if symbol not in multi_day_symbols]
        if missing_multi_day:
            issues.append(
                "swap history has no multi-day rollover evidence for symbols: "
                f"{missing_multi_day}"
            )
        historical_swap = bool(
            entity_ok
            and account_ok
            and quality_ok
            and triple_weekday_ok
            and not missing_multi_day
            and swap_manifest_verified
            and swap_source_evidence_verified
            and not missing
            and not below
            and not stale
        )

    forward_required = product_profile == "spot_plus_forward"
    if forward_frame is None:
        if forward_required:
            issues.append("forward schedule missing")
    else:
        forwards = validate_forward_schedule(forward_frame)
        forward_rows = len(forwards)
        forward_symbols = tuple(sorted(str(value) for value in forwards["symbol"].unique()))
        missing = [symbol for symbol in required if symbol not in set(forward_symbols)]
        if missing:
            issues.append(f"forward missing symbols: {missing}")
        forward_fraction, forward_gaps, forward_details = _coverage_by_symbol(
            forwards,
            time_column="observation_time",
            required_symbols=required,
            start=start,
            end=end,
            max_gap_days=max_forward_gap_days,
        )
        below = [
            symbol
            for symbol, detail in forward_details.items()
            if detail["coverage_fraction"] < minimum_coverage_fraction
        ]
        stale = [
            symbol for symbol, detail in forward_details.items() if detail["stale_gap_count"] > 0
        ]
        if below:
            issues.append(f"forward coverage below threshold for symbols: {below}")
        if stale:
            issues.append(f"forward stale gaps for symbols: {stale}")
        if not forward_manifest_verified:
            issues.append("forward source manifest not verified")
        if not forward_source_evidence_verified:
            issues.append("forward source authenticity not externally verified")
        entity_ok = bool(
            normalized_entity and _entity_matches(forwards["broker_entity"], normalized_entity)
        )
        if normalized_entity and not entity_ok:
            issues.append("forward broker_entity rows do not match requested legal entity")
        quality_ok = forwards["quote_quality"].eq(HISTORICAL_FORWARD_QUALITY).all()
        if not quality_ok:
            issues.append("forward rows are not verified tradable bid/ask quotes")
        incomplete_tenors = [
            symbol
            for symbol in required
            if set(forwards.loc[forwards["symbol"].eq(symbol), "tenor"]) != ALLOWED_TENORS
        ]
        if incomplete_tenors:
            issues.append(f"forward 1M/3M tenor set incomplete for symbols: {incomplete_tenors}")
        historical_forward = bool(
            entity_ok
            and quality_ok
            and not incomplete_tenors
            and forward_manifest_verified
            and forward_source_evidence_verified
            and not missing
            and not below
            and not stale
        )

    product_cost_ready = historical_swap and (historical_forward or not forward_required)
    verdict: CostVerdict = (
        "historical_market_cost_ready"
        if product_cost_ready
        else "cost_incomplete_research_only"
    )
    return CostCoverageReport(
        schema_version=3,
        generated_at_utc=_utc_now(),
        coverage_start=start.isoformat().replace("+00:00", "Z"),
        coverage_end_exclusive=end.isoformat().replace("+00:00", "Z"),
        broker_entity=normalized_entity,
        account_currency=normalized_account,
        product_profile=product_profile,
        swap_symbols_present=swap_symbols,
        forward_symbols_present=forward_symbols,
        required_symbols=required,
        swap_row_count=swap_rows,
        forward_row_count=forward_rows,
        swap_coverage_fraction=swap_fraction,
        forward_coverage_fraction=forward_fraction,
        swap_stale_gaps=swap_gaps,
        forward_stale_gaps=forward_gaps,
        swap_coverage_by_symbol=swap_details,
        forward_coverage_by_symbol=forward_details,
        swap_manifest_verified=swap_manifest_verified,
        forward_manifest_verified=forward_manifest_verified,
        swap_source_evidence_verified=swap_source_evidence_verified,
        forward_source_evidence_verified=forward_source_evidence_verified,
        historical_market_swap=historical_swap,
        historical_market_forward=historical_forward,
        issues=tuple(dict.fromkeys(issues)),
        verdict=verdict,
        formal_net_returns_ready=False,
        trading_approval=False,
        return_labels_opened=False,
        factor_outcome_evaluations_added=0,
    )


def load_swap_directory(directory: str | Path) -> pd.DataFrame:
    """Load legacy per-symbol swap CSVs as explicitly unverified research input."""
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(root)
    frames: list[pd.DataFrame] = []
    for path in sorted(root.glob("*.csv")):
        if path.name.startswith("_"):
            continue
        frame = pd.read_csv(path)
        if "symbol" not in frame.columns:
            frame = frame.copy()
            frame["symbol"] = path.stem.split(".")[0].upper().replace("/", "")
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no swap csv files in {root}")
    return validate_swap_schedule(pd.concat(frames, ignore_index=True))


def write_cost_coverage_report(report: CostCoverageReport, output: str | Path) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path.resolve()


def assert_formal_cost_ready(report: CostCoverageReport) -> None:
    """Hard gate: a coverage report cannot approve formal returns or trading."""
    if report.formal_net_returns_ready or report.trading_approval:
        raise BrokerCostContractError("cost report cannot self-approve formal readiness")
    detail = "; ".join(report.issues) if report.issues else report.verdict
    raise BrokerCostContractError(f"formal cost gate closed: {detail}")
