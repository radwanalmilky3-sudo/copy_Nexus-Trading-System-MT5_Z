#!/usr/bin/env python3
"""Discover FX research candidates without registering factors or opening outcomes.

The tool queries a frozen set of OpenAlex searches, archives the raw responses,
and writes an auditable candidate table. Search ranking is discovery evidence,
not evidence that a strategy works. Every row remains unreviewed until a human
verifies the paper, economic mechanism, data contract and search-budget impact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import httpx

PROGRAM_VERSION: Final = "fx-research-discovery-v1"
PROVIDER: Final = "OpenAlex"
API_ROOT: Final = "https://api.openalex.org/works"
ALLOWED_HOST: Final = "api.openalex.org"
TERMS_URL: Final = "https://openalex.org/terms"
DOCUMENTATION_URL: Final = "https://developers.openalex.org/"
DATA_LICENSE: Final = "CC0"
MAX_RESPONSE_BYTES: Final = 12 * 1024 * 1024
DEFAULT_PER_QUERY: Final = 50
DEFAULT_DELAY_SECONDS: Final = 0.5


@dataclass(frozen=True)
class ResearchQuery:
    query_id: str
    theme: str
    search_text: str
    intended_use: str


QUERIES: Final[tuple[ResearchQuery, ...]] = (
    ResearchQuery(
        "slow_currency_premia",
        "slow_horizon_fx_factors",
        "foreign exchange currency risk premia factor investing carry value momentum liquidity",
        "Find economically motivated monthly or cross-sectional currency premia.",
    ),
    ResearchQuery(
        "intraday_fx_microstructure",
        "intraday_microstructure",
        "foreign exchange intraday microstructure fixing order flow liquidity bid ask",
        "Find executable intraday mechanisms and the market-data contract they require.",
    ),
    ResearchQuery(
        "fx_machine_learning",
        "factor_mining_methods",
        '"exchange rate forecasting" machine learning',
        "Find constrained panel, ensemble, shrinkage and non-linear discovery methods.",
    ),
    ResearchQuery(
        "data_snooping_controls",
        "statistical_validation",
        "financial strategy data snooping multiple testing backtest overfitting false discovery",
        "Find methods that control selection bias and repeated research trials.",
    ),
    ResearchQuery(
        "realtime_macro_fx",
        "point_in_time_macro",
        "exchange rates real time macroeconomic data revisions forecasts vintages",
        "Find PIT macro states and revision-aware currency research designs.",
    ),
)

OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "query_id",
    "theme",
    "search_rank",
    "openalex_id",
    "doi",
    "title",
    "publication_year",
    "work_type",
    "cited_by_count",
    "is_retracted",
    "is_paratext",
    "open_access_status",
    "is_oa",
    "primary_source",
    "landing_page_url",
    "pdf_url",
    "authors",
    "topics",
    "abstract",
    "discovery_status",
    "factor_registry_status",
    "outcome_evaluations_added",
    "provider",
    "source_url",
    "raw_sha256",
    "retrieved_at_utc",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _query_params(
    query: ResearchQuery,
    *,
    from_year: int,
    to_year: int,
    per_query: int,
    api_key: str | None,
) -> dict[str, str]:
    params = {
        "search": query.search_text,
        "filter": (
            f"from_publication_date:{from_year}-01-01,"
            f"to_publication_date:{to_year}-12-31"
        ),
        "per-page": str(per_query),
        "select": (
            "id,doi,title,publication_year,type,cited_by_count,is_retracted,is_paratext,"
            "open_access,primary_location,authorships,topics,abstract_inverted_index"
        ),
    }
    if api_key:
        params["api_key"] = api_key
    return params


def _source_url(params: dict[str, str]) -> str:
    # Never persist an API key in manifests or normalized rows.
    safe = {key: value for key, value in params.items() if key != "api_key"}
    return str(httpx.URL(API_ROOT, params=safe))


def _validate_endpoint(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"refusing non-OpenAlex endpoint: {url}")


def _fetch(
    client: httpx.Client,
    query: ResearchQuery,
    *,
    from_year: int,
    to_year: int,
    per_query: int,
    api_key: str | None,
) -> tuple[bytes, str]:
    params = _query_params(
        query,
        from_year=from_year,
        to_year=to_year,
        per_query=per_query,
        api_key=api_key,
    )
    source_url = _source_url(params)
    _validate_endpoint(source_url)
    response = client.get(API_ROOT, params=params)
    if response.status_code in {401, 403} and not api_key:
        raise RuntimeError(
            "OpenAlex rejected an unauthenticated request; set OPENALEX_API_KEY "
            "to a free API key and retry"
        )
    response.raise_for_status()
    payload = response.content
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError(f"OpenAlex response exceeds {MAX_RESPONSE_BYTES} bytes")
    return payload, source_url


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _abstract(index: object) -> str:
    if not isinstance(index, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int) and position >= 0:
                positioned.append((position, word))
    return " ".join(word for _, word in sorted(positioned))


def _names(authorships: object) -> str:
    if not isinstance(authorships, list):
        return ""
    names: list[str] = []
    for item in authorships:
        author = _object(_object(item).get("author"))
        name = author.get("display_name")
        if isinstance(name, str) and name:
            names.append(name)
    return " | ".join(names)


def _topics(topics: object) -> str:
    if not isinstance(topics, list):
        return ""
    values: list[str] = []
    for item in topics[:8]:
        name = _object(item).get("display_name")
        if isinstance(name, str) and name:
            values.append(name)
    return " | ".join(values)


def normalize_payload(
    query: ResearchQuery,
    payload: bytes,
    *,
    source_url: str,
    raw_sha256: str,
    retrieved_at_utc: str,
    from_year: int,
    to_year: int,
) -> list[dict[str, object]]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid OpenAlex JSON for {query.query_id}: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise ValueError(f"OpenAlex response for {query.query_id} lacks results")
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for rank, raw_work in enumerate(document["results"], start=1):
        work = _object(raw_work)
        work_id = work.get("id")
        title = work.get("title")
        year = work.get("publication_year")
        if not isinstance(work_id, str) or not work_id.startswith("https://openalex.org/W"):
            raise ValueError(f"{query.query_id} rank {rank}: invalid OpenAlex work id")
        if work_id in seen_ids:
            raise ValueError(f"{query.query_id}: duplicate work id {work_id}")
        seen_ids.add(work_id)
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"{query.query_id} rank {rank}: missing title")
        if not isinstance(year, int) or not from_year <= year <= to_year:
            raise ValueError(f"{query.query_id} rank {rank}: publication year outside query")
        open_access = _object(work.get("open_access"))
        primary = _object(work.get("primary_location"))
        source = _object(primary.get("source"))
        rows.append(
            {
                "query_id": query.query_id,
                "theme": query.theme,
                "search_rank": rank,
                "openalex_id": work_id,
                "doi": work.get("doi") or "",
                "title": title.strip(),
                "publication_year": year,
                "work_type": work.get("type") or "",
                "cited_by_count": int(work.get("cited_by_count") or 0),
                "is_retracted": bool(work.get("is_retracted")),
                "is_paratext": bool(work.get("is_paratext")),
                "open_access_status": open_access.get("oa_status") or "",
                "is_oa": bool(open_access.get("is_oa")),
                "primary_source": source.get("display_name") or "",
                "landing_page_url": primary.get("landing_page_url") or "",
                "pdf_url": primary.get("pdf_url") or "",
                "authors": _names(work.get("authorships")),
                "topics": _topics(work.get("topics")),
                "abstract": _abstract(work.get("abstract_inverted_index")),
                "discovery_status": "candidate_unreviewed_not_registered",
                "factor_registry_status": "not_registered",
                "outcome_evaluations_added": 0,
                "provider": PROVIDER,
                "source_url": source_url,
                "raw_sha256": raw_sha256,
                "retrieved_at_utc": retrieved_at_utc,
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    _atomic_bytes(path, (json.dumps(payload, indent=2) + "\n").encode())


def run_discovery(
    output_dir: Path,
    *,
    from_year: int,
    to_year: int,
    per_query: int,
    api_key: str | None,
    delay_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    if from_year < 1900 or to_year < from_year:
        raise ValueError("invalid publication year range")
    if not 1 <= per_query <= 100:
        raise ValueError("per_query must be between 1 and 100")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must be non-negative")
    retrieved_at = _utc_now()
    raw_root = output_dir / "raw"
    archive_root = output_dir / "archive"
    rows: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    headers = {"User-Agent": f"fx-portfolio-system/{PROGRAM_VERSION}"}
    with httpx.Client(
        timeout=45,
        follow_redirects=True,
        trust_env=False,
        headers=headers,
        transport=transport,
    ) as client:
        for index, query in enumerate(QUERIES):
            if index and delay_seconds:
                time.sleep(delay_seconds)
            payload, source_url = _fetch(
                client,
                query,
                from_year=from_year,
                to_year=to_year,
                per_query=per_query,
                api_key=api_key,
            )
            digest = _sha256(payload)
            raw_path = raw_root / f"{query.query_id}.json"
            archive_path = archive_root / query.query_id / f"{digest}.json"
            _atomic_bytes(raw_path, payload)
            if not archive_path.exists():
                _atomic_bytes(archive_path, payload)
            normalized = normalize_payload(
                query,
                payload,
                source_url=source_url,
                raw_sha256=digest,
                retrieved_at_utc=retrieved_at,
                from_year=from_year,
                to_year=to_year,
            )
            rows.extend(normalized)
            sources.append(
                {
                    **asdict(query),
                    "source_url": source_url,
                    "raw_path": str(raw_path),
                    "archive_path": str(archive_path),
                    "raw_sha256": digest,
                    "response_bytes": len(payload),
                    "result_count": len(normalized),
                }
            )
    rows.sort(key=lambda row: (str(row["query_id"]), int(row["search_rank"])))
    csv_path = output_dir / "fx_research_candidates.csv"
    _write_csv(csv_path, rows)
    unique_works = len({str(row["openalex_id"]) for row in rows})
    manifest: dict[str, object] = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "generated_at_utc": retrieved_at,
        "provider": PROVIDER,
        "provider_documentation": DOCUMENTATION_URL,
        "provider_terms": TERMS_URL,
        "provider_data_license": DATA_LICENSE,
        "api_key_supplied": api_key is not None,
        "from_year": from_year,
        "to_year": to_year,
        "per_query": per_query,
        "query_count": len(QUERIES),
        "query_match_rows": len(rows),
        "unique_works": unique_works,
        "candidate_csv": str(csv_path),
        "candidate_csv_sha256": _sha256(csv_path.read_bytes()),
        "discovery_only": True,
        "factor_registry_modified": False,
        "outcome_evaluations_added": 0,
        "sources": sources,
    }
    _atomic_json(output_dir / "manifest.json", manifest)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/fx_research_discovery"))
    parser.add_argument("--from-year", type=int, default=2016)
    parser.add_argument("--to-year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--per-query", type=int, default=DEFAULT_PER_QUERY)
    parser.add_argument("--api-key-env", default="OPENALEX_API_KEY")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    try:
        manifest = run_discovery(
            args.output_dir,
            from_year=args.from_year,
            to_year=args.to_year,
            per_query=args.per_query,
            api_key=api_key,
            delay_seconds=args.delay_seconds,
        )
    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
        print(f"research discovery failed: {error}", file=sys.stderr)
        return 1
    print(
        f"queries={manifest['query_count']} rows={manifest['query_match_rows']} "
        f"unique_works={manifest['unique_works']} output={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
