# API TEST REPORT — NEXUS TRADER MT5 (المرحلتان 5 و6 من M.2 + ملاحق المرحلة 8)

> التاريخ: 2026-11-04 ليلًا. البوابة الحية: `http://127.0.0.1:9000` (OpenAPI حي 165 مساراً). الأدلة: `qa/evidence/{tc_au_results.json, tc_mt_results.json, auth_login.json, phase12_rate_limit_results.json, d16_ws_broadcast_results.json, tc_sv_results.json}`.
> الحالات: PASS / FAIL / BLOCKED / NOT TESTED / FIXED-PENDING RETEST / FIXED-VERIFIED.

## 1) المصادقة والتوكنات — TC-AU (المرحلة 5): **8/10** (فشلان موثقان بقرار مالك)

| ID | الفحص | الفعلي الحي | الحالة |
|---|---|---|---|
| TC-AU-01 | دخول صحيح | 200 + JWT (165 حرفاً) + expiresAt | **PASS** |
| TC-AU-02 | كلمة مرور خاطئة | 401 + لا توكن في الجسم + تفصيل EN بالتصميم (i18n عند الواجهة — mapper مثبت) | **PASS** |
| TC-AU-03 | Bearer تالف | 401 | **PASS** |
| TC-AU-04 | بلا ترويسة | 401 | **PASS** |
| TC-AU-05 | توكن منته/ملغى | 401 | **PASS** |
| TC-AU-06 | تجديد refresh | **404 — لا endpoint** (تصميم JWT وحيد 24h؛ تناقض الوثائق صُحح في DATA_FLOW_MAP F5) | **FAIL موثق (D14)** |
| TC-AU-07 | خروج ثم استخدام القديم | 200 بعد logout (JWT عديم الحالة؛ مخفف: /me يرفض غير active فوراً) | **FAIL موثق (D15)** |
| TC-AU-08 | دورة توكن EA | إنشاء→نشط→إلغاء→ملغى (SHA-256 فقط) | **PASS** |
| TC-AU-09 | RBAC خلفي | مشاهد × API إداري = **403** (أعيد إثباته حياً في TC-E2E-05) | **PASS** |
| TC-AU-10 | PIN الحساسات | PIN خاطئ على kill-release = 403 | **PASS** |

## 2) APIs جسر MT5 — TC-MT-02 (المرحلة 6): **7/7 PASS حي**
إنشاء توكن (`POST /api/admin/ea-tokens` → raw `nexus_ea_` مرة واحدة) → القائمة بلا خام (بصمة SHA-256 فقط، raw_leaked=false) → handshake يربط الهوية (200 + user=redhwan + heartbeat=3 + protocol=1) → هوية ثانية بنفس التوكن = **409** → poll (200 + commands[] + server_time) → طابور الأوامر (200) → إبطال `DELETE /api/admin/ea-tokens/{id}` (200) ثم poll = **401 فوري**.
الجسر الحي على طرف المالك: **BLOCKED** (TC-MT-01 — يتطلب MT5 terminal؛ كل الطرف الخادمي مختبر).

## 3) اختبار API أثناء الدورة (ملاحق)
| الفحص | النتيجة | المرجع |
|---|---|---|
| حارس معدل النداءات على login (بند معلق مُغلق) | انفجار 15 دخولاً خاطئاً → 401×12 ثم **429 + Retry-After:60**؛ شرعي 200 بعد تنظيف النافذة | phase12_rate_limit_results.json |
| قناة WS الجديدة `/ws/broadcast` (D16) | تخويل إطار JWT (auth ok) + توصيل بث حقيقي (PUBLISH→frame) + رفض 4401/4401 | d16_ws_broadcast_results.json (4/4) |
| مسح المسارات المحمية المجهولة | 11 مساراً إدارياً/حساساً بلا توكن = **401 كلها** (صفر 200) | tc_sec_results.json (SEC-03) |
| نداءات وظيفية عبر OpenAPI الفعلي (9 خدمات) | 200 وظيفي حيث العام + **403 إلزامي** على الخدمات الداخلية بلا سر | tc_sv_results.json (المرحلة 8) |
| 404 صادق-فارغ | candles/agents-decision/معرفات زائفة → 404 بلا بيانات مفبركة | tc_sv + tc_sc |

## 4) ملاحظات API مسجلة
- **N2**: تفاصيل الأخطاء بالإنجليزية من الطبقة الخادمية بالتصميم (i18n عند الواجهة) — لا إجراء إلا برغبة مالك.
- **D7**: `POST /api/agents/evaluate` متزامن → 502 بعد ~15s والدورة تكتمل لاحقاً (نمط async = تحسين مستقبلي).
- **N6**: `/api/data/flow/{symbol}` يرد 200 بغلاف صفري صادق (`bars_analyzed:0`) لرموز غير معروفة — توحيد مستقبلي مقترح.

## الخلاصة
- المصادقة/RBAC/حماية المسارات: **مثبتة حياً** مع فشلين تصميميين مسجلين بقرار مالك (D14/D15) — لا يُحسبان نجاحاً.
- APIs الجسر: **مثبتة حياً بالكامل** من طرف الخادم.
- لا عيوب API مفتوحة تمنع الاعتماد الورقي (التفاصيل في DEFECT_REGISTER).
