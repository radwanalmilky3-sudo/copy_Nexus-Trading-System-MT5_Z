'use client';

import { cn } from '@/lib/utils';
import { useDashboardStore } from '@/stores/dashboardStore';
import { GlowText } from '@/components/shared/GlowText';
import NeonCard from '@/components/shared/NeonCard';
import { ArrowUpCircle, ArrowDownCircle, Activity } from 'lucide-react';
import { manualOrderPayload } from '@/lib/trade-controls-presentation';
import { useState, useCallback } from 'react';

interface ManualTradePanelProps {
  currentBid?: number;
  currentAsk?: number;
  spread?: number;
}

export function ManualTradePanel({
  currentBid = 1.08452,
  currentAsk = 1.08468,
  spread = 1.6,
}: ManualTradePanelProps) {
  const { symbol } = useDashboardStore();
  const [lots, setLots] = useState('0.01');
  const [sl, setSl] = useState('50');
  const [tp, setTp] = useState('100');

  /* صدق الواجهة: لا يوجد مسار بوابة للأوامر اليدوية — /api/executor/order
   * نقطة داخلية محمية بسرّ الخدمات ولا يمكن للمتصفح استدعاءها. الأزرار
   * معطّلة صراحة حتى يوفر البوابة مسارًا مُصرّحًا به؛ لا نُمثّل تنفيذًا. */
  const executionWired = false;

  const handleBuy = useCallback(() => {
    if (!executionWired) return;
    const payload = manualOrderPayload({ symbol, lots, sl, tp, price: currentAsk });
    if (payload) console.log('Manual BUY:', payload);
  }, [executionWired, symbol, lots, sl, tp, currentAsk]);

  const handleSell = useCallback(() => {
    if (!executionWired) return;
    const payload = manualOrderPayload({ symbol, lots, sl, tp, price: currentBid });
    if (payload) console.log('Manual SELL:', payload);
  }, [executionWired, symbol, lots, sl, tp, currentBid]);

  return (
    <NeonCard title="تداول يدوي" accentColor="cyan" isLive>
      {/* Price display */}
      <div className="flex items-center justify-between mb-4">
        <div className="text-center">
          <div className="text-[10px] uppercase text-text-muted font-mono mb-0.5">Bid</div>
          <GlowText color="red" size="lg" className="font-mono">
            {currentBid.toFixed(5)}
          </GlowText>
        </div>

        <div className="flex flex-col items-center gap-0.5">
          <Activity className="h-3.5 w-3.5 text-text-muted" />
          <span className="text-[10px] font-mono text-text-muted">{spread.toFixed(1)} pip</span>
        </div>

        <div className="text-center">
          <div className="text-[10px] uppercase text-text-muted font-mono mb-0.5">Ask</div>
          <GlowText color="green" size="lg" className="font-mono">
            {currentAsk.toFixed(5)}
          </GlowText>
        </div>
      </div>

      {/* Input fields */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <div>
          <label className="block text-[10px] uppercase text-text-muted font-mono mb-1">
            Lots
          </label>
          <input
            type="number"
            step="0.01"
            min="0.01"
            value={lots}
            onChange={(e) => setLots(e.target.value)}
            className={cn(
              'w-full rounded-md bg-bg-input border border-border-primary px-2 py-1.5',
              'text-sm font-mono text-text-primary',
              'focus:outline-none focus:border-neon-purple/60 transition-colors'
            )}
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase text-text-muted font-mono mb-1">
            SL (pips)
          </label>
          <input
            type="number"
            step="1"
            min="0"
            value={sl}
            onChange={(e) => setSl(e.target.value)}
            className={cn(
              'w-full rounded-md bg-bg-input border border-border-primary px-2 py-1.5',
              'text-sm font-mono text-text-primary',
              'focus:outline-none focus:border-neon-red/60 transition-colors'
            )}
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase text-text-muted font-mono mb-1">
            TP (pips)
          </label>
          <input
            type="number"
            step="1"
            min="0"
            value={tp}
            onChange={(e) => setTp(e.target.value)}
            className={cn(
              'w-full rounded-md bg-bg-input border border-border-primary px-2 py-1.5',
              'text-sm font-mono text-text-primary',
              'focus:outline-none focus:border-neon-green/60 transition-colors'
            )}
          />
        </div>
      </div>

      {/* Action buttons — disabled until the gateway exposes an authorized
          manual-order route; the executor endpoint is internal-only. */}
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={handleBuy}
          disabled
          title="تنفيذ الأوامر اليدوية غير موصول بمحرك التنفيذ بعد"
          className={cn(
            'flex items-center justify-center gap-2 rounded-lg py-2.5',
            'bg-neon-green/10 border border-neon-green/40 text-neon-green',
            'font-bold text-sm uppercase tracking-wider',
            'opacity-40 cursor-not-allowed'
          )}
        >
          <ArrowUpCircle className="h-4 w-4" />
          Buy
        </button>
        <button
          onClick={handleSell}
          disabled
          title="تنفيذ الأوامر اليدوية غير موصول بمحرك التنفيذ بعد"
          className={cn(
            'flex items-center justify-center gap-2 rounded-lg py-2.5',
            'bg-neon-red/10 border border-neon-red/40 text-neon-red',
            'font-bold text-sm uppercase tracking-wider',
            'opacity-40 cursor-not-allowed'
          )}
        >
          <ArrowDownCircle className="h-4 w-4" />
          Sell
        </button>
      </div>
      <p className="text-[10px] leading-relaxed text-text-muted text-center">
        تنفيذ الأوامر اليدوية غير موصول بمحرك التنفيذ بعد — الأزرار معطّلة حتى توفير مسار مُصرّح به في البوابة.
      </p>
    </NeonCard>
  );
}
