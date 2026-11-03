from datetime import datetime, timezone

from services.nexus_data.research_market import session_gap_review


def epoch(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def test_saved_weekly_schedule_is_symbol_scoped_and_not_historical_authority():
    observation = dict(server='real', broker_symbol='AUDUSDs',
                       captured_at_utc='2026-10-20T16:00:00Z',
                       observed_offset_seconds=10800,
                       windows=[dict(day=d, start_seconds=180, end_seconds=86100)
                                for d in range(1, 6)])
    account = dict(server='real', version=9, settings=dict(session_observation=observation))
    bars = [dict(time=epoch('2026-10-16T23:45:00')),
            dict(time=epoch('2026-10-19T00:00:00'))]
    result = session_gap_review(bars, 'M15', account, 'AUDUSDs')
    assert result['weekly_closure_candidates'] == 1
    assert result['confirmed_closed'] == 0
    assert result['unclassified_gaps'] == 1
    assert result['settings_version'] == 9
    assert session_gap_review(bars, 'M15', account, 'XAUUSDs')['state'] == 'symbol_mismatch'
    observation['server'] = 'demo'
    assert session_gap_review(bars, 'M15', account, 'AUDUSDs')['state'] == 'server_mismatch'


def test_in_session_missing_bar_is_not_weekend_or_repaired():
    account = dict(server='real', version=1, settings=dict(session_observation=dict(
        server='real', broker_symbol='AUDUSDs', captured_at_utc='2026-10-20T16:00:00Z',
        observed_offset_seconds=10800,
        windows=[dict(day=2, start_seconds=0, end_seconds=86400)])))
    bars = [dict(time=epoch('2026-10-20T10:00:00')),
            dict(time=epoch('2026-10-20T10:30:00'))]
    result = session_gap_review(bars, 'M15', account, 'AUDUSDs')
    assert result['weekly_closure_candidates'] == 0
    assert result['unclassified_gaps'] == 1
    assert len(bars) == 2
