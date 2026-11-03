# PAPER_OBSERVATION_REPORT — Paper Fundamental Validation phase

**Window:** 2026-10-10 ~09:19Z–10:15Z (observation & repair) · **Mode:** PAPER · **Baseline:** `PAPER_BASELINE_CERTIFICATE.md`

## Phase timeline

| time (UTC) | event |
|---|---|
| ~09:19 | Phase start: fundamental tables inspected → all domain scores/predictions are zero-data shells; `fund_events`/`fund_sources` empty |
| ~09:2x | Root cause isolated: `upsert_source` SQL — DuckDB 1.5.5 BinderException on `updated_at=CURRENT_TIMESTAMP` inside `ON CONFLICT DO UPDATE SET`; reproduced on scratch DB |
| ~09:35 | One-token fix applied (`now()`, identical DB-clock semantics; persistence infrastructure only) |
| ~09:36 | nexus-data restarted via run.py watchdog (launcher respawn, health green) |
| ~09:38 | nexus-news restarted via watchdog → `initialize()` re-upserted all 15 sources |
| ~09:38–10:10 | Cascade verification: sources 15, events flowing, fusion/gold/explanations real; polls healthy; **zero** `persistence_failed` after restart |
| ~09:5x | pytest re-run with fix: **208 passed / 141.4 s / exit 0**; SHA manifest regenerated: **99 MATCH_AFTER + 1 DIVERGED (the fix) + 0 MISSING** |
| ~10:00 | Health sweep: 10/10 ports, executor paper-only, MT5 #2000020618 balance 1317.16 / 0 positions, Redis auto_trade=false / blackout clear / kill_switch unset |
| ~10:00–10:15 | Domain evidence collection (all five domains), fusion/gold/Arabic proofs, deliverables written |

## Before → after (live counts)

| table | before fix | after fix |
|---|---|---|
| fund_sources | 0 | **15** |
| fund_events | 0 | **≥100** (80 calendar + 20 Fed in latest slice) |
| macro_releases | 0 | **18+** |
| central_bank_events | 0 | **20** |
| source_health_history | 0 | **15+** (growing per poll) |
| market_series / flows / geo tables | 0 | 0 (honest UNAVAILABLE — see domain docs) |
| factor scores | zero shells | real: monetary 73.5 / geo 75.2 conf at live cycles; unavailable domains honest zeros |
| fusion / gold / explanations | zero shells | real bullish snapshots (conf ~70, full Arabic chain) |
| `fundamental.persistence_failed` | ~12,287 cumulative | **last at 09:37:51Z; zero after fix** |

## Guard & execution state (unchanged, re-verified)

```text
auto_trade            false (Redis, persisted)
kill_switch           unset
fundamental blackout  clear (actively recomputed; reason_ar present)
nexus-executor        broker=paper, trading_mode=paper, real_broker_execution_enabled=false
MT5                   #2000020618 balance 1317.16 USD, XAUUSD positions 0 (checked 10:00Z)
```

No real orders were sent at any point of this phase. No MT5/Redis/Ollama shutdowns. No scoring/fusion/contracts code was modified — the single source change is the documented one-token persistence fix.

## Open observations (recorded, non-blocking)

1. **API `latest_rows` order-column quirk** — tables without `created_at` (macro_releases, central_bank_events, news_articles, geopolitical_events) 500 on the default `order_col`; pass `release_timestamp`/`event_id`/`published_at`. `prediction_reasoning_steps`/`source_fetch_runs` are outside the latest allowlist (evidence via joined tables/logs).
2. **Legacy `GET :9005/api/news/calendar` returns []** — the legacy parser mirror is not fed by FundamentalRuntime; canonical calendar = Redis `nexus:news:calendar` (83) + DuckDB (80 fund_events / 18 macro_releases). Dashboard fundamental tab uses the `:9000/api/fundamental/*` proxies (all 200) — no impact on fusion; worth unifying in a future pack iteration (semantic change — not applied here).
3. **News provider relevance quality degraded** — live batch contains off-topic headlines (Pokémon cards etc.); geo/fusion correctly discount it (quality 0.65, reliability 0.37). Provider query tuning is an operational follow-up.
4. **BLS healthy but series rows not yet observed in sampled tables** — poll interval 900 s; fetch health rows prove live HTTP-200 ingestion path; series landing to be confirmed over a longer window.
5. **macro actuals absent** — secondary calendar delivers forecast/previous only for in-window events; engine correctly takes no shock credit (no leakage).
6. **model_evaluations latest endpoint** 500s on default order column (same quirk family as #1).
7. Standing tech debt unchanged: nexus-news Redis client lacks socket timeouts (watchdog recovery verified); WSL keep-alive required for Redis VM.

## Deliverables issued this phase

`PAPER_BASELINE_CERTIFICATE.md` · `FUNDAMENTAL_SOURCE_VALIDATION.md` · `MACRO_VALIDATION.md` · `MONETARY_VALIDATION.md` · `CROSS_ASSET_VALIDATION.md` · `GEOPOLITICS_VALIDATION.md` · `FLOWS_VALIDATION.md` · `FUSION_VALIDATION.md` · `GOLD_IMPACT_VALIDATION.md` · `ARABIC_EXPLANATION_VALIDATION.md` · `PAPER_OBSERVATION_REPORT.md` (this file) · refreshed `SHA_MANIFEST.json`

## Final status

```text
PAPER FUNDAMENTAL VALIDATION PASS
```

Rationale: the one true fundamental blocker (dead persistence chain) was proven, fixed with a semantics-identical one-token change, regression-tested (208/208), and the full five-domain → fusion → gold-impact → Arabic-explanation pipeline now runs on REAL sources with honest UNAVAILABLE handling wherever configuration is missing. No mock data, no proxy-as-real, no missing-as-neutral, no leakage, no FinBERT-as-gold-direction, no structural-as-M5-trigger, no duplicate-as-independent — all verified against live rows. This is **not** a `READY FOR LIVE` statement.
