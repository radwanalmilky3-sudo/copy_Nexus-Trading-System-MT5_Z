'use client';

import { FlaskConical } from 'lucide-react';
import { ResearchLabTable, StatePill, type ResearchColumn } from './ResearchLabTable';
import type { StrategyRow } from './types';

const columns: ReadonlyArray<ResearchColumn<StrategyRow>> = [
  { key: 'name', label: 'الاستراتيجية', render: (row) => <span className="font-medium text-text-primary">{row.name}</span> },
  { key: 'family', label: 'العائلة', render: (row) => row.family },
  { key: 'timeframe', label: 'الإطار الزمني', render: (row) => <span className="font-mono text-neon-cyan">{row.timeframe}</span>, align: 'center' },
  { key: 'status', label: 'الحالة', render: (row) => <StatePill tone={row.status === 'validated' ? 'green' : row.status === 'candidate' ? 'gold' : 'muted'}>{row.status}</StatePill>, align: 'center' },
  { key: 'confidence', label: 'الثقة', render: (row) => <span className="font-mono">{row.confidence}</span>, align: 'center' },
  { key: 'lastRun', label: 'آخر تشغيل', render: (row) => row.lastRun, align: 'left' },
];

export function StrategyTable({ rows }: { rows: ReadonlyArray<StrategyRow> }) { return <ResearchLabTable rows={rows} columns={columns} emptyTitle="لا توجد استراتيجيات مقروءة" emptyDescription="مصدر الاستراتيجيات غير موصول بعد. ستظهر هنا الاستراتيجيات المرشحة ونتائج تقييمها عند تفعيل مصدر بيانات موثّق." />; }
export function StrategyHeader() { return <div className="flex items-center gap-2 text-xs text-text-muted"><FlaskConical className="h-4 w-4 text-neon-purple" /><span>كتالوج الاستراتيجيات · عرض فقط</span></div>; }
