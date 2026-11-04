/**
 * M2 — pure cell-flash diffing for live tables.
 *
 * Given the numeric snapshot of the previous render and the next one, returns
 * key → direction for every value that CHANGED. Components map row/cell ids
 * into the key (e.g. `${ticket}:pnl`); anything absent from the previous
 * snapshot (first load, new row) never flashes.
 */

export type FlashDir = 'up' | 'down';

export function cellFlashes(
  prev: Record<string, number> | null | undefined,
  next: Record<string, number>,
): Record<string, FlashDir> {
  const out: Record<string, FlashDir> = {};
  if (!prev) return out;
  for (const [key, value] of Object.entries(next)) {
    const before = prev[key];
    if (typeof before !== 'number' || !Number.isFinite(before)) continue;
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    if (value > before) out[key] = 'up';
    else if (value < before) out[key] = 'down';
  }
  return out;
}

/** Tailwind-free class hook (keyframes live in globals.css). */
export function flashClass(dir: FlashDir | undefined): string {
  if (dir === 'up') return 'cell-flash-up';
  if (dir === 'down') return 'cell-flash-down';
  return '';
}
