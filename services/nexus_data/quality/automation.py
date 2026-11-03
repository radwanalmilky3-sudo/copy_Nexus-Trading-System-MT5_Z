"""Owner-local, bounded periodic certification; never manufactures passing evidence."""
import asyncio
import logging
from datetime import datetime, timezone

from .stored_audit import audit_stored_ohlcv, latest_quality
from .repair import repair_pair

logger = logging.getLogger(__name__)


class QualityAutomation:
    def __init__(self, store, interval=60, provider=None, invalidate=None, calendar_store=None):
        self.store = store
        self.provider = provider
        self.invalidate = invalidate
        self.calendar_store = calendar_store
        self.interval = max(30, interval)
        self.state = dict(enabled=True, interval_seconds=self.interval, last_cycle=None,
                          audited=0, failed=0, warnings=0, errors=0,
                          repair_enabled=provider is not None, quarantined=0, replaced=0, inserted=0,
                          blocked_pairs=0, deferred=0, manifests_stale=0)
        if calendar_store is not None:
            self.state['calendar']=calendar_store.status.model_dump(mode='json')

    async def cycle(self):
        counts = dict(audited=0, failed=0, warnings=0, errors=0, quarantined=0, replaced=0, inserted=0,
                      blocked_pairs=0, deferred=0, manifests_stale=0)
        if self.calendar_store is not None:
            status=await self.calendar_store.refresh(datetime.now(timezone.utc))
            self.state['calendar']=status.model_dump(mode='json')
        if self.provider is not None:
            pairs = set(await self.store._fetch('SELECT DISTINCT symbol,timeframe FROM ohlcv'))
            exists = await self.store._fetch("SELECT 1 FROM information_schema.tables WHERE table_name='quarantine'")
            if exists:
                pairs.update(await self.store._fetch("SELECT DISTINCT json_extract_string(payload_json,'$.symbol'),json_extract_string(payload_json,'$.timeframe') FROM quarantine WHERE resolution_status='open' AND reason_code LIKE 'auto_%'"))
            for symbol, timeframe in sorted(pairs):
                try:
                    calendar=await self.calendar_store.context(symbol,datetime.now(timezone.utc)) if self.calendar_store else None
                    result = await repair_pair(self.store, self.provider, symbol, timeframe, invalidate=self.invalidate,calendar=calendar)
                    for key in ('quarantined', 'replaced', 'inserted'):
                        counts[key] += result[key]
                    counts['deferred'] += result['deferred']
                except Exception:
                    counts['errors'] += 1
                    logger.exception('Automatic repair failed for %s/%s', symbol, timeframe)
        groups = await self.store._fetch(
            'SELECT DISTINCT symbol,timeframe,source FROM ohlcv ORDER BY symbol,timeframe,source')
        exists = await self.store._fetch("SELECT 1 FROM information_schema.tables WHERE table_name='quarantine'")
        if exists:
            isolated = await self.store._fetch("SELECT DISTINCT json_extract_string(payload_json,'$.symbol'),json_extract_string(payload_json,'$.timeframe'),json_extract_string(payload_json,'$.source') FROM quarantine WHERE resolution_status='open' AND reason_code LIKE 'auto_%'")
            groups = sorted(set(groups) | set(isolated))
        for symbol, timeframe, source in groups:
            try:
                previous = await latest_quality(self.store, symbol, timeframe, source)
                if previous and previous['snapshot_current'] and not previous['expired']:
                    continue
                report = await audit_stored_ohlcv(self.store, symbol, timeframe, source)
                counts['audited'] += 1
                counts['failed'] += report['status'] == 'failed'
                counts['warnings'] += report['status'] == 'warning'
            except Exception:
                counts['errors'] += 1
                logger.exception('Automatic stored quality audit failed for %s/%s/%s', symbol, timeframe, source)
        exists = await self.store._fetch("SELECT 1 FROM information_schema.tables WHERE table_name='quarantine'")
        if exists:
            blocked = await self.store._fetch("SELECT COUNT(DISTINCT (json_extract_string(payload_json,'$.symbol'),json_extract_string(payload_json,'$.timeframe'))) FROM quarantine WHERE resolution_status='open' AND reason_code LIKE 'auto_%'")
            counts['blocked_pairs'] = blocked[0][0]
        try:
            reconciled = await self.store.reconcile_ohlcv_manifests()
            counts['manifests_stale'] = int(reconciled.get('stale', 0))
        except Exception:
            counts['errors'] += 1
            logger.exception('OHLCV manifest reconciliation failed')
        self.state.update(counts, last_cycle=datetime.now(timezone.utc).isoformat())

    async def run(self):
        while True:
            try:
                await self.cycle()
            except Exception:
                self.state['errors'] += 1
                logger.exception('Automatic quality cycle failed')
            await asyncio.sleep(self.interval)
