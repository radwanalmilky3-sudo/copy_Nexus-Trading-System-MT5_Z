'use client';

import { BarChart3 } from 'lucide-react';
import { ResearchLabTable, StatePill, type ResearchColumn } from './ResearchLabTable';
import type { BacktestRow } from './types';

const columns: ReadonlyArray<ResearchColumn<BacktestRow>> = [
  { key: 'strategy', label: 'الاستراتيجية', render: (row) => <span className="font-medium text-text-primary">{row.strategy}</span> },
  { key: 'period', label: 'الفترة', render: (row) => row.period },
  { key: 'market', label: 'السوق', render: (row) => <span className="font-mono text-neon-cyan">{row.market}</span>, align: 'center' },
  { key: 'returnPct', label: 'العائد', render: (row) => <span className="font-mono text-neon-green">{row.returnPct}</span>, align: 'center' },
  { key: 'maxDrawdownPct', label: 'أقصى تراجع', render: (row) => <span className="font-mono text-neon-red">{row.maxDrawdownPct}</span>, align: 'center' },
  { key: 'status', label: 'الحالة', render: (row) => <StatePill tone={row.status === 'complete' ? 'green' : row.status === 'blocked' ? 'red' : 'gold'}>{row.status}</StatePill>, align: 'center' },
];

export function BacktestTable({ rows }: { rows: ReadonlyArray<BacktestRow> }) { return <ResearchLabTable rows={rows} columns={columns} emptyTitle="لا توجد اختبارات تاريخية" emptyDescription="مصدر نتائج الـ backtest فارغ حاليًا. لا يتم تشغيل أو جدولة أي اختبار من هذه الصفحة." />; }
export function BacktestHeader() { return <div className="flex items-center gap-2 text-xs text-text-muted"><BarChart3 className="h-4 w-4 text-neon-cyan" /><span>نتائج الاختبارات التاريخية · غير قابلة للتعديل</span></div>; }
