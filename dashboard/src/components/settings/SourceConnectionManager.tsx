'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, CheckCircle2, CircleOff, EyeOff, KeyRound, Pencil, Plus,
  RefreshCcw, Save, Search, ShieldCheck, Trash2, Wifi, X, Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const API = process.env.NEXT_PUBLIC_API_URL || '';

type SourceRow = {
  source_id: string;
  name_ar: string;
  name_en: string;
  organization?: string;
  category: string;
  transport: string;
  source_tier?: string;
  cost_label?: string;
  endpoint?: string;
  documentation_url?: string;
  enabled: boolean;
  official: boolean;
  custom: boolean;
  removable: boolean;
  auth_mode: 'none' | 'query' | 'header' | 'bearer';
  secret_env?: string | null;
  secret_name?: string | null;
  secret_optional?: boolean;
  secret_configured: boolean;
  secret_backend: string;
  polling_interval_sec: number;
  freshness_limit_sec: number;
  timeout_sec: number;
  analysis_mapping: 'health_only' | 'cross_asset' | 'flows';
  analysis_ready?: boolean;
  headers?: Record<string, string>;
  query_params?: Record<string, string>;
  runtime_health?: any;
  last_test?: any;
};

type FormState = {
  source_id: string;
  name_ar: string;
  name_en: string;
  organization: string;
  category: string;
  transport: string;
  endpoint: string;
  documentation_url: string;
  enabled: boolean;
  auth_mode: 'none' | 'query' | 'header' | 'bearer';
  secret_env: string;
  secret_name: string;
  secret_optional: boolean;
  secret: string;
  clear_secret: boolean;
  polling_interval_sec: number;
  freshness_limit_sec: number;
  timeout_sec: number;
  analysis_mapping: 'health_only' | 'cross_asset' | 'flows';
};

const emptyForm: FormState = {
  source_id: '', name_ar: '', name_en: '', organization: '', category: 'macro', transport: 'json',
  endpoint: '', documentation_url: '', enabled: true, auth_mode: 'none', secret_env: '', secret_name: '',
  secret_optional: true, secret: '', clear_secret: false, polling_interval_sec: 300,
  freshness_limit_sec: 900, timeout_sec: 15, analysis_mapping: 'health_only',
};

const statusAr: Record<string, string> = {
  healthy: 'سليم', config_required: 'يتطلب إعدادًا', degraded: 'متدهور', unknown: 'غير معروف',
  offline: 'معطل/غير متصل', unavailable: 'غير متاح', rate_limited: 'محدود مؤقتًا', disabled: 'معطل',
};

function sourceStatus(s: SourceRow) {
  if (!s.enabled) return 'disabled';
  return s.runtime_health?.health || s.last_test?.state || 'unknown';
}

function statusClass(status: string) {
  if (status === 'healthy') return 'border-neon-green/30 bg-neon-green/10 text-neon-green';
  if (status === 'config_required') return 'border-yellow-400/30 bg-yellow-400/10 text-yellow-400';
  if (status === 'degraded' || status === 'rate_limited') return 'border-orange-400/30 bg-orange-400/10 text-orange-300';
  if (status === 'offline' || status === 'unavailable' || status === 'disabled') return 'border-neon-red/30 bg-neon-red/10 text-neon-red';
  return 'border-border-secondary bg-bg-tertiary text-text-muted';
}

async function jsonFetch(url: string, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  const token = localStorage.getItem('nexus-token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const res = await fetch(url, { ...init, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.message || `${res.status} ${res.statusText}`);
  return body;
}

export default function SourceConnectionManager() {
  const [sources, setSources] = useState<SourceRow[]>([]);
  const [secretBackend, setSecretBackend] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [editor, setEditor] = useState<SourceRow | 'new' | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await jsonFetch(`${API}/api/fundamental/sources/manage`);
      setSources(Array.isArray(data.sources) ? data.sources : []);
      setSecretBackend(data.secret_backend || '');
    } catch (e) {
      setMessage(`تعذر تحميل إدارة المصادر: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const counts = useMemo(() => ({
    total: sources.length,
    healthy: sources.filter((s) => sourceStatus(s) === 'healthy').length,
    config: sources.filter((s) => sourceStatus(s) === 'config_required').length,
    disabled: sources.filter((s) => !s.enabled).length,
    analysis: sources.filter((s) => s.analysis_ready && s.enabled).length,
    free: sources.filter((s) => String(s.source_tier || '').startsWith('FREE_')).length,
  }), [sources]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return sources.filter((s) => {
      const st = sourceStatus(s);
      const matchFilter = filter === 'all' || (filter === 'enabled' ? s.enabled : filter === 'disabled' ? !s.enabled : st === filter);
      const hay = `${s.source_id} ${s.name_ar} ${s.name_en} ${s.category} ${s.endpoint || ''}`.toLowerCase();
      return matchFilter && (!q || hay.includes(q));
    });
  }, [sources, filter, query]);

  const edit = (s: SourceRow) => {
    setEditor(s);
    setForm({
      source_id: s.source_id, name_ar: s.name_ar || '', name_en: s.name_en || '', organization: s.organization || '',
      category: s.category || 'macro', transport: s.transport || 'json', endpoint: s.endpoint || '',
      documentation_url: s.documentation_url || '', enabled: s.enabled,
      auth_mode: s.auth_mode || 'none', secret_env: s.secret_env || '', secret_name: s.secret_name || '',
      secret_optional: s.secret_optional ?? true, secret: '', clear_secret: false,
      polling_interval_sec: s.polling_interval_sec || 300, freshness_limit_sec: s.freshness_limit_sec || 900,
      timeout_sec: s.timeout_sec || 15, analysis_mapping: s.analysis_mapping || 'health_only',
    });
  };

  const addNew = () => { setEditor('new'); setForm(emptyForm); };
  const closeEditor = () => { setEditor(null); setForm(emptyForm); };

  const saveSource = async (testAfter = false) => {
    try {
      const isNew = editor === 'new';
      const sid = form.source_id.trim().toLowerCase();
      if (!sid) throw new Error('معرّف المصدر مطلوب');
      const payload = { ...form, source_id: sid, secret: form.secret || undefined };
      await jsonFetch(isNew ? `${API}/api/fundamental/sources/manage` : `${API}/api/fundamental/sources/manage/${encodeURIComponent(sid)}`, {
        method: isNew ? 'POST' : 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      setMessage('تم حفظ إعدادات المصدر. المفاتيح لا تُعاد إلى الواجهة.');
      closeEditor();
      await load();
      if (testAfter) await testSource(sid);
    } catch (e) {
      setMessage(`فشل الحفظ: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const testSource = async (sid: string) => {
    setTesting(sid);
    try {
      const result = await jsonFetch(`${API}/api/fundamental/sources/manage/${encodeURIComponent(sid)}/test`, { method: 'POST' });
      setMessage(result.ok
        ? `✅ ${sid}: اتصال ناجح — ${result.http_status ?? ''} — ${Math.round(result.latency_ms ?? 0)} ms`
        : `⚠️ ${sid}: ${result.message_ar || result.state}`);
      await load();
    } catch (e) {
      setMessage(`فشل اختبار ${sid}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setTesting(null);
    }
  };

  const toggle = async (s: SourceRow) => {
    try {
      await jsonFetch(`${API}/api/fundamental/sources/manage/${encodeURIComponent(s.source_id)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !s.enabled }),
      });
      await load();
    } catch (e) { setMessage(`تعذر تغيير حالة المصدر: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const remove = async (s: SourceRow) => {
    if (!s.removable) return;
    if (!window.confirm(`حذف المصدر المخصص ${s.name_ar || s.source_id}؟`)) return;
    try {
      await jsonFetch(`${API}/api/fundamental/sources/manage/${encodeURIComponent(s.source_id)}`, { method: 'DELETE' });
      await load();
    } catch (e) { setMessage(`تعذر حذف المصدر: ${e instanceof Error ? e.message : String(e)}`); }
  };

  return (
    <div className="mx-auto w-full max-w-[1500px] p-4" dir="rtl">
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 border border-border-primary bg-bg-secondary/50 p-3">
        <div className="shrink-0">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-neon-cyan" />
            <h2 className="text-[13px] font-mono font-bold text-text-primary">إدارة واتصال مصادر التحليل الأساسي</h2>
          </div>
          <p className="mt-1 max-w-md text-[10px] font-mono leading-4 text-text-muted">
            إدارة Free-First: المجاني الرسمي مسار أساسي؛ المفاتيح لا تُعرض بعد الحفظ (DPAPI).
          </p>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {([
            ['إجمالي المصادر', counts.total, ''],
            ['مجانية', counts.free, 'text-neon-green border-neon-green/30'],
            ['سليم', counts.healthy, 'text-neon-green border-neon-green/30'],
            ['يتطلب إعدادًا', counts.config, 'text-yellow-400 border-yellow-400/30'],
            ['معطل', counts.disabled, 'text-neon-red border-neon-red/30'],
            ['مهيأ للتحليل', counts.analysis, 'text-neon-cyan border-neon-cyan/30'],
          ] as const).map(([label, value, tone]) => (
            <span key={label} className={cn('rounded border bg-bg-secondary/50 px-2 py-1 text-[10px] font-mono', tone || 'text-text-primary border-border-primary')}>{label}: <b>{value}</b></span>
          ))}
          <span className="text-[9px] font-mono text-text-muted">Secret backend: {secretBackend || '—'}</span>
        </div>
        <div className="flex shrink-0 gap-2">
          <button onClick={load} disabled={loading} className="flex items-center gap-1.5 border border-neon-cyan/30 bg-neon-cyan/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-cyan">
            <RefreshCcw className={cn('h-3 w-3', loading && 'animate-spin')} /> تحديث
          </button>
          <button onClick={addNew} className="flex items-center gap-1.5 border border-neon-green/30 bg-neon-green/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-green">
            <Plus className="h-3 w-3" /> إضافة مصدر
          </button>
        </div>
      </div>

      {message && <div className="mb-3 border border-border-primary bg-bg-secondary px-3 py-2 text-[10px] font-mono text-text-secondary">{message}</div>}

      <div className="mb-3 flex flex-wrap gap-2 border border-border-primary bg-bg-secondary/40 px-3 py-2">
        <div className="relative min-w-[280px] flex-1">
          <Search className="absolute right-2.5 top-2 h-3.5 w-3.5 text-text-muted" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ابحث باسم المصدر أو المعرّف أو الرابط..." className="w-full border border-border-primary bg-bg-tertiary py-1.5 pr-8 pl-3 text-[10px] font-mono text-text-secondary outline-none" />
        </div>
        <select value={filter} onChange={(e) => setFilter(e.target.value)} className="border border-border-primary bg-bg-tertiary px-3 py-1.5 text-[10px] font-mono text-text-secondary">
          <option value="all">كل المصادر</option><option value="healthy">سليم</option><option value="config_required">يتطلب إعدادًا</option>
          <option value="degraded">متدهور</option><option value="enabled">مفعّل</option><option value="disabled">معطل</option>
        </select>
      </div>

      <div className="overflow-x-auto border border-border-primary bg-bg-primary">
        <table className="w-full min-w-[1420px] text-right text-[10px] font-mono">
          <thead className="bg-bg-secondary text-text-secondary"><tr>
            {['المصدر','الاتصال','التحليل','Endpoint','المفتاح','Poll','آخر اختبار','إجراءات'].map((x) => <th key={x} className="border-b border-border-primary px-3 py-2">{x}</th>)}
          </tr></thead>
          <tbody>
            {filtered.map((s) => {
              const st = sourceStatus(s);
              return <tr key={s.source_id} className="border-b border-border-primary/70 hover:bg-bg-secondary/30">
                <td className="px-3 py-2 align-top"><div className="font-bold text-text-primary">{s.name_ar || s.source_id}</div><div className="text-[9px] text-text-muted">{s.name_en}</div><div className="text-[9px] text-neon-cyan">{s.source_id} · {s.official ? 'رسمي' : 'مخصص'}</div><div className="mt-1 text-[9px] text-neon-green">{s.cost_label || s.source_tier || '—'}</div></td>
                <td className="px-3 py-2 align-top"><span className={cn('inline-flex border px-2 py-0.5 font-bold', statusClass(st))}>{statusAr[st] || st}</span><div className="mt-1 max-w-[250px] text-[9px] text-text-muted">{s.runtime_health?.health_description_ar || s.last_test?.message_ar || '—'}</div></td>
                <td className="px-3 py-2 align-top">{s.analysis_ready ? <span className="text-neon-green">جاهز</span> : <span className="text-yellow-400">اتصال فقط</span>}<div className="text-[9px] text-text-muted">{s.analysis_mapping}</div></td>
                <td className="max-w-[330px] break-all px-3 py-2 align-top text-text-muted">{s.endpoint || 'غير مضبوط'}</td>
                <td className="px-3 py-2 align-top">{s.auth_mode === 'none' ? 'لا يحتاج' : s.secret_configured ? <span className="text-neon-green">● محفوظ</span> : <span className="text-yellow-400">○ غير مضبوط</span>}<div className="text-[9px] text-text-muted">{s.secret_env || s.secret_name || '—'}</div></td>
                <td className="px-3 py-2 align-top">{s.polling_interval_sec}s<div className="text-[9px] text-text-muted">timeout {s.timeout_sec}s</div></td>
                <td className="px-3 py-2 align-top">{s.last_test?.tested_at ? new Date(s.last_test.tested_at).toLocaleString('ar') : '—'}<div className="text-[9px] text-text-muted">{s.last_test?.latency_ms != null ? `${Math.round(s.last_test.latency_ms)} ms` : ''}</div></td>
                <td className="px-3 py-2 align-top"><div className="flex flex-wrap gap-1">
                  <button onClick={() => testSource(s.source_id)} disabled={testing === s.source_id} className="border border-neon-cyan/30 px-2 py-1 text-neon-cyan"><Wifi className="inline h-3 w-3" /> {testing === s.source_id ? '...' : 'اختبار'}</button>
                  <button onClick={() => edit(s)} className="border border-border-secondary px-2 py-1 text-text-secondary"><Pencil className="inline h-3 w-3" /> تعديل</button>
                  <button onClick={() => toggle(s)} className={cn('border px-2 py-1', s.enabled ? 'border-yellow-400/30 text-yellow-400' : 'border-neon-green/30 text-neon-green')}>{s.enabled ? <><CircleOff className="inline h-3 w-3" /> إيقاف</> : <><Zap className="inline h-3 w-3" /> تشغيل</>}</button>
                  {s.removable && <button onClick={() => remove(s)} className="border border-neon-red/30 px-2 py-1 text-neon-red"><Trash2 className="inline h-3 w-3" /> حذف</button>}
                </div></td>
              </tr>;
            })}
            {!loading && filtered.length === 0 && <tr><td colSpan={8} className="px-4 py-8 text-center text-text-muted">لا توجد مصادر مطابقة.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="mt-3 border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-[9px] font-mono leading-5 text-text-muted">
        <b className="text-yellow-400">قاعدة أمان:</b> نجاح اختبار الاتصال لا يعني تلقائيًا أن المصدر يدخل في التحليل. لا يدخل أي مصدر مخصص في scoring إلا إذا اختير له Mapping مدعوم، ولا تُستخدم القيم المفقودة كـ Neutral.
      </div>

      {editor && <Editor form={form} setForm={setForm} isNew={editor === 'new'} secretConfigured={editor !== 'new' && editor.secret_configured} onClose={closeEditor} onSave={() => saveSource(false)} onSaveTest={() => saveSource(true)} />}
    </div>
  );
}

function Editor({ form, setForm, isNew, secretConfigured, onClose, onSave, onSaveTest }: {
  form: FormState; setForm: React.Dispatch<React.SetStateAction<FormState>>; isNew: boolean; secretConfigured: boolean; onClose: () => void; onSave: () => void; onSaveTest: () => void;
}) {
  const f = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((p) => ({ ...p, [key]: value }));
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" dir="rtl">
    <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto border border-border-secondary bg-bg-primary shadow-2xl">
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border-primary bg-bg-secondary px-4 py-3"><KeyRound className="h-4 w-4 text-neon-cyan" /><b className="text-[12px] font-mono text-text-primary">{isNew ? 'إضافة مصدر جديد' : `تعديل ${form.source_id}`}</b><button onClick={onClose} className="mr-auto text-text-muted"><X className="h-4 w-4" /></button></div>
      <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
        <Input label="Source ID" value={form.source_id} disabled={!isNew} onChange={(v) => f('source_id', v)} />
        <Input label="الاسم العربي" value={form.name_ar} onChange={(v) => f('name_ar', v)} />
        <Input label="الاسم الإنجليزي" value={form.name_en} onChange={(v) => f('name_en', v)} />
        <Input label="المؤسسة" value={form.organization} onChange={(v) => f('organization', v)} />
        <Select label="الفئة" value={form.category} options={['macro','monetary','cross_asset','geopolitical','flows','news','calendar','custom']} onChange={(v) => f('category', v)} />
        <Select label="Transport" value={form.transport} options={['api','json','rss','xml','text','sdmx']} onChange={(v) => f('transport', v)} />
        <div className="md:col-span-2"><Input label="Endpoint URL" value={form.endpoint} onChange={(v) => f('endpoint', v)} /></div>
        <div className="md:col-span-2"><Input label="Documentation URL" value={form.documentation_url} onChange={(v) => f('documentation_url', v)} /></div>
        <Select label="طريقة المصادقة" value={form.auth_mode} options={['none','query','header','bearer']} onChange={(v) => f('auth_mode', v as FormState['auth_mode'])} />
        <Input label="اسم متغير ENV (fallback)" value={form.secret_env} onChange={(v) => f('secret_env', v)} />
        <Input label="اسم query/header للمفتاح" value={form.secret_name} onChange={(v) => f('secret_name', v)} />
        <div><label className="mb-1 block text-[9px] font-mono text-text-muted">API Key / Token {secretConfigured ? '(موجود حاليًا؛ اتركه فارغًا للإبقاء)' : ''}</label><input type="password" autoComplete="new-password" value={form.secret} onChange={(e) => f('secret', e.target.value)} className="w-full border border-border-primary bg-bg-tertiary px-2 py-1.5 text-[10px] font-mono text-text-secondary outline-none" /></div>
        <NumberInput label="Polling (ثانية)" value={form.polling_interval_sec} onChange={(v) => f('polling_interval_sec', v)} />
        <NumberInput label="Freshness limit (ثانية)" value={form.freshness_limit_sec} onChange={(v) => f('freshness_limit_sec', v)} />
        <NumberInput label="Timeout (ثانية)" value={form.timeout_sec} onChange={(v) => f('timeout_sec', v)} />
        <Select label="ربط التحليل" value={form.analysis_mapping} options={['health_only','cross_asset','flows']} onChange={(v) => f('analysis_mapping', v as FormState['analysis_mapping'])} />
        <label className="flex items-center gap-2 text-[10px] font-mono text-text-secondary"><input type="checkbox" checked={form.enabled} onChange={(e) => f('enabled', e.target.checked)} /> مفعّل</label>
        <label className="flex items-center gap-2 text-[10px] font-mono text-text-secondary"><input type="checkbox" checked={form.secret_optional} onChange={(e) => f('secret_optional', e.target.checked)} /> المفتاح اختياري</label>
        {secretConfigured && <label className="flex items-center gap-2 text-[10px] font-mono text-neon-red"><input type="checkbox" checked={form.clear_secret} onChange={(e) => f('clear_secret', e.target.checked)} /> حذف المفتاح المحفوظ</label>}
      </div>
      <div className="flex flex-wrap justify-end gap-2 border-t border-border-primary bg-bg-secondary px-4 py-3">
        <button onClick={onClose} className="border border-border-primary px-3 py-1.5 text-[10px] font-mono text-text-muted">إلغاء</button>
        <button onClick={onSave} className="flex items-center gap-1 border border-neon-purple/30 bg-neon-purple/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-purple"><Save className="h-3 w-3" /> حفظ</button>
        <button onClick={onSaveTest} className="flex items-center gap-1 border border-neon-cyan/30 bg-neon-cyan/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-cyan"><Wifi className="h-3 w-3" /> حفظ واختبار الاتصال</button>
      </div>
    </div>
  </div>;
}

function Input({ label, value, onChange, disabled = false }: { label: string; value: string; onChange: (v:string) => void; disabled?: boolean }) {
  return <div><label className="mb-1 block text-[9px] font-mono text-text-muted">{label}</label><input disabled={disabled} value={value} onChange={(e) => onChange(e.target.value)} className="w-full border border-border-primary bg-bg-tertiary px-2 py-1.5 text-[10px] font-mono text-text-secondary outline-none disabled:opacity-50" /></div>;
}
function NumberInput({ label, value, onChange }: { label: string; value: number; onChange:(v:number)=>void }) {
  return <div><label className="mb-1 block text-[9px] font-mono text-text-muted">{label}</label><input type="number" value={value} onChange={(e) => onChange(Number(e.target.value))} className="w-full border border-border-primary bg-bg-tertiary px-2 py-1.5 text-[10px] font-mono text-text-secondary outline-none" /></div>;
}
function Select({ label, value, options, onChange }: { label: string; value: string; options:string[]; onChange:(v:string)=>void }) {
  return <div><label className="mb-1 block text-[9px] font-mono text-text-muted">{label}</label><select value={value} onChange={(e) => onChange(e.target.value)} className="w-full border border-border-primary bg-bg-tertiary px-2 py-1.5 text-[10px] font-mono text-text-secondary outline-none">{options.map((o) => <option key={o} value={o}>{o}</option>)}</select></div>;
}
