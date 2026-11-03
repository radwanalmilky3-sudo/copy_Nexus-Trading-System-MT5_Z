"""Disposable fixtures reproducing session-export identity mismatch without secrets."""
import json
from types import SimpleNamespace

import pytest

from tests.test_data.test_session_contracts import export_payload, NOW


def policy_payload(expected_server='Demo', symbol_map=None):
    return dict(expected_server=expected_server,
                symbol_map=symbol_map if symbol_map is not None else {'XAUUSD': 'XAUUSD'},
                clock_evidence=dict(evidence_id='clock-1', source_uri='https://broker.example/clock',
                                    published_at='2026-10-18T00:00:00Z', effective_from='2026-10-19T00:00:00Z',
                                    effective_to='2026-10-20T00:00:00Z', utc_offset_seconds=0),
                exceptions=[])


def evaluate(payload, policy_data, now=NOW):
    from services.nexus_data.quality.session_contracts import CalendarPolicy, parse_session_export
    from services.nexus_data.quality.session_store import evaluate_export
    export = parse_session_export(json.dumps(payload).encode(), now=now)
    policy = CalendarPolicy.model_validate_json(json.dumps(policy_data))
    return evaluate_export(export, policy, now, 'fixture-hash')


def test_live_style_mismatch_reports_server_and_symbols_without_secrets():
    payload = export_payload()
    payload['server'] = 'OneRoyal-Server'
    payload['symbols'][0]['broker_symbol'] = 'XAUUSDs'
    status = evaluate(payload, policy_payload('OneRoyal-Demo', {'XAUUSD': 'XAUUSD'}))
    assert status.state == 'identity_mismatch'
    assert status.reason == 'Export server/symbols do not match configured broker identity'
    dumped = status.model_dump_json().lower()
    assert 'login' not in dumped and 'password' not in dumped and 'token' not in dumped


def test_matching_server_with_missing_mapped_symbol_is_identity_mismatch():
    payload = export_payload()
    payload['symbols'][0]['broker_symbol'] = 'XAUUSDs'
    status = evaluate(payload, policy_payload('Demo', {'XAUUSD': 'XAUUSD'}))
    assert status.state == 'identity_mismatch'


def test_matching_symbols_with_wrong_server_is_identity_mismatch():
    payload = export_payload()
    payload['server'] = 'Other-Demo'
    assert evaluate(payload, policy_payload('Demo')).state == 'identity_mismatch'


def test_extra_symbol_beyond_policy_map_is_still_ready():
    payload = export_payload()
    payload['symbols'].append(dict(broker_symbol='XAUUSDs', days=payload['symbols'][0]['days']))
    assert evaluate(payload, policy_payload('Demo')).state == 'ready'


def test_export_contract_rejects_login_field():
    from services.nexus_data.quality.session_contracts import parse_session_export
    payload = export_payload()
    payload['login'] = '123456'
    with pytest.raises(ValueError):
        parse_session_export(json.dumps(payload).encode(), now=NOW)


@pytest.mark.asyncio
async def test_unmapped_logical_symbol_context_is_identity_mismatch(operational_store):
    from services.nexus_data.quality.session_contracts import CalendarPolicy
    from services.nexus_data.quality.session_store import SessionEvidenceStore
    importer = SessionEvidenceStore(operational_store, None,
                                    CalendarPolicy.model_validate_json(json.dumps(policy_payload())))
    context = await importer.context('BTCUSD', NOW)
    assert context.status.state == 'identity_mismatch'
    assert context.status.reason == 'Logical symbol not mapped'
    assert context.export is None


@pytest.mark.asyncio
async def _sync_setup(operational_store, tmp_path, export_overrides=None, captured=None):
    from shared.broker_settings_models import AccountCreate, AccountSettings, ProfileCreate
    from services.nexus_data.broker_settings_store import BrokerSettingsStore
    store = BrokerSettingsStore(operational_store)
    profile = await store.create_profile('u1', ProfileCreate(name='broker', broker_name='broker'))
    account = await store.create_account('u1', AccountCreate(
        profile_id=profile['profile_id'], label='real', server='real', login='123456'))
    settings = AccountSettings.model_validate_json(json.dumps(
        {'assets': [{'broker_symbol': s, 'mode': 'analysis'} for s in ['XAUUSDs', 'XAGUSDs']]}))
    await store.save_settings('u1', account['account_id'], 1, settings)

    def symbol(name, error=False):
        return dict(broker_symbol=name, days=[
            dict(day=d, quote_status='error' if error else 'ok' if d in range(1, 6) else 'no_sessions',
                 trade_status='no_sessions', quote_error=1 if error else 0, trade_error=0,
                 quote_sessions=[dict(start_seconds=180, end_seconds=86340)] if d in range(1, 6) and not error else [],
                 trade_sessions=[]) for d in range(7)])

    stamp = captured or '2026-10-19T08:00:00Z'
    raw = dict(schema_version=1, server='real', company='broker', captured_at_utc=stamp, connected=True,
               observed_server_offset_seconds=10800,
               symbols=[symbol('XAUUSDs'), symbol('OTHER')])
    raw.update(export_overrides or {})
    path = tmp_path / 'sessions.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    operational_store._session_calendar_store = SimpleNamespace(export_path=path)
    return store, account


@pytest.mark.asyncio
async def test_sync_rejects_wrong_server_without_leaking_login(operational_store, tmp_path):
    from services.nexus_data.account_session_sync import sync_account_sessions
    store, account = await _sync_setup(operational_store, tmp_path, export_overrides={'server': 'demo'})
    with pytest.raises(ValueError) as excinfo:
        await sync_account_sessions(store, 'u1', account['account_id'])
    assert '123456' not in str(excinfo.value)


@pytest.mark.asyncio
async def test_sync_rejects_expired_export(operational_store, tmp_path):
    from datetime import datetime, timedelta, timezone
    from services.nexus_data.account_session_sync import sync_account_sessions
    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime('%Y-%m-%dT%H:%M:%SZ')
    store, account = await _sync_setup(operational_store, tmp_path, captured=stale)
    with pytest.raises(ValueError):
        await sync_account_sessions(store, 'u1', account['account_id'])


@pytest.mark.asyncio
async def test_sync_imports_only_present_symbols_and_never_checks_login(operational_store, tmp_path):
    from services.nexus_data.account_session_sync import sync_account_sessions
    from datetime import datetime, timezone
    store, account = await _sync_setup(operational_store, tmp_path)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    file = operational_store._session_calendar_store.export_path
    raw = json.loads(file.read_text(encoding='utf-8'))
    raw['captured_at_utc'] = stamp
    file.write_text(json.dumps(raw), encoding='utf-8')
    result = await sync_account_sessions(store, 'u1', account['account_id'])
    assert result['imported'] == ['XAUUSDs']
    assert result['skipped'] == ['XAGUSDs']
    assert result['historical_authority'] is False
