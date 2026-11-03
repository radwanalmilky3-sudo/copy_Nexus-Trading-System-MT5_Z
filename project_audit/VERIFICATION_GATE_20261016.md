# بوابة التحقق الموحدة — 2026-10-16

## النتائج

| الفحص | النتيجة |
|---|---|
| اختبارات Python الكاملة | **1000 passed, 3 warnings** في 47.37 ثانية (بعد إصلاح 20 فشلًا) |
| TypeScript (dashboard `tsc --noEmit`) | **PASS — TS_EXIT=0** |
| تشغيل الخدمات / قاعدة حية / شبكة | لم يُنفَّذ (خارج نطاق البوابة) |

## ملاحظات التحقق

- الفشل الـ20 في الدفعة الأولى نتج عن تعديلات الأودت نفسها (عقود أشد fail-closed) أو توقعات اختبارات قديمة؛ صُحِّح المصدر أو التوقع بعد التحقق من أن السلوك الجديد هو الصحيح:
  - `duckdb_store`: DuckDB يرفض ADD COLUMN بقيود → عمود خالص + UPDATE افتراضي.
  - `fundamental_store.query_named`: قبول `None` كقيمة SQL مربوطة (كان يرفضه).
  - `intelligence` trade-memory: سجل structlog بـ`error=` kwarg كان ينهار في بيئة الاختبار → format في الرسالة.
  - ML provenance: `getattr` لحقول fold/ensemble الغائبة في الاختبارات.
  - اختبار backtest empty: عزل `_fetch_trades` (المصدر الدائم الجديد).
  - اختبار الحارس المطلس: تمرير `_require` كما في اختبارات Mode المجاورة.
  - اختبار performance: قبول 503 (fail-closed الجديد).
  - اختبار exposure: قبول رسالة circuit-breaker المرفوضة أيضًا.
  - اختبار الذروة المتشكلة: تواريخ ديناميكية (تاريخ ثابت كان قد انغلق بالكامل).
  - HierarchicalTable: نوع `LucideIcon` بدل ComponentType المتعارض.
- لا يُعلن الاكتمال 100% إلا مع مطابقة `FILE_MANIFEST.tsv` (بند 8 في REMAINING_WORK).
