'use client';

import * as React from 'react';
import { Moon, Sun } from 'lucide-react';

// مبدّل الثيم (فاتح/غامق) — القاعدة الغامقة هي الافتراضي؛ الاختيار يُحفظ
// محلياً ويُطبَّق عبر كلس `light` على عنصر html فيقلب كل توكنات التصميم.
const STORAGE_KEY = 'nexus-theme';

function apply(theme: 'dark' | 'light') {
  const root = document.documentElement;
  if (theme === 'light') root.classList.add('light');
  else root.classList.remove('light');
}

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<'dark' | 'light'>('dark');
  const [ready, setReady] = React.useState(false);

  React.useEffect(() => {
    const saved = (localStorage.getItem(STORAGE_KEY) as 'dark' | 'light' | null) ?? 'dark';
    setTheme(saved);
    apply(saved);
    setReady(true);
    const handler = (e: Event) => {
      const next = (e as CustomEvent<{ theme: 'dark' | 'light' }>).detail?.theme;
      if (next === 'dark' || next === 'light') setTheme(next);
    };
    window.addEventListener('nexus-theme-change', handler);
    return () => window.removeEventListener('nexus-theme-change', handler);
  }, []);

  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    apply(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch {}
    window.dispatchEvent(new CustomEvent('nexus-theme-change', { detail: { theme: next } }));
  };

  if (!ready) return <span className="h-8 w-8" aria-hidden="true" />;
  const isLight = theme === 'light';
  return (
    <button
      type="button"
      onClick={toggle}
      title={isLight ? 'التبديل إلى الثيم الغامق' : 'التبديل إلى الثيم الفاتح'}
      aria-label={isLight ? 'الثيم الفاتح — اضغط للغامق' : 'الثيم الغامق — اضغط للفاتح'}
      aria-pressed={isLight}
      className="flex h-8 w-8 items-center justify-center rounded border border-border-primary bg-bg-secondary text-text-secondary transition-colors hover:border-neon-gold/40 hover:text-neon-gold"
    >
      {isLight ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
    </button>
  );
}

export default ThemeToggle;
