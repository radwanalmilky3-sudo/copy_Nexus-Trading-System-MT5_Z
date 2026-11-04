# 📋 البرومبت الجاهز — انسخ ما بين الخطين إلى chat.z.ai

> الطريقة: افتح محادثتك في chat.z.ai، والصق النص التالي كأول رسالة (أو مع طلب بناء مشروعك)،
> فيتبنّى المساعد هناك نفس التصميم حرفياً. أرفق معه ملف `globals.css` إن سُمح بالمرفقات.

---

```text
طبّق على المشروع المطلوب طبقة التصميم التالية حرفياً (ثيم «طرفية الذهب» الداكن). لا تغيّر الألوان ولا الخطوط:

【الهوية】
- واجهة عربية RTL كاملة: <html lang="ar" dir="rtl" className="dark"> — وضع داكن دائم.
- الطابع: طرفية مالية (Trading Terminal) فاخرة — خلفية سوداء دافئة، الذهبي هو لون الهوية الوحيد، نصوص ثانوية رمادية دافئة.

【الخطوط】
- النصوص: IBM Plex Sans Arabic (أوزان 400/500/600/700) — عبر next/font/local مع متغير --font-plex-arabic.
- الأرقام والأسعار: IBM Plex Mono (400/500/600) مع متغير --font-plex-mono، وتُعرض دائماً داخل صنف .num بـ font-variant-numeric: tabular-nums و letter-spacing: -0.01em و dir="ltr".
- body عليه font-feature-settings: "ss01".
- مقاييس الخط: عنوان الصفحة text-lg/xl bold، الأرقام الكبيرة text-3xl bold بلون ذهبي، التسميات text-xs بلون neutral-400، التفاصيل الدقيقة text-[11px] بلون neutral-500.

【الألوان — متغيرات CSS (oklch)】
--background: oklch(0.16 0.01 85)   /* أسود دافئ */
--foreground: oklch(0.93 0.012 85)  /* أبيض دافئ */
--card: oklch(0.2 0.012 85)  --card-foreground: oklch(0.93 0.012 85)
--popover: oklch(0.19 0.012 85)  --popover-foreground: oklch(0.93 0.012 85)
--primary: oklch(0.78 0.145 82)   /* الذهبي الرئيسي #e5ad34 */
--primary-foreground: oklch(0.18 0.03 82)
--secondary: oklch(0.26 0.015 85)  --secondary-foreground: oklch(0.93 0.012 85)
--muted: oklch(0.25 0.012 85)  --muted-foreground: oklch(0.66 0.02 85)
--accent: oklch(0.28 0.025 82)  --accent-foreground: oklch(0.95 0.03 85)
--destructive: oklch(0.704 0.191 22.216)
--border: oklch(1 0 0 / 9%)  --input: oklch(1 0 0 / 13%)
--ring: oklch(0.78 0.145 82 / 55%)
--radius: 0.625rem
(مكافئات hex: خلفية #0f0d08، بطاقة #191610، ذهبي #e5ad34، نص #ebe7df، ثانوي #989285)

【قواعد الذهبي في Tailwind】
- أرقام بارزة وعناوين مميزة: text-amber-300 (#fcd34d).
- الحدود دائماً ذهبية شفافة: border-amber-500/15 للهيدر، /20 للبطاقات، /40 للأزرار والشارات — ممنوع الحدود الرمادية الصريحة حول العناصر الذهبية.
- الإيجابي/الصاعد: emerald-600 أو emerald-400. السلبي/الهابط: red-500 أو red-400.

【البصمات الإلزامية】
1) صنف .gold-text: تدرج ذهبي على النص — background: linear-gradient(120deg,#fde68a 0%,#f59e0b 45%,#d97706 100%); -webkit-background-clip:text; color:transparent. استخدمه على كلمة واحدة من العنوان الرئيسي وعلى الرقم الأهم.
2) هالة علوية: طبقة fixed أعلى الصفحة h-80 بـ background: radial-gradient(ellipse at top, rgba(245,158,11,0.12), transparent 62%).
3) البطاقة الأهم (السعر): border-amber-500/20 bg-gradient-to-br from-amber-500/10 to-transparent.
4) التبويب/الزر النشط: bg-gradient-to-b from-amber-400 to-amber-600 text-amber-950 font-bold مع shadow-md shadow-amber-500/25، وزوايا rounded-lg.
5) الهيدر ثابت sticky: border-b border-amber-500/15 bg-background/80 backdrop-blur-md، وفيه شعار مربع h-10 w-10 rounded-xl bg-gradient-to-br from-amber-300 to-amber-600 ظل ذهبي shadow-amber-500/25.
6) شريط تقدم/موقع: مسار bg-neutral-800 h-1.5 rounded-full ومؤشر bg-gradient-to-r from-amber-600 to-amber-300.
7) شارات الحالة: إيجابي bg-emerald-600 text-white، سلبي bg-red-500 text-white، محايد bg-neutral-600 text-white، حي/ذهبي border-amber-500/40 bg-amber-500/10 text-amber-300.
8) شريط تمرير رفيع: .gold-scroll بعرض 8px ومقبض #44403c.
9) ظهور تدريجي للأقسام عند التمرير (motion: whileInView، fade+انزلاق خفيف) وعدّادات أرقام متحركة للأرقام الكبيرة.

【البنية】
- حاوية: mx-auto w-full max-w-7xl px-4 sm:px-6.
- شبكة بطاقات فوقية قابلة لإعادة الترتيب والتحجيم (react-grid-layout) ثم المحتوى بألواح قابلة للسحب (react-resizable-panels) وتبويبات RTL (react-aria-components).
- كل الأرقام والأسعار داخل .num وdir="ltr"، والنصوص العربية RTL.

【التقنيات】Next.js + Tailwind CSS 4 + shadcn/ui + lucide-react + motion. ثبّت الخطوط كملفات ttf محلية في src/fonts (IBM Plex Sans Arabic + IBM Plex Mono من IBM/Google).
```

---

## ملاحظات الاستخدام في chat.z.ai

1. **الصق البرومبت أعلاه** كما هو في بداية المشروع الجديد، ثم اكتب طلبتك العادية فوقه
   (مثال: «طبّق هذا الثيم على متجري/تقريري/لوحتي…»).
2. **أرفق الملفات** إن أردت مطابقة 100%: `globals.css` + مجلد `fonts/` + `layout-fonts.tsx` —
   فهي المصدر الفعلي، والبرومبت وصفٌ لها.
3. **للمشاريع غير Next.js** (HTML عادي / React عادي / Vue): استبدل فقرة الخطوط بـ
   Google Fonts: `IBM Plex Sans Arabic` و `IBM Plex Mono`، واستخدم نفس متغيرات CSS
   في `:root` بدل next/font.
4. **المعاينة**: افتح `preview.html` في المتصفح — يعرض الثيم كاملاً (ألوان، خطوط، بطاقات،
   شارات، تدرجات) ويمكنك إرساله كمرجع بصري للمساعد في chat.z.ai.
