import type { BrokerSymbol } from './types';

export type SymbolSortKey = 'category' | 'name' | 'description';
export const SYMBOL_COLUMNS: { key: SymbolSortKey; label: string }[] = [
  { key: 'category', label: 'التصنيف' },
  { key: 'name', label: 'اسم الأصل' },
  { key: 'description', label: 'شرح مختصر' },
];

export function filterSymbols(
  rows: BrokerSymbol[],
  filters: { category: string; name: string; description: string },
): BrokerSymbol[] {
  const keys: (keyof typeof filters)[] = ['category', 'name', 'description'];
  return rows.filter((row) =>
    keys.every((key) => (row[key] || '').toLocaleLowerCase().includes(filters[key].toLocaleLowerCase())),
  );
}

export function sortSymbols(rows: BrokerSymbol[], key: SymbolSortKey, dir: 'asc' | 'desc'): BrokerSymbol[] {
  const factor = dir === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => {
    const av = (a[key] || '').trim();
    const bv = (b[key] || '').trim();
    if (!av && bv) return 1;
    if (av && !bv) return -1;
    return factor * av.localeCompare(bv, 'en', { numeric: true, sensitivity: 'base' });
  });
}

export function nextSortDir(
  current: { key: SymbolSortKey; dir: 'asc' | 'desc' } | null,
  clicked: SymbolSortKey,
): 'asc' | 'desc' {
  if (!current || current.key !== clicked) return 'asc';
  return current.dir === 'asc' ? 'desc' : 'asc';
}
