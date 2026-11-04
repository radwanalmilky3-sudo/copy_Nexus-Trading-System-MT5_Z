# SYSTEM ARCHITECTURE DISCOVERY REPORT — NEXUS TRADER MT5

| البند | القيمة |
|---|---|
| الوثيقة | SYSTEM_ARCHITECTURE_DISCOVERY_REPORT.md (وثيقة 2/16 ضمن برنامج M.2) |
| التاريخ | 2026-11-04 (UTC) — جولة الفحص 16:07–16:32 UTC |
| المنهجية | اكتشاف مستقل: لا افتراض بعدد الخدمات، التصنيف من الأدلة الفعلية (عمليات جارية، منافذ، استجابات HTTP، مفاتيح Redis، schema قاعدة البيانات) |
| نطاق التداول | Paper Trading فقط — `nexus:system:auto_trade=false` (مُتحقق منه من Redis) |
| Git عند الإعداد | bc3be35 (عملية re-verification مسائية سابقة) — الأدلة أدناه من جولة مستقلة جديدة |
| التغطية | مكتملة للبنية الثابتة؛ بنود NOT VERIFIED معلَّمة صراحة في §9 |

---

## 1. الملخص التنفيذي

تم تنفيذ جولة اكتشاف بنية مستقلة كاملة على منظومة NEXUS TRADER MT5. **العدّ الحقيقي للخدمات (microservices) هو 9 خدمات uvicorn/FastAPI على المنافذ 9000–9008**، جميعها حيّة ومُتحقق منها عبر `/health`. هذا العدد يطابق سجل `run.py` حرفيًا (مطابقة 1:1 بين السجل والعمليات الجارية بالـ PID)، ولا توجد أي خدمة غير مسجَّلة.

خارج الخدمات التسع، تم تصنيف المكونات الأخرى بناءً على الدليل لا الاسم: مكتبة واحدة (`nexus_strategy` — بلا `main.py`)، تطبيق ويب واحد (Next.js 14.2.5 على 3100)، مُنسِّق واحد (`run.py`)، مُمرِّر TCP واحد (3000→3100)، 13 عاملاً خلفيًا (A0–A12 تابعة لـ nexus-agents وليست خدمات)، حلقة خلفية واحدة داخل nexus-data، ومخزنان (Redis وDuckDB).

**حالتان تشغيليتان موثقتان بالأدلة:**
1. **تذبذب 9004 (nexus-agents)**: أعادت `/health` **503 OFFLINE** في 16:27:20 UTC (`llm_online:false`، زمن استجابة LLM ‏6030ms) ثم **200 ONLINE** في 16:31:55 (زمن استجابة 4593ms) — سلوك **fail-closed صحيح** أمام تذبذب اعتماد Z.ai الخارجي (glm-4.5-flash). ليست عيبًا في المنظومة لكنها مخاطرة توفر خارجية تُسجَّل في سجل العيوب كملاحظة P2.
2. **9001 (nexus-data) = degraded «صادق»**: `data_mode: REAL_MT5_REQUIRED`، `synthetic_fallback: false`، `mt5: false` — متوقع في بيئة بلا جسر MT5 حي، والمكونات الداخلية (redis:true, duckdb:true, quality_automation بدورة 60 ثانية) سليمة.

نقطة اكتشاف مهمة على الواجهة: **المنفذ 3000 ليس خادم dashboard بل مُمرِّر TCP** (`port3000_forward.py`، خارج شجرة المستودع عمدًا) يوجه إلى **next-server v14.2.5** على المنفذ 3100. جميع صفحات الواجهة (6 عليا + 12 تبويبًا فرعيًا + `/api/health`) أجابت **HTTP 200**.

---

## 2. خريطة المنافذ المسموعة (دليل مباشر `ss -ltnp`)

| المنفذ | العملية | الدليل (PID) | التصنيف |
|---|---|---|---|
| 3000 | python3 `scripts/port3000_forward.py` | 3581 | مُمرِّر TCP (0.0.0.0:3000 → 127.0.0.1:3100) |
| 3100 | `next-server (v14.2.5)` | 9306 | تطبيق ويب — dashboard (إنتاج Next.js، cwd=`dashboard/`) |
| 9000 | uvicorn `services.nexus_api.main` | 32293 | microservice |
| 9001 | uvicorn `services.nexus_data.main` | 31209 | microservice |
| 9002 | uvicorn `services.nexus_features.main` | 4059 | microservice |
| 9003 | uvicorn `services.nexus_ml.main` | 21985 | microservice |
| 9004 | uvicorn `services.nexus_agents.main` | 13842 | microservice (+13 عاملًا داخليًا) |
| 9005 | uvicorn `services.nexus_news.main` | 4062 | microservice |
| 9006 | uvicorn `services.nexus_risk.main` | 4063 | microservice |
| 9007 | uvicorn `services.nexus_executor.main` | 4068 | microservice |
| 9008 | uvicorn `services.nexus_monitor.main` | 4069 | microservice |

لا توجد منافذ خدمية أخرى مسموعة. المفتاح `HEAL_STATUS` عند 16:07 و16:26: `redis ok / forwarder ok / stack ok`.

---

## 3. سجل المكونات (16 خانة لكل مكوّن)

> خانات السجل: (1) الاسم (2) النوع (3) نقطة الدخول (4) المنفذ/الواجهة (5) العملية الجارية (6) نقطة الصحة (7) حالة الصحة وقت الفحص (8) الاعتماديات (9) يُنتج (10) يستهلك (11) ترتيب الإقلاع (12) مصدر الإعدادات (13) السجلات (14) سياسة الإعادة (15) دليل الإثبات (16) ملاحظات/مجهولات.

### 3.1 nexus-api — 9000
(1) `nexus-api`. (2) microservice. (3) `services.nexus_api.main:app`. (4) 127.0.0.1:9000. (5) uvicorn PID 32293. (6) `/health`. (7) **200 healthy** (16:31). (8) Redis (heartbeat `nexus:health:nexus-api`), DuckDB, JWT/auth على `app_users`. (9) واجهة REST موحدة للـ dashboard + WS gateway. (10) طلبات الواجهة؛ أحداث الخدمات. (11) **الأخير** في `STARTUP_ORDER`. (12) `.env` عبر `shared/config_loader.py` (عقد `shared/config_contract.py`). (13) `logs/`. (14) إدارة إعادة تشغيل عبر `run.py`. (15) `ss` + `curl /health` + مطابقة cmdline. (16) بوابة الواجهة الأمامية: `NEXT_PUBLIC_API_URL=http://127.0.0.1:9000` يُضبط من `run.py`.

### 3.2 nexus-data — 9001
(1) `nexus-data`. (2) microservice (+حلقة خلفية داخلية). (3) `services.nexus_data.main:app`. (4) 127.0.0.1:9001. (5) uvicorn PID 31209 (يحجز قفل DuckDB للكتابة). (6) `/health`. (7) **200 degraded — صادق**: `data_mode=REAL_MT5_REQUIRED`, `synthetic_fallback=false`, `mt5=false`, `ibkr=false`, `ccxt=false`, `redis=true`, `duckdb=true`. (8) DuckDB (ملف `data/nexus.duckdb`)، Redis. (9) `stream:ticks`، `stream:ohlcv`، `stream:features`، جداول السوق. (10) مصادر بيانات (MT5 غير متصل حاليًا). (11) **الأول** في `STARTUP_ORDER`. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl body كامل محفوظ. (16) حلقة `quality_automation` داخلية كل 60s: آخر دورة 16:31:28 — `audited=0 failed=0 warnings=0 errors=0 repair_enabled=true blocked_pairs=0`; حالة التقويم `not_configured` (بلا جلسات — متوقع).

### 3.3 nexus-features — 9002
(1) `nexus-features`. (2) microservice. (3) `services.nexus_features.main:app`. (4) 127.0.0.1:9002. (5) uvicorn PID 4059. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:health:nexus-features` + مؤشرات fundamental)، DuckDB (قراءة). (9) مؤشرات هندسية/أساسية: `nexus:fundamental:*`، `nexus:cross_asset:*`، `stream:features`. (10) `stream:ticks`/`stream:ohlcv` من nexus-data. (11) الثاني. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline. (16) —.

### 3.4 nexus-ml — 9003
(1) `nexus-ml`. (2) microservice. (3) `services.nexus_ml.main:app`. (4) 127.0.0.1:9003. (5) uvicorn PID 21985. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:health:nexus-ml`). (9) تنبؤات/تقييمات نماذج. (10) خصائص من nexus-features. (11) الخامس. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline. (16) —.

### 3.5 nexus-agents — 9004
(1) `nexus-agents`. (2) microservice + 13 عاملًا خلفيًا داخليًا (A0–A12). (3) `services.nexus_agents.main:app`. (4) 127.0.0.1:9004. (5) uvicorn PID 13842. (6) `/health`. (7) **تذبذب موثق**: 503 OFFLINE عند 16:27:20 (`redis:true, llm_online:false, llm_latency_ms=6030.67`) → **200 ONLINE** عند 16:31:55 (`ready:true, llm_online:true, llm_latency_ms=4593.45`). (8) Redis (`nexus:health:nexus-agents` + `nexus:health:A0..A12`)، **LLM خارجي Z.ai** `https://api.z.ai/api/paas/v4` (glm-4.5-flash). (9) `stream:agent:verdict` (4 رسائل وقت الفحص)، مفاتيح `nexus:strategy:*`، `nexus:genai:*`. (10) إشارات/خصائص، LLM خارجي. (11) السادس. (12) `.env` (مفتاح LLM — غير مُطبع عمدًا وفق خطوط M.2 الحمراء). (13) `logs/`. (14) run.py + fail-closed داخلي (يرفض ONLINE بلا LLM). (15) curl body ×2 بطوابع زمنية. (16) عمال A0–A12 حالتهم كلها `idle` بتوقيع `service: nexus-agents` — **ليست خدمات مستقلة**. البند `stream:processed` لعلامات تكرار state-writer موجود (4 مفاتيح).

### 3.6 nexus-news — 9005
(1) `nexus-news`. (2) microservice. (3) `services.nexus_news.main:app`. (4) 127.0.0.1:9005. (5) uvicorn PID 4062. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:health:nexus-news`، `nexus:news:*`)، DuckDB (جداول الأخبار). (9) `stream:news`، `nexus:news:meta/calendar/ticker:*`. (10) مصادر خارجية للأنباء (جلب مجدول). (11) الثالث. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline. (16) —.

### 3.7 nexus-risk — 9006
(1) `nexus-risk`. (2) microservice. (3) `services.nexus_risk.main:app`. (4) 127.0.0.1:9006. (5) uvicorn PID 4063. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:health:nexus-risk`, `nexus:risk:*`). (9) `stream:risk:decision`، `nexus:risk:day_start_balance/equity_peak/open_risk_snapshot`. (10) مراكز/صفقات من executor، إعدادات runtime. (11) الرابع. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline. (16) —.

### 3.8 nexus-executor — 9007
(1) `nexus-executor`. (2) microservice. (3) `services.nexus_executor.main:app`. (4) 127.0.0.1:9007. (5) uvicorn PID 4068. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:health:nexus-executor`, `stream:orders`, `stream:positions`, `stream:trades:close`)، DuckDB (trades/positions/ea_commands)، **جسر MT5** (سطر الأوامر للـ EA — يُدقَّق في خطوة تدقيق الجسر). (9) أوامر EA (`ea_commands`)، أحداث صفقات. (10) قرارات risk + verdicts agents. (11) السابع. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline. (16) سابقًا في M.2 (commit bc3be35): `real_broker_execution_enabled=false` مُتحقق حيًا (TC-MT-04) — Paper-only مُبْرَز. الاتصال الفعلي بالـ EA اليوم: **NOT VERIFIED** (mt5:false — ضمن خطوة لاحقة).

### 3.9 nexus-monitor — 9008
(1) `nexus-monitor`. (2) microservice (+وحدتان داخليتان). (3) `services.nexus_monitor.main:app`. (4) 127.0.0.1:9008. (5) uvicorn PID 4069. (6) `/health`. (7) **200 healthy**. (8) Redis (`nexus:monitor:metrics`, `nexus:alerts:log`, جميع مفاتيح health). (9) مقاييس مجمعة، تنبيهات، بوت Telegram (داخلي)، مصدّر metrics (داخلي). (10) مفاتيح الصحة والأنابيب. (11) الثامن. (12) `.env`. (13) `logs/`. (14) run.py. (15) curl + cmdline + فحص الاستيراد. (16) **بند مُعلّق سابق أُغلق بالدليل**: `telegram_bot.py` و`metrics_exporter.py` وحدتان داخليتان تُستوردان نسبيًا (`from .telegram_bot import TelegramNotifier`, `from .metrics_exporter import MetricsExporter` في `services/nexus_monitor/main.py` سطرا 32 و34) — **ليستا خدمتين منفصلتين**.

### 3.10 nexus_strategy — مكتبة
(1) `nexus_strategy`. (2) **library** (بلا `main.py`، لا منفذ، لا عملية). (3) حزمة `services/nexus_strategy/` (`__init__.py`, `anti_leakage.py`, `catalog.py`, ...). (4) —. (5) تُحمَّل داخل عمليات أخرى. (6) —. (7) —. (8) —. (9) منطق استراتيجيات/كتالوج/منع تسرب البيانات. (10) تستوردها الخدمات. (11) —. (12) —. (13) —. (14) —. (15) `ls services/`: 10 حزم، 9 فقط بـ `main.py`. (16) لا تُحتسب في عدّ الخدمات.

### 3.11 dashboard (واجهة الويب)
(1) `dashboard`. (2) web-app (Next.js 14.2.5 إنتاجي). (3) `next-server` (cwd `dashboard/`). (4) `*:3100` + توجيه خارجي 3000→3100. (5) PID 9306. (6) `/api/health` (200). (7) **200 لكل 19 مسارًا مفحوصًا** (§7). (8) `NEXT_PUBLIC_API_URL` → 9000، WS → 9000. (9) —. (10) REST/WS من nexus-api. (11) يُدار من run.py (`DASHBOARD_PORT=3100`, حد إعادة تشغيل 3). (12) متغيرات NEXT_PUBLIC من run.py. (13) stdout عبر run.py. (14) `_MAX_DASHBOARD_RESTARTS=3`. (15) `ss` + cmdline + فحص HTTP شامل. (16) صفحة الجذر `/` تحوّل 307 إلى `/nexus`؛ `/history` و`/settings` تحولان إلى `/nexus/history` و`/nexus/settings` (تحويل مسار داخلي، **ليس** تحويل تسجيل دخول).

### 3.12 run.py — المنسِّق
(1) `run.py`. (2) orchestrator/supervisor. (3) `python run.py` (CLI: `--reload`, اختيار خدمات). (4) —. (5) مُشغِّل العمليات التسع + dashboard. (6) —. (7) —. (8) subprocess/env. (9) إقلاع كامل المنظومة بالترتيب. (10) `SERVICE_REGISTRY` (9 مداخل)، `SERVICE_TO_MODULE`، `STARTUP_ORDER`. (11) الترتيب: data → features → news → risk → ml → agents → executor → monitor → api. (12) `.env` + `config_contract` (33+ مفتاحًا منها `REDIS_URL`). (13) يجمع stdout ملونًا. (14) إعادة تشغيل dashboard بحد أقصى 3. (15) قراءة run.py سطور 50–89، 366، 576–594، 639–640. (16) لا يوجد سجل خدمة خارج هذه التسع.

### 3.13 port3000_forward.py — مُمرِّر المعاينة
(1) `port3000_forward.py`. (2) TCP forwarder (بروكسي معاينة). (3) `python3 /home/z/my-project/scripts/port3000_forward.py` — **خارج شجرة المستودع عمدًا** (تعليق الملف ذاته). (4) 0.0.0.0:3000 → 127.0.0.1:3100. (5) PID 3581. (6) —. (7) يعمل (فحص HTTP عبر 3000 ناجح). (8) —. (9) —. (10) —. (11) خارج run.py. (12) ثوابت داخل الملف. (13) —. (14) —. (15) قراءة الملف + cmdline PID 3581. (16) سبب تضارب الوثائق القديمة التي ذكرت «dashboard على 3000 dev».

### 3.14 Redis — مخزن حالة/رسائل
(1) `redis-server`. (2) data-store (in-memory). (3) `/home/z/my-project/redis/bin/redis-server` (`--save "" --appendonly no`, dir=`/home/z/my-project/redis`). (4) 127.0.0.1:6379 (db0). (5) جارٍ (ping=PONG). (6) `heal` في السكربت. (7) ok. (8) —. (9) 137 مفتاحًا (§5). (10) كل الخدمات. (11) —. (12) سطر أوامر heal. (13) `logs/redis_server.log`. (14) إعادة تشغيل تلقائية من nexus_heal.sh عند السقوط. (15) INFO keyspace: `db0:keys=137,expires=124`. (16) **بلا ثبات** (no persistence) — فقدان المفاتيح عند إعادة تشغيل الحاوية هو سلوك معروف ومقصود في هذه البيئة.

### 3.15 DuckDB — قاعدة تحليلية
(1) `nexus.duckdb`. (2) data-store (تحليلي ملفي). (3) `data/nexus.duckdb` (36,450,304 بايت) + WAL (2,624,937 بايت). (4) ملف. (5) يحتضنه nexus-data (PID 31209 يحمل قفل الكتابة — لا يسمح بقارئ خارجي). (6) عبر 9001 `/health` (`duckdb:true`). (7) ok. (8) —. (9) 62 جدولًا (§6). (10) nexus-data (كتابة)، بقية الخدمات (قراءة داخل العملية نفسها). (11) —. (12) —. (13) —. (14) WAL. (15) فحص عبر نسخة read-only في /tmp بسبب القفل. (16) الجداول التشغيلية الحيوية (ohlcv/ticks/trades/positions/ea_commands) **فارغة حاليًا** — متسق مع Paper بلا جسر حي.

### 3.16 عمال nexus-agents A0–A12
(1) A0–A12. (2) **background workers** (فتحات عمال داخل nexus-agents). (3) حلقة داخل خدمة 9004. (4) —. (5) داخل PID 13842. (6) `nexus:health:A0..A12`. (7) 13/13 `idle` (16:30:18). (8) Redis فقط. (9) verdicts إلى `stream:agent:verdict`. (10) مهام تقييم/تحليل. (11) —. (12) —. (13) `logs/`. (14) داخل الخدمة. (15) قراءة قيم المفاتيح (توقيع `service: nexus-agents`). (16) **قرار تصنيفي**: لا تُحتسب خدماتًا؛ إنما فتحات عمال لعملية واحدة.

### 3.17 مكونات غير مستخدمة/مساعدة
(1) `fx-trading-system-main/`. (2) **unused** (مجلد شفرة غير مُشار إليه وقت التشغيل — لا استيراد `from fx_trading_system_main` في `services/` ولا في `run.py`). (15) مسح استيراد الجلسات السابقة + غياب أي مرجع في cmdline العمليات. (16) يُدرج في SYSTEM_INVENTORY كمرشح حذف/أرشفة — لا يُحذف وفق الخطوط الحمراء (ممنوع حذف وظائف) بل يُعلَّم فقط.
(1) `start_all.py`, `bootstrap_ensemble.py`, `_check_db.py`. (2) scripts/auxiliary (بلا عملية جارية). (16) مساعدة يدوية؛ ليست ضمن التشغيل التلقائي.

---

## 4. حالة صحة الخدمات التسع (لقطة 16:31 UTC)

| الخدمة | HTTP | status | ملاحظة |
|---|---|---|---|
| nexus-api 9000 | 200 | healthy | — |
| nexus-data 9001 | 200 | **degraded** | mt5=false متوقع؛ البنية الداخلية سليمة |
| nexus-features 9002 | 200 | healthy | — |
| nexus-ml 9003 | 200 | healthy | — |
| nexus-agents 9004 | 200/503 | **flap** | تذبذب LLM الخارجي — fail-closed صحيح |
| nexus-news 9005 | 200 | healthy | — |
| nexus-risk 9006 | 200 | healthy | — |
| nexus-executor 9007 | 200 | healthy | — |
| nexus-monitor 9008 | 200 | healthy | — |

> صيغة التقييم وفق M.2: لا تُحتسب حالة 9004 المتذبذبة PASS مطلقًا؛ تُوثَّق كحالة اعتماد خارجية (زمن استجابة LLM 4.6–6.0 ثانية حتى عند ONLINE).

---

## 5. فضاء مفاتيح Redis (137 مفتاحًا — db0، 124 بانتهاء صلاحية)

| العائلة | العدد | الوظيفة |
|---|---|---|
| `nexus:strategy:item:*` | 57 | حالة جلسات الاستراتيجيات (منها `seed-session-breakout`) + `nexus:strategy:index` + `nexus:strategy:research:log` |
| `nexus:health:*` | 21 | نبضات: 8 خدمات (api/data/executor/features/ml/news/risk/agents) + A0–A12 |
| `nexus:fundamental:*` | 19 | monetary/macro/geopolitical/flows/cross_asset/gold: latest+details، blackout، data_quality، fusion:latest |
| `nexus:risk:*` | 7 | day_start_balance، equity_peak، open_risk_snapshot، … |
| `nexus:stream:processed:*` | 4 | علامات إلغاء تكرار لعمال state-writer |
| `nexus:cross_asset:*` | 4 | DXY، XAUUSD، … |
| `nexus:runtime:settings` (+last) | 2 | إعدادات تشغيل حية |
| `nexus:news:*` | 5 | meta، calendar، ticker:active، ticker:lifecycle |
| Streams (7) | 7 | `stream:ticks/ohlcv/features/news` + `stream:signals/orders/positions/trades:close/risk:decision/agent:verdict` |
| أخرى | 15 | `nexus:system:auto_trade=false`، `nexus:monitor:metrics`، `nexus:alerts:log`، `nexus:genai:daily_bias`، `nexus:genai:brief:last_run`، `nexus:correlation:matrix` |

**أطوال الـ streams وقت الفحص**: signals=0، orders=0، positions=0، trades:close=0، risk:decision=0، **agent:verdict=4** — خطوط التداول خامدة (Paper، لا جسر حي)، خط الأحكام تحدثه العمال.

---

## 6. مخطط DuckDB الفعلي — 62 جدولًا (main)

**جداول بها بيانات (لقطة):** `event_asset_impacts` 2088، `prediction_reasoning_steps` 783، `fundamental_factor_scores` 1305، `fundamental_explanations`/`fundamental_fusion_results`/`gold_impact_predictions` 261 لكل منها، `source_fetch_runs`/`source_health_history` 187، `fund_events` 135، `user_audit_log` 56، `app_user_roles`/`app_users` 53، `data_vintages`/`macro_releases` 50، `asset_factor_profiles` 67، `fund_sources` 25، `app_role_permissions` 36، `economic_indicator_catalog` 37، `event_expectations` 48، `api_tokens` 5، `asset_registry` 2، `news_ticker_items` 2، `central_bank_events` 3، `fundamental_knowledge_claims` 5، `fundamental_knowledge_sources` 1.

**جداول تشغيلية فارغة حاليًا** (متسق مع Paper بلا جسر حي): `ohlcv`، `ticks`، `trades`، `positions`، `ea_commands`، `broker_accounts`، `agent_logs`، `alert_delivery_log`، `datasets`، `news_articles`، `news_nlp_analysis`، `news_story_clusters`، وغيرها (المجموع 62).

**أعمدة الجداول الحرجة للتدقيق اللاحق** (مُتحقق منها `information_schema.columns`):
- `api_tokens` (11): token_id, user_id, token_hash, label, mt5_login, mt5_broker, mt5_server, active, created_at, last_used_at, revoked_at — **تجزئة التوكن مخزنة (token_hash) لا النص الصريح**.
- `ea_commands` (12): command_id, user_id, token_id, symbol, action, payload_json, status, claimed_at, completed_at, result_json, created_at, updated_at.
- `trades` (14): id, symbol, side, entry_price, exit_price, pnl_pips, pnl_usd, rr_ratio, duration_s, session, conviction, opened_at, closed_at, strategy.
- `positions` (14): id, symbol, side, entry_price, current_price, sl, tp1..tp3, size, pnl_pips, pnl_usd, status, opened_at.
- `app_users` (13): user_id, username, full_name, email, password_hash, avatar_path, language, timezone, active, deleted, created_at, updated_at, last_login_at — **كلمات المرور مجزأة**.
- `user_audit_log` (7): audit_id, actor_user_id, action, target_type, target_id, details_json, created_at.

---

## 7. جرد الواجهة (dashboard) — كل المسارات مفحوصة HTTP عبر 3000

| المسار | HTTP | الملاحظة |
|---|---|---|
| `/` | 307 → `/nexus` | تحويل جذري |
| `/nexus` | 200 | الصفحة الرئيسية للوحة |
| `/analytics` | 200 | — |
| `/login` | 200 | — |
| `/progress-state` | 200 | — |
| `/history` | 307 → `/nexus/history` | تحويل مسار (ليس auth) |
| `/settings` | 307 → `/nexus/settings` | تحويل مسار (ليس auth) |
| `/nexus/ea-bridge` | 200 | تبويب جسر MT5 |
| `/nexus/strategies` | 200 | — |
| `/nexus/research-lab` | 200 | — |
| `/nexus/ml-models` | 200 | — |
| `/nexus/models` | 200 | — |
| `/nexus/model-comparison` | 200 | — |
| `/nexus/deep-learning` | 200 | — |
| `/nexus/reinforcement-learning` | 200 | — |
| `/nexus/progress` | 200 | — |
| `/nexus/audit-progress` | 200 | — |
| `/nexus/history` | 200 | — |
| `/nexus/settings` | 200 | — |
| `/api/health` | 200 | نقطة صحة الواجهة |

مجموعات المكونات في `src/components/`: audit, fundamental, layout, progress, research-lab, settings, shared, trade-controls, ui, windows. مسار API وحيد: `src/app/api/health/route.ts`.

---

## 8. تضاربات الوثائق مقابل الواقع (إلزامي وفق M.2)

| # | الوثائق/الافتراض | الواقع المُتحقق | الحكم |
|---|---|---|---|
| C1 | «dashboard يعمل على 3000 (Next dev)» | 3000 = مُمرِّر TCP خارجي؛ الخادم next-server v14.2.5 (إنتاج) على 3100 | وثيقة قديمة — يُصحَّح في SYSTEM_INVENTORY |
| C2 | `telegram_bot`/`metrics_exporter` بند مجهول «ربما خدمات» | وحدتان داخليتان في nexus-monitor (استيراد نسبي) | مغلق بالدليل |
| C3 | عدد الخدمات «غير معروف مسبقًا» | 9 خدمات = سجل run.py = عمليات جارية = مفاتيح health الخدمية (8 + agents) | توافق كامل |
| C4 | `DB_SCHEMA.md` مقابل `DB_SCHEMA_ACTUAL.md` | الفعلي الآن 62 جدولًا؛ المطابقة التفصيلية عمودًا-بعمود تُنفَّذ في خطوة DATABASE | مفتوح — مجدول |
| C5 | «A0–A12 خدمات» | فتحات عمال تابعة لـ nexus-agents (توقيع service واحد) | مصنَّف |

---

## 9. بنود UNKNOWN / NOT VERIFIED

| البند | الحالة | سبب | الوجهة |
|---|---|---|---|
| اتصال جسر MT5 الحي (EA ↔ executor) | NOT VERIFIED | `mt5:false`؛ التدقيق الحي خطوة لاحقة إلزامية | خطوة MT5 Bridge Audit |
| مطابقة DB_SCHEMA.md عمودًا-بعمود | NOT TESTED | خارج نطاق هذه الجولة | خطوة DATABASE |
| صلاحية مزود LLM خارجي (Z.ai) على المدى الطويل | NOT VERIFIED | تذبذب موثق في نافذة 5 دقائق | مراقبة + سجل عيوب P2 |
| استخدام `ibkr`/`ccxt` | NOT CONFIGURED | `false` في /health — بلا تكوين | غير ضمن نطاق M.2 (Paper/MT5 فقط) |
| محتوى `fx-trading-system-main` بالتفصيل | PARTIAL | مصنَّف unused بدليل الاستيراد؛ الجرد التفصيلي في SYSTEM_INVENTORY | الوثيقة 3/16 |

---

## 10. القرار التصنيفي النهائي (العدّ الحقيقي)

| الفئة | العدد | الأعضاء |
|---|---|---|
| **microservices (uvicorn/FastAPI)** | **9** | api 9000, data 9001, features 9002, ml 9003, agents 9004, news 9005, risk 9006, executor 9007, monitor 9008 |
| مكتبات (بلا عملية) | 1 | nexus_strategy |
| تطبيقات ويب | 1 | dashboard (Next.js 14.2.5 @3100) |
| منسِّق/مشرف | 1 | run.py |
| مُمرِّرات | 1 | port3000_forward.py (3000→3100) |
| عمال خلفيون | 13+1 | A0–A12 (داخل agents) + quality_automation (داخل data) |
| مخازن | 2 | Redis (137 مفتاحًا)، DuckDB (62 جدولًا) |
| مكونات غير مستخدمة | 1 | fx-trading-system-main |
| سكربتات مساعدة | 3 | start_all.py, bootstrap_ensemble.py, _check_db.py |

**إجمالي الكيانات الجارية الفعلية: 13 عملية** (9 خدمات + dashboard + forwarder + redis-server + run.py كمشرف إن كان حيًا) — العدد المرجعي للخدمات في كل وثائق M.2 اللاحقة هو **9**.

---

## 11. الأدلة (أوامر الجولة)

```
ss -ltnp | grep -E ':(900[0-9]|3000|3100)\b'
curl http://127.0.0.1:9004/health            # ×2 بطوابع 16:27 و16:31
for p in 9000..9008: curl :$p/health
/home/z/my-project/redis/bin/redis-cli DBSIZE / INFO keyspace / --scan / XLEN
./venv-nexus/bin/python - <<duckdb: information_schema.tables/columns على نسخة /tmp read-only>>
cat /proc/<pid>/cmdline لكل منفذ
for p in كل مسارات الواجهة: curl -o /dev/null -w %{http_code}
rg telegram_bot|metrics_exporter services/nexus_monitor/main.py run.py
```

> نهاية الوثيقة 2/16 — التالية: SYSTEM_INVENTORY.md (3/16).
