from services.nexus_features.main import _chronological_bars


def test_ohlcv_rows_are_oldest_first_for_latest_bar_consumers():
    newest = {"timestamp": "2026-10-14T10:15:00+00:00", "close": 102}
    older = {"timestamp": "2026-10-14T10:00:00+00:00", "close": 100}

    ordered = _chronological_bars([newest, older])

    assert ordered == [older, newest]
    assert ordered[-1]["close"] == 102
