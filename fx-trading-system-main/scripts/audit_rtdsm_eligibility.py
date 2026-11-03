#!/usr/bin/env python3
"""Audit row-level strict versus conservative PIT eligibility in RTDSM vintages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from fx_system.macro_vintages import rtdsm_eligibility_audit


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(
            "data/supplemental_fx/normalized/phillyfed_rtdsm_vintages.csv.gz"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/external_factor_eligibility_20260717/rtdsm_row_audit.json"),
    )
    args = parser.parse_args()
    frame = pd.read_csv(
        args.input,
        usecols=["series_id", "pit_eligible", "availability_policy"],
    )
    audit = {
        "schema_version": 1,
        "input_path": str(args.input),
        "input_sha256": _sha256(args.input),
        **rtdsm_eligibility_audit(frame),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()

