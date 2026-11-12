# qa/repro_d3_fundamental.py — Reproduce the 400 "record violates schema constraints"
# from logs/run_out.log (2026-11-09 21:29:55 burst) against a FRESH temp DB.
#
# Uses the REAL production code path:
#   DataStore(temp) -> init_tables() -> FundamentalStore.insert_record()
# with the REAL record builders from nexus_news.
# Never touches data/nexus.duckdb (production) — temp file only.
#
# Run: venv-nexus/Scripts/python.exe qa/repro_d3_fundamental.py

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.nexus_data.duckdb_store import DataStore  # noqa: E402
from services.nexus_data.fundamental_store import FundamentalStore  # noqa: E402
from services.nexus_news.fundamental.bootstrap_v5 import (  # noqa: E402
    asset_factor_profile_records,
    asset_records,
    indicator_catalog_records,
    knowledge_seed,
)
from services.nexus_news.fundamental.normalization import (  # noqa: E402
    calendar_event_record,
    calendar_to_macro,
)
from services.nexus_news.fundamental.runtime import _jsonable  # noqa: E402

results: list[tuple[str, str]] = []


async def try_insert(store: FundamentalStore, table: str, record: dict, label: str) -> None:
    try:
        await store.insert_record(table, record)
        results.append((label, "OK"))
    except Exception as exc:
        results.append((label, f"FAIL {type(exc).__name__}: {str(exc)[:180]}"))


async def main() -> None:
    tmp = os.path.join(tempfile.gettempdir(), "nexus_repro_d3.duckdb")
    for suffix in ("", ".wal"):
        if os.path.exists(tmp + suffix):
            os.remove(tmp + suffix)

    ds = DataStore(tmp)
    await ds.init_tables()
    # The data service loads the fundamental schema separately (see main.py
    # "fundamental.schema_ready") — replicate that here.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "services", "nexus_data", "fundamental_schema.sql"), encoding="utf-8") as fh:
        await ds._run_script(fh.read())
    mig = os.path.join(root, "services", "nexus_data", "migrations", "research_lineage_001.sql")
    if os.path.exists(mig):
        with open(mig, encoding="utf-8") as fh:
            await ds._run_script(fh.read())
    store = FundamentalStore(ds)

    # 1) fund_sources rows FIRST (the runtime seeds sources before governance
    #    tables; catalog rows carry source_id with a real FK to fund_sources).
    from services.nexus_news.fundamental.source_registry import OFFICIAL_SOURCES

    for src in OFFICIAL_SOURCES:
        rec = src.as_record()
        try:
            await store.upsert_source(_jsonable(rec))
            results.append((f"src:{str(src.source_id)[:28]}", "OK"))
        except Exception as exc:
            results.append((f"src:{str(src.source_id)[:28]}", f"FAIL {type(exc).__name__}: {str(exc)[:180]}"))

    # 2) Governance seed tables (bootstrap_v5)
    for row in indicator_catalog_records():
        await try_insert(store, "economic_indicator_catalog", _jsonable(row), f"catalog:{str(row.get('indicator_id', '?'))[:28]}")
    for row in asset_records():
        await try_insert(store, "asset_registry", _jsonable(row), f"asset:{str(row.get('asset_id', '?'))[:28]}")
    for row in asset_factor_profile_records():
        await try_insert(store, "asset_factor_profiles", _jsonable(row), f"profile:{str(row.get('profile_id', '?'))[:28]}")
    sources, claims = knowledge_seed()
    for row in sources:
        await try_insert(store, "fundamental_knowledge_sources", _jsonable(row), f"ksrc:{str(row.get('source_id', '?'))[:28]}")
    for row in claims:
        await try_insert(store, "fundamental_knowledge_claims", _jsonable(row), f"claim:{str(row.get('claim_id', '?'))[:28]}")

    # 3) fund_sources row for calendar_secondary is already covered above if
    #    present in SOURCE_REGISTRY; keep the explicit upsert as a fallback.
    try:
        await store.upsert_source({
            "source_id": "calendar_secondary",
            "name_ar": "التقويم الاقتصادي الثانوي",
            "name_en": "Secondary Economic Calendar",
            "category": "calendar",
            "transport": "http",
        })
        results.append(("src:calendar_secondary", "OK"))
    except Exception as exc:
        results.append(("src:calendar_secondary", f"FAIL {type(exc).__name__}: {str(exc)[:180]}"))

    # 3) Calendar → fund_events → macro_releases (the D3 suspect path)
    class FakeCal:  # field-shape of CalendarEvent used by the builders
        source = "calendar_secondary"
        event_name = "US Non-Farm Payrolls"
        currency = "USD"
        timestamp = datetime(2026, 11, 9, 15, 30, tzinfo=timezone.utc)
        impact = "high"
        actual = "150K"
        forecast = "180K"
        previous = "120K"

        def model_dump(self, mode="json"):  # matches the pydantic CalendarEvent API
            return {
                "source": self.source, "event_name": self.event_name, "currency": self.currency,
                "timestamp": self.timestamp.isoformat(), "impact": self.impact,
                "actual": self.actual, "forecast": self.forecast, "previous": self.previous,
            }

    ev = calendar_event_record(FakeCal())
    await try_insert(store, "fund_events", _jsonable(ev), "fund_events:calendar")
    macro = calendar_to_macro(FakeCal())
    if macro:
        db_macro = {k: v for k, v in macro.items() if k in {
            "event_id", "indicator_code", "indicator_name_en", "indicator_name_ar", "frequency", "unit",
            "actual", "forecast", "previous", "first_release_value", "revised_previous", "latest_value",
            "consensus_low", "consensus_high", "surprise_absolute", "surprise_percent", "surprise_zscore",
            "revision_effect_score", "historical_importance", "gold_relevance", "rate_implication_score",
            "usd_implication_score", "yield_implication_score", "gold_implication_score",
            "release_timestamp", "revision_timestamp",
        }}
        await try_insert(store, "macro_releases", _jsonable(db_macro), "macro_releases:calendar")

    print("\n===== REPRO RESULTS =====")
    fails = 0
    for label, status in results:
        flag = "" if status == "OK" else "  <<<<"
        if status != "OK":
            fails += 1
        print(f"{label:48} {status}{flag}")
    print(f"\ntotal={len(results)} failures={fails}")


if __name__ == "__main__":
    asyncio.run(main())
