'use client';

/**
 * «متابعة QA والتقرير الحي» — MASTER PROMPT V4.1 §16.4.
 *
 * Live QA progress page backed by the ISOLATED store qa/progress/state.json
 * (served read-only via /api/qa-progress). Never touches the trading DuckDB.
 * Requires an authenticated nexus-token (same gate as /nexus).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';

interface Results { pass: number; fail: number; blocked: number; not_tested: number; not_applicable: number }
interface Screen { screen_id: string; name: string; route: string; phase: string; work_status: string; elements: number; menus: number; tests_total: number; results: Results; issues: number; updated_at: string | null }
interface Issue { issue_id: string; screen_id: string; element_id: string; severity: string; desc: string; root: string; fix: string; retest: string; status: string; evidence: string }
interface Phase { id: string; status_ar: string; status: string; owner: string; note: string }
interface Agent { agent_id: string; role: string; task: string; screen: string; status: string; result: string; updated_at: string }
interface Menu { menu_id: string; screen_id: string; name: string; kind: string; options: number; searchable: boolean; status_ar: string }
interface Element { element_id: string; screen_id: string; name: string; type: string; component: string; status_ar: string }
interface Integration { screen_id: string; component: string; channel: string; source: string; result_ar: string }
interface QaState {
  meta?: { last_update?: string };
  summary?: Record<string, number>;
  phases?: Phase[]; screens?: Screen[]; issues?: Issue[]; agents?: Agent[];
  menus?: Menu[]; elements?: Element[]; integrations?: Integration[];
  timeline?: { at: string; event: string }[];
}

const WORK_AR: Record<string, string> = {
  QUEUED: 'في الطابور', 'IN PROGRESS': 'جارٍ', COMPLETED: 'مكتمل', BLOCKED: 'محظور',
};
const SEV_COLOR: Record<string, string> = {
  CRITICAL: 'text-neon-red', HIGH: 'text-neon-red', MEDIUM: 'text-amber-300', LOW: 'text-text-muted', INFO: 'text-text-muted',
};

function Badge({ children, tone = 'muted' }: { children: React.ReactNode; tone?: 'ok' | 'bad' | 'warn' | 'muted' }) {
  const cls = {
    ok: 'bg-emerald-400/10 border-emerald-400/30 text-emerald-300',
    bad: 'bg-red-400/10 border-red-400/30 text-neon-red',
    warn: 'bg-amber-400/10 border-amber-400/30 text-amber-300',
    muted: 'bg-white/5 border-border-primary text-text-muted',
  }[tone];
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-bold border ${cls}`}>{children}</span>;
}

export default function QaProgressPage() {
  const router = useRouter();
  const [auth, setAuth] = useState<'checking' | 'ready' | 'error'>('checking');
  const [state, setState] = useState<QaState | null>(null);
  const [err, setErr] = useState('');
  const [fScreen, setFScreen] = useState('');
  const [fPhase, setFPhase] = useState('');
  const [fWork, setFWork] = useState('');
  const [fSev, setFSev] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('nexus-token');
    if (!token) { router.replace('/login'); return; }
    apiClient.getMe().then(() => setAuth('ready'))
      .catch(() => { localStorage.removeItem('nexus-token'); router.replace('/login'); });
  }, [router]);

  const refresh = useCallback(async () => {
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('nexus-token') : null;
      const res = await fetch('/api/qa-progress', {
        cache: 'no-store',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(String(res.status));
      setState(await res.json());
      setErr('');
    } catch {
      setErr('تعذر قراءة مخزن المتابعة');
    }
  }, []);

  useEffect(() => {
    if (auth !== 'ready') return;
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [auth, refresh]);

  const s = state?.summary ?? {};
  const screens = useMemo(() => (state?.screens ?? []).filter((x) =>
    (!fScreen || x.screen_id === fScreen) && (!fPhase || x.phase === fPhase) && (!fWork || x.work_status === fWork),
  ), [state, fScreen, fPhase, fWork]);
  const issues = useMemo(() => (state?.issues ?? []).filter((x) =>
    (!fScreen || x.screen_id === fScreen) && (!fSev || x.severity === fSev),
  ), [state, fScreen, fSev]);

  if (auth === 'checking') return <div className="grid h-screen place-items-center bg-bg-primary text-xs text-text-muted">جارٍ التحقق من الحساب…</div>;

  const exportReport = () => {
    const blob = new Blob([JSON.stringify(state, null, 1)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'qa_final_report.json'; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-bg-primary text-text-primary p-4 sm:p-6" dir="rtl">
      <header className="flex flex-wrap items-center gap-3 mb-4">
        <h1 className="text-lg font-black gradient-text">متابعة QA والتقرير الحي</h1>
        <Badge tone="warn">MASTER PROMPT V4.1</Badge>
        <span className="text-[10px] text-text-muted">
          آخر تحديث: {state?.meta?.last_update ?? '—'}
        </span>
        <div className="flex-1" />
        <button type="button" onClick={refresh} className="neon-button px-3 py-1.5 text-xs">تحديث الآن</button>
        <button type="button" onClick={exportReport} className="neon-button px-3 py-1.5 text-xs">تصدير التقرير</button>
        <a href="/nexus" className="neon-button px-3 py-1.5 text-xs">العودة للوحة</a>
      </header>

      {err && <p role="alert" className="text-xs text-neon-red mb-3">{err}</p>}

      {/* ملخص حي */}
      <section className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 mb-5">
        {[
          ['الوحدات', s.screens_total ?? 0, 'muted'], ['مكتملة', s.work_completed ?? 0, 'ok'],
          ['جارية', s.work_in_progress ?? 0, 'warn'], ['محظورة', s.work_blocked ?? 0, 'bad'],
          ['PASS', s.pass ?? 0, 'ok'], ['FAIL', s.fail ?? 0, 'bad'],
          ['مختبرة', s.tests_executed ?? 0, 'muted'], ['لا ينطبق', s.not_applicable ?? 0, 'muted'],
        ].map(([label, val, tone]) => (
          <div key={String(label)} className="rounded-lg border border-border-primary bg-bg-secondary/60 p-3">
            <div className="text-[10px] text-text-muted mb-1">{label}</div>
            <div className="text-xl font-black">
              <Badge tone={tone as 'ok' | 'bad' | 'warn' | 'muted'}>{String(val)}</Badge>
            </div>
          </div>
        ))}
      </section>

      {/* المراحل */}
      <section className="mb-5">
        <h2 className="text-sm font-bold text-amber-300 mb-2">مراحل التنفيذ</h2>
        <div className="flex flex-wrap gap-1.5">
          {(state?.phases ?? []).map((p) => (
            <div key={p.id} className="rounded border border-border-primary bg-bg-secondary/60 px-2 py-1">
              <span className="text-[11px] font-bold">{p.id}</span>{' '}
              <Badge tone={p.status === 'COMPLETED' ? 'ok' : p.status === 'IN_PROGRESS' ? 'warn' : p.status === 'BLOCKED' ? 'bad' : 'muted'}>
                {p.status_ar}
              </Badge>
              {p.note && <span className="text-[10px] text-text-muted mr-1">— {p.note}</span>}
            </div>
          ))}
        </div>
      </section>

      {/* فلاتر */}
      <section className="flex flex-wrap gap-2 mb-3">
        <select value={fScreen} onChange={(e) => setFScreen(e.target.value)} aria-label="فلتر الشاشة"
          className="rounded border border-border-primary bg-bg-secondary px-2 py-1 text-xs">
          <option value="">كل الشاشات</option>
          {(state?.screens ?? []).map((x) => <option key={x.screen_id} value={x.screen_id}>{x.screen_id} — {x.name}</option>)}
        </select>
        <select value={fPhase} onChange={(e) => setFPhase(e.target.value)} aria-label="فلتر المرحلة"
          className="rounded border border-border-primary bg-bg-secondary px-2 py-1 text-xs">
          <option value="">كل المراحل</option>
          {['QUEUED', 'MAP', 'INSPECT', 'TEST', 'DIAGNOSE', 'REPAIR', 'RETEST', 'REPORT'].map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
        <select value={fWork} onChange={(e) => setFWork(e.target.value)} aria-label="فلتر حالة العمل"
          className="rounded border border-border-primary bg-bg-secondary px-2 py-1 text-xs">
          <option value="">كل حالات العمل</option>
          {Object.entries(WORK_AR).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={fSev} onChange={(e) => setFSev(e.target.value)} aria-label="فلتر الشدة"
          className="rounded border border-border-primary bg-bg-secondary px-2 py-1 text-xs">
          <option value="">كل الشدات</option>
          {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'].map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      </section>

      {/* جدول الشاشات */}
      <section className="mb-5 overflow-x-auto">
        <h2 className="text-sm font-bold text-amber-300 mb-2">جدول الشاشات والوحدات</h2>
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr className="text-text-muted border-b border-border-primary">
              {['المعرف', 'الشاشة', 'المسار', 'المرحلة', 'حالة العمل', 'عناصر', 'قوائم', 'اختبارات', 'PASS', 'FAIL', 'محظور', 'غير مختبر', 'لا ينطبق', 'عيوب'].map((h) => <th key={h} className="px-2 py-1.5 text-right whitespace-nowrap">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {screens.map((x) => (
              <tr key={x.screen_id} className="border-b border-border-primary/50 hover:bg-white/[0.03]">
                <td className="px-2 py-1.5 font-mono">{x.screen_id}</td>
                <td className="px-2 py-1.5">{x.name}</td>
                <td className="px-2 py-1.5 font-mono text-[10px] text-text-muted">{x.route}</td>
                <td className="px-2 py-1.5">{x.phase}</td>
                <td className="px-2 py-1.5"><Badge tone={x.work_status === 'COMPLETED' ? 'ok' : x.work_status === 'IN PROGRESS' ? 'warn' : x.work_status === 'BLOCKED' ? 'bad' : 'muted'}>{WORK_AR[x.work_status] ?? x.work_status}</Badge></td>
                <td className="px-2 py-1.5">{x.elements}</td>
                <td className="px-2 py-1.5">{x.menus}</td>
                <td className="px-2 py-1.5">{x.tests_total}</td>
                <td className="px-2 py-1.5 text-emerald-300 font-bold">{x.results.pass}</td>
                <td className="px-2 py-1.5 text-neon-red font-bold">{x.results.fail}</td>
                <td className="px-2 py-1.5">{x.results.blocked}</td>
                <td className="px-2 py-1.5">{x.results.not_tested}</td>
                <td className="px-2 py-1.5 text-text-muted">{x.results.not_applicable}</td>
                <td className="px-2 py-1.5">{x.issues}</td>
              </tr>
            ))}
            {screens.length === 0 && <tr><td colSpan={14} className="px-2 py-4 text-center text-text-muted">لا توجد وحدات مطابقة للفلاتر بعد.</td></tr>}
          </tbody>
        </table>
      </section>

      {/* المشكلات */}
      <section className="mb-5">
        <h2 className="text-sm font-bold text-amber-300 mb-2">جدول المشكلات</h2>
        <div className="space-y-1.5">
          {issues.map((i) => (
            <div key={i.issue_id} className="rounded border border-border-primary bg-bg-secondary/60 p-2 text-[11px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono">{i.issue_id}</span>
                <Badge tone={i.severity === 'CRITICAL' || i.severity === 'HIGH' ? 'bad' : i.severity === 'MEDIUM' ? 'warn' : 'muted'}>{i.severity}</Badge>
                <span className="font-mono text-text-muted">{i.screen_id}/{i.element_id}</span>
                <span className="text-text-muted">الحالة: {i.status}</span>
              </div>
              <p className="mt-1">{i.desc}</p>
              {i.root && <p className="text-text-muted">السبب الجذري: {i.root}</p>}
              {i.fix && <p className="text-emerald-300/80">الإصلاح: {i.fix}</p>}
              {i.retest && <p className="text-text-muted">إعادة الاختبار: {i.retest}</p>}
            </div>
          ))}
          {issues.length === 0 && <p className="text-xs text-text-muted">لا مشكلات مسجلة بعد.</p>}
        </div>
      </section>

      {/* القوائم + العناصر + التكامل */}
      <section className="grid lg:grid-cols-3 gap-4 mb-5">
        <div>
          <h2 className="text-sm font-bold text-amber-300 mb-2">القوائم</h2>
          {(state?.menus ?? []).map((m) => (
            <div key={m.menu_id} className="rounded border border-border-primary bg-bg-secondary/60 p-2 mb-1.5 text-[11px]">
              <span className="font-mono">{m.menu_id}</span> — {m.name} · {m.kind} · {m.options} خيار{m.searchable ? ' · بحث' : ''} · <Badge tone={m.status_ar === 'ناجح' ? 'ok' : 'muted'}>{m.status_ar}</Badge>
            </div>
          ))}
          {(state?.menus ?? []).length === 0 && <p className="text-xs text-text-muted">—</p>}
        </div>
        <div>
          <h2 className="text-sm font-bold text-amber-300 mb-2">العناصر</h2>
          {(state?.elements ?? []).slice(-30).map((e) => (
            <div key={e.element_id + e.screen_id} className="rounded border border-border-primary bg-bg-secondary/60 p-2 mb-1.5 text-[11px]">
              <span className="font-mono">{e.element_id}</span> — {e.name} · {e.type} · <Badge tone={e.status_ar === 'ناجح' ? 'ok' : e.status_ar === 'فاشل' ? 'bad' : 'muted'}>{e.status_ar}</Badge>
            </div>
          ))}
          {(state?.elements ?? []).length === 0 && <p className="text-xs text-text-muted">—</p>}
        </div>
        <div>
          <h2 className="text-sm font-bold text-amber-300 mb-2">التكامل</h2>
          {(state?.integrations ?? []).map((i, idx) => (
            <div key={idx} className="rounded border border-border-primary bg-bg-secondary/60 p-2 mb-1.5 text-[11px]">
              <span className="font-mono">{i.component}</span> · {i.channel} · <Badge tone={i.result_ar === 'ناجح' ? 'ok' : 'muted'}>{i.result_ar}</Badge>
              {i.source && <div className="text-text-muted text-[10px]">المصدر: {i.source}</div>}
            </div>
          ))}
          {(state?.integrations ?? []).length === 0 && <p className="text-xs text-text-muted">—</p>}
        </div>
      </section>

      {/* نشاط الوكلاء + السجل الزمني */}
      <section className="grid lg:grid-cols-2 gap-4">
        <div>
          <h2 className="text-sm font-bold text-amber-300 mb-2">سجل نشاط الوكلاء</h2>
          {(state?.agents ?? []).map((g) => (
            <div key={g.agent_id} className="rounded border border-border-primary bg-bg-secondary/60 p-2 mb-1.5 text-[11px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold">{g.role}</span>
                <Badge tone={g.status === 'COMPLETED' ? 'ok' : g.status === 'IN PROGRESS' ? 'warn' : 'muted'}>{g.status}</Badge>
                <span className="font-mono text-text-muted">{g.screen}</span>
                <span className="text-[10px] text-text-muted">{g.updated_at}</span>
              </div>
              <p>{g.task}</p>
              {g.result && <p className="text-text-muted">{g.result}</p>}
            </div>
          ))}
        </div>
        <div>
          <h2 className="text-sm font-bold text-amber-300 mb-2">السجل الزمني</h2>
          <div className="rounded border border-border-primary bg-bg-secondary/60 p-2 max-h-64 overflow-y-auto">
            {(state?.timeline ?? []).slice().reverse().map((t, idx) => (
              <div key={idx} className="text-[11px] mb-1">
                <span className="font-mono text-text-muted">{t.at}</span> — {t.event}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
