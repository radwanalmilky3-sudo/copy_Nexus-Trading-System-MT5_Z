'use client';

import { cn } from '@/lib/utils';
import { useDashboardStore } from '@/stores/dashboardStore';
import { GlowText } from '@/components/shared/GlowText';
import { apiClient } from '@/lib/api-client';
import { autoTradeEnabled as autoTradeTouchable, autoTradeServerCheck } from '@/lib/trade-controls-presentation';
import { Bot, BotOff } from 'lucide-react';
import { useState, useCallback, useRef, useEffect } from 'react';

interface AutoTradeToggleProps {
  compact?: boolean;
}

export function AutoTradeToggle({ compact = false }: AutoTradeToggleProps) {
  const { autoTradeEnabled, isKilled, systemStateStatus } = useDashboardStore();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const btnRef = useRef<HTMLButtonElement>(null);
  const [popupPos, setPopupPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (confirmOpen && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPopupPos({ top: r.bottom + 8, left: r.left + r.width / 2 });
    }
  }, [confirmOpen]);

  const requestToggle = useCallback(async (enabled: boolean, pinValue?: string) => {
    setBusy(true);
    setError('');
    try {
      const response = await apiClient.systemToggleAutoTrade(enabled, pinValue);
      autoTradeServerCheck(response, enabled);
      useDashboardStore.getState().setAutoTrade(response.data.auto_trade);
      setConfirmOpen(false);
      setPin('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر تحديث حالة التداول الآلي');
    } finally {
      setBusy(false);
    }
  }, []);

  const handleToggle = useCallback(() => {
    if (!autoTradeTouchable({ isKilled, busy, systemStateStatus })) return;

    if (autoTradeEnabled) {
      void requestToggle(false);
    } else {
      setError('');
      setPin('');
      setConfirmOpen(true);
    }
  }, [autoTradeEnabled, busy, isKilled, requestToggle, systemStateStatus]);

  const handleConfirm = useCallback(() => {
    if (!pin.trim() || busy) return;
    void requestToggle(true, pin.trim());
  }, [busy, pin, requestToggle]);

  if (compact) {
    return (
      <>
        <button
          ref={btnRef}
          onClick={handleToggle}
          disabled={isKilled || busy || systemStateStatus !== 'confirmed'}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-bold uppercase transition-all',
            autoTradeEnabled
              ? 'bg-neon-green/10 border border-neon-green/40 text-neon-green shadow-neon-green'
              : 'bg-bg-input border border-border-primary text-text-muted',
            (isKilled || busy || systemStateStatus !== 'confirmed') && 'opacity-40 cursor-not-allowed'
          )}
        >
          {autoTradeEnabled ? <Bot className="h-3.5 w-3.5" /> : <BotOff className="h-3.5 w-3.5" />}
          {systemStateStatus === 'confirmed' ? (autoTradeEnabled ? 'Auto' : 'Off') : 'Sync'}
        </button>

        {/* Fixed confirm — avoids overflow-x-auto clipping from nav bar */}
        {error && <p role="alert" className="mt-2 max-w-56 text-center text-[10px] text-neon-red">{error}</p>}
        {confirmOpen && (
          <div
            className="fixed z-[200] w-56 rounded-lg border border-border-primary bg-bg-card p-3 shadow-xl animate-fade-in"
            style={{ top: popupPos.top, left: popupPos.left, transform: 'translateX(-50%)' }}
          >
            <p className="text-xs text-text-secondary mb-2">¿Activar auto-trading? Se requiere permiso y PIN.</p>
            <input
              type="password"
              autoComplete="current-password"
              aria-label="PIN de autorización"
              value={pin}
              onChange={(event) => setPin(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') handleConfirm(); }}
              className="mb-3 w-full rounded-md border border-border-primary bg-bg-input px-3 py-2 text-center text-sm text-text-primary"
              placeholder="PIN"
              disabled={busy}
            />
            {error && <p role="alert" className="mb-2 text-[10px] text-neon-red">{error}</p>}
            <div className="flex gap-2">
              <button
                onClick={handleConfirm}
                disabled={busy || !pin.trim()}
                aria-busy={busy}
                className="flex-1 rounded-md bg-neon-green/20 border border-neon-green/40 px-3 py-1 text-xs font-bold text-neon-green hover:bg-neon-green/30 transition-colors"
              >
                {busy ? 'جارٍ التحقق…' : 'Activar'}
              </button>
              <button
                onClick={() => setConfirmOpen(false)}
                disabled={busy}
                className="flex-1 rounded-md bg-bg-tertiary border border-border-primary px-3 py-1 text-xs font-medium text-text-muted hover:text-text-secondary transition-colors"
              >
                Cancelar
              </button>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div className="flex flex-col items-center gap-3">
      {/* Large toggle */}
      <button
        onClick={handleToggle}
        disabled={isKilled || busy || systemStateStatus !== 'confirmed'}
        className={cn(
          'relative w-20 h-10 rounded-full transition-all duration-300',
          autoTradeEnabled
            ? 'bg-neon-green/20 shadow-neon-green'
            : 'bg-bg-tertiary',
          (isKilled || busy || systemStateStatus !== 'confirmed') && 'opacity-40 cursor-not-allowed'
        )}
      >
        <span
          className={cn(
            'absolute top-1 left-1 h-8 w-8 rounded-full transition-all duration-300 flex items-center justify-center',
            autoTradeEnabled
              ? 'translate-x-10 bg-neon-green shadow-neon-green'
              : 'translate-x-0 bg-border-primary'
          )}
        >
          {autoTradeEnabled ? (
            <Bot className="h-4 w-4 text-bg-primary" />
          ) : (
            <BotOff className="h-4 w-4 text-text-muted" />
          )}
        </span>
      </button>

      <GlowText
        color={autoTradeEnabled ? 'green' : 'red'}
        size="sm"
        pulse={autoTradeEnabled}
      >
        {systemStateStatus === 'confirmed'
          ? (autoTradeEnabled ? 'AUTO TRADING ON' : 'AUTO TRADING OFF')
          : (systemStateStatus === 'loading' ? 'SYNCING SYSTEM STATE' : 'SYSTEM STATE UNKNOWN')}
      </GlowText>
      {error && !confirmOpen && <p role="alert" className="max-w-xs text-center text-xs text-neon-red">{error}</p>}

      {/* Confirm dialog overlay */}
      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg-overlay animate-fade-in">
          <div className="w-80 rounded-xl border border-border-primary bg-bg-card p-6 shadow-lg animate-slide-up">
            <h3 className="text-lg font-semibold text-text-primary mb-2">
              Enable Auto-Trading
            </h3>
            <p className="text-sm text-text-secondary mb-6">
              The server will validate your permission and PIN before enabling automated trading.
            </p>
            <input
              type="password"
              autoComplete="current-password"
              aria-label="Authorization PIN"
              value={pin}
              onChange={(event) => setPin(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') handleConfirm(); }}
              className="mb-3 w-full rounded-lg border border-border-primary bg-bg-input px-4 py-3 text-center text-text-primary"
              placeholder="PIN"
              disabled={busy}
            />
            {error && <p role="alert" className="mb-3 text-center text-xs text-neon-red">{error}</p>}
            <div className="flex gap-3">
              <button
                onClick={handleConfirm}
                disabled={busy || !pin.trim()}
                aria-busy={busy}
                className="flex-1 rounded-lg bg-neon-green/20 border border-neon-green/40 px-4 py-2 text-sm font-bold text-neon-green hover:bg-neon-green/30 hover:shadow-neon-green transition-all"
              >
                {busy ? 'Validating…' : 'Enable'}
              </button>
              <button
                onClick={() => setConfirmOpen(false)}
                disabled={busy}
                className="flex-1 rounded-lg bg-bg-tertiary border border-border-primary px-4 py-2 text-sm font-medium text-text-muted hover:text-text-secondary transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
