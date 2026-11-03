import { NextResponse } from 'next/server';
import {
  HEALTH_SERVICES,
  HEALTH_SERVER_TIMEOUT_MS,
  type HealthServiceStatus,
  type ServiceProbeResult,
  type SystemHealthPayload,
} from '@/lib/system-health-config';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

interface WirePayload {
  status?: unknown;
  ready?: unknown;
  cpu_pct?: unknown;
  ram_pct?: unknown;
}

/**
 * Per-service probe deadline. ``nexus-api`` additionally aggregates Redis and
 * the nexus-data hop, so it gets a wider budget than the leaf services; the
 * shared default stays at ``HEALTH_SERVER_TIMEOUT_MS`` (3000ms).
 */
const SERVICE_TIMEOUT_MS: Record<string, number> = {
  'nexus-api': 5000,
};

/**
 * A probe that answered inside its deadline but slower than this is
 * ``degraded``, never ``timeout``: ``timeout`` is reserved for the abort path.
 */
const SLOW_DEGRADED_MS = 1500;

async function probeService(
  name: string,
  port: number,
  path: string,
  budgetMs: number,
): Promise<ServiceProbeResult> {
  const started = Date.now();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), budgetMs);
  try {
    // Always IPv4 loopback: uvicorn binds 127.0.0.1 only and ``localhost``
    // may resolve to ::1, which stalls instead of refusing.
    const res = await fetch(`http://127.0.0.1:${port}${path}`, {
      signal: controller.signal,
      cache: 'no-store',
    });
    const latencyMs = Date.now() - started;
    let status: HealthServiceStatus = res.ok ? 'online' : 'offline';
    let cpu: number | null = null;
    let ram: number | null = null;
    if (res.ok) {
      try {
        const body = (await res.json()) as WirePayload;
        if (typeof body.cpu_pct === 'number') cpu = body.cpu_pct;
        if (typeof body.ram_pct === 'number') ram = body.ram_pct;
        const wire = String(body.status ?? '').toLowerCase();
        if (wire === 'degraded' || wire === 'warning') status = 'degraded';
        else if (wire === 'down' || wire === 'unhealthy' || wire === 'error') status = 'offline';
        else if (body.ready === false) status = 'degraded';
        else if (status === 'online' && latencyMs >= SLOW_DEGRADED_MS) status = 'degraded';
      } catch {
        /* keep online: /health answered 200 with a non-JSON body */
      }
    }
    return { name, status, latencyMs, httpStatus: res.status, cpu, ram };
  } catch {
    const latencyMs = Date.now() - started;
    const timedOut = controller.signal.aborted;
    return {
      name,
      status: timedOut ? 'timeout' : 'offline',
      latencyMs,
      httpStatus: 0,
      cpu: null,
      ram: null,
    };
  } finally {
    clearTimeout(timer);
  }
}

export async function GET(): Promise<NextResponse<SystemHealthPayload>> {
  const settled = await Promise.allSettled(
    HEALTH_SERVICES.map((svc) =>
      probeService(svc.name, svc.port, svc.path, SERVICE_TIMEOUT_MS[svc.name] ?? HEALTH_SERVER_TIMEOUT_MS),
    ),
  );
  const services = settled.map((result, index) =>
    result.status === 'fulfilled'
      ? result.value
      : {
          name: HEALTH_SERVICES[index].name,
          status: 'offline' as HealthServiceStatus,
          latencyMs: 0,
          httpStatus: 0,
          cpu: null,
          ram: null,
        },
  );
  return NextResponse.json(
    { success: true, checkedAt: new Date().toISOString(), services },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
