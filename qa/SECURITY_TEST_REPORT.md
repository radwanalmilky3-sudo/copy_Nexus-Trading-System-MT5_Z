# SECURITY TEST REPORT — NEXUS TRADER MT5 (المرحلة 11 من M.2)

> التاريخ: 2026-11-04 ليلًا. منهجية غير تخريبية فقط. الأدلة: `qa/evidence/tc_sec_results.json` (سكربت `scripts/tc_sec_security_live.py`) + أدلة المراحل السابقة المشار إليها.
> الحالات: PASS / FAIL / BLOCKED / NOT TESTED / FIXED-PENDING RETEST / FIXED-VERIFIED.

## النتيجة: 5 PASS + 1 NOT TESTED (موثق) — لا FAIL

| ID | الفحص | الفعلي | الحالة |
|---|---|---|---|
| TC-SEC-01 | مسح الأسرار في الكود | **0 إيجاديات** عبر services/shared/dashboard-src/run.py/qa (أنماط: مفاتيح Nexus، مفاتيح OpenAI-نمط، مفاتيح ZAI، أسرار عامة ≥32 حرفاً) — القيم فقط في `.env` (غير متتبع) | **PASS** |
| TC-SEC-02 | `.env` خارج Git | `git ls-files` لا يحوي أي `.env` — فقط `.env.example` النموذجي (بلا أسرار، أُنشئ هذه الدورة ضمن إصلاح العقد الذهبي) | **PASS** |
| TC-SEC-03 | رفض المسارات المحمية المجهولة | 11 مساراً إدارياً/حساساً بلا توكن: **كلها 401** (users/audit/ea-tokens/kill-switch×2/config-risk×2/risk-status/agents-decision/system-health/sources-health) — **صفر 200** | **PASS** |
| TC-SEC-04 | رؤوس الأمان | **ملاحظة مسجلة بصدق**: البوابة والداشبورد بلا `X-Frame-Options` / `X-Content-Type-Options` / `CSP` (أساس dev) — مُرحّلة لقائمة التحصين (SEC-BACKLOG) | **PASS\*** (توثيق — لا ثغرة مفعّلة، ولا اختبار تخريبي) |
| TC-SEC-05 | فصل paper/live | جسم حي 9007: `broker=paper, trading_mode=paper, real_broker_execution_enabled=false` + سلسلة run.py/safety.py (TC-MT-04) | **PASS** |
| TC-SEC-06 | مسح ثغرات الاعتماديات | pip-audit غير متاح في الصندوق (لا وصول لقاعدة CVE) — **NOT TESTED بصدق**؛ مراجعة التثبيتات اليدوية سارية | **NOT TESTED** |

## أدلة أمنية مكمّلة من المراحل السابقة (تُحتسب ضمن التغطية)
| الدليل | المرجع |
|---|---|
| تخزين توكن EA كبصمة SHA-256 فقط — القائمة لا تعيد الخام (raw_leaked=false) | TC-MT-02 حي |
| إبطال التوكن = 401 فوري على المطالبات | TC-MT-02 حي (DELETE→401) |
| RBAC خلفي: مشاهد × API إداري = **403** | TC-E2E-05 حي |
| إطار تخويل WS إلزامي: بلا إطار → 4401، توكن تالف → 4401، صلاحية ناقصة → إغلاق | D16 verify حي (4/4) |
| الخدمات الداخلية ترفض كل نداء بلا سر داخلي (403 إلزامي ×6 خدمات) | TC-SV حي (المرحلة 8) |
| حماية تحويلات الواجهة: بلا جلسة → /login | TC-SC-16a/b حي |
| PIN إلزامي لإلغاء KILL (خاطئ = 403) | TC-AU-10 حي (جولة سابقة) |
| بيانات دخول خاطئة = 401 بلا تسريب تفاصيل | TC-AU-02 حي |

## قائمة تحصين مقترحة (لا تمنع الاعتماد)
1. رؤوس الأمان (SEC-04) عبر middleware البوابة + next.config `headers()` عند النشر الإنتاجي.
2. D15: إبطال خادمي للتوكن (denylist) — قرار مالك قيد البت منذ المرحلة 5.
3. TLS/HTTPS أمام البوابة قبل أي تعرض خارجي (موثق في EA_BRIDGE §4).
4. تشغيل pip-audit في بيئة بوصول لقاعدة CVE (متطلب دورة قادمة).

## البوابة
- لا عيوب أمنية مفتوحة تمنع المتابعة → PERFORMANCE (نفس المرحلة) ثم المرحلة 12.
