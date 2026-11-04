# 🥇 حزمة نقل التصميم — ثيم «طرفية الذهب» (Gold Terminal Theme)

الحزمة الكاملة لنقل التصميم من مشروع **FinGPT Gold** إلى أي مشروع آخر (في chat.z.ai أو أي بيئة).
الطابع: طرفية مالية داكنة — أسود دافئ + ذهبي عنبري + خطا IBM Plex + RTL عربي أصلي.

## محتويات الحزمة

| الملف | الغرض |
|---|---|
| `globals.css` | **القلب**: ملف الثيم الكامل الجاهز للصق (Tailwind 4 + متغيرات oklch + الأصناف المساعدة) |
| `layout-fonts.tsx` | إعداد الخطوط المحلية IBM Plex (انسخه كـ `src/app/layout.tsx` أو انسخ تعريفَيه) |
| `fonts/` | ملفات الخطوط السبعة ttf — تُوضع في `src/fonts/` |
| `THEME_PROMPT.md` | **برومبت جاهز للصق في chat.z.ai** يعيد إنتاج نفس التصميم حرفياً |
| `DESIGN_TOKENS.md` | مرجع كل التوكنز: ألوان (oklch + hex)، خطوط ومقاييس، تدرجات، شارات، حركة |
| `preview.html` | معاينة حية مستقلة — افتحها في المتصفح وأرسلها كمرجع بصري |
| `project-files/components.json` | إعداد shadcn/ui (new-york, neutral, cssVariables) |
| `project-files/postcss.config.mjs` | إعداد Tailwind 4 PostCSS |
| `project-files/src/lib/utils.ts` | دالة `cn()` المطلوبة لمكوّنات shadcn |

## التركيب في مشروع Next.js جديد (خطوات حرفية)

```bash
# 1. أنشئ المشروع (أو استخدم مشروعاً قائماً)
bun create next-app my-app --typescript --tailwind --eslint

cd my-app
# 2. انسخ الملفات
cp kit/globals.css        src/app/globals.css
cp kit/layout-fonts.tsx   src/app/layout.tsx      # أو انسخ تعريفَي الخط فقط
cp -r kit/fonts           src/fonts
cp kit/project-files/components.json .
mkdir -p src/lib && cp kit/project-files/src/lib/utils.ts src/lib/
bun add clsx tailwind-merge class-variance-authority lucide-react motion tw-animate-css
```

ثم أي مكوّنات shadcn تحتاجها: `bunx shadcn@latest add button card badge tabs table`

## التركيب في مشروع HTML عادي (غير Next.js)

- استخدم Google Fonts بدل الملفات المحلية:
  `IBM Plex Sans Arabic` (400,500,600,700) + `IBM Plex Mono` (400,500,600)
- انسخ متغيرات `:root` و `.dark` من globals.css، واستبدل `var(--font-plex-arabic)` بـ `'IBM Plex Sans Arabic'` و `var(--font-plex-mono)` بـ `'IBM Plex Mono'`.
- أو انسخ `preview.html` مباشرة — هو نموذج عمل كامل بهذه الطريقة.

## الاستخدام في chat.z.ai

1. افتح `THEME_PROMPT.md` وانسخ النص الواقع بين الخطين.
2. الصقه في محادثة مشروعك الجديد (أول رسالة)، ثم اكتب طلبك فوقه.
3. أرفق `preview.html` (أو صورة منه) كمرجع بصري إن أردت مطابقة أدق.
4. إن كانت البيئة تدعم مرفقات كود: أرفق `globals.css` + `fonts/` + `layout-fonts.tsx`.

## ملاحظات

- الثيم داكن دائم (`className="dark"` على html) — لا يحتاج next-themes إلا إذا أردت وضعاً فاتحاً لاحقاً.
- قسم `rc-dock`/`Allotment` في نهاية globals.css اختياري — احذفه إن لم تستخدم المكتبتين.
- قيم hex المذكورة تقريبية للمرجع؛ المصدر الرسمي هو قيم oklch (دقة ألوان أوسع).
