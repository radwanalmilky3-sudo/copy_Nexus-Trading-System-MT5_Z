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
**سجل تنفيذ (2026-11-04 ليلًا 2):** المرحلة 7 (الشاشات) منفذة — **17/17 PASS** بعد إصلاحين فوريين اكتشفتهما الجولة: **D16** (قناة WS broadcast مفقودة خادمياً + عميل بمسار/تخويل خاطئين → موجّه `/ws/broadcast` جديد + إطار تخويل؛ تحقق حي 4/4 + انحدار 555/555) و**D17** (تصادم معرّف cal-ui → مفاتيح React مكررة؛ إدراج currency + إثبات وحدة + إعادة قياس صفر تحذيرات). أُصلحت كذلك فجوة موروثة: إنشاء `.env.example` (عقد القيم الآمنة). أُسجّل D18 (عقد ذهبي متقادم — قرار مالك) وملاحظات N3/N4/N5 (CORS للمنشأ :3000، ضجيج 404 صادق، سقوط dashboard — أُضيف فحصه لسكربت الشفاء). P2-3 أُغلقت كـD17 بعد تصحيح الإسناد (القنص أثبت أن مصدر التحذيرات NewsFeed لدينا لا TradingView). الأدلة: `qa/evidence/tc_sc_results.json` + `d16_ws_broadcast_results.json` + لقطات `docs/screenshots/round-m2-phase7/`.
**سجل تنفيذ (2026-11-04 ليلًا 3):** المرحلة 8 (المكونات) منفذة — **TC-SV 9/9 PASS** حي (health + OpenAPI + نداء وظيفي من OpenAPI الفعلي + حالة خطأ)؛ نمط أمني مثبت: 403 إلزامي على كل نداء داخلي بلا سر. **P2-2 أُصلحت أثناء المرحلة (FIXED-VERIFIED)**: news كانت تدوس النبضة بسلسلة خام + monitor بلا نبضة ذاتية → SystemHealth للطرفين، إعادة إقلاع عبر المشرف، والتحقق الحي بعد دورة كاملة: news/monitor = healthy (data degraded وagents unhealthy حالتان صادقتان موروثتان — mt5_ok=false / مزود LLM). المخرج: `qa/COMPONENT_QA_REPORT.md` + أدلة `qa/evidence/tc_sv_results.json`. ملاحظة N6 (غلاف صفري لـdata/flow).
**سجل تنفيذ (2026-11-04 ليلًا 4):** المراحل 9–11 منفذة — **قاعدة البيانات 7/7 PASS** (نسخة معزولة؛ 62 جدولاً/65 PK؛ 43 نشطاً+10 محذوفون منطقياً بتصميم؛ صفر تكرارات؛ رفض القفل = إثبات الكاتب الوحيد) — `qa/DATABASE_VALIDATION_REPORT.md`. **E2E: 5 PASS + 1 BLOCKED** (S1 fail-closed، S3 pause/reset، S5 بسلوك D15، S6 RBAC 403 — بعد تصحيح خلل قراءة استجابة في سكربت الاختبار وتنظيف 3 مستخدمي QA؛ S2 قاعدة صفرية) — `qa/E2E_TEST_REPORT.md`. **الأمن 5 PASS + 1 NOT TESTED صادق** (صفر أسرار، 11×401، paper-only، رؤوس مفقودة موثقة كتحصين) + **الأداء: كل العتبات مستوفاة** (health 6–235ms، login 57ms avg، شاشات 556–1444ms، dashboard 1GB RSS = جذر N5) — تقريرا المرحلة 11. **المرحلة 12 مغلقة**: rate limiter منفذ ومتحقق حياً (429/Retry-After) + risk_rules متسق-أكثر-تحفظاً (توثيق).

## 6. معايير القبول
- صفر عيوب Critical/High مفتوحة.
- تغطية = منفذ/المعتمد × 100 مع فصل PASS/FAIL/BLOCKED/NOT TESTED (لا حذف فاشل من المقام).
- سيناريوهات E2E الأساسية ناجحة؛ المصادقة/RBAC ناجحة؛ سلامة DB مثبتة؛ Playwright قابل للتشغيل؛ HANDOFF محدث؛ تقرير نهائي بأدلة.
- البنود المتعذرة (جسر MT5 الحي) موثقة بأسبابها ومتطلباتها.

## 7. إدارة الأدلة
لقطات: `docs/screenshots/…` (الجولات السابقة) + `qa/evidence/` (استجابات/قياسات هذه الدورة). كل ادعاء في التقارير مرتبط بدليل ملف أو استجابة مسجلة.
