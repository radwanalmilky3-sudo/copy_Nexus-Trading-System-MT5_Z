/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ['lucide-react', 'recharts'],
  },
  // images: next/image optimizer is unused (zero imports, zero remote assets).
  // The former images.remotePatterns hostname:'**' allowed ANY https host and
  // kept the self-hosted Image-Optimizer DoS advisory (GHSA-9g9p-9gw9-jx7f)
  // practically reachable — removed as security hardening (next 14.2.5 -> 14.2.35).
  async headers() {
    // T-012 (2026-11-06): browser-facing hardening headers on every route.
    // CSP is deliberately limited to `frame-ancestors 'none'` — it blocks all
    // framing without touching script/style sources, so Next.js inline
    // bootstrap and the trading UI are unaffected. HSTS stays out on purpose:
    // it is a TLS-time header (browsers must ignore it over http://) and is
    // wired at the reverse proxy when the fleet is first exposed externally
    // (qa/HANDOFF.md §6). The proxied /api/* responses carry the same set from
    // the FastAPI side (shared/security_headers.py), so no duplication needed.
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Content-Security-Policy', value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
  async rewrites() {
    // Same-origin proxy for the whole gateway API: the browser talks to this
    // dev server (:3100) and Next forwards server-side to nexus-api. This
    // sidesteps CORS entirely and keeps working even if a browser tab holds
    // a bundle built with a stale NEXT_PUBLIC_API_URL. The dashboard has no
    // Next API routes of its own, so /api/* is safe to delegate wholesale.
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:9000'}/api/:path*`,
      },
      {
        source: '/health',
        destination: 'http://127.0.0.1:9000/health',
      },
      {
        source: '/health/:path*',
        destination: 'http://127.0.0.1:9000/health/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
