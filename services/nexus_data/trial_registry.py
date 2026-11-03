"""DuckDB-backed disclosure registry for research trial families (Phase 5ج).

Every family of hypotheses tested during research/evaluation must be disclosed
here (family_id + per-trial p-values + FDR-adjusted q-values) BEFORE a model
may be promoted.  Absence of a disclosed family is a hard rejection
("absence of a record => reject") at the promotion gate in
``services.nexus_ml.model_promotion``.

When NEXUS_DATA_URL is set, synchronous authenticated HTTP delegates all
storage to nexus-data's locked connection, with no local fallback.
Standalone mode uses TRIAL_REGISTRY_DB (or DUCKDB_PATH) and explicitly
closes its connection. Failed family disclosure returns None, never q-values;
partial or unavailable families cannot pass the promotion gate.
"""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import structlog

from services.nexus_ml.statistical_gates import (
    FDRMethod,
    DEFAULT_FDR_THRESHOLD,
    benjamini_hochberg,
    benjamini_yekutieli,
    minimum_resamples_for_fdr,
)

logger = structlog.get_logger("nexus_data.trial_registry")

DEFAULT_METHOD: FDRMethod = "bh"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS research_trials (
    trial_id      VARCHAR,
    family_id     VARCHAR,
    p_value       DOUBLE,
    q_value       DOUBLE,
    method        VARCHAR,
    total_trials  BIGINT,
    min_resamples BIGINT,
    created_at    TIMESTAMP,
    meta          VARCHAR
)
"""


def _db_path() -> str:
    override = os.getenv("TRIAL_REGISTRY_DB", "").strip()
    if override:
        return override
    return os.getenv("DUCKDB_PATH", "./data/nexus.duckdb")


def _q_values(p_values: Sequence[float], method: str) -> list[float]:
    if method == "by":
        return benjamini_yekutieli(p_values)
    if method != "bh":
        raise ValueError(f"unknown FDR method: {method!r}")
    return benjamini_hochberg(p_values)


def _connect() -> Any:
    import duckdb  # imported lazily so the module imports without duckdb

    path = Path(_db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(path))
    conn.execute(_SCHEMA_SQL)
    return conn


def _remote(action: str, payload: dict[str, Any]) -> Any:
    """Never fall back to a local writer when the service is configured."""
    import httpx

    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise RuntimeError("internal credential unavailable")
    url = os.environ["NEXUS_DATA_URL"].strip().rstrip("/")
    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
        response = client.post(
            f"{url}/internal/trials/{action}", json=payload,
            headers={"X-Nexus-Internal-Secret": secret},
        )
        response.raise_for_status()
        body = response.json()
    if not isinstance(body, dict) or body.get("ok") is not True:
        raise ValueError("invalid registry response")
    return body["result"]


def _service_enabled() -> bool:
    return bool(os.getenv("NEXUS_DATA_URL", "").strip())


def _insert_rows(conn: Any, rows: list[list[Any]], *, single: bool = False) -> None:
    """Atomic disclosure, with content-identical retries and incremental trials.

    Family retries compare a multiset (including duplicate hypotheses), ignoring
    generated IDs/timestamps. Single-trial retries require the same trial_id;
    callers omitting that ID create a new trial and must retain the returned ID
    for a retry. Partial families remain unavailable to promotion.
    """
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(_SCHEMA_SQL)
        family = rows[0][1]
        existing = _read_rows(conn, family)
        fields = ("p_value", "q_value", "method", "total_trials", "min_resamples", "meta")
        def stored_content(row: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(row[key] for key in fields)
        def incoming_content(row: list[Any]) -> tuple[Any, ...]:
            return tuple(row[index] for index in (2, 3, 4, 5, 6, 8))
        insert = True
        if existing and not single:
            if not _complete(existing) or sorted(map(stored_content, existing)) != sorted(map(incoming_content, rows)):
                raise ValueError("family content conflict")
            insert = False
        elif existing:
            row = rows[0]
            same_id = [old for old in existing if old["trial_id"] == row[0]]
            if same_id:
                if len(same_id) != 1 or stored_content(same_id[0]) != incoming_content(row):
                    raise ValueError("trial content conflict")
                insert = False
            elif len(existing) >= row[5] or any(
                old["total_trials"] != row[5] or old["method"] != row[4]
                or old["min_resamples"] != row[6] or old["meta"] != row[8]
                for old in existing
            ):
                raise ValueError("family size or metadata conflict")
        if insert:
            conn.executemany("INSERT INTO research_trials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            logger.warning("trial_registry.rollback_failed")
        raise


def _read_rows(conn: Any, family_id: str) -> list[dict[str, Any]]:
    conn.execute(_SCHEMA_SQL)
    cursor = conn.execute(
        "SELECT trial_id, family_id, p_value, q_value, method, total_trials, "
        "min_resamples, created_at, meta FROM research_trials "
        "WHERE family_id = ? ORDER BY created_at, trial_id", [family_id],
    )
    return [dict(zip([d[0] for d in cursor.description], row)) for row in cursor.fetchall()]


def _complete(rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False
    try:
        total = rows[0]["total_trials"]
        method = rows[0]["method"]
        return (
            total == len(rows) and total > 0 and method in ("bh", "by")
            and len({r["trial_id"] for r in rows}) == total
            and all(r["total_trials"] == total and r["method"] == method
                    and math.isfinite(float(r["p_value"])) and 0 <= float(r["p_value"]) <= 1
                    and math.isfinite(float(r["q_value"])) and 0 <= float(r["q_value"]) <= 1
                    for r in rows)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _make_rows(family_id: str, p_values: Sequence[float], method: str,
               meta: dict[str, Any] | None = None) -> tuple[list[float], list[list[Any]]]:
    if not isinstance(family_id, str) or not family_id.strip():
        raise ValueError("empty family")
    ps = [float(p) for p in p_values]
    qs = _q_values(ps, method)
    minimum = minimum_resamples_for_fdr(len(ps), DEFAULT_FDR_THRESHOLD, method=method)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [[uuid.uuid4().hex, family_id, p, q, method, len(ps), minimum, now,
             json.dumps(meta or {}, sort_keys=True, default=str)] for p, q in zip(ps, qs)]
    return qs, rows


def record_trial(
    *,
    family_id: str,
    p_value: float,
    trial_id: str | None = None,
    q_value: float | None = None,
    method: str = DEFAULT_METHOD,
    total_trials: int | None = None,
    min_resamples: int | None = None,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Insert one trial; multi-trial families remain undisclosed until complete."""
    try:
        payload = dict(family_id=family_id, p_value=p_value, trial_id=trial_id,
                       q_value=q_value, method=method, total_trials=total_trials,
                       min_resamples=min_resamples, meta=meta)
        if _service_enabled():
            result = _remote("record", payload)
            return result if isinstance(result, str) and result else None
        row = _single_row(**payload)
        with closing(_connect()) as conn:
            _insert_rows(conn, [row], single=True)
        return row[0]
    except Exception:
        logger.warning("trial_registry.record_failed")
        return None


def _single_row(*, family_id: str, p_value: float, trial_id: str | None = None,
                q_value: float | None = None, method: str = DEFAULT_METHOD,
                total_trials: int | None = None, min_resamples: int | None = None,
                meta: dict[str, Any] | None = None) -> list[Any]:
    _, rows = _make_rows(family_id, [p_value], method, meta)
    row = rows[0]
    if q_value is not None:
        q = float(q_value)
        if not math.isfinite(q) or not 0 <= q <= 1:
            raise ValueError("invalid q")
        row[3] = q
    total = 1 if total_trials is None else int(total_trials)
    if total < 1:
        raise ValueError("invalid total")
    row[0] = trial_id or row[0]
    row[5] = total
    row[6] = (minimum_resamples_for_fdr(total, DEFAULT_FDR_THRESHOLD, method=method)
              if min_resamples is None else int(min_resamples))
    if row[6] < 1:
        raise ValueError("invalid resamples")
    return row


def record_family(
    family_id: str,
    p_values: Sequence[float],
    *,
    method: str = DEFAULT_METHOD,
    meta: dict[str, Any] | None = None,
) -> list[float] | None:
    """Return q-values only after durable atomic disclosure, otherwise None.

    None is required by disclose_promotion_family's existing caller contract.
    """
    try:
        qs, rows = _make_rows(family_id, p_values, method, meta)
        if _service_enabled():
            result = _remote("family", dict(family_id=family_id, p_values=list(p_values),
                                            method=method, meta=meta))
            if not isinstance(result, list) or result != qs:
                raise ValueError("invalid disclosure acknowledgement")
        else:
            with closing(_connect()) as conn:
                _insert_rows(conn, rows)
        return qs
    except Exception:
        logger.warning("trial_registry.family_failed")
        return None


def get_family(family_id: str) -> list[dict[str, Any]]:
    """Return stored rows; callers must check completeness before promotion."""
    if not family_id:
        return []
    try:
        if _service_enabled():
            rows = _remote("get", {"family_id": family_id})
            if not isinstance(rows, list) or any(
                not isinstance(r, dict) or r.get("family_id") != family_id for r in rows
            ):
                raise ValueError("invalid family response")
            return rows
        with closing(_connect()) as conn:
            return _read_rows(conn, family_id)
    except Exception:
        logger.warning("trial_registry.get_failed")
        return []


def has_disclosed_family(family_id: str) -> bool:
    """Partial, corrupt or unavailable families are never disclosed."""
    return _complete(get_family(family_id))


def best_family_q_value(family_id: str) -> float | None:
    rows = get_family(family_id)
    return min(float(r["q_value"]) for r in rows) if _complete(rows) else None
