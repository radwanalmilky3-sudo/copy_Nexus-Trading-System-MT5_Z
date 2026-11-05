# COMPONENT QA REPORT — NEXUS TRADER MT5 (المرحلة 8 من M.2)

> التاريخ: 2026-11-04 ليلًا. المنهجية: لكل خدمة — `/health` (فحص جسم) + OpenAPI حي + نداء وظيفي حقيقي من مسارات OpenAPI الفعلية (لا تخمين) + حالة خطأ (مسار بمعرف زائف). الأدلة: `qa/evidence/tc_sv_results.json` (سكربت `scripts/tc_sv_services_live.py`).
> الحالات: PASS / FAIL / BLOCKED / NOT TESTED / FIXED-PENDING RETEST / FIXED-VERIFIED.

## 1) الخدمات التسع — نتائج حية (16:56 UTC)

| ID | الخدمة | Port | /health | OpenAPI | نداء وظيفي | حالة خطأ | الحكم |
|---|---|---|---|---|---|---|---|
| TC-SV-01 | nexus-api | 9000 | **200 (2ms)** | 165 مساراً | GET /api/admin/audit → 200 (ب JWT) | معرف زائف → 404 صادق | **PASS** |
| TC-SV-02 | nexus-data | 9001 | **200 (1ms)** | 26 مساراً | GET /api/data/fundamental/schema → 200 | /api/data/flow/زائف → 200 **غلاف صفري صادق** (`bars_analyzed:0` — انظر N6) | **PASS** |
| TC-SV-03 | nexus-features | 9002 | **200 (1ms)** | 4 مسارات | GET /health → 200 | /api/features/institutional/زائف → **403** (حماية داخلية) | **PASS** |
| TC-SV-04 | nexus-ml | 9003 | **200 (1ms)** | 19 مساراً | GET /api/ml/models/status → **403** (حماية داخلية — سلوك صحيح) | predict/زائف → 403 | **PASS** |
| TC-SV-05 | nexus-agents | 9004 | **503 (6.0s)** — fail-closed موثق | 14 مساراً | 403 (حماية داخلية) | 403 | **PASS كسلوك موثق** (جسم 503: `status:OFFLINE, llm:OFFLINE, ready:false, llm_latency_ms:6023` — مهلة مزود LLM، Redis سليم) |
| TC-SV-06 | nexus-news | 9005 | **200 (2ms)** | 8 مسارات | 403 (حماية داخلية) | 403 | **PASS** (+ إصلاح P2-2 أدناه) |
| TC-SV-07 | nexus-risk | 9006 | **200 (3ms)** | 9 مسارات | 403 (حماية داخلية) | — | **PASS** |
| TC-SV-08 | nexus-executor | 9007 | **200 (2ms)** | 6 مسارات | GET /account → 200 (paper: broker=paper) | — | **PASS** |
| TC-SV-09 | nexus-monitor | 9008 | **200 (1ms)** | 6 مسارات | 403 (حماية داخلية) | — | **PASS** (+ إصلاح P2-2 أدناه) |

**النتيجة: 9/9 PASS** (9004 ضمن سلوك fail-closed الموثق — لا يُحسب فشلاً؛ سجل الأدلة يحفظ الجسم كاملاً).

**نمط أمني مثبت:** الخدمات الداخلية (9002/9003/9004/9005/9006/9008) ترد **403** على كل نداء بلا سر داخلي — البوابة 9000 هي الواجهة الوحيدة العامة. هذا يعزز نتائج الأمن (المرحلة 11).

## 2) حالات الخدمات في `/api/system/health` — إصلاح P2-2 (FIXED-VERIFIED)

**الجذران (اكتشاف هذه الدورة):**
1. `nexus-news` كانت تدوس على نبضة monitor الصحيحة بسلسلة ISO خام (`_redis.set` بطابع زمني فقط) — البوابة تفحص `isinstance(dict)` فترفض → "unknown" دائم تقريباً.
2. `nexus-monitor` تكتب نبضات **الآخرين** فقط ولا تكتب نبضتها هي أبداً → "unknown" دائم.

**الإصلاح:** news تكتب `SystemHealth` كاملاً بنفس شكل الجميع (`CACHE_HEALTH_PREFIX` + `ServiceName.NEWS`)؛ monitor تضيف نبضة ذاتية في نهاية كل دورة فحص (`ttl = 3×الفاصل`). إعادة إقلاع حية عبر المشرف، وبعد دورة نبضة كاملة:

```
nexus-api healthy | nexus-data degraded* | nexus-features healthy | nexus-ml healthy
nexus-agents unhealthy* | nexus-news healthy ✅ | nexus-risk healthy
nexus-executor healthy | nexus-monitor healthy ✅
```
\* حالتان صادقتان موروثتان لا علاقة لهما بـP2-2: `nexus-agents unhealthy` = fail-closed (مزود LLM)؛ `nexus-data degraded` = redis+duckdb سليمان و`mt5_ok=false` (لا طرف MT5 في الصندوق — **اتساق تام** مع TC-MT-01 BLOCKED).

## 3) تصنيف المكونات (خلاصة — التفصيل في SYSTEM_INVENTORY.md)

| النوع | المكونات |
|---|---|
| microservices حية | nexus-api, nexus-data, nexus-features, nexus-ml, nexus-agents, nexus-news, nexus-risk, nexus-executor, nexus-monitor (الحقول 16 كاملة في SYSTEM_INVENTORY) |
| مكتبة (بلا main) | `nexus_strategy` |
| مشرف/منسق | run.py (شفاء <1s مقاس، سقف إعادة dashboard 3) |
| غير مستخدم وقت التشغيل | `fx-trading-system-main` (لا مرجع حي) |
| خارجي (طرف المالك) | MT5 Terminal + NexusBridgeEA.mq5 — BLOCKED حي (TC-MT-01) |

## 4) ملاحظات جديدة مسجلة

| ID | الوصف | التصنيف |
|---|---|---|
| N6 | ~~`/api/data/flow/{symbol}` يرد 200 بغلاف صفري صادق لرموز غير معروفة — تصميم مقبول ويستحق توحيداً مستقبلياً~~ — **مُوحَّد ومغلق 2026-11-05 (T-008)**: 404 قاعدة البحث بالرمز في خدمة البيانات كلها (ohlcv + flow + flow-alias + provenance)، التزام عقود الصدق UI-05/UI-06 (الغياب صريح لا يُموي بصفر)؛ مستهلكو flow يتراجعون لتغليفهم المحلي، وohlcv-404 محفوظ لما يعتمد عليه (outcome_collector)؛ 5 بروبات تثبيت جديدة + 3 بروبات قديمة حدّثت لدلالة 404 (نمط D19: انزياح اختبارات لا عيوب إنتاج) | ملاحظة تصميم → CLOSED |
| P2-2 | أُغلقت — FIXED-VERIFIED (أعلاه §2) | مُصلحة |

## 5) البوابة للمراحل التالية
- المرحلة 9 (قاعدة البيانات): TC-DB-01..07 — النسخة المعزولة +WAL.
- TC-SV-10 (تدهور رشيق) مستوفى سابقاً (S4 جولة 3)؛ TC-SV-11 (Redis أساسي) ضمن أدلة هذه الدورة (keys/النبضات/pub-sub الجديد D16).
