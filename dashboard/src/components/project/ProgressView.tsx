'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, AlertCircle, AlertTriangle, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import HierarchicalTable, { ProgressItem } from '@/components/progress/HierarchicalTable';

type State = {
  last_updated: string;
  current_task: { id: string; name: string } | string;
  items: ProgressItem[];
};

type LoadError = 'network' | 'unavailable' | null;

const POLL_MS = 5000;
const STALE_MS = 30 * 60 * 1000;
const DATE_LOCALE = 'ar-SA-u-ca-gregory-nu-latn';

function formatDateAr(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(DATE_LOCALE, { dateStyle: 'medium', timeStyle: 'short' });
}

function relativeAr(iso: string, now: number): string {
  const minutes = Math.round((new Date(iso).getTime() - now) / 60_000);
  const rtf = new Intl.RelativeTimeFormat('ar', { numeric: 'auto' });
  if (Math.abs(minutes) < 60) return rtf.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return rtf.format(hours, 'hour');
  return rtf.format(Math.round(hours / 24), 'day');
}

export function ProgressView() {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<LoadError>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const aliveRef = useRef(true);
  const stateRef = useRef<State | null>(null);
  const etagRef = useRef<string | null>(null);
  const minuteRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    if (!aliveRef.current) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRefreshing(true);
    const minute = Math.floor(Date.now() / 60_000);
    if (minuteRef.current !== minute) {
      minuteRef.current = minute;
      setNow(Date.now());
    }
    try {
      const res = await fetch('/progress-state', { cache: 'no-cache', signal: controller.signal });
      if (res.status === 503) {
        setError('unavailable');
        return;
      }
      if (res.status === 304) {
        setError(null);
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const etag = res.headers.get('etag');
      const prev = stateRef.current;
      if (prev && etag && etag === etagRef.current) {
        void res.body?.cancel().catch(() => undefined);
      } else {
        const data = (await res.json()) as State;
        if (!aliveRef.current) return;
        if (etag) etagRef.current = etag;
        if (!prev || prev.last_updated !== data.last_updated) {
          stateRef.current = data;
          setState(data);
        }
      }
      setError(null);
    } catch (err) {
      const aborted = err instanceof Error && err.name === 'AbortError';
      if (aliveRef.current && !aborted) setError('network');
    } finally {
      if (aliveRef.current && !controller.signal.aborted) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer !== null) return;
      timer = setInterval(() => {
        void load();
      }, POLL_MS);
    };
    const stop = () => {
      if (timer === null) return;
      clearInterval(timer);
      timer = null;
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stop();
      } else {
        void load();
        start();
      }
    };

    void load();
    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [load]);

  const currentTaskId =
    typeof state?.current_task === 'object'
      ? state.current_task.id
      : state?.items.find((x) => x.status === 'in_progress' && x.start_time)?.id;
  const active =
    state?.items.find((x) => x.id === currentTaskId) ||
    state?.items.find((x) => x.status === 'in_progress' && x.start_time);

  const canFormat = now !== null && typeof window !== 'undefined';
  const startedAt = active?.start_time
    ? canFormat
      ? formatDateAr(active.start_time)
      : active.start_time
    : '–';
  const updatedLabel = state
    ? canFormat
      ? formatDateAr(state.last_updated)
      : state.last_updated
    : '–';
  const staleLabel =
    state && now !== null && now - new Date(state.last_updated).getTime() > STALE_MS
      ? relativeAr(state.last_updated, now)
      : null;
  const errorContent =
    error === 'unavailable' ? (
      <>
        ملف الحالة غير متاح — تأكد من وجود <bdi dir="ltr">project_audit/DASHBOARD_STATE.json</bdi> ثم أعد
        المحاولة
      </>
    ) : error === 'network' ? (
      <>تعذر قراءة حالة المشروع — تحقق من اتصال الشبكة ثم أعد المحاولة</>
    ) : null;

  return (
    <div dir="rtl" className="min-h-full bg-bg-primary p-3 sm:p-5">
      <div className="mx-auto max-w-[1600px] space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold text-text-primary">
              <Activity className="text-neon-cyan" size={19} />
              متابعة التطوير
            </h1>
            <p className="mt-1 text-[11px] text-text-muted">مصدر الحالة: project_audit/DASHBOARD_STATE.json</p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={refreshing}
            title="تحديث حالة المشروع"
            aria-label="تحديث حالة المشروع"
            className="rounded p-1 text-text-muted transition-colors hover:bg-bg-tertiary/40 hover:text-text-secondary disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RefreshCw size={15} className={cn('text-text-muted', refreshing && 'animate-spin')} />
          </button>
        </div>

        {staleLabel && (
          <div
            role="status"
            className="flex items-center gap-2 rounded border border-neon-gold/40 bg-neon-gold/10 px-3 py-2 text-[11px] text-neon-gold"
          >
            <AlertTriangle size={14} className="shrink-0" />
            <span>
              البيانات قديمة — آخر تحديث {staleLabel}؛ اضغط زر التحديث للحصول على أحدث حالة
            </span>
          </div>
        )}

        <section
          className="rounded border border-neon-cyan/25 bg-bg-secondary p-4"
          aria-busy={!state && !error}
        >
          {!state && !error ? (
            <div role="status" className="text-sm text-text-secondary">
              جارٍ تحميل حالة المشروع…
            </div>
          ) : (
            <>
              <div className="text-[10px] text-text-muted">المهمة الحالية قيد التنفيذ</div>
              <div className="mt-1 text-sm font-bold text-neon-cyan">
                {active?.name ||
                  (typeof state?.current_task === 'object'
                    ? state.current_task.name
                    : state?.current_task) ||
                  'لا توجد مهمة نشطة حاليًا — راجع قائمة المهام أدناه'}
              </div>
              <div className="mt-2 text-[10px] text-text-muted">
                البداية: {startedAt} · آخر تحديث: {updatedLabel}
              </div>
            </>
          )}
        </section>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded border border-neon-red/30 bg-neon-red/10 px-3 py-2 text-xs text-neon-red"
          >
            <AlertCircle size={14} className="shrink-0" />
            <span className="flex-1">{errorContent}</span>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded border border-neon-red/40 px-2 py-0.5 text-[10px] font-bold transition-all hover:bg-neon-red/20"
            >
              إعادة المحاولة
            </button>
          </div>
        )}

        {state && <HierarchicalTable items={state.items} currentTaskId={currentTaskId} />}
      </div>
    </div>
  );
}
