'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiClient } from '@/lib/api-client';
import { deriveDomainContract } from '@/lib/fundamental-contract';
import type { DomainDTO, DriverDTO, GoldOverviewDTO, SourceHealthDTO } from '@/types/fundamental';
import LocalAIAnalystPanel from './LocalAIAnalystPanel';
import MultiAssetImpactPanel from './MultiAssetImpactPanel';
import FundamentalCharts from './FundamentalCharts';
import DataLineagePanel from './DataLineagePanel';

const TABS = [
  ['overview', 'نظرة عامة على الذهب'],
  ['macro', 'الاقتصاد الكلي'],
  ['monetary', 'السياسة النقدية والبنوك المركزية'],
  ['cross_asset', 'الأسواق المترابطة'],
  ['geopolitical', 'الجيوسياسة والمخاطر العالمية'],
  ['flows', 'التدفقات والتمركزات'],
  ['learning', 'التعلم والنتائج'],
  ['local_ai', 'المحلل المحلي AI'],
] as const;

type Tab = typeof TABS[number][0];

const statusAr: Record<string, string> = {
  healthy: 'سليم', degraded: 'متدهور', rate_limited: 'مقيّد مؤقتًا', config_required: 'يتطلب إعدادًا',
  offline: 'غير متصل', unknown: 'غير معروف', unavailable: 'غير متاح', fresh: 'حديث', stale: 'قديم', live: 'حي',
};

function n(v: unknown, digits = 0) {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : '—';
}

function Metric({ label, value, suffix = '' }: { label: string; value: unknown; suffix?: string }) {
  return (
    <div className="min-w-[120px] border border-sky-200 bg-white px-3 py-2 shadow-sm">
      <div className="text-[11px] text-sky-800">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-900">{typeof value === 'number' ? n(value) + suffix : String(value ?? '—')}</div>
    </div>
  );
}

function StateMessage({ text }: { text: string }) {
  return <div className="border border-sky-200 bg-sky-50 p-5 text-sm text-sky-950">{text}</div>;
}

function DomainRail({ domains }: { domains: DomainDTO[] }) {
  return (
    <div className="overflow-x-auto border border-sky-200 bg-white">
      <table className="w-full min-w-[780px] text-right text-xs">
        <thead className="bg-sky-50 text-sky-950">
          <tr>{['المحور','أثر الذهب','الاتجاه','القوة','الثقة','التغطية','الجودة','الحداثة'].map(x => <th key={x} className="px-3 py-2 font-semibold">{x}</th>)}</tr>
        </thead>
        <tbody>
          {domains.map((d) => {
            const contract = deriveDomainContract(d);
            const unavailable = contract.domain_state === 'UNAVAILABLE';
            const degraded = contract.domain_state === 'DEGRADED';
            const stateLabel = unavailable ? 'غير متاح' : degraded ? 'بيانات جزئية' : d.direction;
            return (
            <tr key={d.domain} className="border-t border-sky-100">
              <td className="px-3 py-2 font-semibold text-slate-900">{d.domain_ar ?? d.domain}</td>
              <td className="px-3 py-2 font-mono">{unavailable || degraded ? '—' : n(d.gold_impact_score, 1)}</td>
              <td className={`px-3 py-2 ${unavailable ? 'text-slate-500' : degraded ? 'text-amber-800' : ''}`}>{stateLabel}</td>
              <td className="px-3 py-2">{unavailable || degraded ? '—' : n(d.strength)}</td>
              <td className="px-3 py-2">{unavailable || degraded ? '—' : `${n(d.confidence)}%`}</td>
              <td className="px-3 py-2">{n(d.coverage_score)}%</td>
              <td className="px-3 py-2">{n(d.data_quality_score)}%</td>
              <td className="px-3 py-2">{n(d.freshness_score)}%</td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Drivers({ title, items }: { title: string; items: DriverDTO[] }) {
  return (
    <section className="border border-sky-200 bg-white">
      <h3 className="border-b border-sky-100 bg-sky-50 px-3 py-2 text-sm font-semibold text-sky-950">{title}</h3>
      <div className="divide-y divide-sky-100">
        {items.length === 0 ? <div className="p-3 text-xs text-slate-600">لا توجد أدلة موثوقة مسجلة حاليًا.</div> : items.map((d) => (
          <details key={`${d.code}-${d.label_ar}`} className="px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium text-slate-900">{d.label_ar} — أثر الذهب {n(d.gold_impact_score,1)}/100</summary>
            <p className="mt-2 text-xs leading-6 text-slate-700">{d.explanation_ar}</p>
            <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-600">
              <span>الثقة {n(d.confidence)}%</span><span>•</span><span>الأفق {d.horizon_class}</span>
              {d.sources.map((s) => <span key={`${d.code}-${s.source_id}`}>• {s.source_name_ar || s.source_name} ({String(s.origin).toUpperCase()})</span>)}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}


const DETAIL_COLUMNS: Record<string, Array<[string,string]>> = {
  macro: [
    ['indicator_name_ar','المؤشر'], ['actual','الفعلي'], ['forecast','المتوقع'], ['previous','السابق'],
    ['revised_previous','المراجعة'], ['surprise_absolute','المفاجأة'], ['surprise_zscore','المفاجأة المعيارية'],
    ['rate_implication_score','أثر الفائدة'], ['usd_implication_score','أثر الدولار'], ['yield_implication_score','أثر العوائد'],
    ['gold_implication_score','أثر الذهب'], ['source_name_ar','المصدر'], ['source_timestamp','الوقت'],
  ],
  monetary: [
    ['event_kind','الحدث'], ['tone_score','النبرة الحالية'], ['previous_tone_score','النبرة السابقة'], ['policy_delta','تغير السياسة'],
    ['rate_surprise_bps','مفاجأة الفائدة'], ['forward_guidance_score','التوجيه المستقبلي'], ['gold_implication_score','أثر الذهب'],
    ['confidence','الثقة'], ['source_name_ar','المصدر'], ['source_timestamp','الوقت'],
  ],
  cross_asset: [
    ['series_code','الأصل/المؤشر'], ['value','القيمة'], ['change','التغير'], ['change_pct','التغير %'],
    ['origin','أصل البيانات'], ['quality_score','الجودة'], ['freshness','الحداثة'], ['source_name_ar','المصدر'], ['timestamp','الوقت'],
  ],
  geopolitical: [
    ['title_ar','الحدث'], ['region','المنطقة'], ['event_class','النوع'], ['severity_score','الخطورة'], ['escalation_score','التصعيد'],
    ['persistence_score','الاستمرارية'], ['safe_haven_score','ضغط الملاذ الآمن'], ['energy_risk_score','مخاطر الطاقة'],
    ['independent_source_count','المصادر المستقلة'], ['gold_implication_score','أثر الذهب'], ['confidence','الثقة'],
  ],
  flows: [
    ['flow_type','النوع'], ['value','القيمة'], ['flow_direction','الاتجاه'], ['strength_score','القوة'], ['crowding_score','الازدحام'],
    ['confirmation_score','التأكيد'], ['divergence_score','التباعد'], ['native_horizon','الأفق'], ['freshness_score','الحداثة'],
    ['quality_score','الجودة'], ['source_name_ar','المصدر'], ['timestamp','الوقت'],
  ],
};

function detailValue(key: string, value: unknown): string {
  if (value == null || value === '') return '—';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toFixed(Math.abs(value) >= 100 ? 1 : 2) : '—';
  if (typeof value === 'boolean') return value ? 'نعم' : 'لا';
  if (key.includes('timestamp') || key.endsWith('_at')) {
    const d = new Date(String(value));
    return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('ar');
  }
  return String(value);
}

function DomainDetails({ domain }: { domain: DomainDTO }) {
  const rows = domain.details ?? [];
  if (!rows.length) return <StateMessage text="لا توجد سجلات تفصيلية حقيقية متاحة لهذا المحور حاليًا." />;
  const columns = DETAIL_COLUMNS[domain.domain] ?? [];
  return <section className="border border-sky-200 bg-white">
    <h2 className="border-b border-sky-100 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-950">البيانات التفصيلية ومصدر كل قيمة</h2>
    <div className="overflow-x-auto"><table className="w-full min-w-[980px] text-right text-xs">
      <thead><tr>{columns.map(([key,label]) => <th key={key} className="whitespace-nowrap px-3 py-2 text-sky-900">{label}</th>)}</tr></thead>
      <tbody>{rows.slice(0,50).map((row, idx) => <tr key={String(row.event_id ?? row.observation_id ?? row.article_id ?? idx)} className="border-t border-sky-100">
        {columns.map(([key]) => <td key={key} className="whitespace-nowrap px-3 py-2 text-slate-700">{detailValue(key, row[key])}</td>)}
      </tr>)}</tbody>
    </table></div>
  </section>;
}

function DomainView({ domain }: { domain?: DomainDTO }) {
  const contract = deriveDomainContract(domain);
  if (!domain || contract.domain_state === 'UNAVAILABLE') {
    return <StateMessage text="بيانات هذا المحور غير متاحة حاليًا. لم تُستبدل بقيمة محايدة أو بيانات تجريبية." />;
  }
  return <div className="space-y-3">
    {contract.domain_state === 'DEGRADED' && (
      <div className="border border-amber-300 bg-amber-50 px-4 py-3 text-xs leading-6 text-amber-950">
        حالة المحور: بيانات جزئية (DEGRADED) — الأدلة الحقيقية موجودة (evidence_count={contract.evidence_count}) لكن الدرجة الكاملة لم تُحسب هذه الدورة. لا تعني DEGRADED قيمة محايدة ولا وجود نتيجة محرك؛ الأصفار أدناه صادقة ولم تُستبدل بشيء.
      </div>
    )}
    <div className="flex flex-wrap gap-2">
      <Metric label="أثر المحور على الذهب" value={domain.gold_impact_score} />
      <Metric label="النتيجة الأصلية للمحور" value={domain.native_score} />
      <Metric label="القوة" value={domain.strength} suffix="/100" />
      <Metric label="الثقة" value={domain.confidence} suffix="%" />
      <Metric label="تغطية البيانات" value={domain.coverage_score} suffix="%" />
      <Metric label="جودة البيانات" value={domain.data_quality_score} suffix="%" />
      <Metric label="حداثة البيانات" value={domain.freshness_score} suffix="%" />
      <Metric label="الأفق" value={domain.horizon_class} />
    </div>
    <div className="grid gap-3 xl:grid-cols-2">
      <Drivers title="العوامل الداعمة" items={domain.primary_drivers ?? []} />
      <Drivers title="العوامل المعارضة" items={domain.counter_drivers ?? []} />
    </div>
    <DomainDetails domain={domain} />
  </div>;
}

export default function FundamentalWorkspace() {
  const [tab, setTab] = useState<Tab>('overview');
  const [overview, setOverview] = useState<GoldOverviewDTO | null>(null);
  const [sources, setSources] = useState<SourceHealthDTO[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [o, s] = await Promise.all([apiClient.getFundamentalOverview(), apiClient.getFundamentalSourceHealth()]);
        if (!cancelled) { setOverview(o.data); setSources(s.data); setError(''); }
      } catch {
        if (!cancelled) setError('تعذر الاتصال بخدمة التحليل الأساسي. لا يتم عرض بيانات تجريبية بديلة.');
      } finally { if (!cancelled) setLoading(false); }
    };
    load();
    const timer = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const domain = useMemo(() => overview?.domains?.find(d => d.domain === tab), [overview, tab]);

  return (
    <div dir="rtl" className="min-h-full bg-sky-50 p-3 text-slate-900">
      <header className="border border-sky-200 bg-white">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-sky-100 px-4 py-3">
          <div><h1 className="text-base font-bold text-sky-950">مركز الاستخبارات الأساسية متعدد الأصول</h1><p className="mt-1 text-xs text-slate-600">XAUUSD أساس الاعتماد الحالي · BTCUSD أثر مستقل · خمسة محاور أساسية · تعليل سببي قابل للتتبع</p></div>
          <div className="text-left text-xs text-slate-600">آخر تحديث: {overview?.generated_at ? new Date(overview.generated_at).toLocaleString('ar') : '—'}</div>
        </div>
        <nav className="flex overflow-x-auto border-b border-sky-100 bg-sky-50">
          {TABS.map(([id,label]) => <button key={id} onClick={() => setTab(id)} className={`whitespace-nowrap border-l border-sky-100 px-3 py-2 text-xs ${tab===id?'bg-sky-700 font-semibold text-white':'text-sky-950 hover:bg-sky-100'}`}>{label}</button>)}
        </nav>
      </header>

      {loading && <div className="mt-3"><StateMessage text="جارٍ تحميل التحليل الأساسي…" /></div>}
      {error && <div className="mt-3"><StateMessage text={error} /></div>}

      {!loading && overview && <main className="mt-3 space-y-3">
        {overview.blackout?.state !== 'clear' && <div className="border border-amber-300 bg-amber-50 px-4 py-3 text-sm font-medium text-amber-950">حالة الأمان: {overview.blackout.reason_ar ?? 'حالة الحظر غير واضحة؛ فتح تعرّض جديد محظور احترازيًا.'}</div>}

        {tab === 'overview' && <>
          {overview.state !== 'ready' ? <StateMessage text={overview.message_ar ?? 'التحليل الأساسي غير متاح.'} /> : <>
            <div className="flex flex-wrap gap-2">
              <Metric label="الميل الأساسي للذهب" value={overview.direction_ar ?? overview.direction} />
              <Metric label="قوة السيناريو" value={overview.strength} suffix="/100" />
              <Metric label="الثقة" value={overview.confidence} suffix="%" />
              <Metric label="تغطية البيانات" value={overview.coverage_score} suffix="%" />
              <Metric label="جودة البيانات" value={overview.data_quality_score} suffix="%" />
              <Metric label="حداثة البيانات" value={overview.freshness_score} suffix="%" />
              <Metric label="درجة التعارض" value={overview.conflict_score} suffix="/100" />
              <Metric label="مرحلة الحدث" value={overview.prediction_stage} />
              <Metric label="تأكيد السوق" value={overview.market_confirmation} />
              <Metric label="حالة حظر التداول" value={overview.blackout?.state === 'clear' ? 'واضح' : 'محظور/متدهور'} />
            </div>
            <DomainRail domains={overview.domains ?? []} />
            <MultiAssetImpactPanel />
            <FundamentalCharts overview={overview} />
            <DataLineagePanel />
            <section className="border border-sky-200 bg-white p-4">
              <h2 className="text-sm font-semibold text-sky-950">سلسلة انتقال الأثر إلى الذهب</h2>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                {(overview.transmission_chain_ar ?? []).map((x,i) => <span key={`${i}-${x}`} className="contents"><span className="border border-sky-200 bg-sky-50 px-2 py-1">{x}</span>{i < (overview.transmission_chain_ar?.length ?? 0)-1 && <span className="text-sky-700">←</span>}</span>)}
              </div>
            </section>
            <div className="grid gap-3 xl:grid-cols-2">
              <Drivers title="أقوى العوامل الداعمة" items={overview.primary_drivers ?? []} />
              <Drivers title="أقوى العوامل المعارضة" items={overview.counter_drivers ?? []} />
            </div>
            {overview.explanation && <section className="border border-sky-200 bg-white">
              <h2 className="border-b border-sky-100 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-950">{overview.explanation.headline_ar}</h2>
              <dl className="grid gap-0 lg:grid-cols-2">
                {[
                  ['ماذا حدث؟',overview.explanation.what_happened_ar],['لماذا يهم؟',overview.explanation.why_it_matters_ar],
                  ['كيف ينتقل الأثر؟',overview.explanation.transmission_to_gold_ar],['كيف يؤثر على الذهب؟',overview.explanation.gold_effect_ar],
                  ['لماذا هذه الثقة؟',overview.explanation.confidence_reason_ar],['ما الأفق الزمني؟',overview.explanation.horizon_ar],
                  ['ماذا حدث فعليًا بعد ذلك؟',overview.explanation.actual_outcome_ar],['ماذا تعلم النظام؟',overview.explanation.lesson_ar],
                ].map(([k,v]) => <div key={k} className="border-b border-sky-100 p-3 lg:border-l"><dt className="text-xs font-semibold text-sky-900">{k}</dt><dd className="mt-1 text-xs leading-6 text-slate-700">{v}</dd></div>)}
              </dl>
            </section>}
          </>}
        </>}

        {(['macro','monetary','cross_asset','geopolitical','flows'] as Tab[]).includes(tab) && <DomainView domain={domain} />}

        {tab === 'learning' && <section className="border border-sky-200 bg-white p-4"><h2 className="text-sm font-semibold text-sky-950">وضع التعلم</h2><p className="mt-2 text-xs leading-6 text-slate-700">المبسّط: خلاصة عربية مباشرة. المتوسط: المحركات والتعارض والآفاق. المتقدم: النتائج الأصلية، أثر الذهب، الأوزان، جودة البيانات، المصدر، والاستقلال السببي.</p>{overview.explanation && <div className="mt-3 grid gap-3 lg:grid-cols-2"><div className="border border-sky-100 bg-sky-50 p-3 text-xs leading-6"><b>مبسّط:</b> {overview.explanation.simple_summary_ar}</div><div className="border border-sky-100 bg-sky-50 p-3 text-xs leading-6"><b>متقدم:</b> {overview.explanation.advanced_summary_ar}</div></div>}</section>}

        {tab === 'local_ai' && <LocalAIAnalystPanel />}

        <section className="border border-sky-200 bg-white">
          <h2 className="border-b border-sky-100 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-950">صحة مصادر التحليل الأساسي</h2>
          <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-right text-xs"><thead><tr>{['المصدر','الحالة','الشرح','الحداثة','الأصل','آخر نجاح','الاستجابة'].map(x=><th key={x} className="px-3 py-2 text-sky-900">{x}</th>)}</tr></thead><tbody>{sources.map(s=><tr key={s.source_id} className="border-t border-sky-100"><td className="px-3 py-2 font-medium">{s.name_ar} <span className="text-slate-500">({s.name_en})</span></td><td className="px-3 py-2">{statusAr[s.health] ?? s.health}</td><td className="px-3 py-2">{s.health_description_ar}</td><td className="px-3 py-2">{statusAr[s.freshness] ?? s.freshness}</td><td className="px-3 py-2">{s.origin}</td><td className="px-3 py-2">{s.last_success_at ? new Date(s.last_success_at).toLocaleString('ar') : '—'}</td><td className="px-3 py-2">{s.latency_ms == null ? '—' : `${n(s.latency_ms)} ms`}</td></tr>)}</tbody></table></div>
        </section>
      </main>}
    </div>
  );
}
