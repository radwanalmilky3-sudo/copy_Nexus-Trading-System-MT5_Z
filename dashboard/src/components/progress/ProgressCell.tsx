import { memo } from 'react';

const STATUS_AR: Record<string, string> = {
  pending: 'قيد الانتظار',
  in_progress: 'قيد التنفيذ',
  done: 'مكتملة',
  failed: 'فشل',
};

function ProgressCell({ value, isActive = false, status = 'pending', showSpinner = false }: { value?: number | null; isActive?: boolean; status?: string; showSpinner?: boolean }) {
  const isNull = value == null;
  const percent = typeof value === 'number' ? Math.max(0, Math.min(100, value)) : 0;
  const complete = percent >= 100;
  const started = percent > 0;
  const statusLabel = STATUS_AR[status] ?? status;
  return <div className="min-w-20 space-y-1" title={isNull ? `لم يتم تقييم هذا البعد · الحالة: ${statusLabel}` : `القيمة: ${value} · الحالة: ${statusLabel}`}>
    <div className="flex items-center justify-center gap-1 font-mono text-[10px]">
      {showSpinner && (complete || status === 'done') && <span className="text-neon-green">✓</span>}
      {showSpinner && !complete && status === 'in_progress' && isActive === true && <span className="text-blue-400 spin-slow">⟳</span>}
      {showSpinner && !complete && status === 'pending' && isActive === true && <span className="text-yellow-400 pulse-scale">⏳</span>}
      <span
        className={complete ? 'text-neon-green' : started ? 'text-neon-cyan' : isNull ? 'text-text-muted underline decoration-dotted underline-offset-2' : 'text-yellow-400'}
        title={isNull ? 'لم يتم تقييم هذا البعد' : undefined}
      >{typeof value === 'number' ? `${percent}%` : '—'}</span>
      {showSpinner && isActive === true && !complete && <span className="text-neon-cyan" title="المهمة الحالية">●</span>}
    </div>
    <div className="h-1 overflow-hidden rounded-full bg-bg-tertiary"><div className={`h-full rounded-full transition-[width] duration-500 ${complete ? 'bg-neon-green' : started ? 'bg-neon-cyan' : 'bg-yellow-400'}`} style={{width:`${percent}%`}} /></div>
  </div>;
}

export default memo(ProgressCell);
