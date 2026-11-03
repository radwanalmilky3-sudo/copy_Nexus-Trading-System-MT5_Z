'use client';

import { useEffect, useMemo, useState } from 'react';
import { CalendarClock, Newspaper, Search, ShieldCheck } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import { newsFeedBanners, newsFeedViewState } from './news-presentation';
import type { FundamentalNewsDTO, NewsTickerItemDTO } from '@/types/fundamental';

function s(v: unknown): string { return v == null ? '—' : String(v); }
function num(v: unknown): string { return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '—'; }

export default function NewsIntelligencePanel() {
  const [data, setData] = useState<FundamentalNewsDTO | null>(null);
  const [selected, setSelected] = useState<Record<string, unknown> | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await apiClient.getFundamentalNews();
        if (!cancelled) { setData(r.data); setError(''); }
      } catch { if (!cancelled) setError('تعذر تحديث الأخبار الحقيقية؛ لا توجد بيانات تجريبية بديلة.'); }
    };
    load(); const id = window.setInterval(load, 15_000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const news = useMemo(() => {
    const rows = data?.news ?? [];
    const q = query.trim().toLowerCase();
    return q ? rows.filter((x) => s(x.headline).toLowerCase().includes(q) || s(x.source).toLowerCase().includes(q)) : rows;
  }, [data, query]);
  const ticker = (data?.ticker ?? []) as NewsTickerItemDTO[];
  const focus = selected ?? news[0] ?? null;

  // The additive truth fields (state/last_update_at/sources) are part of the
  // DTO now; the presentation helpers treat missing values as "unknown", never ready.
  const viewState = newsFeedViewState(data, Boolean(error) && !data);
  const banners = newsFeedBanners(data, viewState);

  return (
    <div className="space-y-3">
      {error && <div className="border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">{error}</div>}
      <div className="border border-sky-200 bg-sky-50 px-3 py-2 text-[11px] leading-5 text-sky-950">
        <div className="flex flex-wrap gap-3">
          <span>حالة المسار: <b>{viewState}</b></span>
          <span>آخر تحديث: {banners.lastUpdateLabel ?? '—'}</span>
          <span>أول إتاحة: {banners.firstAvailableLabel ?? '—'}</span>
        </div>
        {banners.staleWarning && <div className="mt-1 font-semibold text-amber-900">{banners.staleWarning}</div>}
        {banners.reasonAr && viewState !== 'ready' && <div className="mt-1 text-amber-900">{banners.reasonAr}</div>}
        {banners.sourceIssues.length > 0 && (
          <ul className="mt-1 list-disc pr-4 text-amber-950">
            {banners.sourceIssues.map((line) => <li key={line}>{line}</li>)}
          </ul>
        )}
      </div>
      <div className="grid gap-3 2xl:grid-cols-[1.4fr_1fr]">
        <section className="border border-sky-200 bg-white">
          <header className="flex flex-wrap items-center gap-3 border-b border-sky-100 bg-sky-50 px-3 py-2">
            <div className="flex items-center gap-2 text-sm font-semibold text-sky-950"><Newspaper className="h-4 w-4" /> الأخبار الحية</div>
            <div className="mr-auto flex items-center gap-2 border border-sky-200 bg-white px-2 py-1.5"><Search className="h-3.5 w-3.5 text-sky-600" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="بحث في الأخبار…" className="w-52 bg-transparent text-xs outline-none" /></div>
          </header>
          <div className="max-h-[520px] divide-y divide-sky-100 overflow-auto">
            {news.length === 0 && <div className="p-5 text-xs text-slate-600">لا توجد أخبار حقيقية مطابقة حاليًا.</div>}
            {news.map((row, i) => {
              const rel = row.asset_relevance as Record<string, unknown> | undefined;
              const xau = rel?.XAUUSD;
              const btc = rel?.BTCUSD;
              const selectedNow = focus === row;
              return <button key={s(row.id ?? `${row.headline}-${i}`)} onClick={() => setSelected(row)} className={`block w-full p-3 text-right transition ${selectedNow ? 'bg-sky-50' : 'hover:bg-sky-50/60'}`}>
                <div className="flex flex-wrap items-center gap-2 text-[10px]">
                  <span className="rounded bg-sky-100 px-1.5 py-0.5 font-bold text-sky-800">{s(row.severity ?? row.impact ?? 'NEWS').toUpperCase()}</span>
                  <span className="text-slate-500">{s(row.source)}</span><span className="text-slate-400">{s(row.timestamp)}</span>
                  {row.is_commercial_noise === true && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">مستبعد من التحليل المالي</span>}
                </div>
                <div className="mt-1.5 text-sm font-medium leading-6 text-slate-900">{s(row.headline)}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-600">
                  <span>الموضوع: {s(row.topic)}</span><span>•</span><span>Novelty {num(row.novelty_score)}</span>
                  {typeof xau === 'number' && <span>• XAU relevance {num(xau)}</span>}
                  {typeof btc === 'number' && <span>• BTC relevance {num(btc)}</span>}
                </div>
              </button>;
            })}
          </div>
        </section>

        <section className="border border-sky-200 bg-white">
          <header className="border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950">تفاصيل الخبر المختار</header>
          {!focus ? <div className="p-5 text-xs text-slate-600">اختر خبرًا لعرض التفاصيل.</div> : <div className="space-y-4 p-4">
            <div><div className="text-[11px] text-slate-500">ماذا حدث؟</div><div className="mt-1 text-sm font-semibold leading-7 text-slate-900">{s(focus.headline)}</div></div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="border border-sky-100 bg-sky-50 p-2"><span className="text-slate-500">المصدر</span><div className="mt-1 font-medium">{s(focus.source)}</div></div>
              <div className="border border-sky-100 bg-sky-50 p-2"><span className="text-slate-500">الموضوع</span><div className="mt-1 font-medium">{s(focus.topic)}</div></div>
              <div className="border border-sky-100 bg-sky-50 p-2"><span className="text-slate-500">FinBERT</span><div className="mt-1 font-medium">{s(focus.finbert_state)} · {num(focus.finbert_score)}</div></div>
              <div className="border border-sky-100 bg-sky-50 p-2"><span className="text-slate-500">أصل البيانات</span><div className="mt-1 font-medium">{s(focus.data_origin)}</div></div>
            </div>
            <div className="border border-sky-200 bg-white p-3 text-xs leading-6 text-slate-700"><b>قاعدة الأمان:</b> المشاعر ليست اتجاهًا للذهب. اتجاه الأصل لا يُعرض إلا من محرك Asset Impact الحتمي.</div>
          </div>}
        </section>
      </div>

      <div className="grid gap-3 xl:grid-cols-[1.4fr_1fr]">
        <section className="border border-sky-200 bg-white">
          <header className="flex items-center gap-2 border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950"><CalendarClock className="h-4 w-4" /> التقويم الاقتصادي</header>
          <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-right text-xs"><thead><tr className="text-sky-900">{['الحدث','العملة','الأهمية','الفعلي','المتوقع','السابق','الوقت','المصدر'].map(x => <th key={x} className="px-3 py-2">{x}</th>)}</tr></thead><tbody>{(data?.calendar ?? []).slice(0,40).map((r,i) => <tr key={s(r.id ?? i)} className="border-t border-sky-100"><td className="px-3 py-2 font-medium">{s(r.event_name)}</td><td className="px-3 py-2">{s(r.currency)}</td><td className="px-3 py-2">{s(r.impact)}</td><td className="px-3 py-2">{s(r.actual)}</td><td className="px-3 py-2">{s(r.forecast)}</td><td className="px-3 py-2">{s(r.previous)}</td><td className="px-3 py-2">{s(r.timestamp)}</td><td className="px-3 py-2">{s(r.source)}</td></tr>)}</tbody></table></div>
        </section>
        <section className="border border-sky-200 bg-white">
          <header className="flex items-center gap-2 border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950"><ShieldCheck className="h-4 w-4" /> قائمة الشريط النشطة</header>
          <div className="max-h-72 divide-y divide-sky-100 overflow-auto">{ticker.length === 0 ? <div className="p-4 text-xs text-slate-600">لا توجد تنبيهات نشطة.</div> : ticker.slice(0,20).map((x) => <div key={x.ticker_item_id} className="p-3"><div className="flex items-center gap-2 text-[10px]"><span className="font-bold">{x.severity.toUpperCase()}</span><span>{x.asset_id}</span><span className="text-slate-500">{x.status}</span></div><div className="mt-1 text-xs leading-5 text-slate-800">{x.headline_ar}</div></div>)}</div>
        </section>
      </div>
    </div>
  );
}
