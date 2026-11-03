"""Tests for shared.redis_client — cache and stream helpers."""
from __future__ import annotations

import pytest
import pytest_asyncio

from shared.redis_client import RedisClient


class TestRedisClientCache:
    @pytest.mark.asyncio
    async def test_cache_set_and_get(self, redis_client: RedisClient):
        await redis_client.cache_set("test:key", {"value": 42})
        result = await redis_client.cache_get("test:key")
        assert result == {"value": 42}

    @pytest.mark.asyncio
    async def test_cache_get_missing_key(self, redis_client: RedisClient):
        result = await redis_client.cache_get("nonexistent:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_delete(self, redis_client: RedisClient):
        await redis_client.cache_set("del:key", "value")
        await redis_client.cache_delete("del:key")
        result = await redis_client.cache_get("del:key")
        assert result is None


class TestRedisClientStream:
    @pytest.mark.asyncio
    async def test_publish_event(self, redis_client: RedisClient):
        from shared.events import TickEvent

        event = TickEvent(symbol="EURUSD", bid=1.085, ask=1.0852)
        entry_id = await redis_client.publish_event("stream:test", event)
        assert entry_id is not None

    @pytest.mark.asyncio
    async def test_ensure_consumer_group(self, redis_client: RedisClient):
        await redis_client.ensure_consumer_group("stream:test", "test-group")

    @pytest.mark.asyncio
    async def test_delivery_is_acknowledged_only_when_consumer_explicitly_acks(self):
        from shared.constants import RedisStream

        class FakeRedis:
            def __init__(self):
                self.acknowledged = []

            async def xgroup_create(self, *args, **kwargs):
                return None

            async def xreadgroup(self, **kwargs):
                return [("stream:ticks", [("123-0", {
                    "event_type": "tick",
                    "source": "test",
                    "symbol": "EURUSD",
                    "bid": "1.1",
                    "ask": "1.2",
                })])]

            async def xack(self, *args):
                self.acknowledged.append(args)

        client = RedisClient()
        fake_redis = FakeRedis()
        client._redis = fake_redis
        deliveries = client.subscribe_deliveries(RedisStream.TICK_STREAM, "test-group", "test-worker")

        delivery = await anext(deliveries)
        assert delivery.event.symbol == "EURUSD"
        assert fake_redis.acknowledged == []

        await delivery.ack()
        assert fake_redis.acknowledged == [(str(RedisStream.TICK_STREAM), "test-group", "123-0")]
        await deliveries.aclose()


class TestRedisClientHealth:
    @pytest.mark.asyncio
    async def test_health_check(self, redis_client: RedisClient):
        healthy = await redis_client.health_check()
        assert healthy is True

    @pytest.mark.asyncio
    async def test_not_connected_raises(self):
        client = RedisClient(url="redis://localhost:9999/0")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = client.r
