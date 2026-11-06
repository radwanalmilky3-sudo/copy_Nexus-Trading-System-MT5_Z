'use client';

import { useEffect, useRef, useState } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient } from '@/lib/api-client';

/**
 * LiveGoldPrice — T-027: chip حي في رأس الداشبورد يعرض آخر إغلاق XAUUSD.
 * يستطلم M15 (الإطار المتراكم فعلياً — OHLCV_TIMEFRAMES) مع سقوط إلى M1، كل 5 ثوانٍ؛ عند غياب البيانات
 * أو الخطأ يظهر '—' بهدوء (لا إزعاج ولا سبام أخطاء). الاتجاه يُقارن بإغلاق
 * الشمعة السابقة وليس بفرضية محلية.
 */
export default function LiveGoldPrice() {
  const [price, setPrice] = useState<number | null>(null);
  const [dir, setDir] = useState<'up' | 'down' | 'flat'>('flat');
  const prevClose = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const tick = async () => {
      if (!cancelled && typeof document !== 'undefined' && document.hidden) {
        timer = setTimeout(tick, 5000);
        return;
      }
      try {
        let bars: Array<{ close: number }> = [];
        try {
          const res = await apiClient.getCandles('XAUUSD', 'M15', 2);
          bars = (res?.data ?? []) as Array<{ close: number }>;
        } catch {
          bars = [];
        }
        if (bars.length === 0) {
          const res1 = await apiClient.getCandles('XAUUSD', 'M1', 2);
          bars = (res1?.data ?? []) as Array<{ close: number }>;
        }
        const last = bars.length > 0 ? bars[bars.length - 1] : null;
        if (!cancelled && last) {
          const close = Number(last.close);
          if (Number.isFinite(close) && close > 0) {
            setPrice(close);
            const prev = bars.length > 1 ? Number(bars[bars.length - 2].close) : prevClose.current;
            if (prev && Number.isFinite(prev)) {
              setDir(close > prev ? 'up' : close < prev ? 'down' : 'flat');
            }
            prevClose.current = close;
          }
        }
      } catch {
        // هادئ: الشريحة تُبقي آخر قيمة معروفة وتعيد المحاولة
      }
      if (!cancelled) timer = setTimeout(tick, 5000);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return (
    <div
      data-testid="live-gold-price"
      title="XAUUSD — آخر إغلاق M1 من خدمة البيانات"
      className="hidden md:flex items-center gap-1.5 px-2 py-1 rounded-md border border-amber-500/20 bg-amber-500/5 font-mono"
    >
      <span className="text-[9px] font-bold tracking-wider text-amber-400/80">XAUUSD</span>
      {price !== null ? (
        <span
          className={cn(
            'num text-[11px] font-bold tabular-nums',
            dir === 'up' && 'text-neon-green',
            dir === 'down' && 'text-neon-red',
            dir === 'flat' && 'text-amber-200',
          )}
        >
          {price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </span>
      ) : (
        <span className="text-[11px] font-bold text-text-muted">—</span>
      )}
      {dir === 'up' && <TrendingUp className="h-3 w-3 text-neon-green" />}
      {dir === 'down' && <TrendingDown className="h-3 w-3 text-neon-red" />}
    </div>
  );
}

/** شارة الإصدار — تُخبز وقت البناء عبر NEXT_PUBLIC_BUILD_ID (commit قصير). */
export function BuildBadge() {
  const build = process.env.NEXT_PUBLIC_BUILD_ID ?? '';
  if (!build) return null;
  return (
    <span
      data-testid="build-badge"
      title="إصدار البناء الحالي"
      className="hidden lg:inline px-1.5 py-0.5 rounded text-[8px] font-mono text-text-muted border border-border-primary/60 select-none"
    >
      build:{build}
    </span>
  );
}
