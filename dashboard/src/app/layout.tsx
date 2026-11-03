import type { Metadata } from 'next';
import './globals.css';
import { Providers } from './providers';

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
        className="font-sans antialiased"
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
