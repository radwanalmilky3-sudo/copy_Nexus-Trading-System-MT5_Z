'use client';

/**
 * Live development log (owner 2026-11-07) — replaces the stale manual
 * DASHBOARD_STATE snapshot. Reads the real repository via /git-dev-state:
 * latest commits, tree cleanliness, and the last recorded test gates.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, GitCommitHorizontal, RefreshCcw } from "lucide-react";
import { cn } from '@/lib/utils';

const POLL_MS = 30_000;
const STALE_MS = 10 * 60 * 1000;
const DATE_LOCALE = 'ar-SA-u-ca-gregory-nu-latn';

type Commit = { hash: string; subject: string; date: string; author: string };
type GitDevState = {
  generated_at: string;
  repo: string;
  branch: string;
  head: { hash: string; short: string; subject: string; date: string; author: string };
  commits: Commit[];
  dirty: { count: number; files: { status: string; path: string }[] };
  last_gates: string | null;
  source: string;
};

function rel(iso: string, now: number): string {
  const minutes = Math.round((new Date(iso).getTime() - now) / 60_000);
  const rtf = new Intl.RelativeTimeFormat('ar', { numeric: 'auto' });
  if (Math.abs(minutes) < 60) return rtf.format(minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return rtf.format(hours, 'hour');
  return new Date(iso).toLocaleDateString(DATE_LOCALE);
}

export default function GitDevLogView() {
  const [state, setState] = useState<GitDevState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [showDirty, setShowDirty] = useState(false);
  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const res = await fetch('/git-dev-state', { cache: 'no-store' });
      if (!res.ok) throw new Error(res.status === 503 ? 'git_unavailable' : `HTTP ${res.status}`);
      const data = (await res.json()) as GitDevState;
      if (!aliveRef.current) return;
      setState(data);
      setError(null);
    } catch (err) {
      if (!aliveRef.current) return;
      setError(err instanceof Error && err.message === 'git_unavailable'
        ? 'تعذر قراءة المستودع (git غير متاح من خدمة الداشبورد).'
        : `تعذر جلب سجل التطوير الحي (${err instanceof Error ? err.message : 'خطأ غير معروف'}).`);
    } finally {
      if (aliveRef.current) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    void load();
    const t = setInterval(() => void load(), POLL_MS);
    return () => { aliveRef.current = false; clearInterval(t); };
  }, [load]);

  const now = state ? new Date(state.generated_at).getTime() : Date.now();
  const stale = state ? Date.now() - new Date(state.generated_at).getTime() > STALE_MS : false;

  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-3 p-4" dir="rtl">
      <div className="flex flex-wrap items-start justify-between gap-3 border border-border-primary bg-bg-secondary/50 p-4">
        <div>
          <div className="flex items-center gap-2">
            <GitCommitHorizontal className="h-4 w-4 text-neon-cyan" />
            <h2 className="text-[13px] font-mono font-bold text-text-primary">متابعة التطوير — سجل حي من المستودع</h2>
          </div>
          <p className="mt-1 max-w-3xl text-[10px] font-mono leading-5 text-text-muted">
            يقرأ المستودع مباشرة (git log + حالة الشجرة) — لا ملفات يدوية ولا لقطات تتقادم.
            آخر ما دُفع إلى main يظهر هنا فوراً.
          </p>
        </div>
        <button
          onClick={() => void load()}
          disabled={refreshing}
          className="flex items-center gap-1.5 border border-neon-cyan/30 bg-neon-cyan/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-cyan hover:bg-neon-cyan/20 disabled:opacity-50"
        >
          <RefreshCcw className={cn('h-3 w-3', refreshing && 'animate-spin')} />
          تحديث
        </button>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-lg border border-neon-red/30 bg-neon-red/5 px-3 py-2 text-[10px] font-mono text-neon-red">
          <AlertCircle className="h-3.5 w-3.5" /> {error}
        </div>
      )}

      {state && (
        <>
          <div className="grid gap-2 sm:grid-cols-3">
            <div className={cn('rounded border px-3 py-2', stale ? 'border-neon-gold/40 bg-neon-gold/5' : 'border-neon-green/30 bg-neon-green/5')}>
              <div className="text-[9px] font-mono text-text-muted">الفرع / آخر دفعة</div>
              <div className="mt-1 flex items-center gap-1.5 text-[10px] font-mono font-bold text-text-primary" dir="ltr">
                {state.branch} @ {state.head.short}
              </div>
              <div className="text-[9px] font-mono text-text-muted">{rel(state.head.date, now)}</div>
            </div>
            <div className={cn('rounded border px-3 py-2', state.dirty.count > 0 ? 'border-neon-gold/40 bg-neon-gold/5' : 'border-neon-green/30 bg-neon-green/5')}>
              <div className="flex items-center gap-1.5 text-[9px] font-mono text-text-muted">
                {state.dirty.count > 0 ? <AlertCircle className="h-3 w-3 text-neon-gold" /> : <CheckCircle2 className="h-3 w-3 text-neon-green" />}
                شجرة العمل
              </div>
              <div className="mt-1 text-[10px] font-mono font-bold text-text-primary">
                {state.dirty.count > 0 ? `${state.dirty.count} ملف غير ملتزم` : 'نظيفة — كل شيء ملتزم ومدفوع'}
              </div>
              {state.dirty.count > 0 && (
                <button onClick={() => setShowDirty((v) => !v)} className="mt-1 text-[9px] font-mono text-neon-cyan underline">
                  {showDirty ? 'إخفاء الملفات' : 'عرض الملفات'}
                </button>
              )}
            </div>
            <div className="rounded border border-border-primary/60 bg-bg-secondary/30 px-3 py-2">
              <div className="text-[9px] font-mono text-text-muted">بوابات آخر commit</div>
              <div className="mt-1 text-[10px] font-mono text-text-secondary" dir="ltr">
                {state.last_gates ?? '—'}
              </div>
            </div>
          </div>

          {showDirty && state.dirty.count > 0 && (
            <div className="rounded border border-neon-gold/30 bg-neon-gold/5 p-3">
              {state.dirty.files.map((f, i) => (
                <div key={i} className="text-[9px] font-mono text-text-muted" dir="ltr">
                  {f.status} {f.path}
                </div>
              ))}
            </div>
          )}

          <div className="overflow-hidden rounded border border-border-primary">
            {state.commits.map((c) => (
              <div key={c.hash} className="border-b border-border-primary/40 px-3 py-2 last:border-b-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[9px] font-mono font-bold text-neon-cyan" dir="ltr">{c.hash}</span>
                  <span className="text-[10px] leading-5 text-text-primary">{c.subject}</span>
                </div>
                <div className="mt-0.5 flex gap-2 text-[9px] font-mono text-text-muted">
                  <span>{rel(c.date, now)}</span>
                  <span dir="ltr">{c.author}</span>
                  <span dir="ltr">{new Date(c.date).toLocaleString(DATE_LOCALE)}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="text-[9px] font-mono text-text-muted">
            المصدر: git حي ({state.repo}) · آخر تحديث {new Date(state.generated_at).toLocaleString(DATE_LOCALE)} · تحديث تلقائي كل 30 ثانية
            {stale && <b className="text-neon-gold"> — البيانات أقدم من 10 دقائق (خدمة الداشبورد قد تكون متوقفة)</b>}
          </div>
        </>
      )}
    </div>
  );
}
