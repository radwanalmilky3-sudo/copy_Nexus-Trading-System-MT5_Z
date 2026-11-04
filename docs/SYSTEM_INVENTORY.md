# SYSTEM INVENTORY — NEXUS TRADER MT5

| البند | القيمة |
|---|---|
| الوثيقة | SYSTEM_INVENTORY.md (وثيقة 3/16 ضمن برنامج M.2) |
| التاريخ | 2026-11-04 (UTC) — مرجع الأدلة: SYSTEM_ARCHITECTURE_DISCOVERY_REPORT.md §2–§9 |
| المنهجية | جرد من الشيفرة + العمليات الجارية، مع عزل أي افتراض غير مدعوم بدليل |
| نطاق | Paper Trading فقط |

---

## 1. الجرد الرقمي الإجمالي

| العنصر | العدد | الدليل |
|---|---|---|
| خدمات حية (uvicorn/FastAPI) | 9 | `ss -ltnp` + `/health` لكل منفذ 9000–9008 |
| حزم برمجية في `services/` | 10 | 9 بـ `main.py` + 1 مكتبة (`nexus_strategy`) |
| أسطر بايثون في الخدمات | 31,217 LOC | `cat services/*/*.py \| wc -l` (التوزيع أدناه) |
| وحدات `shared/` | 29 ملفًا | `ls shared/*.py` |
| صفحات الواجهة (مسارات HTTP) | 19 | 6 عليا + 12 تبويب `/nexus/*` + `/api/health` — كلها 200 |
| ملفات مصدر الواجهة | 111 | `dashboard/src/app/**` + `dashboard/src/components/*/*.tsx` |
| جداول DuckDB | 62 | `information_schema.tables` |
| مفاتيح Redis | 137 (db0) | `DBSIZE` / `INFO keyspace` |
| مفاتيح عقد الإعدادات | 37 | `shared/config_contract.py` (سرد §5) |
| سكربتات مستوى الجذر | 8 | `run.py` + 7 مساعدة/تشخيصية (§6) |
| مكوّنات غير مستخدمة | 1 | `fx-trading-system-main/` (§7) |

---

## 2. جرد الخدمات (التفصيل بالملفات والأحجام)

| الخدمة | ملفات .py | LOC | دور موثق (من الشيفرة والأنابيب) | نقاط صحة |
|---|---|---|---|---|
| nexus-data (9001) | 20 | 6,257 | استيعاب البيانات، OHLCV، جودة/إصلاح تلقائي (دورة 60s)، تقويم اقتصادي | `/health` 200 degraded (mt5=false متوقع) |
| nexus-ml (9003) | 13 | 6,193 | تدريب/تقييم نماذج، تنبؤات، ensemble | `/health` 200 healthy |
| nexus-risk (9006) | 6 | 4,643 | بوابة مخاطر (day_start_balance، equity_peak، open_risk)، قرارات `stream:risk:decision` | `/health` 200 healthy |
| nexus-features (9002) | 13 | 3,652 | مؤشرات فنية/أساسية، cross-asset، `stream:features` | `/health` 200 healthy |
| nexus-executor (9007) | 9 | 3,571 | تنفيذ Paper، أوامر EA (`ea_commands`)، جسر MT5 | `/health` 200 healthy؛ `real_broker_execution_enabled=false` (TC-MT-04 سابقًا) |
| nexus-agents (9004) | 9 | 2,402 | 13 عامل A0–A12، أحكام LLM (`stream:agent:verdict`)، fail-closed | `/health` 200/503 flap (Z.ai خارجي) |
| nexus-news (9005) | 10 | 1,907 | جلب أخبار/تقويم، ticker، `stream:news` | `/health` 200 healthy |
| nexus-monitor (9008) | 5 | 1,216 | مقاييس، تنبيهات، Telegram (داخلي)، metrics exporter (داخلي) | `/health` 200 healthy |
| nexus-api (9000) | 7 | 871 | بوابة REST/WS للواجهة، auth/JWT | `/health` 200 healthy |
| **nexus_strategy (مكتبة)** | 6 | 574 | كتالوج استراتيجيات، anti-leakage — بلا `main.py`، لا منفذ | — |
| **المجموع** | **108** | **31,217** | | |

## 3. جرد الواجهة (dashboard — Next.js 14.2.5)

| المنطقة | المكونات |
|---|---|
| مسارات عليا | `/` (→/nexus)، `/nexus`، `/analytics`، `/login`، `/progress-state`، `/history` (→/nexus/history)، `/settings` (→/nexus/settings) |
| تبويبات `/nexus/*` (12) | ea-bridge، strategies، research-lab، ml-models، models، model-comparison، deep-learning، reinforcement-learning، progress، audit-progress، history، settings |
| مجموعات `src/components/` (10) | audit، fundamental، layout، progress، research-lab، settings، shared، trade-controls، ui، windows |
| مسار API | `/api/health` فقط |
| تشغيل | next-server PID 9306 @ `*:3100`؛ معاينة خارجية عبر مُمرِّر 3000→3100 (خارج المستودع) |
| متغيرات | `NEXT_PUBLIC_API_URL`، `NEXT_PUBLIC_WS_URL`، `NEXT_PUBLIC_WS_GATEWAY_URL` — يضبطها `run.py` إلى 9000 |

## 4. جرد مخازن البيانات

### 4.1 DuckDB — `data/nexus.duckdb` (36.4MB + WAL 2.6MB) — 62 جدولًا

| المجموعة | الجداول (بأعداد الصفوف الحالية) |
|---|---|
| هوية/دخول | app_users 53، app_roles 7، app_role_permissions 36، app_user_roles 53، api_tokens 5، user_audit_log 56 |
| أساسيات/أحداث | event_asset_impacts 2088، event_expectations 48، central_bank_events 3، geopolitical_events 0، fund_events 135، fund_sources 25 |
| تنبؤ/شرح | prediction_reasoning_steps 783، fundamental_explanations 261، fundamental_fusion_results 261، gold_impact_predictions 261، fundamental_factor_scores 1305، asset_factor_profiles 67 |
| معرفة | fundamental_knowledge_sources 1، fundamental_knowledge_claims 5، research_artifacts 0، lineage 0 |
| بيانات سوق | ohlcv 0، ticks 0، market_series_observations 0، data_vintages 50، macro_releases 50، economic_indicator_catalog 37، economic_indicator_observations 0 |
| جودة/مصادر | source_fetch_runs 187، source_health_history 187، quality_runs 0، quarantine 0، import_jobs 0، datasets 0، ohlcv_manifests 0، ohlcv_backfill_runs 0 |
| تنفيذ/وساطة | trades 0، positions 0، ea_commands 0، broker_accounts 0، broker_profiles 0، broker_account_settings 0، broker_account_events 0 |
| أخرى | agent_logs 0، alert_delivery_log 0، news_* 0/0/0/2، flow_observations 0، asset_event_outcomes 0، asset_registry 2، fundamental_* إدارية 0، local_ai_analysis_runs 0، user_notification_preferences 0، user_ticker_acknowledgements 0، model_evaluations 0، fundamental_training_features 0 |

### 4.2 Redis — 137 مفتاحًا
التفصيل الكامل للعائلات والأطوال في وثيقة الاكتشاف §5. ملاحظات الجرد:
- نبضات 21 (8 خدمات + 13 عاملًا) — صيغة JSON موحدة `service_name/status/last_heartbeat`.
- `nexus:system:auto_trade=false` — قيد Paper موثق.
- **بلا ثبات** (`--save "" --appendonly no`) — تصميم مقصود، المفاتيح قابلة لإعادة البناء.

## 5. عقد الإعدادات — 37 مفتاحًا (`shared/config_contract.py`)

| المجموعة | المفاتيح |
|---|---|
| اتصال | `REDIS_URL`, `PORT`, `IBKR_PORT`, `DEFAULT_BROKER`/`NEXUS_DEFAULT_BROKER` |
| وضع التداول | `NEXUS_TRADING_MODE`, `NEXUS_TRADING_MODE_TYPE`, `NEXUS_SETTINGS__AUTO_TRADE_ENABLED` |
| أسرار (لا تُطبع قيمها) | `NEXUS_INTERNAL_API_SECRET`, `NEXUS_RISK_APPROVAL_SECRET` |
| LLM | `NEXUS_LOCAL_LLM_URL`, `MLFLOW_TRACKING_URI` |
| مخاطر/استراتيجية | `NEXUS_RISK_PER_TRADE`, `NEXUS_MIN_VERDICT_CONVICTION`, `NEXUS_CONFLICT_LOCK_CONVICTION`, `NEXUS_ACTIVE_SIGNAL_TTL`, `STRATEGY_MIN_TRADES/WIN_RATE/PROFIT_FACTOR/MAX_DD_PCT` |
| نوافذ حجب أخبار | `NEXUS_HIGH_IMPACT_BLACKOUT_BEFORE/AFTER_MIN`, `NEXUS_MEDIUM_IMPACT_BLACKOUT_BEFORE/AFTER_MIN` |
| بحث | `NEXUS_RESEARCH_BATCH`, `NEXUS_RESEARCH_INTERVAL_SEC`, `NEXUS_OPERATIONAL_TF` |
| مصادر خارجية | `FED_RSS_URL`, `TREASURY_DATA_ENDPOINT`, `IMF_DATA_ENDPOINT`, `CFTC_COT_ENDPOINT`, `CENTRAL_BANK_GOLD_ENDPOINT`, `GOLD_ETF_DATA_ENDPOINT`, `MARKET_FLOW_DATA_ENDPOINT` |
| بيئة | `NEXUS_ENV`, `NEXUS_CONFIG_CONTRACT` |

> ملف `.env` موجود فعليًا. **ممنوع طباعة محتواه** وفق الخطوط الحمراء M.2؛ التحقق من القيم يُجرى عبر فحوصات سلوكية فقط.

## 6. سكربتات مستوى الجذر

| السكربت | الدور | ضمن التشغيل التلقائي؟ |
|---|---|---|
| `run.py` | المنسِّق الرسمي (سجل 9 خدمات + dashboard + ترتيب إقلاع) | نعم — نقطة الدخول المعتمدة |
| `start_all.py` | مشغل قديم/بديل | لا (يُوثَّق كـ legacy) |
| `bootstrap_ensemble.py` | تهيئة يدوية للـ ensemble | لا |
| `_check_db.py` | فحص DB يدوي | لا |
| `preflight.py` | فحص ما قبل التشغيل | لا (يدوي) |
| `diagnose_pnl.py`, `mt5_diagnose.py`, `mt5_sym_check.py` | تشخيص MT5/PnL | لا |

سكربتات بنية تحتية خارج المستودع: `scripts/nexus_heal.sh` (شفاء ذاتي: redis/forwarder/stack)، `scripts/port3000_forward.py` (مُمرِّر 3000→3100).

## 7. مكونات غير مستخدمة — `fx-trading-system-main/`

| الخانة | القيمة |
|---|---|
| النوع | مجلد مشروع مستقل (pyproject.toml, configs, docs, examples, outputs) |
| دليل عدم الاستخدام | لا استيراد له في أي من الخدمات التسع ولا في `run.py`؛ لا عملية جارية تخصه؛ لا منفذ |
| القرار | **UNUSED — يُعلَّم فقط**. لا يُحذف ولا يُعدَّل وفق الخطوط الحمراء (ممنوع حذف وظائف/إعادة بناء) |
| الإجراء المطلوب لاحقًا | إدراجه في MASTER_QA كقرار أرشفة معلّق على قرار المالك |

## 8. البنود UNKNOWN / قيود الجرد

| البند | الحالة |
|---|---|
| مطابقة `DB_SCHEMA.md` الوثائقية مع الفعلي عمودًا-بعمود | NOT TESTED — في خطوة DATABASE |
| تفصيل ملفات `fx-trading-system-main` الداخلية | PARTIAL — مُصنَّف unused، التفصيل غير ضروري للقرار |
| قيم `.env` الفعلية | مقصودة السرية — تُختبر سلوكيًا فقط |
| ثبات LLM الخارجي على مدى ساعات | NOT VERIFIED — مراقبة مستمرة |

> نهاية الوثيقة 3/16 — التالية: DATA_FLOW_MAP.md (4/16).
