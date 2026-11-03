from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_downloader():
    path = Path(__file__).parents[1] / "scripts" / "download_official_fx_rates.py"
    spec = importlib.util.spec_from_file_location("download_official_fx_rates", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


downloader = _load_downloader()


def test_official_overnight_parsers_never_mark_rates_as_ois() -> None:
    nyfed = downloader.parse_nyfed(
        json.dumps(
            {
                "refRates": [
                    {
                        "effectiveDate": "2025-01-02",
                        "type": "SOFR",
                        "percentRate": 4.4,
                    }
                ]
            }
        ).encode(),
        "https://example.test/sofr",
    )
    ecb = downloader.parse_ecb(
        b"TIME_PERIOD,OBS_VALUE\n2025-01-02,2.9\n",
        "https://example.test/estr",
        currency="EUR",
        series_id="ESTR",
        series_name="Euro short-term rate",
        role="overnight_reference",
        tenor="ON",
    )
    boc = downloader.parse_boc(
        json.dumps(
            {"observations": [{"d": "2025-01-02", "AVG.INTWO": {"v": "3.2"}}]}
        ).encode(),
        "https://example.test/corra",
        source_series="AVG.INTWO",
        series_id="CORRA",
        series_name="Canadian Overnight Repo Rate Average",
        role="overnight_reference",
        tenor="ON",
    )

    assert {row["series_id"] for row in [*nyfed, *ecb, *boc]} == {
        "SOFR",
        "ESTR",
        "CORRA",
    }
    assert all(row["series_role"] == "overnight_reference" for row in [*nyfed, *ecb, *boc])
    assert all(row["is_ois"] is False for row in [*nyfed, *ecb, *boc])


def test_boe_parser_preserves_sonia_and_policy_roles() -> None:
    payload = b"DATE,IUDSOIA,IUDBEDR\n02 Jan 2025,4.75,4.75\n"

    rows = downloader.parse_boe(payload, "https://example.test/boe")

    roles = {row["series_id"]: row["series_role"] for row in rows}
    assert roles == {"SONIA": "overnight_reference", "BANK_RATE": "policy_rate"}
    assert all(row["available_time"].startswith("2025-01-03") for row in rows)


def test_rba_parser_marks_only_explicit_ois_columns() -> None:
    payload = """F1 INTEREST RATES AND YIELDS – MONEY MARKET
Title,Cash,Overnight,OIS 1M,OIS 3M
Series ID,FIRMMCRTD,FIRMMCRID,FIRMMOIS1D,FIRMMOIS3D
02-Jan-2025,4.35,4.34,4.30,4.20
""".encode()

    rows = downloader.parse_rba(payload, "https://example.test/rba")

    ois = [row for row in rows if row["is_ois"]]
    non_ois = [row for row in rows if not row["is_ois"]]
    assert {row["tenor"] for row in ois} == {"1M", "3M"}
    assert {row["series_role"] for row in ois} == {"ois"}
    assert {row["series_id"] for row in non_ois} == {"CASH_RATE_TARGET", "AONIA"}


def test_snb_parser_handles_metadata_preamble_and_secondary_tona() -> None:
    payload = b"""CubeId;zimoma
PublishingDate;2025-03-01 14:30

Date;D0;Value
2025-01;SARON;0.45
2025-01;1TGT;0.50
2025-01;TONA;0.23
"""

    rows = downloader.parse_snb(payload, "https://example.test/snb")

    by_series = {row["series_id"]: row for row in rows}
    assert by_series["SARON"]["quality"] == "official_primary_monthly"
    assert by_series["TONA_MONTHLY"]["currency"] == "JPY"
    assert by_series["TONA_MONTHLY"]["quality"] == "official_secondary_monthly_republication"
    assert all(row["frequency"] == "monthly" for row in rows)
