'use client';

import React, { useCallback, useMemo, useRef } from 'react';
import ReactGridLayout, { WidthProvider, type Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { GripVertical } from 'lucide-react';

/* WidthProvider measures the container via ResizeObserver; a bare
 * <ReactGridLayout> never gets a width, every horizontal position
 * computes NaN, React drops those styles and all windows stack at
 * the origin (the "tables on top of each other" bug). */
const MeasuredGrid = WidthProvider(ReactGridLayout);

export interface GridBoardItem {
  i: string;
  node: React.ReactNode;
}

interface GridBoardProps {
  layout: Layout[];
  items: GridBoardItem[];
  onLayoutChange: (layout: Layout[]) => void;
  rowHeight?: number;
}

/**
 * Draggable/resizable board for dashboard windows (M1.4).
 * - Drag via the grip handle that appears on hover (no visual noise otherwise).
 * - Every change is reported once the user actually moves/resizes, so the
 *   store only persists real user edits.
 * - Resize handle is subtle and only visible on hover.
 */
export default function GridBoard({
  layout,
  items,
  onLayoutChange,
  rowHeight = 36,
}: GridBoardProps) {
  /* Skip the layout callback RGL fires right after mount — persisting the
   * untouched default would be a no-op write with reordered rows. */
  const mountedRef = useRef(false);

  const layoutMap = useMemo(
    () => new Map(layout.map((l) => [l.i, l])),
    [layout]
  );

  const children = useMemo(
    () =>
      items.map((item) => (
        <div
          key={item.i}
          dir="rtl"
          className="group relative h-full w-full min-h-0 overflow-hidden"
        >
          <span
            title="اسحب لتحريك النافذة — واسحب الحافة السفلية لتغيير الحجم"
            className="grid-drag-handle absolute left-1.5 top-1.5 z-20 cursor-grab rounded p-0.5 text-text-muted opacity-0 transition-opacity hover:bg-bg-tertiary hover:text-text-secondary active:cursor-grabbing group-hover:opacity-100"
          >
            <GripVertical className="h-3.5 w-3.5" />
          </span>
          {item.node}
        </div>
      )),
    [items]
  );

  const handleLayoutChange = useCallback(
    (next: Layout[]) => {
      if (!mountedRef.current) {
        mountedRef.current = true;
        return;
      }
      onLayoutChange(next);
    },
    [onLayoutChange]
  );

  return (
    /* dir="ltr": react-grid-layout anchors items to the left edge; inside the
     * RTL app shell the whole board mirrors and x=0 lands on the right. The
     * board measures/positions LTR (matching the owner's reference layout),
     * while every window content wrapper above stays dir="rtl". */
    <div dir="ltr" className="w-full">
      <MeasuredGrid
        layout={layout}
        cols={12}
        rowHeight={rowHeight}
        margin={[8, 8]}
        containerPadding={[0, 0]}
        draggableHandle=".grid-drag-handle"
        onLayoutChange={handleLayoutChange}
        onResizeStop={(l) => handleLayoutChange(l)}
        compactType="vertical"
        resizeHandles={['se']}
        className="nexus-grid"
      >
        {children}
      </MeasuredGrid>
    </div>
  );
}
