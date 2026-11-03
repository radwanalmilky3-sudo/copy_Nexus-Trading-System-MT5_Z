'use client';

import { useEffect, useRef, useState } from 'react';
import { apiClient, getAuthHeaders } from '@/lib/api-client';
import { cn } from '@/lib/utils';
import { AlertTriangle, CheckCircle2, XCircle, RefreshCw, Loader2 } from 'lucide-react';
import { hasMarketFeedBars } from '@/lib/market-feed-status';
import { classifyCandlesProbe, classifyDiagnosticBanner, classifyUpstreamProbe } from '@/lib/system-health-status';

interface ServiceStatus {
  name: string;
  ok: boolean;
  detail?: string;
}

// The gateway is a single uvicorn worker; at page load it absorbs a burst of
// ~35 authenticated endpoints (each with a CORS preflight) and several proxy
// calls to dead upstreams that each take ~2s server-side. 8s was too tight
// under that congestion (probes spuriously reported "unreachable"); 12s stays
// under the app-wide 15s request budget while letting a real 502 surface.
const PROBE_TIMEOUT_MS = 12_000;

async function fetchProbe(url: string): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    return await fetch(url, { headers: getAuthHeaders(), signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

export default function SystemDiagnostic() {
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [checking, setChecking] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [expanded, setExpanded] = useState(false);
  const checkSeqRef = useRef(0);

  const check = async () => {
    const seq = ++checkSeqRef.current;
    setChecking(true);

    // Run all five probes in parallel so the banner resolves in ~slowest-probe
    // time instead of the sum of every sequential round-trip.
    const [gateway, candles, mt5, ml, agents] = await Promise.all([
      // nexus-api gateway (+ nested Redis/DuckDB)
      (async (): Promise<ServiceStatus[]> => {
        try {
          const health = await apiClient.getHealth();
          const h = health.data;
          const out: ServiceStatus[] = [
            { name: 'nexus-api (gateway)', ok: h.status === 'healthy', detail: h.status },
          ];
          const redis = h.components.find((c) => c.name === 'redis');
          out.push({
            name: 'Redis',
            ok: redis?.status === 'healthy',
            detail: redis?.status ?? 'not reported',
          });
          const duckdb = h.components.find((c) => c.name === 'duckdb');
          out.push({
            name: 'DuckDB',
            ok: duckdb?.status === 'healthy',
            detail: duckdb?.status ?? 'not reported',
          });
          return out;
        } catch {
          return [
            { name: 'nexus-api (gateway)', ok: false, detail: 'unreachable' },
            { name: 'Redis', ok: false, detail: 'gateway offline' },
            { name: 'DuckDB', ok: false, detail: 'gateway offline' },
          ];
        }
      })(),

      // nexus-data via candles (auth header required; 401 is auth, not MT5 down)
      (async (): Promise<ServiceStatus> => {
        try {
          const res = await fetchProbe(
            `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000'}/api/v2/market/candles?symbol=XAUUSD&timeframe=M15&count=1`,
          );
          const hasBars = res.ok ? hasMarketFeedBars(await res.json().catch(() => null)) : false;
          const probe = classifyCandlesProbe(res.status, hasBars);
          return { name: 'nexus-data (MT5 feed)', ok: probe.kind === 'ok', detail: probe.detail };
        } catch {
          return { name: 'nexus-data (MT5 feed)', ok: false, detail: 'no response in 12s' };
        }
      })(),

      // MT5 connection via positions
      (async (): Promise<ServiceStatus> => {
        try {
          const pos = await apiClient.getPositionsSnapshot();
          const live = pos.data.live_connected;
          return {
            name: 'MetaTrader 5',
            ok: Boolean(live),
            detail: live ? 'connected' : 'disconnected — check MT5_LOGIN in .env',
          };
        } catch {
          return { name: 'MetaTrader 5', ok: false, detail: 'positions endpoint failed' };
        }
      })(),

      // ML models (traders pipeline)
      (async (): Promise<ServiceStatus> => {
        try {
          const res = await fetchProbe(
            `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000'}/api/ml/traders/status`,
          );
          const probe = classifyUpstreamProbe(res.status);
          if (probe.kind === 'ok') {
            const data = await res.json();
            const mlFitted = data?.ml?.is_fitted;
            return {
              name: 'ML Models',
              ok: Boolean(mlFitted),
              detail: mlFitted ? `trained (${data?.ml?.model_name ?? 'ensemble'})` : 'not trained yet',
            };
          }
          return { name: 'ML Models', ok: false, detail: probe.detail };
        } catch {
          return { name: 'ML Models', ok: false, detail: 'no response in 12s' };
        }
      })(),

      // Agents service
      (async (): Promise<ServiceStatus> => {
        try {
          const res = await fetchProbe(
            `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000'}/api/agents/status`,
          );
          const probe = classifyUpstreamProbe(res.status);
          if (probe.kind === 'ok') {
            const payload = await res.json();
            const rows = Array.isArray(payload) ? payload : (payload?.agents ?? []);
            const meta = Array.isArray(payload) ? null : payload?.meta;
            const ready = rows.filter((a: { status: string }) => a.status !== 'offline').length;
            const pipeline = meta?.pipeline_state ?? (ready > 0 ? 'ready' : 'offline');
            return {
              name: 'Agent Pipeline',
              ok: meta?.service_online ?? ready > 0,
              detail: `${ready}/${rows.length} ready · ${pipeline}`,
            };
          }
          return { name: 'Agent Pipeline', ok: false, detail: probe.detail };
        } catch {
          return { name: 'Agent Pipeline', ok: false, detail: 'no response in 12s' };
        }
      })(),
    ]);

    const results: ServiceStatus[] = [...gateway, candles, mt5, ml, agents];

    // Ignore a stale response that finishes after a newer check has started.
    if (seq !== checkSeqRef.current) return;

    setServices(results);
    setLastChecked(new Date());
    setChecking(false);
  };

  useEffect(() => {
    check();
    const id = window.setInterval(check, 30_000);
    return () => window.clearInterval(id);
  }, []);

  const checked = lastChecked !== null;
  const bannerMode = classifyDiagnosticBanner(checked, services);
  const anyDown = bannerMode === 'fault';
  const downCount = services.filter((s) => !s.ok).length;

  // Hide only after a completed check confirmed every service is healthy.
  if (bannerMode === 'healthy' && !expanded) return null;

  // Honest loading state: never claim "all systems operational" before the
  // first check has completed (UI-01 regression guard).
  if (bannerMode === 'checking') {
    return (
      <div className="rounded-lg border px-4 py-2.5 mb-3 bg-neon-gold/5 border-neon-gold/30">
        <div className="flex items-center gap-3">
          <Loader2 className="h-4 w-4 text-neon-gold shrink-0 animate-spin" />
          <span className="text-xs font-semibold flex-1 text-neon-gold">Checking services…</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'rounded-lg border px-4 py-2.5 mb-3 transition-all',
        anyDown
          ? 'bg-neon-red/5 border-neon-red/30'
          : 'bg-neon-green/5 border-neon-green/30',
      )}
    >
      <div className="flex items-center gap-3">
        {anyDown ? (
          <AlertTriangle className="h-4 w-4 text-neon-red shrink-0" />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-neon-green shrink-0" />
        )}

        <span className={cn('text-xs font-semibold flex-1', anyDown ? 'text-neon-red' : 'text-neon-green')}>
          {anyDown
            ? `${downCount} service${downCount > 1 ? 's' : ''} offline — trading paused`
            : 'All systems operational'}
        </span>

        {lastChecked && (
          <span className="text-[10px] font-mono text-text-muted hidden sm:inline">
            {lastChecked.toLocaleTimeString()}
          </span>
        )}

        <button
          onClick={check}
          disabled={checking}
          className="p-1 rounded text-text-muted hover:text-text-primary transition-colors"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', checking && 'animate-spin')} />
        </button>

        <button
          onClick={() => setExpanded(!expanded)}
          className="text-[10px] font-mono text-text-muted hover:text-text-secondary transition-colors"
        >
          {expanded ? 'hide' : 'details'}
        </button>
      </div>

      {expanded && services.length > 0 && (
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
          {services.map((svc) => (
            <div
              key={svc.name}
              className={cn(
                'flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs',
                svc.ok ? 'bg-neon-green/5' : 'bg-neon-red/8',
              )}
            >
              {svc.ok ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-neon-green shrink-0" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-neon-red shrink-0" />
              )}
              <span className={cn('font-medium', svc.ok ? 'text-text-secondary' : 'text-neon-red')}>
                {svc.name}
              </span>
              {svc.detail && (
                <span className={cn('ml-auto text-[10px] font-mono shrink-0', svc.ok ? 'text-text-muted' : 'text-neon-red/70')}>
                  {svc.detail}
                </span>
              )}
            </div>
          ))}

          {services.some((s) => s.name === 'nexus-data (MT5 feed)' && !s.ok) && (
            <div className="col-span-full mt-1 text-[10px] font-mono text-neon-gold/80 leading-relaxed">
              nexus-data crash fix applied (MT5 COM single-thread). Restart <code>python run.py</code> to reload.
            </div>
          )}
          {services.some((s) => s.name === 'MetaTrader 5' && !s.ok) && (
            <div className="col-span-full mt-1 text-[10px] font-mono text-neon-gold/80 leading-relaxed">
              Open MetaTrader 5 terminal and confirm MT5_LOGIN / MT5_SERVER in .env match your broker.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
