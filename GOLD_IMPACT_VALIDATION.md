# GOLD_IMPACT_VALIDATION — Paper Fundamental Validation phase

**Component:** GoldImpact prediction layer (fusion → XAUUSD direction/strength/horizons) · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
GOLD IMPACT ENGINE        PASS (live prediction with direction, strength,
                                confidence, 4-horizon probability triples,
                                stage, blackout flag, structural bias)
TRANSMISSION CHAIN        PASS (explicit 4-node chain persisted per prediction)
INVALIDATION              PASS (3 concrete Arabic invalidation conditions)
HONESTY                  PASS (confidence_validation=unvalidated; weakening
                                factor for low coverage recorded; no backfill)
```

## Live prediction (DuckDB `gold_impact_predictions`, latest 13:04:31+03)

```text
prediction_id   0a642bee8a9f418ab007f4cbefe49fde
event_id        cal-feddefac94b13027a1d12e08   (Prelim UoM Consumer Sentiment — REAL calendar event)
direction       bullish          strength 26.77/100      confidence 69.64/100
coverage 32.2   freshness 100.0  data_quality 75.0       conflict 0.0
prediction_stage=at_release     structural_bias=neutral  model_version=1.0.0
blackout_active=False           (consistent with Redis nexus:fundamental:blackout=clear)
```

### Per-horizon probability triples (bull / bear / neutral)

| horizon | bullish | bearish | neutral |
|---|---|---|---|
| 5m | 0.440 | 0.215 | 0.345 |
| 15m | 0.435 | 0.220 | 0.345 |
| 60m | 0.421 | 0.234 | 0.345 |
| 4h | 0.399 | 0.256 | 0.345 |

Probabilities decay with horizon (bull 0.44→0.40 as uncertainty compounds) — no flat overconfident distribution.

### Transmission chain (`transmission_chain_json`)

```text
["المحاور الأساسية الخمسة", "الدمج الديناميكي", "العوائد والدولار/الملاذ الآمن", "XAUUSD"]
```
Event → economic meaning → fusion → rates/yields/dollar/safe-haven → XAUUSD, exactly the mandated reasoning route. With the cross-asset node unavailable, the chain is still recorded and the weakness surfaces as coverage penalty + weakening factor (no invented confirmation — per the failed-link rule).

### Confirmation / contradiction / invalidation

- **Confirmations (3):** geo metrics «شدة الحدث 49/100، التصعيد 49/100، ضغط الملاذ الآمن 37/100، والمصادر المستقلة 1.» + monetary tone line «النبرة الحالية +0.0 مقابل السابقة +0.0…» (repeated in the geo+monetary cluster pair).
- **Contradictions:** `[]` — none recorded (honestly empty, not suppressed).
- **Weakening:** `["تغطية البيانات أقل من المستوى المثالي."]` — low coverage (32.2) explicitly discounts confidence.
- **Invalidation (3):** (1) sustained reversal of dollar & real yields against the scenario; (2) new high-impact event changing the market/policy regime; (3) data quality/freshness degrading to unavailable.
- **`confidence_validation=unvalidated`** — the model honestly states the confidence is not yet historically calibrated (calibration requires outcome accumulation in `fundamental_event_outcomes`; `actual_outcome_ar=«لم يتم تقييم النتيجة الفعلية بعد.»`).

## Forbidden-list compliance

No post-event leakage (prediction built pre/outcome-null), structural bias is `neutral` and separate from the event-driven call, blackout flag mirrors the live guard state, and no MT5 order was or can be generated from this layer in PAPER mode (executor `broker=paper`, `real_broker_execution_enabled=false`, positions 0).

## API / UI

`GET :9000/api/fundamental/gold/overview` → 200 (58 KB bundle: overview + probabilities + chain + invalidations) rendered by `FundamentalWorkspace` (dashboard tab «التحليل الأساسي»).

```text
GOLD IMPACT VALIDATION: PASS
```
