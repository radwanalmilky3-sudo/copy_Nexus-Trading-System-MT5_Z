#!/usr/bin/env python3
"""Archive and normalize free supplemental data for exploratory FX research.

The sources cover commodity prices, global supply-chain pressure, economic-policy
uncertainty, and geopolitical risk. They are current-vintage downloads, not
revision-aware point-in-time archives. Conservative availability lags prevent
obvious same-month look-ahead but do not make revised history suitable for strict
factor promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

PROGRAM_VERSION = "fx-supplemental-data-v4"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
QUALITY = "exploratory_current_vintage"
SNAPSHOT_QUALITY = "exploratory_current_vintage_retrieved_snapshot"

WORLD_BANK_PAGE = "https://www.worldbank.org/en/research/commodity-markets"
WORLD_BANK_LINK_PATTERN = re.compile(
    r'href=["\']([^"\']*CMO-Historical-Data-Monthly\.xlsx)["\']', re.IGNORECASE
)
GSCPI_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "gscpi/downloads/gscpi_data.csv"
)
GSCPI_VINTAGE_URL = (
    "https://www.newyorkfed.org/medialibrary/research/interactives/"
    "data/gscpi/gscpi_interactive_data.csv"
)
GEPU_URL = "https://www.policyuncertainty.com/media/Global_Policy_Uncertainty_Data.xlsx"
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
OFR_FSI_URL = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
ECB_CISS_URL = (
    "https://data-api.ecb.europa.eu/service/data/"
    "CISS/D.U2.Z0Z.4F.EC.SS_CIN.IDX?format=csvdata"
)
BOC_BCPI_URL = (
    "https://www.bankofcanada.ca/valet/observations/group/"
    "BCPI_MONTHLY/csv?start_date=1972-01-01"
)
RBA_I2_URL = "https://www.rba.gov.au/statistics/tables/xls/i02hist.xlsx"
CBOE_FX_VOLATILITY_INDICES = {
    "EVZ": (
        "CBOE_EVZ_30D",
        "Cboe EuroCurrency Volatility Index",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/EVZ_History.csv",
    ),
    "EUVIX": (
        "CBOE_EUVIX_30D",
        "Cboe/CME FX Euro Volatility Index",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/EUVIX_History.csv",
    ),
    "JYVIX": (
        "CBOE_JYVIX_30D",
        "Cboe/CME FX Yen Volatility Index",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/JYVIX_History.csv",
    ),
    "BPVIX": (
        "CBOE_BPVIX_30D",
        "Cboe/CME FX British Pound Volatility Index",
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/BPVIX_History.csv",
    ),
}

NORMALIZED_COLUMNS = [
    "observation_time",
    "available_time",
    "series_id",
    "series_name",
    "value",
    "unit",
    "frequency",
    "provider",
    "family",
    "quality",
    "source_url",
]
GSCPI_VINTAGE_COLUMNS = [
    "observation_time",
    "available_time",
    "vintage_label",
    "series_id",
    "value",
    "provider",
    "quality",
    "source_url",
]


@dataclass(frozen=True)
class Source:
    key: str
    url: str
    relative_path: str
    parser: Callable[[bytes, str], list[dict[str, object]]]
    snapshot_availability: bool = False


def _finite(value: object, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"non-finite {label}: {value!r}")
    return number


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _record(
    *,
    observation_date: date,
    lag_days: int,
    series_id: str,
    series_name: str,
    value: object,
    unit: str,
    provider: str,
    family: str,
    source_url: str,
) -> dict[str, object]:
    observation = datetime.combine(observation_date, datetime.min.time(), tzinfo=UTC)
    available = observation + timedelta(days=lag_days)
    return {
        "observation_time": observation.isoformat(),
        "available_time": available.isoformat(),
        "series_id": series_id,
        "series_name": series_name,
        "value": _finite(value, series_id),
        "unit": unit,
        "frequency": "monthly",
        "provider": provider,
        "family": family,
        "quality": QUALITY,
        "source_url": source_url,
    }


def _snapshot_record(
    *,
    observation_date: date,
    retrieved_at: datetime,
    series_id: str,
    series_name: str,
    value: object,
    unit: str,
    frequency: str,
    provider: str,
    family: str,
    source_url: str,
) -> dict[str, object]:
    """Represent a current-vintage snapshot without inventing historical releases."""
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    available = retrieved_at.astimezone(UTC)
    observation = datetime.combine(observation_date, datetime.min.time(), tzinfo=UTC)
    if observation >= available:
        raise ValueError(f"{series_id}: observation is not earlier than snapshot retrieval")
    return {
        "observation_time": observation.isoformat(),
        "available_time": available.isoformat(),
        "series_id": series_id,
        "series_name": series_name,
        "value": _finite(value, series_id),
        "unit": unit,
        "frequency": frequency,
        "provider": provider,
        "family": family,
        "quality": SNAPSHOT_QUALITY,
        "source_url": source_url,
    }


def _excel_engine(payload: bytes) -> str:
    return "openpyxl" if payload.startswith(b"PK") else "xlrd"


def _read_excel(payload: bytes, **kwargs: Any) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(payload), engine=_excel_engine(payload), **kwargs)


def _period_rows(frame: pd.DataFrame) -> list[tuple[int, int, int]]:
    output: list[tuple[int, int, int]] = []
    for row_number, raw in frame.iloc[:, 0].items():
        match = re.fullmatch(r"(\d{4})M(\d{2})", str(raw).strip())
        if match:
            output.append((int(row_number), int(match.group(1)), int(match.group(2))))
    if len(output) < 24:
        raise ValueError("World Bank workbook contains too few monthly periods")
    return output


def _find_header_column(frame: pd.DataFrame, expected: str) -> int:
    for column in range(1, frame.shape[1]):
        for row in range(min(10, frame.shape[0])):
            if str(frame.iloc[row, column]).strip() == expected:
                return column
    raise ValueError(f"World Bank workbook is missing {expected!r}")


def parse_world_bank(payload: bytes, source_url: str) -> list[dict[str, object]]:
    prices = _read_excel(payload, sheet_name="Monthly Prices", header=None)
    indices = _read_excel(payload, sheet_name="Monthly Indices", header=None)
    price_series = {
        "Crude oil, average": ("WB_CRUDE_OIL_AVG", "Crude oil average", "USD per barrel"),
        "Crude oil, WTI": ("WB_CRUDE_OIL_WTI", "Crude oil WTI", "USD per barrel"),
        "Coal, Australian": ("WB_COAL_AU", "Australian coal", "USD per metric ton"),
        "Natural gas, Europe": (
            "WB_NATURAL_GAS_EU",
            "European natural gas",
            "USD per MMBtu",
        ),
        "Aluminum": ("WB_ALUMINUM", "Aluminum", "USD per metric ton"),
        "Iron ore, cfr spot": ("WB_IRON_ORE", "Iron ore CFR spot", "USD per dmtu"),
        "Copper": ("WB_COPPER", "Copper", "USD per metric ton"),
        "Gold": ("WB_GOLD", "Gold", "USD per troy ounce"),
    }
    index_series = {
        "Total Index": ("WB_COMMODITY_TOTAL", "World Bank total commodity index"),
        "Energy": ("WB_COMMODITY_ENERGY", "World Bank energy index"),
        "Agriculture **": ("WB_COMMODITY_AGRICULTURE", "World Bank agriculture index"),
        "Food **": ("WB_COMMODITY_FOOD", "World Bank food index"),
        "Metals  & Minerals": (
            "WB_COMMODITY_METALS_MINERALS",
            "World Bank metals and minerals index",
        ),
        "Base Metals (ex. iron ore)": (
            "WB_COMMODITY_BASE_METALS",
            "World Bank base metals index excluding iron ore",
        ),
        "Precious Metals": (
            "WB_COMMODITY_PRECIOUS_METALS",
            "World Bank precious metals index",
        ),
    }
    output: list[dict[str, object]] = []
    for frame, definitions, unit in (
        (prices, price_series, None),
        (indices, index_series, "2010=100"),
    ):
        periods = _period_rows(frame)
        for source_name, definition in definitions.items():
            column = _find_header_column(frame, source_name)
            series_id, series_name, *explicit_unit = definition
            target_unit = explicit_unit[0] if explicit_unit else str(unit)
            non_missing = 0
            for row_number, year, month in periods:
                value = frame.iloc[row_number, column]
                if pd.isna(value) or str(value).strip() in {"", ".", "...", "…"}:
                    continue
                output.append(
                    _record(
                        observation_date=_month_end(year, month),
                        lag_days=45,
                        series_id=series_id,
                        series_name=series_name,
                        value=value,
                        unit=target_unit,
                        provider="world_bank_pink_sheet",
                        family="commodity",
                        source_url=source_url,
                    )
                )
                non_missing += 1
            if non_missing < 24:
                raise ValueError(f"World Bank {source_name!r} has too few observations")
    return output


def parse_gscpi(payload: bytes, source_url: str) -> list[dict[str, object]]:
    frame = _read_excel(payload, sheet_name="GSCPI Monthly Data")
    if not {"Date", "GSCPI"}.issubset(frame.columns):
        raise ValueError("NY Fed GSCPI workbook has an unexpected schema")
    output = []
    for _, item in frame.dropna(subset=["Date", "GSCPI"]).iterrows():
        timestamp = pd.to_datetime(item["Date"], errors="coerce")
        if pd.isna(timestamp):
            raise ValueError("NY Fed GSCPI workbook contains an invalid date")
        output.append(
            _record(
                observation_date=_month_end(timestamp.year, timestamp.month),
                lag_days=45,
                series_id="GSCPI",
                series_name="Global Supply Chain Pressure Index",
                value=item["GSCPI"],
                unit="standard deviations",
                provider="new_york_fed",
                family="supply_chain_pressure",
                source_url=source_url,
            )
        )
    if len(output) < 120:
        raise ValueError("NY Fed GSCPI workbook contains too few observations")
    return output


def _gscpi_release_time(vintage: pd.Timestamp) -> datetime:
    first = pd.Timestamp(year=vintage.year, month=vintage.month, day=1)
    fourth_business_day = pd.date_range(
        first,
        periods=4,
        freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()),
    )[-1]
    local = datetime(
        fourth_business_day.year,
        fourth_business_day.month,
        fourth_business_day.day,
        10,
        tzinfo=ZoneInfo("America/New_York"),
    )
    return local.astimezone(UTC)


def parse_gscpi_vintages(payload: bytes, source_url: str) -> list[dict[str, object]]:
    try:
        frame = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError) as error:
        raise ValueError("NY Fed GSCPI vintage response is not valid CSV") from error
    if len(frame.columns) < 2 or frame.columns[0] != "Date":
        raise ValueError("NY Fed GSCPI vintage CSV has an unexpected schema")
    observations = pd.to_datetime(frame["Date"], errors="coerce", dayfirst=True)
    if observations.isna().any() or observations.duplicated().any():
        raise ValueError("NY Fed GSCPI vintage CSV has invalid observation dates")
    output: list[dict[str, object]] = []
    for vintage_label in frame.columns[1:]:
        vintage = pd.to_datetime(vintage_label, format="%b-%y", errors="coerce")
        if pd.isna(vintage):
            raise ValueError(f"invalid GSCPI vintage label: {vintage_label!r}")
        available = _gscpi_release_time(vintage)
        for observation, value in zip(observations, frame[vintage_label], strict=True):
            if pd.isna(value):
                continue
            observation_time = datetime.combine(
                observation.date(), datetime.min.time(), tzinfo=UTC
            )
            if observation_time >= available:
                raise ValueError(
                    f"GSCPI vintage {vintage_label} contains a future observation"
                )
            output.append(
                {
                    "observation_time": observation_time.isoformat(),
                    "available_time": available.isoformat(),
                    "vintage_label": vintage_label,
                    "series_id": "GSCPI",
                    "value": _finite(value, f"GSCPI {vintage_label}"),
                    "provider": "new_york_fed",
                    "quality": "verified_monthly_vintage_from_2022",
                    "source_url": source_url,
                }
            )
    if len(output) < 1_000:
        raise ValueError("NY Fed GSCPI vintage CSV contains too few observations")
    return output


def parse_gepu(payload: bytes, source_url: str) -> list[dict[str, object]]:
    frame = _read_excel(payload, sheet_name="Sheet1")
    required = {"Year", "Month", "GEPU_current", "GEPU_ppp"}
    if not required.issubset(frame.columns):
        raise ValueError("Global EPU workbook has an unexpected schema")
    definitions = {
        "GEPU_current": ("GEPU_CURRENT", "Global EPU current-price GDP weights"),
        "GEPU_ppp": ("GEPU_PPP", "Global EPU PPP-adjusted GDP weights"),
    }
    output = []
    valid = frame.dropna(subset=["Year", "Month"])
    for _, item in valid.iterrows():
        year, month = int(item["Year"]), int(item["Month"])
        for column, (series_id, series_name) in definitions.items():
            if pd.isna(item[column]):
                continue
            output.append(
                _record(
                    observation_date=_month_end(year, month),
                    lag_days=60,
                    series_id=series_id,
                    series_name=series_name,
                    value=item[column],
                    unit="index",
                    provider="policyuncertainty_com",
                    family="policy_uncertainty",
                    source_url=source_url,
                )
            )
    if len(output) < 240:
        raise ValueError("Global EPU workbook contains too few observations")
    return output


def parse_gpr(payload: bytes, source_url: str) -> list[dict[str, object]]:
    frame = _read_excel(payload, sheet_name="Sheet1")
    global_definitions = {
        "GPR": ("GPR_GLOBAL", "Global geopolitical risk"),
        "GPRT": ("GPR_THREATS", "Global geopolitical threats"),
        "GPRA": ("GPR_ACTS", "Global geopolitical acts"),
    }
    country_definitions = {
        "GPRC_AUS": ("GPR_AUS", "Australia geopolitical risk"),
        "GPRC_CAN": ("GPR_CAN", "Canada geopolitical risk"),
        "GPRC_CHE": ("GPR_CHE", "Switzerland geopolitical risk"),
        "GPRC_DEU": ("GPR_DEU", "Germany geopolitical risk"),
        "GPRC_FRA": ("GPR_FRA", "France geopolitical risk"),
        "GPRC_GBR": ("GPR_GBR", "United Kingdom geopolitical risk"),
        "GPRC_ITA": ("GPR_ITA", "Italy geopolitical risk"),
        "GPRC_JPN": ("GPR_JPN", "Japan geopolitical risk"),
        "GPRC_USA": ("GPR_USA", "United States geopolitical risk"),
    }
    definitions = {**global_definitions, **country_definitions}
    required = {"month", *definitions}
    if not required.issubset(frame.columns):
        raise ValueError("GPR workbook has an unexpected schema")
    output = []
    for _, item in frame.dropna(subset=["month"]).iterrows():
        timestamp = pd.to_datetime(item["month"], errors="coerce")
        if pd.isna(timestamp):
            raise ValueError("GPR workbook contains an invalid month")
        for column, (series_id, series_name) in definitions.items():
            if pd.isna(item[column]):
                continue
            output.append(
                _record(
                    observation_date=_month_end(timestamp.year, timestamp.month),
                    lag_days=60,
                    series_id=series_id,
                    series_name=series_name,
                    value=item[column],
                    unit="index",
                    provider="caldara_iacoviello_gpr",
                    family="geopolitical_risk",
                    source_url=source_url,
                )
            )
    if len(output) < 1_000:
        raise ValueError("GPR workbook contains too few observations")
    return output


def parse_ofr_fsi(
    payload: bytes,
    source_url: str,
    *,
    retrieved_at: datetime | None = None,
) -> list[dict[str, object]]:
    try:
        frame = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError) as error:
        raise ValueError("OFR FSI response is not valid CSV") from error
    definitions = {
        "OFR FSI": ("OFR_FSI", "OFR Financial Stress Index"),
        "Credit": ("OFR_FSI_CREDIT", "OFR FSI credit component"),
        "Equity valuation": (
            "OFR_FSI_EQUITY_VALUATION",
            "OFR FSI equity-valuation component",
        ),
        "Safe assets": ("OFR_FSI_SAFE_ASSETS", "OFR FSI safe-assets component"),
        "Funding": ("OFR_FSI_FUNDING", "OFR FSI funding component"),
        "Volatility": ("OFR_FSI_VOLATILITY", "OFR FSI volatility component"),
        "United States": ("OFR_FSI_US", "OFR FSI United States contribution"),
        "Other advanced economies": (
            "OFR_FSI_OTHER_ADVANCED",
            "OFR FSI other-advanced-economies contribution",
        ),
        "Emerging markets": (
            "OFR_FSI_EMERGING",
            "OFR FSI emerging-markets contribution",
        ),
    }
    required = {"Date", *definitions}
    if not required.issubset(frame.columns):
        raise ValueError("OFR FSI CSV has an unexpected schema")
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("OFR FSI CSV has invalid or duplicate dates")
    snapshot_time = retrieved_at or datetime.now(UTC)
    output: list[dict[str, object]] = []
    for row_number, timestamp in dates.items():
        for column, (series_id, series_name) in definitions.items():
            value = frame.at[row_number, column]
            if pd.isna(value):
                continue
            output.append(
                _snapshot_record(
                    observation_date=timestamp.date(),
                    retrieved_at=snapshot_time,
                    series_id=series_id,
                    series_name=series_name,
                    value=value,
                    unit="index contribution",
                    frequency="daily",
                    provider="office_of_financial_research",
                    family="financial_stress",
                    source_url=source_url,
                )
            )
    if len(output) < 9_000:
        raise ValueError("OFR FSI CSV contains too few observations")
    return output


def parse_ecb_ciss(
    payload: bytes,
    source_url: str,
    *,
    retrieved_at: datetime | None = None,
) -> list[dict[str, object]]:
    try:
        frame = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig")
    except (UnicodeDecodeError, pd.errors.ParserError) as error:
        raise ValueError("ECB CISS response is not valid CSV") from error
    required = {"KEY", "FREQ", "TIME_PERIOD", "OBS_VALUE"}
    if not required.issubset(frame.columns):
        raise ValueError("ECB CISS CSV has an unexpected schema")
    expected_key = "CISS.D.U2.Z0Z.4F.EC.SS_CIN.IDX"
    if set(frame["KEY"].dropna()) != {expected_key} or set(frame["FREQ"].dropna()) != {"D"}:
        raise ValueError("ECB CISS CSV contains an unexpected series")
    dates = pd.to_datetime(frame["TIME_PERIOD"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("ECB CISS CSV has invalid or duplicate dates")
    snapshot_time = retrieved_at or datetime.now(UTC)
    output = [
        _snapshot_record(
            observation_date=timestamp.date(),
            retrieved_at=snapshot_time,
            series_id="ECB_CISS",
            series_name="ECB Composite Indicator of Systemic Stress",
            value=value,
            unit="index",
            frequency="daily",
            provider="european_central_bank",
            family="financial_stress",
            source_url=source_url,
        )
        for timestamp, value in zip(dates, frame["OBS_VALUE"], strict=True)
        if not pd.isna(value)
    ]
    if len(output) < 1_000:
        raise ValueError("ECB CISS CSV contains too few observations")
    return output


def parse_boc_bcpi(
    payload: bytes,
    source_url: str,
    *,
    retrieved_at: datetime | None = None,
) -> list[dict[str, object]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Bank of Canada BCPI response is not UTF-8") from error
    lines = text.splitlines()
    markers = [
        number
        for number, line in enumerate(lines)
        if line.strip().strip('"') == "OBSERVATIONS"
    ]
    if len(markers) != 1 or markers[0] + 2 >= len(lines):
        raise ValueError("Bank of Canada BCPI CSV is missing OBSERVATIONS")
    try:
        frame = pd.read_csv(io.StringIO("\n".join(lines[markers[0] + 1 :])))
    except pd.errors.ParserError as error:
        raise ValueError("Bank of Canada BCPI observations are invalid CSV") from error
    definitions = {
        "M.BCPI": ("BOC_BCPI_TOTAL", "Bank of Canada commodity price index total"),
        "M.BCNE": ("BOC_BCPI_EX_ENERGY", "Bank of Canada BCPI excluding energy"),
        "M.ENER": ("BOC_BCPI_ENERGY", "Bank of Canada BCPI energy"),
        "M.MTLS": ("BOC_BCPI_METALS", "Bank of Canada BCPI metals and minerals"),
        "M.FOPR": ("BOC_BCPI_FORESTRY", "Bank of Canada BCPI forestry"),
        "M.AGRI": ("BOC_BCPI_AGRICULTURE", "Bank of Canada BCPI agriculture"),
        "M.FISH": ("BOC_BCPI_FISH", "Bank of Canada BCPI fish"),
    }
    required = {"date", *definitions}
    if not required.issubset(frame.columns):
        raise ValueError("Bank of Canada BCPI CSV has an unexpected schema")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("Bank of Canada BCPI CSV has invalid or duplicate dates")
    snapshot_time = retrieved_at or datetime.now(UTC)
    output: list[dict[str, object]] = []
    for row_number, timestamp in dates.items():
        for column, (series_id, series_name) in definitions.items():
            value = frame.at[row_number, column]
            if pd.isna(value):
                continue
            output.append(
                _snapshot_record(
                    observation_date=timestamp.date(),
                    retrieved_at=snapshot_time,
                    series_id=series_id,
                    series_name=series_name,
                    value=value,
                    unit="index (January 1972=100)",
                    frequency="monthly",
                    provider="bank_of_canada",
                    family="commodity",
                    source_url=source_url,
                )
            )
    if len(output) < 1_000:
        raise ValueError("Bank of Canada BCPI CSV contains too few observations")
    return output


def parse_rba_i2(
    payload: bytes,
    source_url: str,
    *,
    retrieved_at: datetime | None = None,
) -> list[dict[str, object]]:
    frame = _read_excel(payload, sheet_name="Data", header=None)
    labels = frame.iloc[:, 0].astype(str).str.strip()
    series_rows = labels[labels == "Series ID"].index.tolist()
    if len(series_rows) != 1:
        raise ValueError("RBA I2 workbook is missing a unique Series ID row")
    series_row = int(series_rows[0])
    metadata_rows: dict[str, int] = {}
    for label in ("Title", "Description", "Frequency", "Units"):
        matches = labels[labels == label].index.tolist()
        if len(matches) != 1 or int(matches[0]) >= series_row:
            raise ValueError(f"RBA I2 workbook is missing metadata row {label!r}")
        metadata_rows[label] = int(matches[0])

    definitions: list[tuple[int, str, str, str]] = []
    for column in range(1, frame.shape[1]):
        raw_series_id = frame.iloc[series_row, column]
        if pd.isna(raw_series_id) or not str(raw_series_id).strip():
            continue
        source_series_id = str(raw_series_id).strip()
        if not re.fullmatch(r"[A-Z0-9_]+", source_series_id):
            raise ValueError(f"RBA I2 workbook has invalid Series ID {source_series_id!r}")
        title = str(frame.iloc[metadata_rows["Title"], column]).strip()
        description = str(frame.iloc[metadata_rows["Description"], column]).strip()
        frequency = str(frame.iloc[metadata_rows["Frequency"], column]).strip()
        unit = str(frame.iloc[metadata_rows["Units"], column]).strip()
        if frequency != "Monthly" or not title or not description or not unit:
            raise ValueError(f"RBA I2 metadata is incomplete for {source_series_id}")
        definitions.append(
            (
                column,
                f"RBA_{source_series_id}",
                f"{title}: {description}",
                unit,
            )
        )
    if len(definitions) < 10:
        raise ValueError("RBA I2 workbook contains too few commodity series")

    snapshot_time = retrieved_at or datetime.now(UTC)
    output: list[dict[str, object]] = []
    seen_dates: set[date] = set()
    for row_number in range(series_row + 1, frame.shape[0]):
        raw_date = frame.iloc[row_number, 0]
        timestamp = pd.to_datetime(raw_date, errors="coerce")
        if pd.isna(timestamp):
            continue
        observation_date = timestamp.date()
        if observation_date in seen_dates:
            raise ValueError("RBA I2 workbook contains duplicate observation dates")
        seen_dates.add(observation_date)
        for column, series_id, series_name, unit in definitions:
            value = frame.iloc[row_number, column]
            if pd.isna(value):
                continue
            output.append(
                _snapshot_record(
                    observation_date=observation_date,
                    retrieved_at=snapshot_time,
                    series_id=series_id,
                    series_name=series_name,
                    value=value,
                    unit=unit,
                    frequency="monthly",
                    provider="reserve_bank_of_australia",
                    family="commodity",
                    source_url=source_url,
                )
            )
    if len(output) < 1_000:
        raise ValueError("RBA I2 workbook contains too few observations")
    return output


def parse_cboe_fx_volatility(
    payload: bytes,
    source_url: str,
    *,
    index_symbol: str,
    series_id: str,
    series_name: str,
    retrieved_at: datetime | None = None,
) -> list[dict[str, object]]:
    """Normalize one Cboe currency-volatility history as a retrieval snapshot.

    Cboe publishes the current full history, not a release-by-release vintage
    archive.  Historical rows therefore become available to strict forward use
    only at this project's retrieval time.  These are 30-day VIX-style indices,
    not one-year OTC implied volatility, risk reversals, or executable options.
    """

    if index_symbol not in CBOE_FX_VOLATILITY_INDICES:
        raise ValueError(f"unsupported Cboe FX volatility index {index_symbol!r}")
    try:
        frame = pd.read_csv(io.BytesIO(payload))
    except (UnicodeDecodeError, pd.errors.ParserError) as error:
        raise ValueError("Cboe FX volatility response is not valid CSV") from error
    if list(frame.columns) != ["DATE", index_symbol]:
        raise ValueError(
            f"Cboe {index_symbol} CSV has an unexpected schema {list(frame.columns)!r}"
        )
    dates = pd.to_datetime(frame["DATE"], format="%m/%d/%Y", errors="coerce")
    values = pd.to_numeric(frame[index_symbol], errors="coerce")
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError(f"Cboe {index_symbol} CSV has invalid, duplicate, or unsorted dates")
    if values.isna().any() or not values.map(math.isfinite).all() or (values <= 0).any():
        raise ValueError(f"Cboe {index_symbol} CSV has invalid index values")
    if len(frame) < 500:
        raise ValueError(f"Cboe {index_symbol} CSV contains too few observations")

    snapshot_time = retrieved_at or datetime.now(UTC)
    return [
        _snapshot_record(
            observation_date=timestamp.date(),
            retrieved_at=snapshot_time,
            series_id=series_id,
            series_name=series_name,
            value=value,
            unit="VIX-style index points",
            frequency="daily",
            provider="cboe_global_indices",
            family="fx_implied_volatility_state",
            source_url=source_url,
        )
        for timestamp, value in zip(dates, values, strict=True)
    ]


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _archive_snapshot(
    root: Path,
    *,
    key: str,
    relative_path: str,
    payload: bytes,
    retrieved_at: datetime,
) -> Path:
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("snapshot retrieved_at must be timezone-aware")
    timestamp = retrieved_at.astimezone(UTC)
    digest = hashlib.sha256(payload).hexdigest()
    suffixes = "".join(Path(relative_path).suffixes) or ".bin"
    filename = f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}_{digest[:16]}{suffixes}"
    destination = root / "archive" / key / f"{timestamp.year:04d}" / filename
    if destination.exists():
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise ValueError(f"archived snapshot digest mismatch: {destination}")
    else:
        _atomic_write(destination, payload)
    return destination


def _fetch(url: str, timeout: float, retries: int) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": f"{PROGRAM_VERSION} (+public research archive)"}
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > MAX_RESPONSE_BYTES:
                    raise ValueError("supplemental response exceeds declared size limit")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if not payload or len(payload) > MAX_RESPONSE_BYTES:
                    raise ValueError("supplemental response is empty or oversized")
                return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def discover_world_bank_url(timeout: float, retries: int) -> str:
    html = _fetch(WORLD_BANK_PAGE, timeout, retries).decode("utf-8", errors="strict")
    matches = WORLD_BANK_LINK_PATTERN.findall(html)
    if not matches:
        raise ValueError("World Bank commodity page contains no monthly Pink Sheet link")
    url = urllib.parse.urljoin(WORLD_BANK_PAGE, matches[0])
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "thedocs.worldbank.org":
        raise ValueError(f"unexpected World Bank Pink Sheet URL: {url}")
    return url


def _write_normalized(rows: list[dict[str, object]], path: Path) -> str:
    frame = pd.DataFrame(rows, columns=NORMALIZED_COLUMNS)
    if frame.empty or frame.duplicated(["observation_time", "series_id"]).any():
        raise ValueError("normalized supplemental data is empty or contains duplicate keys")
    frame = frame.sort_values(["observation_time", "series_id"]).reset_index(drop=True)
    encoded = frame.to_csv(index=False).encode("utf-8")
    _atomic_write(path, encoded)
    return hashlib.sha256(encoded).hexdigest()


def _write_gscpi_vintages(rows: list[dict[str, object]], path: Path) -> str:
    frame = pd.DataFrame(rows, columns=GSCPI_VINTAGE_COLUMNS)
    key = ["observation_time", "available_time", "series_id"]
    if frame.empty or frame.duplicated(key).any():
        raise ValueError("GSCPI vintage data is empty or contains duplicate keys")
    frame = frame.sort_values(["available_time", "observation_time"]).reset_index(drop=True)
    encoded = frame.to_csv(index=False).encode("utf-8")
    _atomic_write(path, encoded)
    return hashlib.sha256(encoded).hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/supplemental_fx"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0 or not 0 <= args.retries <= 10:
        print("invalid timeout or retry count", file=sys.stderr)
        return 2
    root = args.output.expanduser().resolve()
    metadata_path = root / "manifest.json"
    previous = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    previous_urls = {
        item["key"]: item["url"] for item in previous.get("sources", []) if "key" in item
    }
    previous_sources = {
        item["key"]: item for item in previous.get("sources", []) if "key" in item
    }
    run_retrieved_at = datetime.now(UTC)
    world_bank_url = previous_urls.get("world_bank_pink_sheet")
    if args.refresh or not world_bank_url:
        world_bank_url = discover_world_bank_url(args.timeout, args.retries)
    sources = [
        Source(
            "world_bank_pink_sheet",
            world_bank_url,
            "raw/world_bank/CMO-Historical-Data-Monthly.xlsx",
            parse_world_bank,
        ),
        Source("nyfed_gscpi", GSCPI_URL, "raw/nyfed/gscpi.xls", parse_gscpi),
        Source("global_epu", GEPU_URL, "raw/academic/global_epu.xlsx", parse_gepu),
        Source("geopolitical_risk", GPR_URL, "raw/academic/gpr.xls", parse_gpr),
        Source(
            "ofr_financial_stress",
            OFR_FSI_URL,
            "raw/official/ofr_fsi.csv",
            parse_ofr_fsi,
            snapshot_availability=True,
        ),
        Source(
            "ecb_ciss",
            ECB_CISS_URL,
            "raw/official/ecb_ciss.csv",
            parse_ecb_ciss,
            snapshot_availability=True,
        ),
        Source(
            "boc_bcpi",
            BOC_BCPI_URL,
            "raw/official/boc_bcpi.csv",
            parse_boc_bcpi,
            snapshot_availability=True,
        ),
        Source(
            "rba_i2_commodity_prices",
            RBA_I2_URL,
            "raw/official/rba_i02hist.xlsx",
            parse_rba_i2,
            snapshot_availability=True,
        ),
        *[
            Source(
                f"cboe_{index_symbol.lower()}",
                source_url,
                f"raw/official/cboe_{index_symbol.lower()}_history.csv",
                partial(
                    parse_cboe_fx_volatility,
                    index_symbol=index_symbol,
                    series_id=series_id,
                    series_name=series_name,
                ),
                snapshot_availability=True,
            )
            for index_symbol, (
                series_id,
                series_name,
                source_url,
            ) in CBOE_FX_VOLATILITY_INDICES.items()
        ],
    ]
    all_rows: list[dict[str, object]] = []
    gscpi_vintage_rows: list[dict[str, object]] = []
    source_manifest: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        path = root / source.relative_path
        try:
            if path.exists() and not args.refresh:
                payload = path.read_bytes()
                status = "cached"
                stored_retrieval = previous_sources.get(source.key, {}).get(
                    "retrieved_at", previous.get("retrieved_at")
                )
                source_retrieved_at = (
                    pd.Timestamp(stored_retrieval).to_pydatetime()
                    if stored_retrieval
                    else run_retrieved_at
                )
            else:
                payload = _fetch(source.url, args.timeout, args.retries)
                status = "downloaded"
                source_retrieved_at = run_retrieved_at
            if source.snapshot_availability:
                rows = source.parser(
                    payload, source.url, retrieved_at=source_retrieved_at
                )
            else:
                rows = source.parser(payload, source.url)
            if status == "downloaded":
                _atomic_write(path, payload)
            archive_path = _archive_snapshot(
                root,
                key=source.key,
                relative_path=source.relative_path,
                payload=payload,
                retrieved_at=source_retrieved_at,
            )
            all_rows.extend(rows)
            source_manifest.append(
                {
                    "key": source.key,
                    "url": source.url,
                    "path": source.relative_path,
                    "archive_path": archive_path.relative_to(root).as_posix(),
                    "status": status,
                    "retrieved_at": source_retrieved_at.astimezone(UTC).isoformat(),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "rows": len(rows),
                    "first_observation": min(str(row["observation_time"]) for row in rows),
                    "last_observation": max(str(row["observation_time"]) for row in rows),
                }
            )
            print(f"[{status:10}] {source.key:24} {len(rows):>7} rows", flush=True)
        except Exception as error:
            errors.append({"key": source.key, "url": source.url, "error": str(error)})
            print(f"[failed    ] {source.key}: {error}", file=sys.stderr, flush=True)

    vintage_path = root / "raw" / "nyfed" / "gscpi_vintages.csv"
    try:
        if vintage_path.exists() and not args.refresh:
            vintage_payload = vintage_path.read_bytes()
            vintage_status = "cached"
            stored_vintage_retrieval = previous_sources.get(
                "nyfed_gscpi_vintages", {}
            ).get("retrieved_at", previous.get("retrieved_at"))
            vintage_retrieved_at = (
                pd.Timestamp(stored_vintage_retrieval).to_pydatetime()
                if stored_vintage_retrieval
                else run_retrieved_at
            )
        else:
            vintage_payload = _fetch(GSCPI_VINTAGE_URL, args.timeout, args.retries)
            vintage_status = "downloaded"
            vintage_retrieved_at = run_retrieved_at
        gscpi_vintage_rows = parse_gscpi_vintages(vintage_payload, GSCPI_VINTAGE_URL)
        if vintage_status == "downloaded":
            _atomic_write(vintage_path, vintage_payload)
        vintage_archive_path = _archive_snapshot(
            root,
            key="nyfed_gscpi_vintages",
            relative_path="raw/nyfed/gscpi_vintages.csv",
            payload=vintage_payload,
            retrieved_at=vintage_retrieved_at,
        )
        source_manifest.append(
            {
                "key": "nyfed_gscpi_vintages",
                "url": GSCPI_VINTAGE_URL,
                "path": vintage_path.relative_to(root).as_posix(),
                "archive_path": vintage_archive_path.relative_to(root).as_posix(),
                "status": vintage_status,
                "retrieved_at": vintage_retrieved_at.astimezone(UTC).isoformat(),
                "bytes": len(vintage_payload),
                "sha256": hashlib.sha256(vintage_payload).hexdigest(),
                "rows": len(gscpi_vintage_rows),
                "first_observation": min(
                    str(row["observation_time"]) for row in gscpi_vintage_rows
                ),
                "last_observation": max(
                    str(row["observation_time"]) for row in gscpi_vintage_rows
                ),
            }
        )
        print(
            f"[{vintage_status:10}] {'nyfed_gscpi_vintages':24} "
            f"{len(gscpi_vintage_rows):>7} rows",
            flush=True,
        )
    except Exception as error:
        errors.append(
            {"key": "nyfed_gscpi_vintages", "url": GSCPI_VINTAGE_URL, "error": str(error)}
        )
        print(f"[failed    ] nyfed_gscpi_vintages: {error}", file=sys.stderr, flush=True)

    normalized_path = root / "normalized" / "supplemental_observations.csv"
    gscpi_vintage_path = root / "normalized" / "gscpi_vintages.csv"
    normalized_hash: str | None = None
    gscpi_vintage_hash: str | None = None
    if not errors:
        normalized_hash = _write_normalized(all_rows, normalized_path)
        gscpi_vintage_hash = _write_gscpi_vintages(
            gscpi_vintage_rows, gscpi_vintage_path
        )
    manifest = {
        "schema_version": 1,
        "program_version": PROGRAM_VERSION,
        "retrieved_at": run_retrieved_at.isoformat(),
        "successful_sources": len(source_manifest),
        "failed_sources": len(errors),
        "rows": len(all_rows),
        "normalized_path": (
            normalized_path.relative_to(root).as_posix() if not errors else None
        ),
        "normalized_sha256": normalized_hash,
        "gscpi_vintage_path": (
            gscpi_vintage_path.relative_to(root).as_posix() if not errors else None
        ),
        "gscpi_vintage_sha256": gscpi_vintage_hash,
        "sources": source_manifest,
        "errors": errors,
        "limitations": [
            "All normalized observations are current-vintage and may contain revisions.",
            "GSCPI vintages from January 2022 onward are preserved separately with "
            "scheduled release availability.",
            "Conservative lags prevent same-month use but do not create a PIT vintage archive.",
            "OFR FSI, ECB CISS, Bank of Canada BCPI, and RBA I2 historical rows become "
            "available only at the archived snapshot retrieval time; no historical release "
            "dates are invented.",
            "Cboe EVZ/EUVIX/JYVIX/BPVIX are incomplete-currency 30-day volatility-state "
            "proxies archived at retrieval time; they are not one-year OTC volatility, "
            "risk reversals, or a cross-sectional variance-risk-premium factor. All four "
            "histories stop before this project's first archive, so they have no strict "
            "fresh-forward coverage.",
            "Commodity prices are USD-denominated global proxies, not country terms-of-trade data.",
            "EPU and GPR are academic public datasets; redistribution terms need separate review.",
            "No series is OIS, a forward point, broker financing, or executable market depth.",
            "Raw payload snapshots and run manifests are archived so future refreshes do not "
            "erase the self-built vintage history.",
        ],
    }
    manifest_payload = (
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    _atomic_write(metadata_path, manifest_payload)
    manifest_archive = root / "manifests" / (
        f"{run_retrieved_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
    )
    _atomic_write(manifest_archive, manifest_payload)
    if errors:
        print(
            "Supplemental download incomplete; normalized output was not replaced",
            file=sys.stderr,
        )
        return 1
    print(
        f"Completed {len(source_manifest)}/{len(sources) + 1} sources, "
        f"{len(all_rows)} current-vintage rows and "
        f"{len(gscpi_vintage_rows)} GSCPI vintage rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
