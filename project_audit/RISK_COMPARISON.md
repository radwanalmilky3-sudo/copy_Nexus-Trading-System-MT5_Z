# Risk Layer Comparison — Reference `fx_system` vs Nexus Risk

Scope: reference = `fx-trading-system-main/src/fx_system/risk.py` + `portfolio_runner.py`
(+ `config.py` RiskConfig, `engine.py` drawdown kill path, tests skimmed); ours =
`services/nexus_risk/main.py` (+ `rules_engine.py`, `position_sizer.py`, `anti_tilt.py`)
with `services/nexus_executor/main.py` skimmed only for how risk gates orders.
Read-only audit; no code copied, no files modified.

## Risk metric coverage

The reference risk layer evaluates a signal against a compact but complete set of
pre-trade metrics: account-level drawdown versus `max_drawdown`, daily return versus
`daily_loss_limit`, open position count, a duplicate-symbol check, a reward/risk
(R:R) sanity cap, per-unit stop-distance validity (finite, positive, convertible to
account currency), available portfolio risk budget, gross notional versus a leverage
ceiling, per-currency net exposure converted through the rate graph, and a
returns-based correlation-cluster count. Every metric is computed at evaluation time
from live inputs (equity, positions, prices, historical returns) and produces a
typed `RiskDecision` with an explicit machine-readable reason string on rejection.
Nexus covers a different, more behavioral surface: Nexus-only daily loss percent
(closed + floating PnL of Nexus-tagged trades divided by day-start balance), low
win-rate circuit breaker on the last trades, an ergodic temporal-growth breaker,
anti-tilt streaks, per-direction loss blocks, anti-stacking cooldown, session gate,
Friday-close gate, news blackout, spread/slippage/RR checks, and a daily trade cap.
However, several of its nominally portfolio-level metrics are inert or never
computed: `weekly_dd_pct` is only ever written as 0.0 (the weekly-drawdown breaker
therefore never fires), `correlation_exposure` is hardcoded to 0.0 in the exposure
endpoints, and there is no drawdown-from-peak (equity high-water mark) metric at all
— only day-start-relative loss. Metrics the reference has and we lack entirely:
account-level max-drawdown kill switch, gross notional/leverage, currency net
exposure, reward/risk cap expressed as a maximum (we enforce a minimum R:R floor
instead), and data-driven correlation.

## Position sizing

The reference sizes from risk budget, not from a lot heuristic: target risk per
trade is the lesser of equity × `risk_per_trade` and (equity × `max_portfolio_risk`
minus the sum of open positions' initial account risk), divided by the
currency-converted stop distance per unit, floored to the configured unit step and
rejected below `min_units`; the resulting base notional is then re-clamped so the
trade fits inside remaining gross-leverage room, and re-checked against the minimum.
Sizing and limit checking are one atomic step — if the cap shrinks the size below
the minimum, the trade is rejected rather than shipped at an undersized or oversized
volume. Nexus instead runs a multiplicative heuristic stack in
`position_sizer.calculate_size`: balance-derived risk amount over pip-value risk per
lot, scaled by volatility regime, tilt factor, session factor, a profit-edge
multiplier from trade-memory stats, and a Kelly cap when win-rate/avg-win/avg-loss
are available; then `scale_by_conviction` can multiply the result by up to 1.15,
after which `main.py` re-clamps against both an absolute lot ceiling
(equity divisor and a 0.50 hard ceiling) and a risk-budget lot ceiling, and finally
applies an ergodic multiplier. The guard rails (re-clamp after conviction, hard
ceiling, min-lot rejection, post-hoc `check_max_risk_per_trade`) are thoughtful and
address real past incidents, but sizing never looks at what is already open: there
is no "available risk = portfolio budget − open risk" concept, so three concurrent
approvals each sized against full balance can collectively exceed any intended
per-trade budget. Sizing inputs are also partly stale or synthetic: `vol_regime`
and `session` are read from `_current_state` fields that the account-sync path never
populates (defaults "medium"/"london"), so two of the sizer's five factors are
effectively constants.

## Portfolio-level vs single-symbol limits

The reference is explicitly portfolio-first: it builds a provisional position map,
computes currency exposures across the whole book, sums open initial risk against a
portfolio risk budget, computes aggregate gross notional against an equity-scaled
leverage cap, and counts correlated same-direction positions from a returns matrix
with a configurable threshold and lookback — all before approving a single new
trade. Its `portfolio_runner.py` adds a separate capital-integrity layer for the
sleeve portfolio: target vectors are normalized so gross weight per sleeve cannot
exceed 1.0, duplicates/NaN/non-finite values are rejected, and capital limits are
enforced structurally, so an oversized target can never be booked to the ledger.
Nexus's limits are almost entirely single-symbol or count-based: max open
positions (count only), a hard-coded static correlation table of nine pairs (no
lookback, no returns data, no same-direction nuance beyond sign-insensitive
`abs(corr)`), duplicate-position rejection per symbol, per-(symbol,direction)
anti-stacking cooldown, and per-(symbol,direction) loss blocks. There is no
aggregate open-risk budget, no gross notional or leverage ceiling, no net currency
exposure view (all longs on USD-quoted symbols effectively stack USD exposure
unexamined), and no per-strategy or per-sleeve capital allocation. The only
portfolio-level signals exposed (`correlation_exposure`, `daily_pnl` in one
endpoint) are placeholders returning 0.0, which means downstream consumers such as
the GenAI risk manager see a portfolio picture that is systematically
under-stated.

## Breach / kill-switch flows

The reference fails closed in two places on hard breach: `evaluate` returns
`drawdown_kill_switch` when drawdown reaches `max_drawdown` and
`daily_loss_limit` when the day's return breaches the daily limit, and the engine
additionally flattens/holds when drawdown reaches the cap with positions open —
breach state is derived from computed equity, so it is self-healing (it re-arms the
moment equity recovers or the next session starts fresh, per its own bookkeeping).
Nexus's breach flow is distributed across Redis flags and several consumers: the
stream consumer checks `system:kill_switch` first and publishes a REJECT; the
trade-close consumer arms a 30-minute kill switch when anti-tilt reaches TILT; the
daily-loss, low-win-rate, ergodic, Friday, session, news and manual-pause rules
each independently reject inside `_evaluate_proposal`; and — critically — the
executor re-verifies kill switch, auto-trade, blackout and signed approval in
`evaluate_executor_guard` immediately before any opening broker call, with Redis
failures failing closed. That defense-in-depth is stronger than the reference's
single in-process check. The weakness is recovery and auditability rather than
detection: `reset-day` clears nearly everything at once (day-start baseline,
counters, tilt, kill switch, direction blocks, ergodic pause, recent results) in one
call protected only by the internal API secret, with no evidence recorded of who
reset what after which breach; and the tilt-triggered kill switch silently expires
via TTL. There is also no forced-unwind path — breaches block new entries but never
close existing exposure, whereas the reference's engine path explicitly flattens on
max drawdown.

## Approval workflows (our NEXUS_RISK_APPROVAL_SECRET vs reference gates)

The reference has no cryptographic approval artifact because it is a single
in-process system: its "approval" is the `RiskDecision` dataclass returned by
`evaluate` plus configuration-level gates (strategy `paper_enabled` flags,
`max_reward_risk` and factor validation raising at construction time, and the
project-level red lines in AGENTS.md that forbid trading approval outright). Trust
is established by code path, not by token. Nexus instead separates risk
authorization from execution with a signed, expiring approval: on every APPROVE,
nexus-risk canonicalizes a fixed v1 payload (proposal id, symbol, side, order type,
entry, price, SL, TP, size, slippage, signal timestamp, expiry — default TTL 30s)
and HMAC-SHA256-signs it with the dedicated `NEXUS_RISK_APPROVAL_SECRET`;
nexus-executor reconstructs the canonical payload from the event, verifies the
signature with `hmac.compare_digest`, rejects expired approvals and approvals
inside the expiry safety margin, and requires the executed terms to match the
signed terms byte-for-byte — so a tampered size/SL or a replayed stale approval
cannot reach the broker. Missing or empty secret fails closed (signing returns
empty → decision forced to REJECT). Residual gaps: the legacy
`NEXUS_INTERNAL_API_SECRET` fallback still exists for migration (warned, but live
trading should hard-refuse it), there is no nonce/replay store keyed by proposal id
(the expiry window and executor dedup are the only replay barriers), and the REST
evaluate path will sign whatever terms are supplied for price/size within the
validated envelope — approval minting authority rests on the shared internal secret
rather than on the isolated approval key.

## Paper vs live gating

The reference system makes paper vs live moot by construction: it is a research
system with no live broker path at all (fxPractice only, production domains
rejected in code), strategies carry `paper_enabled` defaults of false, and no
component is permitted to approve trading — the gate is architectural and is
enforced at the repository red-line level, not at runtime. Nexus makes the mode a
runtime property: `NEXUS_TRADING_MODE` (default `paper`) selects the broker in the
executor, paper mode is hard-blocked from real execution, and the mode is
process-level — the API can only move live → paper, never paper → live, and the
restart requirement is the gate. On top of that, risk-side gates
(`system:auto_trade`, news blackout, kill switch) apply identically in both modes,
which is good for behavioral parity: paper exercises the same decision machinery.
What is missing relative to the reference's philosophy is a hard research
prerequisite: nothing in nexus-risk prevents live mode while live-state fields are
degenerate (e.g., weekly drawdown never computed, vol/session factors constant), and
`NEXUS_AGGRESSIVE_TRADING=true` can silently loosen position caps, spread/slippage
tolerances, correlation limit and news blackout with only a config log line —
there is no equivalent of the reference's invariably-frozen approval flags, and no
preflight assertion that live mode requires the dedicated approval secret (that
lives in run.py/preflight per the docstring, but the fallback path still verifies).

## Tilt / status semantics

The reference has no tilt concept; its behavioral controls are structural
(conditional sizing, portfolio budget exhaustion, correlation clustering), and its
status vocabulary is decision-centric: approve/reject with a reason code such as
`max_portfolio_risk` or `correlation_cluster_limit`, which makes every rejection
directly attributable to a named limit. Nexus introduces a genuinely richer status
model: `NORMAL` / `WARNING` / `TILT` driven by consecutive losses (warn at 3, tilt
at 5, 30-minute cooldown, restore-on-restart via Redis with same-day semantics),
plus session wins/losses, size-escalation and trade-frequency detectors, and a
per-direction anti-revenge block that pauses only the offending symbol+side while
everything else stays tradeable — a finer granularity than the reference's
all-or-nothing drawdown halt. The status semantics, however, have three
inconsistencies worth fixing: TILT expiry is lazy (state only downgrades when
`get_tilt_status` is called or another trade closes), so a TILT can outlive its
cooldown in persisted snapshots; WARNING is reported but never reduces size beyond
the tilt factor table (which maps warning to 0.5 only if the string matches — the
sizer receives `tilt_status.value.lower()`, so it does apply, but WARNING does not
block or throttle trade frequency); and the breaker status endpoint
(`get_active_circuit_breakers`) reports a dozen breakers with hardcoded `triggered:
False` placeholders (anti_stacking, anti_revenge, session_gate, correlation_limit,
spread_limit, news_blackout, daily_trade_limit, trade_cooldown, min_conviction),
so the dashboard's "active breakers" view understates what is actually enforced
inside `_evaluate_proposal`. Reference rejections always map 1:1 to an enforced
rule; Nexus's status surface does not.

## Comparison table

| Capability | Reference (`fx_system`) | Nexus | Gap severity |
|---|---|---|---|
| Drawdown-based kill (equity high-water mark) | Max-drawdown kill switch + engine flatten | Absent; only day-start daily loss | High |
| Weekly drawdown metric | Not present (N/A) | Field exists but never computed → breaker inert | High |
| Aggregate open-risk budget (portfolio risk − open risk) | Core of `evaluate` sizing | Absent; each trade sized vs full balance | High |
| Currency net exposure cap | Per-currency exposure vs equity | Absent; `correlation_exposure` hardcoded 0.0 | High |
| Correlation clustering | Returns matrix, threshold + lookback | Static 9-pair table, sign-insensitive, no data | High |
| Gross notional / leverage cap | Equity-scaled cap with size re-clamp | Lot ceilings only (equity divisor + 0.50) | Med |
| Sizing approach | Risk-budget / stop distance, atomic with limits | Multi-factor heuristic + Kelly + conviction/ergodic multipliers with re-clamps | Med |
| Min R:R / max R:R policy | Max reward/risk cap (0.85) | Min R:R floor (1.3–1.5) only | Med |
| Daily loss metric | Daily return vs limit | Nexus-only closed+floating PnL / day-start (shared-account aware) | Low (ours stronger) |
| Kill-switch flow | In-process check + engine flatten | Redis flag checked in risk AND executor guard; TTL expiry, no unwind | Med |
| Breach recovery / reset audit | Session-driven, self-deriving | Single `reset-day` clears all, no audit trail | Med |
| Order approval artifact | In-process RiskDecision (no token needed) | HMAC-signed expiring payload, term-matching verified at executor | Low (ours stronger) |
| Approval secret hygiene | N/A | Dedicated key with legacy fallback still active | Med |
| Replay protection | N/A | Expiry TTL + executor dedup; no per-proposal nonce store | Low |
| Paper/live gating | Architecturally paper-only (research repo) | Process-level mode, paper hard-blocked from live, mode can only tighten | Low |
| Anti-tilt / streaks | None | 3-state tilt + cooldown + Redis persistence + direction blocks | Low (ours stronger) |
| Status/breaker reporting accuracy | Rejection reason == enforced rule | Several breaker rows hardcoded `triggered: False` | Med |
| Session/weekend/news gates | Calendar-driven close-before-weekend | Session gate, Friday close, news blackout, hot runtime overrides | Low (ours stronger) |
| Daily trade cap | None (position-count cap only) | Redis-persisted cap, survives restarts | Low (ours stronger) |
| Restart durability of risk state | N/A (stateless eval from ledger) | Redis-backed day baseline, counts, tilt, blocks (good) | Low |

## Actionable Recommendations

Ranked by impact (highest first); no code, implementation left to the owners.

1. **Add an equity high-water-mark drawdown kill switch and actually compute weekly
   drawdown.** Track peak equity (persisted across restarts like the day-start
   baseline), reject new entries when peak-relative drawdown crosses a configured
   cap, and populate `weekly_dd_pct` from a rolling seven-day Nexus PnL/equity
   series so the existing weekly breaker stops being decorative. This closes the
   largest structural safety gap versus the reference and costs one new Redis-backed
   series plus one check in `_evaluate_proposal`.

2. **Introduce a portfolio open-risk budget and enforce it before approving.**
   Sum the account-currency risk (lots × risk-per-lot at current stop distance) of
   all open Nexus positions, compare against an equity-scaled portfolio risk cap,
   and size each new trade against the *remaining* budget rather than full balance.
   This is the reference's central insight and prevents N simultaneous approvals
   from collectively exceeding the intended per-trade risk.

3. **Replace the static correlation table with data-driven correlation and add net
   currency exposure.** Compute pairwise correlation from a rolling returns window
   (as the reference does) or from the features service, treat same-direction
   clustering explicitly, and expose a real `correlation_exposure` / per-currency
   net exposure figure so stacked USD or gold-correlated bets are visible to both
   the rules engine and the GenAI risk manager.

4. **Make breaker status reporting truthful and add a reset audit log.** Populate
   every row of `get_active_circuit_breakers` from the actual enforcement state
   (session gate, blackout, stacking, direction block, daily trade limit, etc.)
   instead of hardcoded `False`, and record each `reset-day` / `pause` invocation
   (caller, timestamp, pre-reset breach values) so a breach-clear can be reviewed.
   Consider requiring a distinct confirmation for clearing an armed kill switch.

5. **Fail closed on live mode without the dedicated approval secret, and add
   per-proposal replay defense.** Remove or hard-disable the legacy
   `NEXUS_INTERNAL_API_SECRET` fallback when `NEXUS_TRADING_MODE` is live, and
   record consumed proposal IDs (short Redis SETNX with the approval TTL) in the
   executor so a single approval can never authorize two broker sends even if the
   stream redelivers within the expiry window.

6. **Feed real regime inputs into the sizer or drop the phantom factors.** Either
   populate `vol_regime` and `session` from the volatility/session services during
   account sync (so the 0.5–1.25 factor range is meaningful), or remove those
   factors from the formula to avoid implying dispersion that does not exist.
   Likewise, re-evaluate whether the conviction 1.15 up-scaler and the profit-edge
   up-scaler should ever *increase* size beyond the risk budget — prefer
   shrink-only multipliers outside of explicitly validated Kelly inputs.

7. **Add a breach unwind path for hard breaches.** Daily-loss / drawdown / kill
   switch currently only block new entries; for the hardest tiers, publish a close
   instruction for open Nexus positions (paper and live) rather than leaving
   exposure running through the freeze window — mirroring the reference engine's
   flatten-on-max-drawdown behavior.

8. **Close the tilt lifecycle edge cases.** Downgrade TILT to NORMAL based on
   persisted wall-clock cooldown (not lazy monotonic checks), align the WARNING tier
   with an actual throttle (e.g., size reduction or frequency limit) rather than
   status-only reporting, and surface cooldown expiry in the risk-state cache so the
   dashboard never shows a stale TILT or an unlapsed kill switch.
