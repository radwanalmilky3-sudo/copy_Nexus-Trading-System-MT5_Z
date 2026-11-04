# 🐞 DEFECTS — سجل عيوب اختبار الشاشات (يُحدَّث مع كل جولة)

> وفق TEST_PLAN.md §8: هذا الملف ← إصلاح ← اختبار انحدار ← تقرير PDF نهائي.
> آخر تحديث: 2026-11-04 — الجولة 1 (P0).

## الجولة 1 — P0 (فحص تحميل كل شاشة) — 2026-11-04

**المنهجية**: متصفح آلي (agent-browser 0.41.1، viewport 1440×900، عبر بروكسي :3000)
— زيارة كل مسار من الجرد (18 مسارًا)، لقطة لكل شاشة، جمع أخطاء الصفحة والكونسول
وسجل نداءات الشبكة عبر DevTools.

**النتيجة الإجمالية: 16/16 شاشة P0 ناجحة — صفر أخطاء صفحة، صفر أخطاء كونسول.**

| # | الشاشة | المسار | تحميل | PageErrors | ConsoleErrs | لقطة |
|---|---|---|---|---|---|---|
| 1 | الدخول | `/login` (عبر `/`→307) | ✅ | 0 | 0 | 01_login.png |
| 2 | لوحة القيادة | `/nexus` | ✅ | 0 | 0 | 03_dashboard_nexus.png |
| 3 | الاستراتيجيات | `/nexus/strategies` | ✅ | 0 | 0 | 04_strategies.png |
| 4 | النماذج | `/nexus/models` | ✅ | 0 | 0 | 05_models.png |
| 5 | نماذج ML | `/nexus/ml-models` | ✅ | 0 | 0 | 06_ml_models.png |
| 6 | مقارنة النماذج | `/nexus/model-comparison` | ✅ | 0 | 0 | 07_model_comparison.png |
| 7 | السجل | `/nexus/history` | ✅ | 0 | 0 | 08_history.png |
| 8 | جسر MT5 | `/nexus/ea-bridge` | ✅ | 0 | 0 | 09_ea_bridge.png |
| 9 | الإعدادات | `/nexus/settings` | ✅ | 0 | 0 | 10_settings.png |
| 10 | متابعة التطوير | `/nexus/progress` | ✅ | 0 | 0 | 11_progress.png |
| 11 | تقدم التدقيق | `/nexus/audit-progress` | ✅ | 0 | 0 | 12_audit_progress.png |
| 12 | التعلم العميق | `/nexus/deep-learning` | ✅ | 0 | 0 | 13_deep_learning.png |
| 13 | التعلم المعزز | `/nexus/reinforcement-learning` | ✅ | 0 | 0 | 14_reinforcement_learning.png |
| 14 | مختبر البحث | `/nexus/research-lab` | ✅ | 0 | 0 | 15_research_lab.png |
| 15 | التحليلات | `/analytics` | ✅ | 0 | 0 | 16_analytics.png |
| 16 | الحماية `/history` العامة | تحويل إلى `/nexus/history` | ✅ | 0 | 0 | 17_public_history.png |
| 17 | الحماية `/settings` العامة | تحويل إلى `/nexus/settings` | ✅ | 0 | 0 | 18_public_settings.png |

### نداءات الشبكة (22,968 طلبًا مُتتبعًا)
- **22,002 × 200** — سليم.
- **800 × 404** — نوعان فقط، كلاهما **حالة "لا بيانات بعد" موثقة وليست عيبًا**:
  - `GET /api/v2/market/candles?...count=1` → `{"detail":"Historical market data not found"}` — قاعدة DuckDB جديدة فارغة؛ تُشفى تلقائيًا مع تراكم الشموع.
  - `GET /api/agents/decision/XAUUSD` → `{"detail":"No decision yet for this symbol"}` — خط الوكلاء `pipeline_state=offline` (ZAI_API_KEY فارغ عمدًا، fail-closed).
- **16 × 401** — حدث واحد فقط (اختبار كلمة مرور خاطئة **المتعمد** S5 الجزئي) يظهر مكررًا في تتبع كل شاشة.

### ملاحظات موثقة (ليست عيوب)
| # | الملاحظة | التصنيف | القرار |
|---|---|---|---|
| N1 | لافتة `services offline — trading paused 3` على /nexus رغم سلامة الخدمات | سلوك fail-closed صحيح: 3 شروط غير مستوفاة على قاعدة جديدة (لا شموع، نماذج غير مدرّبة `is_fitted=false`، وكلاء offline بغياب ZAI_API_KEY) | يُقبل؛ تحسين نصي اختياري P2 (صياغة "بانتظار البيانات/التدريب/مفتاح الذكاء") |
| N2 | شريط علوي `DEMO` + BAL $10,000 وPAPER | مقصود (وضع العرض الورقي) | يُقبل |
| N3 | رسالة المالك داخل لوحة P&L تظهر بخط صغير مقروء | تنسيق | P2 تجميلي اختياري |

### عيوب مفتوحة حرجة
**لا يوجد.**

### عيب تم إصلاحه في هذه الجولة
| # | العيب | الجذر | الإصلاح | التحقق |
|---|---|---|---|---|
| D1 | nexus-api (9000) لا يقلع: `ModuleNotFoundError: No module named 'jwt'` | `requirements.txt` يغفل PyJWT بينما `middleware/auth.py` يستورده مباشرة (كان يُثبَّت مسبقًا كاعتماد جانبي في بيئة قديمة) | إضافة `PyJWT>=2.9.0,<3.0` إلى requirements.txt + تثبيته في venv | إقلاع كامل + 9000=200 + دخول 200 |

## الجولة 2 — P1 (الوظائف: كل زر/نموذج + سيناريوهات S1–S5) — **قادمة**
- النطاق: أزرار لوحة القيادة، نماذج الإعدادات، إنشاء/إلغاء توكن EA، التحقق من عدم الإرسال المزدوج، S5 خروج/دخول كامل، S4 إيقاف خدمة وتدهور رشيق.
- المعيار: TEST_PLAN.md §4 طبقات D وE + §6.
