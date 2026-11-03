# Progress Screen — Arabic/RTL/UX Review (Agent-13) — 2026-10-16

READ-ONLY review. Files: `dashboard/src/app/dashboard/progress/page.tsx`,
`dashboard/src/components/progress/{HierarchicalTable,ProgressCell,ErrorFixCell}.tsx`,
`dashboard/src/app/progress-state/route.ts` (+ layout/globals for context).

Measured contrast (WCAG AA needs 4.5:1 for <18.66px text):

| fg | vs #09090b | vs #0f1117 | vs #161820 | verdict |
|---|---|---|---|---|
| `--text-muted #4e5264` | **2.57** | **2.44** | **2.29** | **FAIL** |
| `--text-secondary #8b8fa3` | 6.21 | 5.89 | 5.53 | pass |
| `--neon-cyan #06b6d4` | 8.19 | 7.77 | 7.30 | pass |
| `--neon-green #22c55e` | 8.73 | 8.28 | 7.77 | pass |
| `--neon-red #ef4444` | 5.29 | 5.01 | 4.71 | pass |
| `--neon-gold #eab308` | 10.37 | 9.84 | 9.24 | pass |

Node ICU samples used: `toLocaleString('ar-SA')` → `١٦‏/١٠‏/٢٠٢٦، ٥:٢٣:٠١ م`
(Arabic-Indic digits), `toLocaleString('ar')` → `16/10/2026، 5:23:01 م` (Latin),
`ar-SA-u-ca-islamic-umalqura` → `٥‏/٥‏/١٤٤٨ هـ` (Hijri), `RelativeTimeFormat('ar')`
→ `قبل 3 ساعات` / `هذه الدقيقة` (natural, Latin digits).

---

## P0

### P0-1 `--text-muted` fails WCAG AA everywhere (2.3–2.6:1)
- `dashboard/src/app/globals.css:56` — `--text-muted: #4e5264` on dark bgs = **2.29–2.57:1**, needs 4.5:1.
- Hit sites (all 9–11px): `page.tsx:129` (source line), `page.tsx:154,160` (current-task labels),
  `HierarchicalTable:67` (empty state), `:83` (description column), `:92` (entire `<thead>`),
  `ProgressCell:13,20` (null values), `ErrorFixCell:20,22` ("—" placeholders).
- Fix: raise to **`#7c8398`** (4.69–5.26 on all three bgs) or reuse `#8b8fa3`.
- Replacement: `--text-muted: #7c8398;`

## P1

### P1-1 Mixed numeral systems + unpinned calendar on one line
- `page.tsx:106` `toLocaleString('ar-SA')` → Arabic-Indic digits `١٦‏/١٠‏/٢٠٢٦…`;
  `page.tsx:160` prints raw ISO `last_updated` (Latin, `2026-10-16T14:23:01Z`) on the
  **same line**: `البداية: ١٦/١٠/٢٠٢٦… · آخر تحديث: 2026-10-16T14:23:01Z`.
- Percent values use Latin digits (`ProgressCell:14`), `RelativeTimeFormat('ar')` outputs
  Latin digits (`page.tsx:21-25`) → three numeral styles in one screen.
- `ar-SA` calendar is not pinned (Hijri in builds with `ar-SA`→`islamic-umalqura` default,
  Gregorian in this Node) → a timestamp may silently render as year ١٤٤٨ هـ.
- Fix: one pinned helper, e.g.
  `new Date(x).toLocaleString('ar-SA-u-ca-gregory-nu-latn', { dateStyle: 'medium', timeStyle: 'short' })`
  applied to **both** `start_time` and `last_updated`, output in `<time dateTime={iso}>`.

### P1-2 Collapsed tree chevron points wrong way in RTL
- `HierarchicalTable:82` — collapsed shows `<ChevronRight/>`; under `dir="rtl"` children
  expand leftward, so collapsed must point **left**: `<ChevronLeft size={13}/>`.
  (Expanded `<ChevronDown/>` is fine.) Fix: `isExpanded ? <ChevronDown/> : <ChevronLeft/>`.

### P1-3 Copy control not keyboard accessible, feedback not announced
- `ErrorFixCell:19` — `<div onClick={copyError}>` has no `role`, `tabIndex`, key handler,
  or aria-label → unreachable by keyboard; `تم النسخ ✓` only changes `title` (mouse-only).
- Fix: `role="button" tabIndex={0} onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && copyError()}
  aria-label="نسخ نص الخطأ"` + `<span role="status" className="sr-only">تم نسخ الخطأ</span>`
  toggled with `copied`. Wrap the error payload in `<bdi dir="ltr">` (raw error text is English).

### P1-4 `lang="en"` root while page is Arabic
- `layout.tsx:29` `<html lang="en">`; only `page.tsx:121` sets `dir="rtl"` → screen readers
  use an English voice for Arabic text; `Inter({subsets:['latin']})` (`layout.tsx:6-10`)
  has no Arabic glyphs → Arabic falls back to an unrelated system font.
- Fix: add `lang="ar"` to the wrapper at `page.tsx:121`
  (`<div dir="rtl" lang="ar" …>`), and add `subsets: ['arabic']` / a Noto Sans Arabic face.

### P1-5 Error/empty/stale messages not actionable
- `page.tsx:115` «ملف الحالة غير متاح» → «ملف الحالة غير متاح — تأكد من وجود
  `<bdi dir="ltr">project_audit/DASHBOARD_STATE.json</bdi>` ثم أعد المحاولة»
- `page.tsx:117` «تعذر قراءة حالة المشروع» → «تعذر قراءة حالة المشروع — تحقق من اتصال
  الشبكة ثم أعد المحاولة»
- `HierarchicalTable:67` «لا توجد بيانات تقدم لعرضها» → «لا توجد مهام تطوير لعرضها —
  أعد التحديث أو انتظر توليد ملف الحالة» (also add `role="status"`)
- `page.tsx:149` «البيانات قديمة — آخر تحديث {staleLabel}» → append «؛ اضغط زر التحديث
  للحصول على أحدث حالة»
- `page.tsx:158` «لم تبدأ مهمة محددة» → «لا توجد مهمة نشطة حاليًا — راجع قائمة المهام أدناه»

### P1-6 Raw English status enums inside Arabic tooltips
- `ProgressCell:6,13` «الحالة: pending» / «الحالة: in_progress»; same enum flows from
  `HierarchicalTable:87` (`status={item.status}`).
- Fix: map `pending → قيد الانتظار`, `in_progress → قيد التنفيذ`, `done → مكتملة`,
  `failed → فشل` before interpolation.

### P1-7 No loading state — first paint lies
- Before the first fetch resolves, `state === null` yet `page.tsx:154-160` renders
  «لم تبدأ مهمة محددة» + «البداية: –» as if idle, with no `aria-busy`.
- Fix: when `!state && !error`, render `<div role="status">جارٍ تحميل حالة المشروع…</div>`
  (and `aria-busy="true"` on the section).

### P1-8 First-person phrasing
- `page.tsx:154` «المهمة الحالية التي أعمل عليها» — the screen speaks as the system, not
  the user; unnatural. Fix: «المهمة الحالية قيد التنفيذ».

## P2

### P2-1 Physical instead of logical CSS properties
- `HierarchicalTable:82` `pr-7` for indent (physically correct only because `dir="rtl"`)
  while `ms-1` on the same line is logical → use `ps-7`.
- `HierarchicalTable:92` `text-right` on the `<table>` → `text-start`.
- `page.tsx:160` uses `·`/`—` fine; no `ml/pl` offenders found in the four reviewed files
  (grep showed many in sibling screens — out of scope).

### P2-2 Latin identifier not bidi-isolated
- `page.tsx:129` «مصدر الحالة: project_audit/DASHBOARD_STATE.json» — currently survives UBA
  by luck; isolate it: «مصدر الحالة: <bdi dir="ltr">project_audit/DASHBOARD_STATE.json</bdi>».

### P2-3 No visible keyboard focus ring
- Refresh button `page.tsx:137`, retry button `page.tsx:173`, tree toggle
  `HierarchicalTable:82` have no `focus-visible` styling; repo-wide grep finds zero
  `focus-visible` rules (only `.neon-input:focus{outline:none}`, `globals.css:156-161`).
- Fix (each): add
  `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neon-cyan focus-visible:ring-offset-2 focus-visible:ring-offset-bg-primary`.

### P2-4 ARIA gaps
- `HierarchicalTable:82` tree toggle: add `aria-expanded={isExpanded}` and
  `type="button"`; leaf rows render a non-interactive `<span>` instead of a dead button.
- `HierarchicalTable:92` pie/bar charts: add `role="img"` +
  `aria-label="توزيع نسب الإنجاز حسب الفئة"` / `aria-label="تقدّم الخدمات حسب النسبة المئوية"`.
- Table: add `<caption className="sr-only">مهمام التقدّم حسب الخدمة والفئة</caption>`.
- Good already: `page.tsx:135-136` aria-label+title on refresh, `page.tsx:165`
  `role="alert"`, `page.tsx:145` `role="status"`.

### P2-5 Terminology inconsistency (تطوير / تقدم / حالة)
- `page.tsx:127` «متابعة التطوير» vs `HierarchicalTable:67` «بيانات تقدم» vs `:92`
  «تقدم الخدمات» vs `page.tsx:117,129,135` «حالة المشروع».
- Fix: keep «تطوير» for the screen («لا توجد بيانات تطوير لعرضها»), use «نسبة الإنجاز»
  for metrics, reserve «حالة» only for status. Also `HierarchicalTable:9` bare header
  «كود» → «الكود» to match «البند»/«الخطأ».

### P2-6 Bar chart ignores RTL
- `HierarchicalTable:92` `BarChart layout="vertical"` renders LTR inside SVG: bars grow
  left→right and category labels sit left, opposite the RTL table beside it.
- Fix: `<XAxis type="number" domain={[0,100]} reversed hide/>`,
  `<YAxis type="category" orientation="right" width={100} …/>`, and swap
  `margin={{left:30,right:15}}` → `{{left:15,right:30}}`.

### P2-7 Reduced-motion gap + tiny Arabic text + truncation
- `page.tsx:139` `animate-spin` on RefreshCw is **not** covered by the
  `prefers-reduced-motion` block (`globals.css:374-379` only stops `.spin-slow/.pulse-scale`).
  Fix: add `.animate-spin` to that media query or a `.refresh-spin` class.
- `ErrorFixCell:17` / `ProgressCell:7` use `text-[10px]` — Arabic is illegible at 10px;
  use ≥12px. `ErrorFixCell:8` `slice(0,100)` can split surrogate pairs; prefer
  `Array.from(text).slice(0,100).join('')` and `dir="ltr"`+`line-clamp-3`.
- Emojis `❌/✅` (`ErrorFixCell:19,22`) are announced by SRs — add `aria-hidden="true"`.

### P2-8 Untranslated server payload + perf nit
- `route.ts:11` returns `{ error: 'DASHBOARD_STATE.json unavailable' }` (English, in Arabic
  UI). Client only reads status (safe), but prefer a machine code:
  `NextResponse.json({ code: 'state_file_unavailable' }, { status: 503 })`.
- `page.tsx:21` constructs `Intl.RelativeTimeFormat` per call → hoist to module scope.

### Positive (no action)
- `dir="rtl"` present (`page.tsx:121`); hydration safe (`page.tsx:103` gates on
  `now !== null`, so SSR and first client render both show the raw ISO string);
  `relativeAr` output reads naturally («قبل 3 ساعات»); all neon colors pass AA;
  `role="alert"`/`role="status"` correct; refresh button has both `title` and `aria-label`;
  `prefers-reduced-motion` respected for the cell spinners; `colSpan={13}` matches
  4 + 9 columns.
