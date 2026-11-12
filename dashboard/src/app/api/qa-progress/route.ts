import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

/**
 * QA progress store reader — MASTER PROMPT V4.1 §16.4.
 *
 * Serves the ISOLATED QA tracking store (qa/progress/state.json) that lives
 * OUTSIDE the trading DuckDB. Read-only: this route never writes; updates
 * come from the QA process via qa/progress_update.py.
 *
 * Store resolution: NEXUS_QA_STORE env override, else <cwd>/qa/progress/
 * state.json, else <cwd>/../qa/progress/state.json (dashboard dev runs with
 * cwd=dashboard/).
 */
const CANDIDATES = [
  process.env.NEXUS_QA_STORE,
  path.join(process.cwd(), 'qa', 'progress', 'state.json'),
  path.join(process.cwd(), '..', 'qa', 'progress', 'state.json'),
].filter((p): p is string => Boolean(p));

export async function GET(request: Request) {
  // Authorization: forward the caller's nexus-token to nexus-api /auth/me;
  // only authenticated users may read the QA store.
  const auth = request.headers.get('authorization') ?? '';
  if (!auth.toLowerCase().startsWith('bearer ')) {
    return NextResponse.json({ error: 'unauthorized', message_ar: 'يلزم تسجيل الدخول لعرض المتابعة.' }, { status: 401 });
  }
  try {
    const meUrl = (process.env.NEXUS_API_URL ?? 'http://127.0.0.1:9000').replace(/\/$/, '') + '/api/v2/auth/me';
    const me = await fetch(meUrl, { headers: { Authorization: auth }, signal: AbortSignal.timeout(5000) });
    if (!me.ok) {
      return NextResponse.json({ error: 'unauthorized', message_ar: 'جلسة غير صالحة.' }, { status: 401 });
    }
  } catch {
    return NextResponse.json({ error: 'auth_unreachable', message_ar: 'تعذر التحقق من الجلسة.' }, { status: 503 });
  }

  for (const candidate of CANDIDATES) {
    try {
      const raw = await readFile(candidate, 'utf-8');
      const state = JSON.parse(raw) as Record<string, unknown>;
      return NextResponse.json(state, {
        headers: { 'Cache-Control': 'no-store' },
      });
    } catch {
      // try next candidate
    }
  }
  return NextResponse.json(
    { error: 'qa_store_unavailable', message_ar: 'مخزن المتابعة غير متاح حاليًا.' },
    { status: 503, headers: { 'Cache-Control': 'no-store' } },
  );
}
