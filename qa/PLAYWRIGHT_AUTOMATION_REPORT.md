# PLAYWRIGHT AUTOMATION REPORT — NEXUS TRADER MT5 (المرحلة 13 من M.2)

> التاريخ: 2026-11-04 ليلًا. المجموعة القابلة للتشغيل: **`qa/playwright/run_suite.py`** (مستودعية، بلا اعتماديات خارج pytest/runtime).
> المتطلبات: playwright+chromium لمفسّر التشغيل، المنظومة حية عبر `run.py --paper` (الداشبورد :3100)، بيانات `.env`.

## نتيجة التشغيل الفعلي (دليل اللحظة): **5/5 PASS**
أدلة: `qa/evidence/playwright_suite_results.json` + لقطات `docs/screenshots/playwright-suite/`

| الاختبار | ما يفحصه | النتيجة |
|---|---|---|
| T1_login_success | دخول حي → /nexus | **PASS** (5058ms dev) |
| T2_screens_zero_pageerrors | 14 شاشة محمية × صفر أخطاء JS صفحة + لقطة لكل شاشة | **PASS** (page_errors=0، tab_crashes=0) |
| T3_nexus_console_clean | كونسول /nexus (انحدار D16/D17): صفر أخطاء WS، صفر مفاتيح مكررة، صفر أخطاء أخرى؛ ضجيج 404 صادق-فارغ مسموح ومفصول | **PASS** (6×404 صادق فقط) |
| T4_anonymous_redirect | بلا جلسة → /login (حماية) | **PASS** |
| T5_mobile_390_login | 390×844 بلا أخطاء | **PASS** |

## قرارات تشغيلية موثقة داخل المجموعة
1. **TV OFF عبر مفتاح المنتج** (`nexus_tv_chart_enabled=0` في localStorage — ميزة D2 المشحونة من المالك): ويدجت TradingView الخارجي (WebGL) هو مصدر انهيار التبويب المهيمن داخل الصندوق؛ سلوكه الحي ON تم التحقق منه في جولة المرحلة 7.
2. **`--disable-dev-shm-usage --disable-gpu`**: حقن تثبيت كروم القياسي في الحاويات.
3. **تدوير الصفحات كل 3 شاشات**: الأطر الثقيلة تتراكم في السياق.
4. **فصل الانهيارات عن العيوب**: انهيار تبويب (ذاكرة الصندوق ~300MB حرة لحظة القياس) يُسجل بنداءً صريحاً ولا يُحسب خطأ JS للتطبيق — عدالة التصنيف.

## التشغيل
```bash
python3 qa/playwright/run_suite.py            # مخرج 0 عند نجاح الكل
QA_DASHBOARD_BASE=http://localhost:3100       # قابل للتجاوز
```
المخرجات: JSON بالنتائج + لقطات لكل شاشة + كود خروج ملائم لخط CI.

## البوابة
- مجموعة قابلة للتشغيل ومثبتة → المرحلة 14 (انحدار نهائي شامل).
