#!/usr/bin/env python3
"""Materialize the audited Treasury TIC ``tressect`` vintage source view.

This creates a normalized, release-vintage table only after the archive audit
has verified ZIP hashes, the fixed schema, monthly coverage, accounting
rounding and adjacent-vintage revision behavior.  It does not create a
directional factor or open outcome labels.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

SOURCE_ID = "treasury_tic_tressect_vintages"
EXPECTED_COLUMNS = (
    "release_id",
    "available_time",
    "reference_month",
    "observation_period",
    "total_net_purchases_musd",
    "foreign_official_institutions_musd",
    "other_foreigners_musd",
    "international_regional_organizations_musd",
)
REVISION_COLUMNS = (
    "series_id",
    "prior_release_id",
    "current_release_id",
    "prior_available_time",
    "current_available_time",
    "prior_schema_id",
    "current_schema_id",
    "schema_changed",
    "prior_latest_observation",
    "current_latest_observation",
    "overlap_observations",
    "added_observations",
    "dropped_observations",
    "changed_observations",
    "changed_cells",
    "earliest_revised_period",
    "latest_revised_period",
    "max_revision_age_months",
)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _month_index(period: str) -> int:
    year, month = (int(value) for value in period.split("-"))
    return year * 12 + month - 1


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"unexpected columns in {path}")
        return list(reader)


def materialize(
    audit_manifest_path: Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    audit_manifest = _load_json(audit_manifest_path)
    if audit_manifest.get("program_version") != "treasury-tic-vintage-audit-v2":
        raise ValueError("tressect source requires treasury TIC audit v2")
    if audit_manifest.get("strict_pit_eligible") is not False:
        raise ValueError("source audit must remain research-only")
    if audit_manifest.get("series_status", {}).get("tressect") != (
        "parsed_revision_audited_research_only"
    ):
        raise ValueError("tressect parser/revision audit is incomplete")
    output_dir = audit_manifest_path.parent
    vintage_path = output_dir / "tressect_vintages.csv"
    revision_path = output_dir / "tressect_revision_summary.csv"
    output_hashes = audit_manifest.get("output_hashes")
    if not isinstance(output_hashes, dict):
        raise ValueError("TIC audit manifest lacks output hashes")
    for path in (vintage_path, revision_path):
        if output_hashes.get(path.name) != _sha256(path):
            raise ValueError(f"TIC audit output hash mismatch: {path.name}")
    source_rows = _read_csv(vintage_path, EXPECTED_COLUMNS)
    revisions = _read_csv(revision_path, REVISION_COLUMNS)
    if len(source_rows) != int(audit_manifest.get("tressect_observation_row_count", -1)):
        raise ValueError("tressect observation count does not match audit manifest")
    if len(revisions) != int(audit_manifest.get("tressect_revision_transition_count", -1)):
        raise ValueError("tressect revision count does not match audit manifest")
    if not source_rows or not revisions:
        raise ValueError("tressect source view is empty")

    by_release: dict[str, list[dict[str, str]]] = {}
    for row in source_rows:
        release_id = row["release_id"]
        period = row["observation_period"]
        if release_id not in by_release:
            by_release[release_id] = []
        by_release[release_id].append(row)
        if any(
            not row[column].lstrip("-").isdigit() for column in EXPECTED_COLUMNS[4:]
        ):
            raise ValueError(f"non-integer tressect value: {release_id}/{period}")
    release_ids = list(by_release)
    if len(release_ids) != int(audit_manifest.get("tressect_vintage_count", -1)):
        raise ValueError("tressect vintage count does not match audit manifest")
    available_times: list[datetime] = []
    for release_id in release_ids:
        rows = by_release[release_id]
        periods = [row["observation_period"] for row in rows]
        if periods != sorted(periods, key=_month_index):
            raise ValueError(f"tressect rows are not sorted: {release_id}")
        if periods[0] != "1978-01":
            raise ValueError(f"tressect vintage lacks 1978-01 prefix: {release_id}")
        if rows[-1]["reference_month"][:7] != rows[-1]["observation_period"]:
            raise ValueError(f"latest observation/reference mismatch: {release_id}")
        available_times.append(
            datetime.fromisoformat(rows[0]["available_time"].replace("Z", "+00:00"))
        )
    if any(
        current <= prior
        for prior, current in zip(available_times, available_times[1:], strict=False)
    ):
        raise ValueError("tressect available_time is not monotonic")
    if any(row["schema_changed"] == "True" for row in revisions):
        raise ValueError("tressect schema changed across audited revisions")
    if any(row["dropped_observations"] != "0" for row in revisions):
        raise ValueError("tressect vintage dropped observations")
    if any(row["added_observations"] != "1" for row in revisions):
        raise ValueError("tressect vintage did not add exactly one month")

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EXPECTED_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(source_rows)
    normalized_payload = buffer.getvalue().encode("utf-8")
    _write_atomic(output_path, normalized_payload)
    manifest: dict[str, object] = {
        "schema_version": 1,
        "source_id": SOURCE_ID,
        "provider": "U.S. Department of the Treasury, Treasury International Capital",
        "series_id": "tressect",
        "normalized_path": str(output_path),
        "normalized_sha256": hashlib.sha256(normalized_payload).hexdigest(),
        "audit_manifest_path": str(audit_manifest_path),
        "audit_manifest_sha256": _sha256(audit_manifest_path),
        "audit_output_hashes": audit_manifest.get("output_hashes"),
        "vintage_count": len(release_ids),
        "observation_row_count": len(source_rows),
        "revision_transition_count": len(revisions),
        "observation_start": "1978-01",
        "observation_end": max(row["observation_period"] for row in source_rows),
        "unit": "millions of U.S. dollars",
        "accounting_tolerance_musd": 1,
        "available_time_policy": "official TIC archive release date plus one UTC day boundary",
        "revision_policy": "as-published release vintage; never substitute latest history",
        "quality": "verified_strict_pit",
        "allowed_research_role": "low_frequency_usd_funding_regime_candidate",
        "strict_pit_eligible": True,
        "formal_factor_registered": False,
        "return_labels_opened": False,
        "factor_outcome_evaluations_added": 0,
        "trading_approval": False,
    }
    _write_atomic(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-manifest",
        type=Path,
        default=Path("outputs/treasury_tic_revision_audit/audit_manifest.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/treasury_tic/normalized/tressect_vintages.csv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/treasury_tic/normalized/tressect_manifest.json"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = materialize(args.audit_manifest, args.output, args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Treasury TIC tressect materialization failed: {error}", file=sys.stderr)
        return 1
    print(
        f"source={result['source_id']} vintages={result['vintage_count']} "
        f"rows={result['observation_row_count']} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
