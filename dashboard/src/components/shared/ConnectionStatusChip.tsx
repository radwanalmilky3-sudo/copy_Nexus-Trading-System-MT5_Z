'use client';

import { useEffect, useState } from 'react';
import {
  subscribeWsAggregate,
  type WsConnectionState,
} from '@/hooks/useWebSocket';
import { cn } from '@/lib/utils';

const LABELS: Record<WsConnectionState, string> = {
  connected: 'البث متصل',
  connecting: 'جارٍ الاتصال…',
  reconnecting: 'إعادة الاتصال…',
  failed: 'تعذر الاتصال',
  idle: 'البث غير مفعّل',
};

const DOT: Record<WsConnectionState, string> = {
  connected: 'bg-neon-green',
  connecting: 'bg-neon-cyan animate-pulse-dot',
  reconnecting: 'bg-neon-orange animate-pulse-dot',
  failed: 'bg-neon-red',
  idle: 'bg-gray-500',
};

const TONE: Record<WsConnectionState, string> = {
  connected: 'text-neon-green border-neon-green/30 bg-neon-green/5',
  connecting: 'text-neon-cyan border-neon-cyan/30 bg-neon-cyan/5',
  reconnecting: 'text-neon-orange border-neon-orange/30 bg-neon-orange/5',
  failed: 'text-neon-red border-neon-red/30 bg-neon-red/5',
  idle: 'text-text-muted border-border-primary bg-bg-tertiary/40',
};

/**
 * Live data-feed status chip. Mirrors the aggregate state of the real
 * WebSocket instances mounted on the page — it never invents a connection.
 */
export default function ConnectionStatusChip({ className }: { className?: string }) {
  const [state, setState] = useState<WsConnectionState>('idle');

  useEffect(() => subscribeWsAggregate(setState), []);

  return (
    <span
      dir="rtl"
      title="حالة اتصال البث اللحظي (WebSocket)"
      className={cn(
        'flex items-center gap-1.5 rounded border px-2 py-1 font-mono text-[10px] whitespace-nowrap',
        TONE[state],
        className
      )}
    >
      <span className={cn('h-1.5 w-1.5 rounded-full', DOT[state])} />
      {LABELS[state]}
    </span>
  );
}
