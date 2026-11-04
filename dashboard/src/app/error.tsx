'use client';

import { useEffect } from 'react';

/**
 * Route-level error boundary (Next.js App Router).
 * Shows the real error message — never a fabricated healthy state — and a
 * retry that re-renders the failing route segment.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[route-error]', error);
  }, [error]);

  return (
    <div
      dir="rtl"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-6"
    >
      <div className="font-mono text-sm text-neon-red">
        حدث خطأ غير متوقع في هذه الشاشة
      </div>
      <div className="max-w-md break-words text-center text-xs text-text-muted">
        {error?.message || 'خطأ غير معروف'}
        {error?.digest ? ` (مرجع: ${error.digest})` : ''}
      </div>
      <button
        onClick={reset}
        className="rounded border border-border-primary px-3 py-1.5 text-xs text-text-secondary transition-colors hover:bg-bg-tertiary"
      >
        إعادة المحاولة
      </button>
    </div>
  );
}
