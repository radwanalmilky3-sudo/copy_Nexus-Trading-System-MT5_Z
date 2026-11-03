'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient } from '@/lib/api-client';
import { useWebSocket } from './useWebSocket';
import { gatewayWsUrl } from '@/lib/gateway-ws';

export interface CircuitBreaker {
  name: string;
  status: 'ok' | 'violated';
  detail?: string;
}

export interface RiskState {
  dailyLossUsed: number;
  dailyLossMax: number;
  weeklyDDUsed: number;
  weeklyDDMax: number;
  positionCount: number;
  positionMax: number;
  sessionMax: number;
  currentSession: string;
  correlationExposure: number;
  correlationMax: number;
  tiltLevel: 'NORMAL' | 'WARNING' | 'TILT' | 'UNKNOWN';
  consecutiveLosses: number;
  circuitBreakers: CircuitBreaker[];
  isLive: boolean;
}

function detectCurrentSession(): { name: string; sessionMax: number } {
  const now = new Date();
  const h = now.getUTCHours();
  const m = now.getUTCMinutes();
  const t = h * 60 + m;

  if (t >= 12 * 60 && t < 16 * 60) return { name: 'London/NY Overlap', sessionMax: 10 };
  if (t >= 7 * 60 && t < 16 * 60)  return { name: 'London',             sessionMax: 8 };
  if (t >= 12 * 60 && t < 21 * 60) return { name: 'New York',           sessionMax: 8 };
  if (t >= 0 * 60 && t < 8 * 60)   return { name: 'Tokyo',              sessionMax: 4 };
  if (t >= 22 * 60 || t < 6 * 60)  return { name: 'Sydney',             sessionMax: 3 };
  return { name: 'Off Hours', sessionMax: 3 };
}

function mapBackendRisk(d: Record<string, unknown>): Partial<RiskState> {
  const state = d.state as Record<string, unknown> | undefined;
  const src = state ?? d;

  const result: Partial<RiskState> = {};
  if (src.available !== true) return result;

  const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined);
  const requiredMetrics = ['daily_loss_pct', 'max_daily_loss_pct', 'weekly_dd_pct', 'max_weekly_drawdown_pct', 'open_positions_count', 'max_positions'];
  if (requiredMetrics.some((key) => n(src[key]) === undefined) || !Array.isArray(src.circuit_breakers)) return {};

  if (n(src.daily_loss_pct) !== undefined) result.dailyLossUsed = n(src.daily_loss_pct)!;
  if (n(src.max_daily_loss_pct) !== undefined) result.dailyLossMax = n(src.max_daily_loss_pct)!;
  if (n(src.weekly_dd_pct) !== undefined) result.weeklyDDUsed = n(src.weekly_dd_pct)!;
  if (n(src.max_weekly_drawdown_pct) !== undefined) result.weeklyDDMax = n(src.max_weekly_drawdown_pct)!;
  if (n(src.open_positions_count) !== undefined) result.positionCount = n(src.open_positions_count)!;
  if (n(src.max_positions) !== undefined) result.positionMax = n(src.max_positions)!;
  if (n(src.correlation_exposure) !== undefined) result.correlationExposure = n(src.correlation_exposure)!;
  if (n(src.max_correlation) !== undefined) result.correlationMax = n(src.max_correlation)!;
  if (n(src.consecutive_losses) !== undefined) result.consecutiveLosses = n(src.consecutive_losses)!;

  if (typeof src.tilt_status === 'string') {
    const t = src.tilt_status.toUpperCase();
    if (t === 'TILT') result.tiltLevel = 'TILT';
    else if (t === 'WARNING' || t === 'CAUTION') result.tiltLevel = 'WARNING';
    else if (t === 'NORMAL' || t === 'OK') result.tiltLevel = 'NORMAL';
    else result.tiltLevel = 'UNKNOWN';
  }

  if (typeof src.current_session === 'string') result.currentSession = src.current_session;
  if (typeof src.session === 'string') result.currentSession = src.session;

  const breakers = (src.circuit_breakers ?? src.breakers) as
    | Array<{ name: string; triggered: boolean; reason?: string }>
    | undefined;
  if (Array.isArray(breakers)) {
    const mapped = breakers.map((b) => ({
      name: b.name.replace(/_/g, ' '),
      status: b.triggered ? 'violated' as const : 'ok' as const,
      detail: b.triggered ? b.reason : undefined,
    }));
    result.circuitBreakers = mapped;
  }

  return result;
}

const DEFAULT_RISK: RiskState = {
  dailyLossUsed: 0,
  dailyLossMax: 20.0,
  weeklyDDUsed: 0,
  weeklyDDMax: 25.0,
  positionCount: 0,
  positionMax: 5,
  sessionMax: 8,
  currentSession: '—',
  correlationExposure: 0,
  correlationMax: 0.95,
  tiltLevel: 'UNKNOWN',
  consecutiveLosses: 0,
  circuitBreakers: [],
  isLive: false,
};

export function useRisk() {
  const [risk, setRisk] = useState<RiskState>(() => {
    const session = detectCurrentSession();
    return {
      ...DEFAULT_RISK,
      sessionMax: session.sessionMax,
      currentSession: session.name,
    };
  });

  const poll = useCallback(async () => {
    try {
      const res = await apiClient.getRiskState();
      const raw = res.data as unknown as Record<string, unknown>;
      if (raw && Object.keys(raw).length > 0) {
        const mapped = mapBackendRisk(raw);
        if (mapped.dailyLossUsed === undefined) {
          setRisk((prev) => ({ ...prev, isLive: false }));
          return;
        }
        const session = detectCurrentSession();
        setRisk((prev) => ({
          ...prev,
          ...mapped,
          sessionMax: mapped.currentSession ? session.sessionMax : prev.sessionMax,
          currentSession: mapped.currentSession ?? session.name,
          isLive: true,
        }));
      } else setRisk((prev) => ({ ...prev, isLive: false }));
    } catch {
      // Keep the last snapshot for context, but never present it as live.
      setRisk((prev) => ({ ...prev, isLive: false }));
    }
  }, []);

  // nexus-api's risk_broadcaster pushes on every risk evaluation (proposal
  // approved/rejected, breaker triggered) — refetch immediately on signal
  // instead of waiting for the next poll tick. The interval below is only
  // a safety net for a dropped socket.
  const pollRef = useRef(poll);
  pollRef.current = poll;
  const wsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { isConnected: wsConnected } = useWebSocket({
    url: gatewayWsUrl('/risk'),
    onMessage: () => {
      if (wsDebounceRef.current) clearTimeout(wsDebounceRef.current);
      wsDebounceRef.current = setTimeout(() => pollRef.current(), 250);
    },
  });

  useEffect(() => {
    poll();
    const intervalMs = wsConnected ? 45_000 : 10_000;
    const id = window.setInterval(poll, intervalMs);
    return () => window.clearInterval(id);
  }, [poll, wsConnected]);

  useEffect(() => {
    const updateSession = () => {
      const session = detectCurrentSession();
      setRisk((prev) => ({
        ...prev,
        sessionMax: prev.isLive ? prev.sessionMax : session.sessionMax,
        currentSession: prev.isLive ? prev.currentSession : session.name,
      }));
    };
    const id = window.setInterval(updateSession, 60_000);
    return () => window.clearInterval(id);
  }, []);

  const effectiveMax = Math.min(risk.positionMax, risk.sessionMax);
  const anyViolation = risk.circuitBreakers.some((cb) => cb.status === 'violated');
  const anyGaugeCritical =
    risk.dailyLossUsed / risk.dailyLossMax > 0.8 ||
    risk.weeklyDDUsed / risk.weeklyDDMax > 0.8 ||
    (risk.positionCount / effectiveMax) > 0.8 ||
    risk.correlationExposure / risk.correlationMax > 0.8;

  return {
    risk: { ...risk, positionMax: effectiveMax },
    fullRisk: risk,
    anyViolation,
    anyGaugeCritical,
    isConnected: risk.isLive,
  };
}
