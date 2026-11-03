from __future__ import annotations

import hashlib
import json
import lzma
import os
import struct
import time
import warnings
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from .models import CurrencyPair, utc_timestamp

REQUIRED_COLUMNS = ("open", "high", "low", "close")
QUOTE_COLUMNS = tuple(
    f"{side}_{field}" for side in ("bid", "ask") for field in REQUIRED_COLUMNS
)

DUKASCOPY_PRICE_DIVISORS = {
    "AUDCAD": 100_000,
    "AUDCHF": 100_000,
    "AUDJPY": 1_000,
    "AUDNZD": 100_000,
    "AUDUSD": 100_000,
    "CADCHF": 100_000,
    "CADJPY": 1_000,
    "CHFJPY": 1_000,
    "EURAUD": 100_000,
    "EURCAD": 100_000,
    "EURCHF": 100_000,
    "EURGBP": 100_000,
    "EURJPY": 1_000,
    "EURNZD": 100_000,
    "EURUSD": 100_000,
    "GBPAUD": 100_000,
    "GBPCAD": 100_000,
    "GBPCHF": 100_000,
    "GBPJPY": 1_000,
    "GBPNZD": 100_000,
    "GBPUSD": 100_000,
    "NZDCAD": 100_000,
    "NZDCHF": 100_000,
    "NZDJPY": 1_000,
    "NZDUSD": 100_000,
    "USDCAD": 100_000,
    "USDCHF": 100_000,
    "USDJPY": 1_000,
    "USDNOK": 100_000,
    "USDSEK": 100_000,
}


def has_bid_ask(frame: pd.DataFrame) -> bool:
    return set(QUOTE_COLUMNS).issubset(frame.columns)


def _invalid_ohlc(frame: pd.DataFrame, prefix: str = "") -> pd.Series:
    columns = [f"{prefix}{column}" for column in REQUIRED_COLUMNS]
    open_, high, low, close = (frame[column] for column in columns)
    return (
        (low > pd.concat([open_, close], axis=1).min(axis=1))
        | (high < pd.concat([open_, close], axis=1).max(axis=1))
        | (high < low)
        | (frame[columns] <= 0).any(axis=1)
    )


def validate_bars(
    frame: pd.DataFrame,
    symbol: str = "unknown",
    invalid_ohlc: str = "raise",
) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(column).lower().replace(" ", "_") for column in result.columns]
    present_quote_columns = set(QUOTE_COLUMNS) & set(result)
    if present_quote_columns and present_quote_columns != set(QUOTE_COLUMNS):
        missing_quotes = sorted(set(QUOTE_COLUMNS) - set(result))
        raise ValueError(f"{symbol}: incomplete bid/ask OHLC columns {missing_quotes}")
    quote_mode = bool(present_quote_columns)
    if quote_mode:
        for column in QUOTE_COLUMNS:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        synchronized_mid = set(REQUIRED_COLUMNS).issubset(result.columns)
        if synchronized_mid:
            for field in REQUIRED_COLUMNS:
                result[field] = pd.to_numeric(result[field], errors="coerce")
        else:
            for field in REQUIRED_COLUMNS:
                result[field] = (result[f"bid_{field}"] + result[f"ask_{field}"]) / 2
    missing = set(REQUIRED_COLUMNS) - set(result.columns)
    if missing:
        raise ValueError(f"{symbol}: missing OHLC columns {sorted(missing)}")
    if not isinstance(result.index, pd.DatetimeIndex):
        timestamp_column = next(
            (name for name in ("timestamp", "datetime", "date") if name in result.columns), None
        )
        if timestamp_column is None:
            raise ValueError(f"{symbol}: expected DatetimeIndex or timestamp column")
        result.index = pd.to_datetime(result.pop(timestamp_column), utc=True)
    elif result.index.tz is None:
        result.index = result.index.tz_localize("UTC")
    else:
        result.index = result.index.tz_convert("UTC")
    result.index.name = "timestamp"
    if result.index.duplicated().any():
        raise ValueError(f"{symbol}: duplicate bar timestamps")
    result = result.sort_index()
    for column in REQUIRED_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if "volume" not in result:
        result["volume"] = 0.0
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce").fillna(0.0)
    result = result.dropna(subset=list(REQUIRED_COLUMNS))
    invalid = _invalid_ohlc(result)
    if quote_mode:
        crossed = ~np.isfinite(result[list(QUOTE_COLUMNS)]).all(axis=1)
        for field in REQUIRED_COLUMNS:
            crossed |= result[f"ask_{field}"] < result[f"bid_{field}"]
            crossed |= (result[field] < result[f"bid_{field}"]) | (
                result[field] > result[f"ask_{field}"]
            )
        invalid |= _invalid_ohlc(result, "bid_") | _invalid_ohlc(result, "ask_") | crossed
    if invalid.any():
        invalid_count = int(invalid.sum())
        if invalid_ohlc == "drop":
            warnings.warn(
                f"{symbol}: dropping {invalid_count} invalid provider OHLC rows",
                RuntimeWarning,
                stacklevel=2,
            )
            result = result.loc[~invalid]
        else:
            raise ValueError(f"{symbol}: {invalid_count} invalid OHLC rows")
    else:
        invalid_count = 0
    if len(result) < 2:
        raise ValueError(f"{symbol}: not enough valid bars")
    result.attrs["dropped_invalid_ohlc"] = invalid_count
    result.attrs["price_mode"] = "bid_ask" if quote_mode else "mid"
    if quote_mode:
        result["spread_open"] = result["ask_open"] - result["bid_open"]
        result["spread_close"] = result["ask_close"] - result["bid_close"]
    for column in ("swap_long_pips", "swap_short_pips"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def load_csv(path: str | Path, symbol: str | None = None) -> pd.DataFrame:
    csv_path = Path(path)
    frame = pd.read_csv(csv_path)
    return validate_bars(frame, symbol or csv_path.stem)


def load_csv_directory(directory: str | Path, symbols: list[str]) -> dict[str, pd.DataFrame]:
    root = Path(directory)
    manifest_path = root / "_data_manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    manifest_symbols = manifest.get("symbols", {})
    result: dict[str, pd.DataFrame] = {}
    for raw_symbol in symbols:
        symbol = CurrencyPair.parse(raw_symbol).symbol
        candidates = [root / f"{symbol}.csv", root / f"{symbol.lower()}.csv"]
        path = next((item for item in candidates if item.exists()), None)
        if path is None:
            raise FileNotFoundError(f"No CSV found for {symbol}; tried: {candidates}")
        expected_hash = manifest_symbols.get(symbol, {}).get("csv_sha256")
        if expected_hash is not None:
            with path.open("rb") as handle:
                actual_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(f"{symbol}: CSV SHA-256 does not match _data_manifest.json")
        frame = load_csv(path, symbol)
        source = manifest_symbols.get(symbol, {}).get("source", {})
        if isinstance(source, dict):
            frame.attrs.update(
                {
                    f"source_{key}": value
                    for key, value in source.items()
                    if isinstance(value, (str, int, float, bool)) or value is None
                }
            )
        frame.attrs["source_csv_hash_verified"] = expected_hash is not None
        frame.attrs["source_manifest_schema_version"] = manifest.get("schema_version")
        result[symbol] = frame
    return result


def save_csv_directory(data: Mapping[str, pd.DataFrame], directory: str | Path) -> None:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    csv_hashes: dict[str, str] = {}
    for symbol, frame in data.items():
        path = root / f"{symbol}.csv"
        frame.to_csv(path, index=True)
        with path.open("rb") as handle:
            csv_hashes[symbol] = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest = {
        "schema_version": 2,
        "symbols": {
            symbol: {
                "csv_sha256": csv_hashes[symbol],
                "rows": len(frame),
                "start": frame.index[0].isoformat(),
                "end": frame.index[-1].isoformat(),
                "dropped_invalid_ohlc": int(frame.attrs.get("dropped_invalid_ohlc", 0)),
                "price_mode": "bid_ask" if has_bid_ask(frame) else "mid",
                "mean_spread_price": (
                    float(frame["spread_close"].mean()) if has_bid_ask(frame) else None
                ),
                "historical_swap": {
                    "long": "swap_long_pips" in frame,
                    "short": "swap_short_pips" in frame,
                },
                "source": {
                    key.removeprefix("source_"): value
                    for key, value in frame.attrs.items()
                    if key.startswith("source_")
                    and (
                        isinstance(value, (str, int, float, bool)) or value is None
                    )
                },
            }
            for symbol, frame in data.items()
        }
    }
    (root / "_data_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def attach_historical_swaps(
    data: Mapping[str, pd.DataFrame],
    directory: str | Path,
    maximum_staleness_days: int = 14,
) -> dict[str, pd.DataFrame]:
    """As-of join historical financing known by each bar; future rows are never backfilled."""
    root = Path(directory)
    output: dict[str, pd.DataFrame] = {}
    for symbol, frame in data.items():
        candidates = [root / f"{symbol}.csv", root / f"{symbol.lower()}.csv"]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            raise FileNotFoundError(f"No historical swap file found for {symbol} in {root}")
        swaps = pd.read_csv(path)
        swaps.columns = [str(column).strip().lower() for column in swaps.columns]
        required = {"available_time", "swap_long_pips", "swap_short_pips"}
        missing = required - set(swaps)
        if missing:
            raise ValueError(f"{symbol}: historical swap file is missing {sorted(missing)}")
        swaps["available_time"] = pd.to_datetime(swaps["available_time"], utc=True, errors="coerce")
        if swaps["available_time"].isna().any():
            raise ValueError(f"{symbol}: historical swap file contains invalid available_time")
        for column in ("swap_long_pips", "swap_short_pips"):
            swaps[column] = pd.to_numeric(swaps[column], errors="coerce")
            if swaps[column].isna().any() or not np.isfinite(swaps[column]).all():
                raise ValueError(f"{symbol}: historical swap file contains invalid {column}")
        if swaps.duplicated("available_time").any():
            raise ValueError(f"{symbol}: duplicate historical swap available_time")
        left = pd.DataFrame({"timestamp": frame.index}).sort_values("timestamp")
        merged = pd.merge_asof(
            left,
            swaps.sort_values("available_time"),
            left_on="timestamp",
            right_on="available_time",
            direction="backward",
            tolerance=timedelta(days=maximum_staleness_days),
            allow_exact_matches=True,
        ).set_index("timestamp")
        enriched = frame.copy()
        enriched["swap_long_pips"] = merged["swap_long_pips"].reindex(enriched.index)
        enriched["swap_short_pips"] = merged["swap_short_pips"].reindex(enriched.index)
        output[symbol] = enriched
    return output


class YahooFXProvider:
    """Public-data adapter for research; Yahoo data is not execution-quality bid/ask data."""

    @staticmethod
    def download(
        symbols: list[str],
        start: str,
        end: str | None,
        interval: str,
    ) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        requested_interval = "1h" if interval == "4h" else interval
        result: dict[str, pd.DataFrame] = {}
        for raw_symbol in symbols:
            symbol = CurrencyPair.parse(raw_symbol).symbol
            ticker = yf.Ticker(f"{symbol}=X")
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", category=DeprecationWarning, module=r"yfinance\..*"
                )
                frame = ticker.history(
                    start=start,
                    end=end,
                    interval=requested_interval,
                    auto_adjust=False,
                    actions=False,
                    repair=False,
                )
            if frame.empty:
                raise RuntimeError(f"Yahoo returned no data for {symbol}=X")
            frame = frame.rename(columns=str.lower)
            if interval == "1d":
                # Preserve the provider's trading-date label without DST-driven 23:00 shifts.
                frame.index = pd.DatetimeIndex(frame.index.date).tz_localize("UTC")
            elif frame.index.tz is None:
                frame.index = frame.index.tz_localize("UTC")
            else:
                frame.index = frame.index.tz_convert("UTC")
            if interval == "4h":
                frame["_samples"] = 1
                frame = (
                    frame.resample("4h", origin="start_day")
                    .agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                            "_samples": "sum",
                        }
                    )
                    .dropna(subset=["open", "high", "low", "close"])
                )
                frame = frame.loc[frame["_samples"] == 4].drop(columns="_samples")
            frame = drop_incomplete_bars(frame, interval)
            validated = validate_bars(frame, symbol, invalid_ohlc="drop")
            validated.attrs.update(
                {
                    "source_provider": "yahoo",
                    "source_manifest_complete": True,
                }
            )
            result[symbol] = validated
        return result


class OandaCandleProvider:
    """Historical practice-domain bid/ask candles; live OANDA domains are forbidden."""

    PRACTICE_URL = "https://api-fxpractice.oanda.com"

    @classmethod
    def download(
        cls,
        symbols: list[str],
        start: str,
        end: str | None,
        interval: str,
        token: str,
        *,
        base_url: str = PRACTICE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, pd.DataFrame]:
        if base_url.rstrip("/") != cls.PRACTICE_URL:
            raise ValueError("OANDA historical data is restricted to the fxPractice domain")
        if not token:
            raise ValueError("OANDA_PRACTICE_TOKEN is required for OANDA historical data")
        granularity = {"1h": "H1", "4h": "H4", "1d": "D"}[interval]
        start_time = pd.Timestamp(start)
        start_time = (
            start_time.tz_localize("UTC")
            if start_time.tzinfo is None
            else start_time.tz_convert("UTC")
        )
        end_time = pd.Timestamp(end) if end is not None else pd.Timestamp.now(tz="UTC")
        end_time = (
            end_time.tz_localize("UTC")
            if end_time.tzinfo is None
            else end_time.tz_convert("UTC")
        )
        headers = {"Authorization": f"Bearer {token}"}
        result: dict[str, pd.DataFrame] = {}
        with httpx.Client(
            base_url=base_url,
            headers=headers,
            transport=transport,
            timeout=30,
        ) as client:
            for raw_symbol in symbols:
                pair = CurrencyPair.parse(raw_symbol)
                instrument = f"{pair.base}_{pair.quote}"
                cursor = start_time
                first_page = True
                records: list[dict[str, object]] = []
                while cursor < end_time:
                    response = client.get(
                        f"/v3/instruments/{instrument}/candles",
                        params={
                            "price": "BA",
                            "granularity": granularity,
                            "count": 5000,
                            "from": cursor.isoformat(),
                            "includeFirst": str(first_page).lower(),
                        },
                    )
                    response.raise_for_status()
                    candles = response.json().get("candles", [])
                    if not candles:
                        break
                    latest: pd.Timestamp | None = None
                    for candle in candles:
                        timestamp = pd.Timestamp(candle["time"])
                        timestamp = (
                            timestamp.tz_localize("UTC")
                            if timestamp.tzinfo is None
                            else timestamp.tz_convert("UTC")
                        )
                        latest = timestamp
                        if not candle.get("complete", False) or timestamp >= end_time:
                            continue
                        bid = candle.get("bid")
                        ask = candle.get("ask")
                        if bid is None or ask is None:
                            raise RuntimeError("OANDA BA candle response omitted bid or ask prices")
                        row: dict[str, object] = {
                            "timestamp": timestamp,
                            "volume": float(candle.get("volume", 0)),
                        }
                        for field, key in zip(REQUIRED_COLUMNS, ("o", "h", "l", "c"), strict=True):
                            row[f"bid_{field}"] = float(bid[key])
                            row[f"ask_{field}"] = float(ask[key])
                        records.append(row)
                    if latest is None or latest <= cursor:
                        break
                    cursor = latest
                    first_page = False
                    if len(candles) < 5000:
                        break
                if not records:
                    raise RuntimeError(
                        f"OANDA returned no complete bid/ask candles for {pair.symbol}"
                    )
                frame = pd.DataFrame(records).set_index("timestamp")
                validated = validate_bars(frame, pair.symbol)
                validated.attrs.update(
                    {
                        "source_provider": "oanda_fxpractice",
                        "source_base_url": cls.PRACTICE_URL,
                        "source_hour_coverage": 1.0,
                        "source_manifest_complete": True,
                    }
                )
                result[pair.symbol] = validated
        return result


class DukascopyTickProvider:
    """Public Dukascopy bid/ask ticks, aggregated without midpoint reconstruction.

    Dukascopy stores one LZMA-compressed ``bi5`` file per UTC hour. Each 20-byte
    big-endian record contains the millisecond offset, ask, bid, ask volume and
    bid volume. Raw responses and confirmed no-data hours are cached so an
    interrupted multi-year download can resume without starting over.
    """

    BASE_URL = "https://datafeed.dukascopy.com/datafeed"
    _TICK_RECORD = struct.Struct(">iiiff")
    PARSER_VERSION = "dukascopy-bi5-v1"

    @staticmethod
    def _utc(value: str | pd.Timestamp) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        return (
            timestamp.tz_localize("UTC")
            if timestamp.tzinfo is None
            else timestamp.tz_convert("UTC")
        )

    @staticmethod
    def _candidate_market_hour(timestamp: pd.Timestamp) -> bool:
        # Request a deliberately broad FX week. The extra DST boundary hour is
        # harmless and makes genuine provider gaps visible in the audit.
        weekday = timestamp.weekday()
        return weekday < 4 or (weekday == 4 and timestamp.hour < 22) or (
            weekday == 6 and timestamp.hour >= 21
        )

    @classmethod
    def _hours(cls, start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
        first = start.floor("h")
        last = end.ceil("h")
        return [
            timestamp
            for timestamp in pd.date_range(first, last, freq="1h", inclusive="left")
            if timestamp < end and cls._candidate_market_hour(timestamp)
        ]

    @staticmethod
    def _relative_path(symbol: str, hour: pd.Timestamp) -> Path:
        # Dukascopy's month component is zero based.
        return Path(
            symbol,
            f"{hour.year:04d}",
            f"{hour.month - 1:02d}",
            f"{hour.day:02d}",
            f"{hour.hour:02d}h_ticks.bi5",
        )

    @classmethod
    def _download_hour(
        cls,
        client: httpx.Client,
        symbol: str,
        hour: pd.Timestamp,
        cache_directory: Path,
        max_retries: int,
        cache_missing: bool,
    ) -> tuple[pd.Timestamp, bytes | None, str]:
        relative = cls._relative_path(symbol, hour)
        cache_path = cache_directory / relative
        missing_path = cache_path.with_suffix(cache_path.suffix + ".missing")
        if cache_path.exists():
            payload = cache_path.read_bytes()
            try:
                cls._hour_bar(payload, hour, symbol)
            except ValueError:
                invalid_path = cache_path.with_suffix(cache_path.suffix + ".invalid")
                cache_path.replace(invalid_path)
            else:
                return hour, payload, "cached"
        if missing_path.exists():
            return hour, None, "cached_no_data"

        response: httpx.Response | None = None
        for attempt in range(max_retries + 1):
            try:
                response = client.get(relative.as_posix())
                if response.status_code == 404:
                    break
                response.raise_for_status()
                payload = response.content
                if payload:
                    bar, _ = cls._hour_bar(payload, hour, symbol)
                    if bar is None:
                        break
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
                    temporary.write_bytes(payload)
                    temporary.replace(cache_path)
                    return hour, payload, "downloaded"
                break
            except httpx.HTTPError:
                if attempt >= max_retries:
                    return hour, None, "download_failed"
                time.sleep(min(2**attempt, 4))

        if cache_missing:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            missing_path.touch()
        status = "no_data" if response is not None else "download_failed"
        return hour, None, status

    @classmethod
    def _hour_bar(
        cls,
        payload: bytes,
        hour: pd.Timestamp,
        symbol: str,
    ) -> tuple[dict[str, object] | None, int]:
        try:
            raw = lzma.decompress(payload)
        except lzma.LZMAError as error:
            raise ValueError(f"{symbol} {hour}: invalid Dukascopy LZMA payload") from error
        if not raw:
            return None, 0
        if len(raw) % cls._TICK_RECORD.size:
            raise ValueError(
                f"{symbol} {hour}: Dukascopy payload length is not a multiple of 20 bytes"
            )

        try:
            scale = DUKASCOPY_PRICE_DIVISORS[symbol]
        except KeyError as error:
            raise ValueError(
                f"{symbol}: no explicit Dukascopy price divisor metadata"
            ) from error
        first_bid = first_ask = last_bid = last_ask = None
        first_mid = last_mid = None
        bid_high = ask_high = float("-inf")
        bid_low = ask_low = float("inf")
        mid_high = float("-inf")
        mid_low = float("inf")
        volume = 0.0
        ticks = 0
        previous_offset = -1
        unpacked = cls._TICK_RECORD.iter_unpack(raw)
        for offset, ask_integer, bid_integer, ask_volume, bid_volume in unpacked:
            if offset >= 3_600_000 or offset < previous_offset:
                raise ValueError(f"{symbol} {hour}: invalid Dukascopy tick offset ordering")
            previous_offset = offset
            ask = ask_integer / scale
            bid = bid_integer / scale
            mid = (bid + ask) / 2
            if bid <= 0 or ask < bid:
                raise ValueError(f"{symbol} {hour}: invalid or crossed Dukascopy quote")
            if not np.isfinite(ask_volume) or not np.isfinite(bid_volume):
                raise ValueError(f"{symbol} {hour}: non-finite Dukascopy quote volume")
            if ask_volume < 0 or bid_volume < 0:
                raise ValueError(f"{symbol} {hour}: negative Dukascopy quote volume")
            if first_bid is None:
                first_bid, first_ask = bid, ask
                first_mid = mid
            last_bid, last_ask = bid, ask
            last_mid = mid
            bid_high, bid_low = max(bid_high, bid), min(bid_low, bid)
            ask_high, ask_low = max(ask_high, ask), min(ask_low, ask)
            mid_high, mid_low = max(mid_high, mid), min(mid_low, mid)
            volume += float(bid_volume) + float(ask_volume)
            ticks += 1

        return (
            {
                "timestamp": hour,
                "open": first_mid,
                "high": mid_high,
                "low": mid_low,
                "close": last_mid,
                "bid_open": first_bid,
                "bid_high": bid_high,
                "bid_low": bid_low,
                "bid_close": last_bid,
                "ask_open": first_ask,
                "ask_high": ask_high,
                "ask_low": ask_low,
                "ask_close": last_ask,
                "volume": volume,
                "_source_hours": 1,
                "tick_count": ticks,
            },
            ticks,
        )

    @staticmethod
    def _aggregate(hourly: pd.DataFrame, interval: str) -> pd.DataFrame:
        if interval == "1h":
            return hourly.drop(columns="_source_hours")
        rule = {"4h": "4h", "1d": "1D"}[interval]
        aggregated = hourly.resample(rule, origin="start_day").agg(
            {
                "bid_open": "first",
                "bid_high": "max",
                "bid_low": "min",
                "bid_close": "last",
                "ask_open": "first",
                "ask_high": "max",
                "ask_low": "min",
                "ask_close": "last",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "_source_hours": "sum",
                "tick_count": "sum",
            }
        )
        minimum_hours = 4 if interval == "4h" else 20
        return aggregated.loc[aggregated["_source_hours"] >= minimum_hours].drop(
            columns="_source_hours"
        )

    @classmethod
    def download(
        cls,
        symbols: list[str],
        start: str,
        end: str | None,
        interval: str,
        *,
        cache_directory: str | Path = Path("data/dukascopy_cache"),
        concurrency: int = 8,
        max_retries: int = 2,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        now: pd.Timestamp | None = None,
    ) -> dict[str, pd.DataFrame]:
        if not 1 <= concurrency <= 32:
            raise ValueError("Dukascopy concurrency must be between 1 and 32")
        if not 0 <= max_retries <= 10:
            raise ValueError("Dukascopy max_retries must be between 0 and 10")
        if interval not in {"1h", "4h", "1d"}:
            raise ValueError(f"Unsupported Dukascopy interval: {interval}")
        start_time = cls._utc(start)
        current = cls._utc(now if now is not None else pd.Timestamp.now(tz="UTC"))
        requested_end = cls._utc(end) if end is not None else current
        end_time = min(requested_end, current.floor("h"))
        if start_time >= end_time:
            raise ValueError("Dukascopy start must be before the available end time")

        cache_root = Path(cache_directory) / cls.PARSER_VERSION
        output: dict[str, pd.DataFrame] = {}
        with httpx.Client(
            base_url=base_url.rstrip("/") + "/", transport=transport, timeout=30
        ) as client:
            for raw_symbol in symbols:
                symbol = CurrencyPair.parse(raw_symbol).symbol
                hours = cls._hours(start_time, end_time)
                records: list[dict[str, object]] = []
                statuses: dict[str, int] = {}
                tick_count = 0
                batch_size = max(128, concurrency * 32)
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    for offset in range(0, len(hours), batch_size):
                        futures = [
                            executor.submit(
                                cls._download_hour,
                                client,
                                symbol,
                                hour,
                                cache_root,
                                max_retries,
                                hour < current - timedelta(days=7),
                            )
                            for hour in hours[offset : offset + batch_size]
                        ]
                        for future in as_completed(futures):
                            hour, payload, status = future.result()
                            statuses[status] = statuses.get(status, 0) + 1
                            if payload is None:
                                continue
                            bar, ticks = cls._hour_bar(payload, hour, symbol)
                            tick_count += ticks
                            if bar is not None:
                                records.append(bar)
                if not records:
                    raise RuntimeError(f"Dukascopy returned no bid/ask ticks for {symbol}")
                hourly = pd.DataFrame(records).set_index("timestamp").sort_index()
                frame = cls._aggregate(hourly, interval)
                frame = frame.loc[(frame.index >= start_time) & (frame.index < end_time)]
                frame = drop_incomplete_bars(frame, interval, end_time)
                validated = validate_bars(frame, symbol)
                available_hours = len(hourly)
                no_data_hours = statuses.get("no_data", 0) + statuses.get(
                    "cached_no_data", 0
                )
                validated.attrs.update(
                    {
                        "source_provider": "dukascopy",
                        "source_requested_hours": len(hours),
                        "source_available_hours": available_hours,
                        "source_no_data_hours": no_data_hours,
                        "source_failed_hours": statuses.get("download_failed", 0),
                        "source_downloaded_hours": statuses.get("downloaded", 0),
                        "source_cached_hours": statuses.get("cached", 0),
                        "source_tick_count": tick_count,
                        "source_hour_coverage": available_hours / len(hours) if hours else 0.0,
                        "source_base_url": base_url.rstrip("/"),
                        "source_price_divisor": DUKASCOPY_PRICE_DIVISORS[symbol],
                        "source_volume_semantics": "sum_bid_ask_quote_size",
                        "source_parser_version": cls.PARSER_VERSION,
                        "source_manifest_complete": True,
                    }
                )
                output[symbol] = validated
        return output


def drop_incomplete_bars(
    frame: pd.DataFrame,
    interval: str,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Remove a live provider's still-forming final candle."""
    duration = {
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }[interval]
    current = now if now is not None else pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    return frame.loc[frame.index + duration <= current]


@dataclass(frozen=True)
class SyntheticFXProvider:
    """Creates correlated, cross-rate-consistent bars for deterministic system tests."""

    seed: int = 42

    def generate(
        self,
        symbols: list[str],
        bars: int = 3000,
        interval: str = "4h",
        start: str = "2020-01-01",
        price_mode: str = "mid",
    ) -> dict[str, pd.DataFrame]:
        rng = np.random.default_rng(self.seed)
        pairs = [CurrencyPair.parse(value) for value in symbols]
        currencies = sorted({ccy for pair in pairs for ccy in (pair.base, pair.quote)})
        usd_values = {
            "USD": 1.0,
            "EUR": 1.10,
            "GBP": 1.28,
            "JPY": 0.0091,
            "CHF": 1.11,
            "CAD": 0.74,
            "AUD": 0.67,
            "NZD": 0.62,
        }
        annual_vol = {
            "USD": 0.045,
            "EUR": 0.060,
            "GBP": 0.070,
            "JPY": 0.065,
            "CHF": 0.055,
            "CAD": 0.060,
            "AUD": 0.075,
            "NZD": 0.080,
        }
        periods_per_year = {"1h": 24 * 260, "4h": 6 * 260, "1d": 260}[interval]
        frequency = {"1h": "1h", "4h": "4h", "1d": "1D"}[interval]
        index = pd.date_range(utc_timestamp(start), periods=bars, freq=frequency)
        index = index[index.dayofweek < 5][:bars]
        if len(index) < bars:
            # Build a longer calendar when weekend filtering removed rows.
            index = pd.date_range(utc_timestamp(start), periods=int(bars * 1.5), freq=frequency)
            index = index[index.dayofweek < 5][:bars]

        market = rng.normal(0, 1 / np.sqrt(periods_per_year), size=bars)
        regime = np.repeat(rng.choice([-1.0, 0.0, 1.0], size=(bars // 250) + 1), 250)[:bars]
        factors: dict[str, np.ndarray] = {}
        for i, currency in enumerate(currencies):
            vol = annual_vol.get(currency, 0.07)
            beta = 0.25 + (i % 4) * 0.12
            idiosyncratic = rng.normal(0, vol / np.sqrt(periods_per_year), size=bars)
            drift = regime * ((i - len(currencies) / 2) * 0.000002)
            returns = beta * market + idiosyncratic + drift
            factors[currency] = np.cumsum(returns)

        output: dict[str, pd.DataFrame] = {}
        for pair in pairs:
            initial = usd_values.get(pair.base, 1.0) / usd_values.get(pair.quote, 1.0)
            log_close = np.log(initial) + factors[pair.base] - factors[pair.quote]
            close = np.exp(log_close)
            open_ = np.r_[close[0], close[:-1]]
            bar_sigma = np.maximum(np.abs(close / open_ - 1), 0.00015)
            wick_up = rng.uniform(0.2, 1.0, bars) * bar_sigma
            wick_down = rng.uniform(0.2, 1.0, bars) * bar_sigma
            high = np.maximum(open_, close) * (1 + wick_up)
            low = np.minimum(open_, close) * (1 - wick_down)
            frame = pd.DataFrame(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": rng.integers(500, 5000, bars).astype(float),
                },
                index=index,
            )
            if price_mode == "bid_ask":
                spread_pips = np.maximum(0.25, rng.lognormal(mean=-0.1, sigma=0.35, size=bars))
                half_spread = spread_pips * pair.pip_size / 2
                for field in REQUIRED_COLUMNS:
                    frame[f"bid_{field}"] = frame[field] - half_spread
                    frame[f"ask_{field}"] = frame[field] + half_spread
                frame["swap_long_pips"] = -0.15 + 0.05 * np.sin(np.arange(bars) / 50)
                frame["swap_short_pips"] = -0.10 - 0.05 * np.sin(np.arange(bars) / 50)
            elif price_mode != "mid":
                raise ValueError(f"Unsupported synthetic price_mode: {price_mode}")
            validated = validate_bars(frame, pair.symbol)
            validated.attrs.update(
                {
                    "source_provider": "synthetic",
                    "source_manifest_complete": True,
                }
            )
            output[pair.symbol] = validated
        return output


def load_from_config(config: object) -> dict[str, pd.DataFrame]:
    provider = config.provider
    if provider == "csv":
        data = load_csv_directory(config.directory, config.symbols)
    elif provider == "yahoo":
        data = YahooFXProvider.download(config.symbols, config.start, config.end, config.interval)
    elif provider == "synthetic":
        data = SyntheticFXProvider(seed=config.seed).generate(
            config.symbols,
            config.synthetic_bars,
            config.interval,
            config.start,
            config.price_mode,
        )
    elif provider == "oanda":
        data = OandaCandleProvider.download(
            config.symbols,
            config.start,
            config.end,
            config.interval,
            os.environ.get("OANDA_PRACTICE_TOKEN", ""),
        )
    elif provider == "dukascopy":
        data = DukascopyTickProvider.download(
            config.symbols,
            config.start,
            config.end,
            config.interval,
            cache_directory=config.dukascopy_cache_directory,
            concurrency=config.dukascopy_concurrency,
            max_retries=config.dukascopy_max_retries,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    if config.swap_directory is not None:
        data = attach_historical_swaps(
            data,
            config.swap_directory,
            config.maximum_swap_staleness_days,
        )

    start = pd.Timestamp(config.start)
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    end = pd.Timestamp(config.end) if config.end is not None else None
    if end is not None:
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
    sliced: dict[str, pd.DataFrame] = {}
    for symbol, frame in data.items():
        if config.price_mode == "bid_ask" and not has_bid_ask(frame):
            raise ValueError(
                f"{symbol}: data.price_mode=bid_ask requires complete bid/ask OHLC columns"
            )
        mask = frame.index >= start
        if end is not None:
            mask &= frame.index < end
        selected = frame.loc[mask].copy()
        if len(selected) < 2:
            raise ValueError(
                f"{symbol}: fewer than two bars remain in requested range "
                f"[{config.start}, {config.end or 'latest'})"
            )
        sliced[symbol] = selected
    return sliced
