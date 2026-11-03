"""
Nexus Trader — async Redis client.

Thin wrapper around ``redis.asyncio`` providing:
  * connection pooling
  * Redis-Stream publish / consume helpers
  * cache get / set with TTL
  * health-check
  * structured logging via structlog
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import redis.asyncio as aioredis
import structlog

from .constants import REDIS_KEY_PREFIX, STREAM_MAX_LEN, RedisStream
from .events import Event, parse_event

logger = structlog.get_logger(__name__)


def _command_unsupported(exc: Exception) -> bool:
    """True when Redis rejected a command as unknown (Redis < 6.2 XAUTOCLAIM)."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("unknown command", "unknown subcommand", "noperm")
    )


@dataclass(slots=True)
class StreamDelivery:
    """A parsed stream entry whose acknowledgement is controlled by its consumer."""

    client: "RedisClient"
    stream: str
    group: str
    message_id: str
    event: Event
    _acknowledged: bool = False

    async def ack(self) -> bool:
        """ACK the entry; False means it was already ACKed (or the group is gone)."""
        if self._acknowledged:
            return True
        result = await self.client.r.xack(self.stream, self.group, self.message_id)
        self._acknowledged = True
        # A 0 here means another worker (or a previous crashed attempt's retry
        # path) already removed the entry from the PEL: the effect must be
        # idempotent, so surface it instead of pretending the ACK was ours.
        if result == 0:
            await logger.awarning(
                "redis.stream.ack_noop",
                stream=self.stream,
                group=self.group,
                msg_id=self.message_id,
            )
        return bool(result)

    async def is_processed(self) -> bool:
        """True when this entry is already in the processed-id registry."""
        return await self.client.is_processed(self.stream, self.group, self.message_id)

    async def mark_processed(self, *, ttl_sec: int = 30 * 24 * 3600) -> bool:
        """Dedupe hook for replay-sensitive side effects (False = duplicate)."""
        return await self.client.mark_processed(
            self.stream, self.group, self.message_id, ttl_sec=ttl_sec
        )


class RedisClient:
    """Async Redis client with stream and cache helpers."""

    def __init__(
        self,
        url: str | None = None,
        *,
        max_connections: int = 20,
        decode_responses: bool = True,
    ) -> None:
        # Use 127.0.0.1 (not "localhost") by default: on Windows "localhost"
        # resolves to IPv6 ::1 first, and if Redis only listens on IPv4 each new
        # connection eats a ~2s timeout before falling back. Forcing IPv4 avoids
        # that penalty entirely.
        self._url = url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self._max_connections = max_connections
        self._decode_responses = decode_responses
        self._pool: aioredis.ConnectionPool | None = None
        self._redis: aioredis.Redis | None = None
        # None until the first XPENDING+XCLAIM reclaim proves whether the
        # server supports XAUTOCLAIM (Redis 6.2+).  Never guessed from the URL.
        self._xautoclaim_supported: bool | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._redis is not None:
            return
        self._pool = aioredis.ConnectionPool.from_url(
            self._url,
            max_connections=self._max_connections,
            decode_responses=self._decode_responses,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        await logger.ainfo("redis.connected", url=self._url)

    async def disconnect(self) -> None:
        if self._redis is not None:
            await self._redis.close() # <--- تم التعديل هنا
            self._redis = None
        if self._pool is not None:
            await self._pool.disconnect()
            self._pool = None
        await logger.ainfo("redis.disconnected")

    @property
    def r(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("RedisClient is not connected — call connect() first")
        return self._redis

    # ── Health ───────────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        try:
            return await self.r.ping()
        except Exception:
            await logger.awarning("redis.health_check_failed")
            return False

    # ── Stream Publish ───────────────────────────────────────────────────

    async def publish_event(
        self,
        stream: str | RedisStream,
        event: Event,
        *,
        maxlen: int = STREAM_MAX_LEN,
    ) -> str:
        """Publish an event to a Redis Stream. Returns the stream entry ID."""
        payload = event.to_stream_dict()
        entry_id: str = await self.r.xadd(
            str(stream),
            payload,
            maxlen=maxlen,
            approximate=True,
        )
        await logger.adebug(
            "redis.stream.published",
            stream=str(stream),
            event_type=event.event_type,
            entry_id=entry_id,
        )
        return entry_id

    # ── Stream Consume ───────────────────────────────────────────────────

    async def ensure_consumer_group(
        self,
        stream: str | RedisStream,
        group: str,
    ) -> None:
        try:
            await self.r.xgroup_create(
                str(stream), group, id="0", mkstream=True,
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def reclaim_pending(
        self,
        stream: str | RedisStream,
        group: str,
        consumer: str,
        *,
        min_idle_ms: int = 60_000,
        count: int = 10,
        max_attempts: int = 3,
        dlq_stream: str | None = None,
        dlq_maxlen: int = 10_000,
    ) -> list[tuple[str, list[tuple[str, Any]]]]:
        """Reclaim or dead-letter stale pending entries using Redis 5 commands.

        ``XAUTOCLAIM`` (Redis 6.2+) is feature-detected on the first use and
        preferred when available; the ``XPENDING`` + per-id ``XCLAIM`` fallback
        also works on Redis 5.  Entries that reach ``max_attempts`` are copied
        to ``dlq_stream`` (bounded) before being ACKed so a poison entry cannot
        occupy the PEL forever; without a DLQ they are left pending and
        re-checked on the next run.  When an entry's source payload has already
        been trimmed from the stream, a tombstone is dead-lettered instead of
        returning with the entry stuck in the PEL.
        """
        if min_idle_ms < 0 or count <= 0 or max_attempts <= 0:
            raise ValueError("min_idle_ms must be >= 0; count and max_attempts must be positive")
        stream_key = str(stream)
        pending = await self.r.xpending_range(
            stream_key,
            group,
            min="-",
            max="+",
            count=count,
        )
        eligible: list[tuple[str, int]] = []
        for item in pending or []:
            if isinstance(item, dict):
                msg_id = str(item.get("message_id") or item.get("message-id"))
                idle_ms = int(item.get("time_since_delivered", item.get("idle", 0)))
                deliveries = int(item.get("times_delivered", item.get("deliveries", 0)))
            else:
                msg_id = str(item[0])
                idle_ms = int(item[2])
                deliveries = int(item[3])
            if idle_ms >= min_idle_ms:
                eligible.append((msg_id, deliveries))

        to_claim: list[str] = []
        reclaimed: list[tuple[str, list[tuple[str, Any]]]] = []
        for msg_id, deliveries in eligible:
            if deliveries >= max_attempts:
                if not dlq_stream:
                    await logger.awarning(
                        "redis.stream.retry_limit_reached",
                        stream=stream_key,
                        group=group,
                        msg_id=msg_id,
                        deliveries=deliveries,
                    )
                    continue
                await self._dead_letter_pending(
                    stream_key,
                    group,
                    msg_id,
                    dlq_stream,
                    deliveries,
                    dlq_maxlen,
                )
                continue
            to_claim.append(msg_id)

        if to_claim:
            reclaimed.extend(
                await self._claim_entries(
                    stream_key, group, consumer, min_idle_ms, to_claim,
                )
            )
        return reclaimed

    async def _claim_entries(
        self,
        stream_key: str,
        group: str,
        consumer: str,
        min_idle_ms: int,
        msg_ids: list[str],
    ) -> list[tuple[str, list[tuple[str, Any]]]]:
        """Claim vetted entry ids, preferring XAUTOCLAIM when the server has it."""
        if not msg_ids:
            return []
        if self._xautoclaim_supported is not False:
            try:
                result = await self.r.xautoclaim(
                    stream_key,
                    group,
                    consumer,
                    min_idle_time=min_idle_ms,
                    start_id=msg_ids[0],
                    count=len(msg_ids),
                )
            except aioredis.ResponseError as exc:
                if not _command_unsupported(exc):
                    raise
                self._xautoclaim_supported = False
                await logger.awarning(
                    "redis.stream.xautoclaim_unsupported",
                    stream=stream_key,
                    group=group,
                    error=str(exc),
                )
            else:
                self._xautoclaim_supported = True
                entries = result[1] if isinstance(result, (list, tuple)) and len(result) >= 2 else result
                wanted = set(msg_ids)
                # XAUTOCLAIM may return (None, None) placeholders for entries
                # deleted mid-claim; only vetted, still-present ids are yielded.
                return [
                    (str(entry_id), fields)
                    for entry_id, fields in (entries or [])
                    if entry_id and str(entry_id) in wanted
                ]
        # Redis 5 path: XAUTOCLAIM is unavailable, claim one id at a time.
        claimed: list[tuple[str, list[tuple[str, Any]]]] = []
        for msg_id in msg_ids:
            messages = await self.r.xclaim(
                stream_key,
                group,
                consumer,
                min_idle_time=min_idle_ms,
                message_ids=[msg_id],
            )
            if messages:
                claimed.extend(messages)
        return claimed

    async def _dead_letter_pending(
        self,
        stream: str,
        group: str,
        msg_id: str,
        dlq_stream: str,
        deliveries: int,
        dlq_maxlen: int,
    ) -> None:
        """Copy one pending entry to a bounded DLQ, then ACK the source.

        If the source payload has already been trimmed out of the stream, the
        original bytes no longer exist; a tombstone is written instead so the
        entry can never block the PEL again.
        """
        entries = await self.r.xrange(stream, min=msg_id, max=msg_id, count=1)
        if entries:
            _entry_id, fields = entries[0]
            payload = dict(fields)
        else:
            payload = {"_reason": "source_payload_missing"}
            await logger.awarning(
                "redis.stream.source_payload_trimmed",
                stream=stream,
                group=group,
                msg_id=msg_id,
            )
        payload.update({
            "_source_stream": stream,
            "_source_group": group,
            "_source_id": msg_id,
            "_delivery_attempts": str(deliveries),
        })
        await self._publish_dlq(
            dlq_stream, payload, preserve_id=msg_id, dlq_maxlen=dlq_maxlen,
        )
        await self.r.xack(stream, group, msg_id)
        await logger.awarning(
            "redis.stream.dead_lettered",
            stream=stream,
            group=group,
            msg_id=msg_id,
            dlq_stream=dlq_stream,
            deliveries=deliveries,
        )

    async def _publish_dlq(
        self,
        dlq_stream: str,
        payload: dict[str, Any],
        *,
        preserve_id: str | None,
        dlq_maxlen: int,
    ) -> None:
        """Copy one entry into the bounded DLQ, preserving its ID when possible.

        A DLQ whose top ID is newer than ``preserve_id`` (e.g. auto-ID
        tombstones) rejects the preserved ID; the entry is then written under a
        fresh ID instead of being dropped — a duplicate DLQ row beats a poison
        entry that can never leave the PEL.
        """
        try:
            await self.r.xadd(
                dlq_stream,
                payload,
                id=preserve_id or "*",
                maxlen=dlq_maxlen,
                approximate=True,
            )
            return
        except aioredis.ResponseError as exc:
            message = str(exc).lower()
            if "equal or smaller" not in message and "already exists" not in message:
                raise
        if preserve_id:
            # Re-running recovery after a successful DLQ write is safe: prove
            # the exact ID exists before treating this as done.
            existing = await self.r.xrange(
                dlq_stream, min=preserve_id, max=preserve_id, count=1,
            )
            if existing and str(existing[0][0]) == preserve_id:
                return
        await self.r.xadd(dlq_stream, payload, maxlen=dlq_maxlen, approximate=True)

    @staticmethod
    def idempotency_key(stream: str | RedisStream, group: str, message_id: str) -> str:
        """Return the stable key consumers should use for processed entries."""
        return f"nexus:stream:processed:{str(stream)}:{group}:{message_id}"

    @staticmethod
    def dead_letter_stream(stream: str | RedisStream) -> str:
        """Conventional bounded DLQ name for ``<stream>``."""
        return f"{str(stream)}:dlq"

    async def is_processed(
        self,
        stream: str | RedisStream,
        group: str,
        message_id: str,
    ) -> bool:
        """True when this entry id is already in the processed-id registry."""
        return bool(await self.r.exists(self.idempotency_key(stream, group, message_id)))

    async def mark_processed(
        self,
        stream: str | RedisStream,
        group: str,
        message_id: str,
        *,
        ttl_sec: int = 30 * 24 * 3600,
    ) -> bool:
        """Mark an entry id as processed; False means it was already marked.

        Documented idempotency hook for replay-sensitive side effects (XCLAIM
        and consumer restarts re-deliver entries).  Two supported patterns:

        * claim-before-effect — call before applying the effect; a redelivery
          returns False and is skipped, so the effect runs at most once (a
          crash between mark and effect loses it);
        * mark-after-effect — apply, then mark; a crash between effect and mark
          allows exactly one duplicate, so the effect itself must be safe to
          retry once.

        Multi-effect handlers need one key per effect
        (``idempotency_key(...) + ":<effect>"`` via the raw Redis key).
        """
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be positive")
        return bool(await self.r.set(
            self.idempotency_key(stream, group, message_id),
            "1",
            ex=ttl_sec,
            nx=True,
        ))

    async def subscribe_stream(
        self,
        stream: str | RedisStream,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 2000,
        dlq_stream: str | None = None,
        dlq_maxlen: int = 10_000,
    ) -> AsyncIterator[Event]:
        """Yield parsed Events from a consumer-group read loop.

        Legacy consumers are ack-everything: entries that fail to parse are
        logged and ACKed.  When ``dlq_stream`` is supplied the raw payload is
        copied there first and the entry is ACKed only after that copy
        succeeds, so a DLQ outage leaves the entry pending instead of lost.
        """
        stream_key = str(stream)
        await self.ensure_consumer_group(stream_key, group)

        while True:
            try:
                entries = await self.r.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream_key: ">"},
                    count=count,
                    block=block_ms,
                )
                if not entries:
                    continue
                for _stream_name, messages in entries:
                    for msg_id, fields in messages:
                        try:
                            event = parse_event(fields)
                        except Exception:
                            await logger.awarning(
                                "redis.stream.parse_error",
                                stream=stream_key,
                                msg_id=msg_id,
                            )
                            if dlq_stream:
                                await self._publish_dlq(
                                    dlq_stream,
                                    {
                                        **dict(fields),
                                        "_source_stream": stream_key,
                                        "_source_group": group,
                                        "_source_id": str(msg_id),
                                        "_reason": "parse_error",
                                    },
                                    preserve_id=None,
                                    dlq_maxlen=dlq_maxlen,
                                )
                            await self.r.xack(stream_key, group, msg_id)
                            continue
                        try:
                            yield event
                        finally:
                            # Legacy semantics kept on purpose: this generator
                            # acks once the event is handed to the caller, who
                            # has no delivery handle.  Callers needing
                            # at-least-once processing must use
                            # subscribe_deliveries().
                            await self.r.xack(stream_key, group, msg_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await logger.aexception("redis.stream.read_error", stream=stream_key)
                await asyncio.sleep(1)

    async def subscribe_deliveries(
        self,
        stream: str | RedisStream,
        group: str,
        consumer: str,
        *,
        count: int = 10,
        block_ms: int = 2000,
        dlq_stream: str | None = None,
        dlq_maxlen: int = 10_000,
        reclaim_interval_sec: float | None = None,
        reclaim_min_idle_ms: int = 60_000,
        reclaim_max_attempts: int = 3,
    ) -> AsyncIterator[StreamDelivery]:
        """Yield parsed entries; callers must explicitly ack after processing succeeds.

        Parse failures are logged and left pending unless a DLQ is supplied;
        with a DLQ, the original payload is copied first and only then ACKed.
        Pending recovery is opt-in via ``reclaim_interval_sec``: each interval
        :meth:`reclaim_pending` runs (Redis-5-compatible XPENDING/XCLAIM, with
        feature-detected XAUTOCLAIM) and any entries this consumer now owns are
        yielded exactly like fresh reads.  Side effects that must survive a
        redelivery should use :meth:`StreamDelivery.mark_processed`.
        """
        stream_key = str(stream)
        await self.ensure_consumer_group(stream_key, group)
        if reclaim_interval_sec is not None and reclaim_interval_sec <= 0:
            raise ValueError("reclaim_interval_sec must be positive")
        next_reclaim = (
            time.monotonic() + float(reclaim_interval_sec)
            if reclaim_interval_sec is not None
            else None
        )

        while True:
            try:
                if next_reclaim is not None and time.monotonic() >= next_reclaim:
                    next_reclaim = time.monotonic() + float(reclaim_interval_sec)
                    reclaimed = await self.reclaim_pending(
                        stream_key,
                        group,
                        consumer,
                        min_idle_ms=reclaim_min_idle_ms,
                        count=count,
                        max_attempts=reclaim_max_attempts,
                        dlq_stream=dlq_stream,
                        dlq_maxlen=dlq_maxlen,
                    )
                    for entry_id, fields in reclaimed:
                        async for delivery in self._deliver_entries(
                            stream_key,
                            group,
                            [(entry_id, fields)],
                            dlq_stream=dlq_stream,
                            dlq_maxlen=dlq_maxlen,
                        ):
                            yield delivery
                entries = await self.r.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream_key: ">"},
                    count=count,
                    block=block_ms,
                )
                if not entries:
                    continue
                for _stream_name, messages in entries:
                    async for delivery in self._deliver_entries(
                        stream_key,
                        group,
                        messages,
                        dlq_stream=dlq_stream,
                        dlq_maxlen=dlq_maxlen,
                    ):
                        yield delivery
            except asyncio.CancelledError:
                raise
            except Exception:
                await logger.aexception("redis.stream.read_error", stream=stream_key)
                await asyncio.sleep(1)

    async def _deliver_entries(
        self,
        stream_key: str,
        group: str,
        messages: list[tuple[Any, Any]],
        *,
        dlq_stream: str | None,
        dlq_maxlen: int,
    ) -> AsyncIterator[StreamDelivery]:
        """Yield one StreamDelivery per parseable entry; never ACK a failed DLQ copy."""
        for msg_id, fields in messages:
            message_id = str(msg_id)
            try:
                event = parse_event(fields)
            except Exception:
                await logger.awarning(
                    "redis.stream.parse_error_pending",
                    stream=stream_key,
                    msg_id=message_id,
                )
                if dlq_stream:
                    # If this copy raises, the exception reaches the caller's
                    # read_error handler and the entry stays pending — losing
                    # both the payload and its PEL record is never acceptable.
                    await self._publish_dlq(
                        dlq_stream,
                        {
                            **dict(fields),
                            "_source_stream": stream_key,
                            "_source_group": group,
                            "_source_id": message_id,
                            "_reason": "parse_error",
                        },
                        preserve_id=None,
                        dlq_maxlen=dlq_maxlen,
                    )
                    await self.r.xack(stream_key, group, message_id)
                continue
            yield StreamDelivery(
                client=self,
                stream=stream_key,
                group=group,
                message_id=message_id,
                event=event,
            )

    # ── Cache ────────────────────────────────────────────────────────────

    async def cache_set(
        self,
        key: str,
        value: Any,
        *,
        ttl_sec: int = 60,
        prefix: bool = True,
    ) -> None:
        full_key = f"{REDIS_KEY_PREFIX}{key}" if prefix else key
        serialised = json.dumps(value, default=str)
        await self.r.set(full_key, serialised, ex=ttl_sec)

    async def cache_get(
        self,
        key: str,
        *,
        prefix: bool = True,
    ) -> Any | None:
        full_key = f"{REDIS_KEY_PREFIX}{key}" if prefix else key
        raw = await self.r.get(full_key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def cache_delete(self, key: str, *, prefix: bool = True) -> None:
        full_key = f"{REDIS_KEY_PREFIX}{key}" if prefix else key
        await self.r.delete(full_key)

    # ── Pub/Sub (simple channel-based) ───────────────────────────────────

    async def publish_channel(self, channel: str, data: dict[str, Any]) -> None:
        await self.r.publish(channel, json.dumps(data, default=str))

    async def subscribe_channel(
        self, *channels: str
    ) -> AsyncIterator[dict[str, Any]]:
        pubsub = self.r.pubsub()
        await pubsub.subscribe(*channels)
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    try:
                        yield json.loads(msg["data"])
                    except json.JSONDecodeError:
                        yield {"raw": msg["data"]}
        finally:
            await pubsub.unsubscribe(*channels)
            await pubsub.aclose() # <--- تم الإبقاء على aclose هنا لأنها خاصة بـ PubSub وليست Redis
