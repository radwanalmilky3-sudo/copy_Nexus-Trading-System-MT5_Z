import json

import pytest
from pydantic import ValidationError


def models():
    from shared import broker_settings_models as m
    return m


def test_rejects_client_owner():
    with pytest.raises(ValidationError):
        models().ProfileCreate(name='Mine', broker_name='OneRoyal', owner_user_id='victim')
    with pytest.raises(ValidationError):
        models().AccountCreate(profile_id='p',label='Demo',server='OneRoyal-Demo',login='123',account_kind='demo',password='secret')


def test_transition_date_does_not_invent_utc_hour():
    x=models().SupportTransitionDraft.model_validate_json(json.dumps(dict(
        from_offset_seconds=10800,to_offset_seconds=7200,session_start_date='2026-11-02',during_market_closure='yes')))
    assert x.model_dump(mode='json')['session_start_date']=='2026-11-02'
    assert x.effective_at_utc is None and x.next_open_utc is None
    assert x.during_market_closure=='yes'
    assert models().SupportTransitionDraft.model_validate_json(x.model_dump_json())==x


def test_defaults_fail_closed():
    m=models()
    assert m.AssetPreference(broker_symbol='XAUUSD').mode=='disabled'
    assert m.AccountSettings().transition.during_market_closure=='unknown'
    assert m.AccountSettings().assets==[]
    with pytest.raises(ValidationError):
        m.SaveSettings(expected_version=0,settings=m.AccountSettings())


def test_rejects_naive_datetime_and_duplicate_assets():
    m=models()
    for field in ('effective_at_utc','next_open_utc','evidence_received_at'):
        with pytest.raises(ValidationError):
            m.SupportTransitionDraft.model_validate_json(json.dumps({field:'2026-11-02T01:00:00'}))
    with pytest.raises(ValidationError):
        m.SupportTransitionDraft(from_offset_seconds=50401)
    with pytest.raises(ValidationError):
        m.SupportTransitionDraft(support_reply='a'*8001)
    with pytest.raises(ValidationError):
        m.AccountSettings(assets=[m.AssetPreference(broker_symbol='XAUUSD')]*2)
    with pytest.raises(ValidationError):
        m.AccountCreate(profile_id='p',label='Demo',server='Demo',login='notdigits')
