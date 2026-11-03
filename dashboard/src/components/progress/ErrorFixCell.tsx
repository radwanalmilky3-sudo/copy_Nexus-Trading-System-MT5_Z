'use client';
import { useEffect, useRef, useState } from 'react';

export default function ErrorFixCell({ error, fix }: { error?: string | null; fix?: string | null }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const errorText = typeof error === 'string' ? error.trim() : '';
  const fixText = typeof fix === 'string' ? fix.trim() : '';
  const shorten = (text: string) => text.length > 100 ? `${text.slice(0, 100)}…` : text;

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    };
  }, []);

  const copyError = async () => {
    if (!errorText || copied) return;
    try {
      await navigator.clipboard.writeText(errorText);
      setCopied(true);
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        setCopied(false);
      }, 1200);
    } catch { /* clipboard unavailable */ }
  };
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      void copyError();
    }
  };
  return <div className="min-w-44 space-y-1 text-[10px] leading-tight">
    {errorText
      ? <div
          className="line-clamp-2 cursor-copy text-neon-red transition-opacity hover:opacity-80"
          title={copied ? 'تم النسخ ✓' : errorText}
          onClick={copyError}
          onKeyDown={onKeyDown}
          role="button"
          tabIndex={0}
          aria-label="نسخ نص الخطأ"
        >❌ {shorten(errorText)}{copied && <span className="text-neon-green"> ✓</span>}</div>
      : <div className="text-text-muted">—</div>}
    {errorText && fixText && <div className="border-t border-border-primary/30" />}
    {fixText ? <div className="line-clamp-2 text-neon-green" title={fixText}>✅ {shorten(fixText)}</div> : <div className="text-text-muted">—</div>}
    <span role="status" className="sr-only">{copied ? 'تم النسخ' : ''}</span>
  </div>;
}
