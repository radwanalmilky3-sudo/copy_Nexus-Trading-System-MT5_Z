/**
 * Native WebSocket URLs for the nexus-api gateway (FastAPI), e.g. `/ws/ticks`.
 * Use NEXT_PUBLIC_WS_GATEWAY_URL as the origin only (no `/ws/...` suffix).
 */
export function gatewayWsUrl(path: string): string {
  // Sandbox deployment: derive the origin from the browser location so the
  // dashboard works behind the preview gateway (same host, wss over https).
  // The external gateway routes the request to nexus-api (:9000) via the
  // XTransformPort query parameter and passes the WebSocket upgrade through.
  const fallback =
    typeof window !== 'undefined'
      ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
      : 'ws://127.0.0.1:9000';
  const root = (
    process.env.NEXT_PUBLIC_WS_GATEWAY_URL || fallback
  ).replace(/\/$/, '');
  const p = path.startsWith('/') ? path : `/${path}`;
  const withWs = p.startsWith('/ws') ? p : `/ws${p}`;
  const sep = withWs.includes('?') ? '&' : '?';
  return `${root}${withWs}${sep}XTransformPort=9000`;
}
