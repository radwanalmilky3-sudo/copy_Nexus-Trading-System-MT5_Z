from __future__ import annotations

import importlib.util
import io
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "download_fx_supplemental_data.py"
SPEC = importlib.util.spec_from_file_location("fx_supplemental_downloader", SCRIPT_PATH)
assert SPEC and SPEC.loader
downloader = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = downloader
SPEC.loader.exec_module(downloader)


def _xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    return buffer.getvalue()


def _world_bank_payload() -> bytes:
    price_names = [
        "Crude oil, average",
        "Crude oil, WTI",
        "Coal, Australian",
        "Natural gas, Europe",
        "Aluminum",
        "Iron ore, cfr spot",
        "Copper",
        "Gold",
    ]
    index_names = [
        "Total Index",
        "Energy",
        "Agriculture **",
        "Food **",
        "Metals  & Minerals",
        "Base Metals (ex. iron ore)",
        "Precious Metals",
    ]

    def sheet(names: list[str]) -> pd.DataFrame:
        rows: list[list[object]] = [[None] * (len(names) + 1) for _ in range(10)]
        for column, name in enumerate(names, start=1):
            rows[4][column] = name
        for month in range(24):
            year = 2020 + month // 12
            period = f"{year}M{month % 12 + 1:02d}"
            rows.append([period, *[100.0 + month + column for column in range(len(names))]])
        return pd.DataFrame(rows)

    return _xlsx({"Monthly Prices": sheet(price_names), "Monthly Indices": sheet(index_names)})


def test_parsers_preserve_conservative_availability_and_source_roles() -> None:
    world_bank = downloader.parse_world_bank(
        _world_bank_payload(), "https://thedocs.worldbank.org/pink.xlsx"
    )
    assert len(world_bank) == 15 * 24
    assert {row["family"] for row in world_bank} == {"commodity"}

    dates = pd.date_range("2000-01-31", periods=120, freq="ME")
    gscpi_payload = _xlsx(
        {
            "GSCPI Monthly Data": pd.DataFrame(
                [["Date", "GSCPI"], *zip(dates, np.linspace(-1, 1, len(dates)), strict=True)]
            )
        }
    )
    gscpi = downloader.parse_gscpi(gscpi_payload, "https://newyorkfed.org/gscpi.xls")
    assert len(gscpi) == 120
    assert gscpi[0]["provider"] == "new_york_fed"

    gepu_payload = _xlsx(
        {
            "Sheet1": pd.DataFrame(
                [
                    ["Year", "Month", "GEPU_current", "GEPU_ppp"],
                    *[
                        [timestamp.year, timestamp.month, 100 + number, 110 + number]
                        for number, timestamp in enumerate(dates)
                    ],
                ]
            )
        }
    )
    gepu = downloader.parse_gepu(gepu_payload, "https://policyuncertainty.com/gepu.xlsx")
    assert len(gepu) == 240
    assert {row["series_id"] for row in gepu} == {"GEPU_CURRENT", "GEPU_PPP"}

    gpr_columns = [
        "month",
        "GPR",
        "GPRT",
        "GPRA",
        "GPRC_AUS",
        "GPRC_CAN",
        "GPRC_CHE",
        "GPRC_DEU",
        "GPRC_FRA",
        "GPRC_GBR",
        "GPRC_ITA",
        "GPRC_JPN",
        "GPRC_USA",
    ]
    gpr_dates = pd.date_range("2000-01-01", periods=90, freq="MS")
    gpr_payload = _xlsx(
        {
            "Sheet1": pd.DataFrame(
                [gpr_columns]
                + [
                    [timestamp, *[100 + number] * (len(gpr_columns) - 1)]
                    for number, timestamp in enumerate(gpr_dates)
                ]
            )
        }
    )
    gpr = downloader.parse_gpr(gpr_payload, "https://matteoiacoviello.com/gpr.xls")
    assert len(gpr) == 90 * 12
    assert {row["family"] for row in gpr} == {"geopolitical_risk"}

    combined = pd.DataFrame([*world_bank, *gscpi, *gepu, *gpr])
    observation = pd.to_datetime(combined["observation_time"], utc=True)
    available = pd.to_datetime(combined["available_time"], utc=True)
    assert (available > observation).all()
    assert set(combined["quality"]) == {"exploratory_current_vintage"}


def test_world_bank_discovery_rejects_nonofficial_download_host(monkeypatch) -> None:
    monkeypatch.setattr(
        downloader,
        "_fetch",
        lambda *_args: b'<a href="https://example.com/CMO-Historical-Data-Monthly.xlsx">x</a>',
    )

    with pytest.raises(ValueError, match="unexpected World Bank"):
        downloader.discover_world_bank_url(1.0, 0)


def test_gscpi_vintage_matrix_preserves_release_availability() -> None:
    dates = pd.date_range("1970-01-31", periods=600, freq="ME")
    frame = pd.DataFrame(
        {
            "Date": dates.strftime("%d-%b-%Y"),
            "Jan-22": np.linspace(-2, 2, len(dates)),
            "Feb-22": np.linspace(-1, 3, len(dates)),
        }
    )
    payload = frame.to_csv(index=False).encode()

    rows = downloader.parse_gscpi_vintages(payload, "https://newyorkfed.org/vintages.csv")
    result = pd.DataFrame(rows)

    assert len(result) == 1_200
    assert set(result["quality"]) == {"verified_monthly_vintage_from_2022"}
    assert set(result["vintage_label"]) == {"Jan-22", "Feb-22"}
    releases = result.groupby("vintage_label")["available_time"].first()
    assert releases["Jan-22"] == "2022-01-06T15:00:00+00:00"
    assert releases["Feb-22"] == "2022-02-04T15:00:00+00:00"


def test_normalized_writer_rejects_duplicate_observation_series_keys(tmp_path) -> None:
    row = downloader._record(
        observation_date=pd.Timestamp("2020-01-31").date(),
        lag_days=45,
        series_id="TEST",
        series_name="Test",
        value=1,
        unit="index",
        provider="test",
        family="test",
        source_url="https://example.com/test",
    )

    with pytest.raises(ValueError, match="duplicate"):
        downloader._write_normalized([row, row], tmp_path / "normalized.csv")


def test_official_current_vintage_parsers_use_snapshot_time_not_fake_release_lag() -> None:
    retrieved_at = datetime(2026, 7, 16, 8, 30, tzinfo=UTC)

    daily_dates = pd.date_range("2000-01-03", periods=1_001, freq="B")
    ofr_columns = [
        "OFR FSI",
        "Credit",
        "Equity valuation",
        "Safe assets",
        "Funding",
        "Volatility",
        "United States",
        "Other advanced economies",
        "Emerging markets",
    ]
    ofr_frame = pd.DataFrame({"Date": daily_dates.strftime("%Y-%m-%d")})
    for number, column in enumerate(ofr_columns):
        ofr_frame[column] = np.linspace(number, number + 1, len(daily_dates))
    ofr = downloader.parse_ofr_fsi(
        ofr_frame.to_csv(index=False).encode(),
        downloader.OFR_FSI_URL,
        retrieved_at=retrieved_at,
    )

    ciss_frame = pd.DataFrame(
        {
            "KEY": ["CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX"] * len(daily_dates),
            "FREQ": ["D"] * len(daily_dates),
            "TIME_PERIOD": daily_dates.strftime("%Y-%m-%d"),
            "OBS_VALUE": np.linspace(0, 1, len(daily_dates)),
        }
    )
    ciss = downloader.parse_ecb_ciss(
        ciss_frame.to_csv(index=False).encode(),
        downloader.ECB_CISS_URL,
        retrieved_at=retrieved_at,
    )

    monthly_dates = pd.date_range("2000-01-01", periods=144, freq="MS")
    bcpi_columns = ["M.BCPI", "M.BCNE", "M.ENER", "M.MTLS", "M.FOPR", "M.AGRI", "M.FISH"]
    bcpi_frame = pd.DataFrame({"date": monthly_dates.strftime("%Y-%m-%d")})
    for number, column in enumerate(bcpi_columns):
        bcpi_frame[column] = 100 + number + np.arange(len(monthly_dates))
    bcpi_payload = (
        '"TERMS AND CONDITIONS"\n"https://www.bankofcanada.ca/terms/"\n\n'
        '"OBSERVATIONS"\n' + bcpi_frame.to_csv(index=False)
    ).encode()
    bcpi = downloader.parse_boc_bcpi(
        bcpi_payload,
        downloader.BOC_BCPI_URL,
        retrieved_at=retrieved_at,
    )

    rba_series = [f"TEST{number:02d}" for number in range(12)]
    rba_rows: list[list[object]] = [
        ["I2 COMMODITY PRICES", *[None] * len(rba_series)],
        ["Title", *[f"Commodity series {number}" for number in range(12)]],
        ["Description", *[f"Description {number}" for number in range(12)]],
        ["Frequency", *["Monthly"] * len(rba_series)],
        ["Type", *["Original"] * len(rba_series)],
        ["Units", *["Index, test=100"] * len(rba_series)],
        [None, *[None] * len(rba_series)],
        [None, *[None] * len(rba_series)],
        ["Source", *["RBA"] * len(rba_series)],
        ["Publication date", *[pd.Timestamp("2026-07-01")] * len(rba_series)],
        ["Series ID", *rba_series],
    ]
    for number, timestamp in enumerate(pd.date_range("2000-01-31", periods=120, freq="ME")):
        rba_rows.append([timestamp, *[100 + number + column for column in range(12)]])
    rba = downloader.parse_rba_i2(
        _xlsx({"Data": pd.DataFrame(rba_rows)}),
        downloader.RBA_I2_URL,
        retrieved_at=retrieved_at,
    )

    combined = pd.DataFrame([*ofr, *ciss, *bcpi, *rba])
    assert len(ofr) == 9 * len(daily_dates)
    assert len(ciss) == len(daily_dates)
    assert len(bcpi) == 7 * len(monthly_dates)
    assert len(rba) == 12 * 120
    assert set(combined["available_time"]) == {retrieved_at.isoformat()}
    assert set(combined["quality"]) == {
        "exploratory_current_vintage_retrieved_snapshot"
    }
    assert {"daily", "monthly"}.issubset(set(combined["frequency"]))


def test_cboe_fx_volatility_is_a_retrieval_snapshot_not_otc_vrp() -> None:
    retrieved_at = datetime(2026, 7, 16, 8, 30, tzinfo=UTC)
    dates = pd.bdate_range("2020-01-02", periods=600)
    payload = pd.DataFrame(
        {
            "DATE": dates.strftime("%m/%d/%Y"),
            "EVZ": np.linspace(7.0, 18.0, len(dates)),
        }
    ).to_csv(index=False).encode()

    rows = downloader.parse_cboe_fx_volatility(
        payload,
        downloader.CBOE_FX_VOLATILITY_INDICES["EVZ"][2],
        index_symbol="EVZ",
        series_id="CBOE_EVZ_30D",
        series_name="Cboe EuroCurrency Volatility Index",
        retrieved_at=retrieved_at,
    )
    frame = pd.DataFrame(rows)

    assert len(frame) == 600
    assert set(frame["available_time"]) == {retrieved_at.isoformat()}
    assert set(frame["quality"]) == {
        "exploratory_current_vintage_retrieved_snapshot"
    }
    assert set(frame["family"]) == {"fx_implied_volatility_state"}
    assert set(frame["unit"]) == {"VIX-style index points"}
    assert set(frame["series_id"]) == {"CBOE_EVZ_30D"}

    wrong_column = payload.replace(b"EVZ", b"EUVIX", 1)
    with pytest.raises(ValueError, match="unexpected schema"):
        downloader.parse_cboe_fx_volatility(
            wrong_column,
            downloader.CBOE_FX_VOLATILITY_INDICES["EVZ"][2],
            index_symbol="EVZ",
            series_id="CBOE_EVZ_30D",
            series_name="Cboe EuroCurrency Volatility Index",
            retrieved_at=retrieved_at,
        )


def test_snapshot_record_rejects_future_observation() -> None:
    with pytest.raises(ValueError, match="not earlier"):
        downloader._snapshot_record(
            observation_date=pd.Timestamp("2026-07-17").date(),
            retrieved_at=datetime(2026, 7, 16, tzinfo=UTC),
            series_id="TEST",
            series_name="Test",
            value=1,
            unit="index",
            frequency="daily",
            provider="test",
            family="test",
            source_url="https://example.com/test",
        )


def test_raw_snapshot_archive_is_content_verified_and_time_versioned(tmp_path) -> None:
    first_time = datetime(2026, 7, 16, 8, 30, tzinfo=UTC)
    second_time = datetime(2026, 7, 17, 8, 30, tzinfo=UTC)

    first = downloader._archive_snapshot(
        tmp_path,
        key="test_source",
        relative_path="raw/test.csv",
        payload=b"date,value\n2026-07-15,1\n",
        retrieved_at=first_time,
    )
    same = downloader._archive_snapshot(
        tmp_path,
        key="test_source",
        relative_path="raw/test.csv",
        payload=b"date,value\n2026-07-15,1\n",
        retrieved_at=first_time,
    )
    second = downloader._archive_snapshot(
        tmp_path,
        key="test_source",
        relative_path="raw/test.csv",
        payload=b"date,value\n2026-07-15,2\n",
        retrieved_at=second_time,
    )

    assert same == first
    assert first != second
    assert first.read_bytes().endswith(b",1\n")
    assert second.read_bytes().endswith(b",2\n")
    assert first.parent.name == "2026"
