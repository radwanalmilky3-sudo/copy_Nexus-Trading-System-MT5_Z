import { execFile } from 'node:child_process';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { NextResponse } from 'next/server';
import { promisify } from 'node:util';

export const dynamic = 'force-dynamic';

const NO_STORE = { 'Cache-Control': 'no-store' };
const run = promisify(execFile);

/**
 * Live development log — owner 2026-11-07 (replaces the stale manual
 * project_audit/DASHBOARD_STATE.json snapshot): the "متابعة التطوير" screen
 * reads the actual repository via git so it can never go stale again.
 */

function rootCandidates(): string[] {
  const candidates: string[] = [];
  const root = process.env.NEXUS_ROOT?.trim();
  if (root) candidates.push(path.resolve(root));
  const cwd = process.cwd();
  candidates.push(path.resolve(cwd), path.resolve(cwd, '..'), path.resolve(cwd, '..', '..'));
  return [...new Set(candidates)];
}

async function resolveRepo(): Promise<string | null> {
  for (const candidate of rootCandidates()) {
    try {
      const stat = await fs.stat(path.join(candidate, '.git'));
      if (stat.isDirectory()) return candidate;
    } catch {
      // not a repo — try the next candidate
    }
  }
  return null;
}

const UNIT = '\x1f';
const RECORD = '\x1e';

async function git(root: string, args: string[]): Promise<string> {
  const { stdout } = await run('git', ['-C', root, ...args], { maxBuffer: 4 * 1024 * 1024 });
  return stdout;
}

function unavailable(reason: unknown): Response {
  console.error('[git-dev-state] unavailable:', reason);
  return NextResponse.json({ error: 'git_unavailable' }, { status: 503, headers: NO_STORE });
}

export async function GET(): Promise<Response> {
  let root: string | null;
  try {
    root = await resolveRepo();
  } catch (err) {
    return unavailable(err);
  }
  if (!root) return unavailable('no .git root found');

  try {
    const branch = (await git(root, ['rev-parse', '--abbrev-ref', 'HEAD'])).trim();
    const headLine = (await git(root, ['log', '-1', `--pretty=format:%H${UNIT}%h${UNIT}%s${UNIT}%cI${UNIT}%an`])).trim();
    const [headHash, headShort, headSubject, headDate, headAuthor] = headLine.split(UNIT);

    const logRaw = (await git(root, ['log', '-30', `--pretty=format:%h${UNIT}%s${UNIT}%cI${UNIT}%an${RECORD}`])).trim();
    const commits = logRaw
      .split(RECORD)
      .filter(Boolean)
      .map((line) => {
        const [hash, subject, date, author] = line.split(UNIT);
        return { hash, subject, date, author };
      });

    const statusRaw = await git(root, ['status', '--porcelain']);
    const dirtyFiles = statusRaw
      .split('\n')
      .filter(Boolean)
      .map((line) => ({ status: line.slice(0, 2).trim(), path: line.slice(3).trim() }));

    const lastGateLine = commits.find((c) => /Gates?:/.test(c.subject))?.subject ?? null;
    const gates = lastGateLine ? (lastGateLine.match(/Gates?:([^|]*)/)?.[1]?.trim() ?? null) : null;

    return NextResponse.json(
      {
        generated_at: new Date().toISOString(),
        repo: root,
        branch,
        head: { hash: headHash, short: headShort, subject: headSubject, date: headDate, author: headAuthor },
        commits,
        dirty: { count: dirtyFiles.length, files: dirtyFiles.slice(0, 50) },
        last_gates: gates,
        source: 'git_live',
      },
      { headers: NO_STORE },
    );
  } catch (err) {
    return unavailable(err);
  }
}
