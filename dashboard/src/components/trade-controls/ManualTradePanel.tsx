'use client';

import { cn } from '@/lib/utils';
import { useDashboardStore } from '@/stores/dashboardStore';
import { GlowText } from '@/components/shared/GlowText';
import NeonCard from '@/components/shared/NeonCard';
import { ArrowUpCircle, ArrowDownCircle, Activity } from 'lucide-react';
import { manualOrderPayload, manualOrderOutcome } from '@/lib/trade-controls-presentation';
import { apiClient } from '@/lib/api-client';
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

  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; message: string } | null>(null);

  /* المسار الآن موصول: POST /api/positions/manual-order في البوابة يمرّ عبر
   * نفس سلسلة الأمان الحتمية للوكلاء (تقييم المخاطر المركزية + موافقة موقّعة
   * + حارس المنفّذ). الحارس لا يُضعَف للنقر اليدوي؛ كل رفض يُعرض بسبه الحقيقي. */
  const submit = useCallback(async (side: 'BUY' | 'SELL', price: number) => {
    if (busy) return;
    const payload = manualOrderPayload({ symbol, lots, sl, tp, price });
    if (!payload) {
      setNotice({ ok: false, message: 'راجع المدخلات: اللوت موجب وSL/TP أرقام صريحة (SL ليس فارغًا).' });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const response = await apiClient.placeManualOrder({
        symbol: payload.symbol,
        side,
        lots: payload.lots,
        entry: payload.price,
        sl: payload.sl,
        tp: payload.tp,
      });
      setNotice(manualOrderOutcome(response));
    } catch {
      setNotice({ ok: false, message: 'تعذر الوصول إلى البوابة؛ لم يُنفَّذ أي أمر.' });
    } finally {
      setBusy(false);
    }
  }, [busy, symbol, lots, sl, tp]);

  const handleBuy = useCallback(() => {
    void submit('BUY', currentAsk);
  }, [submit, currentAsk]);

  const handleSell = useCallback(() => {
    void submit('SELL', currentBid);
  }, [submit, currentBid]);

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

      {/* Action buttons — wired through the gateway manual-order route;
          every order passes central-risk approval + the executor guard. */}
      {notice && (
        <p role="status" className={cn('text-[10px] text-center px-2 py-1 rounded border',
          notice.ok ? 'text-neon-green bg-neon-green/10 border-neon-green/30' : 'text-neon-red bg-neon-red/10 border-neon-red/30')}>
          {notice.message}
        </p>
      )}
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={handleBuy}
          disabled={busy}
          title="شراء بسعر الطلب الحالي — يمرّ عبر تقييم المخاطر وحارس التنفيذ"
          aria-busy={busy}
          className={cn(
            'flex items-center justify-center gap-2 rounded-lg py-2.5',
            'bg-neon-green/10 border border-neon-green/40 text-neon-green',
            'font-bold text-sm uppercase tracking-wider',
            'hover:bg-neon-green/20 hover:shadow-neon-green active:scale-[0.98]',
            'transition-all duration-200 disabled:cursor-wait disabled:opacity-60'
          )}
        >
          <ArrowUpCircle className="h-4 w-4" />
          {busy ? '…' : 'Buy'}
        </button>
        <button
          onClick={handleSell}
          disabled={busy}
          title="بيع بسعر العرض الحالي — يمرّ عبر تقييم المخاطر وحارس التنفيذ"
          aria-busy={busy}
          className={cn(
            'flex items-center justify-center gap-2 rounded-lg py-2.5',
            'bg-neon-red/10 border border-neon-red/40 text-neon-red',
            'font-bold text-sm uppercase tracking-wider',
            'hover:bg-neon-red/20 hover:shadow-neon-red active:scale-[0.98]',
            'transition-all duration-200 disabled:cursor-wait disabled:opacity-60'
          )}
        >
          <ArrowDownCircle className="h-4 w-4" />
          {busy ? '…' : 'Sell'}
        </button>
      </div>
      <p className="text-[10px] leading-relaxed text-text-muted text-center">
        كل أمر يمرّ عبر تقييم المخاطر المركزية وموافقة موقّعة وحارس التنفيذ — وقد يُرفض بأمان (مفتاح الإيقاف، التداول الآلي، نافذة الأخبار، حدود الحجم).
      </p>
    </NeonCard>
  );
}
