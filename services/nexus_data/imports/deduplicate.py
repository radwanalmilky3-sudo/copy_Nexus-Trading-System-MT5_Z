"""Deterministic in-memory deduplication for canonical records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, TypeVar

from .contracts import CanonicalOHLCV, CanonicalTick, canonical_record_key

Record = TypeVar("Record", CanonicalOHLCV, CanonicalTick)
Key = TypeVar("Key")


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    records: tuple[CanonicalOHLCV | CanonicalTick, ...]
    duplicate_count: int
    duplicate_keys: tuple[tuple[object, ...], ...]


def deduplicate(records: Iterable[Record], *, key: Callable[[Record], Key] | None = None) -> DeduplicationResult:
    """Keep the first occurrence while preserving input order."""
    key_fn = key or canonical_record_key
    seen: set[object] = set()
    unique: list[Record] = []
    duplicate_keys: list[tuple[object, ...]] = []
    for record in records:
        record_key = key_fn(record)
        if record_key in seen:
            duplicate_keys.append(_key_tuple(record_key))
            continue
        seen.add(record_key)
        unique.append(record)
    return DeduplicationResult(tuple(unique), len(duplicate_keys), tuple(duplicate_keys))


def ohlcv_key(record: CanonicalOHLCV) -> tuple[object, ...]:
    return (record.symbol, record.timeframe, record.timestamp)


def tick_key(record: CanonicalTick) -> tuple[object, ...]:
    return canonical_record_key(record)[1:]


def _key_tuple(value: object) -> tuple[object, ...]:
    return value if isinstance(value, tuple) else (value,)
