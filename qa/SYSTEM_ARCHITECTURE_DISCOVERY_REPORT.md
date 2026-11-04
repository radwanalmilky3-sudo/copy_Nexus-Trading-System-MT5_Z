# SYSTEM ARCHITECTURE DISCOVERY REPORT — NEXUS TRADER MT5

> **الإصدار:** 1.1 (M.2) — 2026-11-04 (تحديث مسائي بأدلة مُعاد التحقق)
> **المنهجية:** اكتشاف مستقل من المستودع الفعلي + OpenAPI الحي + العمليات الجارية — **بلا افتراض مسبق لعدد الخدمات**.
> **أدلة الاكتشاف:** `ps`/`ss` (عمليات حية)، `curl /openapi.json` ×9 (مسارات API الحقيقية — **مُعاد عدّها مساءً: 257 ✔**)، `curl /health` ×10، نسخة DuckDB معزولة (**62 جدولاً مع عدّ الصفوف**)، جرد Redis (**129 مفتاحاً** + أطوال الـstreams)، قراءة run.py/main.py، مسح الاستيرادات، جرد dashboard (18 ملف مسار).
> **درجة الثقة العامة:** عالية لكل ما وُسم (تم التحقق الحي)؛ متوسطة لتفاصيل الأنظمة الفرعية الداخلية (من قراءة الكود دون اختبار وحدة كل منها).

---

## 1. خريطة المعمارية الفعلية (المُثبتة)

```
                     MetaTrader 5 (جهاز المالك — BLOCKED للاختبار هنا)
                        │ NexusBridgeEA.mq5 (توكن API) + NexusSessionReader.mq5
                        ▼
   ┌───────────────── 9 خدمات FastAPI مستقلة (uvicorn، supervised) ─────────────────┐
   │                                                                                │
   │  nexus-data 9001 ──(MT5/CCXT/YFinance/IBKR connectors)──► DuckDB 62 جدولاً      │
   │      │  (كاتب وحيد single-writer — القفل مُثبت بالتجربة)                        │
   │      ▼                                                                        │
   │  nexus-features 9002 (OHLCV/مؤشرات/تقلب/ارتباط/جلسات) ──► Redis nexus:*        │
   │      ▼                                                                        │
   │  nexus-ml 9003 (8 نماذج + RL/DL/ML traders + ensemble)                        │
   │      ▼                                                                        │
   │  nexus-agents 9004 (13 وكيلاً + graph + LLM glm-4.5-flash) ──► قرار            │
   │      ▼                                                                        │
   │  nexus-risk 9006 (rules/sizer/correlation/anti-tilt) ── قبول/رفض               │
   │      ▼                                                                        │
   │  nexus-executor 9007 (paper/EA queue/smart routing) ──► صفقة تجريبية           │
   │      ▼                                                                        │
   │  nexus-monitor 9008 (metrics + telegram + performance)                        │
   │      │                                                                        │
   │  nexus-news 9005 (fetcher/تقويم/مشاعر/fundamental V61) ──► أخبار/تنبيهات        │
   │                                                                                │
   │  nexus-api 9000 = البوابة (165 مسار API + auth middleware + rate_limit +       │
   │              9 أنظمة WebSocket: ticks/positions/orders/risk/news/agents)       │
   └────────────────────────────────┬───────────────────────────────────────────────┘
                                    ▼
                 Dashboard Next.js 14.2.5 (React 18, zustand, RTL)
                        :3100 (next dev) ◄─ TCP proxy :3000
```

**البنية التحتية:** Redis 7.4.1 (cache + pub/sub + قوائم) — DuckDB ملفي (كاتب وحيد) — مشرف `run.py` (إقلاع بوابة صحة + إعادة إطلاق ذاتي).

---

## 2. سجل المكونات الكامل (Component Register)

| Component ID | الاسم | النوع | المسؤولية | المسار | نقطة الإقلاع | المنفذ | APIs | الاعتماديات | مصادر البيانات | المخرجات | الاتصال | حالة التشغيل (حية) | حالة التنفيذ | حالة الاختبار | ملاحظات |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CS-01 | nexus-api | Microservice (API Gateway) | بوابة REST/WS + مصادقة JWT + توكنات EA + تجميع | `services/nexus_api/` | `main:app` uvicorn | 9000 | **165 مسار** (OpenAPI) + 9 WS namespaces | Redis، DuckDB(عبر data)، كل الخدمات | الخدمات التسع | ردود موحدة للواجهة | HTTP/WS | **200 — PID 23513** | مكتمل | pytest test_api + جولات 1–3 حي | middleware/auth.py (D1 مُصلح)، rate_limit.py موجود |
| CS-02 | nexus-data | Microservice (Data + DB Writer) | استيعاب السوق + كتابة DuckDB + جودة + إعدادات بروكر + أساسي | `services/nexus_data/` | `main:app` | 9001 | 26 | DuckDB، Redis، connectors | MT5/CCXT/YFinance/IBKR | جداول 58 + Redis cache | HTTP | **200 — PID 4041** | مكتمل | test_data + حي | قفل DB مُثبت (كاتب وحيد) |
| CS-03 | nexus-features | Microservice (Feature Engine) | OHLCV، مؤشرات، تقلب، ارتباط، جلسات، multi-timeframe | `services/nexus_features/` | `main:app` | 9002 | 4 | Redis، data API | Redis/DuckDB | nexus:features:* | HTTP | **200 — PID 4059** | مكتمل | test_features | internal_auth بين الخدمات |
| CS-04 | nexus-ml | Microservice (ML Engine) | 8 نماذج (LSTM/RF/HMM/FinBERT/ISO/XGB/LGBM) + rl/dl/ml traders + ensemble + promotion | `services/nexus_ml/` | `main:app` | 9003 | 19 | Redis، features، models_store/ | features history | توقعات/نماذج pkl | HTTP | **200 — PID 21985** (أُعيد إطلاقه ذاتياً في S4) | مكتمل | test_ml + S4 حي | النماذج غير مدرّبة في الصندوق (state صادق) |
| CS-05 | nexus-agents | Microservice (AI Agents + Orchestrator) | 13 وكيلاً + graph دورة قرار + LLM سحابي + shadow trades | `services/nexus_agents/` | `main:app` | 9004 | 14 | Redis، LLM (Z.ai)، ml/news/risk | features/أخبار | قرارات NO_TRADE/… | HTTP | **200 — LLM ONLINE مؤكد (glm-4.5-flash، 263ms — 15:44Z)** | مكتمل (يعتمد مفتاح LLM) | test_agents + حي | 503 عابرة عند فشل LLM-probe = fail-closed مقصود (D6) |
| CS-06 | nexus-news | Microservice (News Engine) | جلب أخبار + تقويم + مشاعر + fundamental V61 + blackout | `services/nexus_news/` | `main:app` | 9005 | 8 | Redis، مصادر خارجية | feed/تقويم | nexus:news:* | HTTP | **200 — PID 4062** | مكتمل | test_news | مراقبة الصحة تظهرها unknown (فجوة تقارير — D-قائمة P2) |
| CS-07 | nexus-risk | Microservice (Risk Manager) | قواعد مخاطرة + حجم مركز + ارتباط + anti-tilt | `services/nexus_risk/` | `main:app` | 9006 | 9 | Redis، config/risk_rules.yaml | القرارات | قبول/رفض | HTTP | **200 — PID 4063** | مكتمل | test_risk | قواعدها YAML بلا UI (D4) |
| CS-08 | nexus-executor | Microservice (Execution) | paper executor + EA queue + smart routing + mt5/ibkr/ccxt adapters | `services/nexus_executor/` | `main:app` | 9007 | 6 | Redis، risk | قرارات مقبولة | صفقات تجريبية | HTTP | **200 — PID 4068** | مكتمل (paper) | test_executor | **لا تنفيذ حقيقي — paper فقط** |
| CS-09 | nexus-monitor | Microservice (Monitoring) | مقاييس + أداء + Telegram notifier | `services/nexus_monitor/` | `main:app` | 9008 | 6 | Redis، الخدمات | سجلات | مقاييس/تنبيهات | HTTP | **200 — PID 4069** | مكتمل | test_monitor | metrics_exporter + telegram_bot **مكوّنان داخليان** لا خدمتان |
| CS-10 | dashboard | Frontend Application | **18 ملف مسار = 15 شاشة فعّالة (13 داخل /nexus) + login + analytics + 3 تحويلات** + RTL + 30 نافذة + حالة (zustand) | `dashboard/` | `next dev -p 3100` | 3100 (بروكسي 3000) | يستهلك 9000 | nexus-api | البوابة | واجهة | HTTP/WS | **يعمل — dev mode** | مكتمل | 27 اختبار .mjs + جولات 1–3 | بلا Playwright (فجوة تُعالج بهذه الدورة) |
| CS-11 | run.py | Supervisor / Process Manager | إقلاع 9000–9008+dashboard، بوابة صحة، إعادة إطلاق (<1s مُقاس)، بناء URLs الأقران | `run.py` | `python run.py --paper --skip-preflight` | — | — | كل ما سبق | — | عمليات حية | subprocess | **يعمل — PID 4040** | مكتمل | S4 أثبت الشفاء الذاتي | `start_all.py` مجرد غلاف compatibility |
| CS-12 | Redis | Cache / Message Broker | cache + pub/sub + قوائم أوامر EA | `/home/z/my-project/redis/` | redis-server | 6379 | RESP | — | الخدمات | nexus:* (118)، stream:* (11) = **129** | TCP | **يعمل — 129 مفتاحاً حياً (مساءً)** | مكتمل | فحوص الشفاء كل 5 د | بناء محلي 7.4.1 (لا sudo)؛ تفصيل الأسماء في SYSTEM_INVENTORY §4 |
| CS-13 | DuckDB | Database (single-writer) | **62 جدولاً**: auth/مخاطرة/أساسي/سوق/صفقات/تدقيق | `data/nexus.duckdb` (16MB + WAL) | عبر nexus-data | — | SQL | — | connectors | استعلامات | ملف مقفول | **مقفول بنشط (كاتب وحيد)** — نسخة معزولة للقراءة | مفتاح التعديل داخل الخدمة | تدقيق هذه الدورة | إثبات القفل: IOException عند فتح ثانٍ؛ عدّ الصفوف مساءً في INVENTORY §3 |
| CS-14 | NexusBridgeEA | MT5 Expert Advisor (خارجي) | جسر أوامر/بيانات بين MT5 والنظام | `mql5/Experts/NexusBridgeEA.mq5` | MT5 terminal | — | REST→9000 (توكن api_tokens) | nexus-api | MT5 terminal | ticks/أوامر | HTTP | **BLOCKED — يتطلب جهاز المالك** | مكتمل (كود) | E2E حي على صندوق مستحيل — وفق docs/EA_BRIDGE.md | الاختبار على جهاز حقيقي = بند مالك |
| CS-15 | NexusSessionReader | MT5 Indicator | قراءة الجلسات داخل MT5 | `mql5/Indicators/NexusSessionReader.mq5` | MT5 terminal | — | — | MT5 | MT5 | مخزن جلسات | ملف | BLOCKED (نفس أعلاه) | مكتمل (كود) | NOT TESTED هنا | — |
| LIB-01 | shared/ | Shared Library (40 وحدة) | نماذج/إعدادات/redis/duckdb clients/استراتيجية/أمان/أحداث/LLM factory | `shared/` | استيراد | — | — | — | — | — | استيراد | مُحمّلة داخل كل خدمة | مكتمل | test_shared | ليست خدمة — مكتبة |
| LIB-02 | nexus_strategy | Strategy Library | كتالوج استراتيجيات + walk-forward + anti-leakage | `services/nexus_strategy/` | استيراد (بلا main.py) | — | — | — | — | — | استيراد | مُدمجة | مكتمل (مكتبة) | ضمن tests | **ليست خدمة مستقلة — لا main.py** |
| REF-01 | fx-trading-system-main | Vendored Reference (بحث) | مرجع بحثي (كتيبات/سكربتات/أوراق) | `fx-trading-system-main/` | لا يُشغَّل | — | — | — | — | — | — | غير مشغّل | خارج نطاق التشغيل | غير مطلوب | **docstring-refs فقط** في catalog.py/fundamental_store.py — صفر استيراد تشغيلي (مُثبت grep) |
| ART-01 | notebooks/ | Research Artifacts | 5 دفاتر بحث Jupyter | `notebooks/` | يدوي | — | — | — | — | — | — | غير مشغّل | بحثي | غير مطلوب | ليست مكونات تشغيل |
| UTL-01 | bootstrap_ensemble.py | CLI Utility | بذر بيانات تدريب ensemble | جذر | يدوي | — | — | 9001/9000/Redis | — | بذر | HTTP | عند الطلب | مكتمل | NOT TESTED هذه الدورة | — |
| UTL-02 | preflight.py | CLI Utility | فحوص ما قبل الإقلاع | جذر | يدوي/run.py | — | — | — | — | تقرير | — | عند الطلب | مكتمل | test_preflight.py موجود | — |
| UTL-03 | scripts/ (13 سكربت) | Admin Utilities | schema/rebuild/seed/smoke/ui_walkthrough… | `scripts/` | يدوي | — | — | — | — | — | — | عند الطلب | مكتمل | جزئي | — |
| LEG-01 | _check_db.py | **Dead Utility** | فحص DB بمسار ويندوز مُقعد `C:\...` | جذر | لا يعمل هنا | — | — | — | — | — | — | **معطّل في الصندوق** | قديم | — | أثر ويندوز قديم — مرشح أرشفة (قرار مالك) |
| LEG-02 | start_nexus.bat / stop_nexus.bat / autostart_loggedon.cmd | Windows Launchers | إقلاع على جهاز المالك | جذر | ويندوز فقط | — | — | — | — | — | — | غير قابلة هنا | مكتمل (ويندوز) | NOT VERIFIED هنا | سجّلت NOT VERIFIED لا فشل |
| TEST-01 | tests/ (pytest) | Test Suite | 184 ملفاً في 14 مجالاً — **test_api وحدها 555 اختباراً: 555/555 PASS (مساءً بعد D13)** | `tests/` | pytest | — | — | — | — | تقرير | — | عند الطلب | مكتمل | تُشغَّل هذه الدورة | — |
| TEST-02 | dashboard/tests (27 ملف .mjs) | Unit Tests (Node) | عقود عرض/حالة الواجهة | `dashboard/tests/` | node --test | — | — | — | — | تقرير | — | عند الطلب | مكتمل | تُشغَّل هذه الدورة | — |

---

## 3. العدد الحقيقي (إحصاء مبني على أدلة)

| الفئة | العدد | الأساس |
|---|---|---|
| **خدمات مستقلة قابلة للنشر (Microservices)** | **9** | 9 × `main.py` + 9 × سجل run.py:80-88 + 9 × uvicorn حي + 9 × OpenAPI |
| تطبيق واجهة أمامية | 1 (dashboard Next.js 14.2.5) | package.json + عملية next-server حية |
| مشرف عمليات | 1 (run.py) | PID 4040 حي + سجل الخدمات في الكود |
| بنية تحتية | 2 (Redis، DuckDB) | عمليات/ملفات حية |
| مكتبات مشتركة | 2 (shared/ بـ40 وحدة، nexus_strategy بـ5 وحدات) | لا main.py — استيراد فقط |
| مكونات MT5 خارجية | 2 (EA + Indicator) | mql5/ — BLOCKED للاختبار الحي هنا |
| أدوات CLI عند الطلب | 16 (bootstrap_ensemble، preflight، 13 سكربت، تشخيصات) | جذر + scripts/ |
| اختبارات | 184 pytest + 27 node | عدّ ملفات |
| مرجع بحثي غير مشغّل | 1 (fx-trading-system-main) | صفر استيراد تشغيلي |
| **إجمالي مسارات API الحقيقية** | **257** | مجموع OpenAPI: 165+26+4+19+14+8+9+6+6 |
| **شاشات الواجهة** | **18 ملف مسار = 15 فعّالة (13 /nexus + login + analytics) + 3 تحويلات** | جرد `dashboard/src/app` (18 × page.tsx) + جولات القياس |

**المكونات المكتملة:** 9/9 خدمات + dashboard + supervisor + infra = **مكتملة تشغيلياً** (بحالة بيانات صفرية موثقة).
**غير مكتمل/بقيود:** بيانات السوق فارغة (قاعدة جديدة — تتراكم تلقائياً)، جسر MT5 حي (يحتاج جهاز المالك)، نماذج ML غير مدرّبة في الصندوق (تُدرّب بالأداة المخصصة)، بلا Docker/CI (لا تتطلبها بيئة الصندوق).
**متوقفة/غير مستخدمة:** `_check_db.py` (مسار ويندوز ميت)، `start_all.py` (غلاف deprecated يعمل لكنه يفوّض لـrun.py).
**مكرر/متداخل:** لا تكرار وظيفي بين الخدمات؛ التداخل الوحيد: **فجوة تقارير الصحة** (news/monitor يظهران `unknown` في `/api/system/health` رغم عملهما — عيب P2 مسجل).
**تناقضات وثائق↔كود:** **لا تناقض في عدد الخدمات** — README/NEXUS_MASTER_PLAN/HANDOFF تقول 9 والكود 9. (الهدف "10" في برومبت M.1 كان هدفاً وليس حقائق المستودع؛ المعتمد الفعلي 9.)

---

## 4. تقييم معماري مستقل

| المعيار | التقييم | الدليل |
|---|---|---|
| فصل المسؤوليات | **جيد جداً** | كل خدمة نطاق واحد واضح (data/…/monitor)؛ الوكيلُ عنصر داخل agents لا خدمة |
| استقلالية الخدمات | جيد | كل خدمة uvicorn مستقل؛ إسقاط 9003 أثبت بقاء البقية (S4) |
| الترابط Coupling | مقبول | HTTP بين الأقران + Redis؛ URLs الأقران يبنيها run.py برمجياً (نقطة مركزية — أثبتت هشاشة عند إقلاع يدوي بلا env: عيب D8 المُصلح) |
| التماسك Cohesion | جيد | shared/ مركزي بلا تكرار عميل Redis/DB |
| موثوقية الاتصال | جيد | fail-closed في كل الطبقات (بلا LLM → NO_TRADE؛ بلا شموع → lافتة صادقة) |
| تحمل الأعطال | **ممتاز مقاساً** | إعادة إطلاق ذاتي <1 ث (S4 موثق بلقطات) |
| سلامة تدفق البيانات | جيد | كاتب DB وحيد + dedup في imports/ + جودة/حجر صحي |
| قابلية التوسع | مقبول | DuckDB ملفي مناسب للصندوق؛ عنق زجاجة محتمل للكتابة عالية التردد (تزكية مستقبلية لا عيب حالي — 0 صفوف ticks) |
| تجنب التكرار | جيد | لا خدمتان تتشاركان مسؤولية؛ fx-trading-system-main مرجع لا نسخة عمل |
| أمن الاتصالات | جيد | خدمات على 127.0.0.1 فقط، JWT + PIN للعمليات الحساسة، internal_auth بين الخدمات |
| المراقبة والتشغيل | جيد مع فجوة | supervisor + heal كل 5 د + نسخ يومي؛ فجوة: news/monitor `unknown` في health تجميعي |

**خلاصة:** المعمارية متناسبة مع الهدف، بلا تعقيد زائد وبلا حاجة مثبتة لدمج/فصل خدمات. لا يُوصى بأي إعادة هيكلة حالياً.

## 5. المخاطر المعمارية (مبنية على أدلة)
1. **run.py مركزية URLs الأقران** — أي إقلاع يدوي خارج env الكامل يكسر التوجيه (D8 حصل فعلاً؛ المخلف: حلقة D9 عند تعارض منافذ يدوية).
2. **DuckDB كاتب وحيد** — سلامة ممتازة، لكن تراكم ticks لاحقاً سيضغط (مراقبة دورية).
3. **dev mode للداشبورد في الصندوق** — استهلاك ذاكرة متصاعد (~1GB قيّد في جولة 3)؛ للإنتاج: `next build`.
4. **الاعتماد على LLM سحابي** — 429 مع الحصة المجانية (D6)؛ fail-closed يمنع الضرر.

## 6. درجات الثقة
| الاستنتاج | الثقة |
|---|---|
| 9 خدمات حية بمنافذها | عالية جداً (عمليات + openapi + health) |
| 257 مسار API | عالية (OpenAPI مباشر) |
| 58 جدول DuckDB وعددها | عالية → **مُحدّث مساءً: 62 جدولاً بعدّ صفوف** |
| تصنيف nexus_strategy مكتبة | عالية (لا main.py، استيراد فقط) |
| fx-trading-system-main غير مشغّل | عالية (grep شامل: docstrings فقط) |
| جسر MT5 يعمل حياً | **NOT VERIFIED — يتطلب جهاز المالك** (BLOCKED) |

## 7. تحديث دورة مساء 2026-11-04 (إصلاحات فورية + إعادة تحقق)
| البند | الدليل | النتيجة |
|---|---|---|
| **D10** إنشاء مستخدم باسم محذوف منطقياً (tombstone) = 200 صامت + إخفاء رفض data-service كـ503 عام | 826eecb (a/b/c) + تحصين 5921635 (عرض تفصيل 400 المتحكّم به فقط) | FIXED-VERIFIED — 17/17 ×3 ثم 248/248 |
| **D12** عيب عزل اختبار: stub لرمز غير موجود (`system.local_health`) يُسقط جمع ملف اختبار التخويل عند HEAD | 5921635 | FIXED-VERIFIED |
| **D13** عيب عزل اختبار: `/api/config/risk` يجري نداء شبكة حقيقياً لـnexus-risk الحية → 403 حي يُمرّر للاختبار | 5921635 (stub لـ`risk._risk_proxy`) | FIXED-VERIFIED — **555/555 انحدار كامل** |
| 9004 LLM ONLINE (glm-4.5-flash، 263.22ms) | `curl /health` 15:44Z | يؤكد F2 حياً |
| **تأرجح 9004 الديناميكي**: ONLINE (263ms @ 15:44Z) ↔ OFFLINE (probe 6s @ 15:54Z) ↔ ONLINE (3.76s @ 15:56Z) | لقطات /health الثلاث | سلوك D6 الموثق (fail-closed + استرداد ذاتي) — ليس عيباً جديداً |
| **9001 `status: degraded` صادق**: `data_mode=REAL_MT5_REQUIRED`، `synthetic_fallback=false`، redis+duckdb ok، mt5/ibkr/ccxt=false (لا مصادر في الصندوق)، جودة تعمل (0 أخطاء) | /health @ 15:54Z | الحالة الموثقة "قاعدة صفرية صادقة" — ليست عيباً |
| أرقام محدثة: DuckDB 62 جدولاً، Redis 129 مفتاحاً، dashboard 18 ملف مسار، 257 مسار API (مُعاد العدّ) | أوامر هذا المساء | تحدّث الوثائق المرتبطة |
