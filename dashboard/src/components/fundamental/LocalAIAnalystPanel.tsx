'use client';

import { useState } from 'react';
import { Bot, Send, ShieldCheck, AlertTriangle, WifiOff } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { LocalAIAnalysisDTO } from '@/types/fundamental';
import {
  localAiStatePresentation,
  localAiModelLine,
  evidenceIdItems,
  localAiGuardNote,
} from '@/lib/local-ai-presentation';

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <section className="border border-sky-100 bg-sky-50 p-3">
      <h4 className="text-xs font-semibold text-sky-950">{title}</h4>
      <ul className="mt-2 space-y-1 text-xs leading-6 text-slate-700">
        {items.map((x, i) => <li key={`${title}-${i}`}>• {x}</li>)}
      </ul>
    </section>
  );
}

export default function LocalAIAnalystPanel() {
  const [asset, setAsset] = useState<'XAUUSD' | 'BTCUSD'>('XAUUSD');
  const [question, setQuestion] = useState('اشرح لي لماذا وصل التحليل الأساسي إلى حالته الحالية وما الأدلة الناقصة؟');
  const [result, setResult] = useState<LocalAIAnalysisDTO | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const submit = async () => {
    setLoading(true); setError('');
    try {
      const res = await apiClient.analyzeFundamentalLocalAI(question, asset);
      setResult(res.data);
    } catch {
      setError('تعذر الوصول إلى المحلل المحلي. لم يتم إنشاء إجابة بديلة أو وهمية.');
    } finally { setLoading(false); }
  };

  const view = localAiStatePresentation(result);
  const evidence = evidenceIdItems(result?.answer ?? null);
  const modelLine = localAiModelLine(result);

  return (
    <div className="space-y-3">
      <div className="border border-sky-200 bg-white p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-sky-700" />
            <div><h2 className="text-sm font-bold text-sky-950">المحلل المحلي AI</h2><p className="text-[11px] text-slate-600">تفسير مساعد قائم فقط على الحالة الحتمية والمصادر المسجلة — بلا صلاحية تنفيذ أو تغيير درجات.</p></div>
          </div>
          <div className="flex items-center gap-2 rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800"><ShieldCheck className="h-3.5 w-3.5" /> {localAiGuardNote()}</div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-[140px_1fr_auto]">
          <select value={asset} onChange={(e) => setAsset(e.target.value as 'XAUUSD' | 'BTCUSD')} className="border border-sky-200 bg-white px-3 py-2 text-xs outline-none focus:border-sky-500">
            <option value="XAUUSD">XAUUSD — الذهب</option>
            <option value="BTCUSD">BTCUSD — بيتكوين</option>
          </select>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={800} rows={2} className="resize-none border border-sky-200 px-3 py-2 text-xs leading-6 outline-none focus:border-sky-500" />
          <button onClick={submit} disabled={loading || !question.trim()} className="flex items-center justify-center gap-2 bg-sky-700 px-4 py-2 text-xs font-semibold text-white hover:bg-sky-800 disabled:opacity-50"><Send className="h-3.5 w-3.5" />{loading ? 'يحلل…' : 'حلل'}</button>
        </div>
      </div>

      {error && <div className="border border-red-200 bg-red-50 p-3 text-xs text-red-800">{error}</div>}
      {view.kind === 'rejected' && (
        <div className="flex items-start gap-2 border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p>{view.headline}</p>
            <ul className="mt-1 space-y-0.5 font-mono text-[11px]">
              {view.details.map((d, i) => <li key={i}>• {d}</li>)}
            </ul>
          </div>
        </div>
      )}
      {view.kind === 'unavailable' && (
        <div className="border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
          <div className="flex items-center gap-2 font-semibold"><WifiOff className="h-4 w-4" />{view.headline}</div>
          <ul className="mt-2 space-y-0.5 font-mono text-[11px] text-slate-700">
            {view.details.map((d, i) => <li key={i}>• {d}</li>)}
          </ul>
          <p className="mt-2 text-[11px] text-slate-600">لا توجد إجابة بديلة أو وهمية عند تعذر الاتصال.</p>
        </div>
      )}

      {view.kind === 'ready' && result?.answer && (
        <div className="grid gap-3 xl:grid-cols-2">
          <section className="border border-sky-200 bg-white p-4 xl:col-span-2">
            <div className="mb-2 flex items-center justify-between gap-2 flex-wrap text-[11px] text-slate-500">
              <span className="font-mono">{modelLine}</span>
              <span>Schema: {result.schema_valid ? 'PASS' : 'FAIL'}</span>
            </div>
            <h3 className="text-sm font-semibold text-sky-950">الملخص</h3>
            <p className="mt-2 text-sm leading-7 text-slate-800">{result.answer.summary_ar}</p>
            {evidence.length > 0 && (
              <p className="mt-2 text-[11px] text-slate-600 font-mono">
                معرفات الأدلة المستعملة: {evidence.map((e) => e.label).join(' · ')}
              </p>
            )}
          </section>
          <section className="border border-sky-200 bg-white p-4"><h3 className="text-sm font-semibold text-sky-950">ماذا حدث؟</h3><p className="mt-2 text-xs leading-6 text-slate-700">{result.answer.what_happened}</p></section>
          <section className="border border-sky-200 bg-white p-4"><h3 className="text-sm font-semibold text-sky-950">لماذا يهم؟</h3><p className="mt-2 text-xs leading-6 text-slate-700">{result.answer.why_it_matters}</p></section>
          <ListBlock title="سلسلة انتقال الأثر" items={result.answer.transmission} />
          <ListBlock title="مقارنة الأصول" items={result.answer.asset_comparison} />
          <ListBlock title="ما يؤكد التحليل" items={result.answer.confirmations} />
          <ListBlock title="ما يعارض التحليل" items={result.answer.contradictions} />
          <ListBlock title="الأدلة الناقصة" items={result.answer.missing_evidence} />
          <ListBlock title="المصادر المستخدمة" items={result.answer.sources} />
          <ListBlock title="الادعاءات المعرفية المستخدمة" items={result.answer.claims_used} />
          <section className="border border-sky-200 bg-white p-4 xl:col-span-2"><p className="text-xs leading-6 text-slate-700"><b>جودة البيانات:</b> {result.answer.data_quality_note || '—'}</p><p className="mt-2 text-xs leading-6 text-slate-700"><b>عدم اليقين:</b> {result.answer.uncertainty_note || '—'}</p></section>
        </div>
      )}
    </div>
  );
}
