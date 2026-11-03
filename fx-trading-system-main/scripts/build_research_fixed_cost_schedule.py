#!/usr/bin/env python3
"""Build research-only fixed financing schedule (software_fixture).

Reads configs/research_fixed_costs.yaml and writes a daily broker_financing CSV
plus sidecar manifest. Does not unlock formal net returns or trading approval.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "research_fixed_costs.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    account = cfg["account"]
    coverage = cfg["coverage"]
    fin = cfg["financing"]
    annual = fin["annual_rates"]

    start = datetime.fromisoformat(coverage["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(coverage["end_exclusive"].replace("Z", "+00:00"))

    out_csv = ROOT / cfg["outputs"]["financing_csv"]
    out_manifest = ROOT / cfg["outputs"]["financing_manifest"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "symbol",
        "effective_time",
        "available_time",
        "long_financing",
        "short_financing",
        "unit",
        "day_count",
        "source",
        "provenance",
        "quote_quality",
        "version",
        "broker_entity",
        "account_currency",
        "triple_swap_weekday",
        "rollover_multiplier",
    ]

    rows: list[str] = [",".join(header)]
    day = start
    n_days = 0
    while day < end:
        # Research simplification: stamp every calendar day at 22:00Z.
        stamp = day.strftime("%Y-%m-%dT22:00:00Z")
        # Wednesday triple (weekday(): Mon=0 ... Sun=6)
        mult = 3 if day.weekday() == 2 else 1
        for symbol, rates in annual.items():
            long_daily = float(rates["long"]) / 360.0
            short_daily = float(rates["short"]) / 360.0
            rows.append(
                ",".join(
                    [
                        symbol,
                        stamp,
                        stamp,
                        f"{long_daily:.12g}",
                        f"{short_daily:.12g}",
                        fin["unit"],
                        fin["day_count"],
                        fin["source"],
                        fin["provenance"],
                        fin["quote_quality"],
                        fin["version"],
                        account["broker_entity"],
                        account["account_currency"],
                        fin["triple_swap_weekday"],
                        str(mult),
                    ]
                )
            )
        n_days += 1
        day += timedelta(days=1)

    out_csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    csv_sha = _sha256(out_csv)

    manifest = {
        "schema_version": 1,
        "dataset_kind": "broker_financing_schedule",
        "csv_sha256": csv_sha,
        "assumption_id": cfg.get("assumption_id"),
        "status": "software_fixture",
        "formal_net_returns_ready": False,
        "trading_approval": False,
        "coverage": coverage,
        "row_count": len(rows) - 1,
        "calendar_days": n_days,
        "symbols": sorted(annual.keys()),
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_catalog": [
            {
                "source": fin["source"],
                "provenance": fin["provenance"],
                "quote_quality": fin["quote_quality"],
                "version": fin["version"],
                "broker_entity": account["broker_entity"],
                "account_currency": account["account_currency"],
            }
        ],
        "notes": [
            "Research fixed financing only; not IB historical schedule.",
            "cost_incomplete_research_only; do not promote to formal-net.",
        ],
    }
    out_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_csv} rows={len(rows)-1} days={n_days}")
    print(f"wrote {out_manifest} sha256={csv_sha[:16]}...")


if __name__ == "__main__":
    main()
