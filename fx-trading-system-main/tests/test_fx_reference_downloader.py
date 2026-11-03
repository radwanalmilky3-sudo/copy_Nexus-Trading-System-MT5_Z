from __future__ import annotations

import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest


def _load_downloader():
    path = Path(__file__).parents[1] / "scripts" / "download_fx_reference_data.py"
    spec = importlib.util.spec_from_file_location("download_fx_reference_data", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


downloader = _load_downloader()


def _fred_task(*, mutable: bool = True):
    return downloader.DownloadTask(
        key="fred:TEST",
        group="risk",
        provider="fred",
        title="Test series",
        url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=TEST",
        relative_path="fred/risk/TEST.csv",
        validator="fred_csv",
        research_eligibility="test_only",
        mutable=mutable,
        series_id="TEST",
    )


def _cftc_payload() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "f_year.txt",
            "CFTC_Contract_Market_Code,Report_Date_as_YYYY-MM-DD,Open_Interest_All\n"
            "099741,2020-01-07,1000\n",
        )
    return buffer.getvalue()


def test_fred_csv_validation_records_coverage() -> None:
    payload = b"observation_date,TEST\n2020-01-01,1.5\n2020-01-02,.\n"
    metadata = downloader.validate_payload(payload, _fred_task())

    assert metadata == {
        "rows": 2,
        "non_missing_rows": 1,
        "first_observation": "2020-01-01",
        "last_observation": "2020-01-02",
    }


def test_fred_validator_rejects_html_and_duplicate_dates() -> None:
    with pytest.raises(ValueError, match="HTML"):
        downloader.validate_payload(b"<!DOCTYPE html><html></html>", _fred_task())

    duplicate = b"observation_date,TEST\n2020-01-01,1\n2020-01-01,2\n"
    with pytest.raises(ValueError, match="duplicate"):
        downloader.validate_payload(duplicate, _fred_task())


def test_cftc_zip_validation_checks_schema() -> None:
    task = downloader.DownloadTask(
        key="cftc:tff:2020",
        group="cftc",
        provider="cftc",
        title="CFTC test",
        url="https://www.cftc.gov/files/dea/history/fut_fin_txt_2020.zip",
        relative_path="cftc/tff/fut_fin_txt_2020.zip",
        validator="cftc_zip",
        research_eligibility="test_only",
        mutable=False,
        year=2020,
    )

    metadata = downloader.validate_payload(_cftc_payload(), task)

    assert metadata["archive_members"] == ["f_year.txt"]
    assert metadata["uncompressed_bytes"] > 0

    legacy = io.BytesIO()
    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "f_legacy.txt",
            "CFTC_Contract_Market_Code,Report_Date_as_MM_DD_YYYY,Open_Interest_All\n"
            "099741,01/07/2012,1000\n",
        )
    assert downloader.validate_payload(legacy.getvalue(), task)["uncompressed_bytes"] > 0


def test_download_is_atomic_and_cached_file_is_digest_checked(tmp_path, monkeypatch) -> None:
    payload = b"observation_date,TEST\n2020-01-01,1.5\n2020-01-02,2.0\n"
    calls = 0

    def fake_fetch(task, timeout, retries):
        nonlocal calls
        calls += 1
        return payload, {"content_type": "text/csv"}

    monkeypatch.setattr(downloader, "_fetch", fake_fetch)
    task = _fred_task(mutable=False)
    first = downloader.download_task(
        task,
        tmp_path,
        timeout=1,
        retries=0,
        refresh=False,
        skip_existing=False,
    )
    second = downloader.download_task(
        task,
        tmp_path,
        timeout=1,
        retries=0,
        refresh=False,
        skip_existing=False,
    )

    assert calls == 1
    assert first["status"] == "downloaded"
    assert second["status"] == "cached"
    metadata_path = tmp_path / "fred/risk/TEST.csv.meta.json"
    assert json.loads(metadata_path.read_text())["sha256"] == first["sha256"]

    (tmp_path / "fred/risk/TEST.csv").write_bytes(payload + b"2020-01-03,3\n")
    with pytest.raises(ValueError, match="metadata digest"):
        downloader.download_task(
            task,
            tmp_path,
            timeout=1,
            retries=0,
            refresh=False,
            skip_existing=False,
        )


def test_catalog_never_labels_reference_rates_as_ois() -> None:
    tasks = downloader.build_tasks(2020, 2021)
    rate_tasks = [task for task in tasks if task.group == "rates_reference"]

    assert len(rate_tasks) == 8
    assert all("not_ois" in task.research_eligibility for task in rate_tasks)
    assert all(task.url.startswith("https://fred.stlouisfed.org/") for task in rate_tasks)
    assert len([task for task in tasks if task.group == "cftc"]) == 2

    history = [task for task in downloader.build_tasks(2006, 2009) if task.group == "cftc"]
    assert [task.key for task in history] == ["cftc:tff:2006_2016"]
    assert history[0].url.endswith("fin_fut_txt_2006_2016.zip")
