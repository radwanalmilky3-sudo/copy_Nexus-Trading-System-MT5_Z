'use client';

/**
 * M2 — generic virtualized table (@tanstack/react-virtual).
 *
 * Div/grid based on purpose: rows are positioned with translateY only, which
 * is direction-neutral and therefore safe under the dashboard's RTL layout.
 * Renders ~10 rows for thousands of records (plan §5) while keeping the
 * sticky header and the existing visual language (font-mono, border rows).
 */

import { useRef, type ReactNode } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

export interface VirtualColumn<T> {
  key: string;
  header: ReactNode;
  /** Grid track for the column, e.g. '130px' | '1fr'. */
  width: string;
  align?: 'start' | 'end' | 'center';
  dir?: 'ltr' | 'rtl';
  render: (row: T, index: number) => ReactNode;
}

interface VirtualTableProps<T> {
  rows: T[];
  rowKey: (row: T, index: number) => string;
  columns: VirtualColumn<T>[];
  /** Fixed row height in px — required by the virtualizer. */
  rowHeight?: number;
  /** Scroll-viewport height (CSS), e.g. '480px'. */
  height?: string;
  /** Horizontal floor so narrow panes keep readable columns. */
  minWidth?: number;
  emptyMessage?: ReactNode;
}

export default function VirtualTable<T>({
  rows,
  rowKey,
  columns,
  rowHeight = 30,
  height = '420px',
  minWidth = 760,
  emptyMessage,
}: VirtualTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 8,
  });

  const template = columns.map((c) => c.width).join(' ');
  const alignClass = (align?: 'start' | 'end' | 'center') =>
    align === 'end' ? 'text-end' : align === 'center' ? 'text-center' : 'text-start';

  return (
    <div className="w-full overflow-x-auto scrollbar-hide">
      <div style={{ minWidth }}>
        {/* Header — sticky inside the shared scroll viewport. */}
        <div
          className="sticky top-0 z-10 grid border-b border-border-primary/15 bg-bg-primary text-[8px] font-mono font-semibold uppercase tracking-wider text-text-muted"
          style={{ gridTemplateColumns: template }}
          role="row"
        >
          {columns.map((col) => (
            <div key={col.key} role="columnheader" className={`px-2 py-1.5 ${alignClass(col.align)}`}>
              {col.header}
            </div>
          ))}
        </div>

        {rows.length === 0 ? (
          <div className="px-4 py-10 text-center text-[11px] text-text-muted">{emptyMessage ?? 'لا توجد بيانات'}</div>
        ) : (
          <div ref={scrollRef} className="overflow-y-auto scrollbar-hide" style={{ height }}>
            <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
              {virtualizer.getVirtualItems().map((vRow) => {
                const row = rows[vRow.index];
                return (
                  <div
                    key={rowKey(row, vRow.index)}
                    role="row"
                    className="absolute inset-x-0 grid border-b border-border-primary/5 text-[10px] font-mono transition-colors hover:bg-bg-secondary/30"
                    style={{
                      gridTemplateColumns: template,
                      height: vRow.size,
                      transform: `translateY(${vRow.start}px)`,
                    }}
                  >
                    {columns.map((col) => (
                      <div
                        key={col.key}
                        role="gridcell"
                        dir={col.dir}
                        className={`px-2 py-1.5 truncate ${alignClass(col.align)}`}
                      >
                        {col.render(row, vRow.index)}
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
