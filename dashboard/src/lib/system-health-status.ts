export type ProbeStatus = 'online' | 'offline' | 'degraded';

export function classifyProbeStatus(ok: boolean, httpStatus: number): ProbeStatus {
  if (ok) return 'online';
  return httpStatus > 0 ? 'degraded' : 'offline';
}

export type DiagnosticBanner = 'checking' | 'healthy' | 'fault';

export function classifyDiagnosticBanner(
  checked: boolean,
  services: readonly { ok: boolean }[],
): DiagnosticBanner {
  if (!checked) return 'checking';
  if (services.length === 0) return 'checking';
  return services.every((s) => s.ok) ? 'healthy' : 'fault';
}

export type CandlesProbeKind = 'ok' | 'auth' | 'upstream' | 'no-data' | 'unreachable';

export function classifyCandlesProbe(
  httpStatus: number,
  hasBars: boolean,
): { kind: CandlesProbeKind; detail: string } {
  if (httpStatus === 401 || httpStatus === 403) {
    return { kind: 'auth', detail: `HTTP ${httpStatus} — auth required (token missing/expired)` };
  }
  if (httpStatus === 502 || httpStatus === 503) {
    return { kind: 'upstream', detail: `HTTP ${httpStatus} — data service unavailable` };
  }
  if (httpStatus >= 400 || httpStatus === 0) {
    return { kind: 'unreachable', detail: httpStatus === 0 ? 'unreachable' : `HTTP ${httpStatus}` };
  }
  return hasBars
    ? { kind: 'ok', detail: 'ok' }
    : { kind: 'no-data', detail: 'connected, no OHLCV data' };
}

export type UpstreamProbeKind = 'ok' | 'auth' | 'upstream' | 'not-found' | 'error';

/**
 * Classify a gateway-proxied probe (ML/Agents/Risk style). A 502/503 from the
 * gateway means the internal upstream service did not answer — in
 * settings-only mode that is the honest "service not running" state, never
 * a fabricated success.
 */
export function classifyUpstreamProbe(
  httpStatus: number,
): { kind: UpstreamProbeKind; detail: string } {
  if (httpStatus >= 200 && httpStatus < 300) {
    return { kind: 'ok', detail: 'ok' };
  }
  if (httpStatus === 401 || httpStatus === 403) {
    return { kind: 'auth', detail: `HTTP ${httpStatus} — auth required` };
  }
  if (httpStatus === 502 || httpStatus === 503 || httpStatus === 504) {
    return { kind: 'upstream', detail: `upstream offline (HTTP ${httpStatus})` };
  }
  if (httpStatus === 404) {
    return { kind: 'not-found', detail: 'route not found (HTTP 404)' };
  }
  return { kind: 'error', detail: `HTTP ${httpStatus}` };
}
