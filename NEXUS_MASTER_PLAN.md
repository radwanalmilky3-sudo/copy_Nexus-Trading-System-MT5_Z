# NEXUS_MASTER_PLAN — الدستور والخطة الشاملة لسد الفجوات

**المؤلف:** A0 (Swarm Director) | **التاريخ:** 2026-10-17 | **الحالة:** 🟡 مُسلَّمة — بانتظار الموافقة — **لا تنفيذ**
**الأساس:** غوص مرجعي مباشر من 9 وكلاء (A1–A9) على ملفات `fx-trading-system-main` + تقارير `project_audit/` السابقة + تحقق مباشر من مسارات Nexus.

> **إفصاح عن أداة التنسيق:** طُلب Ruflo MCP (`npx ruflo@latest mcp start`). الفحص: (1) `.mcp.json` يعرِّف الخادم لكن `autoStart:false` وأدواته غير مسجلة في هذه الجلسة؛ (2) CLI `npx -y ruflo@latest --version|mcp start` معلّق (timeout 30–45s). **الحكم: Ruflo فشل فعليًا** → نُفِّذ السرب بالبديل المصرَّح به (Task المتوازئ: A0 + A1–A9). إعادة تجربة Ruflo موصى بها في جلسة قادمة بعد إصلاح التسجيل.

---

## 1. الدستور (Constitution)

### 1.1 المبادئ التي لا تُخَالف

| # | المبدأ | المصدر |
|---|---|---|
| C1 | **لا حذف** أي ملف أو جدول أو عمود | طلب المستخدم |
| C2 | **لا تغيير معمارية**: Redis + DuckDB + FastAPI + 9 خدمات + Next.js كما هي | طلب المستخدم |
| C3 | **كل حقل جديد NULL/فارغ افتراضيًا** — السلوك القديم هو الافتراضية | طلب المستخدم |
| C4 | **التغيير إضافي فقط** (Additive): أعمدة، جداول، وحدات، حالات enum مُضافة، نقاط استدعاء — لا استبدال مسارات حيوية | طلب المستخدم |
| C5 | **Fail-closed عند الشك**: غياب البيانات الجديدة ⇒ رفض مُعلَّم أو تجاهل آمن، لا تقدير صامت | المرجع (A5/A4) |
| C6 | **قرار المخاطر لا يتغير ذرّة** إذا كانت الحقول الجديدة غائبة (golden-decision diff) | A8 |
| C7 | **التوثيق يسافر مع البيانات**: provenance/quality/available_at كحقول، لا تعليقات | A1/A2 |
| C8 | paper/live: الوضع الحالي على مستوى العملية يبقى؛ أي ترقية استراتيجية تمر ورقة أولًا | A9 |

### 1.2 الفجوات المؤكدة (خريطة السرب)

| # | الفجوة | الخطورة | المصدر |
|---|---|---|---|
| G1 | لا `available_at`/as-of/fingerprint لبيانات السوق — backtest يرى "المخزن الآن" | عالية | A1, A7 |
| G2 | `quality/validators.py` موجود لكن **صفر استدعاء**؛ كل صف `quality='ok'` افتراضيًا | عالية | A7 |
| G3 | لا هاشات/manifests؛ `WHERE NOT EXISTS` يهمل شمعة صحّحها البروكر (first-write-wins) | عالية | A7 |
| G4 | لا ميزانية مخاطر محفظة (كل صفقة ضد الرصيد الكامل)؛ لا drawdown من القمة؛ `weekly_dd_pct` يُكتب 0 دائمًا؛ `correlation_exposure`=0.0 مضبوط | عالية | A4, A8 |
| G5 | قواطع `get_active_circuit_breakers` تhardcode `triggered:False`؛ `reset-day` بلا سجل تدقيق | متوسطة | A8 |
| G6 | blackout بلا جودة توقيت: timestamp بدائي يعامَل كـ UTC مؤكد؛ لا date-only = يوم كامل؛ لا إلغاء/خلاف | متوسطة-عالية | A2 |
| G7 | `SignalEvent` بلا ATR/SL/TP/holding/group_id؛ backtest يفترض مضاعفات تختلف عن الحي | عالية | A3, A9 |
| G8 | ترقية LLM إلى `active` بنافذة داخلية واحدة (PF≥1.4/WR≥0.52/Sharpe≥0.8) — آلة overfit؛ لا shadow/paper | عالية | A9 |
| G9 | لا FDR/deflated-Sharpe/سجل تجارب؛ `evaluate_promotion` على accuracy/log-loss فقط | عالية | A5, A9 |
| G10 | `.env` بلا تحقق حدود/ enums/ invariants (ورقة⇒مفعّلة)؛ run.py يفحص 5 مفاتيح فقط | متوسطة | A6 |

### 1.3 الحلول (ملخص)

PIT/as-of + fingerprint (G1) ← ربط validators + quarantine (G2) ← مانيفست/مراجعات (G3) ← ميزانية محفظة + peak-DD + قواطع صادقة (G4/G5) ← timing_quality + blackout صارم (G6) ← عقد إشارة اختياري + دورة shadow/paper (G7/G8) ← سجل تجارب + FDR gates (G9) ← عقد تكوين preflight (G10).

---

## 2. خطة المراحل (المرحلة صفر → السادسة)

كل مرحلة: مُستقلة قابلة للتفعيل، لا تكسر السابق، وتخرج بـ acceptance suite أخضر. **لا تنفيذ قبل موافقة صريحة على هذه الخطة.**

### المرحلة صفر — الأساس وشبكة الأمان (≈ يوم–يومان)
**الهدف:** قياس خط الأساس قبل أي لمسة.
- **0.1** نسخة Git احتياطية + تشغيل كامل لحزمة الاختبارات وتسجيل النتيجة (baseline).
- **0.2** تسجيل "قرارات ذهبية" للمخاطر: fixture طلبات معروفة → ملف JSON لتوقع APPROVE/REJECT (يُستخدم في كل مرحلة لاحقة).
- **0.3** إضافة مفاتيح أعلام تفعيل افتراضية `warn`/`off`: `NEXUS_CONFIG_CONTRACT=warn`, `NEXUS_PIT_ENABLED=`, `NEXUS_RISK_PORTFOLIO_GATES=` (فارغ = معطّل).
- **0.4** تشغيل ترحيل موجود غير مستخدم إن وُجد (`migrations/research_lineage_001.sql` — جداول quality_runs/quarantine/lineage) عبر `CREATE TABLE IF NOT EXISTS` فقط.
- **لا تغيير سلوك إطلاقًا.**

### المرحلة 1 — سلامة البيانات الحيّة (≈ 2–3 أيام) — G2
**الهدف:** validators تعمل فعليًا على المسار الحي.
- ربط `validate_ohlcv` / `validate_ticks` داخل `write_ohlcv*` ومسار التِك قبل INSERT.
- دفعة تفشل فحوصات → **لا تُكتب بـ `quality='ok'`**: إما حفظ بـ `quality != 'ok'` أو حجر مع سجل quarantine.
- أعمدة تِك إضافية `source/quality/fetched_at` (NULL افتراضيًا) + هامش params على دوال الكتابة.
- وسم صناعي داخل الاستجابة: صفوف synthetic تحمل `source='synthetic'` صريحًا (لا سجلات فقط).
- **البوابة:** دفعة ملوّثة لا تظهر نظيفة؛ الاختبارات القديمة خضراء.

### المرحلة 2 — نقطة في الزمن (PIT / As-of) (≈ 3–4 أيام) — G1, G3
**الهدف:** أي استعلام تاريخي يرى "ما كان متاحًا وقتها".
- `ALTER TABLE ohlcv/ticks ADD COLUMN IF NOT EXISTS available_at TIMESTAMPTZ NULL`؛ الكتابة المستقبلية تملأ `available_at=CURRENT_TIMESTAMP` (أو `fetched_at`).
- امتداد `query_ohlcv(..., available_through=None, max_staleness_s=None)` → `WHERE available_at <= ?`؛ بدون المعاملات = السلوك الحرفي كما اليوم.
- endpoint إضافي `GET .../pit?available_through=` + `fingerprint_ohlcv(symbol, timeframe, available_through)` (SHA فوق الصفوف المتاحة فقط).
- مراجعات: عند خلاف شمعة مكتملة مخزنة → `UPDATE` مع `revision = COALESCE(revision,0)+1` (لا حذف صف أبدًا).
- جدول `ohlcv_manifests` (`CREATE TABLE IF NOT EXISTS`): صفوف/timeframe + row_count + content_hash.
- **البوابة:** fingerprint يتغيّر عند وصول صف متأخر؛ PIT يستبعد الصفوف غير المتاحة؛ بدون معاملات = byte-identical.

### المرحلة 3 — المخاطر المحفظية والقواطع الصادقة (≈ 4–5 أيام) — G4, G5
**الهدف:** حماية محفظة حقيقية + تقارير breaker صادقة.
- **قمة equity:** مفتاح Redis `nexus:risk:equity_peak` (+ يوم) يُحدَّث في account-sync (نمط `_DAY_START_BALANCE`)؛ حساب `dd_from_peak_pct`.
- **weekly DD حقيقي:** تغذية `weekly_dd_pct` من سلسلة 7 أيام (يوقف الزخرفة).
- **ميزانية مفتوحة:** `Σ(open lots × risk/lot)` مقابل `equity × max_portfolio_open_risk_pct`؛ الحجم الجديد يُقاس ضد **المتبقي**.
- **cfg جديد بقيم None** في `RulesEngineConfig` (يُتخطى الفحص عند None): `max_drawdown_from_peak_pct`, `max_portfolio_open_risk_pct`, `max_gross_leverage`, `max_net_currency_exposure_pct`, `correlation_threshold`, `correlation_lookback_bars`, `max_same_direction_cluster`.
- ترتيب البوابات (يُدرج بعد daily/weekly): peak-DD ← open-risk ← gross-leverage (اختياري).
- **صدق القواطع:** `get_active_circuit_breakers` يقرأ الحالة الفعلية بدل `triggered:False` المضبوط.
- **تدقيق إعادة الضبط:** جدول `risk_reset_audit` (`CREATE TABLE IF NOT EXISTS`، أعمدة NULL) يُكتب عند `reset-day` (caller, ts, قيم ما قبل المسح).
- **البوابة:** configs غائبة ⇒ قرارات ذهبية مطابقة 100%؛ peak ينجو من إعادة التشغيل؛ reset-day يترك أثرًا.

### المرحلة 4 — أحداث و blackout صارم (≈ 2–3 أيام) — G6
**الهدف:** لا يُتداول على توقيت غير موثّق.
- أعمدة إضافية على `fund_events` (`ALTER ... IF NOT NULL`): `timing_quality`, `authority`, `release_tzid`, `decision_date_local`, `scheduled_status`, `supersedes_event_id`, `cancelled`, `source_sha256`, `retrieved_at_utc`.
- enum إضافي `timing_quality` (5 قيم مرجعية) + `scheduled_status` += `unknown` للـ legacy.
- قواعد: حدث date-only (عالي/متوسط الأثر) → حجب **اليوم المدني كاملًا** بمنطقة IANA للحدث (لا دقيقة مخترعة)؛ `timing_quality` غائب/NULL → حالة `unverified_timing` (≠ clear ⇒ يمنع التداول)؛ ملغي/خلاف → append-only، لا صمت "صافي".
- أعمدة إضافية على نوافذ الحجب + `reason_code` += `DATE_ONLY_DAY_BLACKOUT|EVENT_CANCELLED|TIMING_UNVERIFIED`.
- **بوابة:** payload قديم بلا حقول جديدة ⇒ سلوك حرفي؛ high-impact بلا توقيت موثّق ⇒ مقاومة تداول.

### المرحلة 5 — عقد الإشارة ودورة الحياة والإحصاء (≈ 5–7 أيام) — G7, G8, G9
**الهدف:** إشارات محمولة بالمخاطر + ترقية لا تنطلي على overfit.
**5أ — عقد الإشارة (≈ 3 أيام):**
- `shared/events.py` + `shared/research_contracts.py`: حقول اختيارية `atr, stop_atr, target_atr, max_holding_hours, group_id: None` + `reason: ""`.
- executor: إذا الحقول non-NULL وatr>0 → SL/TP من مضاعفات ATR؛ وإلا المسار الحالي حرفيًا.
- ناشرو ML/الوكلاء يملؤون عند التوفر ويتركون None عند الغياب؛ backtesters تفضّل مخاطر الإشارة إن وُجدت.
**5ب — دورة الحياة (≈ 3 أيام):**
- `ALL_STATUSES` += `("shadow","paper")` في `registry.py`؛ `active` غير قابلة للوصول من نافذة واحدة: تتطلب `paper_trades/paper_pf/paper_wr` غير NULL وناجحة؛ NULL ⇒ رفض `paper_metrics_missing`.
- وحدة جديدة `research/paper_tracker.py` + جدول `strategy_paper_fills` (`CREATE TABLE IF NOT EXISTS`).
**5ج — إحصاء صادق (≈ 3 أيام):**
- وحدة جديدة `services/nexus_ml/statistical_gates.py`: BH/BY q-values، `minimum_resamples_for_fdr`، gate DSR اختياري.
- جدول `research_trials` (DuckDB, NULL defaults): trial_id/family_id/p_value/q_value/total_trials/...
- خطّاف في `evaluate_promotion`: بعد الفحوصات الحالية وقبل القبول — عائلة مُفصح عنها + q ≤ FDR؛ غياب السجل ⇒ رفض `trial_universe_undisclosed` (fail-closed).
- evaluator: طيّات purged (embargo = max-holding، label-end purge) مع fallback للنافذة الواحدة عند قلة البيانات؛ عدّ تجارب في السجل.
- **بوابة:** `active` بلا ورق ⇒ فشل؛ إشارة بلا حقول مخاطر ⇒ سلوك اليوم؛ عائلة غير مُفصح ⇒ رفض ترقية.

### المرحلة 6 — عقد التكوين والمصادقة النهائية (≈ 3–4 أيام) — G10 + إغلاق
**الهدف:** إعدادات مُتحقَّق منها + إثبات عدم انهيار النظام.
- وحدة جديدة `shared/config_contract.py` (pydantic, Optional=None): enums مغلقة (`NEXUS_TRADING_MODE: Literal["paper","live"]`)، حدود (`NEXUS_RISK_PER_TRADE: Field(None, gt=0, le=0.02)` …)، invariants: ورقة⇒auto_trade، سرّ الموافقة ≠ السرّ الداخلي، فريدة المنافذ.
- خطّاف في `run.py` بعد `_validate_env`: `validate_config_contract` — `NEXUS_CONFIG_CONTRACT=warn|enforce` (الافتراضي warn = لا كسر).
- `.env.example`: مفاتيح اختيارية معلَّقة بقيم فارغة.
- **المصادقة النهائية:** (أ) golden-decision diff أخضر لكل المراحل؛ (ب) حزمة الاختبارات كاملة؛ (ج) اختبارات القبول لكل مرحلة؛ (د) قياس صحة `/health` للخدمات التسع + الواجهة بعد الرفع.

**المدة الإجمالية التقديرية: 20–27 يوم عمل (~5–6 أسابيع).** تسلسل مقترح: 0 → 1 → 2 → 3 → 4 → 5 → 6 (السلامة أولًا، ثم البيانات، ثم المخاطر، ثم البحث، ثم التغليف).

---

## 3. خريطة الملفات (File Map)

### 3.1 ملفات جديدة (إضافة فقط)

| الملف | المحتوى | المرحلة |
|---|---|---|
| `services/nexus_data/migrations/pit_availability_001.sql` | ALTER ohlcv/ticks + available_at + جدول manifests | 2 |
| `services/nexus_ml/statistical_gates.py` | BH/BY/min-resamples/DSR gates | 5ج |
| `services/nexus_data/trial_registry.py` | إنشاء/إدراج/قراءة `research_trials` | 5ج |
| `services/nexus_agents/research/paper_tracker.py` | تتبّع صفقات الظل/الورق | 5ب |
| `shared/config_contract.py` | عقد pydantic للبيئة | 6 |
| `tests/test_data/test_pit_availability.py`, `tests/test_data/test_quality_gate.py`, `tests/test_risk/test_portfolio_gates.py`, `tests/test_news/test_timing_quality.py`, `tests/test_ml/test_statistical_gates.py`, `tests/test_agents/test_paper_lifecycle.py`, `tests/test_config_contract.py` | اختبارات القبول | مع كل مرحلة |

### 3.2 ملفات معدَّلة (تغييرات إضافية فقط — لا حذف، لا استبدال مسار حي)

| الملف | الإضافة الدقيقة | المرحلة |
|---|---|---|
| `services/nexus_data/duckdb_store.py` | استدعاء validators في write؛ أعمدة ticks؛ available_at؛ revision في فرع التعارض؛ fingerprint؛ manifests | 1–2 |
| `services/nexus_data/main.py` | params اختيارية على الاستعلامات؛ endpoint pit/fingerprint؛ عدّادات quarantine على provenance | 1–2 |
| `services/nexus_data/fundamental_store.py` | تطبيق ترحيلات fund_events الجديدة | 4 |
| `services/nexus_data/fundamental_schema.sql` | ALTER إضافية (timing_quality…) | 4 |
| `services/nexus_risk/main.py` | equity_peak في account-sync (+restore)؛ weekly_dd حقيقي؛ clamp في site الحجم (~1165–1214)؛ reset-day → audit row؛ قراءة قواطع حقيقية؛ correlation_exposure حقيقي خلف cfg | 3 |
| `services/nexus_risk/rules_engine.py` | حقول cfg بـ None؛ `check_drawdown_from_peak` + `check_portfolio_open_risk` (مُدرجة بعد daily/weekly)؛ إصلاح صفوف breaker | 3 |
| `config/risk_rules.yaml` | مفاتيح `capital:` اختيارية فقط | 3 |
| `services/nexus_news/fundamental/blackout.py` | timing_quality؛ date-only → يوم كامل IANA؛ unverified_timing؛ reason codes | 4 |
| `services/nexus_news/fundamental/runtime.py` | تمرير الحقول الجديدة/الحالات | 4 |
| `shared/events.py` | حقول SignalEvent اختيارية (None) | 5أ |
| `shared/research_contracts.py` | mirror اختياري على SignalContract | 5أ |
| `services/nexus_ml/main.py` | تعبئة حقول الإشارة عند التوفر | 5أ |
| `services/nexus_ml/model_promotion.py` | خطّاف FDR/trials قبل accepted=True (لا تغيير التوقيع) | 5ج |
| `services/nexus_ml/backtester.py` + `traders/sl_tp_backtester.py` | تفضيل مخاطر الإشارة عند non-NULL | 5أ |
| `services/nexus_agents/main.py` | تمرير حقول المخاطر في سياق التقييم | 5أ |
| `services/nexus_agents/research/registry.py` | statuses += shadow/paper؛ حقول تخرّج NULL؛ عدّ تجارب؛ بوابة active | 5ب |
| `services/nexus_agents/research/researcher.py` | مسار backtested→shadow بدل active مباشرة | 5ب |
| `services/nexus_agents/research/evaluator.py` | طيّات purged + fallback نافذة واحدة | 5ج |
| `services/nexus_executor/main.py` | SL/TP من ATR عند non-NULL فقط | 5أ |
| `run.py` | استدعاء config_contract (warn افتراضيًا) | 6 |
| `.env.example` | مفاتيح اختيارية معلَّقة | 6 |

### 3.3 جداول DuckDB جديدة (كلها `CREATE TABLE IF NOT EXISTS`، أعمدة قابلة لل)NULL

| الجدول | غرض | المرحلة |
|---|---|---|
| `ohlcv_manifests` | hash + row_count لكل (symbol, timeframe) | 2 |
| `bar_revisions` أو عمود `revision` | تتبّع إصلاحات الشموع | 2 |
| `quarantine` / `quality_runs` / `lineage` | موجودة في research_lineage_001.sql — تُفعَّل فقط | 0 |
| `risk_reset_audit` | تدقيق reset-day | 3 |
| `research_trials` | عائلات FDR وتجارب | 5ج |
| `strategy_paper_fills` | تتبّع ورقة التخرج | 5ب |

### 3.4 مفاتيح Redis جديدة (اختيارية، افتراضيًا معطّلة)

`nexus:risk:equity_peak` (+`_day`)، `nexus:risk:equity_series` (7 أيام)، `nexus:risk:reset_audit`، `nexus:risk:open_risk_snapshot`.

---

## 4. قائمة الامتثال للقيود

| القيد | الحالة |
|---|---|
| لا حذف ملف/جدول | ✅ كل التغييرات ADD/ALTER/CREATE IF NOT EXISTS أو إضافات اختيارية |
| لا تغيير معمارية | ✅ Redis+DuckDB+FastAPI+run.py orchestration كما هي؛ لا خدمة جديدة إلزامية (الوحدات الجديدة داخل الخدمات الحالية) |
| حقول جديدة NULL افتراضيًا | ✅ كل الأعمدة/الحقول/حالات cfg بقيم None/NULL/فارغ؛ الغياب = تجاهل آمن |
| تغيير إضافي فقط | ✅ لا مسار حي يُستبدل؛ كل استدعاء جديد خلف شرط/flag |
| قرارات المخاطر ثابتة عند الغياب | ✅ golden-decision diff في المراحل 0/3/6 |

---

## 5. ما لم يُطلب (خارج النطاق — يُناقش لاحقًا)

- مسار أفق بطيء (NY-close / تعدد الجلسات) — أرشيف أبحاث المرجع، غير ضروري لعمليات scalping الحالية.
- Hansen SPA كامل — يُضاف لاحقًا فوق statistical_gates إن لزم.
- تغييرات dashboard كبيرة — التقارير الجديدة تُعرض عبر endpoints الحالية.

---

## 6. الخطوة التالية

**الخطة جاهزة. لا تنفيذ تم.** أنتظر موافقتك:
- ✅ موافقة كاملة → أبدأ **المرحلة صفر** فورًا.
- ✏️ تعديل مرحلة/أولوية/مدة → أعدّل الخطة قبل أي لمسة.
- ❓ استفسار على أي بند → أُفصِّل من ملفات `project_audit/*INSIGHTS.md` و`*COMPARISON.md`.
