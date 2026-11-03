from __future__ import annotations

import io
import json
import lzma
import struct
import zipfile

import httpx
import pandas as pd
import pytest

from fx_system.cftc import CFTCFinancialFuturesProvider, validate_currency_positioning
from fx_system.config import CostConfig, DataConfig, RiskConfig
from fx_system.data import (
    DukascopyTickProvider,
    OandaCandleProvider,
    SyntheticFXProvider,
    attach_historical_swaps,
    has_bid_ask,
    validate_bars,
)
from fx_system.engine import BacktestEngine
from fx_system.factor_config import (
    FactorDiscoverySettings,
    FactorMiningConfig,
    FactorSettings,
    PointInTimeConfig,
)
from fx_system.factor_dsl import generate_discovery_factors
from fx_system.factor_forward import (
    build_forward_predictions,
    fit_frozen_factor_model,
    validate_frozen_model,
)
from fx_system.factor_research import (
    _market_data_quality,
    audit_factor_data,
    run_factor_mining,
    write_factor_artifacts,
)
from fx_system.factors import FACTOR_DEFINITIONS, build_factor_panel
from fx_system.labels import _label_symbol
from fx_system.models import Side, Signal
from fx_system.point_in_time import (
    PointInTimeData,
    build_carry_factors,
    load_point_in_time_data,
    validate_currency_rates,
    validate_forward_points,
)
from fx_system.reporting import data_fingerprint


def _quote_frame(mid: list[float], spread: float = 0.0002) -> pd.DataFrame:
    index = pd.date_range("2025-01-06", periods=len(mid), freq="1D", tz="UTC")
    close = pd.Series(mid, index=index)
    open_ = close.shift(1).fillna(close.iloc[0])
    frame = pd.DataFrame(index=index)
    frame["open"] = open_
    frame["high"] = pd.concat([open_, close], axis=1).max(axis=1) + 0.0005
    frame["low"] = pd.concat([open_, close], axis=1).min(axis=1) - 0.0005
    frame["close"] = close
    for field in ("open", "high", "low", "close"):
        frame[f"bid_{field}"] = frame[field] - spread / 2
        frame[f"ask_{field}"] = frame[field] + spread / 2
    frame["volume"] = 1000.0
    return validate_bars(frame.drop(columns=["open", "high", "low", "close"]), "EURUSD")


def _bi5(*records: tuple[int, int, int, float, float]) -> bytes:
    raw = b"".join(struct.pack(">iiiff", *record) for record in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def test_bid_ask_validation_derives_mid_and_rejects_crossed_quotes() -> None:
    frame = _quote_frame([1.0, 1.001, 1.002])
    assert has_bid_ask(frame)
    assert frame.iloc[0]["open"] == pytest.approx(1.0)
    assert frame.iloc[0]["spread_open"] == pytest.approx(0.0002)
    crossed = frame.copy()
    crossed.loc[crossed.index[1], "ask_close"] = crossed.loc[crossed.index[1], "bid_close"] - 1e-4
    with pytest.raises(ValueError, match="invalid OHLC"):
        validate_bars(crossed, "EURUSD")
    missing_quote = frame.copy()
    missing_quote.loc[missing_quote.index[1], "ask_open"] = float("nan")
    with pytest.raises(ValueError, match="invalid OHLC"):
        validate_bars(missing_quote, "EURUSD")


def test_oanda_provider_requests_practice_bid_ask_candles() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api-fxpractice.oanda.com"
        assert request.url.params["price"] == "BA"
        assert request.headers["authorization"] == "Bearer token"
        candles = []
        for day, complete in (("2025-01-06", True), ("2025-01-07", True), ("2025-01-08", False)):
            candles.append(
                {
                    "time": f"{day}T00:00:00Z",
                    "complete": complete,
                    "volume": 10,
                    "bid": {"o": "1.0", "h": "1.1", "l": "0.9", "c": "1.0"},
                    "ask": {"o": "1.0002", "h": "1.1002", "l": "0.9002", "c": "1.0002"},
                }
            )
        return httpx.Response(200, json={"candles": candles})

    data = OandaCandleProvider.download(
        ["EURUSD"],
        "2025-01-06",
        "2025-01-09",
        "1d",
        "token",
        transport=httpx.MockTransport(handler),
    )
    assert len(data["EURUSD"]) == 2
    assert has_bid_ask(data["EURUSD"])
    with pytest.raises(ValueError, match="fxPractice"):
        OandaCandleProvider.download(
            ["EURUSD"],
            "2025-01-06",
            "2025-01-09",
            "1d",
            "token",
            base_url="https://api-fxtrade.oanda.com",
        )


def test_dukascopy_tick_decoder_uses_explicit_scale_and_synchronized_mid() -> None:
    payload = _bi5(
        (0, 110_002, 110_000, 1.0, 2.0),
        (100, 110_022, 110_010, 3.0, 4.0),
        (200, 110_012, 110_011, 5.0, 6.0),
    )
    row, ticks = DukascopyTickProvider._hour_bar(
        payload, pd.Timestamp("2025-01-06T00:00:00Z"), "EURUSD"
    )
    assert row is not None
    assert ticks == 3
    assert row["bid_high"] == pytest.approx(1.10011)
    assert row["ask_high"] == pytest.approx(1.10022)
    assert row["high"] == pytest.approx(1.10016)
    assert row["high"] != pytest.approx((row["bid_high"] + row["ask_high"]) / 2)

    jpy_row, _ = DukascopyTickProvider._hour_bar(
        _bi5((0, 150_002, 150_000, 1.0, 1.0)),
        pd.Timestamp("2025-01-06T00:00:00Z"),
        "USDJPY",
    )
    assert jpy_row is not None
    assert jpy_row["bid_open"] == pytest.approx(150.0)
    assert jpy_row["ask_open"] == pytest.approx(150.002)


def test_dukascopy_download_uses_zero_based_month_cache_and_complete_hours(tmp_path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        hour = int(request.url.path.rsplit("/", 1)[-1][:2])
        price = 110_000 + hour
        return httpx.Response(200, content=_bi5((0, price + 2, price, 1.0, 2.0)))

    kwargs = {
        "symbols": ["EURUSD"],
        "start": "2025-01-06T00:00:00Z",
        "end": None,
        "interval": "1h",
        "cache_directory": tmp_path,
        "concurrency": 1,
        "transport": httpx.MockTransport(handler),
        "now": pd.Timestamp("2025-01-06T02:30:00Z"),
    }
    data = DukascopyTickProvider.download(**kwargs)
    assert len(data["EURUSD"]) == 2
    assert all("/datafeed/EURUSD/2025/00/06/" in path for path in requests)
    assert not any(path.endswith("02h_ticks.bi5") for path in requests)
    assert data["EURUSD"].attrs["source_hour_coverage"] == 1.0

    requests.clear()
    cached = DukascopyTickProvider.download(**kwargs)
    assert len(cached["EURUSD"]) == 2
    assert requests == []


def test_dukascopy_four_hour_bar_requires_all_four_source_hours(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        hour = int(request.url.path.rsplit("/", 1)[-1][:2])
        if hour == 2:
            return httpx.Response(404)
        price = 110_000 + hour
        return httpx.Response(200, content=_bi5((0, price + 2, price, 1.0, 1.0)))

    data = DukascopyTickProvider.download(
        ["EURUSD"],
        "2025-01-06T00:00:00Z",
        "2025-01-06T12:00:00Z",
        "4h",
        cache_directory=tmp_path,
        concurrency=2,
        max_retries=0,
        transport=httpx.MockTransport(handler),
        now=pd.Timestamp("2025-01-07T00:00:00Z"),
    )
    assert list(data["EURUSD"].index) == [
        pd.Timestamp("2025-01-06T04:00:00Z"),
        pd.Timestamp("2025-01-06T08:00:00Z"),
    ]


def test_dukascopy_rejects_corrupt_binary_and_data_hash_covers_execution_quotes() -> None:
    with pytest.raises(ValueError, match="LZMA"):
        DukascopyTickProvider._hour_bar(
            b"not-lzma", pd.Timestamp("2025-01-06T00:00:00Z"), "EURUSD"
        )
    with pytest.raises(ValueError, match="multiple of 20"):
        DukascopyTickProvider._hour_bar(
            lzma.compress(b"x"), pd.Timestamp("2025-01-06T00:00:00Z"), "EURUSD"
        )

    original = _quote_frame([1.0, 1.001, 1.002])
    changed = original.copy()
    changed.loc[changed.index[0], "ask_open"] += 0.00001
    assert data_fingerprint({"EURUSD": original}) != data_fingerprint({"EURUSD": changed})


def test_market_data_quality_rejects_sparse_multi_year_history() -> None:
    sparse = _quote_frame([1.0, 1.01]).set_axis(
        pd.DatetimeIndex(["2016-01-04", "2025-01-06"], tz="UTC")
    )
    sparse.attrs.update(
        {
            "source_provider": "dukascopy",
            "source_manifest_complete": True,
            "source_hour_coverage": 1.0,
        }
    )
    config = FactorMiningConfig(
        data=DataConfig(
            provider="csv",
            symbols=["EURUSD"],
            interval="1d",
            start="2016-01-01",
            end="2025-09-15",
            price_mode="bid_ask",
        ),
        risk=RiskConfig(close_before_weekend=False),
    )
    quality = _market_data_quality({"EURUSD": sparse}, config)
    assert quality["minimum_bar_coverage"] < 0.01


def test_cftc_archive_normalizes_currency_positioning_with_conservative_lag(
    tmp_path,
) -> None:
    source = pd.DataFrame(
        [
            {
                "Report_Date_as_YYYY-MM-DD": "2025-01-07",
                "CFTC_Contract_Market_Code": "099741",
                "Open_Interest_All": 1000,
                "Dealer_Positions_Long_All": 100,
                "Dealer_Positions_Short_All": 300,
                "Asset_Mgr_Positions_Long_All": 400,
                "Asset_Mgr_Positions_Short_All": 100,
                "Lev_Money_Positions_Long_All": 350,
                "Lev_Money_Positions_Short_All": 150,
            },
            {
                "Report_Date_as_YYYY-MM-DD": "2025-01-07",
                "CFTC_Contract_Market_Code": "097741",
                "Open_Interest_All": 2000,
                "Dealer_Positions_Long_All": 500,
                "Dealer_Positions_Short_All": 300,
                "Asset_Mgr_Positions_Long_All": 200,
                "Asset_Mgr_Positions_Short_All": 600,
                "Lev_Money_Positions_Long_All": 250,
                "Lev_Money_Positions_Short_All": 750,
            },
        ]
    )
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("FinFutYY.txt", source.to_csv(index=False))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("fut_fin_txt_2025.zip")
        return httpx.Response(200, content=archive_bytes.getvalue())

    positioning = CFTCFinancialFuturesProvider.download(
        2025, 2025, transport=httpx.MockTransport(handler)
    )
    eur = positioning.loc[positioning["currency"] == "EUR"].iloc[0]
    assert eur["leveraged_money_net_ratio"] == pytest.approx(0.2)
    assert eur["asset_manager_net_ratio"] == pytest.approx(0.3)
    assert eur["dealer_net_ratio"] == pytest.approx(-0.2)
    assert eur["available_time"] == pd.Timestamp("2025-03-08T00:00:00Z")
    assert (
        eur["value_vintage_quality"]
        == "current_revised_historical_archive_not_as_published_vintage"
    )
    output = CFTCFinancialFuturesProvider.save(positioning, tmp_path / "positioning.csv")
    manifest = json.loads(
        output.with_suffix(".manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["parser_version"] == "cftc-tff-v2"
    assert manifest["archives"][0]["year"] == 2025


def test_cftc_archive_supports_legacy_report_date_column() -> None:
    legacy_source = pd.DataFrame(
        [
            {
                "Report_Date_as_MM_DD_YYYY": "01/03/2012",
                "CFTC_Contract_Market_Code": "099741",
                "Open_Interest_All": 1000,
                "Dealer_Positions_Long_All": 100,
                "Dealer_Positions_Short_All": 300,
                "Asset_Mgr_Positions_Long_All": 400,
                "Asset_Mgr_Positions_Short_All": 100,
                "Lev_Money_Positions_Long_All": 350,
                "Lev_Money_Positions_Short_All": 150,
            }
        ]
    )
    current_source = legacy_source.rename(
        columns={"Report_Date_as_MM_DD_YYYY": "Report_Date_as_YYYY-MM-DD"}
    )
    current_source["Report_Date_as_YYYY-MM-DD"] = "2013-01-08"

    def archive_payload(source: pd.DataFrame) -> bytes:
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("FinFutYY.txt", source.to_csv(index=False))
        return archive_bytes.getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        source = legacy_source if request.url.path.endswith("2012.zip") else current_source
        return httpx.Response(200, content=archive_payload(source))

    positioning = CFTCFinancialFuturesProvider.download(
        2012,
        2013,
        transport=httpx.MockTransport(handler),
    )

    assert list(positioning["observation_time"]) == [
        pd.Timestamp("2012-01-03T00:00:00Z"),
        pd.Timestamp("2013-01-08T00:00:00Z"),
    ]
    assert list(positioning["available_time"]) == [
        pd.Timestamp("2012-03-03T00:00:00Z"),
        pd.Timestamp("2013-03-09T00:00:00Z"),
    ]


def test_cftc_combined_archive_extends_currency_history_to_2006() -> None:
    source = pd.DataFrame(
        [
            {
                "Report_Date_as_YYYY-MM-DD": "6/13/2006 12:00:00 AM",
                "CFTC_Contract_Market_Code": "090741",
                "Open_Interest_All": 1000,
                "Dealer_Positions_Long_All": 100,
                "Dealer_Positions_Short_All": 300,
                "Asset_Mgr_Positions_Long_All": 400,
                "Asset_Mgr_Positions_Short_All": 100,
                "Lev_Money_Positions_Long_All": 350,
                "Lev_Money_Positions_Short_All": 150,
            },
            {
                "Report_Date_as_YYYY-MM-DD": "1/03/2012 12:00:00 AM",
                "CFTC_Contract_Market_Code": "090741",
                "Open_Interest_All": 1100,
                "Dealer_Positions_Long_All": 100,
                "Dealer_Positions_Short_All": 300,
                "Asset_Mgr_Positions_Long_All": 400,
                "Asset_Mgr_Positions_Short_All": 100,
                "Lev_Money_Positions_Long_All": 350,
                "Lev_Money_Positions_Short_All": 150,
            },
        ]
    )
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("F_TFF_2006_2016.txt", source.to_csv(index=False))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("fin_fut_txt_2006_2016.zip")
        return httpx.Response(200, content=archive_bytes.getvalue())

    positioning = CFTCFinancialFuturesProvider.download(
        2006, 2006, transport=httpx.MockTransport(handler)
    )

    assert len(positioning) == 1
    assert positioning.iloc[0]["currency"] == "CAD"
    assert positioning.iloc[0]["observation_time"] == pd.Timestamp("2006-06-13T00:00:00Z")


def test_cftc_pair_factor_uses_available_time_and_usd_as_neutral_anchor() -> None:
    positioning = validate_currency_positioning(
        pd.DataFrame(
            [
                {
                    "observation_time": "2025-01-01T00:00:00Z",
                    "available_time": "2025-01-08T00:00:00Z",
                    "currency": "EUR",
                    "open_interest": 1000,
                    "dealer_net_ratio": -0.2,
                    "asset_manager_net_ratio": 0.1,
                    "leveraged_money_net_ratio": 0.3,
                },
                {
                    "observation_time": "2025-01-01T00:00:00Z",
                    "available_time": "2025-01-08T00:00:00Z",
                    "currency": "GBP",
                    "open_interest": 900,
                    "dealer_net_ratio": -0.1,
                    "asset_manager_net_ratio": 0.05,
                    "leveraged_money_net_ratio": 0.1,
                },
                {
                    "observation_time": "2025-01-01T00:00:00Z",
                    "available_time": "2025-01-08T00:00:00Z",
                    "currency": "JPY",
                    "open_interest": 1200,
                    "dealer_net_ratio": 0.2,
                    "asset_manager_net_ratio": -0.1,
                    "leveraged_money_net_ratio": -0.2,
                },
            ]
        )
    )
    fixture = _pit_fixture()
    point_in_time = PointInTimeData(
        fixture.currency_rates,
        fixture.forward_points,
        30,
        positioning,
        14,
    )
    index = pd.DatetimeIndex(["2025-01-05", "2025-01-12"], tz="UTC")
    frame = pd.DataFrame({"close": [1.10, 1.11]}, index=index)
    factors = build_carry_factors("EURUSD", frame, point_in_time, 260)
    assert pd.isna(factors.loc[index[0], "cftc_leveraged_net"])
    assert factors.loc[index[1], "cftc_leveraged_net"] == pytest.approx(0.3)
    assert factors.loc[index[1], "cftc_asset_manager_net"] == pytest.approx(0.1)
    usd_jpy = build_carry_factors("USDJPY", frame, point_in_time, 260)
    eur_gbp = build_carry_factors("EURGBP", frame, point_in_time, 260)
    assert usd_jpy.loc[index[1], "cftc_leveraged_net"] == pytest.approx(0.2)
    assert eur_gbp.loc[index[1], "cftc_leveraged_net"] == pytest.approx(0.2)


def test_engine_uses_executable_quotes_and_historical_swap(permissive_risk: RiskConfig) -> None:
    frame = _quote_frame([1.0, 1.0, 1.001, 1.001])
    frame["swap_long_pips"] = -1.0
    frame["swap_short_pips"] = -1.0
    signal = Signal(
        frame.index[0], "EURUSD", Side.LONG, 0.9, "quote-test", 0.01, 1.0, 0.8, 24
    )
    result = BacktestEngine(
        permissive_risk,
        CostConfig(default_spread_pips=0, slippage_pips=0, commission_per_million=0),
    ).run({"EURUSD": frame}, [signal])
    trade = result.trades[0]
    assert trade.entry_price == pytest.approx(frame.iloc[1]["ask_open"])
    assert trade.exit_price == pytest.approx(frame.iloc[2]["bid_open"])
    assert trade.costs > 0


def test_historical_swap_join_never_backfills_future_rate(tmp_path) -> None:
    frame = _quote_frame([1.0, 1.0, 1.0, 1.0])
    swaps = pd.DataFrame(
        {
            "available_time": ["2025-01-07T00:00:00Z", "2025-01-09T00:00:00Z"],
            "swap_long_pips": [-0.5, -1.5],
            "swap_short_pips": [0.2, 0.7],
        }
    )
    swaps.to_csv(tmp_path / "EURUSD.csv", index=False)
    enriched = attach_historical_swaps({"EURUSD": frame}, tmp_path)["EURUSD"]
    assert pd.isna(enriched.loc[pd.Timestamp("2025-01-06", tz="UTC"), "swap_long_pips"])
    assert enriched.loc[pd.Timestamp("2025-01-08", tz="UTC"), "swap_long_pips"] == -0.5
    assert enriched.loc[pd.Timestamp("2025-01-09", tz="UTC"), "swap_long_pips"] == -1.5


def test_triple_barrier_uses_executable_side_of_quote() -> None:
    frame = _quote_frame([1.0, 1.0, 1.0, 1.0], spread=0.002)
    frame.loc[frame.index[1], "high"] = 1.008
    frame.loc[frame.index[1], "bid_high"] = 1.0069
    frame.loc[frame.index[1], "ask_high"] = 1.0089
    frame.loc[frame.index[1], "low"] = 0.999
    frame.loc[frame.index[1], "bid_low"] = 0.998
    frame.loc[frame.index[1], "ask_low"] = 1.0
    labels = _label_symbol(
        frame,
        pd.Series(0.01, index=frame.index),
        1,
        FactorSettings(target_atr=0.7, stop_atr=1.1, max_holding_hours=24),
    )
    assert labels.iloc[0]["_event"] != "target"


def _pit_fixture() -> PointInTimeData:
    rates = validate_currency_rates(
        pd.DataFrame(
            [
                (
                    "2025-01-01", "2025-01-02", "EUR", 2.0, 2.1, 2.2,
                    "test_vendor", "test_ois_history", "historical_market_ois_quote",
                ),
                (
                    "2025-01-01", "2025-01-02", "USD", 4.0, 4.1, 4.2,
                    "test_vendor", "test_ois_history", "historical_market_ois_quote",
                ),
                (
                    "2025-01-01", "2025-01-10", "EUR", 3.0, 3.1, 3.2,
                    "test_vendor", "test_ois_history", "historical_market_ois_quote",
                ),
            ],
            columns=[
                "observation_time",
                "available_time",
                "currency",
                "policy_rate",
                "ois_1m",
                "ois_3m",
                "ois_source",
                "ois_provenance",
                "ois_quote_quality",
            ],
        )
    )
    forwards = validate_forward_points(
        pd.DataFrame(
            [
                (
                    "2025-01-01", "2025-01-02", "EURUSD", 0.001, 0.003, 1.10,
                    "test_vendor", "test_forward_history", "historical_market_quote",
                ),
                (
                    "2025-01-01", "2025-01-10", "EURUSD", 0.002, 0.006, 1.11,
                    "test_vendor", "test_forward_history", "historical_market_quote",
                ),
            ],
            columns=[
                "observation_time",
                "available_time",
                "symbol",
                "forward_points_1m",
                "forward_points_3m",
                "spot_reference",
                "source",
                "provenance",
                "quote_quality",
            ],
        )
    )
    return PointInTimeData(rates, forwards, 30)


def test_carry_factors_use_available_time_not_future_revision() -> None:
    index = pd.DatetimeIndex(["2025-01-05", "2025-01-12"], tz="UTC")
    frame = pd.DataFrame({"close": [1.10, 1.11]}, index=index)
    factors = build_carry_factors("EURUSD", frame, _pit_fixture(), 260)
    assert factors.loc[index[0], "rate_differential"] == pytest.approx(-0.02)
    assert factors.loc[index[1], "rate_differential"] == pytest.approx(-0.01)
    assert factors.loc[index[0], "forward_discount_1m"] == pytest.approx(
        -0.001 / 1.10 * (365 / 30)
    )
    invalid = pd.DataFrame(
        [("2025-01-03", "2025-01-02", "EUR", 1, 1, 1)],
        columns=[
            "observation_time",
            "available_time",
            "currency",
            "policy_rate",
            "ois_1m",
            "ois_3m",
        ],
    )
    with pytest.raises(ValueError, match="observation_time"):
        validate_currency_rates(invalid)


def test_budgeted_factor_dsl_is_deterministic_and_has_no_future_dependency() -> None:
    data = SyntheticFXProvider(seed=301).generate(
        ["EURUSD", "GBPUSD", "USDJPY", "EURGBP"], 180, "4h"
    )
    settings = FactorDiscoverySettings(
        enabled=True,
        max_generated_factors=12,
        primitive_factors=["momentum_1", "momentum_12", "atr_percent"],
    )
    cutoff = data["EURUSD"].index[130]
    prefix_data = {symbol: frame.loc[:cutoff] for symbol, frame in data.items()}
    full, generated = generate_discovery_factors(
        build_factor_panel(data), dict(FACTOR_DEFINITIONS), settings
    )
    prefix, prefix_generated = generate_discovery_factors(
        build_factor_panel(prefix_data), dict(FACTOR_DEFINITIONS), settings
    )
    assert len(generated) == settings.max_generated_factors
    assert [item.name for item in generated] == [item.name for item in prefix_generated]
    assert {"cs_rank", "multiply", "delta"}.issubset({item.operator for item in generated})
    columns = [item.name for item in generated]
    full_prefix = full.loc[
        full["_feature_time"] <= cutoff, ["_feature_time", "_symbol", *columns]
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        full_prefix,
        prefix[["_feature_time", "_symbol", *columns]].reset_index(drop=True),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_factor_discovery_readiness_does_not_require_broker_cost_history() -> None:
    symbols = ["EURUSD", "GBPUSD"]
    data = SyntheticFXProvider(seed=319).generate(
        symbols,
        500,
        "1d",
        start="2018-01-01",
        price_mode="bid_ask",
    )
    for symbol, source in list(data.items()):
        frame = source.drop(columns=["swap_long_pips", "swap_short_pips"])
        frame.attrs.update(
            {
                "source_provider": "dukascopy",
                "source_manifest_complete": True,
                "source_hour_coverage": 1.0,
                "source_failed_hours": 0,
                "source_parser_version": "test-parser-v1",
                "source_csv_hash_verified": True,
            }
        )
        data[symbol] = frame
    config = FactorMiningConfig(
        data=DataConfig(
            provider="csv",
            symbols=symbols,
            interval="1d",
            price_mode="bid_ask",
            start="2018-01-01",
            end="2020-01-01",
        ),
        risk=RiskConfig(close_before_weekend=False),
        factor=FactorSettings(minimum_broker_history_years=1.0),
    )
    readiness = audit_factor_data(data, config)
    assert readiness["factor_discovery_ready"] is True
    assert readiness["historical_cost_validation_ready"] is False
    assert readiness["broker_ready"] is False
    assert readiness["minimum_swap_coverage"] == 0.0


def test_full_quote_carry_discovery_pipeline_records_stress_and_lineage(tmp_path) -> None:
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP", "EURJPY"]
    data = SyntheticFXProvider(seed=302).generate(symbols, 500, "1d", price_mode="bid_ask")
    point_config = PointInTimeConfig(enabled=True, provider="synthetic", synthetic_seed=302)
    point_in_time = load_point_in_time_data(point_config, data)
    config = FactorMiningConfig(
        data=DataConfig(
            provider="synthetic",
            symbols=symbols,
            interval="1d",
            synthetic_bars=500,
            price_mode="bid_ask",
        ),
        costs=CostConfig(),
        risk=RiskConfig(close_before_weekend=False),
        factor=FactorSettings(
            train_bars=250,
            test_bars=75,
            step_bars=75,
            minimum_train_samples=1500,
            minimum_calibration_samples=300,
            bootstrap_samples=100,
            max_features=12,
            cost_stress_multipliers=[1.0, 1.5],
            promotion_required_stress_multiplier=1.5,
        ),
        point_in_time=point_config,
        discovery=FactorDiscoverySettings(
            enabled=True,
            max_generated_factors=8,
            primitive_factors=["momentum_1", "atr_percent", "rate_differential"],
        ),
    )
    mining = run_factor_mining(data, config, point_in_time)
    generated = mining.catalog.loc[mining.catalog["family"] == "discovered_expression"]
    assert len(generated) == 8
    assert mining.panel["rate_differential"].notna().mean() > 0.8
    assert mining.summary["point_in_time_fingerprint_sha256"] == point_in_time.fingerprint()
    assert set(mining.summary["cost_stress"]) == {"1x", "1.5x"}
    assert set(mining.folds[0].stress_metrics) == {"1x", "1.5x"}
    assert mining.summary["data_readiness"]["tier"] == "software_validation"
    assert not mining.summary["data_readiness"]["broker_ready"]
    assert mining.summary["verdict"] in {
        "rejected_for_trading",
        "research_candidate_requires_new_holdout",
    }
    output = write_factor_artifacts(mining, data, config, tmp_path)
    assert (output / "factor_catalog.csv").exists()
    assert (output / "cost_stress_by_fold.csv").exists()
    assert (output / "factor_manifest.json").exists()
    assert (output / "frozen_model_status.json").exists()
    assert not (output / "frozen_factor_model.json").exists()

    frozen = fit_frozen_factor_model(mining, config, allow_rejected_for_testing=True)
    validate_frozen_model(frozen, config)
    existing_predictions, _ = build_forward_predictions(
        data, config, frozen, point_in_time
    )
    assert existing_predictions.empty
    forward_data: dict[str, pd.DataFrame] = {}
    for symbol, frame in data.items():
        extension = frame.iloc[-10:].copy()
        extension.index = pd.bdate_range(
            start=frame.index[-1] + pd.offsets.BDay(1), periods=len(extension)
        )
        combined = pd.concat([frame, extension])
        combined.attrs = frame.attrs.copy()
        forward_data[symbol] = combined
    predictions, _ = build_forward_predictions(
        forward_data, config, frozen, point_in_time
    )
    assert not predictions.empty
    assert predictions["_feature_time"].min() > pd.Timestamp(frozen["research_data_end"])
    assert predictions["probability"].between(0, 1).all()
    changed_prefix = {symbol: frame.copy() for symbol, frame in forward_data.items()}
    changed_prefix["EURUSD"].attrs = forward_data["EURUSD"].attrs.copy()
    changed_prefix["EURUSD"].loc[
        changed_prefix["EURUSD"].index[10], "ask_open"
    ] += 0.00001
    with pytest.raises(ValueError, match="frozen research prefix"):
        build_forward_predictions(changed_prefix, config, frozen, point_in_time)
    changed_rates = point_in_time.currency_rates.copy()
    changed_rates.loc[0, "policy_rate"] += 0.01
    changed_point_prefix = PointInTimeData(
        changed_rates,
        point_in_time.forward_points,
        point_in_time.maximum_staleness_days,
        point_in_time.currency_positioning,
        point_in_time.maximum_positioning_staleness_days,
    )
    with pytest.raises(ValueError, match="point-in-time data changed"):
        build_forward_predictions(
            forward_data, config, frozen, changed_point_prefix
        )
    tampered = dict(frozen)
    tampered["classifier_intercept"] += 1
    with pytest.raises(ValueError, match="contract hash"):
        validate_frozen_model(tampered, config)
    changed_point_in_time = config.model_copy(
        update={
            "point_in_time": point_config.model_copy(
                update={"maximum_positioning_staleness_days": 15}
            )
        }
    )
    with pytest.raises(ValueError, match="point-in-time settings"):
        validate_frozen_model(frozen, changed_point_in_time)


def test_forward_config_changes_only_the_allowed_data_horizon() -> None:
    development = FactorMiningConfig.from_yaml("configs/factors_broker_carry_dev.yaml")
    forward = FactorMiningConfig.from_yaml("configs/factors_broker_carry_forward.yaml")
    assert development.data.end == "2025-09-15"
    assert forward.data.end is None
    development_data = development.data.model_dump(mode="json", exclude={"end"})
    forward_data = forward.data.model_dump(mode="json", exclude={"end"})
    assert development_data == forward_data
    assert development.factor == forward.factor
    assert development.discovery == forward.discovery
    assert development.point_in_time == forward.point_in_time
    assert development.costs == forward.costs
    assert development.risk == forward.risk
