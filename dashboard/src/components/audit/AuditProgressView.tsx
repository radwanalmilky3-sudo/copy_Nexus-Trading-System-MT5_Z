'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, Clock3, RefreshCw } from 'lucide-react';
import { withRequestTimeout } from '@/lib/request-timeout';
import AuditSection from './AuditSection';
import AuditStatusBadge from './AuditStatusBadge';
import { loadAuditEvidence } from './evidence';
import type { AuditEvidence, AuditSnapshot } from './types';

function formatDate(value?: string) {
  if (!value) return 'غير متاح';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ar-SA-u-ca-gregory-nu-latn', { dateStyle: 'medium', timeStyle: 'short' });
}

export default function AuditProgressView() {
  const [snapshot, setSnapshot] = useState<AuditSnapshot | null>(null);
  const [evidence, setEvidence] = useState<AuditEvidence | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [stateLoading, setStateLoading] = useState(true);
  const [evidenceLoading, setEvidenceLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [query, setQuery] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setStateLoading(true); setEvidenceLoading(true);
    setSnapshot(null); setEvidence(null); setStateError(null); setEvidenceError(null);
    void withRequestTimeout(async (signal) => {
      const response = await fetch('/progress-state', { cache: 'no-store', signal });
      if (!response.ok) throw new Error(`تعذر تحميل الخطة: HTTP ${response.status}`);
      const data = await response.json() as AuditSnapshot;
      if (!data || !Array.isArray(data.items)) throw new Error('صيغة خطة التدقيق غير صالحة');
      return data;
    }, controller.signal).then((data) => {
      if (!controller.signal.aborted) setSnapshot(data);
    }).catch((cause) => {
      if (!controller.signal.aborted) setStateError(cause instanceof Error ? cause.message : 'تعذر تحميل الخطة');
    }).finally(() => { if (!controller.signal.aborted) setStateLoading(false); });
    void loadAuditEvidence(controller.signal).then((data) => {
      if (!controller.signal.aborted) setEvidence(data);
    }).catch((cause) => {
      if (!controller.signal.aborted) setEvidenceError(cause instanceof Error ? cause.message : 'تعذر تحميل الأدلة');
    }).finally(() => { if (!controller.signal.aborted) setEvidenceLoading(false); });
    return () => controller.abort();
  }, [refresh]);
  const items = snapshot?.items ?? [];
  const roots = useMemo(() => items.filter((item) => !item.parent_id || !items.some((parent) => parent.id === item.parent_id)), [items]);
  const agents = roots.filter((item) => item.id.startsWith('nexus-') || item.id === 'frontend');
  const checkpoints = items.filter((item) => item.status === 'in_progress' || item.is_current);
  const dbEvidence = items.filter((item) => typeof item.database === 'number');
  const files = (evidence?.evidence.files ?? []).filter((file) => file.path.toLowerCase().includes(query.toLowerCase()));
  const currentTask = typeof snapshot?.current_task === 'object' ? snapshot.current_task?.name : snapshot?.current_task;
  return <div dir="rtl" className="min-h-full bg-bg-primary p-3 sm:p-5"><div className="mx-auto max-w-[1600px] space-y-4">
    <header className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-mono text-neon-cyan">NEXUS / AUDIT CONTROL</p><h1 className="mt-1 text-xl font-black">لوحة تقدم التدقيق</h1><p className="text-xs text-text-muted">الخطة منفصلة عن ملفات الأدلة وبصماتها المقروءة فعليًا.</p></div><button type="button" onClick={() => setRefresh((n) => n + 1)} className="neon-button px-3 py-2 text-xs"><RefreshCw size={13} /> تحديث</button></header>
    {stateLoading && <p role="status" className="text-xs text-text-muted">جارٍ تحميل الخطة…</p>}
    {evidenceLoading && <p role="status" className="text-xs text-text-muted">جارٍ حساب وقراءة بصمات الأدلة…</p>}
    {[stateError, evidenceError].filter(Boolean).map((error, i) => <div key={i} role="alert" className="flex items-center gap-2 rounded border border-neon-red/30 p-3 text-xs text-neon-red"><AlertCircle size={14} />{error}</div>)}
    {evidence?.status === 'degraded' && <p role="alert" className="text-xs text-neon-gold">مصدر التدقيق متدهور: {evidence.state.error || 'بعض الأدلة غير متاحة'}. لا تُعدّ هذه نتيجة تحقق ناجحة.</p>}
    <div className="grid gap-3 md:grid-cols-3">
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-4"><p className="text-xs text-text-muted">المهمة الحالية</p><p className="mt-2 text-sm text-neon-cyan">{currentTask || 'غير متاحة'}</p></div>
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-4"><p className="text-xs text-text-muted">تقدم الخطة المسجل · ليس نسبة نجاح الاختبارات</p><p className="mt-2 font-mono">{evidence ? `${evidence.state.progress.done}/${evidence.state.progress.total} · ${evidence.state.progress.completion_percent}%` : '—'}</p></div>
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-4"><p className="text-xs text-text-muted">ملفات الأدلة المقروءة</p><p className="mt-2 font-mono">{evidence?.evidence.count ?? '—'}</p><p className="mt-1 text-[10px] text-text-muted">آخر تحديث للخطة: {formatDate(snapshot?.last_updated)}</p></div>
    </div>
    <AuditSection title="بصمات ملفات الأدلة SHA-256" eyebrow="Live evidence / project_audit" icon="files" state={evidence ? (files.length ? 'ready' : 'empty') : 'unavailable'} emptyLabel="لا توجد ملفات مطابقة للبحث">
      <p className="mb-3 text-[10px] text-text-muted">المصدر: /api/audit/progress · بصمة المحتوى لا تعني نجاح اختباره. هذه ليست بصمات Git.</p>
      <p className="mb-3 break-all font-mono text-[10px]" dir="ltr">DASHBOARD_STATE.json: {evidence?.state.sha256 || 'unavailable'}</p>
      <div className="max-h-[480px] overflow-auto"><table className="w-full min-w-[800px] text-right text-[11px]"><thead><tr className="text-text-muted"><th className="p-2">الملف</th><th className="p-2">SHA-256</th><th className="p-2">الحجم بالبايت</th><th className="p-2">آخر تعديل</th><th className="p-2">حالة القراءة</th></tr></thead><tbody>{files.map((file) => <tr key={file.path} className="border-t border-border-primary/50"><td className="p-2 font-mono" dir="ltr">{file.path}</td><td className="max-w-[420px] break-all p-2 font-mono text-neon-cyan" dir="ltr">{file.sha256 || '—'}</td><td className="p-2 font-mono">{file.size_bytes ?? '—'}</td><td className="p-2">{formatDate(file.modified_at)}</td><td className="p-2">{file.error || 'مقروء'}</td></tr>)}</tbody></table></div>
    </AuditSection>
    <label className="block text-xs text-text-muted">بحث في أسماء ملفات الأدلة <input value={query} onChange={(e) => setQuery(e.target.value)} className="mr-2 rounded border border-border-primary bg-bg-secondary p-2" placeholder="اسم الملف" /></label>
    <div className="grid gap-4 xl:grid-cols-2">
      <AuditSection title="الخطة والوكلاء" eyebrow="Recorded plan — not live agent health" icon="plan" state={snapshot ? (agents.length ? 'ready' : 'empty') : 'unavailable'}><div className="space-y-2">{agents.map((item) => <div key={item.id} className="flex justify-between gap-3 rounded border border-border-primary p-3 text-xs"><span>{item.name}</span><AuditStatusBadge status={item.status} /></div>)}</div></AuditSection>
      <AuditSection title="نقاط التحقق" eyebrow="Checkpoints" icon="plan" state={snapshot ? (checkpoints.length ? 'ready' : 'empty') : 'unavailable'}><div className="space-y-2">{checkpoints.map((item) => <div key={item.id} className="flex items-center gap-2 text-xs"><Clock3 size={14} /><span className="flex-1">{item.name}</span><AuditStatusBadge status={item.status} /></div>)}</div></AuditSection>
      <AuditSection title="مؤشرات قاعدة البيانات في الخطة" eyebrow="Declared progress — not database verification" icon="database" state={snapshot ? (dbEvidence.length ? 'ready' : 'empty') : 'unavailable'}><p className="mb-3 text-[10px] text-text-muted">نسب تقدم مسجلة في الخطة؛ ليست نتيجة فحص قاعدة البيانات الحالية.</p><div className="space-y-2">{dbEvidence.map((item) => <div key={item.id} className="flex justify-between gap-3 text-xs"><span>{item.name}</span><span className="font-mono">{item.database}%</span></div>)}</div></AuditSection>
    </div>
  </div></div>;
}
