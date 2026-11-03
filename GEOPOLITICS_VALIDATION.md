# GEOPOLITICS_VALIDATION — Paper Fundamental Validation phase

**Domain:** GEOPOLITICS · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
GEOPOLITICS ENGINE        PASS (live domain score 47.79 with severity/
                                escalation/safe-haven/independence metrics;
                                fusion weight 0.56 dominant cluster)
NEWS PROVIDERS            REAL (newsapi/gnews live API keys, real headlines
                                fetched) — QUALITY DEGRADED (off-topic items
                                present; provider trust capped at 70)
STORAGE POLICY            PASS (storage_allowed=False → no article text in
                                DuckDB by licensing; Redis snapshot only)
INDEPENDENCE / DEDUP      PASS (independence_group / causal_group_id /
                                dedup_group_id on every event; reprints cannot
                                count as independent confirmations)
```

## Real source & provenance

- **newsapi** (`https://newsapi.org/v2`, REAL provider, trust 70) and **gnews** (`https://gnews.io/api/v4`, REAL, trust 70) with live keys — `GET :9005/api/news/latest` returned **36 real fetched articles** post-restart.
- **Honest quality note:** fetched batch relevance is degraded — sample headlines: «K92 Mining Announces 2026 Third Quarter Financial Results…» (finance-adjacent) vs «4 Stunningly Rare Perfect 10 E-Reader Pokémon Cards…» (off-topic). This is a **provider relevance limitation**, recorded, not hidden: geo scoring only consumes keyword-matched clusters; unmatched items contribute nothing.
- **Licensing:** `storage_allowed=False` for newsapi/gnews/news_secondary → `news_articles` and `geopolitical_events` tables legitimately contain **0 rows**; the live snapshot lives in Redis (`nexus:news` cache) and in-memory cluster state. This is policy compliance, not an outage.
- Geopolitical records (in-memory, persisted path `_persist_geo_event` gated on storage permission) carry `severity_score, escalation_score, deescalation_score, persistence_score, global_relevance, safe_haven_score, energy_risk_score, currency_risk_score, source_consensus_score, independent_source_count, story_cluster_id, gold_implication_score, confidence` + `event_id=geo:{story_cluster_id}`.

## Engine evidence (live)

- Latest fusion (13:04:31+03): `geopolitical_score=47.79, geopolitical_weight=0.5602`, **dominant cluster**; Arabic weight reason: «الوزن الأساسي 0.16، الحداثة 1.00، الجودة 0.65، الملاءمة 0.58، الموثوقية 0.37، معامل النظام 1.00، والاستقلال 1.00.» — quality 0.65 and reliability 0.37 correctly discount the degraded provider batch.
- Prediction confirmations expose the raw geo metrics: «شدة الحدث 49/100، التصعيد 49/100، ضغط الملاذ الآمن 37/100، والمصادر المستقلة 1.» — **independent_source_count = 1** is stated explicitly; a single source can never be double-counted as multi-source confirmation.
- Earlier factor cycle: `geopolitical confidence=75.2, coverage=74, freshness=100`.

## Forbidden-list compliance

- FinBERT sentiment is **not** used as gold direction (gold call comes from the five-domain fusion; FinBERT is a per-article feature only).
- Duplicate/reprinted headlines are collapsed via `dedup_group_id`/`independence_group` before any confirmation counting.
- No article text persisted contrary to license; no fabricated severity numbers.

## API / UI

- `GET :9000/api/fundamental/news` → 200 (33 KB) and `GET :9000/api/fundamental/geopolitical` (FundamentalWorkspace tab «التحليل الأساسي»).
- Legacy `GET :9005/api/news/calendar` returns [] because the legacy parser mirror is not fed by FundamentalRuntime (canonical calendar = Redis 83 + DuckDB 80/27 rows) — documented in `PAPER_OBSERVATION_REPORT.md`; no effect on the fusion path.

```text
GEOPOLITICS DOMAIN VALIDATION: PASS (real providers, honest quality discount, independence enforced)
```
