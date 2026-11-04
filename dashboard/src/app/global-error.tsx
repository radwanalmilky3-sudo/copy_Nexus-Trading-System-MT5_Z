'use client';

import { useEffect } from 'react';

/**
 * Global error boundary — last resort when the root layout itself fails.
 * Must render its own <html>/<body>; keep it dependency-free (inline styles).
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[global-error]', error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          background: '#09090b',
          color: '#f0f0f5',
          fontFamily: 'ui-monospace, monospace',
          margin: 0,
        }}
      >
        <div
          dir="rtl"
          style={{
            minHeight: '60vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            padding: 24,
          }}
        >
          <div style={{ color: '#ef4444', fontSize: 14 }}>
            تعذّر تحميل اللوحة — خطأ عام
          </div>
          <div
            style={{
              fontSize: 12,
              color: '#8b8fa3',
              maxWidth: 480,
              wordBreak: 'break-word',
              textAlign: 'center',
            }}
          >
            {error?.message || 'خطأ غير معروف'}
          </div>
          <button
            onClick={reset}
            style={{
              border: '1px solid #1e2030',
              borderRadius: 6,
              padding: '6px 14px',
              fontSize: 12,
              color: '#8b8fa3',
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            إعادة المحاولة
          </button>
        </div>
      </body>
    </html>
  );
}
