'use client';

import { useEffect, useMemo, useState } from 'react';
import { Archive, BarChart3, CalendarClock, Newspaper, Search, ShieldCheck } from 'lucide-react';
import NeonCard from '../shared/NeonCard';
import { useDashboardStore } from '@/stores/dashboardStore';
import { apiClient, getAuthHeaders } from '@/lib/api-client';
import type { CalendarEvent, NewsItem } from '@/types/trading';
import type { BlackoutDTO, NewsTickerItemDTO } from '@/types/fundamental';
import MultiAssetImpactPanel from '@/components/fundamental/MultiAssetImpactPanel';
import {
  filterNewsItems,
  impactValue,
  newsFeedBanners,
  newsFeedViewState,
  newsSourceOptions,
  type ImpactFilter,
  type PeriodFilter,
} from '@/components/fundamental/news-presentation';

type Section = 'news' | 'calendar' | 'impact' | 'archive';

type ArchiveRow = {
  id: string;
  headline: string;
  source: string;
  sentiment: 'positive' | 'negative' | 'neutral' | 'unknown';
  publishedAt: string;
  relevance: string;
};

const archSentiment = (value: unknown): ArchiveRow['sentiment'] => {
  if (value == null || value === '') return 'unknown';
  const score = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(score)) return 'unknown';
  if (Math.abs(score) <= 0.2) return 'neutral';
  return score > 0 ? 'positive' : 'negative';
};

const archText = (value: unknown): string =>
  value == null || value === '' ? '—' : String(value);

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

function s(v: unknown): string { return v == null ? '—' : String(v); }
function num(v: unknown): string { return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '—'; }

const STATE_MESSAGE: Record<string, string> = {
  loading: 'جارٍ تحميل البيانات الحقيقية…',
  empty: 'اكتمل آخر مسح للأخبار دون نتائج. الغياب لا يُعامل كحالة جاهزية ولا كبيانات تجريبية.',
  unavailable: 'مسار الأخبار غير متاح حاليًا؛ لا يمكن تأكيد خلوّ الأسواق من الأخبار، ولن تُعرض بيانات بديلة.',
  offline: 'تعذر الاتصال بالمصدر. لا توجد بيانات تجريبية بديلة.',
};

type ExtraNews = {
  topic?: unknown;
  novelty_score?: unknown;
  asset_relevance?: Record<string, unknown>;
  is_commercial_noise?: unknown;
};

export default function NewsFeed() {
  const symbol = useDashboardStore((s) => s.symbol);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [calendar, setCalendar] = useState<CalendarEvent[]>([]);
  const [ticker, setTicker] = useState<NewsTickerItemDTO[]>([]);
  const [blackout, setBlackout] = useState<BlackoutDTO>({ state: 'unavailable' });
  const [envelope, setEnvelope] = useState<Record<string, unknown> | null>(null);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [impact, setImpact] = useState<ImpactFilter>('ALL');
  const [period, setPeriod] = useState<PeriodFilter>('ALL');
  const [symbolFilter, setSymbolFilter] = useState<'ALL' | 'SYMBOL'>('ALL');
  const [sourceFilter, setSourceFilter] = useState<string>('ALL');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [section, setSection] = useState<Section>('news');
  const [archive, setArchive] = useState<ArchiveRow[]>([]);
  const [archiveState, setArchiveState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    if (section !== 'archive') return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/research-lab/news`, {
          cache: 'no-store',
          headers: getAuthHeaders(),
        });
        if (!res.ok) throw new Error('archive fetch failed');
        const payload = await res.json();
        if (cancelled) return;
        const raw: unknown[] = Array.isArray(payload) ? payload : Array.isArray(payload?.rows) ? payload.rows : [];
        setArchive(raw.map((item) => {
          const x = item as Record<string, unknown>;
          return {
            id: archText(x.news_id),
            headline: archText(x.headline),
            source: archText(x.source),
            sentiment: archSentiment(x.sentiment),
            publishedAt: archText(x.published_at),
            relevance: archText(Array.isArray(x.symbols) ? x.symbols.map(String).join(', ') : x.impact),
          };
        }));
        setArchiveState('ready');
      } catch {
        if (!cancelled) setArchiveState('error');
      }
    };
    load();
    const t = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [section]);

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
        setTicker(Array.isArray(data.ticker) ? (data.ticker as NewsTickerItemDTO[]) : []);
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
  const searchedNews = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return filteredNews;
    return filteredNews.filter(
      (x) => x.headline.toLowerCase().includes(q) || String(x.source).toLowerCase().includes(q),
    );
  }, [filteredNews, query]);
  const filteredCalendar = useMemo(
    () => calendar.filter(
      (e) => (impact === 'ALL' || impactValue(e.impact) === impact)
        && (sourceFilter === 'ALL' || String(e.source ?? '') === sourceFilter),
    ),
    [calendar, impact, sourceFilter],
  );
  const selected = useMemo(
    () => searchedNews.find((x) => x.id === selectedId) ?? searchedNews[0] ?? null,
    [searchedNews, selectedId],
  );
  const selectedExtra = (selected ?? null) as (NewsItem & ExtraNews) | null;

  return (
    <div dir="rtl">
      <NeonCard title={`الأخبار والتقويم — الشاشة الموحدة (${symbol})`} glow="cyan" noPadding className="h-full flex flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-border-primary/20 bg-bg-tertiary/60 px-3 py-2">
          {([
            ['news', 'الأخبار', Newspaper],
            ['calendar', 'التقويم الاقتصادي', CalendarClock],
            ['impact', 'الأثر حسب الأصل', BarChart3],
            ['archive', 'أرشيف البحث', Archive],
          ] as const).map(([key, label, Icon]) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition ${section === key ? 'bg-neon-cyan/85 text-bg-primary' : 'border border-border-primary bg-bg-secondary text-text-secondary hover:bg-bg-tertiary'}`}
              aria-pressed={section === key}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        {blackout.state !== 'clear' && (
          <div className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs font-semibold text-amber-300">
            حالة الأمان: {blackout.reason_ar ?? 'حالة التقويم غير واضحة؛ فتح تعرّض جديد محظور احترازيًا.'}
          </div>
        )}

        {(viewState === 'stale' || banners.reasonAr) && (
          <div className="border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs leading-5 text-amber-300">
            {banners.reasonAr ?? STATE_MESSAGE[viewState] ?? STATE_MESSAGE.unavailable}
            {banners.staleWarning && <div className="mt-1 font-semibold">{banners.staleWarning}</div>}
          </div>
        )}

        {(section === 'news' || section === 'calendar') && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border-primary/20 px-3 py-2 text-[10px] text-text-muted">
          <span>التأثير</span>
          {(['ALL','HIGH','MEDIUM','LOW'] as ImpactFilter[]).map(v => (
            <button key={v} onClick={() => setImpact(v)} className={`px-2 py-1 ${impact===v?'bg-neon-cyan/85 text-bg-primary':'border border-border-primary bg-bg-secondary text-text-secondary'}`}>
              {v === 'ALL' ? 'الكل' : impactAr(v)}
            </button>
          ))}
          <span className="mr-3">الفترة</span>
          {(['ALL','1H','24H','7D'] as PeriodFilter[]).map(v => (
            <button key={v} onClick={() => setPeriod(v)} className={`px-2 py-1 ${period===v?'bg-neon-cyan/85 text-bg-primary':'border border-border-primary bg-bg-secondary text-text-secondary'}`}>
              {v === 'ALL' ? 'الكل' : v}
            </button>
          ))}
          <span className="mr-3">الرمز</span>
          {(['ALL','SYMBOL'] as const).map(v => (
            <button key={v} onClick={() => setSymbolFilter(v)} className={`px-2 py-1 ${symbolFilter===v?'bg-neon-cyan/85 text-bg-primary':'border border-border-primary bg-bg-secondary text-text-secondary'}`}>
              {v === 'ALL' ? 'الكل' : symbol}
            </button>
          ))}
          <span className="mr-3">المصدر</span>
          <select
            value={sourceFilter}
            onChange={e => setSourceFilter(e.target.value)}
            className="border border-border-primary bg-bg-secondary px-2 py-1 text-text-secondary"
            aria-label="تصفية حسب مصدر الخبر"
          >
            <option value="ALL">الكل</option>
            {sourceOptions.map(src => <option key={src} value={src}>{src}</option>)}
          </select>
          {sourceFilter !== 'ALL' && <button onClick={() => setSourceFilter('ALL')} className="px-2 py-1 border border-border-primary bg-bg-secondary text-text-secondary">إلغاء التصفية</button>}
          <span className="mr-auto flex items-center gap-2 border border-border-primary bg-bg-secondary px-2 py-1">
            <Search className="h-3.5 w-3.5 text-neon-cyan" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="بحث في الأخبار…"
              className="w-44 bg-transparent text-xs outline-none"
              aria-label="بحث في الأخبار"
            />
          </span>
        </div>
        )}

        <div className="flex flex-wrap gap-3 border-b border-border-primary/20 px-3 py-1.5 text-[10px] text-text-secondary">
          <span>آخر تحديث: {banners.lastUpdateLabel ?? '—'}</span>
          <span>أول إتاحة: {banners.firstAvailableLabel ?? '—'}</span>
        </div>

        {banners.sourceIssues.length > 0 && (
          <div className="border-b border-border-primary bg-bg-tertiary px-4 py-2 text-[11px] leading-5 text-text-primary">
            <b>وضع المصادر:</b>
            <ul className="mt-1 list-disc pr-4">
              {banners.sourceIssues.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </div>
        )}

        {!loaded && viewState === 'loading' && <div className="p-6 text-center text-xs text-text-muted">{STATE_MESSAGE.loading}</div>}
        {loaded && (viewState === 'empty' || viewState === 'unavailable' || viewState === 'offline') && !banners.reasonAr && (
          <div className={`p-6 text-center text-xs ${viewState === 'offline' || viewState === 'unavailable' ? 'text-amber-300' : 'text-text-muted'}`}>
            {STATE_MESSAGE[viewState]}
          </div>
        )}

        {loaded && section === 'news' && (viewState === 'ready' || viewState === 'stale' || viewState === 'empty' || viewState === 'unavailable') && (
          <div className="space-y-3 p-3">
            <div className="grid gap-3 xl:grid-cols-[1.4fr_1fr]">
              <section className="border border-border-primary bg-bg-secondary text-text-primary">
                <h3 className="border-b border-border-primary/40 bg-bg-tertiary px-3 py-2 text-sm font-semibold text-text-primary">الأخبار الحقيقية</h3>
                <div className="max-h-[460px] divide-y divide-border-primary/40 overflow-y-auto">
                  {searchedNews.length === 0 ? <div className="p-4 text-xs text-text-secondary">لا توجد أخبار مطابقة للفلاتر أو البحث.</div> : searchedNews.map(item => {
                    const extra = item as NewsItem & ExtraNews;
                    const rel = extra.asset_relevance;
                    const xau = rel?.XAUUSD;
                    const btc = rel?.BTCUSD;
                    const selectedNow = selected?.id === item.id;
                    return (
                      <button
                        key={item.id}
                        onClick={() => setSelectedId(item.id)}
                        className={`block w-full p-3 text-right transition ${selectedNow ? 'bg-bg-tertiary' : 'hover:bg-bg-tertiary/60'}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <h4 className="text-xs font-semibold leading-5">{item.headline}</h4>
                          <span className="shrink-0 border border-border-primary px-1.5 py-0.5 text-[9px]">{impactAr(item.impact)}</span>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-text-secondary">
                          <span>{item.source}</span><span>•</span><span>{ago(item.timestamp, now)}</span><span>•</span><span>{sentimentAr(item.sentiment)}</span><span>•</span><span>الأصل: {item.data_origin ?? 'REAL'}</span>
                          {extra.is_commercial_noise === true && <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-300">مستبعد من التحليل المالي</span>}
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-text-muted">
                          <span>FinBERT: {item.finbert_state === 'available' && typeof item.finbert_score === 'number' ? item.finbert_score.toFixed(3) : 'غير متاح'} — النبرة لا تساوي اتجاه الذهب.</span>
                          {extra.topic != null && <span>• الموضوع: {s(extra.topic)}</span>}
                          {extra.novelty_score != null && <span>• الجِدّة: {num(extra.novelty_score)}</span>}
                          {typeof xau === 'number' && <span>• صلة XAU: {num(xau)}</span>}
                          {typeof btc === 'number' && <span>• صلة BTC: {num(btc)}</span>}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="border border-border-primary bg-bg-secondary text-text-primary">
                <h3 className="border-b border-border-primary/40 bg-bg-tertiary px-3 py-2 text-sm font-semibold text-text-primary">تفاصيل الخبر المختار</h3>
                {!selected ? <div className="p-5 text-xs text-text-secondary">اختر خبرًا لعرض التفاصيل.</div> : (
                  <div className="space-y-4 p-4">
                    <div>
                      <div className="text-[11px] text-text-muted">ماذا حدث؟</div>
                      <div className="mt-1 text-sm font-semibold leading-7 text-text-primary">{selected.headline}</div>
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="border border-border-primary/40 bg-bg-tertiary p-2"><span className="text-text-muted">المصدر</span><div className="mt-1 font-medium">{selected.source}</div></div>
                      <div className="border border-border-primary/40 bg-bg-tertiary p-2"><span className="text-text-muted">الموضوع</span><div className="mt-1 font-medium">{s(selectedExtra?.topic)}</div></div>
                      <div className="border border-border-primary/40 bg-bg-tertiary p-2"><span className="text-text-muted">FinBERT</span><div className="mt-1 font-medium">{selected.finbert_state === 'available' && typeof selected.finbert_score === 'number' ? `${selected.finbert_state} · ${selected.finbert_score.toFixed(3)}` : s(selected.finbert_state ?? 'غير متاح')}</div></div>
                      <div className="border border-border-primary/40 bg-bg-tertiary p-2"><span className="text-text-muted">أصل البيانات</span><div className="mt-1 font-medium">{s(selected.data_origin ?? 'REAL')}</div></div>
                    </div>
                    <div className="border border-border-primary bg-bg-secondary p-3 text-xs leading-6 text-text-secondary"><b>قاعدة الأمان:</b> المشاعر ليست اتجاهًا للذهب. اتجاه الأصل لا يُعرض إلا من محرك Asset Impact الحتمي.</div>
                  </div>
                )}
              </section>
            </div>

            <div className="grid gap-3 xl:grid-cols-[1.4fr_1fr]">
              <section className="border border-border-primary bg-bg-secondary text-text-primary">
                <h3 className="flex items-center gap-2 border-b border-border-primary/40 bg-bg-tertiary px-3 py-2 text-sm font-semibold text-text-primary"><ShieldCheck className="h-4 w-4" /> الشريط النشط (تنبيهات عالية الأهمية)</h3>
                <div className="max-h-[280px] divide-y divide-border-primary/40 overflow-y-auto">
                  {ticker.length === 0 ? <div className="p-4 text-xs text-text-secondary">لا توجد تنبيهات نشطة.</div> : ticker.slice(0, 20).map(x => (
                    <div key={x.ticker_item_id} className="p-3">
                      <div className="flex flex-wrap items-center gap-2 text-[10px]">
                        <span className="rounded bg-neon-cyan/10 px-1.5 py-0.5 font-bold text-text-secondary">{s(x.severity).toUpperCase()}</span>
                        {x.asset_id && <span>{x.asset_id}</span>}
                        <span className="text-text-muted">{s(x.status)}</span>
                      </div>
                      <div className="mt-1 text-xs leading-5 text-text-primary">{x.headline_ar}</div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>
        )}

        {loaded && section === 'calendar' && (viewState === 'ready' || viewState === 'stale' || viewState === 'empty' || viewState === 'unavailable') && (
          <div className="space-y-3 p-3">
            <section className="border border-border-primary bg-bg-secondary text-text-primary">
              <h3 className="flex items-center gap-2 border-b border-border-primary/40 bg-bg-tertiary px-3 py-2 text-sm font-semibold text-text-primary"><CalendarClock className="h-4 w-4" /> التقويم الاقتصادي</h3>
              <div className="max-h-[560px] overflow-auto">
                <table className="w-full min-w-[720px] text-right text-xs">
                  <thead className="sticky top-0 bg-bg-tertiary text-text-secondary">
                    <tr>{['الحدث','العملة','الأهمية','الفعلي','المتوقع','السابق','الوقت','المصدر'].map(x => <th key={x} className="px-3 py-2 font-semibold">{x}</th>)}</tr>
                  </thead>
                  <tbody>
                    {filteredCalendar.length === 0 ? <tr><td colSpan={8} className="p-4 text-center text-text-secondary">لا توجد أحداث مطابقة للفلاتر.</td></tr> : filteredCalendar.map(event => (
                      <tr key={event.id} className="border-t border-border-primary/40">
                        <td className="px-3 py-2 font-medium">{event.event_name}</td>
                        <td className="px-3 py-2">{event.currency}</td>
                        <td className="px-3 py-2">{impactAr(event.impact)}</td>
                        <td className="px-3 py-2"><b>{event.actual ?? '—'}</b></td>
                        <td className="px-3 py-2">{event.forecast ?? '—'}</td>
                        <td className="px-3 py-2">{event.previous ?? '—'}</td>
                        <td className="px-3 py-2">{new Date(event.timestamp).toLocaleString('ar')}</td>
                        <td className="px-3 py-2">{event.source ?? 'مصدر تقويم'} • {event.data_origin ?? 'REAL'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}

        {section === 'impact' && (
          <div className="p-3"><MultiAssetImpactPanel /></div>
        )}

        {section === 'archive' && (
          <div className="space-y-3 p-3">
            <section className="border border-border-primary bg-bg-secondary text-text-primary">
              <h3 className="flex items-center gap-2 border-b border-border-primary/40 bg-bg-tertiary px-3 py-2 text-sm font-semibold text-text-primary"><Archive className="h-4 w-4" /> الأرشيف البحثي — الأخبار المرتبطة بالأصل والفترة</h3>
              <p className="border-b border-border-primary/40 bg-bg-tertiary/60 px-3 py-1.5 text-[10px] text-text-secondary">التصفية حسب وسوم المصدر ووقت النشر UTC — المصدر: nexus-data.news_articles. توفر الأرشيف لا يثبت حداثته أو اكتماله؛ عرض موحّد يخدم نفس الشاشة دون الرجوع لمختبر البحث.</p>
              <div className="max-h-[560px] overflow-auto">
                <table className="w-full min-w-[720px] text-right text-xs">
                  <thead className="sticky top-0 bg-bg-tertiary text-text-secondary">
                    <tr>{['الخبر','المصدر','الأصول المتأثرة','وقت النشر UTC','النبرة'].map(x => <th key={x} className="px-3 py-2 font-semibold">{x}</th>)}</tr>
                  </thead>
                  <tbody>
                    {archiveState === 'loading' && <tr><td colSpan={5} className="p-4 text-center text-text-secondary">جارٍ التحميل…</td></tr>}
                    {archiveState === 'error' && <tr><td colSpan={5} className="p-4 text-center text-amber-300">تعذر قراءة أرشيف الأخبار — لا تُعرض بيانات بديلة.</td></tr>}
                    {archiveState === 'ready' && archive.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-text-secondary">لا توجد أخبار مطابقة ضمن السجلات المقروءة.</td></tr>}
                    {archiveState === 'ready' && archive.map(r => (
                      <tr key={r.id} className="border-t border-border-primary/40">
                        <td className="px-3 py-2 font-medium">{r.headline}</td>
                        <td className="px-3 py-2">{r.source}</td>
                        <td className="px-3 py-2">{r.relevance}</td>
                        <td className="px-3 py-2">{r.publishedAt}</td>
                        <td className="px-3 py-2">{r.sentiment === 'positive' ? 'إيجابية' : r.sentiment === 'negative' ? 'سلبية' : r.sentiment === 'neutral' ? 'محايدة' : 'غير محددة'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}
      </NeonCard>
    </div>
  );
}
