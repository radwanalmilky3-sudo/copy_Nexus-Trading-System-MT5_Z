import json
from datetime import datetime, timezone

import pytest


def export_payload():
    return dict(schema_version=1,server='Demo',company='Broker',captured_at_utc='2026-10-19T08:00:00Z',connected=True,
                observed_server_offset_seconds=7200,symbols=[dict(broker_symbol='XAUUSD',days=[
                    dict(day=d,quote_status='ok',trade_status='no_sessions',quote_error=0,trade_error=0,
                         quote_sessions=[dict(start_seconds=32400,end_seconds=36000)],trade_sessions=[]) for d in range(7)])])


NOW = datetime(2026,10,19,8,tzinfo=timezone.utc)


def parse(payload):
    from services.nexus_data.quality.session_contracts import parse_session_export
    return parse_session_export(json.dumps(payload).encode(),now=NOW)


def test_preserves_distinct_quote_and_trade_windows():
    result = parse(export_payload())
    assert result.symbols[0].days[1].quote_sessions[0].start_seconds == 32400
    assert result.symbols[0].days[1].trade_sessions == ()


def test_requires_seven_unique_days():
    payload = export_payload()
    payload['symbols'][0]['days'][6]['day'] = 0
    with pytest.raises(ValueError):
        parse(payload)


@pytest.mark.parametrize('raw',[b' '*1048577,b'{"schema_version": NaN}',b'{"schema_version":1,"schema_version":1}'],ids=['oversize','nan','duplicate_key'])
def test_rejects_oversize_and_nonfinite_json(raw):
    from services.nexus_data.quality.session_contracts import parse_session_export
    with pytest.raises(ValueError):
        parse_session_export(raw,now=NOW)


def test_failed_or_truncated_day_is_not_closed():
    payload = export_payload()
    payload['symbols'][0]['days'][1].update(quote_status='error',quote_error=4302,quote_sessions=[])
    result = parse(payload)
    assert result.symbols[0].days[1].quote_status == 'error'
    payload['symbols'][0]['days'][1].update(quote_status='no_sessions',quote_error=4302)
    with pytest.raises(ValueError):
        parse(payload)


@pytest.mark.parametrize('change',[{'connected':1},{'unknown':'x'},{'captured_at_utc':'2026-10-19T08:02:00Z'}])
def test_strict_fields_and_future_capture(change):
    payload=export_payload();payload.update(change)
    with pytest.raises(ValueError):
        parse(payload)
