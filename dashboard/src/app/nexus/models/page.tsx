'use client';

import React, { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { Cpu, Trophy } from 'lucide-react';
import { cn } from '@/lib/utils';
import { ModelsView } from './ModelsView';
import { ModelComparisonView } from '../model-comparison/ModelComparisonView';

// شاشة النماذج الموحّدة — تبويبان بدل صفحتين منفصلتين كانتا تزحمتان الشريط العلوي:
// «تفاصيل النماذج» (التفاصيل وسجل التدريب) و«مقارنة النماذج» (لوحة المتصدرين).
// المسار القديم /nexus/model-comparison يعيد التوجيه إلى هنا مع tab=compare.

type ModelsTab = 'details' | 'compare';

const TABS: { id: ModelsTab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'details', label: 'تفاصيل النماذج', icon: Cpu },
  { id: 'compare', label: 'مقارنة النماذج', icon: Trophy },
];

function ModelsTabs() {
  const params = useSearchParams();
  const initial: ModelsTab = params.get('tab') === 'compare' ? 'compare' : 'details';
  const [tab, setTab] = useState<ModelsTab>(initial);
  const active = TABS.find(t => t.id === tab)!;
  return <div className="space-y-4">
    <div className="flex gap-2 overflow-x-auto rounded-lg border border-border-primary bg-bg-secondary/30 p-2" role="tablist" aria-label="أقسام النماذج">
      {TABS.map(t => {
        const on = t.id === tab;
        return <button key={t.id} type="button" role="tab" aria-selected={on} onClick={() => setTab(t.id)}
          className={cn('inline-flex shrink-0 items-center gap-2 rounded border px-4 py-2 text-sm font-bold transition-colors',
            on ? 'border-neon-cyan bg-neon-cyan/15 text-neon-cyan' : 'border-transparent text-text-muted hover:text-text-secondary')}>
          <t.icon className="h-4 w-4" /><span>{t.label}</span>
        </button>;
      })}
    </div>
    {tab === 'details' ? <ModelsView /> : <ModelComparisonView />}
    <span className="sr-only">{active.label}</span>
  </div>;
}

export default function ModelsPage() {
  return <Suspense fallback={<p role="status">جارٍ تحميل النماذج…</p>}>
    <ModelsTabs />
  </Suspense>;
}
