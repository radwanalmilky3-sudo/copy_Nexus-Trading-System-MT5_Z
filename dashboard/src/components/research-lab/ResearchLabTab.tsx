'use client';

import { AlertTriangle, CheckCircle2, Clock3, Filter, LockKeyhole, Search, SlidersHorizontal } from 'lucide-react';
import type { ReactNode } from 'react';
import { BacktestHeader, BacktestTable } from './BacktestTable';
import { ResearchLabTable, StatePill, type ResearchColumn } from './ResearchLabTable';
import { StrategyHeader, StrategyTable } from './StrategyTable';
import { qualityTime } from './refresh';
import type { ArtifactRow, BacktestRow, CleaningRow, DataImportRow, NewsRow, ProvenanceRow, ResearchRow, ResearchTabDefinition, ResearchViewState, StrategyRow, ValidationRow } from './types';

interface ResearchLabTabProps<T extends ResearchRow> { readonly definition: ResearchTabDefinition<T>; readonly rows: ReadonlyArray<T>; readonly state: ResearchViewState; readonly query: string; readonly onQueryChange: (value: string) => void; readonly onFilterOpen: () => void; }

function StoredQuality({ row }: { row: DataImportRow }) {
  const state = row.qualityStatus || 'not_checked';
  const labels = { passed: 'اجتازت الفحوص الأساسية', warning: 'تحذير جودة', failed: 'فشلت الفحوص', stale: 'تحتاج إعادة فحص · نسخة أو وقت مختلف', not_checked: 'مخزنة · لم تُفحص بعد' };
  const calendarLabels: Record<string,string> = {not_configured:'غير موصول',unavailable:'غير متاح',ready:'جاهز للتحقق ضمن صلاحيته',stale:'قديم',identity_mismatch:'اختلاف الخادم أو الرمز',clock_unverified:'ساعة الوسيط غير موثقة',invalid:'الدليل غير صالح',conflict:'أدلة متعارضة'};
  return <div className="max-w-sm whitespace-normal text-right"><StatePill tone={state === 'passed' ? 'green' : state === 'failed' ? 'red' : state === 'warning' ? 'gold' : 'muted'}>{labels[state]}</StatePill>
    {row.qualityCheckedAt && row.qualityCheckedAt !== '—' && <p className="mt-1 text-[10px] text-text-muted">إصدار الشهادة: <bdi>{qualityTime(row.qualityCheckedAt)}</bdi></p>}
    {row.qualityVerifiedAt && row.qualityVerifiedAt !== '—' && <p className="mt-1 text-[10px] text-text-muted">آخر مطابقة للبصمة: <bdi>{qualityTime(row.qualityVerifiedAt)}</bdi></p>}
    {row.qualityExpiresAt && row.qualityExpiresAt !== '—' && <p className="mt-1 text-[10px] text-text-muted">انتهاء الشهادة: <bdi>{qualityTime(row.qualityExpiresAt)}</bdi></p>}
    {row.historicalSlice && <p className="mt-1 text-[10px] text-text-muted">مجموعة استكمال تاريخي؛ قِدم آخر شمعة فيها لا يثبت توقف التغذية الحية. الفواصل تُقيَّم لهذه المجموعة وحدها.</p>}
    <p className="mt-1 text-[10px] text-text-muted">{`قارئ الجلسات: ${calendarLabels[row.calendarState || 'not_configured'] || 'غير مؤكّد'}`}</p>
    {row.calendarDetails && <p className="mt-1 text-[10px] text-text-muted">{row.calendarDetails}</p>}
    {row.calendarCapturedAt && row.calendarCapturedAt !== '—' && <p className="text-[10px] text-text-muted">التقاط الجلسات: <bdi>{qualityTime(row.calendarCapturedAt)}</bdi></p>}
    {row.calendarImportedAt && row.calendarImportedAt !== '—' && <p className="text-[10px] text-text-muted">استيراد الجلسات: <bdi>{qualityTime(row.calendarImportedAt)}</bdi></p>}
    {row.calendarExpiresAt && row.calendarExpiresAt !== '—' && <p className="text-[10px] text-text-muted">صلاحية الجلسات: <bdi>{qualityTime(row.calendarExpiresAt)}</bdi></p>}
    {row.calendarSnapshotId && <p className="break-all text-[10px] text-text-muted">دليل الجلسات: <bdi>{row.calendarSnapshotId}</bdi></p>}
    {row.gapDetails && <p className="mt-1 text-[10px] text-text-muted">{row.gapDetails}</p>}
    {row.qualityDetails && <p className="mt-1 text-[10px] text-text-muted">{row.qualityDetails}</p>}
    {state !== 'not_checked' && <p className="mt-1 text-[10px] text-text-muted">فحص للصفوف المخزنة؛ ليس اعتمادًا للتداول أو اكتمال الفترة.</p>}
  </div>;
}

function rowColumns(tabId: ResearchTabDefinition<ResearchRow>['id']): ReadonlyArray<ResearchColumn<ResearchRow>> {
  if (tabId === 'data-import') return [{ key: 'source', label: 'المصدر', render: (row) => (row as DataImportRow).source }, { key: 'format', label: 'الصيغة', render: (row) => (row as DataImportRow).format, align: 'center' }, { key: 'rows', label: 'الصفوف', render: (row) => <span className="font-mono">{(row as DataImportRow).rows.toLocaleString('en-US')}</span>, align: 'center' }, { key: 'receivedAt', label: 'آخر شمعة مخزنة', render: (row) => (row as DataImportRow).receivedAt, align: 'left' }, { key: 'status', label: 'الجودة · نسخة محددة', render: (row) => <StoredQuality row={row as DataImportRow} />, align: 'center' }];
  if (tabId === 'cleaning') return [{ key: 'dataset', label: 'مجموعة البيانات', render: (row) => (row as CleaningRow).dataset }, { key: 'rule', label: 'قاعدة التنظيف', render: (row) => (row as CleaningRow).rule }, { key: 'affectedRows', label: 'الصفوف المتأثرة', render: (row) => <span className="font-mono">{(row as CleaningRow).affectedRows.toLocaleString('en-US')}</span>, align: 'center' }, { key: 'updatedAt', label: 'آخر تحديث', render: (row) => (row as CleaningRow).updatedAt, align: 'left' }, { key: 'status', label: 'الحالة', render: (row) => <StatePill tone="gold">{(row as CleaningRow).status}</StatePill>, align: 'center' }];
  if (tabId === 'validation') return [{ key: 'dataset', label: 'مجموعة البيانات', render: (row) => (row as ValidationRow).dataset }, { key: 'check', label: 'الفحوص', render: (row) => <span className="inline-block max-w-sm whitespace-normal">{(row as ValidationRow).check}</span> }, { key: 'result', label: 'نتيجة النسخة المفحوصة', render: (row) => <StatePill tone={(row as ValidationRow).result === 'pass' ? 'green' : (row as ValidationRow).result === 'fail' ? 'red' : 'gold'}>{{ pass: 'اجتازت', warning: 'تحذير', fail: 'فشلت' }[(row as ValidationRow).result]}</StatePill>, align: 'center' }, { key: 'details', label: 'الأسباب', render: (row) => <span className="inline-block max-w-sm whitespace-normal">{(row as ValidationRow).details || 'لا توجد مخالفات مسجلة ضمن نطاق الفحص'}</span> }, { key: 'fingerprint', label: 'بصمة النسخة المفحوصة', render: (row) => <span className="inline-block max-w-xs break-all whitespace-normal font-mono">{(row as ValidationRow).fingerprint || '—'}</span> }, { key: 'score', label: 'نسبة الفحوص المجتازة · ليست ثقة تداول', render: (row) => <span className="font-mono">{(row as ValidationRow).score}</span>, align: 'center' }, { key: 'checkedAt', label: 'وقت الفحص', render: (row) => (row as ValidationRow).checkedAt, align: 'left' }];
  if (tabId === 'provenance') return [{ key: 'asset', label: 'الأصل', render: (row) => (row as ProvenanceRow).asset }, { key: 'origin', label: 'المنشأ', render: (row) => (row as ProvenanceRow).origin }, { key: 'owner', label: 'المالك', render: (row) => (row as ProvenanceRow).owner }, { key: 'capturedAt', label: 'آخر شمعة مخزنة · ليس وقت الجلب', render: (row) => (row as ProvenanceRow).capturedAt, align: 'left' }, { key: 'hash', label: 'البصمة', render: (row) => <span className="font-mono text-neon-cyan">{(row as ProvenanceRow).hash}</span>, align: 'left' }];
  if (tabId === 'news') return [{ key: 'headline', label: 'العنوان', render: (row) => <span className="font-medium text-text-primary">{(row as NewsRow).headline}</span> }, { key: 'source', label: 'المصدر', render: (row) => (row as NewsRow).source }, { key: 'sentiment', label: 'النبرة', render: (row) => <StatePill tone="muted">{(row as NewsRow).sentiment}</StatePill>, align: 'center' }, { key: 'relevance', label: 'الصلة', render: (row) => <span className="font-mono">{(row as NewsRow).relevance}</span>, align: 'center' }, { key: 'publishedAt', label: 'النشر', render: (row) => (row as NewsRow).publishedAt, align: 'left' }];
  return [{ key: 'name', label: 'الاسم', render: (row) => <span className="font-medium text-text-primary">{(row as ArtifactRow).name}</span> }, { key: 'kind', label: 'النوع', render: (row) => (row as ArtifactRow).kind }, { key: 'version', label: 'الإصدار', render: (row) => <span className="font-mono text-neon-cyan">{(row as ArtifactRow).version}</span>, align: 'center' }, { key: 'size', label: 'الحجم', render: (row) => <span className="font-mono">{(row as ArtifactRow).size}</span>, align: 'center' }, { key: 'state', label: 'الحالة', render: (row) => <StatePill tone="muted">{(row as ArtifactRow).state}</StatePill>, align: 'center' }];
}

function StateBanner({ state }: { state: ResearchViewState }) {
  if (state === 'unavailable') return <div role="status" className="rounded-lg border border-neon-gold/25 bg-neon-gold/5 px-3 py-2 text-xs text-neon-gold">المصدر غير متاح أو لم يُوصَل بعد. هذه ليست نتيجة فارغة ولا فحصًا ناجحًا.</div>;
  if (state === 'degraded') return <div role="alert" className="rounded-lg border border-neon-gold/25 bg-neon-gold/5 px-3 py-2 text-xs text-neon-gold">المصدر متدهور؛ قد تكون الأدلة جزئية أو غير صالحة للاعتماد.</div>;
  if (state === 'loading') return <div className="flex items-center gap-2 rounded-lg border border-neon-cyan/20 bg-neon-cyan/5 px-3 py-2 text-xs text-neon-cyan"><Clock3 className="h-3.5 w-3.5 animate-pulse" /> جارٍ تجهيز العرض…</div>;
  if (state === 'error') return <div role="alert" className="flex items-center gap-2 rounded-lg border border-neon-red/25 bg-neon-red/5 px-3 py-2 text-xs text-neon-red"><AlertTriangle className="h-3.5 w-3.5" /> تعذر قراءة المصدر. ما يظهر هنا لا يمثل حالة تشغيلية.</div>;
  return <div className="flex items-center gap-2 rounded-lg border border-neon-green/20 bg-neon-green/5 px-3 py-2 text-xs text-neon-green"><CheckCircle2 className="h-3.5 w-3.5" /> عرض للقراءة فقط · لا توجد عمليات كتابة أو تشغيل</div>;
}

function LoadingRows() { return <div className="space-y-2 rounded-xl border border-border-primary/25 bg-bg-secondary/20 p-4">{[1, 2, 3].map((item) => <div key={item} className="h-10 animate-pulse rounded-lg bg-bg-tertiary/60" />)}</div>; }

export function ResearchLabTab<T extends ResearchRow>({ definition, rows, state, query, onQueryChange, onFilterOpen }: ResearchLabTabProps<T>) {
  const filteredRows = rows.filter((row) => JSON.stringify(row).toLowerCase().includes(query.toLowerCase()));
  const genericRows = filteredRows as ReadonlyArray<ResearchRow>;
  let content: ReactNode;
  if (state === 'loading') content = <LoadingRows />;
  else if (state === 'error' || state === 'unavailable') content = null;
  else if (filteredRows.length === 0) content = <div role="status" className="rounded-xl border border-dashed border-border-primary/40 p-8 text-center text-xs text-text-muted">{state === 'empty' ? 'المصدر متاح ولا يحتوي سجلات.' : query && rows.length > 0 ? 'لا توجد سجلات مطابقة للبحث في الصفحة المعروضة.' : 'لا توجد سجلات قابلة للعرض؛ لا يمكن تأكيد أن المصدر فارغ.'}</div>;
  else if (definition.id === 'strategies') content = <StrategyTable rows={genericRows as ReadonlyArray<StrategyRow>} />;
  else if (definition.id === 'backtests') content = <BacktestTable rows={genericRows as ReadonlyArray<BacktestRow>} />;
  else content = <ResearchLabTable rows={genericRows} columns={rowColumns(definition.id)} emptyTitle="لا توجد سجلات" emptyDescription="المصدر المقروء فارغ حاليًا. لا توجد بيانات وهمية معروضة في هذه الواجهة." />;
  return <section className="space-y-4" aria-labelledby={`${definition.id}-heading`} dir="rtl">
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border-primary/30 bg-bg-secondary/30 p-4">
      <div className="flex-1"><h2 id={`${definition.id}-heading`} className="text-base font-bold">{definition.arabicLabel}</h2><p className="text-[11px] text-text-muted">{definition.englishLabel} · {definition.description}</p></div>
      <label className="flex items-center gap-2 rounded-lg border border-border-primary/30 px-3 py-2 text-xs"><Search className="h-3.5 w-3.5" /><span className="sr-only">بحث</span><input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="بحث في السجلات المعروضة" className="w-44 bg-transparent outline-none" /></label>
      <button type="button" onClick={onFilterOpen} className="flex items-center gap-2 text-xs text-text-muted"><SlidersHorizontal size={13} /> فلاتر <Filter size={11} /></button>
      <span className="flex items-center gap-1 text-[10px] text-text-muted"><LockKeyhole size={12} /> للقراءة فقط</span>
    </div>
    <StateBanner state={state} />
    {definition.id === 'strategies' && (state === 'readonly' || state === 'empty') && <StrategyHeader />}
    {definition.id === 'backtests' && (state === 'readonly' || state === 'empty') && <BacktestHeader />}
    {state !== 'loading' && state !== 'error' && state !== 'unavailable' && <p className="text-[11px] text-text-muted">{filteredRows.length} سجل معروض{query ? ' بعد البحث' : ''} · {state === 'empty' ? 'المصدر متاح لكنه لا يحتوي سجلات.' : 'السجلات المقروءة لا تعني اعتمادها للتداول.'}</p>}
    {content}
  </section>;
}
