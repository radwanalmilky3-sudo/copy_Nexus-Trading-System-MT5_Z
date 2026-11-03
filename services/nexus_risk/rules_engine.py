"""
Nexus Risk — Rules Engine with hardcoded circuit breakers.

Every rule has an absolute minimum that **cannot** be overridden by YAML config.
The YAML file ``risk_rules.yaml`` may tighten limits but never loosen them
below the hardcoded floor.

Gate order in ``check_all_rules`` (Phase 3 / G4 portfolio gates inserted
after the daily/weekly drawdown gates, before every later gate)::

    max_daily_loss → max_weekly_drawdown → max_drawdown_from_peak
    → portfolio_open_risk → max_gross_leverage → max_net_currency_exposure
    → portfolio_correlation → max_same_direction_cluster
    → max_positions → correlation_limit (per-proposal) → spread_limit
    → news_blackout → slippage_limit → friday_close → min_rr_ratio

Every Phase-3 gate has an optional ``RulesEngineConfig`` field that defaults
to ``None``; a ``None`` field (or missing state input) skips that gate
entirely, so default-config decisions stay identical to the golden fixtures.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from shared.config_loader import ConfigLoader
from shared.constants import DEFAULT_RISK_PARAMS
from shared.models import Position, TradeProposal

log = structlog.get_logger(__name__)

# ── Hardcoded Absolute Minimums (INVIOLABLE) ─────────────────────────────────

_HARDCODED_MIN: dict[str, float | int] = {
    "max_risk_per_trade_pct":  2.0,
    "max_daily_loss_pct":      5.0,
    "max_weekly_drawdown_pct": 8.0,
    "max_open_positions":      3,
    "max_correlation":         0.7,
    "max_spread_multiplier":   2.0,
    "news_blackout_minutes":   5,
    "max_slippage_pips":       1.0,
    "friday_close_utc_hour":   20,
    "min_rr_ratio":            1.3,  # absolute floor — never allow below 1.3:1
}

_AGGRESSIVE_TRADING = os.getenv("NEXUS_AGGRESSIVE_TRADING", "false").lower() == "true"

# Static pairwise correlation estimates — shared by the per-proposal
# check_correlation gate and the honest correlation_limit breaker row.
_STATIC_CORR_PAIRS: dict[str, float] = {
    "EURUSD:GBPUSD": 0.85, "EURUSD:USDCHF": -0.90,
    "GBPUSD:EURGBP": -0.70, "AUDUSD:NZDUSD": 0.90,
    "USDJPY:EURJPY": 0.80, "GBPUSD:GBPJPY": 0.75,
    "EURUSD:EURJPY": 0.60, "AUDUSD:AUDJPY": 0.65,
    "USDCAD:USDCHF": 0.55,
}


def _optional_number(value: Any, caster: type = float) -> float | int | None:
    """Read an optional YAML portfolio-gate field.

    Missing key or explicit YAML null ⇒ ``None`` (gate skipped entirely).
    Unparseable values also degrade to ``None`` rather than crashing boot.
    """
    if value is None:
        return None
    try:
        return caster(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CorrelationSnapshot:
    """Correlation input for ``check_portfolio_correlation`` (fed by main.py).

    Provide either pairwise ``pairs`` (``"EURUSD:GBPUSD" -> 0.85``) or a square
    ``matrix`` aligned with ``symbols``. ``lookback_bars`` records the history
    length behind the numbers so an under-sampled matrix can be rejected when
    ``RulesEngineConfig.correlation_lookback_bars`` is configured.
    """

    symbols: list[str] = field(default_factory=list)
    matrix: list[list[float]] | None = None
    pairs: dict[str, float] = field(default_factory=dict)
    lookback_bars: int = 0


def _position_side(pos: Any) -> str:
    """Normalise a position's side/direction to an upper-case string."""
    raw = pos.get("side", "") if isinstance(pos, dict) else getattr(pos, "side", "")
    return str(getattr(raw, "value", raw)).upper()


@dataclass
class RuleViolation:
    rule: str
    message: str
    severity: str = "CRITICAL"
    current_value: float | str = 0.0
    limit_value: float | str = 0.0


@dataclass
class RulesEngineConfig:
    max_risk_per_trade_pct: float = 2.0
    max_daily_loss_pct: float = 5.0
    max_weekly_drawdown_pct: float = 8.0
    max_open_positions: int = 3
    max_correlation: float = 0.7
    max_spread_multiplier: float = 2.0
    news_blackout_minutes: int = 5
    max_slippage_pips: float = 1.0
    friday_close_utc_hour: int = 20
    min_rr_ratio: float = 1.5  # minimum risk-reward ratio for any trade
    # ── Phase 3 portfolio gates (G4) — None ⇒ the check is skipped entirely ──
    max_drawdown_from_peak_pct: float | None = None
    max_portfolio_open_risk_pct: float | None = None
    max_gross_leverage: float | None = None
    max_net_currency_exposure_pct: float | None = None
    correlation_threshold: float | None = None
    correlation_lookback_bars: int | None = None
    max_same_direction_cluster: int | None = None


class RulesEngine:
    """Hardcoded circuit breakers for trade risk evaluation."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self._cfg = RulesEngineConfig()
        self._upcoming_news: list[dict[str, Any]] = []
        # G5 honest-breaker contract: rows whose live signal lives in main.py
        # report ACTUAL state recorded here via ``set_breaker_state`` (or via
        # ``state["breaker_state"]`` passed to ``get_active_circuit_breakers``)
        # instead of a hardcoded ``triggered: False``.
        self._breaker_state: dict[str, dict[str, Any]] = {}
        if config_loader:
            self._load_yaml_overrides(config_loader)

    def _load_yaml_overrides(self, loader: ConfigLoader) -> None:
        """Apply YAML config, but never loosen past hardcoded minimums."""
        try:
            raw = loader._load_yaml("risk_rules.yaml")
        except FileNotFoundError:
            log.warning("rules_engine.no_config", msg="risk_rules.yaml not found, using defaults")
            return

        # `or {}` also tolerates an explicit YAML null section.
        capital = raw.get("capital") or {}
        exposure = raw.get("exposure") or {}
        execution = raw.get("execution") or {}
        calendar = raw.get("calendar") or {}

        self._cfg.max_risk_per_trade_pct = max(
            capital.get("max_risk_per_trade_pct", self._cfg.max_risk_per_trade_pct),
            _HARDCODED_MIN["max_risk_per_trade_pct"],
        )
        self._cfg.max_daily_loss_pct = max(
            capital.get("max_daily_loss_pct", self._cfg.max_daily_loss_pct),
            _HARDCODED_MIN["max_daily_loss_pct"],
        )
        self._cfg.max_weekly_drawdown_pct = max(
            capital.get("max_weekly_drawdown_pct", self._cfg.max_weekly_drawdown_pct),
            _HARDCODED_MIN["max_weekly_drawdown_pct"],
        )
        self._cfg.max_open_positions = max(
            int(exposure.get("max_simultaneous_positions", self._cfg.max_open_positions)),
            int(_HARDCODED_MIN["max_open_positions"]),
        )
        self._cfg.max_correlation = max(
            exposure.get("max_correlation_between_positions", self._cfg.max_correlation),
            _HARDCODED_MIN["max_correlation"],
        )
        self._cfg.max_spread_multiplier = max(
            execution.get("max_spread_multiplier", self._cfg.max_spread_multiplier),
            _HARDCODED_MIN["max_spread_multiplier"],
        )
        self._cfg.max_slippage_pips = max(
            execution.get("max_slippage_pips", self._cfg.max_slippage_pips),
            _HARDCODED_MIN["max_slippage_pips"],
        )
        self._cfg.news_blackout_minutes = max(
            int(calendar.get("news_blackout_minutes", self._cfg.news_blackout_minutes)),
            int(_HARDCODED_MIN["news_blackout_minutes"]),
        )

        friday_raw = calendar.get("friday_close_utc", "20:00")
        hour = int(str(friday_raw).split(":")[0])
        self._cfg.friday_close_utc_hour = max(hour, int(_HARDCODED_MIN["friday_close_utc_hour"]))

        # Phase 3 (G4) portfolio gates — optional; null/absent ⇒ check skipped.
        # Master switch (mirrors main.py): NEXUS_RISK_PORTFOLIO_GATES empty ⇒
        # these yaml overrides are ignored entirely, so a populated `capital:`
        # section alone can never activate portfolio gates.
        _portfolio_gates_flag = os.getenv(
            "NEXUS_RISK_PORTFOLIO_GATES", ""
        ).strip().lower()
        if _portfolio_gates_flag not in ("", "0", "off", "false", "no"):
            self._cfg.max_drawdown_from_peak_pct = _optional_number(
                capital.get("max_drawdown_from_peak_pct"), float,
            )
            self._cfg.max_portfolio_open_risk_pct = _optional_number(
                capital.get("max_portfolio_open_risk_pct"), float,
            )
            self._cfg.max_gross_leverage = _optional_number(
                capital.get("max_gross_leverage"), float,
            )
            self._cfg.max_net_currency_exposure_pct = _optional_number(
                capital.get("max_net_currency_exposure_pct"), float,
            )
            self._cfg.correlation_threshold = _optional_number(
                capital.get("correlation_threshold"), float,
            )
            self._cfg.correlation_lookback_bars = _optional_number(
                capital.get("correlation_lookback_bars"), int,
            )
            self._cfg.max_same_direction_cluster = _optional_number(
                capital.get("max_same_direction_cluster"), int,
            )

        # Optional high-frequency profile for live experimentation.
        if _AGGRESSIVE_TRADING:
            self._cfg.max_open_positions = max(self._cfg.max_open_positions, 8)
            self._cfg.max_spread_multiplier = max(self._cfg.max_spread_multiplier, 4.0)
            self._cfg.max_slippage_pips = max(self._cfg.max_slippage_pips, 4.0)
            self._cfg.max_correlation = max(self._cfg.max_correlation, 0.95)
            self._cfg.news_blackout_minutes = 0

        log.info("rules_engine.config_loaded", config=self._cfg)

    def set_upcoming_news(self, events: list[dict[str, Any]]) -> None:
        self._upcoming_news = events

    def apply_runtime_overrides(self, settings: dict[str, Any]) -> None:
        """Apply front-configurable runtime settings on top of YAML.

        Hardcoded minimums still act as a FLOOR on each limit so the user can
        loosen within reason but never below the inviolable safety floor.
        """
        if not isinstance(settings, dict):
            return
        if "max_daily_loss_pct" in settings:
            self._cfg.max_daily_loss_pct = max(
                float(settings["max_daily_loss_pct"]),
                _HARDCODED_MIN["max_daily_loss_pct"],
            )
        if "max_weekly_dd_pct" in settings:
            self._cfg.max_weekly_drawdown_pct = max(
                float(settings["max_weekly_dd_pct"]),
                _HARDCODED_MIN["max_weekly_drawdown_pct"],
            )
        if "max_open_positions" in settings:
            self._cfg.max_open_positions = max(
                int(settings["max_open_positions"]),
                int(_HARDCODED_MIN["max_open_positions"]),
            )
        if "min_rr_ratio" in settings:
            self._cfg.min_rr_ratio = max(
                float(settings["min_rr_ratio"]),
                float(_HARDCODED_MIN["min_rr_ratio"]),
            )

    # ── Master Check ──────────────────────────────────────────────────────

    def check_all_rules(
        self,
        trade_proposal: TradeProposal,
        current_state: dict[str, Any],
    ) -> tuple[bool, list[RuleViolation]]:
        violations: list[RuleViolation] = []

        balance = current_state.get("balance", 10_000.0)
        daily_loss = current_state.get("daily_loss_pct", 0.0)
        weekly_dd = current_state.get("weekly_dd_pct", 0.0)
        open_count = current_state.get("open_positions_count", 0)
        open_positions = current_state.get("open_positions", [])
        current_spread = current_state.get("current_spread", 0.0)
        avg_spread = current_state.get("avg_spread", 1.0)
        expected_price = current_state.get("expected_price", trade_proposal.entry)
        actual_price = current_state.get("actual_price", trade_proposal.entry)

        v = self.check_daily_loss(daily_loss)
        if v:
            violations.append(v)

        v = self.check_weekly_drawdown(weekly_dd)
        if v:
            violations.append(v)

        # ── Phase 3 portfolio gates (G4) — order: peak-DD → open-risk →
        # gross-leverage → net-currency-exposure → portfolio-correlation →
        # same-direction-cluster. Each skips itself when its cfg field is
        # None or its state input is missing, so default-config behaviour
        # (golden decisions) is unchanged.
        equity_value = float(current_state.get("equity") or balance)
        peak_raw = current_state.get("equity_peak")
        v = self.check_drawdown_from_peak(
            float(peak_raw) if isinstance(peak_raw, (int, float)) else None,
            equity_value,
            day=str(current_state.get("equity_peak_day", "")),
        )
        if v:
            violations.append(v)

        open_risk_raw = current_state.get("open_risk_amount")
        proposed_risk_raw = current_state.get("proposed_risk_amount")
        v = self.check_portfolio_open_risk(
            float(open_risk_raw) if isinstance(open_risk_raw, (int, float)) else 0.0,
            equity_value,
            proposed_risk_amount=(
                float(proposed_risk_raw) if isinstance(proposed_risk_raw, (int, float)) else 0.0
            ),
        )
        if v:
            violations.append(v)

        gross_raw = current_state.get("gross_leverage")
        v = self.check_gross_leverage(
            float(gross_raw) if isinstance(gross_raw, (int, float)) else None,
        )
        if v:
            violations.append(v)

        net_exp_raw = current_state.get("net_currency_exposure_pct")
        v = self.check_net_currency_exposure(
            float(net_exp_raw) if isinstance(net_exp_raw, (int, float)) else None,
        )
        if v:
            violations.append(v)

        v = self.check_portfolio_correlation(current_state.get("correlation_snapshot"))
        if v:
            violations.append(v)

        if self._cfg.max_same_direction_cluster is not None:
            proposal_dir = str(
                getattr(trade_proposal.direction, "value", trade_proposal.direction)
            ).upper()
            same_dir_raw = current_state.get("same_direction_count")
            if isinstance(same_dir_raw, (int, float)):
                same_dir_count = int(same_dir_raw)
            else:
                same_dir_count = 1 + sum(
                    1 for pos in open_positions if _position_side(pos) == proposal_dir
                )
            v = self.check_same_direction_cluster(
                same_dir_count, direction=proposal_dir,
            )
            if v:
                violations.append(v)

        v = self.check_max_positions(open_count)
        if v:
            violations.append(v)

        v = self.check_correlation(trade_proposal.symbol, open_positions)
        if v:
            violations.append(v)

        v = self.check_spread(current_spread, avg_spread)
        if v:
            violations.append(v)

        v = self.check_news_blackout()
        if v:
            violations.append(v)

        v = self.check_slippage(expected_price, actual_price, symbol=trade_proposal.symbol)
        if v:
            violations.append(v)

        v = self.check_friday_close()
        if v:
            violations.append(v)

        v = self.check_min_rr(trade_proposal.entry, trade_proposal.sl, trade_proposal.tp1)
        if v:
            violations.append(v)

        passed = len(violations) == 0
        log.info(
            "rules_engine.check_complete",
            proposal_id=trade_proposal.id,
            passed=passed,
            violations=len(violations),
        )
        return passed, violations

    # ── Individual Rule Checks ────────────────────────────────────────────

    def check_max_risk_per_trade(
        self, size: float, entry: float, sl: float, balance: float, symbol: str = "",
    ) -> RuleViolation | None:
        if (
            not all(math.isfinite(value) for value in (size, entry, sl, balance))
            or size < 0
            or balance <= 0
            or entry == sl
        ):
            return RuleViolation(
                rule="max_risk_per_trade",
                message="Invalid balance or entry == SL",
                current_value=0,
                limit_value=self._cfg.max_risk_per_trade_pct,
            )
        risk_pct = self.risk_pct_for_size(size, entry, sl, balance, symbol)
        if risk_pct > self._cfg.max_risk_per_trade_pct:
            return RuleViolation(
                rule="max_risk_per_trade",
                message=f"Risk {risk_pct:.2f}% exceeds max {self._cfg.max_risk_per_trade_pct}%",
                current_value=round(risk_pct, 2),
                limit_value=self._cfg.max_risk_per_trade_pct,
            )
        return None

    @staticmethod
    def risk_pct_for_size(
        size: float, entry: float, sl: float, balance: float, symbol: str = ""
    ) -> float:
        if balance <= 0 or entry == sl or size <= 0:
            return 0.0
        distance = abs(entry - sl)
        risk_per_lot = distance
        if symbol:
            from shared.asset_specs import get_pip_size, get_pip_value_per_lot

            pip_size = get_pip_size(symbol)
            pip_value_per_lot = get_pip_value_per_lot(symbol)
            if pip_size <= 0 or pip_value_per_lot <= 0:
                return math.inf
            risk_per_lot = distance / pip_size * pip_value_per_lot
        return (size * risk_per_lot / balance) * 100

    def check_daily_loss(self, current_daily_loss: float) -> RuleViolation | None:
        if abs(current_daily_loss) >= self._cfg.max_daily_loss_pct:
            return RuleViolation(
                rule="max_daily_loss",
                message=f"Daily loss {abs(current_daily_loss):.2f}% hit limit {self._cfg.max_daily_loss_pct}%",
                severity="CRITICAL",
                current_value=round(abs(current_daily_loss), 2),
                limit_value=self._cfg.max_daily_loss_pct,
            )
        return None

    def check_weekly_drawdown(self, current_weekly_dd: float) -> RuleViolation | None:
        if abs(current_weekly_dd) >= self._cfg.max_weekly_drawdown_pct:
            return RuleViolation(
                rule="max_weekly_drawdown",
                message=f"Weekly drawdown {abs(current_weekly_dd):.2f}% hit limit {self._cfg.max_weekly_drawdown_pct}%",
                severity="CRITICAL",
                current_value=round(abs(current_weekly_dd), 2),
                limit_value=self._cfg.max_weekly_drawdown_pct,
            )
        return None

    # ── Phase 3 portfolio gates (G4) — None cfg ⇒ check skipped entirely ─────

    def check_drawdown_from_peak(
        self,
        peak_equity: float | None,
        current_equity: float,
        day: str = "",
    ) -> RuleViolation | None:
        """Drawdown from the tracked equity peak (``nexus:risk:equity_peak``).

        Mirrors the daily/weekly gate semantics: block when
        ``dd_from_peak_pct >= max_drawdown_from_peak_pct``. Skips itself when
        the gate is unconfigured (cfg None) or the peak is unknown
        (None / non-positive). ``day`` is context only (peak-day label).
        """
        limit = self._cfg.max_drawdown_from_peak_pct
        if limit is None or peak_equity is None:
            return None
        if (
            not math.isfinite(peak_equity)
            or not math.isfinite(current_equity)
            or peak_equity <= 0
        ):
            return None
        dd_from_peak_pct = (peak_equity - current_equity) / peak_equity * 100.0
        if dd_from_peak_pct >= limit:
            ctx = f" (peak day {day})" if day else ""
            return RuleViolation(
                rule="max_drawdown_from_peak",
                message=(
                    f"Drawdown from peak {dd_from_peak_pct:.2f}% hit limit "
                    f"{limit}%{ctx}"
                ),
                severity="CRITICAL",
                current_value=round(dd_from_peak_pct, 2),
                limit_value=limit,
            )
        return None

    def remaining_open_risk_budget(self, equity: float, already_open_risk: float) -> float:
        """Risk currency still available for a NEW position (main.py clamp).

        ``remaining = equity × max_portfolio_open_risk_pct/100 − already_open_risk``

        * gate disabled (cfg None) ⇒ ``math.inf`` (no portfolio clamp),
        * non-positive/non-finite equity ⇒ ``0.0`` (fail closed),
        * result ≤ 0 means the budget is fully consumed — no new risk allowed.
        """
        limit = self._cfg.max_portfolio_open_risk_pct
        if limit is None:
            return math.inf
        if not math.isfinite(equity) or equity <= 0:
            return 0.0
        budget = equity * limit / 100.0
        return budget - max(already_open_risk, 0.0)

    def check_portfolio_open_risk(
        self,
        open_risk_amount: float,
        equity: float,
        proposed_risk_amount: float = 0.0,
    ) -> RuleViolation | None:
        """Σ(open lots × risk per lot) against the portfolio open-risk budget.

        Budget = ``equity × max_portfolio_open_risk_pct``. A new position is
        measured against the REMAINING budget (budget − already-open risk),
        not the total: block when the budget is fully consumed
        (remaining ≤ 0) or the proposed risk exceeds what remains. Use
        ``remaining_open_risk_budget`` to clamp the size before calling this.
        ``None`` cfg ⇒ skipped.
        """
        limit = self._cfg.max_portfolio_open_risk_pct
        if limit is None:
            return None
        if not all(
            math.isfinite(x) for x in (open_risk_amount, equity, proposed_risk_amount)
        ):
            return RuleViolation(
                rule="portfolio_open_risk",
                message="Invalid portfolio open-risk inputs",
                severity="CRITICAL",
                current_value=0.0,
                limit_value=limit,
            )
        budget = equity * limit / 100.0
        remaining = budget - open_risk_amount
        open_risk_pct = (open_risk_amount / equity * 100.0) if equity > 0 else math.inf
        if remaining <= 0.0 or proposed_risk_amount > remaining:
            return RuleViolation(
                rule="portfolio_open_risk",
                message=(
                    f"Open risk {open_risk_pct:.2f}% of equity "
                    f"({open_risk_amount:.2f} of {budget:.2f} budget); "
                    f"remaining {max(remaining, 0.0):.2f} does not cover "
                    f"proposed risk {proposed_risk_amount:.2f}"
                ),
                severity="CRITICAL",
                current_value=round(
                    open_risk_pct if math.isfinite(open_risk_pct) else limit, 2
                ),
                limit_value=limit,
            )
        return None

    def check_gross_leverage(self, gross_leverage: float | None) -> RuleViolation | None:
        """Σ|position notional| / equity. None cfg or missing value ⇒ skipped."""
        limit = self._cfg.max_gross_leverage
        if limit is None or gross_leverage is None:
            return None
        if not math.isfinite(gross_leverage):
            return RuleViolation(
                rule="max_gross_leverage",
                message="Non-finite gross leverage",
                severity="CRITICAL",
                current_value="invalid",
                limit_value=limit,
            )
        if gross_leverage >= limit:
            return RuleViolation(
                rule="max_gross_leverage",
                message=f"Gross leverage {gross_leverage:.2f} hit limit {limit}",
                severity="CRITICAL",
                current_value=round(gross_leverage, 2),
                limit_value=limit,
            )
        return None

    def check_net_currency_exposure(
        self, net_exposure_pct: float | None,
    ) -> RuleViolation | None:
        """|net base-currency exposure| % of equity. None cfg/value ⇒ skipped."""
        limit = self._cfg.max_net_currency_exposure_pct
        if limit is None or net_exposure_pct is None:
            return None
        if abs(net_exposure_pct) >= limit:
            return RuleViolation(
                rule="max_net_currency_exposure",
                message=(
                    f"Net currency exposure {abs(net_exposure_pct):.2f}% "
                    f"hit limit {limit}%"
                ),
                severity="CRITICAL",
                current_value=round(abs(net_exposure_pct), 2),
                limit_value=limit,
            )
        return None

    def check_portfolio_correlation(
        self,
        snapshot: CorrelationSnapshot | dict[str, Any] | None,
    ) -> RuleViolation | None:
        """Max |pairwise correlation| across the portfolio vs ``correlation_threshold``.

        ``snapshot`` is a ``CorrelationSnapshot`` (or the same shape as a plain
        dict) fed by main.py: either ``pairs`` (``"EURUSD:GBPUSD": 0.85``) or a
        square ``matrix`` aligned with ``symbols``. When
        ``correlation_lookback_bars`` is set and the snapshot declares a
        smaller history, the under-sampled matrix is rejected
        (rule ``correlation_lookback``). None cfg or missing snapshot ⇒ skipped.
        """
        threshold = self._cfg.correlation_threshold
        if threshold is None or snapshot is None:
            return None
        if isinstance(snapshot, dict):
            try:
                snapshot = CorrelationSnapshot(
                    symbols=[str(s) for s in (snapshot.get("symbols") or [])],
                    matrix=snapshot.get("matrix"),
                    pairs={str(k): v for k, v in (snapshot.get("pairs") or {}).items()},
                    lookback_bars=int(snapshot.get("lookback_bars") or 0),
                )
            except (TypeError, ValueError):
                return RuleViolation(
                    rule="portfolio_correlation",
                    message="Invalid correlation snapshot structure",
                    severity="CRITICAL",
                    current_value="invalid",
                    limit_value=threshold,
                )
        required_bars = self._cfg.correlation_lookback_bars
        if (
            required_bars is not None
            and 0 < snapshot.lookback_bars < required_bars
        ):
            return RuleViolation(
                rule="correlation_lookback",
                message=(
                    f"Correlation snapshot uses {snapshot.lookback_bars} bars, "
                    f"required {required_bars}"
                ),
                severity="CRITICAL",
                current_value=snapshot.lookback_bars,
                limit_value=required_bars,
            )
        worst = 0.0
        worst_pair = ""
        for key, value in snapshot.pairs.items():
            try:
                corr = abs(float(value))
            except (TypeError, ValueError):
                continue
            if corr > worst:
                worst, worst_pair = corr, str(key)
        if snapshot.matrix:
            syms = [str(s) for s in snapshot.symbols]
            for i, row in enumerate(snapshot.matrix):
                for j, cell in enumerate(row):
                    if i >= j:
                        continue
                    try:
                        corr = abs(float(cell))
                    except (TypeError, ValueError):
                        continue
                    if corr > worst:
                        a = syms[i] if i < len(syms) else str(i)
                        b = syms[j] if j < len(syms) else str(j)
                        worst, worst_pair = corr, f"{a}:{b}"
        if worst >= threshold:
            return RuleViolation(
                rule="portfolio_correlation",
                message=(
                    f"Portfolio correlation {worst:.2f} ({worst_pair}) "
                    f"hit limit {threshold}"
                ),
                severity="CRITICAL",
                current_value=round(worst, 2),
                limit_value=threshold,
            )
        return None

    def check_same_direction_cluster(
        self, same_direction_count: int | None, direction: str = "",
    ) -> RuleViolation | None:
        """Block clusters of same-direction exposure (count includes the proposal).

        None cfg or missing count ⇒ skipped. Mirrors ``max_positions``:
        block when ``count >= max_same_direction_cluster``.
        """
        limit = self._cfg.max_same_direction_cluster
        if limit is None or same_direction_count is None:
            return None
        if same_direction_count >= limit:
            dir_txt = f" {direction}" if direction else ""
            return RuleViolation(
                rule="max_same_direction_cluster",
                message=(
                    f"{same_direction_count}{dir_txt} same-direction positions, "
                    f"max cluster {limit}"
                ),
                severity="CRITICAL",
                current_value=same_direction_count,
                limit_value=limit,
            )
        return None

    def check_max_positions(self, open_count: int) -> RuleViolation | None:
        if open_count >= self._cfg.max_open_positions:
            return RuleViolation(
                rule="max_positions",
                message=f"{open_count} open positions, max is {self._cfg.max_open_positions}",
                current_value=open_count,
                limit_value=self._cfg.max_open_positions,
            )
        return None

    def check_correlation(
        self, symbol: str, open_positions: list[dict[str, Any] | Position],
    ) -> RuleViolation | None:
        if not open_positions:
            return None

        corr_pairs = _STATIC_CORR_PAIRS
        sym = symbol.upper().replace("/", "")
        for pos in open_positions:
            pos_sym = (pos.get("symbol", "") if isinstance(pos, dict) else pos.symbol)
            pos_sym = pos_sym.upper().replace("/", "")
            if pos_sym == sym:
                return RuleViolation(
                    rule="duplicate_position",
                    message=f"Already have an open position on {sym}",
                    current_value=sym,
                    limit_value="unique",
                )

            pair_key_a = f"{sym}:{pos_sym}"
            pair_key_b = f"{pos_sym}:{sym}"
            corr = corr_pairs.get(pair_key_a) or corr_pairs.get(pair_key_b)
            if corr is not None and abs(corr) > self._cfg.max_correlation:
                return RuleViolation(
                    rule="correlation_limit",
                    message=f"Correlation {sym}/{pos_sym} = {abs(corr):.2f} > {self._cfg.max_correlation}",
                    current_value=round(abs(corr), 2),
                    limit_value=self._cfg.max_correlation,
                )
        return None

    def check_spread(self, current_spread: float, avg_spread: float) -> RuleViolation | None:
        if avg_spread <= 0:
            return None
        ratio = current_spread / avg_spread
        if ratio > self._cfg.max_spread_multiplier:
            return RuleViolation(
                rule="spread_limit",
                message=f"Spread {ratio:.1f}x average exceeds {self._cfg.max_spread_multiplier}x limit",
                current_value=round(ratio, 2),
                limit_value=self._cfg.max_spread_multiplier,
            )
        return None

    def check_news_blackout(self) -> RuleViolation | None:
        if self._cfg.news_blackout_minutes <= 0:
            return None
        now = datetime.now(timezone.utc)
        for event in self._upcoming_news:
            event_time = event.get("timestamp")
            if event_time is None:
                continue
            if isinstance(event_time, str):
                try:
                    event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
            if not hasattr(event_time, "tzinfo") or event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)

            minutes_until = (event_time - now).total_seconds() / 60
            impact = event.get("impact", "low")
            if impact in ("high", "HIGH") and 0 <= minutes_until <= self._cfg.news_blackout_minutes:
                return RuleViolation(
                    rule="news_blackout",
                    message=f"High-impact news in {minutes_until:.0f} min — blackout active",
                    severity="CRITICAL",
                    current_value=f"{minutes_until:.0f}min",
                    limit_value=f"{self._cfg.news_blackout_minutes}min",
                )
        return None

    def check_slippage(
        self, expected: float, actual: float, symbol: str = "",
    ) -> RuleViolation | None:
        # Infer pip divisor from price magnitude or symbol
        if symbol:
            from shared.asset_specs import get_pip_size
            pip_sz = get_pip_size(symbol)
            pip_divisor = 1.0 / pip_sz if pip_sz > 0 else 10_000.0
        else:
            # Infer from price: gold/indices > 500, JPY > 10
            pip_divisor = 100.0 if expected > 10 else 10_000.0
        slip_pips = abs(expected - actual) * pip_divisor
        if slip_pips > self._cfg.max_slippage_pips:
            return RuleViolation(
                rule="slippage_limit",
                message=f"Slippage {slip_pips:.1f} pips exceeds {self._cfg.max_slippage_pips} pip limit",
                current_value=round(slip_pips, 1),
                limit_value=self._cfg.max_slippage_pips,
            )
        return None

    def check_friday_close(self) -> RuleViolation | None:
        if _AGGRESSIVE_TRADING:
            return None
        now = datetime.now(timezone.utc)
        if now.weekday() == 4 and now.hour >= self._cfg.friday_close_utc_hour:
            return RuleViolation(
                rule="friday_close",
                message=f"No new trades after {self._cfg.friday_close_utc_hour}:00 UTC Friday",
                severity="CRITICAL",
                current_value=f"{now.hour}:{now.minute:02d} UTC",
                limit_value=f"{self._cfg.friday_close_utc_hour}:00 UTC",
            )
        return None

    def check_min_rr(
        self, entry: float, sl: float, tp: float,
    ) -> RuleViolation | None:
        """Reject trades whose risk-reward ratio is below the configured minimum.

        tp=0 means no TP yet set (trailing stop / open-ended); skip the check.
        """
        if tp == 0 or sl == 0 or entry == sl:
            return None
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0:
            return None
        rr = reward / risk
        min_rr = max(self._cfg.min_rr_ratio, _HARDCODED_MIN["min_rr_ratio"])
        if rr < min_rr:
            return RuleViolation(
                rule="min_rr_ratio",
                message=(
                    f"R:R {rr:.2f}:1 below minimum {min_rr:.1f}:1 "
                    f"(entry={entry}, sl={sl}, tp={tp})"
                ),
                severity="CRITICAL",
                current_value=round(rr, 2),
                limit_value=min_rr,
            )
        return None

    # ── Circuit breakers (G5 honest reporting) ────────────────────────────────

    def set_breaker_state(
        self,
        name: str,
        triggered: bool,
        reason: str = "",
        triggered_at: str | None = None,
    ) -> None:
        """Record the ACTUAL state of a breaker whose live signal lives in main.py.

        G5 contract (C2 fills): rows such as ``session_gate`` / ``anti_stacking``
        / ``anti_revenge`` / ``min_conviction`` / ``trade_cooldown`` are decided
        in main.py, so main.py calls this (or passes
        ``state["breaker_state"] = {name: {...}}`` to
        ``get_active_circuit_breakers``) instead of the engine reporting a
        hardcoded ``triggered: False``. Tracked state can only ADD a trip; it
        can never mask a live computation.
        """
        self._breaker_state[name] = {
            "triggered": bool(triggered),
            "reason": reason if triggered else "",
            "triggered_at": triggered_at if triggered else None,
        }

    def clear_breaker_state(self, name: str) -> None:
        """Drop the tracked state for one breaker (e.g. after a reset)."""
        self._breaker_state.pop(name, None)

    def _pairwise_correlation_breach(
        self, open_positions: list[Any],
    ) -> tuple[bool, str]:
        """Max |corr| among currently-open position pairs vs ``max_correlation``."""
        syms: list[str] = []
        for pos in open_positions:
            raw = pos.get("symbol", "") if isinstance(pos, dict) else getattr(pos, "symbol", "")
            sym = str(raw).upper().replace("/", "")
            if sym:
                syms.append(sym)
        threshold = self._cfg.max_correlation
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                if syms[i] == syms[j]:
                    continue
                corr = _STATIC_CORR_PAIRS.get(f"{syms[i]}:{syms[j]}") or (
                    _STATIC_CORR_PAIRS.get(f"{syms[j]}:{syms[i]}")
                )
                if corr is not None and abs(corr) > threshold:
                    return True, (
                        f"Open positions {syms[i]}/{syms[j]} correlation "
                        f"{abs(corr):.2f} > {threshold}"
                    )
        return False, ""

    def get_active_circuit_breakers(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Circuit-breaker rows reflecting ACTUAL engine/runner state (G5).

        Every row is resolved from live state instead of hardcoded flags:

        * daily-loss / weekly-DD / peak-DD / open-risk / max-positions /
          anti-tilt / friday-close / spread / news / correlation /
          daily-trade-limit rows are computed from ``state`` and the engine cfg;
        * rows whose live signal lives in main.py (``anti_stacking``,
          ``anti_revenge``, ``session_gate``, ``min_conviction``,
          ``trade_cooldown``) report real state recorded via
          ``set_breaker_state(...)`` or ``state["breaker_state"][name] =
          {"triggered": bool, "reason": str, "triggered_at": iso|None}``.

        Tracked state can only ADD a trip — a live computation can never be
        masked. Triggered rows always carry a reason and a ``triggered_at``.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        daily_loss = abs(state.get("daily_loss_pct", 0))
        weekly_dd = abs(state.get("weekly_dd_pct", 0))
        open_positions = state.get("open_positions_count", 0)
        is_tilt = state.get("tilt_status", "NORMAL").upper() == "TILT"
        friday_v = self.check_friday_close()
        news_v = self.check_news_blackout()

        equity_value = float(state.get("equity") or state.get("balance") or 0.0)
        peak_raw = state.get("equity_peak")
        peak_v = self.check_drawdown_from_peak(
            float(peak_raw) if isinstance(peak_raw, (int, float)) else None,
            equity_value,
            day=str(state.get("equity_peak_day", "")),
        )
        open_risk_raw = state.get("open_risk_amount")
        open_risk_v = self.check_portfolio_open_risk(
            float(open_risk_raw) if isinstance(open_risk_raw, (int, float)) else 0.0,
            equity_value,
        )

        avg_spread = state.get("avg_spread", 0.0)
        current_spread = state.get("current_spread", 0.0)
        spread_ratio = (
            current_spread / avg_spread
            if isinstance(avg_spread, (int, float))
            and isinstance(current_spread, (int, float))
            and avg_spread > 0
            else 0.0
        )
        spread_breached = spread_ratio > self._cfg.max_spread_multiplier
        corr_breached, corr_reason = self._pairwise_correlation_breach(
            state.get("open_positions") or [],
        )
        trade_count = state.get("daily_trade_count")
        trade_limit = state.get("max_daily_trades")
        daily_trade_breached = (
            isinstance(trade_count, (int, float))
            and isinstance(trade_limit, (int, float))
            and trade_limit > 0
            and trade_count >= trade_limit
        )

        overrides_raw = state.get("breaker_state")
        overrides: dict[str, Any] = overrides_raw if isinstance(overrides_raw, dict) else {}

        def _row(name: str, triggered: bool, reason: str) -> dict[str, Any]:
            tracked = overrides.get(name)
            if not isinstance(tracked, dict):
                tracked = self._breaker_state.get(name)
            triggered_at = None
            if not triggered and isinstance(tracked, dict) and tracked.get("triggered"):
                triggered = True
                reason = str(tracked.get("reason", "") or reason)
                triggered_at = tracked.get("triggered_at")
            return {
                "name": name,
                "triggered": triggered,
                "triggered_at": (triggered_at or now_iso) if triggered else None,
                "reason": reason if triggered else "",
            }

        return [
            _row(
                "daily_loss_limit",
                daily_loss >= self._cfg.max_daily_loss_pct,
                f"Daily loss {daily_loss:.1f}% >= {self._cfg.max_daily_loss_pct}%",
            ),
            _row(
                "weekly_drawdown_limit",
                weekly_dd >= self._cfg.max_weekly_drawdown_pct,
                f"Weekly DD {weekly_dd:.1f}% >= {self._cfg.max_weekly_drawdown_pct}%",
            ),
            _row(
                "drawdown_from_peak",
                peak_v is not None,
                peak_v.message if peak_v else "",
            ),
            _row(
                "portfolio_open_risk",
                open_risk_v is not None,
                open_risk_v.message if open_risk_v else "",
            ),
            _row(
                "max_positions",
                open_positions >= self._cfg.max_open_positions,
                f"Open positions {open_positions} >= {self._cfg.max_open_positions}",
            ),
            _row("anti_tilt", is_tilt, "Tilt detected — trading paused"),
            _row(
                "friday_close",
                friday_v is not None,
                friday_v.message if friday_v else "",
            ),
            # Live signals for these five live in main.py/Redis — report the
            # actual state recorded via set_breaker_state / state["breaker_state"].
            _row("anti_stacking", False, ""),
            _row("anti_revenge", False, ""),
            _row("session_gate", False, ""),
            _row("min_conviction", False, ""),
            _row(
                "daily_trade_limit",
                daily_trade_breached,
                f"Daily trades {trade_count} >= {trade_limit}",
            ),
            _row("trade_cooldown", False, ""),
            _row(
                "correlation_limit",
                corr_breached,
                corr_reason,
            ),
            _row(
                "spread_limit",
                spread_breached,
                (
                    f"Spread {spread_ratio:.1f}x average exceeds "
                    f"{self._cfg.max_spread_multiplier}x limit"
                ),
            ),
            _row(
                "news_blackout",
                news_v is not None,
                news_v.message if news_v else "",
            ),
        ]
