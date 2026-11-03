from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "discover_fx_research.py"
SPEC = importlib.util.spec_from_file_location("fx_research_discovery", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
discovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = discovery
SPEC.loader.exec_module(discovery)


def _work(index: int) -> dict[str, object]:
    return {
        "id": f"https://openalex.org/W{1000 + index}",
        "doi": f"https://doi.org/10.0000/test{index}",
        "title": f"FX research candidate {index}",
        "publication_year": 2024,
        "type": "article",
        "cited_by_count": 10 + index,
        "is_retracted": False,
        "is_paratext": False,
        "open_access": {"is_oa": True, "oa_status": "gold"},
        "primary_location": {
            "landing_page_url": f"https://example.test/{index}",
            "pdf_url": f"https://example.test/{index}.pdf",
            "source": {"display_name": "Test Journal"},
        },
        "authorships": [
            {"author": {"display_name": "Ada Researcher"}},
            {"author": {"display_name": "Ben Researcher"}},
        ],
        "topics": [{"display_name": "Foreign exchange"}],
        "abstract_inverted_index": {"Currency": [0], "risk": [1], "premia": [2]},
    }


def _transport() -> httpx.MockTransport:
    query_index = {query.search_text: index for index, query in enumerate(discovery.QUERIES)}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == discovery.ALLOWED_HOST
        search = request.url.params["search"]
        assert request.url.params["per-page"] == "3"
        assert "from_publication_date:2016-01-01" in request.url.params["filter"]
        index = query_index[search]
        return httpx.Response(
            200,
            json={"meta": {"count": 1}, "results": [_work(index)]},
        )

    return httpx.MockTransport(handler)


def test_discovery_archives_raw_and_never_registers_or_evaluates_factors(
    tmp_path: Path,
) -> None:
    manifest = discovery.run_discovery(
        tmp_path,
        from_year=2016,
        to_year=2026,
        per_query=3,
        api_key="secret-test-key",
        delay_seconds=0,
        transport=_transport(),
    )

    assert manifest["query_count"] == 5
    assert manifest["query_match_rows"] == 5
    assert manifest["unique_works"] == 5
    assert manifest["api_key_supplied"] is True
    assert manifest["discovery_only"] is True
    assert manifest["factor_registry_modified"] is False
    assert manifest["outcome_evaluations_added"] == 0
    assert all("secret-test-key" not in source["source_url"] for source in manifest["sources"])
    assert all(Path(source["raw_path"]).is_file() for source in manifest["sources"])
    assert all(Path(source["archive_path"]).is_file() for source in manifest["sources"])

    rows = list(csv.DictReader((tmp_path / "fx_research_candidates.csv").open()))
    assert len(rows) == 5
    assert {row["discovery_status"] for row in rows} == {
        "candidate_unreviewed_not_registered"
    }
    assert {row["factor_registry_status"] for row in rows} == {"not_registered"}
    assert {row["outcome_evaluations_added"] for row in rows} == {"0"}
    assert {row["abstract"] for row in rows} == {"Currency risk premia"}
    assert json.loads((tmp_path / "manifest.json").read_text())["unique_works"] == 5


def test_normalizer_rejects_out_of_contract_work_id() -> None:
    query = discovery.QUERIES[0]
    work = _work(0)
    work["id"] = "https://example.test/not-openalex"
    payload = json.dumps({"results": [work]}).encode()
    with pytest.raises(ValueError, match="invalid OpenAlex work id"):
        discovery.normalize_payload(
            query,
            payload,
            source_url="https://api.openalex.org/works?search=test",
            raw_sha256="a" * 64,
            retrieved_at_utc="2026-07-17T00:00:00Z",
            from_year=2016,
            to_year=2026,
        )


def test_openalex_endpoint_is_https_and_exact_host() -> None:
    discovery._validate_endpoint("https://api.openalex.org/works?search=fx")
    with pytest.raises(ValueError, match="refusing"):
        discovery._validate_endpoint("https://example.test/works")
