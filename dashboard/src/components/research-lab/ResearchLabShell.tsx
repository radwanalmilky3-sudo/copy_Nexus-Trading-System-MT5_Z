'use client';

import { useEffect, useMemo, useState } from 'react';
import { Archive, Beaker, BookOpenCheck, Boxes, CheckCheck, Database, FileCheck2, Newspaper, RefreshCw, ShieldCheck } from 'lucide-react';
import { researchSources } from './adapters';
import { ResearchLabTab } from './ResearchLabTab';
import { DataSourcesWorkspace } from './DataSourcesWorkspace';
import {ResearchScopeProvider,ResearchScopeBar} from './ResearchScope';
import {ResearchEvidencePanel} from './ResearchEvidencePanel';
import {ResearchNewsPanel} from './ResearchNewsPanel';
import { startResearchRefresh } from './refresh';
import type { ResearchRowByTab, ResearchTabDefinition, ResearchTabId, ResearchViewState } from './types';

const TABS: ReadonlyArray<ResearchTabDefinition<ResearchRowByTab[ResearchTabId]>> = [
  { id: 'data-import', arabicLabel: 'مصادر البيانات', englishLabel: 'Datasets', description: 'الشموع المخزنة حسب الأصل والإطار والمصدر', icon: '01', source: researchSources['data-import'] },
  { id: 'cleaning', arabicLabel: 'التنظيف', englishLabel: 'Cleaning', description: 'قواعد جودة البيانات', icon: '02', source: researchSources.cleaning },
  { id: 'validation', arabicLabel: 'التحقق', englishLabel: 'Validation', description: 'نتائج الفحوص المسجلة فقط', icon: '03', source: researchSources.validation },
  { id: 'provenance', arabicLabel: 'التتبّع', englishLabel: 'Provenance', description: 'المصدر وبصمات البيانات المخزنة', icon: '04', source: researchSources.provenance },
  { id: 'strategies', arabicLabel: 'الاستراتيجيات', englishLabel: 'Strategies', description: 'تعريفات مرجعية؛ لا تعني اعتمادها للتداول', icon: '05', source: researchSources.strategies },
  { id: 'backtests', arabicLabel: 'الاختبارات التاريخية', englishLabel: 'Backtests', description: 'نتائج الاختبارات المقروءة', icon: '06', source: researchSources.backtests },
  { id: 'news', arabicLabel: 'الأخبار', englishLabel: 'News', description: 'الأخبار المحفوظة؛ الاتصال لا يثبت حداثتها', icon: '07', source: researchSources.news },
  { id: 'artifacts', arabicLabel: 'المخرجات', englishLabel: 'Artifacts', description: 'المخرجات المسجلة وبصماتها', icon: '08', source: researchSources.artifacts },
];
const ICONS = { 'data-import': Database, cleaning: Beaker, validation: CheckCheck, provenance: ShieldCheck, strategies: BookOpenCheck, backtests: FileCheck2, news: Newspaper, artifacts: Boxes } as const;
type RowsState = { [K in ResearchTabId]: ReadonlyArray<ResearchRowByTab[K]> };
type StatusState = { [K in ResearchTabId]: ResearchViewState };
const emptyRows = (): RowsState => ({ 'data-import': [], cleaning: [], validation: [], provenance: [], strategies: [], backtests: [], news: [], artifacts: [] });
const initialStatus = (): StatusState => ({ 'data-import': 'loading', cleaning: 'loading', validation: 'loading', provenance: 'loading', strategies: 'loading', backtests: 'loading', news: 'loading', artifacts: 'loading' });

export default function ResearchLabShell(){return <ResearchScopeProvider><ResearchLabContent/></ResearchScopeProvider>;}
function ResearchLabContent() {
  const [activeTab, setActiveTab] = useState<ResearchTabId>('data-import');
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState<RowsState>(emptyRows);
  const [statuses, setStatuses] = useState<StatusState>(initialStatus);
  const [sources, setSources] = useState<Partial<Record<ResearchTabId, string>>>({});
  const [totals, setTotals] = useState<Partial<Record<ResearchTabId, number>>>({});
  const [refresh, setRefresh] = useState(0);
  const [filterNotice, setFilterNotice] = useState(false);
  useEffect(() => startResearchRefresh(() => setRefresh((n) => n + 1)), []);
  useEffect(() => {
    const controller = new AbortController();
    if (refresh === 0) { setStatuses(initialStatus()); setRows(emptyRows()); setSources({}); setTotals({}); }
    // Sources settle independently; a stalled service cannot hide healthy sections.
    for (const tab of TABS) void tab.source.load(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      const state: ResearchViewState = result.status === 'available' ? (result.rows.length ? 'readonly' : 'empty') : result.status;
      setRows((current) => ({ ...current, [tab.id]: result.rows } as RowsState));
      setStatuses((current) => ({ ...current, [tab.id]: state }));
      setSources((current) => ({ ...current, [tab.id]: result.source }));
      setTotals((current) => ({ ...current, [tab.id]: result.total }));
    }).catch(() => { if (!controller.signal.aborted) setStatuses((current) => ({ ...current, [tab.id]: 'error' })); });
    return () => controller.abort();
  }, [refresh]);
  const activeDefinition = useMemo(() => TABS.find((tab) => tab.id === activeTab)!, [activeTab]);
  const readableSources = new Set(TABS.filter((tab) => ['readonly', 'empty'].includes(statuses[tab.id])).map((tab) => sources[tab.id]).filter(Boolean)).size;
  return <div className="min-h-full bg-bg-primary px-3 py-4 text-text-primary sm:px-5 lg:px-7" dir="rtl"><div className="mx-auto max-w-[1800px] space-y-4">
    <header className="flex flex-wrap items-end justify-between gap-4 rounded-2xl border border-border-primary/40 bg-bg-secondary p-5">
      <div><div className="mb-2 flex items-center gap-2 text-[10px] font-mono text-neon-purple"><Archive className="h-3.5 w-3.5" /> Research Lab / Workspace</div><h1 className="text-2xl font-black">مختبر البحث</h1><p className="mt-2 text-xs text-text-muted">إدارة بيانات البحث ومراجعة أدلة الجودة والنتائج.</p></div>
      <div className="flex items-center gap-3 text-xs"><span>{readableSources} مصادر مقروءة</span><span className="text-text-muted">8 أقسام</span><button type="button" onClick={() => setRefresh((n) => n + 1)} className="neon-button px-3 py-2" aria-label="تحديث مصادر المختبر"><RefreshCw size={13} /> تحديث</button></div>
    </header>
    <nav className="overflow-x-auto rounded-xl border border-border-primary/30 bg-bg-secondary/40 p-1.5" aria-label="تبويبات مختبر البحث"><div className="flex min-w-max gap-1" role="tablist">{TABS.map((tab) => { const Icon = ICONS[tab.id]; return <button key={tab.id} type="button" role="tab" aria-selected={tab.id === activeTab} onClick={() => { setActiveTab(tab.id); setQuery(''); }} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-right ${tab.id === activeTab ? 'bg-neon-purple/15 text-neon-purple' : 'text-text-muted'}`}><Icon className="h-3.5 w-3.5" /><span><span className="block text-[11px] font-semibold">{tab.arabicLabel}</span><span className="block text-[9px] font-mono opacity-60">{tab.englishLabel}</span></span></button>; })}</div></nav>
    {activeTab!=='data-import'&&<p className="text-[11px] text-text-muted">تحديث تلقائي كل 60 ثانية · المصدر: <bdi>{sources[activeTab] || '—'}</bdi> · عرض {rows[activeTab].length} من {totals[activeTab] ?? '—'} سجل · توفر الأرشيف لا يثبت اكتماله أو حداثته.</p>}
    {filterNotice && <button type="button" onClick={() => setFilterNotice(false)} className="text-xs text-neon-gold">الفلاتر الإضافية غير مفعلة؛ البحث النصي يعمل على السجلات المعروضة. اضغط للإخفاء.</button>}
    {activeTab!=='data-import'&&<ResearchScopeBar/>}
    <div hidden={activeTab!=='data-import'}><DataSourcesWorkspace><ResearchLabTab definition={TABS[0]} rows={rows['data-import']} state={statuses['data-import']} query={query} onQueryChange={setQuery} onFilterOpen={() => setFilterNotice(true)} /></DataSourcesWorkspace></div>
    <ResearchEvidencePanel tab={activeTab} onNavigate={setActiveTab}/>
    {activeTab==='news'&&<ResearchNewsPanel rows={rows.news} state={statuses.news}/>}
    {activeTab!=='data-import'&&<details className="rounded border border-border-primary p-3"><summary className="cursor-pointer text-xs text-text-muted">أرشيف المختبر السابق — مصدر عام لا يمثل بالضرورة الحساب والفترة المختارين</summary><div className="mt-4"><ResearchLabTab definition={activeDefinition} rows={rows[activeTab]} state={statuses[activeTab]} query={query} onQueryChange={setQuery} onFilterOpen={() => setFilterNotice(true)} /></div></details>}
  </div></div>;
}
