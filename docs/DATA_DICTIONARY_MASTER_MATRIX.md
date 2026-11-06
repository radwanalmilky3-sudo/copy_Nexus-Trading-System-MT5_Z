# المصفوفة الرئيسية — تصنيف جداول قاموس البيانات كاملة

> مراجعة شاملة لكل جدول في NEXUS_Data_Dictionary_Reviewed.docx: القرار، الفريم، الخدمة الكاتبة، والشاشة التي يظهر فيها.
> القرارات: **P0** اعتماد فوري (سد فجوات حية) · **P1** قريب (جودة وذاكرة) · **P2** لاحق (توحيد وبنية) · **P3** مؤجل (عند توسعة) · **X** مستبعد/مدموج في الموجود.

**التوزيع:** P0=12 · P1=59 · P2=49 · P3=84 · X=12 — الإجمالي 216


## core

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 1 | `core.organizations` | **X** | — | — (مالك واحد؛ يُعاد عند تعدد العملاء) | تعريف المؤسسة المالكة للنظام، ودعم تعدد المؤسسات إذا توسع NEXUS إلى بيئة متعددة العملاء. |
| 2 | `core.users` | **P2** | nexus_api | مركز المستخدمين والتنبيهات (توثيق الموجود في JWT auth) | حسابات مستخدمي لوحة NEXUS وواجهات الإدارة. |
| 3 | `core.roles` | **P2** | nexus_api | مركز المستخدمين (أدوار super_admin الحالية) | تعريف أدوار المستخدمين والوكلاء والخدمات. |
| 4 | `core.permissions` | **P2** | nexus_api | مركز المستخدمين | تعريف الصلاحيات الدقيقة على مستوى الموارد والعمليات. |
| 5 | `core.role_permissions` | **P2** | nexus_api | — (مع roles) |  |
| 6 | `core.user_roles` | **P2** | nexus_api | — (مع roles) |  |
| 7 | `core.services` | **P2** | nexus_monitor | System Diagnostic (details) — سجل الخدمات التسع | سجل الخدمات المصغرة التسع، وأي خدمات إضافية مستقبلاً. |
| 8 | `core.service_instances` | **P2** | nexus_monitor | System Diagnostic — نسخة كل خدمة ومنفذها | تسجيل كل نسخة تشغيلية من الخدمة؛ لأن الخدمة الواحدة يمكن أن تعمل بأكثر من نسخة. |
| 9 | `core.system_settings` | **X** | — | مدموج في .env + Settings الحالية — لا يُكرر |  |
| 10 | `core.configuration_versions` | **P1** | nexus_api | Settings → نسخ الإعدادات (يتكامل مع حفظ المسودة vN الموجود) | حفظ تاريخ تغييرات الإعدادات وإمكانية معرفة الإعداد الذي كان سارياً وقت حدوث أي قرار. |
| 11 | `core.audit_events` | **P2** | nexus_api | الأدلة والسجل (توحيد مع broker_account_events) | سجل تدقيق عام لكل العمليات الحساسة والإدارية. |
| 12 | `core.idempotency_keys` | **P1** | nexus_api | غير مرئي — يمنع تكرار الأوامر عند إعادة الإرسال | منع تكرار تنفيذ الطلب عند إعادة الإرسال بسبب انقطاع الاتصال أو إعادة المحاولة. |
| 13 | `core.outbox_events` | **P2** | nexus_data | غير مرئي — يضمن أحداث Redis لا تُفقد | ضمان عدم فقدان أحداث النظام عند نشرها إلى Redis أو Message Broker. |
| 14 | `core.inbox_events` | **P2** | nexus_data | غير مرئي — يمنع المعالجة المزدوجة | تسجيل الأحداث المستلمة لمنع تكرار معالجتها. |

## ref

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 15 | `ref.currencies` | **X** | — | — |  |
| 16 | `ref.countries` | **X** | — | — |  |
| 17 | `ref.timeframes` | **P2** | nexus_data | Settings → عمود الفريم لكل أصل (توثيق الموجود) | تعريف الأطر الزمنية الموحدة بين MT5 وNEXUS. |
| 18 | `ref.market_sessions` | **P2** | nexus_risk | Settings → بوابة الجلسات (توثيق الموجود) |  |

## broker

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 29 | `broker.brokers` | **P2** | nexus_data | Settings → جدول الوسطاء (توحيد مع broker_profiles الموجود) |  |
| 30 | `broker.broker_servers` | **P2** | nexus_data | Settings → الخادم في بيانات الحساب |  |
| 31 | `broker.mt5_terminals` | **P2** | nexus_data | — (يغذي MT5_PATH والاتصال) | تسجيل محطات MT5 المثبتة ومساراتها. |
| 32 | `broker.trading_accounts` | **P2** | nexus_data | Settings → جدول الحسابات (توحيد مع broker_accounts) |  |
| 33 | `broker.mt5_terminal_snapshots` | **P3** | nexus_data | — | لقطات حالة المحطة والاتصال. |
| 34 | `broker.mt5_program_instances` | **X** | — | — (لا EA خارجي مبرمج بعد) | نسخ البرامج العاملة على المحطة. |
| 35 | `broker.mt5_connection_events` | **P1** | nexus_data | Settings → تبويب الاتصال: تاريخ كل اتصال/فصل | سجل أحداث الاتصال والفصل. |
| 36 | `broker.account_property_snapshots` | **P3** | nexus_data | — | تخزين خصائص الحساب typed بدلاً من إنشاء عمود لكل خاصية ممكنة في MT5. |
| 37 | `broker.account_margin_snapshots` | **P3** | nexus_data | — |  |
| 38 | `broker.account_permissions` | **P3** | nexus_data | — |  |
| 39 | `broker.instruments` | **P1** | nexus_data | Settings → الأصول (الرمز الموحد عبر الوسطاء) | توحيد رموز التداول بين الوسطاء. هذا مهم لأن XAUUSD قد يظهر بأسماء مختلفة لدى وسيطين. |
| 40 | `broker.broker_symbols` | **P1** | nexus_data | Settings → الأصول (كاش 2060 رمز بدل جلبها كل مرة) | ربط الرمز الموحد برمز الوسيط الفعلي. |
| 41 | `broker.symbol_property_snapshots` | **P3** | nexus_data | — |  |
| 42 | `broker.symbol_trade_sessions` | **P2** | nexus_data | Settings → الجلسات والتوقيت (يكمل المزامنة الموجودة) |  |
| 43 | `broker.symbol_margin_rates` | **P3** | nexus_data | — |  |
| 44 | `broker.symbol_price_statistics` | **P3** | nexus_data | — |  |
| 45 | `broker.symbol_swap_history` | **P3** | nexus_data | — |  |
| 46 | `broker.symbol_option_properties` | **X** | — | — (لا خيارات) |  |

## market

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 47 | `market.data_sources` | **P2** | nexus_data | System Diagnostic (details) — مصدر كل شمعة: MT5/CCXT | تعريف مصادر بيانات السوق؛ مثل MT5، ومزود أسعار خارجي، ومصدر بيانات تاريخية. |
| 48 | `market.market_data_streams` | **X** | — | مدموج في ticks/ohlcv الموجودة + Redis streams | تعريف تدفقات البيانات التي تستقبلها NEXUS. |
| 54 | `market.timeseries_sync_jobs` | **P2** | nexus_data | — (توحيد مع ohlcv_backfill_runs الموجود) | إدارة استيراد البيانات التاريخية من MT5. |
| 55 | `market.data_ingestion_batches` | **P2** | nexus_data | — (توحيد مع ohlcv_manifests) | كل دفعة إدخال لها سجل مستقل يمكن تتبعه. |
| 56 | `market.market_data_gaps` | **P1** | nexus_data | System Diagnostic (details) + التحليل الأساسي | تسجيل الفجوات الزمنية في البيانات. |
| 57 | `market.market_data_corrections` | **P1** | nexus_data | التحليل الأساسي → مصادر البيانات (تصحيح بلا محو) | حفظ التصحيحات التاريخية دون محو القيمة الأصلية. |
| 58 | `market.market_data_replays` | **P3** | nexus_data | — | إعادة تشغيل تدفقات البيانات التاريخية لأغراض الاختبار والتحليل. |
| 59 | `market.market_data_quality_snapshots` | **P1** | nexus_data | System Diagnostic — بند جودة البيانات | ملخص جودة تدفقات السوق على مستوى المصدر والرمز والفترة. |
| 60 | `market.market_event_archive` | **P3** | nexus_data | — | أرشفة أحداث السوق الخام التي لا تستحق أن تتحول كلها إلى أعمدة ثابتة، مع الاحتفاظ بالحمولة الأصلية. |

## context

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 61 | `context.news_providers` | **P1** | nexus_news | Settings → الشريط الإخباري (المزودون المفعّلون) |  |
| 62 | `context.news_sources` | **P2** | nexus_news | — | تعريف القنوات أو الحسابات أو المواقع التابعة لمزود الأخبار. |
| 63 | `context.news_articles` | **P1** | nexus_news | تبويب الأخبار — أرشيف دائم بدل البث العابر | الجدول المركزي للأخبار. |
| 64 | `context.news_article_versions` | **P3** | nexus_news | — | حفظ تغييرات الخبر إذا عدّل المصدر عنوانه أو نصه. |
| 65 | `context.news_entities` | **P3** | nexus_news | — | الأشخاص والمؤسسات والأدوات المالية المستخرجة من الأخبار. |
| 66 | `context.news_article_entities` | **P3** | nexus_news | — | ربط الخبر بالكيانات التي يتناولها. |
| 67 | `context.news_sentiment_results` | **P1** | nexus_news | تبويب الأخبار — مشاعر مرصودة لكل خبر | نتائج تحليل المشاعر؛ بما في ذلك FinBERT أو LLM أو نموذج داخلي. |
| 68 | `context.news_instrument_impact` | **P1** | nexus_news | تبويب الأخبار — تأثير الخبر على XAUUSD | تقييم تأثير الخبر على أداة مالية معينة. |
| 69 | `context.news_duplicate_groups` | **P3** | nexus_news | — | تجميع الأخبار المتكررة أو المنقولة عن المصدر نفسه. |
| 70 | `context.news_duplicate_members` | **P3** | nexus_news | — |  |
| 71 | `context.economic_calendar_countries` | **P2** | nexus_news | — |  |
| 72 | `context.economic_calendar_events` | **P1** | nexus_news | تبويب الأخبار — التقويم الاقتصادي | تعريف الحدث الاقتصادي المتكرر. |
| 73 | `context.economic_calendar_values` | **P1** | nexus_news | تبويب الأخبار — القيم الفعلية مقابل المتوقعة | الحدث الاقتصادي في تاريخ محدد. |
| 74 | `context.economic_calendar_history` | **P3** | nexus_news | — | حفظ تاريخ تعديلات القيم الاقتصادية. |
| 75 | `context.economic_calendar_requests` | **P3** | nexus_news | — |  |
| 76 | `context.economic_blackout_windows` | **P1** | nexus_risk | تبويب الأخبار + Risk Monitor (نوافذ الحجب المفعّلة) | فترات منع أو تقييد التداول حول الأحداث الاقتصادية. |
| 77 | `context.macro_indicators` | **P3** | nexus_news | — | قاموس المؤشرات الاقتصادية الكبرى. |
| 78 | `context.macro_indicator_values` | **P3** | nexus_news | — |  |
| 79 | `context.cross_asset_observations` | **P1** | nexus_data | Risk Monitor → الترابط (DXY/US10Y لحزمة الذهب) | سجل موحد لملاحظات الأدوات الخارجية مثل DXY وUS10Y ومؤشرات أخرى. |

## execution

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 80 | `execution.trading_sessions` | **P3** | nexus_executor | — (115 عموداً؛ يُبسّط عند الحاجة) | جلسات التداول التشغيلية التي تجمع قرارات وتحركات التنفيذ خلال فترة محددة. |
| 91 | `execution.execution_intents` | **P0** | nexus_executor | Live Decision + تبويب Positions (حالة النية قبل التنفيذ) | حفظ نية التداول قبل تحويلها إلى طلب MT5. هذا يفصل قرار الوكيل عن أمر التنفيذ الفعلي. |
| 92 | `execution.execution_approvals` | **P0** | nexus_risk | Risk Monitor — الموافقات المعلقة والمؤرخة |  |
| 93 | `execution.execution_attempts` | **P0** | nexus_executor | تبويب Positions — كل محاولة إرسال ونتيجتها |  |
| 94 | `execution.execution_costs` | **P1** | nexus_executor | تبويب Backtest — التكاليف الفعلية مقابل المقدرة | تفصيل تكاليف التنفيذ الفعلية أو المقدرة. |
| 95 | `execution.execution_slippage` | **P1** | nexus_executor | تبويب Backtest — الانزلاق المقاس لكل تنفيذ | قياس الانزلاق السعري لكل تنفيذ. |
| 96 | `execution.shadow_trades` | **P1** | nexus_executor | تبويب Backtest + P&L (الافتراضي مقابل المنفذ) | صفقات افتراضية تُراقب دون إرسال أوامر حقيقية للوسيط. |

## risk

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 97 | `risk.risk_profiles` | **P0** | nexus_risk | Settings → المخاطرة (سياسات قابلة للتبديل) | ملفات سياسات المخاطر. |
| 98 | `risk.risk_limits` | **P0** | nexus_risk | Risk Monitor — كل حد بقيمته الحالية مقابل عتبته | تعريف حدود المخاطر المفصلة، بدلاً من حصرها في أعمدة ثابتة. |
| 99 | `risk.risk_snapshots` | **P0** | nexus_risk | Risk Monitor — يقرأ القيم من هنا بدل "غير مؤكد" | لقطات حالة المخاطر عبر الزمن. |
| 100 | `risk.risk_assessments` | **P1** | nexus_risk | Risk Monitor — تقييم كل نية قبل الموافقة | تقييم مخاطر كل نية تنفيذ. |
| 101 | `risk.risk_violations` | **P0** | nexus_risk | تبويب Risk — سجل التجاوزات المؤرخ | تسجيل تجاوزات الحدود. |
| 102 | `risk.circuit_breakers` | **P0** | nexus_risk | Risk Monitor → Circuit Breakers (تعريف القواطع) | تعريف قواطع الحماية. |
| 103 | `risk.circuit_breaker_events` | **P0** | nexus_risk | Risk Monitor → سجل التفعيل والرفع |  |
| 104 | `risk.kill_switch_events` | **P0** | nexus_risk | تبويب Risk — سجل KILL بالسبب والمدة | سجل تفعيل وإلغاء مفتاح إيقاف التداول الطارئ. |
| 105 | `risk.position_sizing_calculations` | **P1** | nexus_executor | Live Decision — كيف حُسب اللوت المقترح | تسجيل كيفية تحديد حجم الصفقة. |
| 106 | `risk.exposure_snapshots` | **P1** | nexus_risk | Risk Monitor — التعرض الإجمالي |  |
| 107 | `risk.correlation_risk_snapshots` | **P1** | nexus_risk | Risk Monitor → الترابط (يرتبط بحزمة الذهب) | مخاطر الترابط بين الأدوات المالية. |
| 108 | `risk.anti_tilt_events` | **P0** | nexus_risk | تبويب Risk — الإفراط/الانتقام بالأدلة | توثيق حالات السلوك التداولي غير المنضبط أو محاولات تجاوز السياسة. |
| 109 | `risk.risk_override_requests` | **P1** | nexus_risk | Risk Monitor — طلبات التجاوز (ليست موافقة تلقائية) | طلبات تجاوز سياسة المخاطر؛ وهي ليست موافقة تلقائية على التجاوز. |
| 110 | `risk.risk_decision_audit` | **P1** | nexus_risk | تبويب Risk — سجل غير قابل للتعديل لقرارات المحرك | سجل غير قابل للتعديل الصامت لكل قرار صادر عن محرك المخاطر. |

## features

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 111 | `features.feature_definitions` | **P1** | nexus_features | تبويب Models — قاموس الخصائص | قاموس جميع الخصائص والمؤشرات. |
| 112 | `features.feature_versions` | **P1** | nexus_features | تبويب Models — إصدارات التعريف | حفظ إصدارات تعريف الخصائص حتى لا تتغير نتائج النماذج القديمة بصمت. |
| 113 | `features.feature_parameters` | **P1** | nexus_features | تبويب Models — معلمات المؤشرات | المعلمات المستخدمة في حساب المؤشرات. |
| 114 | `features.feature_calculation_runs` | **P1** | nexus_features | تبويب Models — سجل كل حساب | تسجيل كل عملية حساب للخصائص. |
| 115 | `features.feature_values` | **P1** | nexus_features | غير مرئي — قيم الخصائص للنماذج | جدول القيم الناتجة عن الحساب. |
| 116 | `features.feature_matrices` | **P3** | nexus_ml | — | تعريف مجموعات الخصائص المستخدمة في النماذج. |
| 117 | `features.feature_matrix_members` | **P3** | nexus_ml | — |  |
| 118 | `features.indicator_definitions` | **P2** | nexus_features | تبويب Models — قاموس المؤشرات الفنية | قاموس مؤشرات التحليل الفني التي تُنفذ عبر MT5 أو Python. |
| 124 | `features.market_regimes` | **P1** | nexus_features | RegimeIndicator — قاموس الحالات بدل "Waiting…" | قاموس حالات السوق. |
| 125 | `features.market_regime_observations` | **P1** | nexus_features | RegimeIndicator — تاريخ حالة السوق |  |
| 126 | `features.feature_quality_results` | **P2** | nexus_features | — | نتائج التحقق من صحة الخصائص قبل تمريرها إلى النماذج. |

## ml

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 127 | `ml.model_families` | **P2** | nexus_ml | تبويب Models — عائلات النماذج الثلاث |  |
| 128 | `ml.models` | **P1** | nexus_ml | تبويب Models — سجل دائم بدل models_store على القرص |  |
| 129 | `ml.model_versions` | **P1** | nexus_ml | تبويب Models — كل إصدار ونتائجه |  |
| 130 | `ml.datasets` | **P2** | nexus_ml | — (توحيد مع datasets الموجود) | تعريف مجموعات بيانات التدريب والتقييم. |
| 131 | `ml.training_runs` | **P2** | nexus_ml | — (توحيد مع research_trials) |  |
| 132 | `ml.training_metrics` | **P2** | nexus_ml | — |  |
| 133 | `ml.model_predictions` | **P1** | nexus_ml | Live Decision — التنبؤات المرصودة بأفقها الزمني | جدول التنبؤات. كل تنبؤ له وقت إصدار وأفق زمني ونسخة نموذج محددة. |
| 134 | `ml.prediction_targets` | **P1** | nexus_ml | — (يقيس دقة التنبؤ لاحقاً) | تعريف ما يجب قياسه لاحقاً للحكم على دقة التنبؤ. |
| 135 | `ml.prediction_evaluations` | **P2** | nexus_ml | تبويب Models — دقة فعلية للتنبؤات |  |
| 136 | `ml.walk_forward_runs` | **P3** | nexus_ml | — |  |
| 137 | `ml.walk_forward_folds` | **P3** | nexus_ml | — |  |
| 138 | `ml.ensemble_definitions` | **P3** | nexus_ml | — | تعريف النماذج المجمعة. |
| 139 | `ml.ensemble_members` | **P3** | nexus_ml | — |  |
| 140 | `ml.ensemble_predictions` | **P3** | nexus_ml | — |  |
| 141 | `ml.anomaly_events` | **P3** | nexus_ml | — | نتائج Isolation Forest أو غيره من نماذج اكتشاف الشذوذ. |
| 142 | `ml.model_registry_events` | **P2** | nexus_ml | تبويب Models — دورة حياة النموذج | سجل انتقال النماذج بين مراحل دورة الحياة. |
| 143 | `ml.model_monitoring_metrics` | **P2** | nexus_ml | تبويب Models |  |
| 144 | `ml.model_drift_events` | **P2** | nexus_ml | تبويب Models — انحراف النموذج |  |
| 145 | `ml.model_retraining_jobs` | **P2** | nexus_ml | Autonomous ML Pipeline — سجل إعادة التدريب |  |
| 146 | `ml.model_promotion_reviews` | **P3** | nexus_ml | — | اعتماد النموذج قبل انتقاله إلى بيئة الإنتاج. |

## agents

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 147 | `agents.agent_definitions` | **P1** | nexus_agents | تبويب Agents — تعريف الوكلاء A0..A7 |  |
| 148 | `agents.agent_versions` | **P2** | nexus_agents | — |  |
| 149 | `agents.agent_sessions` | **P1** | nexus_agents | تبويب Agents — الجلسات | جلسة عمل الوكيل، وقد تشمل عدة تشغيلات ومهام. |
| 150 | `agents.agent_runs` | **P1** | nexus_agents | تبويب Agents — كل استدعاء LLM ونتيجته (يكمل agent_logs) | كل استدعاء فعلي للنموذج أو تنفيذ لوكيل. |
| 151 | `agents.agent_tasks` | **P2** | nexus_agents | — | المهام التي ينفذها الوكلاء. |
| 152 | `agents.agent_dependencies` | **X** | — | — (تسلسل ثابت بسيط) | علاقات الاعتماد بين المهام. |
| 153 | `agents.agent_handoffs` | **P3** | nexus_agents | — | تسجيل تسليم المهمة أو السياق من وكيل إلى آخر. |
| 154 | `agents.agent_messages` | **P2** | nexus_agents | تبويب Agents — الرسائل المنظمة | الرسائل المنظمة بين الوكلاء. |
| 155 | `agents.agent_approvals` | **P2** | nexus_agents | — (مع execution_approvals) |  |
| 156 | `agents.agent_guardrail_events` | **P2** | nexus_agents | — |  |
| 157 | `agents.agent_performance_snapshots` | **P2** | nexus_agents | تبويب Agents — أداء كل وكيل |  |

## memory

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 158 | `memory.memory_scopes` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG | تعريف نطاقات الذاكرة. |
| 159 | `memory.memories` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 160 | `memory.memory_items` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG | تجزئة الذاكرة إلى حقائق أو تفضيلات أو قواعد صغيرة. |
| 161 | `memory.memory_links` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG | ربط الذكريات ببعضها. |
| 162 | `memory.memory_versions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 163 | `memory.memory_retrieval_logs` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 164 | `memory.memory_feedback` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 165 | `memory.memory_consolidation_jobs` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |

## knowledge

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 166 | `knowledge.knowledge_collections` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 167 | `knowledge.documents` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 168 | `knowledge.document_versions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 169 | `knowledge.document_chunks` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG | تقسيم المستند إلى مقاطع للبحث الدلالي. |
| 170 | `knowledge.document_entities` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 171 | `knowledge.document_permissions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 172 | `knowledge.document_processing_jobs` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |

## retrieval

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 173 | `retrieval.embedding_models` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 174 | `retrieval.embeddings` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG | تخزين متجهات المستندات والمقاطع والذكريات. يمكن تنفيذ العمود المتجهي باستخدام pgvector. |
| 175 | `retrieval.search_queries` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 176 | `retrieval.retrieval_runs` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 177 | `retrieval.search_results` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 178 | `retrieval.reranking_results` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 179 | `retrieval.retrieval_feedback` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |

## tools

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 180 | `tools.tool_definitions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 181 | `tools.tool_versions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 182 | `tools.tool_permissions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 183 | `tools.tool_invocations` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 184 | `tools.tool_errors` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 185 | `tools.tool_approvals` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |

## prompts

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 186 | `prompts.prompt_definitions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 187 | `prompts.prompt_versions` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 188 | `prompts.prompt_experiments` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 189 | `prompts.prompt_assignments` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |
| 190 | `prompts.prompt_performance` | **P3** | nexus_agents | مؤجل — يُبنى مع أول توسعة حقيقية للذاكرة/RAG |  |

## reasoning

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 191 | `reasoning.hypotheses` | **P1** | nexus_agents | تبويب Journal — الفرضيات |  |
| 192 | `reasoning.evidence_items` | **P1** | nexus_agents | Live Decision + Journal — الأدلة |  |
| 193 | `reasoning.claims` | **P2** | nexus_agents | — |  |
| 194 | `reasoning.claim_evidence` | **P2** | nexus_agents | — |  |
| 195 | `reasoning.objections` | **P1** | nexus_agents | Live Decision — اعتراضات الوكلاء على القرار |  |
| 196 | `reasoning.conclusions` | **P1** | nexus_agents | — |  |
| 197 | `reasoning.decision_records` | **P0** | nexus_agents | Live Decision + Journal — سجل القرارات الرسمي | السجل الرسمي للقرارات التي تنتج من النقاش أو الحوكمة أو التحليل. |
| 198 | `reasoning.decision_approvals` | **P1** | nexus_agents | — (مع execution_approvals) |  |

## governance

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 199 | `governance.governance_councils` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 200 | `governance.council_members` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 201 | `governance.governance_sessions` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 202 | `governance.governance_agenda_items` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 203 | `governance.council_deliberations` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 204 | `governance.council_votes` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 205 | `governance.governance_policies` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 206 | `governance.governance_violations` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 207 | `governance.data_ownership` | **P3** | — | مؤجل — مجلس الحوكمة يفوق حاجة مالك واحد؛ decision_records يغطي الجوهر |  |
| 208 | `governance.data_lineage` | **P2** | nexus_data | — (توحيد مع جدول lineage الموجود) | تتبع منشأ البيانات وتحولاتها بين الطبقات والخدمات. |

## quality

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 209 | `quality.quality_rules` | **P1** | nexus_data | — (يكمل quality_runs الموجود) |  |
| 210 | `quality.quality_rule_versions` | **P2** | nexus_data | — |  |
| 211 | `quality.quality_test_runs` | **P1** | nexus_data | — |  |
| 212 | `quality.quality_test_results` | **P1** | nexus_data | — |  |
| 213 | `quality.quality_issues` | **P1** | nexus_data | System Diagnostic — مشاكل البيانات المفتوحة |  |
| 214 | `quality.data_certificates` | **P1** | nexus_data | System Diagnostic + preflight — شهادة صلاحية البيانات | هذا هو جدول شهادات صلاحية البيانات. |
| 215 | `quality.data_validation_profiles` | **P2** | nexus_data | — |  |
| 216 | `quality.duplicate_detection_runs` | **P3** | nexus_data | — |  |
| 217 | `quality.duplicate_records` | **P3** | nexus_data | — |  |
| 218 | `quality.data_reconciliation_runs` | **P3** | nexus_data | — | مقارنة البيانات المستلمة مع مصدرها أو مع طبقة أخرى. |

## evaluation

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 219 | `evaluation.evaluation_datasets` | **P3** | nexus_ml | — |  |
| 220 | `evaluation.test_cases` | **P3** | nexus_agents | — |  |
| 221 | `evaluation.evaluation_runs` | **P3** | nexus_agents | — |  |
| 222 | `evaluation.evaluation_results` | **P3** | nexus_agents | — |  |
| 223 | `evaluation.graders` | **P3** | nexus_agents | — |  |
| 224 | `evaluation.trace_records` | **P2** | nexus_agents | تبويب Agents — أثر تنفيذ الوكيل | تسجيل أثر تنفيذ الوكيل أو سلسلة الأدوات، مع الاحتفاظ بمدخلات ومخرجات منظمة ومراجعها. |
| 225 | `evaluation.regression_tests` | **P3** | nexus_agents | — |  |

## ops

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 226 | `ops.service_health_checks` | **P1** | nexus_monitor | System Diagnostic — تاريخ فحوص الصحة |  |
| 227 | `ops.service_metrics` | **P1** | nexus_monitor | — |  |
| 228 | `ops.system_events` | **P1** | nexus_monitor | System Console — أرشفة الأحداث بدل 30 سطراً عابرة |  |
| 229 | `ops.application_logs` | **P2** | nexus_monitor | — (سجلات ملفات حالياً؛ يُبنى عند الحاجة للبحث) |  |
| 235 | `ops.backup_jobs` | **P2** | nexus_monitor | — (يكمل النسخ المشفر الموجود BACKUP_PASSPHRASE) |  |
| 236 | `ops.recovery_tests` | **P3** | nexus_monitor | — |  |

## integration

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 237 | `integration.api_clients` | **X** | — | — (كل شيء داخلي 127.0.0.1) |  |
| 238 | `integration.api_requests` | **X** | — | — (نفس السبب) |  |
| 239 | `integration.webhook_endpoints` | **X** | — | — |  |
| 240 | `integration.webhook_deliveries` | **X** | — | — |  |
| 241 | `integration.external_connectors` | **P3** | nexus_data | — (عند تفعيل CCXT ENABLE_CCXT) |  |
| 242 | `integration.connector_sync_runs` | **P3** | nexus_data | — |  |

## analytics

| # | الجدول | القرار | الخدمة الكاتبة | الشاشة | الغرض |
|---|---|---|---|---|---|
| 243 | `analytics.performance_snapshots` | **P1** | nexus_data | نافذة P&L — لقطات أداء مؤرخة |  |
| 244 | `analytics.strategy_definitions` | **P1** | nexus_strategy | تبويب Strategies — قاموس الاستراتيجيات |  |
| 245 | `analytics.strategy_versions` | **P1** | nexus_strategy | تبويب Strategies |  |
| 246 | `analytics.backtest_runs` | **P1** | nexus_strategy | تبويب Backtest — سجل دائم لكل تشغيل |  |
| 247 | `analytics.backtest_trades` | **P1** | nexus_strategy | تبويب Backtest — صفقات كل تشغيل |  |
| 248 | `analytics.backtest_metrics` | **P1** | nexus_strategy | تبويب Backtest — المقاييس لكل تشغيل |  |
| 249 | `analytics.strategy_performance_by_session` | **P2** | nexus_strategy | تبويب Strategies — الأداء حسب الجلسة |  |
| 250 | `analytics.strategy_performance_by_regime` | **P2** | nexus_strategy | تبويب Strategies — الأداء حسب حالة السوق |  |
| 251 | `analytics.trade_journal_entries` | **P1** | nexus_data | تبويب Journal — دفتر يربط القرار بالتنفيذ بالنتيجة | دفتر التداول الذي يربط القرار والتحليل بالتنفيذ والنتيجة. |
