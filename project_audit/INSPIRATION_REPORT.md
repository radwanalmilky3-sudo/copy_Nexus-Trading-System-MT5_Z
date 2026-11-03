# INSPIRATION_REPORT — الفحص الشامل للمشروع المرجعي fx-trading-system

**المدير:** A0 | **تاريخ:** 2026-10-17
**المصدر:** `fx-trading-system-main/src/fx_system/` (نظام أبحاث FX كامل، Python)
**الهدف:** مشروعنا `D:\Nexus-Trading-System-MT5` (9 خدمات FastAPI + Redis + DuckDB + Next.js، تداول حي MT5)
**الأساس:** تقارير الوكلاء التسعة في `project_audit/` (DATA/NEWS/STRATEGY/RISK/VALIDATION/ARCHITECTURE_INSIGHTS + DATA/RISK/STRATEGY_COMPARISON)

> **طبيعة المشروع المرجعي:** نظام أبحاث (لا تداول حي — ممنوع بيانيًا). تركيزه: سلامة البيانات، منع look-ahead، تحقق إحصائي صارم. قوته: الانضباط المنهجي. ضعفه: لا خدمات حية، لا تنفيذ حقيقي. قوتنا: تشغيل حي، توقيع HMAC، 13 وكيل LangGraph. نأخذ منه **المبادئ** ونطبقها على بنية الحية.

---

## أهم 10 ميزات — وكيف نطبقها والوقت المتوقع

### 1. حماية Look-ahead عبر `available_time` (الأهم على الإطلاق)
**المبدأ:** كل صف خارجي (حدث اقتصادي، swap، تقرير CFTC) يحمل `observation_time` (ماذا يصف) **و** `available_time` (متى أصبح معروفًا)، مع رفض أي صف حيث observation > availability. كل join للأسفل بـ as-of مع TTL صلاحية (مثلاً 14 يوم للـ positioning). المرجع يبني **dataset fingerprint** يُحسب "كما كان معروفًا حتى وقت T" — أي تجربة تُقيَّد بدقة بياناتها.
**كيف نطبقه:**
- جدول `market_meta` في DuckDB يسجل `fetched_at` لكل دفعة OHLCV/تِك + عمود `available_at` في جداول الأحداث (`fundamental_schema.sql` يملك `known_at` جزئيًا — يجب توصيله).
- واجهة `GET /asof/{symbol}?through=ISO` تُرجع فقط الصفوف المتاحة عند ذلك الوقت، وتفشل (503) إذا طُلب fingerprint غير مربوط بسجل.
- تجميع الخصائص (features) يستعلم دائمًا عبر as-of، لا SELECT مباشر.
**الوقت:** 3–5 أيام عمل (schema + write-path + as-of query API + اختبارات تسريب).
**المرجع:** `point_in_time.py` | **التقارير:** A1, A2, A7

### 2. توصيل طبقة الجودة الحالية بالمسار الحي (موجودة ومهملة!)
**المبدأ:** المرجع يتحقق في ثلاث طبقات (تِك: offsets متزايدة، bid≤ask؛ ساعة: تناقض الحالة؛ شمعة: high/low تحيط بـ open/close) ويرفض/يعدّ السقوط بوضوح. **nexus-data يملك `quality/validators.py` و`imports/*` و`data_quality_contracts.py` بأصفار استدعاء خارج حزمتها** — كل صف يُكتب `quality='ok'` افتراضيًا حتى لو كان متقاطعًا أو سالبًا.
**كيف نطبقه:** جعل `duckdb_store` يستدعي validators قبل كل INSERT؛ دفعة تفشل → quarantine جدول + عدّاد في `/health`؛ وسم synthetic fallback بحقل `source='synthetic'` صريح في الاستجابة (لا سجلات فقط).
**الوقت:** 2–3 أيام (المكتبة مكتوبة — ربط فقط + اختبارات).
**المرجع:** `validate_bars`, session audit | **التقارير:** A1, A7

### 3. سلسلة نزاهة: هاشات + manifests + مراجعة بدل first-write-wins
**المبدأ:** كل حدود التسليم (ملف → SQLite → cache مشتق) يحمل SHA-256 + sidecar + receipt؛ اللود يفشل عند أي تعارض. الإصلاح لا يُهمل: صف مصحّح يُسجَّل كـ revision. **nexus-data:** لا هاشات، والـ `WHERE NOT EXISTS` يرفض بصمت أي شمعة صحّحها البروكر، والاحتفاظ 7 أيام تِك / 365 يوم OHLCV يعني عدم وجود أرشيف.
**كيف نطبقه:** عمود `revision` + سجل `bar_revisions`؛ manifest يومي لكل (symbol, timeframe): عدد الصفوف + هاش محتوى؛ snapshots أسبوعية قبل الـ prune للبيانات قيد الدراسة.
**الوقت:** 3–4 أيام.
**المرجع:** `_data_manifest.json`, transfer receipts | **التقارير:** A1, A7

### 4. بوابة ترقية استراتيجية حياة: بحث → ظل → ورق → حي (fail-closed)
**المبدأ:** المرجع: `research_candidate_requires_paper` — لا يُ promoted مباشرة إلى `active`. العلم الأحمر: `trading_approval=false` لا يُقلب إلا بإذن بشري، ويُعاد التحقق من الهاشات عند اللود. **nexus-agents:** LLM يرقّي استراتيجية إلى `active` بعد **نافذة واحدة داخلية** (PF≥1.4/WR≥0.52/Sharpe≥0.8) — آلة overfit مباشرة، بلا ورقة ولا ظل.
**كيف نطبقه:** حالات `shadow` و`paper` في سجل الاستراتيجيات؛ الترقية تتطلب حد أدنى صفقات + مدة جدارية في كل مرحلة + PF على **paper fills أمامية**؛ `active` غير قابلة للوصول من backtest واحد.
**الوقت:** 5–7 أيام (سجل + تدفق الترقية + مؤشرات تخرّج).
**المرجع:** lifecycle ladder | **التقارير:** A3, A5, A9

### 5. تحقّق إحصائي قبل أي ترقية: purged walk-forward + FDR
**المبدأ:** المرجع يجمع: (أ) تجريد label-horizon كامل من التدريب + embargo بين الطيات؛ (ب) تصحيح Benjamini-Hochberg على **العائلة كاملة** (بما فيها الفاشلة)؛ (ج) block bootstrap مشترك؛ (د) deflated Sharpe مقابل عدد التجارب المُفصح عنه. **nexus-ml:** يُجريد timestamp واحد فقط، لا embargo، لا holdout، لا FDR. **nexus-agents:** لوب تكيّف يعيد المحاولة حتى تنجح — inflates الاكتشافات الكاذبة.
**كيف نطبقه:** سجل بحث (`research_registry`) يعدّ كل فرضية LLM/نموذج؛ FDR على أي اختبار دلالة ت adopt؛ سقف resamples يُحسب مقدمًا؛ holdout لم يُمس بعد freeze.
**الوقت:** 5–7 أيام (مكتبة إحصائية + تكامل trainer/evaluator).
**المرجع:** `statistical_validation.py`, `hansen_spa.py` | **التقارير:** A3, A5, A9

### 6. ميزانية مخاطر محفظة + قاتل Drawdown من القمة
**المبدأ:** المرجع: حجم الصفقة = min(ميزانية لكل صفقة، **الميزانية المتبقية** = سقف المحفظة − مخاطر مفتوحة) ÷ مسافة الوقف، مع قبضة leverage إجمالي. kill switch على drawdown من equity high-water-mark (قمة) مع flatten. **nexus-risk:** كل صفقة تُقاس ضد الرصيد الكامل (N موافقات تتجاوز الميزانية معًا)؛ `weekly_dd_pct` يُكتب 0 دائمًا (القاطع زخرفة)؛ لا drawdown-from-peak إطلاقًا.
**كيف نطبقه:** Redis سلسلة قمة equity + حساب drawdown-peak في `_evaluate_proposal`؛ جمع مخاطر الصفقات المفتوحة (lots × risk/lot) وطرحها من السقف؛ `correlation_exposure` الحقيقية بدل 0.0 المضبوط يدويًا.
**الوقت:** 3–4 أيام.
**المرجع:** `risk.py` evaluate | **التقارير:** A4, A8

### 7. عقود إشارات موحّدة: الإشارة = حزمة مخاطر
**المبدأ:** `Signal` المرجع تحمل: confidence + ATR + stop_atr/target_atr + max_holding + reason + group_id لساقين متزامنتين (المحفظة تُسقط المجموعة كاملة إذا نقصت ساق). التنفيذ دائمًا **شمعة التالية** عند الفتح. **nexus:** `SignalEvent` بلا SL/TP/ATR/horizon؛ backtest يستخدم مضاعفات ثابتة (0.75/1.8) تختلف عن الحساب الحي — عدم تطابق عقد.
**كيف نطبقه:** امتداد schema للإشارة (أو event جديدها) يحمل geometry؛ الـ backtester للوكلاء والـ ML والـ executor يستهلكون نفس الـ schema؛ خصائص ثابتة تُفحص في اختبارات (RR ≤ حد، holding ≤ حد).
**الوقت:** 3–4 أيام (schema + ترحيل + توافق رجعي).
**المرجع:** `strategies/base.py` Signal | **التقارير:** A3, A9

### 8. نوافذ blackout fail-closed من جودة توقيت مُنمّقة
**المبدأ:** المرجع: دليل توقيت enum (verified-actual / scheduled / rule-derived / date-only / unverified) منفصل عن الطابع الزمني؛ حدث date-only يحجب **اليوم المدني كاملًا** بمنطقة الحدث الزمنية (لا دقيقة مخترعة)؛ event ملغي = خطأ لا "صافي"؛ غياب تغطية = degraded/block لا هدوء. **nexus-news:** يملك `blackout_state=clear` — يجب أن يُشترط: تغطية معلنة + توقيت صالح، وإلا block.
**كيف نطبقه:** حقل `timing_quality` في أحداث الأخبار؛ قاعدة: high-impact + date-only → حجب يوم كامل بتوقيت IANA؛ غياب مصدر → `degraded` يمنع التداول؛ إلغاء/تأجيل append-only.
**الوقت:** 2–3 أيام.
**المرجع:** `central_bank_calendar.py`, `publication_calendar.py` | **التقارير:** A2

### 9. تكوين مخطط كعقد مُتحقق + سجل تجربة
**المبدأ:** pydantic config بحدود رقمية + enums مغلقة + invariants متقاطعة (paper ⇒ enabled)؛ كل تشغيل مُعرَّف بـ (commit, config preset, data snapshot)؛ `validate-config` بوابة preflight. **nexus:** متغيرات بيئة مبعثرة، لا تحقق متقاطع، سجلات تشغيل run.py غير مربوطة بـ git snapshot.
**كيف نطبقه:** pydantic settings لكل خدمة (أو على الأقل risk/executor/ml) يُحمّل مرة عند الإقلاع؛ أمر `python run.py --validate` قبل أي نافذة؛ ملفات preset لكل سيناريو (paper-research, aggressive-test).
**الوقت:** 3–4 أيام (بالتدريج، يبدأ بـ nexus-risk).
**المرجع:** `config.py` | **التقارير:** A6

### 10. تقارير قواطع صادقة + مسار إبطال مُدقَّق
**المبدأ:** المرجع: كل رفض يحمل reason code مفهرس؛ الـ kill switch لا يُفتح بنبضة سوق بل بانتقال حالة صريح. **nexus-risk:** `get_active_circuit_breakers` يhardcode ~10 صفوف `triggered: False` (الواجهة تكذب)؛ `reset-day` يمسح كل شيء بلا سجل مَن/متى/بعد أي اختراق. (نقطة قوة نحافظ عليها: HMAC approvals + عزل paper/live على مستوى العملية + anti-tilt دقيق.)
**كيف نطبقه:** مصدر كل صف breaker من حالة التنفيذ الفعلية؛ سجل `reset_audit(caller, timestamp, pre_reset_values)`؛ تأكيد منفصل لمسح kill switch مُسلَّح.
**الوقت:** 1–2 يوم.
**المرجع:** reason-coded rejections | **التقارير:** A4, A8

---

## ميزات إضافية (خارج العشرة — قيّمة لاحقًا)

| الميزة | المصدر | أولوية |
|---|---|---|
| مسار أفق بطيء (قرار NY-close، تعدد الجلسات، freeze مُسبق) | A3, A9 | متوسطة — فقط إن أردنا alpha متعدد الأيام بدل scalping M5 |
| تجميع إشارات بـ min-vote + رفض مجموعات ناقصة | A3, A9 | متوسطة |
| Hansen SPA كحارس اختيار عائلة (لا يسمي فائزًا) | A5 | منخفضة-متوسطة |
| تجزئة تكلفة صريحة (spread+slippage+commission+swap مع provenance، NaN بدل صفر) | A3, A9 | عالية ضمن بوابة الترقية |
| خط إبطال صلب (flatten) عند أقصى drawdown | A4, A8 | عالية |

## نقاط قوة حالية نحافظ عليها (أمام المرجع)

- **توقيع HMAC مع TTL ومطابقة شروط** (`NEXUS_RISK_APPROVAL_SECRET`) — المرجع لا يعرف tokens أصلًا.
- **دفاع بالعمق:** حارس executor يعيد تحقق kill-switch/auto-trade/blackout/approval قبل كل أوامر — أقوى من فحص in-process واحد.
- **anti-tilt ثلاثي الحالات + كتل اتجاه + Redis durable** — غني عن سلوك المرجع الإحصائي فقط.
- **تنسيق 13 وكيل LangGraph + claim locks + DLQ** — المرجع لا خدمات حية أصلًا.

## خارطة تنفيذ مقترحة (مراحل)

| مرحلة | الميزات | المدة التقديرية |
|---|---|---|
| **P1 — سلامة** | #2 جودة موصولة، #10 قواطع صادقة، #1 تصفية as-of أساسية | ~1.5 أسبوع |
| **P2 — مخاطر** | #6 ميزانية محفظة + drawdown-peak، #8 blackout صارم | ~1 أسبوع |
| **P3 — بحث** | #5 FDR + purged folds، #4 بوابة paper، #7 عقد الإشارة | ~1.5–2 أسبوع |
| **P4 — نزاهة** | #3 هاشات/revisions، #9 config مُتحقق | ~1 أسبوع |

**المجموع التقديري: 5–6 أسابيع عمل** لتطبيق العشرة كاملة بالتسلسل المقترح (أو ~3 أسابيع للـ P1+P2 فقط — الأمان قبل الأناقة).

---

## خلاصة الوكلاء (حالة السرب)

| الوكيل | التقرير | الحالة |
|---|---|---|
| A1 البيانات | DATA_INSIGHTS.md | ✅ |
| A2 الأخبار | NEWS_INSIGHTS.md | ✅ |
| A3 الاستراتيجيات | STRATEGY_INSIGHTS.md | ✅ |
| A4 المخاطر | RISK_INSIGHTS.md | ✅ |
| A5 التحقق | VALIDATION_INSIGHTS.md | ✅ |
| A6 البنية | ARCHITECTURE_INSIGHTS.md | ✅ |
| A7 مقارنة بيانات | DATA_COMPARISON.md | ✅ |
| A8 مقارنة مخاطر | RISK_COMPARISON.md | ✅ |
| A9 مقارنة استراتيجيات | STRATEGY_COMPARISON.md | ✅ |
| **A0 النهائي** | **INSPIRATION_REPORT.md** (هذا) | ✅ |

**10/10 وكلاء انتهوا. التقرير النهائي جاهز.**
