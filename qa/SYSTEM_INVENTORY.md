# SYSTEM INVENTORY — NEXUS TRADER MT5 (M.2)

> 2026-11-04 — جرد فعلي مطابق للكود والحالة الحية. المصدر الأعم: `qa/SYSTEM_ARCHITECTURE_DISCOVERY_REPORT.md`

## 1. الخدمات المستقلة (9 — كلها حية وقت الجرد)
| # | الخدمة | المنفذ | مسارات API | مسؤولية | صحة |
|---|---|---|---|---|---|
| 1 | nexus-api | 9000 | 165 | بوابة + مصادقة + WS | 200 |
| 2 | nexus-data | 9001 | 26 | استيعاب + كتابة DuckDB + جودة | 200 |
| 3 | nexus-features | 9002 | 4 | ميزات فنية | 200 |
| 4 | nexus-ml | 9003 | 19 | نماذج + traders | 200 |
| 5 | nexus-agents | 9004 | 14 | وكلاء + قرار | 200/503 ديناميكي (LLM-probe) |
| 6 | nexus-news | 9005 | 8 | أخبار + أساسي | 200 |
| 7 | nexus-risk | 9006 | 9 | مخاطرة | 200 |
| 8 | nexus-executor | 9007 | 6 | تنفيذ تجريبي | 200 |
| 9 | nexus-monitor | 9008 | 6 | مراقبة | 200 |

**إجمالي مسارات API: 257** (المرجع: openapi.json الحي لكل خدمة — النسخ محفوظة في `qa/evidence/openapi_*.json` عند الحاجة).

## 2. شاشات الواجهة (16)
| # | الشاشة | المسار | المكونات البارزة |
|---|---|---|---|
| 1 | الدخول | `/login` | نموذج، رسائل عربية، حماية نقر مزدوج |
| 2 | لوحة القيادة | `/nexus` | 10 تبويبات + ~30 نافذة (AgentConsole, RiskMonitor, PLDashboard, LiveChart(D2-fix), SystemHealth, NewsFeed…) |
| 3 | الاستراتيجيات | `/nexus/strategies` | جدول + فلترة |
| 4 | النماذج | `/nexus/models` | بطاقات نماذج |
| 5 | نماذج ML | `/nexus/ml-models` | حالة التدريب |
| 6 | مقارنة النماذج | `/nexus/model-comparison` | جداول مقارنة |
| 7 | السجل | `/nexus/history` | CSV + فلترة |
| 8 | جسر MT5 | `/nexus/ea-bridge` | إدارة توكنات EA (نشط/ملغى) |
| 9 | الإعدادات | `/nexus/settings` | بروكر/إشعارات/مصادر — بلا أسرار في DOM |
| 10 | متابعة التطوير | `/nexus/progress` | جدول هرمي |
| 11 | تقدم التدقيق | `/nexus/audit-progress` | مراحل + أدلة |
| 12 | التعلم العميق | `/nexus/deep-learning` | |
| 13 | التعلم المعزز | `/nexus/reinforcement-learning` | |
| 14 | مختبر البحث | `/nexus/research-lab` | مصادر/تشغيلات/جداول |
| 15 | التحليلات | `/analytics` | |
| 16 | الحماية العامة | `/history`,`/settings` → تحويل للـnexus | إعادة توجيه سليمة |

## 3. قاعدة البيانات (DuckDB — 58 جدولاً)
**مجموعات الجداول:** مصادقة (app_users, app_roles, app_role_permissions, app_user_roles, api_tokens, user_audit_log…)، سوق (ohlcv, ticks, market_series_observations, data_vintages…)، صفقات (trades, positions, ea_commands…)، أساسي (fund_* 20+، central_bank_events، event_asset_impacts…)، جودة (quality_runs, quarantine, lineage…)، إخبارية (news_*)، نماذج (model_evaluations…)، تنبيهات (alert_delivery_log…).
**الحالة الفعلية 2026-11-04:** مستخدمون 1 (redhwan — مالك)، أدوار 7، صلاحيات 36، api_tokens 1، تدقيق مستخدم 4، أساسي جزئي (asset_factor_profiles 67، fund_events 20، fund_sources 25، event_asset_impacts 24…)، **سوق/صفقات = 0** (قاعدة جديدة — التراكم تلقائي؛ موثق كحالة صحيحة لا عيب).
**المفاتيح:** PK في كل جدول؛ FK منطقية على مستوى الكود (DuckDB بلا إنفاذ FK صريح في المخطط الحالي — موثق في تقرير قاعدة البيانات).

## 4. Redis (123 مفتاحاً)
`nexus:*` (112): شموع/ميزات/صحة/قرارات/قفل kill-switch/إعدادات. `stream:*` (11): أحداث. الاستخدام: cache + pub/sub + قوائم EA.

## 5. الاختبارات الموجودة
- **pytest:** 184 ملفاً في 14 مجالاً (tests/test_agents, test_api, test_data, test_executor, test_features, test_fundamental, test_ml, test_monitor, test_news, test_risk, test_shared, test_qa + عقود).
- **Node:** 27 ملف .mjs لعقود الواجهة (dashboard/tests).
- **متصفح:** جولات 1–3 موثقة بلقطات (docs/screenshots) — Playwright الرسمي = مخرج هذه الدورة.

## 6. أدوات CLI (16)
bootstrap_ensemble, preflight, diagnose_pnl, mt5_diagnose, mt5_sym_check + scripts/ (apply_schema, rebuild_database, smoke_isolated_services, ui_walkthrough, …).

## 7. مكونات غير قابلة للتشغيل هنا
- **جسر MT5 الحي** (EA على طرف المالك) — BLOCKED، متطلباته في docs/EA_BRIDGE.md.
- Windows launchers (bat/cmd) — NOT VERIFIED هنا (ليست فشلاً).
- `_check_db.py` — ميت (مسار ويندوز مقعد). `start_all.py` — غلاف deprecated يفوّض لrun.py.

## 8. الهوية البصرية
داكن + أزرق/بنفسجي نيون، RTL عربي كامل، خطوط النظام، NeonCard/NeonGauge/PulseIndicator — **محمية: أي إصلاح بصري محدود بالخلل المكتشف فقط**.
