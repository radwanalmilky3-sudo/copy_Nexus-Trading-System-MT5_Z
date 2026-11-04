# 🎨 مرجع توكنز التصميم — ثيم «الذهب الداكن» (Gold Terminal Theme)

> هذا هو التصميم الكامل المستخرج من مشروع FinGPT Gold — جاهز للنقل إلى أي مشروع آخر.
> المنظومة: Tailwind CSS 4 + shadcn/ui + وضع داكن دائم + RTL عربي أصلي.

---

## 1) الهوية العامة

| العنصر | القيمة |
|---|---|
| الاسم | ثيم طرفية الذهب — أسود دافئ + ذهبي عنبري |
| الاتجاه | RTL أصلي (`<html lang="ar" dir="rtl" className="dark">`) |
| الوضع | داكن دائم (لا يوجد فاتح في الاستخدام الفعلي) |
| الطابع | طرفية مالية / Terminal — خلفية داكنة دافئة، ذهبي كأبرز لون، نصوص ثانوية رمادية دافئة |
| نصف القطر الأساسي | `--radius: 0.625rem` (10px) — sm=6px، md=8px، lg=10px، xl=14px |

## 2) الخطوط

| الاستخدام | الخط | الأوزان | المتغير |
|---|---|---|---|
| النصوص العربية والعناوين | **IBM Plex Sans Arabic** | 400, 500, 600, 700 | `--font-plex-arabic` → `--font-sans` |
| الأرقام والأسعار والشيفرة | **IBM Plex Mono** | 400, 500, 600 | `--font-plex-mono` → `--font-mono` |

- الأرقام دائماً داخل `.num`: `font-family: var(--font-mono); font-variant-numeric: tabular-nums; letter-spacing: -0.01em;` مع `dir="ltr"`.
- `font-feature-settings: "ss01"` على body.
- أحياز الخطوط المستخدمة في الواجهة: عنوان الصفحة `text-lg/xl font-bold`، الأرقام الكبيرة `text-3xl font-bold`، العناوين الثانوية `text-xs text-neutral-400`، التسميات الدقيقة `text-[11px]`، الشارات `text-xs`.

## 3) لوحة الألوان — الوضع الداكن (الأساسي)

قيم CSS الأصلية بصيغة oklch، مع مكافئ hex التقريبي للمرجع:

| التوكن | oklch | hex≈ | الاستخدام |
|---|---|---|---|
| `--background` | `oklch(0.16 0.01 85)` | `#0f0d08` | خلفية الصفحة (أسود دافئ مائل للعنبري) |
| `--foreground` | `oklch(0.93 0.012 85)` | `#ebe7df` | النص الأساسي (أبيض دافئ) |
| `--card` | `oklch(0.2 0.012 85)` | `#191610` | خلفية البطاقات |
| `--popover` | `oklch(0.19 0.012 85)` | `#16130e` | القوائم المنبثقة |
| `--primary` | `oklch(0.78 0.145 82)` | `#e5ad34` | **الذهبي الرئيسي** (أزرار، تركيز) |
| `--primary-foreground` | `oklch(0.18 0.03 82)` | `#181003` | نص فوق الذهبي |
| `--secondary` | `oklch(0.26 0.015 85)` | `#27241c` | عناصر ثانوية |
| `--muted` | `oklch(0.25 0.012 85)` | `#24211b` | خلفيات هادئة |
| `--muted-foreground` | `oklch(0.66 0.02 85)` | `#989285` | نصوص ثانوية |
| `--accent` | `oklch(0.28 0.025 82)` | `#2f281b` | تمييز عند hover |
| `--accent-foreground` | `oklch(0.95 0.03 85)` | `#f8edd8` | نص فوق التمييز |
| `--destructive` | `oklch(0.704 0.191 22.216)` | `#ff6467` | أخطاء/سقوط |
| `--border` | `oklch(1 0 0 / 9%)` | أبيض 9% | حدود خفيفة شفافة |
| `--input` | `oklch(1 0 0 / 13%)` | أبيض 13% | حدود الحقول |
| `--ring` | `oklch(0.78 0.145 82 / 55%)` | ذهبي 55% | حلقة التركيز |

### ألوان Tailwind المستخدمة مباشرة في الواجهة

| اللون | hex | الاستخدام |
|---|---|---|
| `amber-300` | `#fcd34d` | أرقام ذهبية بارزة (`text-amber-300`) |
| `amber-400` | `#fbbf24` | بداية تدرج التبويب النشط |
| `amber-500` | `#f59e0b` | الذهبي الأساسي للحدود (`border-amber-500/15..40`) والشارات |
| `amber-600` | `#d97706` | نهاية التدرجات |
| `amber-950` | `#451a03` | نص فوق الذهبي الساطع |
| `emerald-600`/`emerald-400` | `#059669` / `#34d399` | الإيجابي/الصاعد |
| `red-500`/`red-400` | `#ef4444` / `#f87171` | السلبي/الهابط |
| `neutral-400/500` | `#a3a3a3` / `#737373` | نصوص ثانوية وتسميات |
| `neutral-800` | `#262626` | خلفيات أشرطة التقدم |

## 4) التدرجات والتوهجات (بصمة الثيم)

| الاسم | القيمة | الاستخدام |
|---|---|---|
| `.gold-text` | `linear-gradient(120deg, #fde68a 0%, #f59e0b 45%, #d97706 100%)` + `background-clip: text` | تدرج ذهبي على كلمات العنوان والأرقام المميزة |
| التوهج العلوي | `bg-[radial-gradient(ellipse_at_top,rgba(245,158,11,0.12),transparent_62%)]` بطبقة `fixed` بارتفاع 320px | هالة ذهبية أعلى الصفحة |
| بطاقة ذهبية | `bg-gradient-to-br from-amber-500/10 to-transparent` + `border-amber-500/20` | البطاقة الأهم (السعر) |
| تدرج التبويب النشط | `bg-gradient-to-b from-amber-400 to-amber-600 text-amber-950` | التبويب/الزر النشط |
| شريط تقدم | `bg-gradient-to-r from-amber-600 to-amber-300` على `bg-neutral-800` | مؤشر الموقع في النطاق |
| ظل ذهبي | `shadow-amber-500/25` مع `shadow-lg` أو `shadow-md` | الشعار والتبويب النشط |

## 5) الزجاج والحدود (Glass / Backdrop)

- الشريط العلوي: `border-b border-amber-500/15 bg-background/80 backdrop-blur-md` (ثابت sticky).
- شريط التبويبات: `border-amber-500/10 bg-background/85 backdrop-blur-md` (sticky تحت الهيدر).
- الحدود دائماً ذهبية شفافة منخفضة الكثافة: `amber-500/10` حتى `amber-500/40` — لا حدود سوداء صريحة.
- أزرار outline: `border-neutral-700 hover:border-amber-500/40 hover:text-amber-300`.

## 6) الشارات (Badges)

| النمط | الأصناف |
|---|---|
| شارة حي | `border-amber-500/40 bg-amber-500/10 text-amber-300` (variant outline) |
| إيجابي/صاعد | `bg-emerald-600 text-white` |
| سلبي/هابط | `bg-red-500 text-white` |
| ذهبي مميز | `bg-amber-500 text-amber-950` |
| محايد | `bg-neutral-600 text-white` |

## 7) الأنماط المساعدة (من globals.css)

```css
.gold-text      /* تدرج ذهبي للنص */
.num            /* IBM Plex Mono + tabular-nums للأرقام */
.gold-cell-pos  /* #34d399 semibold — إيجابي */
.gold-cell-neg  /* #f87171 semibold — سلبي */
.gold-cell-neu  /* #a8a29e — محايد */
.gold-scroll    /* شريط تمرير 8px بمقبض #44403c */
```

+ قسم اختياري لتلوين إطارات `rc-dock` و`Allotment` بالهوية الذهبية (موجود في globals.css — احذفه إن لم تستخدم المكتبتين).

## 8) الحركة (Motion)

- ظهور تدريجي للبطاقات عند التمرير: `whileInView` (fade + slide بسيط) عبر `motion`.
- عدّادات أرقام متحركة (CountUp) للأرقام الكبيرة.
- `transition-colors` على العناصر التفاعلية + `hover` ذهبي.

## 9) شبكة الصفحة

- حاوية: `mx-auto w-full max-w-7xl px-4 sm:px-6 py-6`.
- بطاقات KPI قابلة للسحب (react-grid-layout) بشبكة 12 عموداً.
- الرسوم البيانية: خطوط سعرية ذهبية `#f59e0b`، خلفية الرسم شفافة، شبكة خطوط `#262626`.

## 10) ما يحتاج تثبيته

```bash
bun add tailwindcss @tailwindcss/postcss tw-animate-css clsx tailwind-merge class-variance-authority
bun add lucide-react motion
# اختياري (مكوّنات جاهزة): shadcn/ui —.radix-ui — أو انسخ مجلد components/ui
bun add react-grid-layout react-resizable-panels allotment rc-dock react-aria-components
bun add lightweight-charts ag-grid-community ag-grid-react
```
