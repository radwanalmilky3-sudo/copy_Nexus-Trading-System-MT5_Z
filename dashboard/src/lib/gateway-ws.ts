/**
 * Native WebSocket URLs for the nexus-api gateway (FastAPI), e.g. `/ws/ticks`.
 * Use NEXT_PUBLIC_WS_GATEWAY_URL as the origin only (no `/ws/...` suffix).
 */
export function gatewayWsUrl(path: string): string {
  // Sandbox deployment: derive the origin from the browser location so the
  // dashboard works behind the preview gateway (same host, wss over https).
  // The external gateway routes the request to nexus-api (:9000) via the
  // XTransformPort query parameter and passes the WebSocket upgrade through.
  //
  // Local dev: the Next.js dev server (:3100) does NOT proxy WebSocket
  // upgrades (rewrites are HTTP-only), so dialing window.location.host
  // there always fails with "تعذر الاتصال". In development, dial the
  // gateway origin directly — the FastAPI gateway accepts the upgrade
  // itself (verified: ws://127.0.0.1:9000 → 101 Switching Protocols).
  let fallback: string;
  if (process.env.NODE_ENV === 'development') {
    fallback = 'ws://127.0.0.1:9000';
  } else if (typeof window !== 'undefined') {
    fallback = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
  } else {
    fallback = 'ws://127.0.0.1:9000';
  }
  const root = (
    process.env.NEXT_PUBLIC_WS_GATEWAY_URL || fallback
  ).replace(/\/$/, '');
  const p = path.startsWith('/') ? path : `/${path}`;
  const withWs = p.startsWith('/ws') ? p : `/ws${p}`;
  const sep = withWs.includes('?') ? '&' : '?';
  return `${root}${withWs}${sep}XTransformPort=9000`;
}
