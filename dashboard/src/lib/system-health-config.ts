export type HealthServiceStatus = 'checking' | 'online' | 'offline' | 'degraded' | 'timeout';

export interface HealthServiceDef {
  /** Widget key, e.g. ``nexus-api``. */
  name: string;
  /** Native service listen port (IPv4 loopback only — never ``localhost``). */
  port: number;
  /** Health path probed server-side. */
  path: string;
}

/**
 * Single source of truth for System Health probing: service -> native port.
 * Native services bind ``127.0.0.1`` (IPv4) only, so every probe must target
 * ``127.0.0.1`` — ``localhost`` can resolve to ``::1`` and stall until abort.
 */
export const HEALTH_SERVICES: HealthServiceDef[] = [
  { name: 'nexus-api', port: 9000, path: '/health' },
  { name: 'nexus-data', port: 9001, path: '/health' },
  { name: 'nexus-agents', port: 9004, path: '/health' },
  { name: 'nexus-risk', port: 9006, path: '/health' },
  { name: 'nexus-executor', port: 9007, path: '/health' },
  { name: 'nexus-ml', port: 9003, path: '/health' },
];

export interface PipelineSegmentDef {
  name: string;
  color: string;
}

/** Pipeline bar segments, in render order. */
export const PIPELINE_SEGMENTS: PipelineSegmentDef[] = [
  { name: 'Data', color: '#00e5ff' },
  { name: 'ML', color: '#bf5af2' },
  { name: 'Agents', color: '#ffd600' },
  { name: 'Risk', color: '#ff9500' },
  { name: 'Exec', color: '#39ff14' },
];

export const PIPELINE_MAP: Record<string, string> = {
  'nexus-data': 'Data',
  'nexus-ml': 'ML',
  'nexus-agents': 'Agents',
  'nexus-risk': 'Risk',
  'nexus-executor': 'Exec',
};

/** Per-service deadline inside ``app/api/health/route.ts`` (parallel probes). */
export const HEALTH_SERVER_TIMEOUT_MS = 3000;

/** Client deadline for one ``/api/health`` round trip (retried once). */
export const HEALTH_CLIENT_TIMEOUT_MS = 5000;

export interface ServiceProbeResult {
  name: string;
  status: HealthServiceStatus;
  latencyMs: number;
  httpStatus: number;
  cpu: number | null;
  ram: number | null;
}

export interface SystemHealthPayload {
  success: boolean;
  checkedAt: string;
  services: ServiceProbeResult[];
}
