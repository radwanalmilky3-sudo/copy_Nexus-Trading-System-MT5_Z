# FUNDAMENTAL_SOURCE_VALIDATION — Paper Fundamental Validation phase

**Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER · **Baseline:** `PAPER_BASELINE_CERTIFICATE.md`

## Verdict

```text
SOURCE REGISTRY            PASS (15/15 sources registered in fund_sources, real
                                 endpoints/auth/retention metadata per source)
LIVE OFFICIAL SOURCES      PASS (fed_rss + bls healthy with real HTTP-200 fetches;
                                 calendar_secondary 83 events ingested)
CONFIG_REQUIRED SOURCES    HONEST UNAVAILABLE (fred, cftc, bea, treasury, imf,
                                 gold_etf, central_bank_gold, market_flow, world_bank)
NEWS PROVIDERS             REAL BUT LICENSE-RESTRICTED (newsapi/gnews live keys,
                                 storage_allowed=False — Redis snapshot only)
PERSISTENCE FOUNDATION     PASS (root bug found & fixed this phase, see below;
                                 zero persistence_failed after fix)
```

## Root-cause fix that made source validation possible

`upsert_source()` in `services/nexus_data/fundamental_store.py:50` used `updated_at=CURRENT_TIMESTAMP` inside `ON CONFLICT ... DO UPDATE SET`. DuckDB 1.5.5 binds that as a column identifier → BinderException on **every** source upsert → `fund_sources` stayed empty → 5,407 `source_id` FK failures cascaded to all event tables (zero-data shells). Fix: `updated_at=now()` (identical DB-clock semantics, persistence infrastructure only, no scoring/fusion/contracts change). Verified: `fund_sources 0 → 15`, all downstream tables filling, `last persistence_failed = 09:37:51Z` (pre-restart), zero after, pytest 208/208.

## Source registry (live table `fund_sources`, 15 rows)

| source_id | domain | endpoint | auth | trust | storage | live state |
|---|---|---|---|---|---|---|
| bls | macro | api.bls.gov/publicAPI/v2 | optional key | 100 | yes | **healthy** (HTTP 200, ~2.5–2.8 s) |
| fed_rss | monetary | federalreserve.gov/feeds/press_all.xml | none | 100 | yes | **healthy** (HTTP 200, ~1.4–3.7 s, recurring) |
| calendar_secondary | calendar | nfs.faireconomy.media/ff_calendar_thisweek.json | none | 65 | yes | **healthy** (83 events → fund_events/macro_releases) |
| fred | cross_asset | api.stlouisfed.org/fred | API key | 98 | yes | config_required (FRED_API_KEY unset) |
| cftc | flows | endpoint config | env endpoint | 100 | yes | config_required |
| bea / treasury / imf / world_bank | macro/cross | official | key/endpoint | 98–100 | yes | config_required |
| gold_etf / central_bank_gold / market_flow | flows | licensed provider | endpoint env | 80–85 | yes | config_required |
| newsapi / gnews / news_secondary | news | newsapi.org / gnews.io | API keys | 60–70 | **no** | live keys; Redis-only snapshot by licensing |

Live `source_health_history` rows (UTC+3): repeated `fed_rss|healthy|fresh|code=200|lat 1.4–3.7 s|المصدر يعمل وتم جلب بيانات حقيقية.` · `bls|healthy|fresh|code=200|lat 2.5–2.8 s` · `fred|config_required|unavailable|يتطلب المصدر إعدادًا إضافيًا.` · `cftc|config_required`.

## API / UI surface

- `GET :9001/api/data/fundamental/latest/fund_sources?limit=30` → 200, count=15.
- `GET :9000/api/fundamental/sources/health` → 200 (5.9 KB) — dashboard source-health panel.
- Dashboard `/dashboard` tab **«التحليل الأساسي»** mounts `FundamentalWorkspace` (fundamental source health + domains + gold overview).

## Forbidden-list compliance

No mock/fake sources; every live row carries `source_id` + endpoint + HTTP status + latency + Arabic health description. Missing credentials → `config_required`/`unavailable`, never substituted by a proxy or synthetic value. Retention respected (`storage_allowed=False` for news providers — articles never persisted to DuckDB).

```text
SOURCE VALIDATION: PASS
```
