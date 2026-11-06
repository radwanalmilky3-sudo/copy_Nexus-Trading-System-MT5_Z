"""T-024 — CCXT public real-data unlock: pure helpers (map parsing, mode label, relabel)."""
import os
from datetime import datetime, timezone

from services.nexus_data import main as nd


def test_parse_symbol_map_valid_entries():
    m = nd.parse_ccxt_symbol_map("XAUUSD:PAXG/USDT , BTCUSD:BTC/USDT")
    assert m == {"XAUUSD": "PAXG/USDT", "BTCUSD": "BTC/USDT"}


def test_parse_symbol_map_uppercases_logical():
    m = nd.parse_ccxt_symbol_map("xauusd:PAXG/USDT")
    assert m == {"XAUUSD": "PAXG/USDT"}


def test_parse_symbol_map_skips_malformed():
    m = nd.parse_ccxt_symbol_map("BAD, XAUUSD:PAXG/USDT, XAG:NOPAIR, :/USDT")
    assert m == {"XAUUSD": "PAXG/USDT"}


def test_parse_symbol_map_empty():
    assert nd.parse_ccxt_symbol_map("") == {}


def test_resolve_data_mode_precedence():
    assert nd.resolve_data_mode(True, False, False) == "REAL_MT5"
    assert nd.resolve_data_mode(False, True, False) == "REAL_CCXT"
    assert nd.resolve_data_mode(False, False, False) == "REAL_MT5_REQUIRED"
    assert nd.resolve_data_mode(True, True, True) == "SYNTHETIC_ALLOWED"
    assert nd.resolve_data_mode(False, True, True) == "SYNTHETIC_ALLOWED"


def test_relabel_bars_to_logical_symbol():
    from shared.models import OHLCV

    bar = OHLCV(
        symbol="PAXG/USDT",
        timeframe="M15",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=3.0,
        timestamp=datetime(2026, 11, 6, tzinfo=timezone.utc),
    )
    out = nd._relabel_bars([bar], "XAUUSD")
    assert out[0].symbol == "XAUUSD"
    assert out[0].close == 1.5
    assert out[0].timeframe == "M15"


def test_relabel_keeps_already_logical_bars():
    from shared.models import OHLCV

    bar = OHLCV(
        symbol="XAUUSD",
        timeframe="M15",
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=3.0,
        timestamp=datetime(2026, 11, 6, tzinfo=timezone.utc),
    )
    out = nd._relabel_bars([bar], "XAUUSD")
    assert out[0] is bar


def test_default_map_targets_gold_proxy():
    raw = os.getenv("CCXT_SYMBOL_MAP", "XAUUSD:PAXG/USDT")
    assert nd.parse_ccxt_symbol_map(raw)["XAUUSD"] == "PAXG/USDT"


def test_public_mode_needs_no_api_key():
    """The gate is ENABLE_CCXT only — public market data works keyless."""
    assert nd.ENABLE_CCXT_FLAG is bool(os.getenv("ENABLE_CCXT", ""))
