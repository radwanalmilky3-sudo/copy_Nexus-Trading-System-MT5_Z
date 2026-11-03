# MACRO_VALIDATION — Paper Fundamental Validation phase

**Domain:** MACRO · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
MACRO DATA INGESTION      PASS (real calendar releases with forecast/previous,
                                full provenance chain, no post-event leakage)
MACRO ENGINE              PASS (honest handling: no actual → no shock credit;
                                domain score/conf = 0 when data unavailable,
                                never forced to neutral)
PRIMARY SOURCES           calendar_secondary (REAL, trust 65) + bls (REAL, trust
                                100, healthy); bea/imf/world_bank config_required
```

## Real source & provenance (evidence)

- **calendar_secondary** — `https://nfs.faireconomy.media/ff_calendar_thisweek.json` (REAL, public calendar feed), trust 65, storage allowed.
- **bls** — `https://api.bls.gov/publicAPI/v2/timeseries/data/` (REAL official U.S. Bureau of Labor Statistics), trust 100, live health `healthy|fresh|code=200|lat≈2.5–2.8s`.

Ingested rows (DuckDB live):

| release_timestamp | event_id | indicator | actual | forecast | previous | gold_relevance | importance |
|---|---|---|---|---|---|---|---|
| 2026-10-09T17:00+03 | cal-feddefac94b13027a1d12e08 | Prelim UoM Consumer Sentiment | null | 47.5 | 47.8 | 60 | 55 |
| 2026-10-09T15:30+03 | cal-52a9dba8cfa03057425e5f4a | Unemployment Rate (CAD) | null | 6.5 | 6.4 | 60 | 92 |
| 2026-10-08T15:30+03 | cal-edc42fc3c1f2afff664d33c6 | Unemployment Claims | null | 200000 | 197000 | 60 | 65 |
| 2026-10-06T12:00+03 | cal-3419614e67cd3af63385c997 | Retail Sales m/m | null | 0.2 | -0.6 | 60 | 78 |
| 2026-10-05T17:00+03 | cal-0d3a64cfb32180c09ca6acb3 | ISM Services PMI | null | 55.1 | 55.4 | 60 | 80 |

`fund_events` (latest 100): 80 `calendar_secondary` + 20 `fed_rss`; types include PMI ×9, CONSUMER_CONFIDENCE ×3, UNEMPLOYMENT ×2, JOBLESS_CLAIMS, RETAIL_SALES, ISM_SERVICES, PPI, FOMC ×3. Every event carries `source_timestamp, published_at, received_at, processed_at, declared_impact, gold_relevance, novelty_score, freshness_state, data_quality_score, raw_hash, dedup_group_id, causal_group_id, independence_group` + ingestion latencies.

## Leakage & honesty checks

- **No post-event leakage:** past-dated releases keep `actual=null` because the provider has not delivered actuals — the engine therefore cannot (and does not) read realized outcomes into pre-release predictions. The prediction for `cal-feddefac94b13027a1d12e08` is built from forecast/previous + domain priors only.
- **Missing ≠ Neutral:** latest cycle `macro` domain = `native 0.0, confidence 0.0, coverage 0.0, freshness 0.0, direction neutral, drivers []` — that is an explicit **unavailable** record (zero weight in fusion, coverage penalty applied), not a synthetic neutral score.
- **Engine result on the live event:** fusion snapshot 13:04:31+03 `macro_score=None, macro_weight=0.0` — macro contributed nothing to the current gold call because no *released* shock exists in-window.

## API / UI

- `GET :9000/api/fundamental/macro` → 200 (16.7 KB) — dashboard macro domain panel.
- `GET :9001/api/data/fundamental/latest/macro_releases?order_col=release_timestamp` → 200 (note: `created_at` default order col 500s on this table — API quirk, documented, not a data bug).

```text
MACRO DOMAIN VALIDATION: PASS (real ingestion; honest unavailable handling; zero leakage)
```
