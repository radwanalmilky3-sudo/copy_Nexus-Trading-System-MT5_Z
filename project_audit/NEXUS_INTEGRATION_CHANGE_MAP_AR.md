# خريطة تعديل Nexus لدمج إمكانيات fx-trading-system

## القرار المعماري

سنضيف طبقة `nexus-research` مستقلة داخل مشروع Nexus. لن ننقل كود البحث إلى `nexus-risk` أو `nexus-executor`، ولن نسمح لمحرك البحث بإرسال أوامر إلى MT5. مصدر البحث سيبقى مسؤولًا عن البحث، البيانات التاريخية، الاختبارات، والتقارير؛ بينما يبقى Nexus مسؤولًا عن التشغيل الحي، المخاطر النهائية، والتنفيذ.

```text
nexus-data → quality/staging → nexus-research
                                      ↓
                              ResearchSignal
                                      ↓
                         target asset/cost adapter
                                      ↓
                              TradeProposal
                                      ↓
                                nexus-risk
                                      ↓
                              nexus-executor → MT5
```

## الملفات التي سنضيفها

### Backend

```text
services/nexus_research/__init__.py
services/nexus_research/main.py
services/nexus_research/worker.py
services/nexus_research/source_adapter.py
services/nexus_research/config.py
services/nexus_research/contracts.py
services/nexus_research/artifacts.py
services/nexus_research/datasets.py
services/nexus_research/quality.py
services/nexus_research/validation.py
services/nexus_research/promotion.py
services/nexus_research/lineage.py
services/nexus_research/requirements.txt
```

### Shared contracts

```text
shared/research_models.py
shared/research_events.py
shared/data_contracts.py
shared/asset_capabilities.py
shared/trace_models.py
```

### API

```text
services/nexus_api/routers/research.py
services/nexus_api/routers/data_import.py
services/nexus_api/routers/data_quality.py
services/nexus_api/routers/audit.py
services/nexus_api/research_client.py
services/nexus_api/data_import_client.py
```

### UI

```text
dashboard/src/app/dashboard/research/page.tsx n+dashboard/src/app/dashboard/data/page.tsx
dashboard/src/app/dashboard/data/import/page.tsx
dashboard/src/app/dashboard/data/quality/page.tsx
dashboard/src/app/dashboard/data/lineage/page.tsx
dashboard/src/app/dashboard/validation/page.tsx
dashboard/src/app/dashboard/audit/page.tsx
dashboard/src/app/dashboard/live-feed/page.tsx
dashboard/src/components/research/ResearchRunTable.tsx
dashboard/src/components/research/ResearchArtifactTree.tsx
dashboard/src/components/research/ValidationGateTable.tsx
dashboard/src/components/data/ImportWizard.tsx
dashboard/src/components/data/ImportJobTable.tsx
dashboard/src/components/data/QualityCheckTable.tsx
dashboard/src/components/data/CorrectionQueue.tsx
dashboard/src/components/data/LineageGraph.tsx
dashboard/src/components/audit/TraceTree.tsx
dashboard/src/components/audit/AuditEventTable.tsx
dashboard/src/components/shared/GlobalDataFilters.tsx
dashboard/src/hooks/useResearch.ts
dashboard/src/hooks/useDataImport.ts
dashboard/src/hooks/useDataQuality.ts
dashboard/src/hooks/useAudit.ts
```

> ملاحظة: السطر الذي يحتوي على `page.tsx\ n+` في القائمة السابقة هو خطأ تنسيقي في العرض؛ المسار الصحيح هو `dashboard/src/app/dashboard/research/page.tsx`.

## الملفات الحالية التي سنعدلها

### 1. خدمة التشغيل

`run.py`

- تسجيل `nexus-research` ضمن الخدمات.
- عدم تكرار port definitions؛ يجب أن يقرأ supervisor من `shared/constants.py`.
- إضافة startup dependency: `nexus-research` يعتمد على `nexus-data` فقط، ولا يعتمد على `nexus-executor`.

`shared/constants.py`

- إضافة port للخدمة الجديدة.
- إضافة Streams:

```text
stream:research:dataset
stream:research:job
stream:research:artifact
stream:research:validation
stream:research:candidate
stream:research:promotion
stream:signals:research
stream:data:quality
stream:data:import
stream:audit:trace
```

### 2. عقود الأحداث

`shared/events.py`

نضيف نماذج مستقلة، ولا نوسع `SignalEvent` بطريقة تكسر المستهلكين الحاليين:

- `DatasetEvent`
- `ImportJobEvent`
- `QualityCheckEvent`
- `ResearchJobEvent`
- `ResearchArtifactEvent`
- `ResearchValidationEvent`
- `ResearchCandidateEvent`
- `PromotionEvent`
- `ResearchSignalEvent`
- `TraceEvent`

كل حدث يحمل:

```text
schema_version
event_id
correlation_id
causation_id
run_id أو dataset_id
source
observed_at
available_at
created_at
manifest_hash
status
```

`shared/models.py`

- إبقاء `Signal` للـML الحالي.
- إضافة `ResearchSignal` للنتائج البحثية.
- إضافة `ResearchArtifactRef`.
- إضافة `DataQualitySummary`.
- إضافة `TradeProposalProvenance`.
- عدم السماح بتحويل `ResearchSignal` إلى `TradeProposal` إلا بعد التحقق من `execution_eligibility` وasset capability.

### 3. البيانات والتخزين

`services/nexus_data/duckdb_store.py`

نضيف جداول تشغيلية مستقلة للبيانات والـresearch:

```sql
datasets
dataset_sources
dataset_partitions
import_jobs
import_job_errors
data_quality_runs
data_quality_checks
data_corrections
data_quarantine
research_runs
research_artifacts
research_signals
research_trades
research_equity_points
research_validation_results
research_promotions
lineage_edges
trace_events
```

لا نضع backtest trades داخل `trades` الحالية؛ جدول `trades` يبقى للتداول التشغيلي. نحتاج `research_trades` لأن المصدر يملك gross/net PnL، costs، R multiple، exit reason، initial risk، group ID، وmanifest مختلفة عن صفقة MT5.

الفهارس المطلوبة:

```sql
(dataset_id, symbol, timeframe, timestamp)
(run_id, artifact_type)
(run_id, symbol, signal_timestamp)
(source_sha256)
(signal_id)
(correlation_id, created_at)
(status, updated_at)
```

`services/nexus_data/main.py`

- إضافة endpoints داخلية لإدخال staging واعتماد canonical.
- عدم السماح بكتابة canonical مباشرة من الواجهة.
- إضافة source availability وpayload hash وvintage وquality إلى provenance.
- فصل synthetic data بوضوح ومنع استخدامها في research formal أو live.
- جعل import jobs قابلة للاستئناف بدل الاعتماد على asyncio task فقط.

`services/nexus_data/mt5_connector.py`

- يبقى مسؤولًا عن live MT5.
- لا نستخدمه لاستيراد التاريخ الطويل وحده.
- نضيف adapter تاريخي منفصل لـCSV/Dukascopy/Parquet.

### 4. خدمة البحث

`services/nexus_research/source_adapter.py`

خريطة المصدر:

| المصدر | ما يحدث بعد الدمج |
|---|---|
| `config.py` | ResearchConfig منفصل ومتحقق بـPydantic |
| `data.py` | provider adapter إلى canonical Dataset |
| `point_in_time.py` | إلزامي قبل feature/research acceptance |
| `research_controls.py` | future canary وnegative controls وdate controls |
| `factor_research.py` | async research job |
| `factor_forward.py` | forward job بعد freeze فقط |
| `engine.py` | research backtest فقط |
| `portfolio.py` | portfolio research bridge |
| `portfolio_ledger.py` | paper/research ledger قبل live |
| `broker_cost_contract.py` | CostContract موحد |
| `research_registry.py` | registry audit وsearch exposure |
| `reporting.py` | artifacts إلى store + SHA |
| `brokers/oanda.py` | لا يُستخدم داخل Nexus |

### 5. الربط مع risk/executor

`services/nexus_risk/main.py`

- إضافة فحص provenance.
- قبول `TradeProposal` فقط إذا كان مصدره candidate مسموحًا.
- فرض الحد الأكثر تحفظًا بين ResearchRiskProfile وNexus hard limits.
- التحقق من freshness وexpiry وduplicate proposal.

`services/nexus_executor/main.py`

- لا يتغير مسار MT5 الأساسي.
- إضافة `research_signal_id` و`run_id` و`correlation_id` إلى order metadata.
- رفض orders التي لا تحمل risk decision صالحًا.
- reconciliation بين order/fill/position/trade.

`shared/asset_specs.py` و`config/assets.yaml`

- إضافة capability matrix لاستخدام كل factor مع كل asset.
- منع نقل عامل FX إلى XAUUSD/BTCUSD تلقائيًا.
- توحيد pip size، contract size، tick value، margin، volume step، quote currency، session.

## نظام استيراد البيانات المقترح

### دورة الحياة

```text
created
  ↓
mapping_review
  ↓
downloading
  ↓
staging
  ↓
normalizing
  ↓
quality_check
  ├─ accepted_formal
  ├─ accepted_research_only
  ├─ quarantined
  └─ rejected
```

### Import Wizard

#### الشاشة 1: المصدر

- MT5
- IBKR
- Dukascopy
- CSV
- Parquet
- API

#### الشاشة 2: النطاق

- symbols
- asset class
- timeframe
- start/end
- historical/live
- timezone
- account/broker

#### الشاشة 3: Mapping

جدول يوضح:

```text
source column → canonical column → type → transform → validation rule
```

#### الشاشة 4: Preview

- أول 20 صفًا وآخر 20 صفًا.
- duplicate count.
- missing count.
- time range.
- bid/ask validity.
- OHLC validity.
- estimated storage.

#### الشاشة 5: Quality

كل check يعرض pass/warn/fail، عدد الصفوف، الأدلة، ومكان التصحيح.

#### الشاشة 6: Commit

- staging hash.
- raw hash.
- manifest.
- acceptance decision.
- dataset ID.

#### الشاشة 7: Job details

- progress.
- throughput.
- retries.
- current partition.
- failed rows.
- quarantine download.
- cancel/resume.

## تصحيح وتنظيف البيانات

لا نعدل المصدر الأصلي. التصحيح يكون كـversioned transformation:

```text
raw row
  ↓ transformation_id
corrected row
  ↓ quality result
canonical row
```

أنواع التصحيح:

- timezone normalization.
- symbol alias mapping.
- decimal/digits normalization.
- duplicate collapse.
- bad OHLC quarantine.
- bid > ask quarantine.
- spread outlier marking.
- missing bar classification: market closed / provider empty / provider failed.
- forming candle rejection.
- timestamp ordering repair فقط إذا كان موثقًا، وإلا quarantine.

كل تصحيح يسجل:

```text
correction_id
dataset_id
row_key
rule_id
before_hash
after_hash
reason
automated_or_manual
actor
created_at
```

## ربط الأصل والمصدر بدقة

نحتاج ثلاثة مفاهيم منفصلة:

1. `source_id`: المزود، مثل MT5 أو Dukascopy أو CSV.
2. `dataset_id`: نسخة محددة بعد الاستيراد والـmanifest.
3. `asset_id`: الأصل المعياري، مثل EURUSD أو XAUUSD.

ولا يكفي الاسم. نحتاج:

```text
asset_id
broker_symbol
asset_class
base_currency
quote_currency
account_currency
contract_size
digits
pip_size
tick_size
tick_value
volume_min
volume_step
session_timezone
provider_symbol
mapping_version
effective_from
effective_to
```

لذلك يمكن أن نثبت أن `EURUSD` من Dukascopy ليس بالضرورة نفس quote contract الخاص بـMT5، حتى لو كان الاسم متساويًا.

## شاشات التنظيف والاعتماد

### Data Quality Home

بطاقات: datasets accepted، quarantined، stale، missing، failed، last validation.

### Quality Check Table

فلاتر: dataset، source، symbol، timeframe، severity، status، check type، date.

### Correction Queue

جدول للصفوف المرفوضة مع before/after، rule، reason، approve/reject، bulk action محمي.

### Lineage

شجرة:

```text
source payload
 → import job
 → dataset version
 → quality run
 → research run
 → candidate
 → proposal
 → risk decision
 → order/fill
```

### Live Feed

جدول حي يعرض source، symbol، last tick، last bar، latency، freshness، spread، quality، reconnect count، last error.

## ترتيب التنفيذ الآمن

### المرحلة 1: العقود فقط

تعديل `shared/*` و`run.py` وschemas دون تشغيل research أو live جديد.

### المرحلة 2: التخزين والـcatalog

إضافة الجداول والـmanifest والـlineage وimport job state.

### المرحلة 3: Data Hub

إضافة adapters وstaging وquality وquarantine.

### المرحلة 4: Research Worker

تشغيل المصدر بشكل async وإخراج artifacts فقط.

### المرحلة 5: Validation/Research UI

إضافة التبويبات والجداول والفلاتر والتفاصيل.

### المرحلة 6: Paper Bridge

ربط ResearchSignal بـTradeProposal وRiskDecision وPaperExecutor فقط.

### المرحلة 7: Live Gate

بعد اكتمال reconciliation والـaudit والـexpiry والـapproval، وليس قبل ذلك.

## شرط عدم كسر المعمارية

أي تعديل يفشل إذا أدى إلى أحد الأمور التالية:

- اتصال dashboard مباشر بـDuckDB.
- كتابة service إلى قاعدة يملكها service آخر دون API/stream.
- import research أثناء event loop الحي.
- تحويل research signal مباشرة إلى order.
- غياب `available_at` أو `manifest_hash`.
- خلط `research_trades` مع `trades` التشغيلية.
- تغيير hard risk guardrail من dashboard.
- قبول dataset synthetic كأنه formal.

هذا هو نطاق التعديل المطلوب قبل بدء التنفيذ الفعلي. لم يتم تعديل أي ملف في مشروع Nexus.

## ملحق: الاستراتيجيات والاختبار وربط الأخبار والعقود

### هل تم دمجها؟

لا. لم يتم دمج أي ميزة في الكود. ما يلي هو التصميم الكامل الذي يجب تنفيذه لاحقًا:

```text
Strategy Development
        ↓
Dataset + Features + Labels
        ↓
Backtest with costs
        ↓
Walk-forward / Purged CV
        ↓
Statistical validation
        ↓
Research Registry
        ↓
Promotion gate
        ↓
Paper proposal
        ↓
nexus-risk
```

### الاستراتيجيات التي يجب إضافتها

من المصدر المرجعي:

1. `regime_mean_reversion`
2. `trend_pullback`
3. `session_breakout`
4. `false_breakout_reversal`
5. `currency_strength_reversion`
6. `cointegration_spread`
7. factor-based strategies من `factor_research.py` و`factor_dsl.py`.
8. slow-horizon sleeves من `long_horizon_*` كبحث مستقل، وليس تداولًا مباشرًا.
9. intraday/event strategies من `intraday_*` بعد اكتمال calendars وspread filters.

### ما يجب إضافته لتطوير استراتيجية

يجب أن تكون كل استراتيجية كيانًا مسجلًا، وليس class فقط:

```text
strategy_id
name
version
asset_universe
timeframes
feature_set
label_contract
entry_contract
exit_contract
cost_contract_id
risk_profile_id
research_status
paper_enabled
live_enabled
code_revision
config_hash
created_at
```

ولا يسمح النظام بتشغيل استراتيجية بلا `feature_set` و`label_contract` و`cost_contract` و`validation_status`.

### محرك الاختبار المطلوب

يجب أن يضيف Nexus مسارًا موحدًا للاختبار:

- backtest تاريخي.
- bid/ask execution.
- spread/slippage/commission/swap.
- next-bar execution.
- stop/target ambiguity policy.
- portfolio risk.
- currency exposure.
- leverage.
- drawdown/daily loss gates.
- strategy comparison.
- walk-forward.
- purged/embargo validation.
- block bootstrap.
- BH/BY FDR.
- negative controls.
- future-information canary.
- one-time holdout.
- forward evaluation.
- search registry وtrial count.

الـBacktest الحالي في Nexus لا يكفي وحده؛ يجب أن نضيف `research backtest` منفصلًا بمخرجات source-native، ثم نعرض نتائجه من خلال API.

### مخرجات اختبار الاستراتيجية

لكل run يجب حفظ:

```text
metrics.json
trades.csv
equity.csv
signals.csv
rejected_signals.json
validation_results.json
run_manifest.json
report.md
```

وتحويلها إلى:

- `research_runs`
- `research_artifacts`
- `research_signals`
- `research_trades`
- `research_equity_points`
- `research_validation_results`

### ربط الاستراتيجيات بالأخبار

الربط يجب ألا يكون نصيًا أو مباشرًا من LLM إلى order. نحتاج طبقة `EventContext` موحدة:

```text
market signal
    + macro events
    + central-bank calendar
    + news sentiment
    + geopolitical events
    + cross-asset factors
    + blackout state
    + source freshness
          ↓
     Strategy Context
          ↓
     signal adjustment / veto / explanation
```

الأخبار لا تعدل signal بصمت. لكل تأثير يجب تحديد نوعه:

- `confirmation`: يؤكد الإشارة.
- `contradiction`: يخفض confidence.
- `blackout`: يمنع الدخول.
- `risk_only`: يؤثر في الحجم لا الاتجاه.
- `context_only`: يظهر للمستخدم ولا يغير القرار.
- `stale`: لا يستخدم.

### الربط مع خدمة الأخبار الحالية

الربط المقترح:

```text
nexus-news
  → NewsAlertEvent / CalendarEvent
  → EventContext Builder
  → nexus-features / nexus-agents
  → ResearchSignal أو SignalEvent
  → nexus-risk
```

يجب استخدام البيانات الموجودة في Nexus مثل:

- `fund_events`
- `event_expectations`
- `data_vintages`
- `central_bank_events`
- `news_articles`
- `news_nlp_analysis`
- `fundamental_factor_scores`
- `fundamental_fusion_results`
- `fundamental_blackout_windows`
- `fundamental_guard_decisions`

ولا نكرر هذه الجداول في source research. نضيف فقط foreign references إلى `source_id` و`event_id` و`available_at` و`vintage_id`.

### عقود الأخبار والبحث

كل خبر أو حدث يدخل استراتيجية يجب أن يحتوي على:

```text
event_id
source_id
event_type
symbol/currency scope
observed_at
published_at
available_at
known_at
received_at
freshness_state
data_quality_score
reliability_score
blackout_state
raw_hash
schema_version
```

إذا غاب `available_at` أو كان المصدر stale، لا يستخدم الحدث في formal backtest أو promotion.

### اختبار الأخبار مع الاستراتيجية

لا نختبر استراتيجية أخبار بتشغيلها على current-vintage. يجب أن توجد أوضاع اختبار منفصلة:

1. `price_only`: السعر فقط.
2. `event_as_published`: الأخبار حسب وقت نشرها الفعلي.
3. `event_with_blackout`: يمنع التداول داخل window الحدث.
4. `event_as_risk_control`: يخفض الحجم فقط.
5. `negative_news_control`: أخبار عشوائية/غير مؤثرة لاختبار عدم وجود overfit.

كل وضع ينتج manifest مستقلًا ولا يجوز دمج النتائج في رقم واحد بدون إظهار الوضع والتكلفة والعينة.

### شاشات تطوير واختبار الاستراتيجيات

نضيف داخل Research:

#### Strategy Catalog

قائمة الاستراتيجيات مع status، version، symbols، timeframe، features، event dependency، promotion state.

#### Strategy Builder

اختيار:

- universe.
- timeframe.
- feature groups.
- entry/exit.
- news policy.
- cost contract.
- risk profile.
- train/test/holdout ranges.

لا يسمح builder بتغيير hard risk limits.

#### Backtest Workspace

جداول ورسوم:

- trades.
- equity.
- drawdown.
- costs.
- exposure.
- rejected signals.
- event windows.
- source quality.

#### Validation Workspace

يعرض gates منفصلة:

- data quality.
- PIT/leakage.
- sample coverage.
- walk-forward.
- FDR.
- bootstrap.
- negative controls.
- holdout.
- forward.

#### Strategy Promotion

لا يتم promotion إلا إذا كان:

```text
data_gate = PASS
pit_gate = PASS
cost_gate = PASS
validation_gate = PASS
holdout_gate = PASS
forward_gate = PASS
reviewer_approval = TRUE
```

### العقود التي يجب أن تغطي كل شيء

نحتاج عقودًا مستقلة لكن مترابطة:

1. `DataContract`: source/schema/asset/time/quality.
2. `AvailabilityContract`: observed/available/decision timestamps.
3. `FeatureContract`: feature name/version/origin/availability.
4. `LabelContract`: horizon/entry/exit/ambiguity policy.
5. `CostContract`: spread/slippage/commission/swap/financing.
6. `RiskContract`: sizing/exposure/leverage/drawdown.
7. `StrategyContract`: logic/universe/version/status.
8. `ResearchRunContract`: config/data/code/manifest.
9. `ValidationContract`: tests/statistics/gates.
10. `PromotionContract`: reviewer/status/expiry/environment.
11. `ProposalContract`: signal → target asset/quantity/SL/TP.
12. `ExecutionContract`: risk approval/order/fill/reconciliation.
13. `AuditContract`: actor/action/reason/before/after/correlation.

### الخلاصة الصريحة

حتى الآن لم تُضف الاستراتيجيات أو اختبارات المصدر أو ربط الأخبار إلى Nexus فعليًا. ما تم إنجازه هو تحديد طبقة الدمج. التنفيذ الصحيح يحتاج إضافة `nexus-research`، عقود البحث، جداول lineage، jobs غير متزامنة، UI research/validation، وربطًا مضبوطًا بخدمة `nexus-news` ثم `nexus-risk`.
