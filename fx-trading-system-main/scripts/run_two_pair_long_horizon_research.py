#!/usr/bin/env python3
"""Run explicitly authorized EURUSD/GBPUSD time-series research from a verified daily cache."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fx_system.dukascopy_daily import build_common_daily_data_from_cache_audit
from fx_system.dukascopy_daily_cache import load_dukascopy_daily_cache
from fx_system.long_horizon import build_long_horizon_research, write_long_horizon_artifacts
from fx_system.long_horizon_config import LongHorizonConfig
from fx_system.long_horizon_research import (
    run_long_horizon_screen,
    write_long_horizon_screen_artifacts,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/long_horizon_two_pair_time_series.yaml"),
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(
            "data/dukascopy_daily_cache/EURUSD_GBPUSD_legacy_to_20250915.sqlite"
        ),
    )
    parser.add_argument("--database-dir", type=Path, default=Path("data/dukascopy_sqlite"))
    parser.add_argument(
        "--transfer-manifest",
        type=Path,
        default=Path(
            "data/dukascopy_sqlite/_sqlite_manifest_EURUSD_GBPUSD_legacy.json"
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screen", action="store_true")
    parser.add_argument(
        "--open-return-labels",
        action="store_true",
        help="Required acknowledgement: this run creates/reads historical outcome labels.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.open_return_labels:
        print(
            "refusing to open outcomes without explicit --open-return-labels",
            file=sys.stderr,
        )
        return 2
    config = LongHorizonConfig.from_yaml(args.config)
    if config.research.research_mode != "time_series_panel":
        print("two-pair runner requires research_mode=time_series_panel", file=sys.stderr)
        return 2
    if config.data.symbols != ["EURUSD", "GBPUSD"]:
        print("two-pair runner requires symbols=[EURUSD, GBPUSD]", file=sys.stderr)
        return 2
    run, cache_receipt = load_dukascopy_daily_cache(
        args.cache,
        args.database_dir,
        transfer_manifest_path=args.transfer_manifest,
    )
    daily = build_common_daily_data_from_cache_audit(run)
    build = build_long_horizon_research(daily, config)
    output = write_long_horizon_artifacts(
        build,
        config,
        args.output or config.research.output_directory,
    )
    screen_summary = None
    if args.screen:
        screen = run_long_horizon_screen(build, config)
        write_long_horizon_screen_artifacts(screen, output)
        screen_summary = screen.summary
    summary = {
        "status": "exploratory_reused_history",
        "research_mode": config.research.research_mode,
        "symbols": config.data.symbols,
        "cache_sha256": cache_receipt.sha256,
        "factor_count": len(build.catalog),
        "fold_count": len(build.folds),
        "screen_executed": args.screen,
        "screen_summary": screen_summary,
        "return_labels_opened": True,
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "note": "Previously inspected history; never an untouched holdout.",
    }
    (output / "two_pair_run_summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

