'use client';
import * as React from 'react';

type ServiceProbe = { name: string; status: string; latencyMs: number | null };
type HealthPayload = { checkedAt: string; services: ServiceProbe[] };

const labelOf = (name: string) => name === 'nexus-api' ? 'البوابة' : name === 'nexus-data' ? 'جسر البيانات (MT5)' : 'التنفيذ الورقي';
const statusOf = (status: string) => status === 'online' ? 'متصل' : status === 'degraded' ? 'متصل بتنقيص' : 'غير متصل';
const toneOf = (status: string) => status === 'online' ? 'border-neon-green/40 text-neon-green' : status === 'degraded' ? 'border-neon-gold/40 text-neon-gold' : 'border-neon-red/40 text-neon-red';

export default function SystemHealthStrip() {
  const [health, setHealth] = React.useState<HealthPayload | null>(null);
  React.useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/api/health', { cache: 'no-store' });
        if (!res.ok) throw new Error('health probe failed');
        const p = await res.json();
        if (!cancelled && p?.services) setHealth({ checkedAt: p.checkedAt, services: p.services });
      } catch {/* حالة الخدمات إرشادية ولا تعيق فحص الحساب */}
    };
    load();
    const timer = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);
  return <div className="flex flex-wrap items-center gap-3 rounded border border-border-primary bg-bg-secondary/30 p-3" aria-label="حالة أسطول النظام">
    <span className="text-sm font-bold">حالة أسطول النظام:</span>
    {health ? health.services.filter(x => ['nexus-api', 'nexus-data', 'nexus-executor'].includes(x.name)).map(x =>
      <span key={x.name} className={`rounded border px-2 py-1 text-xs font-semibold ${toneOf(x.status)}`}>{labelOf(x.name)}: {statusOf(x.status)}{typeof x.latencyMs === 'number' ? ` · ${x.latencyMs}ms` : ''}</span>)
      : <span className="text-xs text-text-muted">جارٍ قراءة حالة الخدمات…</span>}
    <span className="text-xs text-text-muted">هذه حالة الخدمات عامة؛ فحص حسابك تحديدًا يتم بزر «التحقق من اتصال MT5» بعد اختيار الحساب.</span>
  </div>;
}
