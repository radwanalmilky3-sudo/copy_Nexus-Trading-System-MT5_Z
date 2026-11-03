"""
Shared FastAPI dependency providers.

Every router imports from here instead of ``main`` to avoid circular imports.
The singletons are populated by the lifespan in ``main.py``.
"""
from __future__ import annotations

from shared.config_loader import ConfigLoader
from shared.redis_client import RedisClient

from .data_client import DataServiceClient
from .websockets.manager import ConnectionManager

redis: RedisClient = RedisClient()
data_service: DataServiceClient = DataServiceClient()
config_loader: ConfigLoader = ConfigLoader()
ws_manager: ConnectionManager = ConnectionManager()


def get_redis() -> RedisClient:
    return redis


def get_data_service() -> DataServiceClient:
    return data_service


def get_config() -> ConfigLoader:
    return config_loader


def get_ws_manager() -> ConnectionManager:
    return ws_manager
