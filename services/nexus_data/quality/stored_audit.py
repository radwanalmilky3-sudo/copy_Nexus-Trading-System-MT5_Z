"""Snapshot-bound audits. Only evidence metadata is written; market rows are untouched."""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from .session_quality import combined_rows,series_hash,gap_summary,calendar_summary,current_context,MT5_SOURCES
from .session_calendar import calendar_dependency_hash

SCOPE = 'stored_ohlcv_basic_v1'
MAX_ROWS = 100_000
INTERVALS = {'M1': 60, 'M5': 300, 'M15': 900, 'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400}
SNAPSHOT_SQL = ('SELECT timestamp,open,high,low,close,volume,COALESCE(revision,0),available_at,quality '
                'FROM ohlcv WHERE symbol=? AND timeframe=? AND source=? '
                'ORDER BY timestamp,open,high,low,close,volume,COALESCE(revision,0),available_at,quality')


def snapshot_hash(rows: list, symbol: str, timeframe: str, source: str) -> str:
    def encode(value):
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return str(value)
    raw = json.dumps([symbol, timeframe, source, rows], default=encode, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def assess(rows: list, symbol: str, timeframe: str, source: str, now: datetime) -> dict:
    seconds = INTERVALS[timeframe]
    stamps = [row[0] for row in rows]
    numeric = lambda value: isinstance(value, (int, float)) and math.isfinite(value)
    invalid = sum(not (all(numeric(v) and v > 0 for v in row[1:5])
                      and row[3] <= min(row[1], row[4]) <= max(row[1], row[4]) <= row[2]) for row in rows)
    invalid_volume = sum(not numeric(row[5]) or row[5] < 0 for row in rows)
    duplicates = len(stamps) - len(set(stamps))
    forming = sum(stamp + timedelta(seconds=seconds) > now for stamp in stamps)
    gaps = sum((b - a).total_seconds() > seconds for a, b in zip(stamps, stamps[1:]))
    missing_availability = sum(row[7] is None for row in rows)
    flagged = sum(row[8] not in {'ok', 'passed'} for row in rows)
    freshness_limit = max(3600, seconds * 3)
    old = bool(stamps and (now - (stamps[-1] + timedelta(seconds=seconds))).total_seconds() > freshness_limit)
    checks = dict(ohlc_invariants=invalid == 0, valid_volume=invalid_volume == 0,
                  unique_timestamps=duplicates == 0, closed_bars=forming == 0,
                  ingestion_quality_clear=flagged == 0, continuous_observed_intervals=gaps == 0,
                  availability_recorded=missing_availability == 0, recent_observation=not old,
                  temporal_sample=len(rows) >= 2)
    errors = []
    warnings = []
    for count, message in [(invalid, 'شموع تخالف صحة الأسعار أو حدود OHLC'),
                           (invalid_volume, 'قيم حجم غير صالحة'), (duplicates, 'توقيتات شموع مكررة'),
                           (forming, 'شموع غير مكتملة أو مؤرخة في المستقبل')]:
        if count:
            errors.append(f'{message}: {count}')
    if flagged:
        warnings.append(f'صفوف تحمل علامة جودة إدخال غير مؤكدة: {flagged}')
    if gaps:
        warnings.append(f'فواصل زمنية غير مصنفة: {gaps}؛ قد تشمل إغلاق السوق أو انقطاع الجلب؛ لم يُطبَّق تقويم وسيط')
    if missing_availability:
        warnings.append(f'صفوف بلا وقت إتاحة موثق: {missing_availability}؛ لا تثبت أهلية point-in-time')
    if old:
        warnings.append('آخر شمعة أقدم من حد الحداثة؛ قد يكون السوق مغلقًا، ولا يعني ذلك فساد السعر')
    if len(rows) < 2:
        warnings.append('عدد الصفوف لا يكفي لفحص الاستمرارية الزمنية')
    status = 'failed' if errors else 'warning' if warnings else 'passed'
    # Ingestion quality flags are warnings, not fabricated hard price failures.
    return dict(scope=SCOPE, symbol=symbol, timeframe=timeframe, source=source,
                status=status, rows_checked=len(rows), content_hash=snapshot_hash(rows, symbol, timeframe, source),
                checks=checks, issues=errors, warnings=warnings,
                metrics=dict(invalid_ohlc=invalid, invalid_volume=invalid_volume, duplicates=duplicates,
                             forming_or_future=forming, unclassified_gaps=gaps, missing_availability=missing_availability,
                             freshness_limit_seconds=freshness_limit),
                checked_at=now.isoformat(), expires_at=(now + timedelta(seconds=freshness_limit)).isoformat(),
                limitations=['الفحص للصفوف المخزنة فقط؛ لا يثبت اكتمال فترة مطلوبة أو تطابقها مع الوسيط',
                             'ليس اعتمادًا للتداول أو شهادة تكاليف أو صلاحية تدريب نموذج'])


async def audit_stored_ohlcv(store: Any, symbol: str, timeframe: str, source: str, *, now: datetime | None = None, calendar=None) -> dict:
    if timeframe not in INTERVALS or any(not isinstance(v, str) or not v.strip() or len(v) > 160 for v in (symbol, source)):
        raise ValueError('Invalid stored dataset selection')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')

    def execute():
        conn = store._conn
        selection = (symbol, timeframe, source)
        dataset_id = f'ohlcv:{symbol}:{timeframe}:{source}'
        conn.execute((Path(__file__).resolve().parents[1] / 'migrations/research_lineage_001.sql').read_text(encoding='utf-8'))
        unresolved = conn.execute("SELECT COUNT(*) FROM quarantine WHERE dataset_id=? AND resolution_status='open' AND reason_code LIKE 'auto_%'", (dataset_id,)).fetchone()[0]
        count = conn.execute('SELECT COUNT(*) FROM ohlcv WHERE symbol=? AND timeframe=? AND source=?', selection).fetchone()[0]
        if not count and not unresolved:
            raise ValueError('No stored bars for selection')
        if count > MAX_ROWS:
            raise ValueError(f'Audit selection exceeds {MAX_ROWS} rows; no partial certificate produced')
        rows = conn.execute(SNAPSHOT_SQL, selection).fetchall()
        report = assess(rows, symbol, timeframe, source, now)
        selected_calendar=calendar if calendar is not None else current_context(store,symbol,now)
        series=combined_rows(conn,symbol,timeframe) if source in MT5_SOURCES else []
        gaps=gap_summary(rows,series,INTERVALS[timeframe],selected_calendar if source in MT5_SOURCES else None,now)
        report.update(calendar_summary=calendar_summary(selected_calendar),gap_summary=gaps,
                      calendar_dependency_hash=calendar_dependency_hash(selected_calendar),series_dependency_hash=series_hash(series))
        if source in MT5_SOURCES:
            report['warnings']=[w for w in report['warnings'] if not w.startswith('فواصل زمنية غير مصنفة:')]
            unresolved_gaps=gaps['unknown']+gaps['expected_quote_missing']
            report['checks']['continuous_observed_intervals']=unresolved_gaps==0
            if unresolved_gaps:
                report['warnings'].append(f'فترات شموع غير محسومة: {unresolved_gaps}؛ إغلاق موثّق: {gaps["confirmed_closed"]}؛ مغطاة بمسار MT5 آخر: {gaps["covered_elsewhere"]}')
            latest=max((r[0] for r in series if r[0]+timedelta(seconds=INTERVALS[timeframe])<=now),default=None)
            if latest and (now-latest-timedelta(seconds=INTERVALS[timeframe])).total_seconds()<=report['metrics']['freshness_limit_seconds']:
                report['warnings']=[w for w in report['warnings'] if not w.startswith('آخر شمعة أقدم')]
                report['checks']['recent_observation']=True
            report['status']='failed' if report['issues'] else 'warning' if report['warnings'] else 'passed'
        run_id = 'quality:' + uuid.uuid4().hex
        report.update(quality_run_id=run_id, dataset_id=dataset_id)
        report['checks']['quarantine_clear'] = unresolved == 0
        report['metrics']['unresolved_quarantine'] = unresolved
        if unresolved:
            report['status'] = 'failed'
            report['issues'].append(f'صفوف معزولة لم تُستعد من المصدر بعد: {unresolved}')
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True)
        conn.execute('BEGIN TRANSACTION')
        try:
            conn.execute('INSERT INTO datasets(dataset_id,dataset_name,source_system,grain) VALUES (?,?,?,?) '
                         'ON CONFLICT(dataset_id) DO NOTHING', (dataset_id, dataset_id, source, timeframe))
            conn.execute('INSERT INTO quality_runs(quality_run_id,dataset_id,contract_version,status,score,checks_total,'
                         'checks_passed,checks_failed,started_at,finished_at,summary_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                         (run_id, dataset_id, SCOPE, report['status'], sum(report['checks'].values()) / len(report['checks']),
                          len(report['checks']), sum(report['checks'].values()), len(report['checks']) - sum(report['checks'].values()),
                          now, now, payload))
            conn.execute('INSERT INTO research_artifacts(artifact_id,dataset_id,quality_run_id,artifact_type,artifact_name,'
                         'content_checksum,version,status,produced_by,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
                         (run_id + ':report', dataset_id, run_id, 'validation_report', f'{symbol}/{timeframe} · {source}',
                          hashlib.sha256(payload.encode()).hexdigest(), SCOPE, 'available', 'nexus-data:stored-audit', payload))
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        return report

    return await store._execute_locked(execute)


async def latest_quality(store: Any, symbol: str, timeframe: str, source: str) -> dict | None:
    """Compare an immutable report with the current group while holding the owner lock."""
    def execute():
        conn = store._conn
        if not conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name='quality_runs' AND table_schema='main'").fetchone():
            return None
        found = conn.execute('SELECT quality_run_id,summary_json FROM quality_runs WHERE dataset_id=? AND contract_version=? '
                             'ORDER BY finished_at DESC,quality_run_id DESC LIMIT 1',
                             (f'ohlcv:{symbol}:{timeframe}:{source}', SCOPE)).fetchone()
        if not found:
            return None
        report = json.loads(found[1])
        rows = conn.execute(SNAPSHOT_SQL, (symbol, timeframe, source)).fetchall()
        current = snapshot_hash(rows, symbol, timeframe, source)
        unresolved = conn.execute("SELECT COUNT(*) FROM quarantine WHERE dataset_id=? AND resolution_status='open' AND reason_code LIKE 'auto_%'", (f'ohlcv:{symbol}:{timeframe}:{source}',)).fetchone()[0]
        quarantine_current = unresolved == report.get('metrics', {}).get('unresolved_quarantine', 0)
        verified_at = datetime.now(timezone.utc)
        selected_calendar=current_context(store,symbol,verified_at)
        dependencies_current=(report.get('calendar_dependency_hash')==calendar_dependency_hash(selected_calendar)
                              and report.get('series_dependency_hash')==series_hash(combined_rows(conn,symbol,timeframe) if source in MT5_SOURCES else []))
        expired = verified_at > datetime.fromisoformat(report['expires_at'])
        return dict(quality_run_id=found[0], status=report['status'], checked_at=report['checked_at'],
                    snapshot_verified_at=verified_at.isoformat(),
                    expires_at=report['expires_at'], snapshot_current=current == report['content_hash'] and quarantine_current and dependencies_current,
                    expired=expired, content_hash=report['content_hash'], current_content_hash=current,
                    issues=report['issues'], warnings=report['warnings'], scope=SCOPE,
                    calendar_summary=calendar_summary(selected_calendar),gap_summary=report.get('gap_summary'))
    return await store._execute_locked(execute)
