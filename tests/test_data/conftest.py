import pytest_asyncio

from services.nexus_data.duckdb_store import DataStore


@pytest_asyncio.fixture
async def operational_store(tmp_path):
    store = DataStore(str(tmp_path / 'operational.duckdb'))
    await store.init_tables()
    try:
        yield store
    finally:
        await store.aclose()
