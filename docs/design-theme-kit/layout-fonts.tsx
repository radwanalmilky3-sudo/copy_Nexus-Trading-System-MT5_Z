// ============================================================
// إعداد الخطوط — انسخ هذا الملف إلى مشروع Next.js باسم src/app/layout.tsx
// أو انسخ تعريفَي localFont إلى layout.tsx الموجود لديك.
// ملفات الخطوط ttf توضع في المجلد: src/fonts/
// ============================================================
import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// IBM Plex Sans Arabic — خط النصوص العربية (طرفية مالية احترافية، RTL أصلي)
const plexArabic = localFont({
  src: [
    { path: "../fonts/IBMPlexSansArabic-Regular.ttf", weight: "400", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-Medium.ttf", weight: "500", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-SemiBold.ttf", weight: "600", style: "normal" },
    { path: "../fonts/IBMPlexSansArabic-Bold.ttf", weight: "700", style: "normal" },
  ],
  variable: "--font-plex-arabic",
  display: "swap",
});

// IBM Plex Mono — للأرقام والأسعار (محاذاة tabular-nums)
const plexMono = localFont({
  src: [
    { path: "../fonts/IBMPlexMono-Regular.ttf", weight: "400", style: "normal" },
    { path: "../fonts/IBMPlexMono-Medium.ttf", weight: "500", style: "normal" },
    { path: "../fonts/IBMPlexMono-SemiBold.ttf", weight: "600", style: "normal" },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // rtl + dark: جوهر الثيم — عربي، من اليمين لليسار، وضع داكن دائم
    <html lang="ar" dir="rtl" className="dark" suppressHydrationWarning>
      <body
        className={`${plexArabic.variable} ${plexMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
      </body>
    </html>
  );
}
