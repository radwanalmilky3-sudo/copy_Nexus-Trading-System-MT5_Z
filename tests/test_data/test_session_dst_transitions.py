"""Fixture-based UTC historical / DST transition classification (disposable, synthetic hours only)."""
import json
from datetime import datetime, timezone

import pytest

ATHENS = 'Europe/Athens'


def weekly_export(captured_iso, observed_offset=10800, window=(32400, 61200),
                  trading_days=range(1, 6), sunday=None):
    days = []
    for d in range(7):
        windows = []
        if d in trading_days:
            windows = [dict(start_seconds=window[0], end_seconds=window[1])]
        if sunday is not None and d == 0:
            windows = [dict(start_seconds=sunday[0], end_seconds=sunday[1])]
        days.append(dict(day=d, quote_status='ok' if windows else 'no_sessions', trade_status='no_sessions',
                         quote_error=0, trade_error=0, quote_sessions=windows, trade_sessions=[]))
    return dict(schema_version=1, server='Demo', company='Broker', captured_at_utc=captured_iso,
                connected=True, observed_server_offset_seconds=observed_offset,
                symbols=[dict(broker_symbol='XAUUSD', days=days)])


def offset_clock(offset, published='2026-10-20T00:00:00Z',
                 effective_from='2026-10-18T00:00:00Z', effective_to='2026-10-28T00:00:00Z'):
    return dict(evidence_id=f'clock-{offset}', source_uri='https://broker.example/clock',
                published_at=published, effective_from=effective_from, effective_to=effective_to,
                utc_offset_seconds=offset)


def tz_clock(name, published='2026-10-20T00:00:00Z',
             effective_from='2026-10-18T00:00:00Z', effective_to='2026-10-28T00:00:00Z'):
    return dict(evidence_id=f'clock-{name}', source_uri='https://broker.example/clock',
                published_at=published, effective_from=effective_from, effective_to=effective_to,
                timezone_name=name)


def policy(clock, exceptions=()):
    return dict(expected_server='Demo', symbol_map={'XAUUSD': 'XAUUSD'}, clock_evidence=clock,
                exceptions=list(exceptions))


def context(payload, policy_data, now):
    from services.nexus_data.quality.session_contracts import CalendarContext, CalendarPolicy, parse_session_export
    from services.nexus_data.quality.session_store import evaluate_export
    export = parse_session_export(json.dumps(payload).encode(), now=now)
    parsed = CalendarPolicy.model_validate_json(json.dumps(policy_data))
    return CalendarContext(export, parsed, evaluate_export(export, parsed, now, 'fixture-hash'))


def classify(ctx, start_iso, end_iso):
    from services.nexus_data.quality.session_calendar import classify_interval
    start = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
    end = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
    return classify_interval(ctx, start=start, end=end)


def test_before_transition_utc3_known_hours():
    now = datetime(2026, 10, 23, 5, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-23T05:00:00Z', 10800),
                  policy(offset_clock(10800, effective_from='2026-10-22T00:00:00Z',
                                      effective_to='2026-10-24T00:00:00Z')), now)
    assert ctx.status.state == 'ready'
    assert classify(ctx, '2026-10-23T05:30:00Z', '2026-10-23T05:35:00Z').kind == 'confirmed_closed'
    assert classify(ctx, '2026-10-23T06:00:00Z', '2026-10-23T06:05:00Z').kind == 'expected_quote'
    assert classify(ctx, '2026-10-23T14:00:00Z', '2026-10-23T14:05:00Z').kind == 'confirmed_closed'


def test_after_transition_utc2_known_hours():
    now = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-26T06:00:00Z', 7200),
                  policy(offset_clock(7200, effective_from='2026-10-25T00:00:00Z',
                                      effective_to='2026-10-27T00:00:00Z')), now)
    assert ctx.status.state == 'ready'
    assert classify(ctx, '2026-10-26T06:30:00Z', '2026-10-26T06:35:00Z').kind == 'confirmed_closed'
    assert classify(ctx, '2026-10-26T07:00:00Z', '2026-10-26T07:05:00Z').kind == 'expected_quote'
    assert classify(ctx, '2026-10-26T15:00:00Z', '2026-10-26T15:05:00Z').kind == 'confirmed_closed'


def test_known_hours_comparison_table_before_and_after_transition():
    fri_now = datetime(2026, 10, 23, 5, tzinfo=timezone.utc)
    mon_now = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
    clock = tz_clock(ATHENS, effective_from='2026-10-22T00:00:00Z', effective_to='2026-10-28T00:00:00Z')
    fri = context(weekly_export('2026-10-23T05:00:00Z', 10800), policy(clock), fri_now)
    mon = context(weekly_export('2026-10-26T06:00:00Z', 7200), policy(clock), mon_now)
    probes = [
        ('Fri 2026-10-23 (UTC+3)', fri, '05:55Z=08:55 local', '2026-10-23T05:55:00Z', '2026-10-23T06:00:00Z', 'confirmed_closed'),
        ('Fri 2026-10-23 (UTC+3)', fri, '06:00Z=09:00 local', '2026-10-23T06:00:00Z', '2026-10-23T06:05:00Z', 'expected_quote'),
        ('Mon 2026-10-26 (UTC+2)', mon, '06:55Z=08:55 local', '2026-10-26T06:55:00Z', '2026-10-26T07:00:00Z', 'confirmed_closed'),
        ('Mon 2026-10-26 (UTC+2)', mon, '07:00Z=09:00 local', '2026-10-26T07:00:00Z', '2026-10-26T07:05:00Z', 'expected_quote'),
    ]
    table = []
    for era, ctx, hour, start, end, expected in probes:
        kind = classify(ctx, start, end).kind
        table.append(f'{era} {hour} -> {kind}')
        assert kind == expected
    assert table == [
        'Fri 2026-10-23 (UTC+3) 05:55Z=08:55 local -> confirmed_closed',
        'Fri 2026-10-23 (UTC+3) 06:00Z=09:00 local -> expected_quote',
        'Mon 2026-10-26 (UTC+2) 06:55Z=08:55 local -> confirmed_closed',
        'Mon 2026-10-26 (UTC+2) 07:00Z=09:00 local -> expected_quote',
    ]


def test_offset_evidence_is_not_a_dst_rule():
    now = datetime(2026, 10, 26, 5, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-26T05:00:00Z', 10800),
                  policy(offset_clock(10800)), now)
    assert classify(ctx, '2026-10-26T06:00:00Z', '2026-10-26T06:05:00Z').kind == 'expected_quote'
    assert classify(ctx, '2026-10-26T07:00:00Z', '2026-10-26T07:05:00Z').kind == 'expected_quote'


def test_weekend_outside_hours_and_no_historical_projection():
    now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-24T12:00:00Z', 10800),
                  policy(offset_clock(10800, effective_from='2026-10-23T00:00:00Z',
                                      effective_to='2026-10-25T00:00:00Z')), now)
    assert classify(ctx, '2026-10-24T12:30:00Z', '2026-10-24T12:35:00Z').kind == 'confirmed_closed'
    assert classify(ctx, '2026-10-26T10:00:00Z', '2026-10-26T10:05:00Z').kind == 'unknown'
    assert classify(ctx, '2026-10-24T04:00:00Z', '2026-10-24T04:05:00Z').kind == 'unknown'


def test_ambiguous_fallback_hour_is_unknown_not_closed():
    now = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-25T00:00:00Z', 10800, sunday=(10800, 14400)),
                  policy(tz_clock(ATHENS, effective_from='2026-10-24T00:00:00Z',
                                  effective_to='2026-10-26T00:00:00Z')), now)
    assert ctx.status.state == 'ready'
    result = classify(ctx, '2026-10-25T00:30:00Z', '2026-10-25T00:35:00Z')
    assert result.kind == 'unknown'
    assert 'Unresolvable' in result.reason


def test_spring_forward_nonexistent_hour_is_unknown():
    now = datetime(2026, 3, 29, 0, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-03-29T00:00:00Z', 10800, sunday=(12600, 14400)),
                  policy(tz_clock(ATHENS, published='2026-03-27T00:00:00Z',
                                  effective_from='2026-03-28T00:00:00Z',
                                  effective_to='2026-03-30T00:00:00Z')), now)
    result = classify(ctx, '2026-03-29T00:30:00Z', '2026-03-29T00:35:00Z')
    assert result.kind == 'unknown'
    assert 'Unresolvable' in result.reason


def test_undefined_transition_period_stays_unknown():
    now = datetime(2026, 11, 2, 10, tzinfo=timezone.utc)
    payload = weekly_export('2026-11-02T08:00:00Z', 7200)
    no_evidence = context(payload, policy(None), now)
    assert classify(no_evidence, '2026-11-02T10:00:00Z', '2026-11-02T10:05:00Z').kind == 'unknown'
    late = context(payload, policy(offset_clock(7200, published='2026-11-03T00:00:00Z',
                                                effective_from='2026-11-02T00:00:00Z',
                                                effective_to='2026-11-04T00:00:00Z')), now)
    assert late.status.state == 'clock_unverified'
    assert classify(late, '2026-11-02T10:00:00Z', '2026-11-02T10:05:00Z').kind == 'unknown'


@pytest.mark.xfail(strict=True,
                   reason='gap: conflicting observed offset must yield unknown per design spec lines 249-250')
def test_observed_offset_conflict_with_clock_evidence_is_gap():
    now = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
    ctx = context(weekly_export('2026-10-26T06:00:00Z', 7200),
                  policy(offset_clock(10800, effective_from='2026-10-25T00:00:00Z',
                                      effective_to='2026-10-27T00:00:00Z')), now)
    result = classify(ctx, '2026-10-26T06:30:00Z', '2026-10-26T06:35:00Z')
    assert result.kind == 'unknown'


def exception(evidence_id, kind, effective_from, effective_to, windows=()):
    base = dict(evidence_id=evidence_id, source_uri='https://broker.example/holiday',
                published_at='2026-10-18T00:00:00Z', effective_from=effective_from,
                effective_to=effective_to, server='Demo', broker_symbols=['XAUUSD'], kind=kind)
    if kind == 'modified':
        base['quote_windows_utc'] = [dict(start=w[0], end=w[1]) for w in windows]
    return base


def test_holiday_late_open_and_early_close_exceptions():
    now = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
    payload = weekly_export('2026-10-19T08:00:00Z', 0)
    clock = offset_clock(0, effective_from='2026-10-18T00:00:00Z', effective_to='2026-10-20T00:00:00Z')
    holiday = context(payload, policy(clock, [exception(
        'holiday-1', 'closed', '2026-10-19T09:00:00Z', '2026-10-19T10:00:00Z')]), now)
    closed = classify(holiday, '2026-10-19T09:15:00Z', '2026-10-19T09:20:00Z')
    assert closed.kind == 'confirmed_closed'
    assert closed.exception_ids == ('holiday-1',)
    late_open = context(payload, policy(clock, [exception(
        'late-open', 'modified', '2026-10-19T09:00:00Z', '2026-10-19T17:00:00Z',
        [('2026-10-19T12:00:00Z', '2026-10-19T17:00:00Z')])]), now)
    assert classify(late_open, '2026-10-19T09:30:00Z', '2026-10-19T09:35:00Z').kind == 'confirmed_closed'
    assert classify(late_open, '2026-10-19T12:30:00Z', '2026-10-19T12:35:00Z').kind == 'expected_quote'
    early_close = context(payload, policy(clock, [exception(
        'early-close', 'modified', '2026-10-19T09:00:00Z', '2026-10-19T17:00:00Z',
        [('2026-10-19T09:00:00Z', '2026-10-19T12:00:00Z')])]), now)
    assert classify(early_close, '2026-10-19T10:00:00Z', '2026-10-19T10:05:00Z').kind == 'expected_quote'
    assert classify(early_close, '2026-10-19T12:30:00Z', '2026-10-19T12:35:00Z').kind == 'confirmed_closed'
