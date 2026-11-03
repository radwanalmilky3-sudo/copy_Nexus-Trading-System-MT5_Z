'use client';

import { useEffect, useMemo, useState } from 'react';
import NeonCard from '../shared/NeonCard';
import { useDashboardStore } from '@/stores/dashboardStore';
import { apiClient } from '@/lib/api-client';
import type { CalendarEvent, NewsItem } from '@/types/trading';
import type { BlackoutDTO } from '@/types/fundamental';
import {
  filterNewsItems,
  impactValue,
  newsFeedBanners,
  newsFeedViewState,
  newsSourceOptions,
  type ImpactFilter,
  type PeriodFilter,
} from '@/components/fundamental/news-presentation';

function impactAr(v: string) {
  return { HIGH: 'مرتفع', MEDIUM: 'متوسط', LOW: 'منخفض' }[impactValue(v)];
}

function sentimentAr(v: string) {
  const x = v.toLowerCase();
  if (x === 'positive' || x === 'bullish') return 'نبرة إيجابية';
  if (x === 'negative' || x === 'bearish') return 'نبرة سلبية';
  return 'نبرة محايدة';
}

function ago(iso: string, now: number) {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return 'الآن';
  if (minutes < 60) return `منذ ${minutes} د`;
  const h = Math.floor(minutes / 60);
  return h < 24 ? `منذ ${h} س` : `منذ ${Math.floor(h / 24)} يوم`;
}

const STATE_MESSAGE: Record<string, string> = {
  loading: 'جارٍ تحميل البيانات الحقيقية…',
  empty: 'اكتمل آخر مسح للأخبار دون نتائج. الغياب لا يُعامل كحالة جاهزية ولا كبيانات تجريبية.',
  unavailable: 'مسار الأخبار غير متاح حاليًا؛ لا يمكن تأكيد خلوّ الأسواق من الأخبار، ولن تُعرض بيانات بديلة.',
  offline: 'تعذر الاتصال بالمصدر. لا توجد بيانات تجريبية بديلة.',
};

export default function NewsFeed() {
  const symbol = useDashboardStore((s) => s.symbol);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);
  const [blackout, setBlackout] = useState<BlackoutDTO>({ state: 'unavailable' });
  const [envelope, setEnvelope] = useState<Record<string, unknown> | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [impact, setImpact] = useState<ImpactFilter>('ALL');
  const [period, setPeriod] = useState<PeriodFilter>('ALL');
  const [symbolFilter, setSymbolFilter] = useState<'ALL' | 'SYMBOL'>('ALL');
  const [sourceFilter, setSourceFilter] = useState<string>('ALL');
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    const load = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      try {
        const response = await apiClient.getFundamentalNews();
        if (cancelled) return;
        const data = response.data;
        if (
          !Array.isArray(data.news)
          || !Array.isArray(data.calendar)
          || !data.blackout
          || typeof data.blackout.state !== 'string'
          || !data.blackout.state.trim()
        ) {
          throw new Error('Invalid fundamental news payload');
        }
        setNews(data.news as unknown as NewsItem[]);
        setCalendar(data.calendar as unknown as CalendarEvent[]);
        setBlackout(data.blackout);
        setEnvelope(data as unknown as Record<string, unknown>);
        setFetchFailed(false);
      } catch {
        if (!cancelled) {
          setFetchFailed(true);
          setEnvelope(null);
          setBlackout({
            state: 'unavailable',
            reason_ar: 'تعذر تحديث حالة التقويم؛ لا يمكن تأكيد خلوّ الفترة من الحظر.',
          });
        }
      } finally {
        if (!cancelled) setLoaded(true);
        inFlight = false;
      }
    };
    load();
    const timer = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const viewState = newsFeedViewState(envelope, fetchFailed);
  const banners = newsFeedBanners(envelope, viewState);

  const sourceOptions = useMemo(() => newsSourceOptions(news), [news]);
  const filteredNews = useMemo(
    () => filterNewsItems(news, { impact, period, symbol, symbolFilter, source: sourceFilter, now }),
    [news, impact, period, symbol, symbolFilter, sourceFilter, now],
  );
  const filteredCalendar = useMemo(
    () => calendar.filter(
      (e) => (impact === 'ALL' || impactValue(e.impact) === impact)
        && (sourceFilter === 'ALL' || String(e.source ?? '') === sourceFilter),
    ),
    [calendar, impact, sourceFilter],
  );

  return (
    <div dir="rtl">
      <NeonCard title={`الأخبار والتقويم — ${symbol}`} glow="cyan" noPadding className="h-full flex flex-col">
        {blackout.state !== 'clear' && (
          <div className="border-b border-amber-400 bg-amber-50 px-4 py-3 text-xs font-semibold text-amber-950">
            حالة الأمان: {blackout.reason_ar ?? 'حالة التقويم غير واضحة؛ فتح تعرّض جديد محظور احترازيًا.'}
          </div>
        )}

        {(viewState === 'stale' || banners.reasonAr) && (
          <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-xs leading-5 text-amber-950">
            {banners.reasonAr ?? STATE_MESSAGE[viewState] ?? STATE_MESSAGE.unavailable}
            {banners.staleWarning && <div className="mt-1 font-semibold">{banners.staleWarning}</div>}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-b border-border-primary/20 px-3 py-2 text-[10px] text-text-muted">
          <span>التأثير</span>
          {(['ALL','HIGH','MEDIUM','LOW'] as ImpactFilter[]).map(v => (
            <button key={v} onClick={() => setImpact(v)} className={`px-2 py-1 ${impact===v?'bg-sky-600 text-white':'border border-sky-200 bg-white text-sky-900'}`}>
              {v === 'ALL' ? 'الكل' : impactAr(v)}
            </button>
          ))}
          <span className="mr-3">الفترة</span>
          {(['ALL','1H','24H','7D'] as PeriodFilter[]).map(v => (
            <button key={v} onClick={() => setPeriod(v)} className={`px-2 py-1 ${period===v?'bg-sky-600 text-white':'border border-sky-200 bg-white text-sky-900'}`}>
              {v === 'ALL' ? 'الكل' : v}
            </button>
          ))}
          <span className="mr-3">الرمز</span>
          {(['ALL','SYMBOL'] as const).map(v => (
            <button key={v} onClick={() => setSymbolFilter(v)} className={`px-2 py-1 ${symbolFilter===v?'bg-sky-600 text-white':'border border-sky-200 bg-white text-sky-900'}`}>
              {v === 'ALL' ? 'الكل' : symbol}
            </button>
          ))}
          <span className="mr-3">المصدر</span>
          <select
            value={sourceFilter}
            onChange={e => setSourceFilter(e.target.value)}
            className="border border-sky-200 bg-white px-2 py-1 text-sky-900"
            aria-label="تصفية حسب مصدر الخبر"
          >
            <option value="ALL">الكل</option>
            {sourceOptions.map(src => <option key={src} value={src}>{src}</option>)}
          </select>
          {sourceFilter !== 'ALL' && <button onClick={() => setSourceFilter('ALL')} className="px-2 py-1 border border-sky-200 bg-white text-sky-900">إلغاء التصفية</button>}
        </div>

        <div className="flex flex-wrap gap-3 border-b border-border-primary/20 px-3 py-1.5 text-[10px] text-slate-600">
          <span>آخر تحديث: {banners.lastUpdateLabel ?? '—'}</span>
          <span>أول إتاحة: {banners.firstAvailableLabel ?? '—'}</span>
        </div>

        {banners.sourceIssues.length > 0 && (
          <div className="border-b border-sky-200 bg-sky-50 px-4 py-2 text-[11px] leading-5 text-sky-950">
            <b>وضع المصادر:</b>
            <ul className="mt-1 list-disc pr-4">
              {banners.sourceIssues.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </div>
        )}

        {!loaded && viewState === 'loading' && <div className="p-6 text-center text-xs text-text-muted">{STATE_MESSAGE.loading}</div>}
        {loaded && (viewState === 'empty' || viewState === 'unavailable' || viewState === 'offline') && !banners.reasonAr && (
          <div className={`p-6 text-center text-xs ${viewState === 'offline' || viewState === 'unavailable' ? 'text-amber-700' : 'text-text-muted'}`}>
            {STATE_MESSAGE[viewState]}
          </div>
        )}
        {loaded && banners.reasonAr && (viewState === 'empty' || viewState === 'unavailable' || viewState === 'offline') && (
          <div className={`p-6 text-center text-xs ${viewState === 'offline' || viewState === 'unavailable' ? 'text-amber-700' : 'text-text-muted'}`}>
            {banners.reasonAr}
          </div>
        )}

        {loaded && (viewState === 'ready' || viewState === 'stale' || viewState === 'empty' || viewState === 'unavailable') && <div className="grid gap-3 p-3 xl:grid-cols-2">
          <section className="border border-sky-200 bg-white text-slate-900">
            <h3 className="border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950">الأخبار الحقيقية</h3>
            <div className="max-h-[520px] divide-y divide-sky-100 overflow-y-auto">
              {filteredNews.length === 0 ? <div className="p-4 text-xs text-slate-600">لا توجد أخبار مطابقة للفلاتر.</div> : filteredNews.map(item => (
                <article key={item.id} className="p-3">
                  <div className="flex items-start justify-between gap-3"><h4 className="text-xs font-semibold leading-5">{item.headline}</h4><span className="shrink-0 border border-sky-200 px-1.5 py-0.5 text-[9px]">{impactAr(item.impact)}</span></div>
                  <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-slate-600"><span>{item.source}</span><span>•</span><span>{ago(item.timestamp, now)}</span><span>•</span><span>{sentimentAr(item.sentiment)}</span><span>•</span><span>الأصل: {item.data_origin ?? 'REAL'}</span></div>
                  <div className="mt-1 text-[10px] text-slate-500">FinBERT: {item.finbert_state === 'available' && typeof item.finbert_score === 'number' ? item.finbert_score.toFixed(3) : 'غير متاح'} — النبرة لا تساوي اتجاه الذهب.</div>
                </article>
              ))}
            </div>
          </section>

          <section className="border border-sky-200 bg-white text-slate-900">
            <h3 className="border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950">التقويم الاقتصادي</h3>
            <div className="max-h-[520px] divide-y divide-sky-100 overflow-y-auto">
              {filteredCalendar.length === 0 ? <div className="p-4 text-xs text-slate-600">لا توجد أحداث مطابقة للفلاتر.</div> : filteredCalendar.map(event => (
                <article key={event.id} className="p-3">
                  <div className="flex items-start justify-between gap-3"><h4 className="text-xs font-semibold">{event.event_name}</h4><span className="border border-sky-200 px-1.5 py-0.5 text-[9px]">{impactAr(event.impact)}</span></div>
                  <div className="mt-2 grid grid-cols-3 gap-2 text-[10px]"><div>الفعلي: <b>{event.actual ?? '—'}</b></div><div>المتوقع: <b>{event.forecast ?? '—'}</b></div><div>السابق: <b>{event.previous ?? '—'}</b></div></div>
                  <div className="mt-2 text-[10px] text-slate-600">{event.currency} • {new Date(event.timestamp).toLocaleString('ar')} • {event.source ?? 'مصدر تقويم'} • {event.data_origin ?? 'REAL'}</div>
                </article>
              ))}
            </div>
          </section>
        </div>}
      </NeonCard>
    </div>
  );
}
