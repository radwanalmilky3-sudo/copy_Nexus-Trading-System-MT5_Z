"""
Nexus Monitor — Prometheus metrics exporter.

Exposes trading metrics in Prometheus text format so Prometheus can
scrape the /metrics endpoint.

Invariants enforced here:
  * every metric name emits exactly one ``# HELP``/``# TYPE`` pair (duplicate
    TYPE lines make Prometheus reject the whole exposition),
  * NaN/Inf are rendered as the Prometheus-legal ``NaN``/``+Inf``/``-Inf``
    tokens in text output, and as ``None`` in JSON output (strict JSON
    consumers such as ``JSON.parse`` reject bare ``nan``),
  * counters are monotonic — they are only ever incremented,
  * gauges reject non-finite writes so one bad sample cannot poison a
    series permanently.
"""
from __future__ import annotations

import math
import time
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# name → help text, in exposition order.  This registry is the single source
# of truth for HELP/TYPE emission.
_COUNTER_HELP: dict[str, str] = {
    "nexus_trades_total": "Total number of trades executed",
    "nexus_trades_won": "Total number of winning trades",
    "nexus_trades_lost": "Total number of losing trades",
    "nexus_errors_total": "Total number of service errors",
    "nexus_agent_invocations_total": "Total number of agent invocations",
}

_GAUGE_HELP: dict[str, str] = {
    "nexus_pnl_total_usd": "Cumulative P&L in USD",
    "nexus_win_rate": "Win rate percentage",
    "nexus_open_positions": "Number of open positions",
    "nexus_profit_factor": "Profit factor",
    "nexus_sharpe_ratio": "Sharpe ratio",
    "nexus_max_drawdown_pct": "Maximum drawdown percentage",
    "nexus_daily_pnl_usd": "P&L in USD since the last daily reset",
    "nexus_balance_usd": "Account balance in USD",
    "nexus_equity_usd": "Account equity in USD",
}


def _sanitize_number(value: Any) -> float | None:
    """Coerce to a finite float, or None when the value is non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _exposition_value(value: float | None) -> str:
    """Render a value for the Prometheus text exposition format.

    ``nan``/``inf`` (Python's lowercase repr) are not the tokens Prometheus
    expects; emit the canonical ``NaN``/``+Inf``/``-Inf`` so scrapes parse.
    """
    if value is None:
        return "NaN"
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    # repr avoids locale issues and keeps round-trippable precision.
    return repr(value)


def _escape_label_value(value: Any) -> str:
    text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


class MetricsExporter:
    """Collects and exports trading metrics in Prometheus exposition format."""

    def __init__(self) -> None:
        self._counters: dict[str, float] = {
            name: 0.0 for name in _COUNTER_HELP
        }
        self._gauges: dict[str, float] = {
            name: 0.0 for name in _GAUGE_HELP
        }
        self._service_latencies: dict[str, float] = {}
        self._last_update = time.monotonic()

    # ── Counter Updates ───────────────────────────────────────────────────

    def inc_counter(self, name: str, value: float = 1.0) -> None:
        """Increment a counter.  Non-finite or non-positive increments are ignored.

        Counters must be monotonic: this never assigns a lower value, and the
        ``else`` branch only seeds a *new* name (existing counters are never
        reset from here).
        """
        delta = _sanitize_number(value)
        if delta is None or delta < 0:
            log.warning("metrics.counter_increment_ignored", name=name, value=value)
            return
        if name not in self._counters:
            self._counters[name] = 0.0
        self._counters[name] += delta

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge, rejecting non-finite values (they would stick forever)."""
        number = _sanitize_number(value)
        if number is None:
            log.warning("metrics.gauge_rejected_non_finite", name=name, value=value)
            return
        self._gauges[name] = number

    # ── Trade Metrics ─────────────────────────────────────────────────────

    def update_trade_metrics(self, trade: dict[str, Any]) -> None:
        if not isinstance(trade, dict):
            return
        # A malformed/non-finite P&L must not corrupt the running totals: the
        # trade still counts, but its P&L contribution is treated as 0 and the
        # win/loss outcome is derived from the (validated) value.
        raw_pnl = trade.get("pnl_usd", 0)
        pnl = _sanitize_number(raw_pnl)
        if pnl is None:
            log.warning("metrics.trade_pnl_non_finite", pnl=raw_pnl)
            pnl = 0.0

        self._counters["nexus_trades_total"] += 1

        if pnl > 0:
            self._counters["nexus_trades_won"] += 1
        else:
            self._counters["nexus_trades_lost"] += 1

        self._gauges["nexus_pnl_total_usd"] += pnl
        self._gauges["nexus_daily_pnl_usd"] += pnl

        total = self._counters["nexus_trades_total"]
        wins = self._counters["nexus_trades_won"]
        self._gauges["nexus_win_rate"] = (wins / total * 100) if total > 0 else 0.0

        self._last_update = time.monotonic()
        log.debug("metrics.trade_updated", total_trades=total, pnl=pnl)

    # ── Service Health Metrics ────────────────────────────────────────────

    def update_service_metrics(self, service_health: dict[str, Any]) -> None:
        if not isinstance(service_health, dict):
            return
        service = service_health.get("service_name", "unknown")
        latency = _sanitize_number(service_health.get("latency_ms"))
        if latency is None:
            # Absent/invalid latency is represented by omitting the sample
            # rather than publishing NaN for a healthy service.
            self._service_latencies.pop(str(service), None)
        else:
            self._service_latencies[str(service)] = latency
        self._last_update = time.monotonic()

    # ── Bulk State Update ─────────────────────────────────────────────────

    def update_state(
        self,
        *,
        open_positions: int | None = None,
        balance: float | None = None,
        equity: float | None = None,
        profit_factor: float | None = None,
        sharpe_ratio: float | None = None,
        max_drawdown: float | None = None,
    ) -> None:
        """Update state gauges.  ``None``/non-finite values leave the gauge untouched."""
        if open_positions is not None:
            positions = _sanitize_number(open_positions)
            if positions is not None:
                self._gauges["nexus_open_positions"] = positions
        if balance is not None:
            number = _sanitize_number(balance)
            if number is not None:
                self._gauges["nexus_balance_usd"] = number
        if equity is not None:
            number = _sanitize_number(equity)
            if number is not None:
                self._gauges["nexus_equity_usd"] = number
        if profit_factor is not None:
            number = _sanitize_number(profit_factor)
            if number is not None:
                self._gauges["nexus_profit_factor"] = number
        if sharpe_ratio is not None:
            number = _sanitize_number(sharpe_ratio)
            if number is not None:
                self._gauges["nexus_sharpe_ratio"] = number
        if max_drawdown is not None:
            number = _sanitize_number(max_drawdown)
            if number is not None:
                self._gauges["nexus_max_drawdown_pct"] = number
        self._last_update = time.monotonic()

    def reset_daily(self) -> None:
        """Reset the *daily* gauge only (counters and other gauges are untouched)."""
        self._gauges["nexus_daily_pnl_usd"] = 0.0
        log.info("metrics.daily_reset")

    # ── Prometheus Export ─────────────────────────────────────────────────

    def export_metrics(self) -> str:
        lines: list[str] = []

        for name in sorted(self._counters):
            lines.append(f"# HELP {name} {_COUNTER_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {_exposition_value(self._counters[name])}")

        lines.append("")

        for name in sorted(self._gauges):
            lines.append(f"# HELP {name} {_GAUGE_HELP.get(name, name)}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {_exposition_value(self._gauges[name])}")

        if self._service_latencies:
            lines.append("")
            lines.append("# HELP nexus_service_latency_ms Last observed service latency in ms")
            lines.append("# TYPE nexus_service_latency_ms gauge")
            for service in sorted(self._service_latencies):
                safe_name = _escape_label_value(service)
                value = self._service_latencies[service]
                lines.append(
                    f'nexus_service_latency_ms{{service="{safe_name}"}} '
                    f"{_exposition_value(value)}"
                )

        lines.append("")
        return "\n".join(lines) + "\n"

    def get_metrics_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot: non-finite floats are emitted as None.

        ``json.dumps`` would otherwise write bare ``nan``/``Infinity`` tokens,
        which strict JSON parsers (e.g. browser ``JSON.parse``) reject.
        """
        return {
            "counters": {
                name: _sanitize_number(value)
                for name, value in self._counters.items()
            },
            "gauges": {
                name: _sanitize_number(value)
                for name, value in self._gauges.items()
            },
            "service_latencies": {
                name: _sanitize_number(value)
                for name, value in self._service_latencies.items()
            },
            "last_update": self._last_update,
        }
