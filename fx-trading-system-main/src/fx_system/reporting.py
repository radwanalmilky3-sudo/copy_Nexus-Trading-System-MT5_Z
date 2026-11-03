from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .analytics import calculate_metrics, equity_frame, trades_frame
from .config import SystemConfig
from .models import BacktestResult, Signal


def _json_default(value: object) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def data_fingerprint(data: Mapping[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for symbol, frame in sorted(data.items()):
        digest.update(symbol.encode())
        columns = sorted(
            column
            for column in frame.columns
            if column in {"open", "high", "low", "close", "volume"}
            or column == "tick_count"
            or column.startswith(("bid_", "ask_", "spread_", "swap_"))
        )
        digest.update("\0".join(columns).encode())
        digest.update("\0".join(str(frame[column].dtype) for column in columns).encode())
        hashed = pd.util.hash_pandas_object(frame[columns], index=True, categorize=False)
        digest.update(hashed.values.tobytes())
    return digest.hexdigest()


def write_backtest_artifacts(
    result: BacktestResult,
    signals: list[Signal],
    data: Mapping[str, pd.DataFrame],
    config: SystemConfig,
    output_directory: str | Path | None = None,
) -> Path:
    output = Path(output_directory or config.output.directory)
    output.mkdir(parents=True, exist_ok=True)
    metrics = calculate_metrics(result)
    trades_frame(result).to_csv(output / "trades.csv", index=False)
    equity_frame(result).to_csv(output / "equity.csv", index=True)
    if config.output.save_signals:
        pd.DataFrame([signal.to_dict() for signal in signals]).to_csv(
            output / "signals.csv", index=False
        )
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=_json_default, allow_nan=False), encoding="utf-8"
    )
    (output / "rejected_signals.json").write_text(
        json.dumps(result.rejected_signals, indent=2, default=_json_default), encoding="utf-8"
    )
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "uncommitted"
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "git_revision": revision,
        "data_fingerprint_sha256": data_fingerprint(data),
        "symbols": sorted(data),
        "rows": {symbol: len(frame) for symbol, frame in data.items()},
        "ranges": {
            symbol: [frame.index[0].isoformat(), frame.index[-1].isoformat()]
            for symbol, frame in data.items()
        },
        "config": config.model_dump(mode="json"),
        "engine_metadata": result.metadata,
    }
    (output / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8"
    )
    (output / "report.md").write_text(_markdown_report(metrics, manifest), encoding="utf-8")
    return output


def _markdown_report(metrics: dict[str, Any], manifest: dict[str, Any]) -> str:
    warning = (
        "This run uses synthetic data and cannot support a profitability claim."
        if manifest["config"]["data"]["provider"] == "synthetic"
        else "Public midpoint bars are research data, not executable broker bid/ask quotes."
    )
    return f"""# FX portfolio backtest report

Generated: {manifest["created_at"]}

> {warning} No result in this report is investment advice or a return guarantee.

## Portfolio result

| Metric | Value |
|---|---:|
| Initial equity | {metrics["initial_equity"]:,.2f} |
| Final equity | {metrics["final_equity"]:,.2f} |
| Total return | {metrics["total_return"]:.2%} |
| CAGR | {metrics["cagr"]:.2%} |
| Sharpe (0% RF) | {metrics["sharpe"]:.3f} |
| Maximum drawdown | {metrics["max_drawdown"]:.2%} |
| Trades | {metrics["trades"]} |
| Win rate | {metrics["win_rate"]:.2%} |
| Realized payoff ratio | {metrics["payoff_ratio"]:.3f} |
| Profit factor | {metrics["profit_factor"]:.3f} |
| Average holding | {metrics["average_holding_hours"]:.1f} h |
| Maximum holding | {metrics["max_holding_hours"]:.1f} h |
| Modeled total costs | {metrics["costs"]:,.2f} |

## Reproducibility

- Data SHA-256: `{manifest["data_fingerprint_sha256"]}`
- Git revision: `{manifest["git_revision"]}`
- Symbols: {", ".join(manifest["symbols"])}
- Source: `{manifest["config"]["data"]["provider"]}`

The engine generates signals from closed bars, executes only on a subsequent bar, applies spread,
slippage, commission and configured swap, resolves same-bar stop/target ambiguity against the
strategy, and closes every remaining position at the end of the data.
"""
