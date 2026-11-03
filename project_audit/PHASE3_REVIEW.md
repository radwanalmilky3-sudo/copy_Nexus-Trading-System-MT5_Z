# Phase 3 Review — Portfolio Risk Gates (G4/G5)

**Reviewer:** R1 · **Date:** 2026-10-18 · **Scope:** C1 (`rules_engine.py`, `risk_rules.yaml`, `test_portfolio_gates.py`) + C2 (`main.py`, `test_portfolio_gates_main.py`) + A0 master-flag gate

## Verdict: **APPROVE WITH NOTES**

All hard gates of the audit checklist pass; the full suite is green (1175/1175). Three notes (C-1…C-3 below) should be recorded for A0 before the Phase 3 commit, but none is an unsanctioned deletion, safety regression, or golden-decision risk in the shipped (default) configuration.

---

## 1. Change-set classification

`git status` (tracked):

| File | Δ | Expected |
|---|---|---|
| `services/nexus_risk/rules_engine.py` | +582/−27 | ✅ C1 |
| `services/nexus_risk/main.py` | +1087/−7 | ✅ C2 |
| `config/risk_rules.yaml` | +10/−0 | ✅ C1 |
| `tests/test_risk/test_portfolio_gates.py` | new, 446 L, 84 tests | ✅ C1 |
| `tests/test_risk/test_portfolio_gates_main.py` | new, 511 L, 29 tests | ✅ C2 |

No other tracked file modified. No `.env`, `run.py`, `shared/`, or `models/` changes. No new services.

**Untracked pre-existing directory:** `fx-trading-system-main/` (728 files, created 2026-10-17 16:01, i.e. before this work; not in the diff, not touched by C1/C2). Flagged in C-3 below.

### Deletion classification (34 deleted lines total) — ALL SANCTIONED

`services/nexus_risk/rules_engine.py` (27):
- 4× `raw.get("capital"/"exposure"/"execution"/"calendar", {})` → `.get(...) or {}` — rewrite (null-section tolerance). Sanctioned.
- 9-line inline `corr_pairs` dict → hoisted to module constant `_STATIC_CORR_PAIRS` — rewrite/move, values byte-identical. Sanctioned.
- `_b(...)` helper → `_row(...)` (adds tracked-state merge for G5). Rewrite. Sanctioned.
- 12× hardcoded breaker rows `_b("anti_stacking", False, "")`, `_b("anti_revenge", False, "")`, `_b("session_gate", False, "")`, `_b("min_conviction", False, "")`, `_b("daily_trade_limit", False, "")`, `_b("trade_cooldown", False, "")`, `_b("correlation_limit", False, "")`, `_b("spread_limit", False, "")`, `_b("news_blackout", False, "")` — the old decorative `triggered:False` rows; replaced by honest rows (engine-computed or G5 state-fed). Sanctioned (this is the G5 fix itself).

`services/nexus_risk/main.py` (7):
- `from typing import Any, Literal` → `Any, Callable, Literal` — import extension. Sanctioned.
- `global _daily_trade_count` → `global _daily_trade_count, _daily_trades_limit_observed` — extension. Sanctioned.
- 3× `breakers = rules_engine.get_active_circuit_breakers(_current_state)` → `await _breaker_report_state()` — rewrite (honest breakers). Sanctioned.
- `"correlation_exposure": 0.0` in `get_exposure` → real state value (G4: old hardcoded 0.0). Sanctioned.
- `"any_triggered": len(breakers) > 0` → `any(bool(b.get("triggered")) for b in breakers)` — G5 honesty fix (old logic counted non-triggered rows). Sanctioned.

**No unsanctioned functional deletions.**

## 2. Golden safety triple — confirmed, three independent layers

| Layer | Mechanism | Verified |
|---|---|---|
| (a) cfg defaults | All 7 new `RulesEngineConfig` fields = `None` (`rules_engine.py:122-128`); every gate function returns `None` immediately when its limit is `None` | ✅ |
| (b) yaml inert | `risk_rules.yaml` `capital:` Phase-3 block: all 7 keys `null` with comments; `_optional_number(None)` → `None`; explicit-YAML-null sections tolerated (`or {}`) | ✅ |
| (c) master flag | `_apply_portfolio_gate_cfg_from_yaml` (`main.py:260-320`): `NEXUS_RISK_PORTFOLIO_GATES` empty/`0`/`off`/`false`/`no` ⇒ `return` **before** `config._load_yaml("risk_rules.yaml")`. `.env.example:112` ships empty (disabled) | ✅ |

Default-config decisions remain byte-identical to Phase 2 golden fixtures (all 1062 prior tests still pass).

## 3. Gate order — matches plan

AST-verified call order in `check_all_rules` (`rules_engine.py:281-375`):

```
check_daily_loss → check_weekly_drawdown → [Phase-3 block:]
check_drawdown_from_peak → check_portfolio_open_risk → check_gross_leverage
→ check_net_currency_exposure → check_portfolio_correlation
→ check_same_direction_cluster → then max_positions, correlation,
spread, news, slippage, friday, min_rr
```

Phase-3 gates inserted after daily/weekly, before `max_positions` and every later gate. ✅ Docstring in module header documents the same order.

## 4. Peak restore — correct

- `_restore_equity_peak` reads `nexus:risk:equity_peak` (+ `_DAY` key) on lifespan startup; rejects non-finite/non-positive values.
- `_update_equity_peak`: re-baselines on new day (mirrors `_DAY_START_BALANCE`), raises on new highs, persists both keys (TTL 48h). No hardcoded peak constant anywhere.
- `reset_day` → `_rebaseline_portfolio_state`: peak := current equity, series := [today], `dd_from_peak_pct := 0` — prevents the pre-reset HWM from permanently blocking the fresh day.
- Redis failures are log-and-continue (never crash the sync).

## 5. Reset-day audit — correct

- `_reset_audit_insert`: `CREATE TABLE IF NOT EXISTS risk_reset_audit (id, caller, ts, pre_clear_json)` — all columns nullable. ✅
- `_write_reset_audit` called **before** `_rebaseline_portfolio_state` and before balance clearing in `reset_day`. ✅
- `asyncio.wait_for(..., timeout=5.0)` + `except Exception → log.warning("risk.reset_day.audit_write_failed")` — audit failure never blocks the reset. ✅
- DuckDB path from `DUCKDB_PATH` env; test uses `tmp_path` monkeypatched DB (no shared-DB writes in tests). ✅
- No `DROP` / `DELETE FROM` / `TRUNCATE` anywhere in the diff or new tests (rg-verified).

## 6. Other safety checks

- No secrets, keys, or credentials in the diff.
- Fail-closed gap-fills (`_run_portfolio_gates`): `dd_from_peak_unavailable`, `open_risk_unavailable`, `gross_leverage_unavailable`, `correlation_data_unavailable` — each only fires while the matching cfg field is set; default config untouched. ✅
- Open-risk size clamp (`main.py` sizing site) only active when `max_portfolio_open_risk_pct` is configured; clamps to **remaining** budget (`equity×pct − already_open_risk`), zero-remaining ⇒ size 0 ⇒ existing min-lot reject. ✅
- Open-risk snapshot with any uncounted position ⇒ `open_risk_usd=None` ⇒ fail-closed gap gate (when configured). ✅
- Correlation data path: real closes from Redis OHLCV cache, ≥11 observations, all-or-nothing snapshot; unavailable ⇒ fail-closed while threshold configured; disabled while threshold null (golden path never touches Redis). ✅
- Honest breakers: engine rows now computed (daily-loss, weekly-DD, peak-DD, open-risk, max-positions, tilt, friday, spread, news, daily-trade-limit, correlation) + G5 `set_breaker_state`/`state["breaker_state"]` channel for main-side signals (session_gate, anti_stacking, anti_revenge, trade_cooldown) — tracked state can only ADD a trip, never mask. ✅

## 7. Test suite result

```
.venv\Scripts\python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider
→ 1175 passed, 3 warnings in 241.64s (0:04:01)
```

- Phase-2 baseline: 1062. New: +84 (`test_portfolio_gates.py`) + 29 (`test_portfolio_gates_main.py`) = 1175 collected, **1175 passed, 0 failed, 0 skipped**. Matches the expected arithmetic exactly.

## 8. Notes / concerns for A0 (no rejection blockers)

- **C-1 (medium): master flag does not gate the engine's own YAML load.** `RulesEngine(config_loader)` → `_load_yaml_overrides` reads the `capital:` Phase-3 keys unconditionally at construction (`rules_engine.py:197-218`), independently of `NEXUS_RISK_PORTFOLIO_GATES`. The flag only gates main.py's redundant `_apply_portfolio_gate_cfg_from_yaml`. Today this is fully compensated by layer (b) (yaml values are null), so behavior is correct — but if an operator later sets `capital:` values **without** the flag, the gates activate via the engine path and the flag will not stop them. Either document the flag as "main.py-apply only" or add the same env check in `_load_yaml_overrides` in a Phase 3.1 cleanup.
- **C-2 (medium): `max_net_currency_exposure_pct` has no live data plane.** The engine gate exists and reads `state["net_currency_exposure_pct"]`, but main.py never computes/feeds that key and `_run_portfolio_gates` has no `net_currency_exposure_unavailable` gap-fill (unlike peak-DD/open-risk/gross-leverage/correlation). If an operator enables only this field, the gate silently skips on missing input (fail-open). Inert in the shipped config; recommend a data feed or gap-fill gate before the field is ever set. (`max_same_direction_cluster` is fine — the engine falls back to counting open positions.)
- **C-3 (housekeeping): untracked `fx-trading-system-main/`** (728 files, timestamp pre-dates Phase 3) sits in the repo root and is not part of this change set. Add to `.gitignore` or remove before committing Phase 3 so it cannot be swept into the commit.
- Cosmetic: LF→CRLF rewrite warnings on the 3 modified files (git line-ending normalization); no content impact.

---

**Return to A0:** Verdict **APPROVE WITH NOTES**. Totals: 1175 collected / 1175 passed / 0 failed (Phase-2 1062 + 84 + 29). Deletions: 34 lines, all sanctioned (hardcoded breaker rows, decorative `correlation_exposure: 0.0`, `any_triggered` bug, `_b`→`_row` rewrite, import/global extensions). Violations: none. Concerns: C-1 (flag doesn't gate engine YAML path — compensated by null yaml), C-2 (net-currency-exposure gate has no data feed/gap-fill — fail-open only if operator enables that one field), C-3 (pre-existing untracked `fx-trading-system-main/` before commit).
