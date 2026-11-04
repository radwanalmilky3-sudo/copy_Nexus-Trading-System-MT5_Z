# DATA FLOW MAP — NEXUS TRADER MT5

| البند | القيمة |
|---|---|
| الوثيقة | DATA_FLOW_MAP.md (وثيقة 4/16 ضمن برنامج M.2) |
| التاريخ | 2026-11-04 (UTC) |
| المنهجية | ربط كل أنبوب بمنتجِه ومستهلكِه من الشيفرة (`RedisStream.*`, `xadd`, `xreadgroup`, `publish_event`) + التحقق من الحالة الحية عبر `XLEN` |
| مصدر الثوابت | `shared/constants.py` سطور 166–190 (تعريف `RedisStream`) |
| نطاق | Paper Trading فقط (`nexus:system:auto_trade=false`) |

---

## 1. المخطط العام (من اليسار إلى اليمين)

```
[MT5/مصادر بيانات]                     (جسر حي: NOT VERIFIED — mt5=false حاليًا)
      │
      ▼
┌──────────────┐  stream:ticks    ┌────────────────┐ stream:features ┌──────────────┐
│ nexus-data   │─stream:ohlcv────▶│ nexus-features │────────────────▶│ nexus-ml     │
│ 9001         │                  │ 9002           │                 │ 9003         │
└──────▲───────┘                  └────────────────┘                 └──────┬───────┘
       │                                                                    │
       │ stream:trades:close (أرشفة)                              stream:signals / :autonomous
       │                                                                    ▼
       │                                                          ┌──────────────────┐
       │                                                          │ nexus-agents 9004│──▶ Z.ai LLM (خارجي، fail-closed)
       │                                                          │ عمال A0–A12      │
       │                                                          └──────┬───────────┘
       │                                              stream:agent:verdict (+analysis)
       │                                                                    ▼
       │                                                          ┌──────────────────┐
       └──────────────────────────────────────────────────────────│ nexus-risk 9006  │
                                        stream:trades:close(قراءة)│ بوابة المخاطر    │
                                                                  └──────┬───────────┘
                                              stream:risk:decision       │
                                                                  ▼      ▼
                                                ┌────────────────────────────┐
                                                │ nexus-executor 9007        │──▶ جسر MT5/EA (Paper-only)
                                                │ stream:orders/positions    │    real_broker_execution_enabled=false
                                                └────────────────────────────┘
       [نexus-news 9005]──stream:news:alert──▶ (مستهلكون: agents/risk عبر نوافذ الحجب)
       [nexus-api 9000]◀──REST/WS──▶[dashboard 3100] (المستخدم النهائي)
       [nexus-monitor 9008]◀──يقرأ مفاتيح health/metrics──▶[Telegram داخل الوحدة]
```

---

## 2. كتالوج الأنابيب (منتج → مستهلك — من الشيفرة)

| الأنبوب | المنتج (دليل سطر) | المستهلك (دليل سطر) | الحالة الحية (XLEN) |
|---|---|---|---|
| `stream:ticks` | nexus-data (main.py:174) | nexus-features (تحويل إلى OHLCV) | 0 — خامد بلا جسر حي |
| `stream:ohlcv` | nexus-data (main.py:528) | nexus-features (xreadgroup main.py:325–337) | 0 |
| `stream:features` | nexus-features (xadd main.py:461–462) | nexus-ml (xreadgroup main.py:644–647) | 0 |
| `stream:signals` | nexus-ml (xadd main.py:907–908) | nexus-agents (main.py:199, 286, 304) | 0 |
| `stream:signals:autonomous` | nexus-ml/traders_api.py:1362–1363 | (قناة إشارات مستقلة) | غير منشأة وقت الفحص |
| `stream:signals:dlq` | nexus-agents (DLQ main.py:305) | مراجعة يدوية | غير منشأة (سلوك سليم) |
| `stream:agent:analysis` | nexus-agents (publish_event main.py:588) | المراقبة/التتبع | غير منشأة |
| `stream:agent:verdict` | nexus-agents (publish_event main.py:622) | nexus-risk (main.py:968, 1085) | **4** (نشط — عمال idle يكتبون نبضات/أحكام) |
| `stream:risk:decision` | nexus-risk (main.py:991 رفض، 1074 قرار) | nexus-executor (main.py:648, 668) | 0 |
| `stream:orders` | nexus-executor (main.py:898, 1515) | executor داخليًا + dashboard عبر api | 0 |
| `stream:positions` | nexus-executor (main.py:909) | dashboard/risk | 0 |
| `stream:trades:close` | nexus-executor (main.py:992, 1608) | nexus-data (main.py:199, 213 أرشفة DuckDB) + nexus-risk (main.py:1159, 1200 idempotency) | 0 |
| `stream:news:alert` | nexus-news (main.py:393–394) | نوافذ حجب المخاطر/الأحكام | غير منشأة وقت الفحص |
| `stream:news:calendar` | nexus-news (ثابت) | نوافذ الحجب | غير منشأة |
| `stream:system:health` | nexus-ml (main.py:1144–1145) | مراقبة | غير منشأة |
| `stream:session:change` | (ثابت معرَّف) | — | غير مستخدم في المسح الحالي — يُعلَّم UNKNOWN جزئيًا |

> **قاعدة M.2**: الأطوال الصفرية ليست عيبًا بحد ذاتها — هي متسقة مع غياب جسر MT5 حي (لا شموع تصل). الخط الوحيد النشط هو أحكام العمال.

## 3. تدفقات مفاتيح Redis (حالة/ذاكرة)

| المفتاح/العائلة | الكاتب | القارئ |
|---|---|---|
| `nexus:health:<svc>` (8) | كل خدمة لنفسها (دورة نبض) | nexus-monitor + dashboard عبر api |
| `nexus:health:A0..A12` | nexus-agents (عمال) | monitor/dashboard |
| `nexus:strategy:item:*` + `index` | nexus-agents (كتابة حالة الجلسات — state-writer) | strategy/index قراءة، dashboard |
| `nexus:fundamental:*` (19) | nexus-features (fusion/macro/monetary/…) | nexus-ml، agents، dashboard |
| `nexus:cross_asset:*` | nexus-features | ml/agents |
| `nexus:risk:*` (7) | nexus-risk | executor، dashboard |
| `nexus:news:*` (5) | nexus-news | risk (blackout)، dashboard |
| `nexus:runtime:settings` (+last) | nexus-api (من الواجهة) | كل الخدمات (قراءة دورية) |
| `nexus:system:auto_trade` | nexus-api (مفتاح الواجهة) | executor/risk — **false حاليًا** |
| `nexus:stream:processed:*` | عمال agents (إلغاء تكرار state-writer) | العمال أنفسهم |
| `nexus:genai:*`, `nexus:correlation:matrix` | agents/features | dashboard |
| `nexus:monitor:metrics`, `nexus:alerts:log` | nexus-monitor | dashboard/Telegram |

## 4. مسارات الكتابة إلى DuckDB

| المسار | الجداول المتأثرة | ملاحظة |
|---|---|---|
| nexus-data ← `stream:trades:close` | trades, positions | **فارغة حاليًا** — لا إغلاق صفقات بلا جسر حي |
| nexus-data (استيعاب) | ohlcv, ticks, data_vintages, macro_releases, source_fetch_runs/health_history | fetch_runs 187/187 نشطة |
| nexus-api (إدارة المستخدمين) | app_users, app_roles, app_user_roles, app_role_permissions, user_audit_log, api_tokens | audit_log 56 حدثًا — سجل تدقيق حي |
| nexus-features/ml | fundamental_*, event_asset_impacts, gold_impact_predictions, prediction_reasoning_steps | 261/1305/783/2088 صفًا — خط الأساسيات حي |

## 5. التبعيات الخارجية

| التبعية | المستهلك | الحالة |
|---|---|---|
| Z.ai API (glm-4.5-flash) | nexus-agents | **تذبذب موثق**: OFFLINE 16:27 → ONLINE 16:31 (زمن 4.6–6.0s) — fail-closed يعطل الأحكام عند الغياب |
| جسر MT5 / EA | nexus-executor + nexus-data | NOT VERIFIED (mt5=false) — تدقيق حي في خطوة لاحقة |
| مصادر أنباء/بيانات (FED RSS, Treasury, IMF, CFTC, …) | nexus-news / nexus-data | fetch_runs حي (187)؛ التقويم `not_configured` (بلا جلسات) |
| Telegram | nexus-monitor (وحدة داخلية) | غير مختبر وظيفيًا في هذه الجولة |

## 6. تدفق الواجهة (dashboard ↔ الخدمات)

```
المستخدم → :3000 (مُمرِّر TCP) → :3100 next-server
   next-server → REST/WS → nexus-api :9000 → (JWT/قواعد app_users) → خدمات داخلية
   WS الحي: nexus-api يبث أحداث الأنابيب (signals/orders/positions/verdicts) للواجهة
```

## 7. مسارات الفشل (fail-closed / DLQ / حواجز)

| الحالة | السلوك الموثق |
|---|---|
| LLM غير متاح | 9004 يرفض ONLINE (503) — **لا أحكام بلا نموذج** (ملاحظ علنيًا 16:27) |
| إشارة مكررة/فاسدة | DLQ على `stream:signals:dlq` + مفاتيح idempotency (agents 286، risk 1159) |
| قرار مخاطر مرفوض | `stream:risk:decision` مع reject_event (risk 991) — لا يصل أمر تنفيذ |
| تنفيذ وسيط حقيقي | معطّل إلزاميًا: `real_broker_execution_enabled=false` (TC-MT-04) |
| سقوط redis | nexus_heal.sh يعيد تشغيله تلقائيًا (بروتوكول الشفاء: redis/forwarder/stack) |

## 8. بنود UNKNOWN في التدفق

| البند | الحالة |
|---|---|
| استخدام فعلي لـ `stream:session:change` | معرَّف كثابت، لا منتج/مستهلك ظهر في المسح — NOT VERIFIED |
| استهلاك `stream:news:alert` النهائي | المنتج موثق؛ المستهلك ضمن نوافذ الحجب يُدقق في خطوة تدقيق risk/news |
| تدفق WS الحي من 9000 للواجهة | بنية موثقة من run.py (NEXT_PUBLIC_WS_*)؛ الاختبار الوظيفي في خطوة E2E |

> نهاية الوثيقة 4/16 — التالية: SCREEN_COVERAGE_MATRIX.md وفق ترتيب M.2 بعد MASTER_QA_TESTING_REMEDIATION_PLAN.md.
