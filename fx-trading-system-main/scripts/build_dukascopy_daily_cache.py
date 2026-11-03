#!/usr/bin/env python3
"""Build a formal, outcome-blind Dukascopy daily SQLite cache and receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_system.dukascopy_daily import run_dukascopy_daily_from_sqlite
from fx_system.dukascopy_daily_cache import write_dukascopy_daily_cache


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", required=True, help="First New York session-start date")
    parser.add_argument("--end", required=True, help="Exclusive New York session-start date")
    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
        help="Currency pairs, for example EURUSD GBPUSD",
    )
    parser.add_argument("--transfer-manifest", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    run = run_dukascopy_daily_from_sqlite(
        args.database_dir,
        args.symbols,
        args.start,
        args.end,
        transfer_manifest_path=args.transfer_manifest,
    )
    receipt = write_dukascopy_daily_cache(run, args.output, overwrite=args.overwrite)
    summary = {
        "status": "daily_cache_written_outcome_blind",
        "cache_path": str(receipt.cache_path),
        "bytes": receipt.bytes,
        "sha256": receipt.sha256,
        "symbols": list(receipt.symbols),
        "requested_session_count": receipt.session_count,
        "daily_bar_count": receipt.daily_bar_count,
        "contains_returns": False,
        "contains_labels": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
