"""Import server session metadata into an explicitly owned account's settings."""
import asyncio
import json
from datetime import datetime,timedelta,timezone

from shared.broker_settings_models import AccountSettings
from .quality.session_contracts import parse_session_export
from .quality.session_store import read_export


async def sync_account_sessions(store,owner,account_id):
    account=await store.get_account(owner,account_id)
    reader=getattr(store.owner_store,'_session_calendar_store',None)
    path=getattr(reader,'export_path',None)
    if path is None:raise ValueError('Session export is not configured')
    now=datetime.now(timezone.utc)
    export=parse_session_export(await asyncio.to_thread(read_export,path),now=now)
    if not export.connected or export.server!=account['server'] or now-export.captured_at_utc>timedelta(hours=24):
        raise ValueError('Disconnected, mismatched or expired session export')
    requested=[a['broker_symbol'] for a in account['settings']['assets']]
    symbols={s.broker_symbol:s for s in export.symbols}
    observations=[];skipped=[]
    for name in requested:
        symbol=symbols.get(name)
        if symbol is None or any(d.quote_status not in ('ok','no_sessions') or d.quote_error for d in symbol.days) or not any(d.quote_sessions for d in symbol.days):
            skipped.append(name);continue
        observations.append(dict(server=export.server,broker_symbol=name,captured_at_utc=export.captured_at_utc.isoformat(),
            observed_offset_seconds=export.observed_server_offset_seconds,source='NexusSessionReader',
            windows=[dict(day=d.day,start_seconds=w.start_seconds,end_seconds=w.end_seconds) for d in sorted(symbol.days,key=lambda d:d.day) for w in d.quote_sessions]))
    settings=AccountSettings.model_validate_json(json.dumps({**account['settings'],'session_observations':observations}))
    previous=account['settings'].get('session_observations')
    if previous!=settings.model_dump(mode='json')['session_observations']:
        account=await store.save_settings(owner,account_id,account['version'],settings)
    return dict(account=account,imported=[s['broker_symbol'] for s in observations],skipped=skipped,
                captured_at_utc=export.captured_at_utc.isoformat(),historical_authority=False)
