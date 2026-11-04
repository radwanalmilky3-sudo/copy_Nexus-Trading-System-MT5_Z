# HANDOFF — حالة مشروع Nexus Trader MT5 (تُحدَّث مع كل مرحلة)

> آخر تحديث: 2026-11-04 (بعد commit `118d201` — بعد استعادة كاملة من إعادة تدوير عميقة للصندوق)
> الهدف: أي جلسة جديدة تكمل من هنا دون إعادة نقاش.

## 1. ما هو المشروع
نظام تداول ذاتي (XAUUSD/BTCUSD) على MetaTrader 5 — 10 خدمات مجهرية Python/FastAPI
+ داشبورد Next.js 14 + Redis + DuckDB. يعمل حاليًا **Paper Trading** في بيئة عرض (sandbox).

## 2. التشغيل السريع
- المستودع: `/home/z/my-project/Nexus-Trading-System-MT5` (بحروف كبيرة — remote: radwanmhh-svg/Nexus-Trading-System-MT5)
- البيئة الافتراضية: `/home/z/venv-nexus`
- الإقلاع: `run.py --services nexus-data,nexus-features,nexus-agents,nexus-risk,nexus-executor,nexus-monitor,nexus-api --paper --skip-preflight --no-frontend`
- المنافذ: 9000 api | 9004 agents | 9001 data | 3100 dashboard مباشر | 3000 بروكسي | Redis 6379
- الشفاء الذاتي: `scripts/nexus_cron_heal.sh` كل 5 دقائق (Job 500811) — يطبع سطر HEAL_STATUS
- LLM: Z.ai سحابي `glm-4.5-flash` (`NEXUS_LLM_PROVIDER=zai` في `.env` المحلي — لا يُرفع أبدًا)

## 3. قاعدة دائمة (PROJECT_RULES)
**كل تعديل → git commit + push إلى origin main برسالة وصفية واضحة.**

## 4. الحسابات
| الحساب | الحالة |
|---|---|
| `redhwan` | **المالك** — Super Admin، نشط، سجل دخول ناجح (2026-11-03 23:23 UTC) |
| `admin` | تجريبي قديم (Demo Admin) — مرشح للتعطيل عند طلب المالك |
| `NEXUS_ADMIN_PIN` | `tyj95abn` (أُعيد توليده بعد فقد `.env` القديم — يقرأ من `.env` المحلي) |
| bootstrap | مُغلق عمدًا (`bootstrap_user_count = 2`) — أي محاولة تعطي 409 بشكل صحيح |

## 5. آخر ما أُنجز (حتى `d8b0618`)
- ✅ `3677de3` نقل الداشبورد من `/dashboard` إلى `/nexus` (كسر حلقة توجيه)
- ✅ `4d6adc4` إصلاحا تدقيق حرجان: حاجز العقلين fail-closed + original_size
- ✅ `693e425` + `e040bbe` موفّر Z.ai السحابي + توحيد موديل الوكلاء في الوضع السحابي
- ✅ `d8b0618` رسائل خطأ عربية ودّية في صفحة الدخول (كانت JSON خام — سبب "الرفض" المُبلغ)
- ✅ تشخيص كامل لقصة إنشاء الأدمن: حساب المالك موجود ويعمل؛ 409 كان سلوكًا صحيحًا

## 6. قائمة التنفيذ المتفق عليها (بالترتيب)
1. 🔴 ~~إصلاح إنشاء الأدمن~~ — **منجز** (d8b0618)
2. 📄 ~~حفظ TEST_PLAN.md + HANDOFF.md~~ — **منجز** (هذه الوثيقة)
3. ✅ ~~نظام API Token للـ EA~~ — **منجز** (`118d201`): جداول api_tokens/ea_commands، نقاط /api/admin/ea-tokens (create/list/revoke)، /api/ea/handshake، /api/ea/poll — مُختبر كاملًا على النظام الحي (إنشاء→مصافحة→مطالبة→تنفيذ→idempotency→إلغاء→401)
4. 🔴 **جسر MT5 (التالي)**: كتابة الإكسبيرت MQL5 (WebRequest إلى /api/ea/handshake ثم /api/ea/poll كل 3 ث، OnTimer، تنفيذ الأوامر OrderSend/modify/close، إعادة تقارير النتائج)، ثم ربط nexus-executor بكتابة أوامر في ea_commands، ثم شاشة توكنات في الداشبورد
- ⚠️ مفتاح ZAI_API_KEY فارغ حاليًا (فُقد مع .env القديم) — الوكلاء يعملون بقوالب احتياطية حتى يوفر المالك مفتاحًا جديدًا
5. 🖥️ جولات اختبار الشاشات وفق `TEST_PLAN.md` (الجرد أولًا) + تقرير بالصور + Playwright
6. 🟡 معلّقان بقرار المالك: توصيل rate limiter فعليًا + تشديد `risk_rules.yaml`

## 7. أمان (تذكيرات مستمرة)
- المالك سرّب مفاتيح في المحادثة سابقًا (GitHub PAT + Z.ai key) — يجب تدويرهما وإبقاؤهما في `.env` فقط
- لا تكتب أسرار في الكود أو السجلات أو مهام مجدولة

## 8. ملاحظات بيئة
- الصندوق الرملي قد يتعطل مؤقتًا (فشل إقلاع لدى المنصة) — الملفات تبقى محفوظة؛ أعِد المحاولة لاحقًا
- 9004 يرجع 503 عابرًا عند 429 من Z.ai المجاني — المُفصِّل المدمج يتعافى خلال 120 ث
