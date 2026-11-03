import { promises as fs } from 'node:fs';
import path from 'node:path';
import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

const STATE_FILE = 'DASHBOARD_STATE.json';
const NO_STORE = { 'Cache-Control': 'no-store' };

function stateCandidates(): string[] {
  const candidates: string[] = [];
  const root = process.env.NEXUS_ROOT?.trim();
  if (root) candidates.push(path.resolve(root, 'project_audit', STATE_FILE));
  const cwd = process.cwd();
  candidates.push(
    path.resolve(cwd, 'project_audit', STATE_FILE),
    path.resolve(cwd, '..', 'project_audit', STATE_FILE),
    path.resolve(cwd, 'dashboard', '..', 'project_audit', STATE_FILE),
  );
  return [...new Set(candidates)];
}

async function resolveStateFile(): Promise<string | null> {
  for (const candidate of stateCandidates()) {
    try {
      const stat = await fs.stat(candidate);
      if (stat.isFile()) return candidate;
    } catch {
      // missing or unreadable candidate — try the next one
    }
  }
  return null;
}

function unavailable(file: string | null, reason: unknown): Response {
  console.error(
    `[progress-state] state_unavailable (cwd=${process.cwd()}, file=${file ?? 'none-found'})`,
    reason,
  );
  return NextResponse.json({ error: 'state_unavailable' }, { status: 503, headers: NO_STORE });
}

export async function GET(request: Request): Promise<Response> {
  const file = await resolveStateFile();
  if (!file) {
    console.error(
      `[progress-state] ${STATE_FILE} not found; cwd=${process.cwd()}; tried=${stateCandidates().join(', ')}`,
    );
    return NextResponse.json({ error: 'state_unavailable' }, { status: 503, headers: NO_STORE });
  }

  let stat;
  try {
    stat = await fs.stat(file);
  } catch (err) {
    return unavailable(file, err);
  }

  const etag = `W/"${stat.size}-${stat.mtime.getTime()}"`;
  const headers: Record<string, string> = {
    ...NO_STORE,
    ETag: etag,
    'X-State-Last-Updated': stat.mtime.toISOString(),
  };

  const ifNoneMatch = request.headers.get('if-none-match');
  if (ifNoneMatch && ifNoneMatch.split(',').some((tag) => tag.trim() === etag || tag.trim() === '*')) {
    return new Response(null, { status: 304, headers });
  }

  let raw: string;
  try {
    raw = await fs.readFile(file, 'utf8');
  } catch (err) {
    return unavailable(file, err);
  }

  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    const position = /position\s+(\d+)/i.exec(msg)?.[1] ?? 'unknown';
    console.error(
      `[progress-state] malformed JSON in ${file} at position ${position} (size=${stat.size}, mtime=${stat.mtime.toISOString()}): ${msg}`,
    );
    return NextResponse.json({ error: 'state_invalid' }, { status: 500, headers: NO_STORE });
  }

  return NextResponse.json(data, { headers });
}
