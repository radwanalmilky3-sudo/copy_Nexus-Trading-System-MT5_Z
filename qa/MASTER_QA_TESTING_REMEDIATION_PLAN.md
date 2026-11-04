# MASTER QA TESTING & REMEDIATION PLAN — NEXUS TRADER MT5

> **الإصدار:** M.2 — 2026-11-04. هذه الوثيقة هي **المرجع التنفيذي الحاكم** لكل مراحل التدقيق والاختبار والإصلاح.
> نطاقها: البنية المكتشفة فعلياً في `qa/SYSTEM_ARCHITECTURE_DISCOVERY_REPORT.md` (9 خدمات + dashboard + مشرف + Redis + DuckDB + EA خارجي).

## 1. النطاق المكتشف (ملخص)
- 9 خدمات FastAPI حية (9000–9008)، 257 مسار API (OpenAPI حي — مُعاد عدّه مساءً)، dashboard Next.js 14.2.5 بـ18 ملف مسار (15 شاشة فعّالة + 3 تحويلات).
- DuckDB **62 جدولاً** (كاتب وحيد)، Redis 7.4.1 (**129 مفتاحاً**)، مشرف run.py (شفاء <1s مُقاس).
- EA/MT5 على طرف المالك = **BLOCKED** للاختبار الحي في الصندوق (لا يُحسب فشلاً).
- paper-only مفعّل (`run.py --paper`) — ممنوع أي مسار حقيقي.

## 2. منهجية الاختبار
- **مستويات:** API مباشر (curl/python)، واجهة آلية (Playwright + agent-browser)، قاعدة بيانات (نسخة معزولة +WAL)، تكامل (سيناريوهات E2E)، أداء (قياسات مقاسة).
- **قواعد التنفيذ:** كل حالة TC بمعرف وأدلة؛ ممنوع اعتبار HTTP 200 كافياً بلا فحص جسم الاستجابة والاتساق؛ الحالات المتعذرة = BLOCKED/NOT TESTED لا PASS.
- **الإصلاح:** مستمر فور الاكتشاف (Critical فوري، High قبل اعتماد المرحلة، Medium ضمن الدورة أو تأجيل موثق، Low مجدول). كل إصلاح → جذر + ملفات + commit + retest + regression.
- **الحماية:** لا حذف وظائف، لا تغيير هوية/معمارية، لا أسرار في التقارير، تعديلات محدودة قابلة للرجوع (git).

## 3. مصفوفة التغطية (أنواع الاختبار × المكونات)
| النوع | الخدمات | الشاشات | قاعدة البيانات | التكامل | الأمن |
|---|---|---|---|---|---|
| Functional | API لكل خدمة (TC-SV*) | كل شاشة (TC-SC*) | عمليات CRUD/سلامة (TC-DB*) | F1–F5 | — |
| UI/UX | — | RTL/حالات فارغة/تحميل | — | — | — |
| API Testing | OpenAPI + حالات خطأ 4xx/5xx | — | — | — | محمية/غير محمية |
| Database | — | — | تكرار/ترتيب/اتساق | — | — |
| Integration | أقران + Redis | — | — | سيناريوهات S1–S6 | — |
| Security | JWT/PIN/RBAC | حماية مسارات | api_tokens | — | أسرار/اعتماديات |
| Performance | زمن استجابة مقاس | زمن تحميل مقاس | — | — | — |
| Reliability | S4 إسقاط/استعادة | — | — | — | — |
| Compatibility | — | عروض 1440/390 | — | — | — |
| Regression | pytest + node + Playwright بعد كل إصلاح | | | | |

## 4. حالات الاختبار
المرجع التنفيذي: `qa/TEST_CASES.md` (TC-AD*, TC-AU*, TC-MT*, TC-SC*, TC-SV*, TC-DB*, TC-E2E*, TC-SEC*, TC-PF*).
مصفوفة الشاشات: `qa/SCREEN_COVERAGE_MATRIX.md`. سجل العيوب: `qa/DEFECT_REGISTER.md`.

## 5. ترتيب التنفيذ الملزم
| # | المرحلة | المخرج | البوابة |
|---|---|---|---|
| 1 | اكتشاف معماري مستقل | SYSTEM_ARCHITECTURE_DISCOVERY_REPORT | ✅ منجز |
| 2 | جرد | SYSTEM_INVENTORY + DATA_FLOW_MAP | ✅ منجز |
| 3 | هذه الوثيقة + المصفوفات | Master Plan | ✅ منجز |
| 4 | Admin | Admin Validation | Pass مطلوب |
| 5 | المصادقة والتوكنات | API_TEST_REPORT §auth | Pass مطلوب |
| 6 | MT5 | MT5 Validation (BLOCKED موثق للجسر الحي + اختبار APIs المتاحة) | موثق |
| 7 | الشاشات | Screen QA (بجولة حية جديدة) | اجتياز |
| 8 | المكونات والخدمات | COMPONENT_QA_REPORT | كل خدمة مصنفة |
| 9 | قاعدة البيانات | DATABASE_VALIDATION_REPORT | إثبات سلامة |
| 10 | E2E | E2E_TEST_REPORT | سيناريوهات S1–S6 |
| 11 | أمن/أداء/استقرار | SECURITY + PERFORMANCE | قياسات |
| 12 | البنود المعلقة (rate limiter + risk_rules) | Closure | إغلاق أو توثيق تعذر |
| 13 | Playwright | PLAYWRIGHT_AUTOMATION_REPORT | مجموعة قابلة للتشغيل |
| 14 | انحدار نهائي | pytest+node+Playwright | اجتياز |
| 15 | اعتماد | FINAL_ACCEPTANCE_REPORT + HANDOFF | ✋ |

**سجل تنفيذ فوري (مساء 2026-11-04):** أُصلحت D10 (826eecb + تحصين 5921635) وD12 وD13 (عزل اختبار — 5921635) أثناء إعداد الوثائق؛ الانحدار المرتبط: **555/555 PASS** (test_api كاملاً). التفاصيل في DEFECT_REGISTER §أ/§ج.
**سجل تنفيذ (2026-11-04 ليلًا):** المرحلة 6 (MT5) منفذة — TC-MT-02 **7/7 PASS حي** (توكن/ربط/409/poll/إبطال 401 فوري)، TC-MT-03 **PASS** (اتساق EA↔OpenAPI↔وثيقة شامل: LIMIT 20، INTERVAL 5 MINUTE، journal replay)، TC-MT-04 **PASS** (9007 حي: broker=paper، real_broker_execution_enabled=false)، TC-MT-01 **BLOCKED** (لا MT5 terminal في الصندوق). لا عيوب جديدة. الأدلة: `qa/evidence/tc_mt_results.json`.

## 6. معايير القبول
- صفر عيوب Critical/High مفتوحة.
- تغطية = منفذ/المعتمد × 100 مع فصل PASS/FAIL/BLOCKED/NOT TESTED (لا حذف فاشل من المقام).
- سيناريوهات E2E الأساسية ناجحة؛ المصادقة/RBAC ناجحة؛ سلامة DB مثبتة؛ Playwright قابل للتشغيل؛ HANDOFF محدث؛ تقرير نهائي بأدلة.
- البنود المتعذرة (جسر MT5 الحي) موثقة بأسبابها ومتطلباتها.

## 7. إدارة الأدلة
لقطات: `docs/screenshots/…` (الجولات السابقة) + `qa/evidence/` (استجابات/قياسات هذه الدورة). كل ادعاء في التقارير مرتبط بدليل ملف أو استجابة مسجلة.
