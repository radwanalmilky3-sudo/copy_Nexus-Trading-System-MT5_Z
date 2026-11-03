'use client';

import type { AuditStatus } from './types';

const labels: Record<AuditStatus, string> = { done: 'مكتمل', in_progress: 'قيد التنفيذ', pending: 'معلّق', unknown: 'غير معروف' };
const styles: Record<AuditStatus, string> = { done: 'border-neon-green/30 bg-neon-green/10 text-neon-green', in_progress: 'border-neon-cyan/30 bg-neon-cyan/10 text-neon-cyan', pending: 'border-neon-gold/30 bg-neon-gold/10 text-neon-gold', unknown: 'border-border-primary bg-bg-tertiary text-text-muted' };

export default function AuditStatusBadge({ status }: { status?: AuditStatus }) { const value = status ?? 'unknown'; return <span className={`inline-flex rounded border px-2 py-0.5 text-[10px] font-medium ${styles[value]}`}>{labels[value]}</span>; }
