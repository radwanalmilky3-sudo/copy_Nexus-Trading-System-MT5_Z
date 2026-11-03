import json
from datetime import datetime,timedelta,timezone

import pytest

from tests.test_data.test_session_contracts import export_payload,NOW
from tests.test_data.test_session_store import policy_payload


def context(payload=None,policy_data=None,now=NOW):
    from services.nexus_data.quality.session_contracts import CalendarContext,CalendarPolicy,parse_session_export
    from services.nexus_data.quality.session_store import evaluate_export
    export=parse_session_export(json.dumps(payload or export_payload()).encode(),now=now)
    policy=CalendarPolicy.model_validate_json(json.dumps(policy_data or policy_payload()))
    return CalendarContext(export,policy,evaluate_export(export,policy,now,'abc'))


def classify(ctx,start='2026-10-19T10:00:00Z',end='2026-10-19T10:05:00Z'):
    from services.nexus_data.quality.session_calendar import classify_interval
    return classify_interval(ctx,start=datetime.fromisoformat(start.replace('Z','+00:00')),end=datetime.fromisoformat(end.replace('Z','+00:00')))


def test_partial_quote_overlap_is_never_full_closure():
    assert classify(context(),'2026-10-19T09:55:00Z','2026-10-19T10:05:00Z').kind == 'expected_quote'
    assert classify(context()).kind == 'confirmed_closed'


def test_no_historical_projection_or_unverified_clock():
    assert classify(context(),'2026-10-18T10:00:00Z','2026-10-18T10:05:00Z').kind == 'unknown'
    data=policy_payload();data['clock_evidence']=None
    assert classify(context(policy_data=data)).kind == 'unknown'


def test_overnight_and_multiple_windows():
    payload=export_payload()
    payload['symbols'][0]['days'][0]['quote_sessions']=[dict(start_seconds=82800,end_seconds=3600)]
    payload['captured_at_utc']='2026-10-18T08:00:00Z'
    data=policy_payload();data['clock_evidence']['effective_from']='2026-10-18T00:00:00Z'
    ctx=context(payload,data,datetime(2026,10,18,8,tzinfo=timezone.utc))
    assert classify(ctx,'2026-10-19T00:30:00Z','2026-10-19T00:35:00Z').kind == 'expected_quote'


def test_official_exception_and_conflict():
    data=policy_payload()
    exception=dict(evidence_id='holiday-1',source_uri='https://broker.example/holiday',published_at='2026-10-18T00:00:00Z',
                   effective_from='2026-10-19T09:00:00Z',effective_to='2026-10-19T10:00:00Z',server='Demo',broker_symbols=['XAUUSD'],kind='closed',quote_windows_utc=[])
    data['exceptions']=[exception]
    result=classify(context(policy_data=data),'2026-10-19T09:15:00Z','2026-10-19T09:20:00Z')
    assert result.kind == 'confirmed_closed'
    assert result.exception_ids == ('holiday-1',)
    data['exceptions'].append(dict(exception,evidence_id='conflict',kind='modified',quote_windows_utc=[dict(start='2026-10-19T09:00:00Z',end='2026-10-19T10:00:00Z')]))
    assert classify(context(policy_data=data),'2026-10-19T09:15:00Z','2026-10-19T09:20:00Z').kind == 'unknown'


def test_expiry_and_policy_change_invalidate_dependency():
    from services.nexus_data.quality.session_calendar import calendar_dependency_hash
    first=context();second=context(now=NOW+timedelta(hours=25))
    assert calendar_dependency_hash(first) != calendar_dependency_hash(second)
    data=policy_payload();data['clock_evidence']['evidence_id']='clock-2'
    assert calendar_dependency_hash(first) != calendar_dependency_hash(context(policy_data=data))


def test_dst_ambiguity_and_failed_quotes_are_unknown():
    payload=export_payload();data=policy_payload()
    payload['captured_at_utc']='2026-11-01T00:00:00Z'
    payload['symbols'][0]['days'][0]['quote_sessions']=[dict(start_seconds=3600,end_seconds=7200)]
    data['clock_evidence'].update(effective_from='2026-11-01T00:00:00Z',effective_to='2026-11-02T00:00:00Z',timezone_name='America/New_York')
    del data['clock_evidence']['utc_offset_seconds']
    ctx=context(payload,data,datetime(2026,11,1,tzinfo=timezone.utc))
    assert classify(ctx,'2026-11-01T05:15:00Z','2026-11-01T05:20:00Z').kind == 'unknown'
    payload=export_payload();payload['symbols'][0]['days'][1].update(quote_status='error',quote_error=1,quote_sessions=[])
    assert classify(context(payload)).kind=='unknown'


def test_candidate_windows_exclude_only_confirmed_closure():
    from services.nexus_data.quality.session_calendar import candidate_gap_windows
    start=datetime(2026,10,19,9,55,tzinfo=timezone.utc);end=start+timedelta(minutes=10)
    assert candidate_gap_windows(start,end,timedelta(minutes=5),context()) == [(start,start)]
    assert candidate_gap_windows(start,end,timedelta(minutes=5),None) == [(start,end)]
