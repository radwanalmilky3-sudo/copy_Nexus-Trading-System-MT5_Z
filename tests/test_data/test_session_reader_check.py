import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_data.test_session_contracts import export_payload
from tests.test_data.test_session_store import policy_payload


def _stamp(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _wallclock_policy():
    policy=policy_payload()
    now=datetime.now(timezone.utc)
    clock=policy['clock_evidence']
    clock['published_at']=_stamp(now-timedelta(days=1))
    clock['effective_from']=_stamp(now-timedelta(hours=12))
    clock['effective_to']=_stamp(now+timedelta(hours=12))
    return policy


@pytest.mark.parametrize('mode,expected',[('ready',0),('clock_unverified',2),('invalid',1)])
def test_cli_read_only_outcomes(tmp_path,mode,expected):
    policy=_wallclock_policy()
    if mode=='clock_unverified':
        policy['clock_evidence']=None
    payload=export_payload()
    payload['captured_at_utc']=_stamp(datetime.now(timezone.utc)-timedelta(minutes=10))
    path=tmp_path/'export.json';config=tmp_path/'policy.json'
    path.write_text('{' if mode=='invalid' else json.dumps(payload),encoding='utf-8')
    config.write_text(json.dumps(policy),encoding='utf-8')
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/check_session_reader.py'),
                           '--export',str(path),'--policy',str(config)],capture_output=True,text=True,timeout=25)
    assert result.returncode==expected,result.stdout+result.stderr
    output=json.loads(result.stdout)
    assert output['state']==('ready' if expected==0 else 'clock_unverified' if expected==2 else 'invalid')
    assert 'password' not in result.stdout.lower()


def test_shipped_local_policy_pins_live_verified_broker_identity():
    from services.nexus_data.quality.session_contracts import load_calendar_policy
    path=Path(__file__).resolve().parents[2]/'config/broker_calendar.local.json'
    policy=load_calendar_policy(path)
    assert policy.expected_server=='OneRoyal-Server','policy must match the live account server captured by the session reader EA'
    assert policy.symbol_map=={'XAUUSD':'XAUUSDs'},'policy must map to the suffixed broker symbol used on OneRoyal-Server'


def test_shipped_policy_accepts_live_identity_and_stays_clock_unverified(tmp_path):
    payload=export_payload()
    payload['server']='OneRoyal-Server'
    payload['symbols'][0]['broker_symbol']='XAUUSDs'
    payload['captured_at_utc']=_stamp(datetime.now(timezone.utc)-timedelta(minutes=10))
    path=tmp_path/'export.json'
    path.write_text(json.dumps(payload),encoding='utf-8')
    result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/check_session_reader.py'),
                           '--export',str(path),'--policy',str(Path(__file__).resolve().parents[2]/'config/broker_calendar.local.json')],
                          capture_output=True,text=True,timeout=25)
    output=json.loads(result.stdout)
    assert output['state']=='clock_unverified','live identity must now match the shipped policy; only dated broker clock evidence may promote it to ready'
    assert result.returncode==2
