from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

CFTC_FINANCIAL_FUTURES_URL = (
    "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
)
CFTC_FINANCIAL_FUTURES_HISTORY_URL = (
    "https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip"
)

# TFF futures-only contract codes. Each contract is quoted as USD per foreign
# currency, so a positive net ratio represents long foreign currency versus USD.
CFTC_CURRENCY_CONTRACTS = {
    "090741": "CAD",
    "092741": "CHF",
    "096742": "GBP",
    "097741": "JPY",
    "099741": "EUR",
    "112741": "NZD",
    "232741": "AUD",
}

CFTC_PARSER_VERSION = "cftc-tff-v2"

POSITIONING_COLUMNS = (
    "open_interest",
    "dealer_net_ratio",
    "asset_manager_net_ratio",
    "leveraged_money_net_ratio",
)

_SOURCE_COLUMNS = {
    "Open_Interest_All": "open_interest",
    "Dealer_Positions_Long_All": "dealer_long",
    "Dealer_Positions_Short_All": "dealer_short",
    "Asset_Mgr_Positions_Long_All": "asset_manager_long",
    "Asset_Mgr_Positions_Short_All": "asset_manager_short",
    "Lev_Money_Positions_Long_All": "leveraged_money_long",
    "Lev_Money_Positions_Short_All": "leveraged_money_short",
}


def validate_currency_positioning(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate weekly CFTC positioning with conservative point-in-time availability."""
    result = frame.copy()
    result.columns = [str(column).strip().lower() for column in result.columns]
    required = {"observation_time", "available_time", "currency", *POSITIONING_COLUMNS}
    missing = required - set(result)
    if missing:
        raise ValueError(f"currency positioning is missing {sorted(missing)}")
    for column in ("observation_time", "available_time"):
        result[column] = pd.to_datetime(result[column], utc=True, errors="coerce")
        if result[column].isna().any():
            raise ValueError(f"currency positioning contains invalid {column}")
    if (result["available_time"] < result["observation_time"]).any():
        raise ValueError("currency positioning available_time precedes observation_time")
    result["currency"] = result["currency"].astype(str).str.upper()
    if (~result["currency"].str.fullmatch(r"[A-Z]{3}")).any():
        raise ValueError("currency positioning contains invalid currency codes")
    for column in POSITIONING_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")
        if result[column].isna().any() or not np.isfinite(result[column]).all():
            raise ValueError(f"currency positioning contains invalid {column}")
    if (result["open_interest"] <= 0).any():
        raise ValueError("currency positioning open_interest must be positive")
    ratio_columns = [column for column in POSITIONING_COLUMNS if column.endswith("_ratio")]
    if (result[ratio_columns].abs() > 2).any(axis=None):
        raise ValueError("currency positioning net ratios are outside conservative bounds")
    if result.duplicated(["currency", "available_time"]).any():
        raise ValueError("duplicate currency/available_time positioning rows")
    return result.sort_values(["currency", "available_time"]).reset_index(drop=True)


class CFTCFinancialFuturesProvider:
    """Download and normalize public CFTC Traders in Financial Futures archives."""

    @staticmethod
    def _read_archive(payload: bytes, period: int | str) -> pd.DataFrame:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
                if len(members) != 1:
                    raise ValueError(f"CFTC {period}: expected one text member, found {members}")
                with archive.open(members[0]) as handle:
                    return pd.read_csv(
                        handle,
                        dtype={"CFTC_Contract_Market_Code": str},
                        low_memory=False,
                    )
        except zipfile.BadZipFile as error:
            raise ValueError(f"CFTC {period}: invalid ZIP archive") from error

    @classmethod
    def download(
        cls,
        start_year: int,
        end_year: int,
        *,
        availability_lag_days: int = 60,
        cache_directory: str | Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> pd.DataFrame:
        if start_year < 2006 or end_year < start_year:
            raise ValueError("CFTC TFF history starts in June 2006")
        if not 3 <= availability_lag_days <= 90:
            raise ValueError("CFTC availability lag must be between 3 and 90 days")

        archive_frames: list[pd.DataFrame] = []
        archive_sources: list[dict[str, object]] = []
        cache_root = Path(cache_directory) if cache_directory is not None else None
        requests: list[dict[str, object]] = []
        if start_year < 2010:
            requests.append(
                {
                    "period": "2006-2016",
                    "url": CFTC_FINANCIAL_FUTURES_HISTORY_URL,
                    "filename": "fin_fut_txt_2006_2016.zip",
                    "priority": 0,
                    "mutable": False,
                }
            )
        for year in range(max(2010, start_year), end_year + 1):
            requests.append(
                {
                    "period": year,
                    "url": CFTC_FINANCIAL_FUTURES_URL.format(year=year),
                    "filename": f"fut_fin_txt_{year}.zip",
                    "priority": 1,
                    "mutable": year == datetime.now(UTC).year,
                }
            )
        with httpx.Client(transport=transport, timeout=60, follow_redirects=True) as client:
            for request in requests:
                period = request["period"]
                url = str(request["url"])
                cache_path = cache_root / str(request["filename"]) if cache_root else None
                use_cache = bool(
                    cache_path is not None
                    and cache_path.exists()
                    and not bool(request["mutable"])
                )
                if use_cache and cache_path is not None:
                    payload = cache_path.read_bytes()
                    retrieved_at = datetime.fromtimestamp(
                        cache_path.stat().st_mtime, tz=UTC
                    ).isoformat()
                    cache_status = "cached"
                else:
                    response = client.get(url)
                    response.raise_for_status()
                    payload = response.content
                    retrieved_at = datetime.now(UTC).isoformat()
                    cache_status = "downloaded"
                    if cache_path is not None:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        temporary = cache_path.with_suffix(".zip.tmp")
                        temporary.write_bytes(payload)
                        temporary.replace(cache_path)
                frame = cls._read_archive(payload, period)
                frame["_archive_priority"] = int(request["priority"])
                archive_frames.append(frame)
                archive_sources.append(
                    {
                        "year": period,
                        "url": url,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "bytes": len(payload),
                        "retrieved_at": retrieved_at,
                        "cache_status": cache_status,
                    }
                )
        raw = pd.concat(archive_frames, ignore_index=True)
        raw.columns = [str(column).strip() for column in raw.columns]
        date_columns = (
            "Report_Date_as_YYYY-MM-DD",
            "Report_Date_as_MM_DD_YYYY",
        )
        available_date_columns = [column for column in date_columns if column in raw]
        required = {"CFTC_Contract_Market_Code", *_SOURCE_COLUMNS}
        missing = required - set(raw)
        if missing:
            raise ValueError(f"CFTC archive is missing columns {sorted(missing)}")
        if not available_date_columns:
            raise ValueError(f"CFTC archive is missing one of the date columns {date_columns}")

        contract_code = (
            raw["CFTC_Contract_Market_Code"]
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(6)
        )
        selected = raw.loc[contract_code.isin(CFTC_CURRENCY_CONTRACTS)].copy()
        selected["currency"] = contract_code.loc[selected.index].map(CFTC_CURRENCY_CONTRACTS)
        selected = selected.rename(columns=_SOURCE_COLUMNS)
        observation_time = pd.Series(pd.NaT, index=selected.index, dtype="datetime64[ns, UTC]")
        for date_column in available_date_columns:
            raw_dates = selected[date_column]
            parsed_dates = pd.to_datetime(raw_dates, utc=True, errors="coerce", format="mixed")
            supplied = raw_dates.notna() & raw_dates.astype(str).str.strip().ne("")
            if parsed_dates.loc[supplied].isna().any():
                raise ValueError(f"CFTC archive contains invalid dates in {date_column}")
            conflict = observation_time.notna() & parsed_dates.notna() & observation_time.ne(
                parsed_dates
            )
            if conflict.any():
                raise ValueError("CFTC archive contains conflicting report date columns")
            observation_time = observation_time.fillna(parsed_dates)
        selected["observation_time"] = observation_time
        if selected["observation_time"].isna().any():
            raise ValueError("CFTC archive contains invalid report dates")
        selected = selected.loc[
            selected["observation_time"].dt.year.between(start_year, end_year)
        ].copy()
        selected = selected.sort_values("_archive_priority").drop_duplicates(
            ["currency", "observation_time"], keep="last"
        )
        selected["available_time"] = selected["observation_time"] + timedelta(
            days=availability_lag_days
        )
        numeric = [*_SOURCE_COLUMNS.values()]
        for column in numeric:
            selected[column] = pd.to_numeric(selected[column], errors="coerce")
        if selected[numeric].isna().any(axis=None):
            raise ValueError("CFTC archive contains invalid positioning values")
        denominator = selected["open_interest"]
        selected["dealer_net_ratio"] = (
            selected["dealer_long"] - selected["dealer_short"]
        ) / denominator
        selected["asset_manager_net_ratio"] = (
            selected["asset_manager_long"] - selected["asset_manager_short"]
        ) / denominator
        selected["leveraged_money_net_ratio"] = (
            selected["leveraged_money_long"] - selected["leveraged_money_short"]
        ) / denominator
        output = selected[
            ["observation_time", "available_time", "currency", *POSITIONING_COLUMNS]
        ].copy()
        output["availability_quality"] = (
            f"approximate_conservative_{availability_lag_days}d_lag"
        )
        output["value_vintage_quality"] = (
            "current_revised_historical_archive_not_as_published_vintage"
        )
        validated = validate_currency_positioning(output)
        validated.attrs.update(
            {
                "source_provider": "cftc_tff",
                "source_parser_version": CFTC_PARSER_VERSION,
                "source_archives": archive_sources,
                "availability_lag_days": availability_lag_days,
            }
        )
        return validated

    @staticmethod
    def save(frame: pd.DataFrame, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        validated = validate_currency_positioning(frame)
        temporary = output.with_suffix(output.suffix + ".tmp")
        validated.to_csv(temporary, index=False)
        temporary.replace(output)
        with output.open("rb") as handle:
            csv_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
        manifest = {
            "schema_version": 1,
            "provider": frame.attrs.get("source_provider"),
            "parser_version": frame.attrs.get("source_parser_version"),
            "availability_lag_days": frame.attrs.get("availability_lag_days"),
            "value_vintage_quality": sorted(
                validated.get("value_vintage_quality", pd.Series(dtype=str))
                .dropna()
                .astype(str)
                .unique()
                .tolist()
            ),
            "csv_sha256": csv_sha256,
            "rows": len(validated),
            "archives": frame.attrs.get("source_archives", []),
        }
        manifest_path = output.with_suffix(".manifest.json")
        manifest_temporary = manifest_path.with_suffix(".json.tmp")
        manifest_temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest_temporary.replace(manifest_path)
        return output
