# CROSS_ASSET_VALIDATION — Paper Fundamental Validation phase

**Domain:** CROSS-ASSET (DXY / US10Y / yields–dollar–gold transmission) · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
CROSS-ASSET SOURCES       UNAVAILABLE (honest) — fred + treasury require API
                                keys/endpoints (config_required); no data fabricator
RUNTIME CACHE             UNAVAILABLE (honest) — Redis nexus:cross_asset:summary
                                available=false, origin=unavailable
ENGINE BEHAVIOR           PASS — domain score/conf = 0, fusion weight = 0.0,
                                coverage penalty applied; zero synthetic levels
PROXY GUARD               PASS — code refuses origin in {unavailable, synthetic};
                                proxy origin would be labeled quality 60, never 78
```

## Evidence

1. **fred** (`https://api.stlouisfed.org/fred`, REAL Federal Reserve Bank of St. Louis, trust 98) and **treasury** (REAL U.S. Treasury, trust 100) are registry-live but `config_required` — live health rows: `fred|config_required|freshness=unavailable|يتطلب المصدر إعدادًا إضافيًا.` (recurring every poll cycle; honest failure, not silent skip).
2. **Redis runtime cache** `nexus:cross_asset:summary` (written by the cross-asset feeder):
   ```json
   {"dxy":{"level":0.0,"source":"unavailable"},"us10y":{"level":0.0,"source":"unavailable"},
    "gold_yield_regime":"unavailable","available":false,"origin":"unavailable",
    "updated_at":"2026-10-10T10:09:48Z"}
   ```
3. **Gate code** (`runtime.py:_cross_from_runtime_cache`): returns `[]` unless `available=true` and `origin ∉ {unavailable, synthetic}`; proxy-origin rows would carry `quality_score=60` (vs 78 for real) — a proxy can never masquerade as a real feed.
4. **Table** `market_series_observations` = **0 rows** — nothing fabricated reached storage.
5. **Latest fusion** (13:04:31+03): `cross_asset_score=None, cross_asset_weight=0.0`; coverage 32.2/100 reflects the two missing domains (macro + cross_asset + flows) instead of being papered over with neutral scores.

## Transmission-chain honesty

The gold prediction's Arabic transmission chain («المحاور الأساسية الخمسة → الدمج الديناميكي → العوائد والدولار/الملاذ الآمن → XAUUSD») names the *mechanism*; with cross-asset inputs unavailable, the chain node «العوائد والدولار» contributes no data-driven points, and the weakening factor «تغطية البيانات أقل من المستوى المثالي.» records exactly that. No MT5 DXY/Yield proxy, no invented levels.

## API / UI

- `GET :9000/api/fundamental/cross_asset` → 200 (part of FundamentalWorkspace).
- To activate this domain: set `FRED_API_KEY` (and/or `TREASURY_DATA_ENDPOINT`) and restart nexus-news — the engine will then ingest REAL series with provenance; until then the domain stays honestly zero-weighted.

```text
CROSS-ASSET DOMAIN VALIDATION: PASS (honest UNAVAILABLE; anti-proxy guard verified; zero fabrication)
```
