# مصفوفة الواجهة × `.env` — الحالة النهائية (Final)

> هذه المصفوفة تُعيد بناء الأقسام الثلاثة بعد التصحيحات المتفق عليها، وتُثبّت:
> تصحيح «تأكيد MTF»، وحالة `NEXUS_ALLOW_OFF_HOURS` كبذرة فقط، وقرار
> `max_daily_trades` (بدون متغيّر env جديد)، وتصنيف متغيّرات البيئة في بطاقة
> «بيئة النظام (.env)»، إضافة إلى القوالب والترجمة العربية وحالة الاختبارات.
>
> المرجع العام للأولوية: `docs\settings-precedence.md`.

---

## القسم 1 — متزامن UI ↔ env (الطرفان موجودان)

| # | حقل الواجهة (Redis key) | متغيّر env | موضعه في `.env` | طبيعة العلاقة / الأولوية |
|---|--------------------------|------------|-----------------|---------------------------|
| 1 | `off_hours_allowed` — «التداول خارج الجلسات» | `NEXUS_ALLOW_OFF_HOURS` | `.env:17` (‏`.env.example:20`) | **بذرة فقط (seed-only) — Redis يتغلب.** يُزرع في `DEFAULTS` (`shared\runtime_settings.py:82-83`)، ويُستخدم كـ `default_off_hours` فقط عند غياب المفتاح من Redis (`runtime_settings.py:428-429`، والنداء `services\nexus_risk\main.py:2513-2525`). في بطاقة البيئة: **readonly** (`env.py:181-183`). |
| 2 | `trading_mode_type` — «وضع التداول» | `NEXUS_TRADING_MODE_TYPE` | `.env:22` (‏`.env.example:26`) | قيمة تُقرأ عند الإقلاع لبناء الحالة الأولى (`services\nexus_ml\traders\trading_mode.py:734-736`)؛ الحالة الحية تُدار من الواجهة في Redis (`DEFAULTS` — `runtime_settings.py:71`). وصف الخادم: «بذرة عند الإقلاع» (`env.py:127-128`). |
| 3 | `operational_tf` — «إطار التشغيل (TF)» | `NEXUS_OPERATIONAL_TF` | `.env:23` (‏`.env.example:27`) | fallback عند الإقلاع (`services\nexus_ml\main.py:147` و `:684`)، مع تجاوز حيّ عبر Redis/`nexus:dynamic:tf` (`services\nexus_agents\main.py:419-431`). |
| 4 | `research_interval_sec` — «دورة Research» | `NEXUS_RESEARCH_INTERVAL_SEC` | `.env:72` (‏`.env.example:82`) | الـ env هو سقف احتياطي (`services\nexus_agents\main.py:50`)، **وRedis يفوز داخل الحلقة** (`main.py:699-703`). |
| 5 | `disable_research` — «إيقاف Research مؤقتًا» | `NEXUS_DISABLE_RESEARCH` | `.env:74` (‏`.env.example:84`) | قيمة env = `1` **تُوقف حلقة البحث عند الإقلاع** ولا تُرفع من الواجهة (`services\nexus_agents\main.py:52` و `:680-682`)؛ المفتاح الحي موجود في Redis (`DEFAULTS` — `runtime_settings.py:137`). |
| 6 | `strategy_min_profit_factor` — «أدنى PF» | `STRATEGY_MIN_PROFIT_FACTOR` | `.env.example:87` | الطرفان قيدان: env يُقرأ عند بناء الـ registry (`services\nexus_agents\research\registry.py:70`)، والواجهة Redis (`runtime_settings.py:138` مع حدّ `(1.0, 3.0)` في `:183`). |
| 7 | `strategy_min_win_rate` — «أدنى WR» | `STRATEGY_MIN_WIN_RATE` | `.env.example:88` | `registry.py:71` (env) مقابل `runtime_settings.py:139` (Redis). |
| 8 | `autonomous_ml` — «خط ML/DL/RL مستقل» | `NEXUS_AUTONOMOUS_ML` | `.env:96` | القراءة من env في `services\nexus_ml\traders_api.py:2881`؛ القيمة الحية في `runtime_settings.py:109` وتُعرض من الواجهة. |

### ⚠️ تصحيحات ملزِمة على هذا القسم

1. **«تأكيد MTF» ليست مشتقة من `NEXUS_OHLCV_TIMEFRAME`.**
   - حقول MTF في الواجهة: `require_mtf_confirmation` + `min_mtf_agreement`
     (`dashboard\src\app\dashboard\settings\page.tsx:54-55`) وهما **Redis only**
     (`shared\runtime_settings.py:67-68`).
   - `NEXUS_OHLCV_TIMEFRAME` تخص **الشموع المخزَّنة (stored candles)** وتُقرأ في
     `services\nexus_data\main.py:328` — لا علاقة لها ببوابة تأكيد الأطر العليا.
   - لذلك سطر المصفوفة القديم «‏Confirmación MTF ← `NEXUS_OHLCV_TIMEFRAME`»
     **ملغٍ**.
2. **`NEXUS_ALLOW_OFF_HOURS` ليست مزامنة ثنائي الاتجاه** — بذرة فقط، وRedis يتغلب
   (الصف 1 أعلاه).

---

## القسم 2 — حقول الواجهة بدون env (هذا **بالتصميم** — By Design)

**لماذا لا يوجد لها متغيّر env؟** لأنها **إعدادات تشغيلية حية (live runtime settings)**
تُخزَّن في Redis تحت `nexus:runtime:settings` وتُعدَّل من الواجهة **دون restart**؛
وجودها في `.env` كان سيخلق مصدرين متعارضين ويقتل ميزة التعديل الفوري. كلها مضمونة
بقيمة افتراضية في `DEFAULTS` حتى لا يظهر أي حقل فارغ
(عقد الاختبار: `tests\test_settings_contract.py:1123-1130`).

**القيم الافتراضية من `shared\runtime_settings.py` (‏`DEFAULTS` = 54 مفتاحًا، السطور 49-141):**

| قسم الواجهة | الحقل (Redis key) | الافتراضي | السطر |
|-------------|-------------------|-----------|-------|
| نواة التداول | `auto_tf_selection` | `True` | `:73` |
| نواة التداول | `require_mtf_confirmation` | `True` | `:67` |
| نواة التداول | `min_mtf_agreement` | `1` | `:68` |
| نواة التداول | **`max_daily_trades`** | **`5`** | **`:56`** |
| المخاطرة والحجم | `risk_per_trade_pct` | `1.0` | `:51` |
| المخاطرة والحجم | `max_spread_pips` | `3.0` | `:99` |
| المخاطرة والحجم | `sl_atr_multiplier` | `1.5` | `:100` |
| المخاطرة والحجم | `tp_atr_multiplier` | `3.0` | `:101` |
| المخاطرة والحجم | `min_rr_ratio` | `1.5` | `:102` |
| المخاطرة والحجم | `max_hold_bars` | `50` | `:103` |
| المخاطرة والحجم | `cooling_off_streak` | `3` | `:104` |
| المخاطرة والحجم | `sl_floor_atr_mult` | `2.5` | `:105` |
| المخاطرة والحجم | `entry_displacement_atr_mult` | `2.0` | `:106` |
| المخاطرة والحجم | `max_daily_loss_pct` / `max_weekly_dd_pct` | `20.0` / `25.0` | `:52` / `:53` |
| الإشارات والجودة | `quality_score_threshold` | `0` (ديناميكي) | `:108` |
| الإشارات والجودة | `min_conviction_override` | `None` (ديناميكي) | `:61` |
| الإشارات والجودة | `pre_signal_spread_filter` | `True` | `:110` |
| الإشارات والجودة | `signal_cooldown_sec` | `60` | `:111` |
| الإشارات والجودة | `min_confidence_floor` | `0.40` | `:112` |
| الإشارات والجودة | `conviction_min` | `0.55` | `:113` |
| النماذج والتدريب | `retrain_interval_hours` | `4` | `:115` |
| النماذج والتدريب | `outcome_weight` | `5` | `:116` |
| النماذج والتدريب | `allow_synthetic_training` | `False` | `:117` |
| النماذج والتدريب | `dl_seq_len` | `30` | `:118` |
| النماذج والتدريب | `dl_confidence_threshold` | `0.45` | `:119` |
| النماذج والتدريب | `rl_n_epochs` | `15` | `:120` |
| الإشعارات | `notif_enable_browser` | `False` | `:122` |
| الإشعارات | `notif_blackout` | `False` | `:123` |
| الإشعارات | `notif_brief` | `False` | `:124` |
| الإشعارات | `notif_corr_divergence` | `False` | `:125` |
| الارتباط | `corr_refresh_sec` | `300` | `:127` |
| الارتباط | `corr_divergence_threshold` | `0.25` | `:128` |
| الارتباط | `corr_window_default` | `"7d"` | `:129` |
| ذاكرة الصفقات | `trade_memory_window` | `200` | `:131` |
| ذاكرة الصفقات | `cooling_off_duration_sec` | `300` | `:132` |
| الاختبار الخلفي | `backtest_initial_equity` | `5000` | `:134` |
| الاختبار الخلفي | `backtest_default_symbol` | `"XAUUSD"` | `:135` |
| GenAI والبحث | `genai_max_calls_per_hour` | `30` | `:140` |

**الصف الخاص بقرار `max_daily_trades`:**

| الحقل | الافتراضي | القرار المسجَّل |
|-------|-----------|-----------------|
| `max_daily_trades` | **`5`** (`shared\runtime_settings.py:56`) | **لا يوجد متغيّر `NEXUS_MAX_TRADES_PER_DAY`** — لم يُضَف إلى `.env` ولا إلى allowlist (`env.py:119-196`). الرقم **7** الظاهر في الواجهة هو **قيمة Redis حيّة (live override)** وليست افتراضيًا ولا قيمة env. |

> ملاحظتان:
> - `llm_provider` موجودة في `DEFAULTS` (`runtime_settings.py:76`) لكنها **ليس لها حقل
>   في `RUNTIME_SECTIONS`**؛ المقابل العملي لها هو متغيّر env `NEXUS_LLM_PROVIDER`
>   (القسم 3).
> - `allow_synthetic_training` لها شبح twin في env باسم `NEXUS_ALLOW_SYNTHETIC_TRAINING`
>   (danger — `env.py:171-172`) لكن **لا يوجد مستهلك تشغيلي له في الكود**؛ القيمة
>   الفعلية تبقى ما يُحفظ في Redis.

---

## القسم 3 — متغيّرات env غير الظاهرة سابقًا (تصنيف بطاقة البيئة)

التصنيف مأخوذ من allowlist الخادم `services\nexus_api\routers\env.py:119-196`،
والواجهة تجمّعه ديناميكيًا من الـ `category` بلا قائمة مُصلَّدة
(`page.tsx:537-545`).

### 3أ) بطاقة البيئة الأساسية (Core — 27 متغيّرًا، قابلة للتعديل)

| المتغيّر | الوصف في الخادم |
|----------|-----------------|
| `NEXUS_ENV` | بيئة التشغيل (`development`/`staging`/`production`) |
| `NEXUS_MIN_VERDICT_CONVICTION` | أدنى conviction لتنفيذ الصفقة (scalping) |
| `NEXUS_CONFLICT_LOCK_CONVICTION` | عند بلوغ الطرفين هذا الحد تُفرض NO_TRADE |
| `NEXUS_TRADING_MODE_TYPE` | وضع النموذج الأساسي (بذرة عند الإقلاع) |
| `NEXUS_OPERATIONAL_TF` | الإطار الزمني التشغيلي (بذرة عند الإقلاع) |
| `NEXUS_RESEARCH_INTERVAL_SEC` | دورة البحث عن الاستراتيجيات (ثوانٍ) |
| `NEXUS_RESEARCH_BATCH` | عدد الرموز في كل دورة بحث |
| `NEXUS_RESEARCH_SYMBOL` | الرمز البحث الأساسي |
| `NEXUS_DISABLE_RESEARCH` | إيقاف البحث عن استراتيجيات جديدة |
| `STRATEGY_MIN_PROFIT_FACTOR` | أدنى Profit Factor لترقية استراتيجية |
| `STRATEGY_MIN_WIN_RATE` | أدنى Win Rate لترقية استراتيجية |
| `STRATEGY_MIN_SHARPE` | أدنى Sharpe ratio |
| `STRATEGY_MAX_DD_PCT` | أقصى تراجع مسموح DD% |
| `STRATEGY_MIN_TRADES` | أقل عدد صفقات لاعتماد استراتيجية |
| `STRATEGY_MIN_NET_PNL_PCT` | أدنى ربح صافي مئوي |
| `NEXUS_ML_PRIORITY` | أولوية ML مقابل وكلاء GenAI (`0`/`1`) |
| `NEXUS_ACTIVE_SIGNAL_TTL` | صلاحية الإشارة النشطة (ثوانٍ) |
| `NEXUS_AUTONOMOUS_ML` | تشغيل خط ML مستقل |
| `NEXUS_LLM_HEALTH_TIMEOUT_SEC` | مهلة صحة الـ LLM (ثوانٍ) |
| `NEXUS_LLM_PROVIDER` | مزود الذكاء الاصطناعي (`deepseek`/`openai`/`gemini`/`local`) |
| `NEXUS_LLM_MODEL` | اسم النموذج (مثال: `qwen2.5:3b`) — القيمة الحالية في `.env:97` |
| `NEXUS_LOCAL_LLM_URL` | عنوان خادم Ollama المحلي |
| `NEXUS_LOCAL_MODEL` | نموذج Ollama المحلي |
| `IBKR_HOST` / `IBKR_PORT` | مضيف ومنفذ Interactive Brokers |
| `MLFLOW_TRACKING_URI` | عنوان MLflow |
| `MODEL_DIR` | مجلد تخزين النماذج |

### 3ب) خطير (Danger — 6، تعديلها يحتاج تأكيدًا)

| المتغيّر | التحذير العربي في الخادم |
|----------|--------------------------|
| `NEXUS_AGGRESSIVE_TRADING` | «لا تفعّل مع حساب حقيقي» |
| `NEXUS_DATA_SYNTHETIC_FALLBACK` | «1 = بيانات وهمية بدل MT5 الحقيقي» |
| `NEXUS_ALLOW_SYNTHETIC_METRICS` | «لا تستخدم مع نتائج حقيقية» |
| `NEXUS_ALLOW_SYNTHETIC_TRAINING` | «يفسد تدريب النماذج على بيانات حقيقية» |
| `NEXUS_DUCKDB_ALLOW_SECONDARY_WRITER` | «قد يسبب تعارض كتابة البيانات» |
| `NEXUS_MT5_ISOLATED` | «غيّر فقط إذا أدرت لماذا» |

الواجهة تُظهر `window.confirm` قبل الحفظ (`page.tsx:500-506`) وتلوّن الصف بالأحمر
(`page.tsx:1175-1179`).

### 3ج) للقراءة فقط (Read-only — 8، `editable: false`)

| المتغيّر | سبب القفل |
|----------|-----------|
| `NEXUS_TRADING_MODE` | التبديل عبر `--live --confirm-live` فقط |
| `NEXUS_ALLOW_OFF_HOURS` | **بذرة فقط** — بوابة الجلسات المفروضة في Redis تتغلب |
| `DUCKDB_PATH` | مسار قاعدة البيانات |
| `REDIS_URL` | عنوان Redis |
| `MT5_LOGIN` / `MT5_SERVER` | بيانات حساب/خادم الوسيط |
| `NEXUS_MT5_SESSION_EXPORT_PATH` | مسار تصدير جلسات MT5 |
| `NEXUS_BROKER_CALENDAR_POLICY_PATH` | مسار سياسة التقويم |

### 3د) أسرار محجوبة (Secrets — 12، لا تُقرأ ولا تُعدَّل أبدًا)

`NEXUS_PIN`, `NEXUS_SECRET_KEY`, `NEXUS_JWT_SECRET`, `NEXUS_INTERNAL_API_SECRET`,
`NEXUS_ADMIN_PIN`, `NEXUS_RISK_APPROVAL_SECRET`, `MT5_PASSWORD`, `DEEPSEEK_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `NEWSAPI_KEY`, `GNEWS_KEY`

- القائمة مُثبتة بـ `assert len(_DENY) == 12` (`env.py:55-70`).
- لا يظهر مفتاحها ولا قيمتها في استجابة `GET /api/system/env`
  (`env.py:9-11` و `:261-286`)، وأي محاولة كتابة تُرفض برسالة موحّدة (`env.py:462-463`).
- العدّاد يظهر في الواجهة كـ «🛡️ 12 متغيّرات أسرار محمية» (`page.tsx:1115-1120`).

### ملاحظات تشغيلية على القسم 3

- **كل كتابة عبر البطاقة تتطلب restart كامل** (`restart_required: true` —
  `env.py:101`, `:484`؛ والواجهة تُظهر شارة «⏳ يتطلب إعادة تشغيل»
  `page.tsx:511-512`, `:1122-1129`).
- **نسخة احتياطية قبل أي كتابة**: `.env.bak.<UTC yyyymmdd_HHMMSS>`، وفشل النسخ
  يعني `503` دون أي تعديل (`env.py:356-367`).
- **الكتابة ذرّية**: استبدال سطر `KEY=` فقط مع الحفاظ على الترتيب والتعليقات ونهايات
  الأسطر (`env.py:401-447`).
- **إعادة التشغيل غير مسموحة دون إذن المشغّل** (نص البطاقة `page.tsx:1110-1111`).

---

## القوالب (Settings Templates)

| الجانب | التفاصيل |
|--------|----------|
| Endpoint | `GET /api/intelligence/settings/templates` · `POST …/templates/save` · `POST …/templates/load` (`services\nexus_api\routers\intelligence.py:492`, `:540`, `:591`) |
| مجلد التخزين | `config\settings_templates\` (`intelligence.py:433`) — موجود فيه `optimal.json` |
| بطاقة الواجهة | `id="templates"` — «قوالب الإعدادات (Templates)» (`page.tsx:809-926`) |
| نموذج العمل | **تعبئة النموذج فقط (fill-only)** — لا يُكتب شيء قبل «حفظ الكل» (`page.tsx:814-817`, `:341-350`) |
| فتح ملف من الجهاز | file picker محلي `.json` بحد أقصى 1MB، بلا رفع (`page.tsx:412-445`) |
| لقطة التراجع | `nexus:runtime:settings:last` تُلتقط قبل كل حفظ (`intelligence.py:412`, `:434`) وتُستدعى من زر «آخر إعدادات (تراجع)» (`page.tsx:375-382`, `:886-899`) |
| الحماية | منع path traversal (`intelligence.py:603-606`)، تسمية عربية مسموحة (`:437`)، وتمرير عبر `sanitize_patch` + `DEFAULTS` (`:565`) |

---

## الترجمة العربية للواجهة (UI Localization)

- **عناوين وأوصاف حقول الإعدادات كلها عربية** داخل `RUNTIME_SECTIONS`
  (`page.tsx:44-162`) — من «نواة التداول (Trading Core)» إلى «وكيل GenAI والبحث».
- **بطاقة البيئة عربية** في نصّها وتنبيهاتها (`page.tsx:1102-1235`)، بينما تصل
  **أوصاف المتغيّرات من الخادم بالعربية** (`env.py:119-196`)، والرفض موحّد برسالة عربية
  (`env.py:51`).
- **رسائل القوالب عربية** في الواجهة (`page.tsx:345`, `:360`, `:367-371`, `:387`) وفي
  الخادم (`intelligence.py:552`, `:564`, `:586`, `:601`, `:606`, `:608`).
- القيم التقنية تبقى **إنجليزية عمداً** لأنها قيم يقارنها الخادم حرفيًا
  (جلسات التداول `SESSION_CHOICES` — `page.tsx:183-185`).

---

## حالة الاختبارات (Tests)

| الملف | العدد | الحالة |
|-------|-------|--------|
| `tests\test_settings_contract.py` | **103** | ✅ أخضر |
| `tests\test_settings_templates.py` | **23** | ✅ أخضر |
| **المجموع** | **126** | ✅ **126 passed** |
| `tests\test_config_contract.py` + `tests\test_preflight.py` | 25 | ✅ أخضر بعد تعديل `.env.example` (أمر التحقّق المطلوب، exit code 0) |

ملاحظات:
- المذكرة السابقة ذكرت `101` لـ `test_settings_contract.py`؛ العدد الفعلي اليوم **103**،
  والمجموع المعتمد **126** كما هو متفق عليه.
- **ملاحظة سائدة قبل هذه الجولة (ليست من تعديلاتي):** `tests\test_env_api.py` = 22/23،
  ويفشل فيها `test_get_route_carries_the_settings_read_dependency` بسبب
  `'Dependant' object has no attribute 'dependency'` (عدم توافق إصدار FastAPI في
  هذا الاختبار تحديدًا) — لا علاقة له بالمستندات ولا بتعديل `.env.example`.
