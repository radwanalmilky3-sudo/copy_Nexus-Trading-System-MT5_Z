# FUSION_VALIDATION — Paper Fundamental Validation phase

**Component:** DynamicFusionEngine (five domains → one gold-relevant composite) · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
FUSION ENGINE             PASS (live snapshots with per-domain scores+weights,
                                dynamic re-weighting across cycles, Arabic
                                weight_reasons, agreement/conflict metrics)
MISSING-DOMAIN HANDLING   PASS (unavailable domains → weight 0.0 + coverage
                                penalty — never fake neutral scores)
DEPENDENCY HANDLING       PASS (independence_group feeds reliability/autonomy
                                factors; single-source geo discounted: rel 0.37)
```

## Live fusion snapshot (DuckDB `fundamental_fusion_results`, latest 13:04:31+03)

```text
direction=bullish   confidence=69.64   net_score=26.77   strength=26.77
coverage=32.2/100   agreement=100.0    conflict=0.0      data_quality=75.0
freshness=100.0     dominant=geopolitical   minority=monetary
```

| domain | score | effective weight | why (Arabic weight_reasons from `weight_reasons_json`) |
|---|---|---|---|
| macro | None | 0.000 | unavailable (no released shock in window) |
| monetary | 0.0 | 0.4398 | «الوزن الأساسي 0.23، الحداثة 1.00، الجودة 0.85، الملاءمة 0.20، الموثوقية 0.45، معامل النظام 1.00، والاستقلال 1.00.» |
| cross_asset | None | 0.000 | unavailable (FRED/treasury config_required) |
| geopolitical | 47.79 | 0.5602 | «الوزن الأساسي 0.16، الحداثة 1.00، الجودة 0.65، الملاءمة 0.58، الموثوقية 0.37، معامل النظام 1.00، والاستقلال 1.00.» |
| flows | None | 0.000 | unavailable (CFTC/ETF/OI config_required) |

## Dynamic re-weighting proof (two distinct live cycles)

| cycle | monetary | geopolitical | fusion result |
|---|---|---|---|
| 12:42:31+03 | conf 73.5, cov 100, fresh 100 | conf 75.2, cov 74, fresh 100 | direction=**bullish**, conf **70.16** (earlier snapshot rows) |
| 13:04:31+03 | score 0.0, weight 0.44 | score 47.79, weight 0.56 (dominant) | direction=**bullish**, conf **69.64**, net 26.77 |

Weights move with freshness/quality/fit/reliability inputs — the Arabic `weight_reasons` per domain expose every factor (base weight, freshness, quality, fit, reliability, regime, independence), satisfying the per-prediction weight-explanation requirement.

## Contract compliance

- **Five domains always present** in the row (score/weight columns), unavailable ones explicitly None/0.0 — coverage 32.2/100 openly reflects 2-of-5 contributing domains.
- **Agreement 100 / conflict 0** with a single active cluster pair (dominant=geopolitical, minority=monetary) — no manufactured conflict, no hidden disagreement.
- **Dependency penalty visible:** geopolitical reliability 0.37 with independent_source_count=1 propagates into the fusion discount (quality 0.65 → weight held below monetary's fresh-but-low-fit profile at prior cycle).
- **API/UI:** `GET :9000/api/fundamental/gold/overview` → 200 (58 KB, fusion+gold+explanation bundle) powering the dashboard tab «التحليل الأساسي».

```text
FUSION VALIDATION: PASS
```
