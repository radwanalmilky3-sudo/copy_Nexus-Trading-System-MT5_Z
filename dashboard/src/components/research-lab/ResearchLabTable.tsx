'use client';

import type { ReactNode } from 'react';
import { Database, LockKeyhole } from 'lucide-react';
import type { ResearchRow } from './types';

export interface ResearchColumn<T extends ResearchRow> { readonly key: string; readonly label: string; readonly render: (row: T) => ReactNode; readonly align?: 'right' | 'center' | 'left'; }

interface ResearchLabTableProps<T extends ResearchRow> { readonly rows: ReadonlyArray<T>; readonly columns: ReadonlyArray<ResearchColumn<T>>; readonly emptyTitle: string; readonly emptyDescription: string; }

export function ResearchLabTable<T extends ResearchRow>({ rows, columns, emptyTitle, emptyDescription }: ResearchLabTableProps<T>) {
  if (rows.length === 0) return <div className="flex min-h-[260px] flex-col items-center justify-center rounded-xl border border-dashed border-border-primary/40 bg-bg-secondary/30 px-6 text-center"><Database className="mb-3 h-8 w-8 text-neon-cyan/50" /><p className="text-sm font-semibold text-text-primary">{emptyTitle}</p><p className="mt-1 max-w-md text-xs leading-6 text-text-muted">{emptyDescription}</p><span className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-border-primary/40 bg-bg-primary/60 px-2.5 py-1 text-[10px] font-mono text-text-muted"><LockKeyhole className="h-3 w-3" /> READ ONLY · EMPTY SOURCE</span></div>;
  return <div className="overflow-x-auto rounded-xl border border-border-primary/30 bg-bg-secondary/20"><table className="min-w-full border-collapse text-right" dir="rtl"><thead><tr className="border-b border-border-primary/30 bg-bg-secondary/70">{columns.map((column) => <th key={column.key} className={`whitespace-nowrap px-4 py-3 text-[10px] font-semibold tracking-wide text-text-muted ${column.align === 'center' ? 'text-center' : column.align === 'left' ? 'text-left' : 'text-right'}`}>{column.label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id} className="border-b border-border-primary/15 last:border-0 hover:bg-bg-card-hover/50">{columns.map((column) => <td key={`${row.id}-${column.key}`} className={`whitespace-nowrap px-4 py-3 text-xs text-text-secondary ${column.align === 'center' ? 'text-center' : column.align === 'left' ? 'text-left' : 'text-right'}`}>{column.render(row)}</td>)}</tr>)}</tbody></table></div>;
}

export function StatePill({ tone, children }: { tone: 'muted' | 'green' | 'gold' | 'red' | 'cyan'; children: ReactNode }) {
  const toneClass = { muted: 'border-border-primary/40 bg-bg-secondary text-text-muted', green: 'border-neon-green/25 bg-neon-green/10 text-neon-green', gold: 'border-neon-gold/25 bg-neon-gold/10 text-neon-gold', red: 'border-neon-red/25 bg-neon-red/10 text-neon-red', cyan: 'border-neon-cyan/25 bg-neon-cyan/10 text-neon-cyan' }[tone];
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${toneClass}`}>{children}</span>;
}
