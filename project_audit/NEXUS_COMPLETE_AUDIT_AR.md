# تدقيق تسليم كامل لوكيل تطوير Nexus Trading System

## 0) نطاق المهمة وقواعد التنفيذ

هذه الوثيقة هي تسليم تنفيذي لوكيل التطوير، وليست تصريحًا بالتعديل الآن.

- المشروع الهدف: `C:\Nexus-Trading-System-MT5`
- المشروع المرجعي: `work\repo\fx-trading-system-main`
- المطلوب في هذه المرحلة: قراءة، مقارنة، تصميم، وتحديد ما يجب تطويره بدقة.
- المطلوب عدم فعله في مرحلة التدقيق: تعديل ملفات Nexus، تشغيل اختبارات، تغيير قاعدة البيانات، تغيير العقود، أو تشغيل تداول حي.
- كل ما يرد أدناه يجب تحويله لاحقًا إلى مراحل صغيرة قابلة للمراجعة، مع الحفاظ على المعمارية الحدثية الحالية.
- لا يُسمح بنسخ واجهات المصدر أو ربط طبقة البحث مباشرة بالوسيط أو بمحرك التنفيذ.

## 1) الحكم التنفيذي

`fx-trading-system` أقوى من Nexus حاليًا في خمسة محاور: البحث القابل لإعادة الإنتاج، منع تسرب المستقبل، تكاليف التداول الواقعية، التحقق الإحصائي، وسجل الأصول/النتائج البحثية. Nexus أقوى في التشغيل الحي، الخدمات المنفصلة، Redis Streams، التكامل مع MT5، لوحة التحكم، الأخبار، وإدارة التنفيذ.

القرار المعماري الصحيح هو:

1. نقل منطق البحث والتحقق والعقود إلى خدمة Research/Validation مستقلة داخل Nexus.
2. إبقاء MT5 وRedis وRisk وExecutor وNews الحالية هي مصادر التشغيل الرسمية.
3. جعل نتائج البحث غير قابلة للتداول تلقائيًا إلا بعد المرور بعقود البيانات، اختبار الجودة، التحقق الإحصائي، والموافقة على Promotion.
4. جعل كل نتيجة قابلة للتتبع من: مصدر البيانات ← النسخة الزمنية ← التنظيف ← الميزات ← الاستراتيجية ← الاختبار ← القرار ← الصفقة.
5. بناء شاشات Data Hub وResearch وValidation كواجهات جداول وفلاتر وتبويبات، مع إبقاء Console وTree وTrace أدوات تفصيلية داخل الصفحات وليست الواجهة الرئيسية.

## 2) الأدلة التي يجب على الوكيل مراجعتها

### المرجع

- `src/fx_system/config.py`
- `src/fx_system/data.py`
- `src/fx_system/point_in_time.py`
- `src/fx_system/research_controls.py`
- `src/fx_system/factors.py`
- `src/fx_system/indicators.py`
- `src/fx_system/factor_dsl.py`
- `src/fx_system/factor_research.py`
- `src/fx_system/factor_forward.py`
- `src/fx_system/technical.py`
- `src/fx_system/multicurrency.py`
- `src/fx_system/strategies/technical.py`
- `src/fx_system/strategies/multicurrency.py`
- `src/fx_system/engine.py`
- `src/fx_system/labels.py`
- `src/fx_system/risk.py`
- `src/fx_system/portfolio.py`
- `src/fx_system/portfolio_ledger.py`
- `src/fx_system/broker_cost_contract.py`
- `src/fx_system/rates.py`
- `src/fx_system/statistical_validation.py`
- `src/fx_system/hansen_spa.py`
- `src/fx_system/research_registry.py`
- `src/fx_system/reporting.py`
- `src/fx_system/publication_calendar.py`
- `src/fx_system/central_bank_calendar.py`
- `src/fx_system/intraday_calendar.py`
- `src/fx_system/long_horizon_runner.py`
- `src/fx_system/intraday_runner.py`
- `pyproject.toml` و`README.md`

### Nexus

- `shared/events.py`
- `shared/models.py`
- `shared/constants.py`
- `shared/redis_client.py`
- `shared/assets.yaml`
- `shared/risk_rules.yaml`
- `nexus_data/main.py`
- `nexus_data/duckdb_store.py`
- `nexus_data/mt5_connector.py`
- `nexus_data/fundamental_schema.sql`
- `nexus_features`
- `nexus_ml`
- `nexus_agents`
- `nexus_news`
- `nexus_risk`
- `nexus_executor`
- `nexus_api`
- `nexus_monitor`
- `dashboard/src/app/dashboard/layout.tsx`
- `dashboard/src/app/dashboard/page.tsx`
- `dashboard/src/components`
- `dashboard/src/hooks/useTrades.ts`

## 3) خريطة ملكية المكونات

| المجال | المالك بعد الدمج | قاعدة القرار |
|---|---|---|
| MT5 ticks/OHLCV | `nexus_data` | المصدر الحي الوحيد للبيانات التشغيلية |
| التاريخي الخارجي | `nexus_data` + Import Worker | يدخل Staging أولًا ولا يدخل Canonical مباشرة |
| الأخبار والأحداث | `nexus_news` | يوفر observation/available/decision times |
| الميزات | `nexus_features` | يحسب closed-bar فقط ويخزن الإصدار |
| البحث والاستراتيجيات | `nexus_research` | يستعمل عقودًا ثابتة ولا يرسل أوامر |
| ML registry | `nexus_ml` + Research Promotion | لا ترقية دون سجل تجريبي كامل |
| المخاطر | `nexus_risk` | قواعد Nexus الصلبة تغلب إعدادات البحث |
| التنفيذ | `nexus_executor` | لا يقبل إلا RiskDecision معتمدًا |
| السجل والتتبع | `nexus_api` + DuckDB | لكل نتيجة correlation/run/lineage IDs |
| الواجهة | Dashboard | جداول، قوائم، فلاتر، تبويبات، وتفاصيل عند الطلب |

## 4) جرد ميزات fx-trading-system وتصنيف النقل

### A. ينقل كما هو مفاهيميًا داخل Research

1. Typed configuration لعقود البيانات والتكاليف والمخاطر والاستراتيجية والنتائج.
2. Point-in-time observations: `observed_at`, `available_at`, `decision_at`.
3. Future-information canary وnegative controls وcommon-date randomization.
4. Purged walk-forward validation وembargo حول حدود التدريب والاختبار.
5. Paired block bootstrap، FDR، وHansen SPA عند مقارنة استراتيجيات متعددة.
6. Research registry وmanifest وSHA-256 للمدخلات والمخرجات.
7. تقارير قابلة لإعادة البناء من manifest وليس من قيم واجهة مخزنة يدويًا.
8. Factor DSL، factor research، factor forward، ومقارنة العوامل.
9. labels مع اتجاه التنفيذ: close signal ثم next-bar execution.
10. stop-first conservative same-bar handling.

### B. ينقل مع تكييف Nexus

1. CSV/Yahoo/Dukascopy/OANDA adapters تصبح Import Providers، لكن OANDA/MT5 لا يربطان Research مباشرة بالتنفيذ.
2. bid/ask OHLC، spread، swap، commission، slippage، وforward points تصبح Cost Contract موحدًا.
3. technical وmulticurrency features تضاف فوق `nexus_features` مع symbol mapping.
4. portfolio وshared currency exposure تضاف إلى `nexus_risk` وPortfolio Simulator.
5. publication/central-bank/intraday calendars تندمج مع `nexus_news`.
6. long-horizon وintraday runners يبقيان مسارين منفصلين؛ لا يخلطان دقة البيانات أو أفق الإشارة.
7. paper plan وbroker calibration يصبحان بوابة قبل live promotion.

### C. لا ينقل مباشرة

1. CLI `fxtrade` كواجهة تشغيل رئيسية؛ يستبدل بـ API/Redis Job contracts.
2. أي broker submit أو live order logic؛ يبقى في `nexus_executor`.
3. Yahoo midpoint كمرجع حي؛ يستخدم exploratory فقط.
4. افتراضات FX العامة على XAUUSD/BTCUSD/US30؛ يجب استخدام `assets.yaml` وقواعد كل أصل.
5. أي نتيجة تعتمد على `zero_placeholder` للتكاليف أو التمويل كأنها نتيجة إنتاجية.

## 5) أهم فجوات يجب إصلاحها قبل الدمج

### فجوات مرجعية

- Slow-horizon runner قد يخرج target weights دون formal portfolio PnL artifacts؛ يجب استكمال محاكاة PnL قبل اعتباره مرجعًا.
- Point-in-time join يسمح في بعض المسارات بـ exact timestamp؛ يجب اعتماد قاعدة صريحة: `available_at <= decision_at`، مع منع المطابقة المستقبلية.
- التمويل المجهول قد يتحول إلى placeholder صفري؛ يجب تصنيف النتيجة `cost_incomplete` ومنعها من promotion إلى live.
- تكاليف البحث الثابتة fixtures وليست تاريخ broker فعليًا؛ يجب استبدالها أو وسمها بوضوح.
- Dukascopy مصدر quote واحد؛ يلزم broker calibration ومقارنة spread قبل اعتماد live.
- overlapping labels وmodel selection يحتاجان purging وembargo وسجل فرضيات.
- forward runs قد تحتوي `end=null` أو `holdout_bars=0`؛ يجب رفضها كـ production-ready.
- OHLC لا يكشف دائمًا ترتيب intrabar؛ يجب اعتماد conservative stop-first أو tick-level evidence.

### فجوات Nexus

- `Signal` لا يحتوي حاليًا على run ID أو provenance أو available-at أو eligibility.
- OHLCV provenance الحالي محدود بـ source/quality/fetched_at ولا يكفي لإعادة بناء النسخة التاريخية.
- backfill الافتراضي قصير ومحدود؛ يجب أن يصبح Job قابلًا للاستئناف مع partitions.
- synthetic fallback يجب ألا يختلط بالبيانات الحقيقية أو يصل إلى live decisions.
- `insert_ohlcv_batch` يحتاج عدًّا دقيقًا للصفوف المقبولة/المرفوضة/المكررة، لا عدد الصفوف المقدمة فقط.
- تبويبات Dashboard الحالية local-state ولا تحفظ URL state، ولا يوجد global filter context موحد.
- Console وtree وtrace موجودة كأدوات، لكن لا توجد شاشة تشغيلية كاملة للاستيراد والتصحيح والـ lineage.
- labels في الواجهة مختلطة اللغة؛ يجب توحيد اللغة والتسميات في design system.
- Risk rules الحالية قد تكون أوسع من ضوابط المصدر؛ يجب استخدام تقاطع محافظ وعدم السماح للبحث بتوسيع قيود Nexus.

## 6) التغييرات الدقيقة المطلوبة في العقود

### 6.1 Dataset contract

يجب إنشاء عقد موحد لكل مصدر تاريخي أو حي:

```text
dataset_id
source_id
provider
asset_id
canonical_symbol
asset_class
timeframe
grain
timezone
observed_at
available_at
decision_at
vintage_id
source_record_id
raw_uri
raw_sha256
schema_version
quality_status
quality_score
lineage_id
created_at
```

### 6.2 Bar contract

```text
asset_id, symbol, timeframe, timestamp
open, high, low, close, volume
bid_open, bid_high, bid_low, bid_close
ask_open, ask_high, ask_low, ask_close
spread_open, spread_high, spread_low, spread_close
source_id, provider, vintage_id, observed_at, available_at
session, timezone, is_closed, quality_status, row_hash
```

لا يُقبل bar ناقص المصدر أو التوقيت أو الإصدار ضمن canonical research dataset.

### 6.3 Research run contract

```text
run_id, parent_run_id, strategy_id, strategy_version
dataset_id, data_snapshot_hash, code_revision
feature_set_version, cost_contract_version, risk_policy_version
news_snapshot_id, calendar_version
train_start, train_end, validation_start, validation_end
holdout_start, holdout_end, purge_bars, embargo_bars
seed, status, eligibility, created_at, completed_at
```

### 6.4 Signal contract extension

تضاف إلى Signal الحالي:

```text
run_id, strategy_id, strategy_version, feature_set_version
data_vintage_id, observation_time, available_at, decision_time
eligibility, point_in_time_ok, cost_complete, news_context_id
source_provenance, explanation_id, correlation_id
```

الإشارة بلا `point_in_time_ok=true` وبلا provenance كامل لا تمر إلى risk.

## 7) مخطط البيانات المقترح

### 7.1 جداول البيانات والاستيراد

```sql
datasets(dataset_id, source_id, provider, asset_id, timeframe, grain,
         schema_version, snapshot_hash, status, created_at)
dataset_sources(source_id, name, uri, credentials_ref, provider_type,
                timezone, availability_policy, enabled)
dataset_partitions(partition_id, dataset_id, range_start, range_end,
                   row_count, checksum, status)
import_jobs(job_id, dataset_id, mode, requested_range, status,
            submitted_at, started_at, completed_at, counters_json)
import_errors(error_id, job_id, row_number, field, raw_value,
              error_code, severity, resolution_status)
quarantine_rows(row_id, job_id, raw_payload, normalized_payload,
                reason_code, review_status, reviewer, reviewed_at)
```

### 7.2 الجودة والتنظيف

```sql
quality_runs(quality_run_id, dataset_id, rule_set_version, status,
             score, started_at, completed_at)
quality_checks(check_id, quality_run_id, rule_code, dimension,
               passed, severity, observed_count, threshold, details_json)
correction_actions(action_id, dataset_id, row_id, action_type,
                   before_json, after_json, reason, actor, created_at)
asset_lineage(lineage_id, raw_symbol, canonical_asset_id, provider,
              contract_version, mapping_confidence, approved_by)
```

### 7.3 البحث والتحقق والترويج

```sql
research_runs(run_id, strategy_id, strategy_version, dataset_id,
              snapshot_hash, config_json, status, eligibility)
research_artifacts(artifact_id, run_id, artifact_type, uri,
                   sha256, schema_version, created_at)
research_signals(signal_id, run_id, asset_id, decision_time,
                 direction, score, eligibility, explanation_json)
research_trades(trade_id, run_id, signal_id, entry_time, exit_time,
                entry_price, exit_price, costs, pnl, r_multiple,
                stop_first, execution_model)
research_equity(run_id, timestamp, equity, drawdown, exposure,
                gross_pnl, net_pnl, costs)
validation_results(validation_id, run_id, test_type, metric,
                   value, threshold, passed, details_json)
promotions(promotion_id, run_id, from_stage, to_stage, decision,
           approver, reason, created_at)
lineage_edges(lineage_id, parent_type, parent_id, child_type,
              child_id, relation, created_at)
trace_events(trace_id, correlation_id, run_id, event_type,
             service, payload_hash, occurred_at)
```

## 8) تصميم دورة استيراد البيانات وتصحيحها

### الحالة التشغيلية

`REGISTERED → FETCHING → STAGED → MAPPED → NORMALIZED → QUALITY_CHECK → ACCEPTED / RESEARCH_ONLY / QUARANTINED / REJECTED`

### مراحل شاشة الاستيراد

1. اختيار المصدر: MT5، CSV، Dukascopy، OANDA، feed حي، أو provider مخصص.
2. اختيار الأصل والرمز الأصلي والرمز القياسي وasset class وtimezone.
3. اختيار timeframe/grain والفترة الزمنية ونسخة البيانات.
4. رفع/جلب البيانات إلى staging مع raw hash، وليس إلى جدول OHLCV مباشرة.
5. معاينة mapping: أسماء الأعمدة، bid/ask أو midpoint، volume، timezone، session.
6. معاينة صفوف صحيحة ومرفوضة ومكررة قبل الاعتماد.
7. تشغيل قواعد التنظيف القابلة للتفسير.
8. عرض correction queue في جدول؛ كل تصحيح قبل/بعد وسبب ومصدر ومستخدم.
9. اعتماد dataset أو وضعه Research Only أو Quarantine.
10. إنشاء snapshot hash وlineage وquality report.

### قواعد الجودة الإلزامية

- ترتيب زمني صحيح وعدم وجود timestamp مستقبلية بالنسبة إلى ingestion.
- عدم تكرار `(asset_id, timeframe, timestamp, vintage_id)`.
- `high >= max(open, close, low)` و`low <= min(open, close, high)`.
- الأسعار موجبة ولا توجد قفزات غير مفسرة تتجاوز حدود الأصل.
- التحقق من فجوات bars والعطلات والجلسات، لا اعتبار كل gap خطأ.
- bid <= ask وspread غير سالب عند توفر bid/ask.
- توافق digits/pip_size/contract_size مع assets.yaml.
- توحيد timezone مع حفظ timezone الأصلي.
- كشف DST، weekend bars، stale prices، zero volume، outliers.
- مصدر كل صف ووقت توفره ونسخته الزمنية.
- عدم مزج synthetic مع real في dataset واحد.
- تطبيق corporate/roll adjustments فقط كإجراء موثق، وليس تعديلًا صامتًا.
- فصل missing، invalid، corrected، imputed، synthetic في quality flags مستقلة.

### النتيجة لا تكون صالحه للبحث إلا إذا

`schema_passed AND temporal_passed AND asset_mapping_passed AND provenance_complete AND no_blocking_errors`.

## 9) ربط الأصول بدقة

يجب إنشاء Asset Master موحد يربط:

```text
raw_symbol → canonical_asset_id → broker_symbol → asset_class
contract_size, digits, tick_size, pip_size, pip_value
quote_currency, base_currency, margin_currency
trading_sessions, timezone, min_stop, min_tp
spread_policy, swap_policy, commission_policy
```

أمثلة مخاطر لا بد من منعها:

- اعتبار XAUUSD مثل EURUSD في pip value أو contract size.
- اعتبار BTCUSD سوقًا يعمل بنفس جلسات الفوركس.
- استعمال USDJPY price precision في EURUSD أو المؤشرات.
- خلط symbol provider مع symbol broker.
- خلط midpoint التاريخي مع bid/ask التنفيذي.
- تطبيق قواعد USD exposure على أصل لا يملك نفس quote currency.

كل mapping منخفض الثقة يذهب إلى review queue، ولا يمر إلى live.

## 10) الاستراتيجيات والاختبار والبحث

### عائلات الاستراتيجيات المطلوب دمجها

1. `regime_mean_reversion`
2. `trend_pullback`
3. `session_breakout`
4. `false_breakout_reversal`
5. `currency_strength_reversion`
6. `cointegration_spread`

### عقود الاستراتيجية

كل Strategy يجب أن يعرّف:

```text
strategy_id, version, family, assets, timeframes
required_features, required_data_fields, required_news_fields
signal_time, execution_time, holding_horizon
entry_rules, exit_rules, stop_rules, target_rules
cost_model, financing_model, portfolio_constraints
warmup_bars, purge_bars, embargo_bars
parameter_schema, seed_policy, code_revision
```

### مسار تطوير الاستراتيجية

`Draft → Data-Compatible → Research → Validated → Paper → Candidate → Promoted → Live / Rejected / Retired`

لا يصح أن يرسل `nexus_agents` حكمًا إلى executor مباشرة. الوكيل يقترح، Research يتحقق، Risk يقرر، Executor ينفذ.

### الاختبار الواجب لكل تشغيل

- train/validation/holdout منفصلة زمنيًا.
- purging وembargo.
- next-bar execution بعد إغلاق الشمعة.
- bid/ask وspread وcommission وswap وslippage.
- stop-first عند تعارض stop/target داخل نفس الشمعة.
- max holding وreward/risk cap حسب سياسة Nexus.
- shared currency exposure وportfolio risk.
- block bootstrap للثقة.
- FDR عند فحص عدة عوامل/استراتيجيات.
- Hansen SPA أو اختبار مماثل عند مقارنة مجموعة واسعة.
- future-information canary وnegative controls.
- common-date randomization لتجنب أثر التاريخ المشترك.
- sensitivity analysis للتكاليف، الانزلاق، التأخر، والبيانات الناقصة.
- لا promotion إن كانت البيانات أو التمويل أو الأخبار غير مكتملة.

## 11) دمج الأخبار والأحداث

يوجد في Nexus أساس قوي: `fund_sources`, `data_vintages`, `macro_releases`, `central_bank_events`, `news_articles`, `news_nlp_analysis`, `fundamental_fusion_results`, `fundamental_blackout_windows`, `fundamental_guard_decisions`, و`fundamental_audit_log`.

التطوير المطلوب ليس إنشاء نظام أخبار موازٍ؛ بل إضافة ربط research:

```text
news_snapshot_id
event_id
event_type
observed_at
available_at
decision_time
importance
affected_assets
sentiment/regime/central_bank_state
blackout_state
source_quality
```

تصنيف أثر الخبر على الإشارة:

- `confirmation`
- `contradiction`
- `blackout`
- `risk_only`
- `context_only`
- `stale_or_unavailable`

قواعد الدمج:

1. الخبر لا يدخل الإشارة قبل `available_at`.
2. خبر التوقع/النتيجة يحفظ revision/vintage ولا يستبدل الماضي بصمت.
3. blackout يمنع execution أو يخفض الحجم حسب policy، ولا يغير backtest بأثر رجعي.
4. الخبر المتأخر أو منخفض الجودة يظهر كـ `unavailable` لا كـ neutral صامت.
5. تحفظ أسباب تأثير الخبر داخل explanation وlineage.
6. الاختبار يقارن strategy بلا أخبار، مع أخبار، ومع blackout فقط.

## 12) تكامل الأحداث وRedis

لا تغيّر envelope الحالي؛ وسّعه بإضافة:

```text
schema_version, event_id, correlation_id, causation_id
run_id, dataset_id, provenance_id, emitted_at, available_at
```

Streams المقترحة:

- `stream:data:import`
- `stream:data:quality`
- `stream:data:correction`
- `stream:research:run`
- `stream:research:artifact`
- `stream:research:validation`
- `stream:research:promotion`
- `stream:news:context`
- streams الحالية: ticks, ohlcv, features, signals, risk, orders, positions, trades, health.

التسلسل:

`Import → Quality → Canonical Data → Features → Research/Signals → News Context → Risk → Executor`

Research لا يرسل إلى `stream:orders`. المسار الوحيد للأوامر هو RiskDecision ثم Executor.

## 13) خدمة وملفات جديدة مقترحة

### خدمة جديدة

```text
nexus_research/
  main.py
  worker.py
  source_adapter.py
  config.py
  contracts.py
  datasets.py
  quality.py
  validation.py
  costs.py
  portfolio_simulator.py
  artifacts.py
  lineage.py
  promotion.py
```

### shared جديد

```text
shared/research_models.py
shared/research_events.py
shared/data_contracts.py
shared/asset_capabilities.py
shared/trace_models.py
shared/provenance.py
```

### API جديد

```text
/api/data/imports
/api/data/imports/{job_id}
/api/data/quality
/api/data/corrections
/api/data/lineage
/api/research/strategies
/api/research/runs
/api/research/runs/{run_id}
/api/research/runs/{run_id}/artifacts
/api/research/validation
/api/research/promotions
/api/audit/traces
```

### ملفات Nexus تعدل لاحقًا بعد موافقة منفصلة

- `shared/events.py`, `shared/models.py`, `shared/constants.py`
- `shared/assets.yaml`, `shared/risk_rules.yaml`
- `nexus_data/main.py`, `duckdb_store.py`, `mt5_connector.py`
- `nexus_data/fundamental_schema.sql`
- `nexus_features` و`nexus_ml`
- `nexus_news` و`nexus_risk`
- `nexus_api` و`nexus_monitor`
- `dashboard/src/app/dashboard/layout.tsx`
- `dashboard/src/app/dashboard/page.tsx`
- dashboard hooks/types/components

## 14) تصميم الواجهات المطلوبة

### التبويبات الرئيسية

1. **Overview**: حالة النظام، data freshness، quality score، active risk، running jobs.
2. **Data Hub**: datasets، sources، partitions، symbols، timeframes.
3. **Import Center**: wizard، progress، preview، errors، retry/resume.
4. **Data Quality**: checks، score، gaps، duplicates، outliers، stale rows.
5. **Correction Queue**: جدول صفوف المشكلة، before/after، سبب، approve/reject.
6. **Lineage**: جدول المصدر والنسخة والميزة والاستراتيجية والصفقة، مع trace عند الطلب.
7. **Strategies**: catalog، versions، parameters، required data/news، lifecycle.
8. **Research Runs**: queue، status، filters، metrics، artifacts.
9. **Validation**: walk-forward، leakage، costs، bootstrap، FDR، SPA، verdict.
10. **News & Context**: events، snapshots، blackout، strategy impact.
11. **Promotion**: gates، approvals، paper/live status، rollback.
12. **Trading**: positions، orders، trades، risk.
13. **Monitoring**: services، streams، lag، DLQ، alerts.

### قواعد الواجهة

- كل قائمة رئيسية جدول قابل للفرز والتصفية والتصدير والتقسيم إلى صفحات.
- filter bar عالمي: asset، provider، timeframe، date range، status، quality، run، strategy، news state.
- حفظ filters في URL، مع preset وshareable view.
- التفاصيل تظهر في side panel أو row expansion؛ لا يُعرض trace كامل دائمًا.
- tree/trace/journal أدوات drill-down مرتبطة بالصف المحدد.
- جميع التبويبات lazy-loaded؛ لا تبقى كل لوحات البيانات mounted مخفية.
- حالة التبويب قابلة للربط بالرابط، وليس local state فقط.
- ألوان الجودة والحظر والثقة موحدة، مع دلالات نصية لا تعتمد على اللون وحده.
- منع خلط labels اللغوية؛ اعتماد قاموس موحد عربي/إنجليزي حسب إعداد النظام.
- كل action يعرض أثره المتوقع وaudit entry.

## 15) خريطة الربط مع الشاشات الحالية

| الشاشة الحالية | التطوير |
|---|---|
| Trading | إضافة eligibility/provenance/news context بجانب signal |
| Strategies | تحويلها إلى catalog + versions + required inputs + lifecycle |
| Models | ربط model registry بالـ run والـ data snapshot والـ promotion |
| Compare | إضافة مقارنة walk-forward/SPA/FDR/cost scenarios |
| History | إضافة dataset vintage وlineage وsource quality |
| News | إضافة event snapshot وavailable-at وblackout impact |
| Agents | عرض proposal/analysis/verdict مع عدم إخفاء risk gate |
| Fundamental | ربطه بمخرجات news context لا بتغذية مستقلة |
| Journal | ربط كل صفقة بإشارة وrun وfeature snapshot |
| Backtest | تحويله إلى Research Run مع artifacts وvalidation gates |
| Console | إبقاؤه كـ fallback/debug، وليس الشاشة الأساسية |
| Progress | نقله إلى Job Center مع jobs/import/quality/research |

## 16) خطة التنفيذ المرحلية للوكيل

### المرحلة A — تثبيت العقود

أنشئ schemas وversioning وIDs وAsset Master وprovenance. لا تغير execution behavior.

### المرحلة B — Data Hub وStaging

أنشئ staging/import jobs/raw hashes/partitions/quarantine، ثم اربط MT5 وCSV كـ providers.

### المرحلة C — Quality وCorrection

أنشئ quality rules، correction queue، quality score، وقرار ACCEPTED/RESEARCH_ONLY/QUARANTINED.

### المرحلة D — Research Service

استخرج ميزات المصدر إلى worker مع adapters، manifest، artifacts، ودون أي broker side effect.

### المرحلة E — Cost/Portfolio/Validation

أضف bid/ask/costs/financing/portfolio exposure وwalk-forward/leakage/statistical validation.

### المرحلة F — News Context

اربط snapshot/vintage/available-at/blackout/impact مع كل research run وsignal.

### المرحلة G — Promotion

أنشئ gates وapprovals وpaper mode وrollback؛ لا live promotion تلقائي.

### المرحلة H — Dashboard

أنشئ التبويبات والجداول والفلاتر وURL state والـ side panels والـ lineage.

### المرحلة I — تشغيل حذر

فعّل paper/shadow فقط، قارن مع التنفيذ الحالي، ثم راجع broker calibration.

### المرحلة J — اعتماد تدريجي

اعتماد أصل واحد وفترة واحدة واستراتيجية واحدة في كل مرة، مع kill switch وrollback.

## 17) معايير القبول التي يجب أن يقدمها الوكيل

- يمكن استيراد CSV/MT5 إلى staging دون تلويث canonical.
- كل صف مقبول له asset mapping وtimestamp وsource وvintage وhash.
- يمكن رؤية كل خطأ في جدول وتصحيحه أو عزله مع before/after.
- لا يسمح النظام بإشارة ذات future leakage أو missing provenance بالمرور إلى risk.
- يمكن إعادة تشغيل research run من manifest نفسه وإنتاج نفس النتائج ضمن tolerance.
- كل run يحفظ code revision وconfig وdataset snapshot وcost/news/risk versions.
- كل استراتيجية من العائلات الست تملك contract واضحًا أو تكون معلّمة غير مدعومة.
- كل backtest يطبق next-bar، bid/ask، costs، stop-first، portfolio constraints.
- كل news feature يحترم available-at وvintage والـ blackout.
- لا يصل Research مباشرة إلى orders.
- Promotion يحتاج validation gates وقرارًا مسجلًا وrollback.
- الواجهات الرئيسية جداول وفلاتر وتبويبات، مع trace/tree كـ drill-down.
- dashboard لا يحمل كل التبويبات الثقيلة في وقت واحد.
- counters الاستيراد تميز submitted/accepted/rejected/quarantined/duplicate.
- synthetic أو placeholder لا يظهر كبيانات حقيقية ولا يدخل live.

## 18) نقاط يجب ألا يتجاوزها الوكيل

- لا ينسخ source code عشوائيًا داخل Nexus دون عقد واختبارات تكامل لاحقة.
- لا يجعل config المصدر يتغلب على `risk_rules.yaml`.
- لا يخلط backtest research مع live event path.
- لا يملأ missing news/costs بقيم neutral أو zero دون flag.
- لا يساوي بين midpoint وbid/ask.
- لا يستخدم exact timestamp join دون إثبات availability.
- لا يضيف live order path من خلال Research أو Agents.
- لا يغير schema الحالي دون migration/version/rollback.
- لا يبني شاشة جديدة تعتمد على Console كبديل عن model data.
- لا يعتبر نتائج المرجع صحيحة لمجرد أنها موجودة؛ يجب إكمال الفجوات المذكورة في القسم 5.

## 19) ترتيب الأولويات

**P0:** provenance، point-in-time، asset mapping، staging، quality gates، risk boundary، event versioning.

**P1:** Research service، cost/portfolio simulation، walk-forward، leakage controls، news snapshots، artifacts.

**P2:** strategy catalog، factor DSL، statistical validation، promotion workflow، paper mode.

**P3:** dashboard polish، advanced comparison، saved views، localization، performance tuning.

## 20) الخلاصة التي يستلمها الوكيل

المطلوب ليس إضافة ملفات من `fx-trading-system` بشكل مباشر، بل تحويل أقوى ما فيه إلى طبقة Research/Validation قابلة للتتبع داخل Nexus، مع إبقاء التشغيل الحي في خدمات Nexus الحالية. مركز النجاح هو Data Hub: لا استراتيجية موثوقة بلا dataset صحيح، ولا dataset صحيح بلا asset lineage وvintage وavailability، ولا نتيجة قابلة للتداول بلا cost/news/risk validation.

البدء الصحيح للوكيل: تثبيت العقود وAsset Master وStaging وQuality، ثم Research، ثم News/Validation، ثم Promotion والواجهات. أي عمل يبدأ من الواجهة قبل هذه العقود سيعيد بناء الشاشات عدة مرات وسيخفي مشكلات جودة البيانات بدل حلها.

## 21) نتيجة خمس مراجعات مستقلة — إضافات إلزامية

أُعيدت مراجعة الوثيقة على خمس طبقات: اكتمال المصدر، مطابقة معمارية Nexus، صحة البيانات والأصول، الاستراتيجيات والأخبار، ثم التشغيل والواجهة والأمان. النتيجة: التقرير السابق قوي كأساس، لكنه يحتاج الإضافات التالية حتى يكون تسليمًا كاملًا لا يترك ميزات مهمة غير مرئية للوكيل.

### المراجعة الأولى: اكتمال جرد ميزات fx-trading-system

الوحدات التالية يجب أن تظهر في خطة النقل أو في قائمة صريحة لعدم النقل:

| الوحدة/الميزة | ما تقدمه | قرار الدمج |
|---|---|---|
| `analytics.py` | equity/trades frames، metrics، robust screen score | تضاف إلى Artifact Metrics وواجهة Compare |
| `ensemble.py` | دمج إشارات عدة استراتيجيات | يندمج داخل Research/Portfolio، ولا يتجاوز Risk |
| `cftc.py` | CFTC Financial Futures positioning | مزود external factor مع available-at وrelease calendar |
| `cftc_release_calendar.py` | وقت نشر CFTC الموثق/التقريبي | approximate يمنع promotion؛ verified فقط يدخل formal run |
| `macro_vintages.py` | current-vintage مقابل as-published | تخزين vintage منفصل ومنع استبدال الماضي بصمت |
| `external_factor_eligibility.py` | سجل المصدر والعامل وشروط الأهلية | بوابة قبل استعمال أي external factor |
| `structured_external_features.py` | عوامل اقتصادية/خارجية منظمة | تدخل في Feature Registry مع provenance |
| `structured_event_controls.py` | ضوابط أحداث وأثرها الزمني | تدمج مع News Context وblackout |
| `forward_collection_contract.py` | شروط تجميد النموذج وتشغيل forward | بوابة Candidate إلى Paper وليست مجرد job |
| `financial_center_calendar.py` | عطلات، أيام نصفية، مراكز مالية، DST | إلزامي للـ session وFIX-W وأوقات التنفيذ |
| `dukascopy_intake.py` | ledger، نطاقات، sidecars، SHA، اكتمال symbols | يصبح Import Receipt رسميًا |
| `dukascopy_daily_cache.py` | cache SQLite والتحقق من payload/transfer | ينفذ في Staging مع retry/idempotency |
| `dukascopy_event_data.py` | نقل/سلامة tick windows وحدود الأحداث | مطلوب للـ event-window research |
| `dukascopy_commissioning.py` | فحص DST وحدود 17:00 والأحداث | pre-paper broker calibration |
| `intraday_validation.py` | joint stationary bootstrap وnegative controls | يضاف إلى Validation Gates اليومية |
| `long_horizon.py` | panel، factors، labels، folds، audit | مسار slow-horizon مستقل |
| `long_horizon_research.py` | cross-sectional IC/quintile/regime screens | مخرجات بحث لا أوامر حية |
| `long_horizon_execution.py` | two-stage session ledger والـ target quantities | Portfolio Simulator/ledger مع فصل target عن capital weight |
| `long_horizon_portfolio_bridge.py` | ربط الأهداف بالـ synthetic ledger وفحص residuals | لا يستخدم كـ PnL رسمي قبل اكتمال التمويل |
| `portfolio_runner.py` و`portfolio_validation*.py` | تشغيل/تحقق portfolio على مستوى السلة | دمج مع Nexus risk/exposure validation |
| `research.py` و`planner.py` | تنسيق البحث والتخطيط ومخرجات التجارب | يحول إلى job planner لا CLI جانبي |

التقارير السابقة ذكرت معظم المفاهيم، لكنها لم تكن تسمي هذه الوحدات أو تربط كل وحدة بمخرج قابل للتنفيذ. يجب على الوكيل عدم اعتبار هذا الجرد اختياريًا.

### المراجعة الثانية: الميزات الإحصائية غير القابلة للحذف

المصدر لا يقتصر على FDR وSPA. يجب إضافة ما يلي إلى عقد Validation:

- DSR: Deflated Sharpe Ratio لمراعاة تعدد التجارب.
- PBO: Probability of Backtest Overfitting عند اختيار أفضل نتيجة من عدة محاولات.
- BH كحاجز رئيسي وBY كحساسية أكثر تحفظًا.
- Joint stationary/block bootstrap على أيام مشتركة، لا إعادة أخذ عينات مستقلة تخفي الارتباط.
- Joint-sign negative controls وfuture-information canary.
- سجل search budget وعدد العوامل والاختبارات والـ folds قبل تفسير النتيجة.
- إبقاء direction factors منفصلة عن risk-state factors؛ لا يسمح بخلط تنبؤ الاتجاه بتنبؤ حجم الحركة.
- عرض النتيجة `no_candidate_approved` رسميًا عندما لا تجتاز العوامل البوابات.

يجب أن يحتوي `validation_results` على `test_family`, `search_count`, `effective_trials`, `dsr`, `pbo`, `bh_q`, `by_q`, `bootstrap_method`, `negative_control_result`, و`approval_impact`.

### المراجعة الثالثة: سلامة البيانات والتقاويم

#### تقويم الأحداث الرسمية

عند استخدام أحداث Tokyo/ECB/WMR أو تقاويم البنوك المركزية، يلزم:

1. raw artifact وSHA-256 وmanifest لكل مصدر.
2. حالة `verified_actual_publication` أو `official_rule_derived` أو `unknown`.
3. `formal_experiment=true` و`manifest_verified=true` قبل تشغيل النتيجة الرسمية.
4. رفض التحميل عند غياب manifest أو اختلاف hash.
5. `fail_closed` للأحداث التي لا تتوفر لها أوقات نشر موثقة.
6. معالجة نصف أيام التداول وDST والجلسات المحلية بصورة صريحة.

لا يجوز تحويل حدث date-only إلى timestamp مصطنع ثم اعتباره وقت نشر حقيقيًا.

#### vintages والإصدارات

يجب فصل `current_vintage` عن `as_published_vintage`، وحفظ `revision_chain` و`publication_time_confidence` بقيم verified/derived/approximate/unknown. الاستخدام الرسمي لا يقبل approximate أو unknown إلا إذا كان run مصنفًا exploratory ولا يمكن ترقيته.

#### Dukascopy والتغذية الثنائية

يجب أن تسجل شاشة Import Center اكتمال المصدر بالساعات والأيام والرموز، SHA للـ payload والـ SQLite والـ normalized CSV، وpayload/database manifest. عند وجود ساعة غير مكتملة يجب عزل اليوم أو الساق المتأثرة، لا إعادة تطبيع صامتة. يجب فحص حدود New York 17:00 وTokyo/WMR وDST في commissioning report. Dukascopy مصدر quote وحيد، لذلك المقارنة مع broker spread إلزامية قبل paper/live، وتظل النتيجة `research_only` عند فشل المعايرة.

### المراجعة الرابعة: مطابقة Nexus الحقيقي وحدود التكامل

المسارات الحقيقية داخل Nexus هي `services/nexus_data`, `services/nexus_features`, `services/nexus_ml`, `services/nexus_agents`, `services/nexus_news`, `services/nexus_risk`, `services/nexus_executor`, `services/nexus_api`, و`services/nexus_monitor`. يجب أن يستخدم الوكيل هذه المسارات في خطة التعديل، لا مسميات افتراضية في جذر المشروع.

توجد نسخة من `fx-trading-system-main` داخل مشروع Nexus نفسه. يجب اتخاذ قرار واحد قبل أي تطوير:

- جعلها dependency/vendor مرجعية read-only بإصدار وcommit/hash مثبت.
- أو استخراج الحزم المعتمدة إلى `nexus_research` مع سجل مصدر واضح.
- ممنوع الاحتفاظ بنسخة داخلية ونسخة `work\\repo` مع تعديلات غير معروفة المصدر.
- لا يسمح بإعادة نسخ كامل المستودع داخل خدمات Nexus.

#### ملكية DuckDB

بما أن Nexus يطبق ملكية/سلامة DuckDB ويمتلك أكثر من خدمة، يجب أن تكون الكتابة عبر مالك واحد أو writer queue. Import/Quality/Research workers لا يفتحون نفس قاعدة التشغيل للكتابة المتزامنة. المطلوب: migration version، writer ownership، staging منفصل، read models أو API queries للواجهة، وidempotency key يمنع تكرار الصفوف.

#### أمن الصلاحيات

أفعال الاستيراد والتصحيح واعتماد dataset وتشغيل البحث وPromotion مختلفة الصلاحيات: read-only للمشاهدة، operator للاستيراد، reviewer للتصحيح والجودة، researcher للتجارب، approver للترقية، وtrading-admin للتأثير الحي. كل mutation يحتاج confirmation وactor وreason وcorrelation ID وaudit log، ولا تعرض provenance أو logs أسرار providers.

### المراجعة الخامسة: التشغيل، الإعادة، والواجهة

أُضيفت إلى متطلبات الوكيل: Job idempotency key، checkpoint/resume للـ backfill، rate limit وretry/backoff وDLQ، retention للـ raw/artifacts/traces، مؤشرات freshness وlag وmissing partitions وquality score وqueue depth، reconciliation يومي، pause/kill switch منفصل للاستيراد والبحث والتنفيذ، rollback لإصدارات dataset/feature/strategy/model/policy، ومنع promotion عند عدم تطابق code/data/config hashes.

تحتاج شاشة Data Hub إلى مسار ظاهر:

`Source → Fetch → Stage → Map → Normalize → Quality → Approve → Snapshot`

مع عدادات منفصلة: `submitted`, `fetched`, `normalized`, `accepted`, `duplicate`, `rejected`, `quarantined`, `corrected`, `unavailable`.

وتحتاج شاشة Validation إلى مصفوفة قرار:

| البوابة | النتيجة | أثرها |
|---|---|---|
| PIT/leakage | pass/fail | تمنع أو تسمح بالاستمرار |
| source manifest | verified/unverified | official أو exploratory |
| costs/financing | complete/incomplete | يمنع production عند النقص |
| walk-forward | pass/fail | صلاحية خارج العينة |
| DSR/PBO/FDR/SPA | metrics | ثقة الاختيار |
| news/calendar | available/blackout/stale | حجم أو منع أو سياق |
| risk/portfolio | pass/fail | حدود التعرض |
| paper evidence | pass/fail | شرط قبل live |

## 22) القرار النهائي بعد المراجعات الخمس

نعم، كانت هناك إضافات ضرورية. تم تضمينها في هذا الملحق، وأصبح التسليم الكامل للوكيل يشمل الآن:

1. جميع الوحدات المتخصصة في المصدر، وليس فقط أسماء الميزات العامة.
2. DSR/PBO وjoint bootstrap وcalendar manifest وfail-closed.
3. CFTC/vintages/external factors وDukascopy intake/cache/commissioning.
4. تقاويم العطل وDST وأيام النصف وسلامة أحداث WMR/البنوك المركزية.
5. نسخة المصدر المضمنة داخل Nexus ومنع الازدواجية غير القابلة للتتبع.
6. ملكية DuckDB، الصلاحيات، idempotency، resume، DLQ، retention، والـ rollback.
7. مصفوفة Validation وعدادات Import Center المطلوبة للواجهة.

الحالة: **التقرير جاهز للتسليم إلى وكيل التنفيذ كوثيقة تصميم وتدقيق، وليس كإذن لتعديل المشروع أو اعتماد أي استراتيجية للتداول الحي.**

### تثبيت حقائق المرجع التي يجب ألا تُفهم خطأ

- المرجع يعلن أكثر من 60 عاملًا سعريًا وتقلبًا وهيكليًا وتقويميًا ومتعدد العملات، وليس مجرد المؤشرات الأساسية.
- نطاق Dukascopy الرسمي في المرجع يتعامل مع 14 رمزًا، مع مسارات slow-horizon وFIX-W مختلفة؛ يجب ألا يخلط الوكيل بين universes.
- المصدر يذكر صراحة أن نتائج free-data الحالية لم تعتمد strategy اتجاهية، وأن بعض risk-state candidates انعكست خارج العينة؛ لذلك لا يجوز تسويق المصدر على أنه استراتيجية رابحة جاهزة.
- `proposed_tranche_weight` ليس capital weight، والـ 21/42/63-day sleeves ليست PnL رسميًا قبل اكتمال التمويل التاريخي وslippage والـ ledger.
- `research_only`, `exploratory`, `paper`, `candidate`, و`live` حالات مختلفة يجب حفظها في قاعدة البيانات والواجهة، لا اختزالها في `status=success`.

## 23) أمر تشغيل الوكيل — تدقيق نهائي بواسطة 15 وكيلًا

القسم التالي هو أمر جاهز للنسخ إلى وكيل التنفيذ. الغرض منه إجراء **تدقيق فقط**، وليس تنفيذ تطوير أو اختبارات.

### الأمر الجاهز

```text
أنت منسق تدقيق مشروع Nexus Trading System.

المشروع الهدف:
C:\Nexus-Trading-System-MT5

المشروع المرجعي:
C:\Users\rd66\Documents\Codex\2026-10-16\https-github-com-jlcbk-fx-trading\work\repo\fx-trading-system-main

وثيقة التدقيق الأساسية:
outputs\nexus-complete-agent-audit-ar.md

المطلوب:
نفّذ تدقيقًا معماريًا وتقنيًا مقارنًا عميقًا للمشروعين بواسطة 15 وكيلًا يعملون بالتوازي كخلية نحل. مدة التدقيق القصوى 30 دقيقة فقط. بعد انتهاء الوقت اجمع النتائج المتاحة، واذكر بوضوح ما لم يكتمل.

قواعد إلزامية:
1. قراءة وتحليل فقط.
2. ممنوع تعديل أي شفرة أو إعداد أو قاعدة بيانات أو وثيقة داخل مشروع Nexus.
3. ممنوع تشغيل اختبارات أو build أو lint أو compile أو notebooks.
4. ممنوع تشغيل أو إيقاف الخدمات أو فتح اتصال بقاعدة بيانات تشغيلية.
5. ممنوع الاتصال بوسيط أو MT5 أو API خارجي أو تنفيذ أمر تداول.
6. ممنوع إنشاء migrations أو ملفات مؤقتة داخل مشروع Nexus.
7. لا تعتبر أي نتيجة من المصدر Strategy جاهزة أو رابحة؛ تحقق من eligibility والحالة.
8. كل وكيل يعيد findings فقط بصيغة: severity، evidence path/line، impact، recommendation، confidence.
9. لا يكرر الوكلاء نفس النطاق؛ كل وكيل يلتزم بمهمته المحددة.
10. المنسق لا يخفي التعارضات؛ يسجلها ويعرض الدليلين.

طريقة العمل:
- ابدأ بتثبيت baseline: commit/hash، عدد الملفات، الخدمات، والعقود المقروءة.
- شغّل الوكلاء الخمسة عشر بالتوازي في نطاقات قراءة منفصلة.
- لا ينتظر وكيل نتيجة وكيل آخر؛ كل وكيل يقرأ baseline والتقرير الحالي.
- عند وجود اعتماد، سجله كـ dependency ولا يحول المهمة إلى عمل متسلسل.
- في آخر 5 دقائق: أوقف جمع النتائج الجديدة، نفذ reconciliation، أزل التكرار، واصنع الأولويات.
- أخرج تقريرًا موحدًا بتصنيف P0/P1/P2/P3، وجدولًا يربط كل ميزة بملف المالك والعقد والواجهة والبوابة.
- اذكر عدد الوكلاء الذين بدأوا، اكتملوا، تعذر تشغيلهم، أو انتهت مهلة كل منهم.

المخرج النهائي:
Audit Final Package يتضمن executive verdict، مصفوفة فجوات، خريطة الملفات، مخاطر الدمج، ترتيب التنفيذ، معايير القبول، وقائمة صريحة بالعناصر غير المفحوصة. لا تكتب أن العمل مكتمل إذا لم تثبت ذلك بالأدلة.
```

## 24) توزيع مهام الوكلاء الخمسة عشر

| رقم | دور الوكيل | نطاق الفحص | المخرج الإلزامي |
|---:|---|---|---|
| 1 | المنسق/حارس النطاق | baseline، الوقت، تعارضات النتائج، عدم التعديل | سجل تشغيل وملخص حالة كل وكيل |
| 2 | جرد المصدر | كل ملفات `src/fx_system` وREADME وdocs | مصفوفة ميزة/ملف/قرار نقل |
| 3 | المعمارية | حدود الخدمات وResearch وAgents وRisk وExecutor | خريطة تدفق وحدود coupling |
| 4 | استيراد التاريخي | MT5/CSV/Dukascopy/OANDA، backfill، checkpoint | فجوات الاستيراد وmanifest/resume |
| 5 | جودة البيانات | schema، OHLC، gaps، duplicates، outliers، quarantine | مصفوفة قواعد الجودة والبوابات |
| 6 | Asset Master | symbol mapping، FX/XAU/BTC/indices، sessions، DST | مخاطر العقود وحقول Asset Capability |
| 7 | الاستراتيجيات | العائلات الست، factors، DSL، labels، execution | خريطة Strategy Contract وlifecycle |
| 8 | التحقق الإحصائي | walk-forward، purge، embargo، FDR، DSR، PBO، SPA | بوابات Validation وحدود promotion |
| 9 | الأخبار والماكرو | news، CFTC، vintages، central banks، WMR، blackout | خريطة available-at وrevision وfail-closed |
| 10 | التكاليف والمحفظة | bid/ask، spread، swap، commission، slippage، exposure | Cost Contract وPortfolio Bridge risks |
| 11 | الأحداث وRedis | events/models/constants، streams، ACK، DLQ، correlation | عقد أحداث backward-compatible |
| 12 | قاعدة البيانات | DuckDB، schema، migrations، writer ownership، retention | خطة جداول وملكية كتابة بلا تعديل |
| 13 | API والواجهة | tabs، tables، filters، URL state، Import/Quality/Trace | خريطة شاشة/API ونواقص UX |
| 14 | الأمان والتشغيل | auth، roles، secrets، SSRF، kill switch، audit، rollback | مخاطر P0 التشغيلية والأمنية |
| 15 | المحكم النهائي | دمج النتائج، إزالة التكرار، التناقضات، الأولويات | Verdict نهائي وTop 15 corrections |

## 25) طريقة عمل خلية النحل

### المرحلة الأولى — 0 إلى 3 دقائق: توزيع baseline

- المنسق يعلن المسارات والنسخة والزمن النهائي.
- كل وكيل يثبت أنه يعمل في نطاقه فقط.
- لا يكتب أي وكيل داخل مشروع Nexus.

### المرحلة الثانية — 3 إلى 20 دقيقة: الفحص المتوازي

- كل وكيل يراجع الملفات ذات الصلة ويقارنها بالتقرير.
- كل finding يجب أن يضم دليلًا قابلًا للوصول، لا رأيًا عامًا.
- يميز الوكيل بين `confirmed`, `inferred`, `not_verified`.
- يسجل أثر المشكلة على البيانات أو البحث أو الواجهة أو التداول.

### المرحلة الثالثة — 20 إلى 25 دقيقة: تقاطع النتائج

- المنسق يطابق النتائج المتشابهة.
- الوكلاء لا يغيرون نتائج وكيل آخر؛ يضيفون اعتراضًا موثقًا عند الاختلاف.
- تُرفع المخاطر التي قد تسمح بتسرب المستقبل أو تجاوز Risk إلى P0.
- تُرفع مشاكل provenance وasset mapping وcost completeness إلى P0/P1.

### المرحلة الرابعة — 25 إلى 30 دقيقة: التقرير النهائي

- إنتاج جدول موحد: feature → source file → Nexus owner → contract → UI tab → gate → priority.
- إنتاج قائمة `not inspected` و`blocked by time`.
- إصدار قرار: `ready for implementation audit`, `needs clarification`, أو `blocked`.
- لا يصدر أي حكم live-ready من تدقيق ساكن فقط.

## 26) بروتوكول نتيجة كل وكيل

يجب أن يعيد كل وكيل هذا الشكل النصي:

```text
AGENT_ID:
ROLE:
STATUS: completed | partial | blocked
SCOPE:
FILES_REVIEWED:

FINDINGS:
- ID:
  SEVERITY: P0 | P1 | P2 | P3
  TYPE: missing | mismatch | risk | duplication | unclear
  EVIDENCE: absolute path and line/range when available
  OBSERVED:
  IMPACT:
  RECOMMENDATION:
  CONFIDENCE: high | medium | low

FEATURES_COVERED:
UNINSPECTED:
DEPENDENCIES:
```

## 27) ضوابط المنسق ضد النتائج الوهمية

- لا يعتمد finding بلا مسار ملف أو دليل واضح.
- لا يعد وجود class أو endpoint دليلًا على اكتمال السلوك.
- لا يعد test file دليلًا على نجاح الاختبار؛ الاختبارات ممنوعة في هذا التدقيق.
- لا يخلط بين `fetched_at` و`available_at`.
- لا يخلط بين `current_vintage` و`as_published_vintage`.
- لا يخلط بين `research_only` و`paper` أو `candidate` و`live`.
- لا يساوي midpoint ببيانات Bid/Ask.
- لا يسمح بتفسير `proposed_tranche_weight` كوزن رأسمالي أو PnL رسمي.
- لا يسمح للوكلاء بتعديل التقرير أثناء جمع النتائج؛ التعديل النهائي يكون بواسطة المنسق بعد reconciliation فقط.

## 28) شروط نجاح التدقيق خلال 30 دقيقة

يُعتبر التدقيق ناجحًا إذا:

1. تم تسجيل حالة جميع الوكلاء الخمسة عشر.
2. تمت تغطية كل نطاقات المصدر والهدف المذكورة في جدول الأدوار.
3. كل P0/P1 لديه دليل وتأثير ومالك مقترح.
4. تم تحديد جميع ميزات المصدر: من ينقل، من يكيّف، ومن يمنع نقله.
5. تم ربط Data Hub بالاستراتيجيات والأخبار والـ Risk والواجهة.
6. تم فصل ما هو مؤكد عن المستنتج وغير المفحوص.
7. لم تُشغّل اختبارات أو خدمات ولم تُعدّل الشفرة أو قاعدة البيانات.
8. صدر تقرير نهائي قابل للتنفيذ دون ادعاء readiness للتداول الحي.

الحالة المطلوبة بعد التنفيذ: **Audit Only — No Tests — No Code Changes — No Database Changes — No Live Trading**.
