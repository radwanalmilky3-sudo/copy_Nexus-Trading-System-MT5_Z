'use client';

import { cn } from '@/lib/utils';
import { useDashboardStore } from '@/stores/dashboardStore';
import { GlowText } from '@/components/shared/GlowText';
import { apiClient } from '@/lib/api-client';
import { killSwitchOutcome } from '@/lib/trade-controls-presentation';
import { ShieldAlert, X, AlertTriangle } from 'lucide-react';
import { useState, useCallback, useRef } from 'react';

interface KillSwitchProps {
  compact?: boolean;
}

type DialogStep = 'confirm' | 'pin';
type DialogMode = 'kill' | 'release';

export function KillSwitch({ compact = false }: KillSwitchProps) {
  const { isKilled, activateKillSwitch, deactivateKillSwitch } = useDashboardStore();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [mode, setMode] = useState<DialogMode>('kill');
  const [step, setStep] = useState<DialogStep>('confirm');
  const [pin, setPin] = useState('');
  const [requestError, setRequestError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const openDialog = useCallback((nextMode: DialogMode) => {
    setMode(nextMode);
    setStep('confirm');
    setPin('');
    setRequestError('');
    setDialogOpen(true);
  }, []);

  const handleAdvanceToPIN = useCallback(() => {
    setStep('pin');
    setTimeout(() => inputRef.current?.focus(), 80);
  }, []);

  const handleConfirmPIN = useCallback(async () => {
    if (submitting) return;
    setRequestError('');
    setSubmitting(true);
    try {
      if (mode === 'kill') {
        const response = await apiClient.systemKillSwitch(pin, 'manual kill-switch from dashboard');
        if (!killSwitchOutcome(response, 'kill').ok) {
          setRequestError('The server did not confirm the emergency stop.');
          return;
        }
        activateKillSwitch();
      } else {
        const response = await apiClient.systemKillSwitchRelease(pin, 'manual release from dashboard');
        if (!killSwitchOutcome(response, 'release').ok) {
          setRequestError('The server did not confirm the release.');
          return;
        }
        deactivateKillSwitch();
      }
      setDialogOpen(false);
      setPin('');
    } catch {
      // Keep the last server-confirmed state; a failed request is not a state change.
      setRequestError(mode === 'kill'
        ? 'Could not confirm the emergency stop. Check the server connection and try again.'
        : 'Could not release the emergency stop. Check the server connection and try again.');
    } finally {
      setSubmitting(false);
    }
  }, [mode, pin, submitting, activateKillSwitch, deactivateKillSwitch]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleConfirmPIN();
      if (e.key === 'Escape') setDialogOpen(false);
    },
    [handleConfirmPIN],
  );

  function renderKillDialog() {
    const releaseMode = mode === 'release';
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg-overlay animate-fade-in">
        <div
          className={cn(
            'relative w-80 rounded-xl border bg-bg-card p-6 shadow-lg animate-slide-up',
            releaseMode
              ? 'border-neon-cyan/60 shadow-neon-cyan/20'
              : 'border-neon-red/60 shadow-neon-red/20',
          )}
        >
          <button
            onClick={() => setDialogOpen(false)}
            className="absolute top-3 right-3 text-text-muted hover:text-text-primary transition-colors"
          >
            <X className="h-4 w-4" />
          </button>

          <div className="flex flex-col items-center gap-3 mb-5">
            <ShieldAlert className={cn('h-10 w-10', releaseMode ? 'text-neon-cyan' : 'text-neon-red animate-neon-pulse')} />
            <h3 className="text-lg font-bold text-text-primary">
              {releaseMode ? 'RELEASE EMERGENCY STOP' : 'EMERGENCY STOP'}
            </h3>
          </div>

          {/* Step 1 — Are you sure? */}
          {step === 'confirm' && (
            <>
              <div className={cn(
                'mb-4 rounded-lg px-3 py-2.5 text-xs leading-relaxed',
                releaseMode
                  ? 'bg-neon-cyan/10 text-neon-cyan/90'
                  : 'bg-neon-red/10 text-neon-red/90',
              )}>
                {releaseMode
                  ? <>
                      <AlertTriangle className="inline h-3.5 w-3.5 mr-1 -mt-0.5" />
                      This <strong>clears the latched emergency stop</strong> and re-opens trading controls. Auto-trade stays OFF — re-enable it explicitly. Open positions are not touched.
                    </>
                  : <>
                      <AlertTriangle className="inline h-3.5 w-3.5 mr-1 -mt-0.5" />
                      This will <strong>halt all autonomous trading</strong> immediately. Open positions will remain until manually closed.
                    </>
                }
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setDialogOpen(false)}
                  className="flex-1 rounded-lg py-2.5 text-sm font-medium border border-border-primary text-text-secondary hover:text-text-primary transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleAdvanceToPIN}
                  className={cn(
                    'flex-1 rounded-lg py-2.5 text-sm font-bold uppercase tracking-wider transition-all',
                    releaseMode
                      ? 'bg-neon-cyan/20 border border-neon-cyan text-neon-cyan hover:bg-neon-cyan/30'
                      : 'bg-neon-red/20 border border-neon-red text-neon-red hover:bg-neon-red/30',
                  )}
                >
                  {releaseMode ? 'Yes, Release' : 'Yes, Stop'}
                </button>
              </div>
            </>
          )}

          {/* Step 2 — Enter PIN */}
          {step === 'pin' && (
            <>
              <p className="text-xs text-text-secondary text-center mb-4">
                Enter your 4-digit PIN to confirm.
              </p>
              <div className="mb-4">
                <input
                  ref={inputRef}
                  type="password"
                  value={pin}
                  onChange={(e) => { setPin(e.target.value); setRequestError(''); }}
                  onKeyDown={handleKeyDown}
                  placeholder="• • • •"
                  className={cn(
                    'w-full rounded-lg bg-bg-input border px-4 py-3 text-center text-lg font-mono tracking-[0.5em]',
                    'focus:outline-none transition-colors',
                    requestError
                      ? 'border-neon-red text-neon-red'
                      : 'border-border-primary text-text-primary focus:border-neon-purple/60',
                  )}
                />
                {requestError && (
                  <p role="alert" className="text-xs text-neon-red mt-1 text-center">{requestError}</p>
                )}
              </div>
              <button
                onClick={handleConfirmPIN}
                disabled={submitting}
                className={cn(
                  'w-full rounded-lg py-3 text-sm font-bold uppercase tracking-wider transition-all disabled:cursor-wait disabled:opacity-60',
                  releaseMode
                    ? 'bg-neon-cyan/20 border border-neon-cyan text-neon-cyan hover:bg-neon-cyan/30 hover:shadow-neon-cyan'
                    : 'bg-neon-red/20 border border-neon-red text-neon-red hover:bg-neon-red/30 hover:shadow-neon-red',
                )}
              >
                {submitting
                  ? (releaseMode ? 'RELEASING…' : 'STOPPING…')
                  : (releaseMode ? 'CONFIRM RELEASE' : 'CONFIRM KILL')}
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  if (compact) {
    return (
      <>
        <button
          onClick={() => openDialog(isKilled ? 'release' : 'kill')}
          title={isKilled ? 'Release the latched emergency stop (PIN required)' : 'Activate emergency stop'}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold uppercase transition-all',
            isKilled
              ? 'bg-neon-gold/15 border border-neon-gold text-neon-gold hover:bg-neon-gold/25 hover:shadow-neon-gold'
              : 'bg-neon-red/5 border border-neon-red/40 text-neon-red hover:bg-neon-red/10 hover:shadow-neon-red animate-neon-pulse',
          )}
        >
          <ShieldAlert className="h-3.5 w-3.5" />
          {isKilled ? 'RELEASE' : 'KILL'}
        </button>
        {dialogOpen && renderKillDialog()}
      </>
    );
  }

  return (
    <>
      <div className="flex flex-col items-center gap-3">
        <button
          onClick={() => openDialog(isKilled ? 'release' : 'kill')}
          className={cn(
            'relative flex flex-col items-center justify-center gap-2 rounded-2xl px-8 py-6 transition-all',
            isKilled
              ? 'bg-neon-gold/15 border-2 border-neon-gold text-neon-gold hover:bg-neon-gold/25 hover:shadow-neon-gold'
              : 'bg-neon-red/5 border-2 border-neon-red/40 text-neon-red hover:bg-neon-red/10 hover:shadow-neon-red animate-neon-pulse',
          )}
        >
          <ShieldAlert className="h-8 w-8" />
          <span className="text-sm font-bold uppercase tracking-widest">
            {isKilled ? 'Halted — Release' : 'Emergency Stop'}
          </span>
        </button>
        {isKilled && (
          <p className="text-xs text-text-muted text-center">
            Click to release the latched emergency stop (PIN required). Auto-trade stays off until re-enabled explicitly.
          </p>
        )}
        {isKilled && (
          <GlowText color="red" size="xs" pulse>
            TRADING HALTED
          </GlowText>
        )}
      </div>
      {dialogOpen && renderKillDialog()}
    </>
  );
}
