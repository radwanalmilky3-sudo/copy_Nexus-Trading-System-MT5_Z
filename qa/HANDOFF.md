# HANDOFF — NEXUS TRADER MT5 (M.2 → المالك/الدورة القادمة)

> محدث: 2026-11-05 فجرًا. الاعتماد: `qa/FINAL_ACCEPTANCE_REPORT.md` (CERTIFIED — PAPER ONLY). Git: `02ca08b`، شجرة نظيفة.

## 1) حالة المنظومة الآن
- 9 خدمات FastAPI (9000–9008) + dashboard (:3100 عبر run.py) + Redis 7.4.1 + DuckDB (62 جدولاً، كاتب وحيد) — كلها حية ومفحوصة (heal: redis/forwarder/dashboard/stack ok).
- paper-only مثبت بثلاث طبقات (env + run.py + executor حي: `real_broker_execution_enabled=false`).
- نافذة المعاينة: `http://localhost:3000` (ممرر خارجي → 3100)؛ **المدخل القياسي للدخول :3100** (منشأ :3000 غير مدرج في CORS — N3).

## 2) كيف تشغّل/تفحص
```bash
bash /home/z/my-project/scripts/nexus_heal.sh        # شفاء ذاتي (redis/forwarder/dashboard/stack)
python3 run.py --paper                               # إقلاع كامل عبر المشرف
python3 qa/playwright/run_suite.py                   # مجموعة UI (5/5) — مخرج 0 = نجاح
venv-nexus/bin/python -m pytest tests/test_api -q    # 555/555
```
- بيانات الدخول: مالك `redhwan` (كلمة المرور في `.env` — لا تُكتب في أي وثيقة).
- الأدلة: `qa/evidence/*.json`، اللقطات: `docs/screenshots/{round-m2-phase7,playwright-suite}/`.

## 3) ما أُنجز في M.2 (خلاصة تنفيذية)
- المراحل 1–15 كاملة: اكتشاف/جرد/خطة → Admin 5/5 → Auth 8/10 → MT5 3+BLOCKED → شاشات 17/17 → خدمات 9/9 → DB 7/7 → E2E 6+BLOCKED → أمن 5+NT → أداء كل العتبات → إغلاق البندين المعلقين → Playwright 5/5 → انحدار → اعتماد.
- إصلاحات موثقة بالجذر/الدليل/الانحدار: D10/D12/D13 (مساء)، **D16/D17/P2-2/P2-3/.env.example/rate-limiter** (هذه الدورة) — كلها FIXED-VERIFIED.
- المستندات الـ16 كلها موجودة في `qa/` (هذا الملف الـ16).

## 4) قرارات معلقة على المالك (بالتأثير التنازلي)
1. **D15**: إبطال خادمي للتوكن بعد logout (denylist Redis) أو تقصير exp أو قبول التصميم — أمني.
2. **D14**: إضافة `/api/v2/auth/refresh` أو قبول JWT وحيد 24h — ميزة.
3. **D6**: رفع حصة GLM/تباعد النداءات (الآن: fail-closed → NO_TRADE عند 429) — تشغيلي.
4. **D4/D5/D7**: نطاق ميزات (UI قواعد مخاطرة، إيقاف وكيل فعلي، async evaluate).
5. **D19**: دورة معالجة ديون الاختبارات الموروثة (39 pytest + 11 node — stubs/عقود متقادمة، لا عيوب إنتاج).
6. **D18**: تحديث العقد الذهبي `test_local_ai_factory_has_no_cloud_fallbacks` لواقع المزودين الحالي.
7. **N3**: إضافة منشأ :3000 لقائمة CORS أو إبقاء :3100 وحيداً.
8. **N5/P2-1/N1/N2/N4/N6**: تحصين رؤوس الأمان عند النشر، `next build` إنتاجي، حوار تأكيد EA، تحسينات نصية/شكلية.

## 5) المحجوب بيئياً ومتطلبات فكّه
| البند | المتطلب |
|---|---|
| جسر MT5 حي (TC-MT-01) | جهاز المالك: MT5 terminal + compile NexusBridgeEA.mq5 + WebRequest allowlist + توكن من تبويب جسر MT5 (خطوات `docs/EA_BRIDGE.md` كاملة) |
| S2 صفقة كاملة (TC-E2E-06) | تراكم شموع XAUUSD + تدريب النماذج عبر `bootstrap_ensemble.py` |
| pip-audit (TC-SEC-06) | بيئة بوصول لقاعدة CVE ثم `pip-audit -r requirements.txt` |

## 6) بنود ما بعد التسليم المقترحة (دورة قادمة)
1. معالجة D19 (stubs/عقود) لتصفير الانحدار الشامل.
2. رؤوس الأمان + TLS عند أي تعرض خارجي.
3. توحيد سلوك 404/غلاف-صفري عبر نقاط البيانات (N6).
4. بناء إنتاجي للداشبورد لخفض بصمة الذاكرة (~1GB dev → أصغر بكثير).

## 7) تنبيهات صيانة
- سكربت الشفاء يغطي الآن dashboard — لا تحذف فحصه.
- مفتاح TV (`nexus_tv_chart_enabled`) ميزة رسمية لثبات الصندوق — المجموعة تثبته OFF تلقائياً.
- عند أي تعديل على `login`: الحارس `login_rate_guard` يعتمد Redis؛ سقوط Redis لا يعطل الدخول (fail-open مقصود وموثق).
- لا تجبر أي عملية على المنافذ يدوياً — استخدم run.py (D9).
