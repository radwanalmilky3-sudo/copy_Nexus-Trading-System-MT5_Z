# FLOWS_VALIDATION — Paper Fundamental Validation phase

**Domain:** FLOWS (COT / ETF flows / central-bank gold buying / market OI-volume) · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
FLOWS SOURCES             UNAVAILABLE (honest) — cftc, gold_etf,
                                central_bank_gold, market_flow all
                                config_required (licensed/endpoint sources)
ENGINE BEHAVIOR           PASS — flows domain = 0.0 score / 0.0 confidence /
                                0 coverage; fusion weight 0.0; flow_observations
                                = 0 rows; no fabrication, no proxy substitution
STRUCTURAL≠TRIGGER        PASS — central_bank_gold registry entry explicitly
                                forbids structural data as a direct M5 trigger
```

## Evidence

1. **Registry (all REAL providers, pending licensing/config):**
   - **cftc** — CFTC Commitments of Traders (trust 100, 6-h poll) → `config_required` (needs `CFTC_COT_ENDPOINT`).
   - **gold_etf** — licensed ETF-flow provider (trust 80) → `config_required` (`GOLD_ETF_DATA_ENDPOINT`); commercial note: «يتطلب مصدرًا مرخصًا/مسموح التخزين وفق شروط المزود.»
   - **central_bank_gold** (trust 85) → `config_required`; structural-data note: «بيانات هيكلية؛ لا تستخدم كمحفز مباشر لإطار M5.»
   - **market_flow** — OI/volume/options (trust 80, 60-s poll) → `config_required` (`MARKET_FLOW_DATA_ENDPOINT`).
2. **Live health:** `cftc|config_required|freshness=unavailable|يتطلب المصدر إعدادًا إضافيًا.` (observed 12:40:27+03 in `source_health_history`).
3. **Table** `flow_observations` = **0 rows** — nothing invented reached storage.
4. **Latest fusion** (13:04:31+03): `flows_score=None, flows_weight=0.0`.
5. **Factor cycle** (latest sample row): `domain=flows, native=0.0, gold_impact=0.0, direction=neutral, confidence=0.0, coverage=0.0, freshness=0.0, primary_drivers=[], counter_drivers=[]` — an explicit unavailable record, contributing zero to fusion and applying a coverage penalty (coverage 32.2/100 overall).

## Honesty / forbidden-list compliance

- Missing flows data is **not** converted into a neutral-but-present signal: weight 0 + zero confidence + coverage penalty.
- No MT5 position/flow data used as a fundamental proxy; no synthetic COT/ETF numbers.
- Structural central-bank buying (when later configured) is registered as structural context only — never a direct M5 entry trigger (registry commercial note).

## Activation path (documented, not performed)

Set `CFTC_COT_ENDPOINT` / `GOLD_ETF_DATA_ENDPOINT` / `CENTRAL_BANK_GOLD_ENDPOINT` / `MARKET_FLOW_DATA_ENDPOINT` to licensed providers and restart nexus-news; the domain will then ingest REAL rows with the same provenance chain (`observation_id`, `source_id`, timestamps, quality, trust) used by the other domains.

```text
FLOWS DOMAIN VALIDATION: PASS (honest UNAVAILABLE; zero fabrication; structural≠trigger enforced)
```
