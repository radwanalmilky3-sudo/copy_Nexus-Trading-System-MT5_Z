from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from shared.source_manager import SourceManagerStore


def test_official_sources_are_not_deletable():
    with TemporaryDirectory() as d:
        store = SourceManagerStore(Path(d))
        with pytest.raises(ValueError):
            store.delete_source("fred")


def test_custom_source_lifecycle_is_persistent_and_fail_closed():
    with TemporaryDirectory() as d:
        store = SourceManagerStore(Path(d))
        source = store.upsert_source(
            "my_flow",
            {
                "name_ar": "مصدر تدفق مخصص",
                "name_en": "Custom Flow",
                "category": "flows",
                "transport": "json",
                "endpoint": "https://example.com/data",
                "analysis_mapping": "health_only",
                "enabled": True,
            },
            custom=True,
        )
        assert source["custom"] is True
        assert source["analysis_mapping"] == "health_only"
        assert source["secret_configured"] is False

        store.upsert_source("my_flow", {"enabled": False})
        assert store.get_source("my_flow")["enabled"] is False

        store2 = SourceManagerStore(Path(d))
        assert store2.get_source("my_flow")["endpoint"] == "https://example.com/data"
        store2.delete_source("my_flow")
        assert store2.get_source("my_flow") is None


def test_invalid_endpoint_and_mapping_are_rejected():
    with TemporaryDirectory() as d:
        store = SourceManagerStore(Path(d))
        with pytest.raises(ValueError):
            store.upsert_source("bad_source", {
                "name_ar": "سيئ", "name_en": "Bad", "category": "macro",
                "transport": "json", "endpoint": "file:///etc/passwd",
            }, custom=True)
        with pytest.raises(ValueError):
            store.upsert_source("bad_mapping", {
                "name_ar": "سيئ", "name_en": "Bad", "category": "macro",
                "transport": "json", "endpoint": "https://example.com",
                "analysis_mapping": "trade_everything",
            }, custom=True)


def test_builtin_public_connections_have_endpoints():
    with TemporaryDirectory() as d:
        store = SourceManagerStore(Path(d))
        for sid in ("bls", "fed_rss", "cftc", "treasury", "world_bank", "imf"):
            source = store.get_source(sid)
            assert source is not None
            assert str(source.get("endpoint", "")).startswith("https://")
