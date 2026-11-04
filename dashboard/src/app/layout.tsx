import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
import { Providers } from './providers';

/* M1.3 — IBM Plex from the owner's design-theme-kit (local TTFs, no CDN).
 * Sans Arabic carries the UI text; Mono serves numbers/prices via .num. */
const plexArabic = localFont({
  src: [
    { path: '../fonts/IBMPlexSansArabic-Regular.ttf', weight: '400', style: 'normal' },
    { path: '../fonts/IBMPlexSansArabic-Medium.ttf', weight: '500', style: 'normal' },
    { path: '../fonts/IBMPlexSansArabic-SemiBold.ttf', weight: '600', style: 'normal' },
    { path: '../fonts/IBMPlexSansArabic-Bold.ttf', weight: '700', style: 'normal' },
  ],
  variable: '--font-plex-arabic',
  display: 'swap',
});

const plexMono = localFont({
  src: [
    { path: '../fonts/IBMPlexMono-Regular.ttf', weight: '400', style: 'normal' },
    { path: '../fonts/IBMPlexMono-Medium.ttf', weight: '500', style: 'normal' },
    { path: '../fonts/IBMPlexMono-SemiBold.ttf', weight: '600', style: 'normal' },
  ],
  variable: '--font-plex-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Nexus Trader',
  description: 'AI-Powered Multi-Agent Trading Terminal',
  other: { google: 'notranslate' },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" translate="no" className="dark notranslate" suppressHydrationWarning>
      <body
        translate="no"
        className={`${plexArabic.variable} ${plexMono.variable} font-sans antialiased`}
        style={{ background: 'var(--bg-primary)' }}
      >
        <Providers>
          <div className="relative min-h-screen bg-matrix">
            {children}
          </div>
        </Providers>
      </body>
    </html>
  );
}
