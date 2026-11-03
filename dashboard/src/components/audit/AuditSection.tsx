'use client';

import type { ReactNode } from 'react';
import { Database, FileText, GitCommitHorizontal, ListChecks } from 'lucide-react';
import type { AuditSectionState } from './types';

const icons = { plan: ListChecks, files: FileText, git: GitCommitHorizontal, database: Database };

export default function AuditSection({ title, eyebrow, icon, state = 'ready', emptyLabel = 'لا توجد أدلة متاحة حاليًا', children }: { title: string; eyebrow: string; icon: keyof typeof icons; state?: AuditSectionState; emptyLabel?: string; children?: ReactNode }) {
  const Icon = icons[icon];
  return <section className="rounded-lg border border-border-primary bg-bg-card" aria-busy={state === 'unavailable'}><div className="flex items-center justify-between border-b border-border-primary px-4 py-3"><div className="flex min-w-0 items-center gap-2"><Icon size={16} className="shrink-0 text-neon-cyan" /><div className="min-w-0"><p className="text-[9px] uppercase tracking-[0.18em] text-text-muted">{eyebrow}</p><h2 className="truncate text-sm font-bold text-text-primary">{title}</h2></div></div><span className={`h-1.5 w-1.5 rounded-full ${state === 'ready' ? 'bg-neon-green' : state === 'empty' ? 'bg-neon-gold' : 'bg-neon-red'}`} /></div><div className="p-4">{state === 'ready' ? children : <div className="rounded border border-dashed border-border-primary px-4 py-6 text-center text-xs text-text-muted">{state === 'unavailable' ? 'تعذر تحميل هذا المصدر' : emptyLabel}</div>}</div></section>;
}
