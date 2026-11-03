# A4 (Risk) — Risk Architecture Insights from Reference Project

**Scope.** Read-only review of `fx-trading-system-main/src/fx_system/risk.py` and
`fx-trading-system-main/src/fx_system/portfolio_runner.py`. This report extracts design
principles and contracts only; no code is reproduced. Target audience: the Nexus swarm
(nexus-risk, nexus-executor, approval-signing chain).

## Risk metric design

The reference risk layer is built around a single decision contract: every evaluation
yields an immutable verdict carrying three facts — approval flag, sized quantity, and a
machine-readable rejection reason. Metrics are layered, not single-scored. The top layer
is account-level protection expressed as drawdown relative to equity high-water and a
daily loss limit expressed as a fraction of equity; these function as absolute kill
switches evaluated before any sizing work. Below that sits structural metrics: count of
open positions, capital at risk already committed by open positions (summed in account
currency using each position's own initial risk), gross notional leverage, and net
per-currency exposure. A VaR-style stochastic limit is deliberately absent; instead the
design uses deterministic proxies — stop-distance risk, correlation-cluster counting, and
currency decomposition — that can be computed pre-trade from live state without a
covariance estimation step. Each metric has an explicit unit (account currency, notional
fraction, or count), an explicit denominator (equity at decision time), and a threshold
owned by configuration rather than hard-coded in logic.

## Position sizing rules

Sizing is risk-first, not notional-first. The manager converts the intended stop distance
into an account-currency risk-per-unit via the rate graph, then solves for the quantity
whose money-at-risk equals the lesser of a per-trade risk budget and the remaining
portfolio risk budget (portfolio risk cap minus open risk). This guarantees that adding
a position can never inflate aggregate risk beyond policy even if per-trade fractions
would allow it. Quantities are then floored to a broker-legible unit step and rejected
entirely if below a minimum tradable size — sizing never silently rounds up. A second
clamping stage enforces gross leverage: if the position's base-currency notional exceeds
remaining gross room, the quantity is scaled down by the room ratio and re-floored, and
rejected if the result falls under minimum size. Critically, the stop distance used for
sizing prefers the execution venue's actual stop distance over the strategy's estimated
ATR-based distance, so live slippage or stop-adjustments feed directly into size, keeping
realized money-at-risk aligned with policy rather than with the research estimate.

## Portfolio construction runner

The runner separates portfolio *construction* from *accounting* through three explicit
audit trails: a master daily ledger, the sequence of portfolio transitions, and a record
of targets skipped for insufficient future calendar coverage. Construction operates on a
common session calendar with anchored rebalance cadence (default ~21 sessions), and
supports multiple overlapping holding-period sleeves, each constrained so gross sleeve
weight cannot exceed one, with horizon budgets partitioning capital among sleeves. All
daily inputs — prices, spreads, slippage, financing, cash interest, currency multipliers —
are normalized against the same calendar with hard failure on missing sessions, missing
symbols, duplicates, non-finite, or non-positive values where positivity is required;
the runner never forward-fills or invents data. Accounting charges transaction costs
once on the master account's net position change rather than per-sleeve, preventing
cost double-counting in overlapping designs, and books every session including flat
cash-only days so the NAV series has no gaps. Targets whose holding period would run
past available history are skipped with a reason rather than truncated, preserving the
integrity of realized holding-period economics.

## Kill-switch and breach handling

Breach handling is a strictly ordered gate cascade evaluated before any sizing or
provisional-position work. Drawdown breach (equity decline versus policy maximum) is
checked first and short-circuits everything; the daily loss limit is second; only then
do structural gates run (open-position count, duplicate-symbol, signal quality, stop
validity, conversion availability). Each rejection returns a distinct reason code, which
turns risk denial into observable telemetry rather than a silent drop. The design assumes
fail-closed defaults: a missing conversion rate, a non-finite stop distance, or a
non-positive stop all produce rejection, never estimation. There is no automatic
un-trip: once drawdown or daily loss breaches, the policy state itself must change before
new risk can be approved — recovery is an administrative act, not a market tick. This
mirrors the fail-closed principle Nexus enforces on trading-approval state fields:
agents prepare evidence, but only authorized state transitions reopen the gate.

## Exposure limits

Exposure enforcement happens at three scopes. Position scope: one open position per
symbol and a hard cap on open-position count prevents silent pyramiding. Portfolio
scope: capital-at-risk budget and gross notional leverage cap, both measured against
equity and both remaining-budget aware (they consume capacity as positions open). Systemic
scope: every provisional position is folded into a hypothetical portfolio snapshot and
its net per-currency exposure is computed by decomposing each position into base-currency
and quote-currency legs, converting to account currency through the live rate graph; any
single currency whose absolute net exposure exceeds a fraction of equity vetoes the
trade. Correlation clustering adds a fourth gate: positions in the same direction whose
pairwise return correlation over a lookback window exceeds a threshold are counted as a
cluster, and the cluster size is capped — this blocks the common FX failure mode of
nominally diversified pairs that are all the same USD bet. All limits are configuration-
owned and evaluated pre-trade; none rely on post-trade monitoring.

## Separation of risk policy from execution

The reference design draws a hard line: the risk manager is a pure policy evaluator —
it receives a signal, market entry, equity, open positions, timestamp, drawdown, and an
*optional* execution-supplied stop distance, and returns a decision; it places no orders,
holds no broker connection, and mutates no portfolio state. Execution feeds facts back
(stop distance actually achievable, fills at bid/ask or mid-with-spread, per-unit
slippage, financing, cash interest) which the runner applies in its ledger — the cost
model is an input contract, not embedded in risk logic. Portfolio construction similarly
consumes normalized targets and calendars but never makes approval decisions. This
layering means policy thresholds can be audited and versioned independently of execution
realities, execution adapters can be swapped (bid/ask mode versus half-spread mode)
without touching policy, and a synthetic runner can replay policy against full cost
models without any live connectivity. The Nexus analogue is the risk-signed approval
payload verified by the executor: policy authorizes, execution only executes what the
signed terms permit.

## Key Principles for Nexus

- **Fail-closed decision contract in nexus-risk.** Mirror the immutable verdict shape
  (approved flag + sized quantity + reason code) for every rules-engine evaluation;
  every denial must carry a distinct, machine-readable reason (as Nexus already does
  for `approval_payload_invalid_or_secret_missing`) so denials are telemetry, not
  silence.
- **Kill-switch ordering matters.** Evaluate tilt/kill state (`tilt_status` from
  `services/nexus_risk/anti_tilt.py`) and daily-loss style breaches *before* sizing or
  correlation logic, and require an explicit state transition to un-trip — never let a
  market tick auto-recover a tripped switch.
- **Risk-budget-first sizing.** Extend `position_sizer.py` so per-trade risk is capped
  by remaining portfolio risk budget (portfolio cap minus open risk), then clamp by
  gross leverage and floor to broker unit steps with a minimum-size rejection — and
  prefer the execution-confirmed stop distance over the strategy estimate when both
  exist.
- **Provisional-position evaluation.** Before approving, evaluate the *post-trade*
  hypothetical portfolio (currency decomposition, correlation cluster count, gross
  notional) rather than the pre-trade state — this is the only way exposure gates
  prevent the N+1th trade from breaching limits.
- **Pre-trade correlation-cluster limits.** CorrelationChecker should count
  same-direction positions whose pairwise return correlation exceeds a threshold and
  veto when the cluster exceeds a configured maximum — blocking "many pairs, one USD
  bet" concentration that per-symbol limits miss.
- **Paper-mode cost honesty in nexus-executor.** Keep the paper executor's fill model
  (bid/ask or spread + per-unit slippage + financing) as explicit, separately testable
  inputs to ledger accounting — costs charged once on net position change, never
  double-counted, and never silently zero — so paper results remain an honest rehearsal
  of live economics.
- **Policy/execution separation with signed handoff.** Preserve the pattern where
  nexus-risk is a pure evaluator producing HMAC-signed, TTL-bound approval terms and
  nexus-executor verifies `NEXUS_RISK_APPROVAL_SECRET` before any order path (including
  paper); execution adapters stay swappable (MT5/IBKR/CCXT/paper) without touching risk
  policy, and the dedicated secret replaces the legacy fallback as the migration path.
- **Normalization-as-gate for portfolio inputs.** Any Nexus portfolio/ledger replay
  path should hard-fail on missing sessions, missing symbols, duplicates, or non-finite
  inputs against a shared calendar (as `portfolio_runner.py` does) — never forward-fill
  or impute market data inside the accounting path, and record skipped targets with
  reasons instead of truncating holding periods.
