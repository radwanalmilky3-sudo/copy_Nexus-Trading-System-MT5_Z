# دراسة تبني قاموس البيانات — NEXUS_Data_Dictionary_Reviewed.docx

> مراجعة موضوعية وتحديد الجداول/الحقول التي تقوّي النظام، وأين تُضاف في المشروع.
> المصدر: `NEXUS_Data_Dictionary_Reviewed.docx` (مسودة تصميم v1.0 — PostgreSQL 18، 22 نطاقاً، 212 جدولاً).
> التاريخ: 2026-11-06 · الحالة: دراسة للقرار — ليست تنفيذاً.

## 1) الحكم الموضوعي على الوثيقة

**نقاط القوة:**
- تغطية شاملة ومنضبطة التسمية (snake_case موحّد، UUID PKs، TIMESTAMPTZ، JSONB للميتاداتا).
- تفصل **النية عن التنفيذ** (execution_intents قبل الأوامر) — أعمق تحسين معماري في الوثيقة.
- كل جدول "خطير" مقرون بسجل تدقيق (audit) — يتطابق مع فلسفة النظام الحالية (الأدلة قبل الافتراض).
- قاموس ref.* لتعريفات MT5 الرسمية يمنع التفسير الحر للـ enums.

**نقاط الضعف / التحفظات:**
- كُتبت لـ **PostgreSQL 18** بينما النظام يعمل على **DuckDB أحادي الكاتب + Redis Streams**. تبنّي الـ 212 جدولاً كلها الآن = إعادة بناء المنصة، لا تقوية لها.
- أقسام كاملة (memory/knowledge/retrieval/prompts/tools ≈ 33 جدولاً) تخدم منظومة RAG/وكلاء ضخمة **لم تُبنَ بعد** — تبنيّها الآن يخلق جداول فارغة بلا كاتب.
- governance/council (10 جداول) تفوق حاجة مالك واحد حالياً؛ جوهرها موجود في reasoning.decision_records.
- لا يوجد في الوثيقة خطة ترحيل (migration plan) ولا تعيين نطاق ↔ خدمة.

**القرار الموصى به:** تبنّي الوثيقة **كمرجع تصميم** يتم استيعابه تدريجياً كجداول DuckDB (نفس المحرك الحالي، نفس نمط `services/nexus_data/migrations/*_00N.sql` + `duckdb_store.py`)، مع إبقاء PostgreSQL خياراً مستقبلياً فقط إذا تعدد الكتّاب عبر العمليات.

## 2) أولويات التبني — ما يقوّي النظام فعلاً

### P0 — يسد فجوات حيّة في النظام اليوم (الأساس: 4 جداول + 4)
| الجدول من الوثيقة | الفجوة الحالية الفعلية | أين يُضاف في المشروع |
|---|---|---|
| `execution.execution_intents` | قرار الوكيل ينتقل عبر Redis إلى المنفذ دون سجل دائم للنية (SL/TP/الحجم/المبرر) قبل التنفيذ | جدول `execution_intents` في DuckDB + كتابة من `services/nexus_executor` لحظة استلام القرار، وقبل إرسال أمر MT5 |
| `execution.execution_approvals` | موافقات المخاطر (`NEXUS_RISK_APPROVAL_SECRET`) تُقرر وتُفقد — لا سجل لمن وافق/رفض ومتى ولماذا | جدول `execution_approvals` + كتابة من `services/nexus_risk` في مسار الموافقة الحالي |
| `risk.risk_limits` | الحدود موزّعة على إعدادات نصية (max trades/day, spread…) دون مخزن موحّد قابل للنسخ والمراجعة | جدول `risk_limits` (limit_code/scope/metric/operator/threshold/severity/enforcement) — يغذّي RiskMonitor بالحدود المعروضة بدل "غير مؤكد" |
| `risk.risk_violations` + `risk.risk_snapshots` | RiskMonitor يعرض "UNKNOWN/offline" لأنه لا يوجد مخزن قياسات تُقرأ منه | جدولا `risk_snapshots`/`risk_violations` يكتبهما `services/nexus_risk` دورياً ويقرأ منهما الداشبورد |
| `risk.circuit_breaker_events` + `risk.kill_switch_events` | القواطع تعمل لكن تاريخها غير موثّق (لا مراجعة لاحقة) | جدولان في DuckDB يكتبهما nexus_risk ونexus_executor عند أي تفعيل |

**لماذا P0:** كل بند يعالج عرضاً حياً تظهره الواجهة اليوم بحالة غير موثوقة ("تعذر تحديث حد الصفقات اليومية… لا يُعرض الصفر كحالة موثوقة").

### P1 — الجودة والأمانة العلمية (الأسبوع التالي)
| الجدول | القيمة | الموضع |
|---|---|---|
| `market.market_data_gaps` + `market_data_quality_snapshots` | يكمل `quality_runs`/`quarantine` الموجودة: فجوات التغذية تصبح مرئية بدل اكتشافها في preflight فقط | `services/nexus_data/duckdb_store.py` + مؤشر في الداشبورد |
| `reasoning.decision_records` + `objections` + `evidence_items` | مبررات A7 تُعرض حالياً كنص عابر؛ تصبح سجلاً مؤسسياً قابلاً للمراجعة | يكتبه `services/nexus_agents` عند كل تقييم؛ يقرؤه LiveDecisionPanel و"الأدلة والسجل" |
| `execution.shadow_trades` | مقارنة "ما كان سيحدث" مقابل التنفيذ الفعلي — مثالية لوضع PAPER وقياس جودة الإشارات قبل أي LIVE | `services/nexus_executor` (وضع paper يسجل كل إشارة كظل) |
| `quality.*` (شهادات البيانات) | يرفع preflight من "PASS/FAIL" إلى شهادة موثقة بفترة صلاحية | يتكامل مع فحوص preflight في `run.py` |

### P2 — استكمال الوسيط والحسابات (نصفه موجود)
- الموجود فعلاً ويُكتفى منه: `broker_profiles`/`broker_accounts`/`broker_account_settings`/`broker_account_events` + الأصول والجلسات (نُفّذ هذا الأسبوع).
- المفيد إضافته لاحقاً: `broker.mt5_connection_events` (توثيق كل اتصال/فصل بطابع زمني — يغذي تبويب "الاتصال" بتاريخ حقيقي) و`broker.instruments`/`broker_symbols` (كاش ثابت لرموز الوسيط بدل جلب 2060 رمزاً كل مرة).

### مؤجَّل — لا تبناه الآن (مع السبب)
- `memory/knowledge/retrieval/tools/prompts` (33 جدولاً): لا يوجد بعد سوى وكلاء session-based؛ تُبنى عند أول توسعة حقيقية للذاكرة طويلة الأمد.
- `governance.*` (مجلس البيانات): استبدلها عملياً بـ`reasoning.decision_records` + سجل الأحداث الموجود.
- `analytics.*` و`ops.*`: النظام يعرض مباشرة من الخدمات؛ تُبنى عند أول حاجة لتقارير تاريخية.
- `evaluation.*`: يُستبدل مؤقتاً بمقاييس ML الموجودة (models_store + TradeMemory).

## 3) خطة الإدراج التقنية (نمط موحّد)

1. **الترحيلات:** ملفات `services/nexus_data/migrations/dict_<domain>_00N.sql` بنفس نمط `broker_settings_001.sql`، تُنشأ جداول DuckDB عند الإقلاع (نفس نقطة `duckdb.tables_ready`).
2. **الكاتب الواحد:** كل جدول يملكهervice واحد فقط (executor=execution، risk=risk، data=market/quality، agents=reasoning) — احترام قاعدة `_open_primary_connection`.
3. **التكامل مع preflight:** أي جدول P0 يُضاف لفحوص preflight (وجود الجدول = PASS).
4. **الواجهة:** RiskMonitor وLiveDecisionPanel يقرؤون الجداول الجديدة عبر nexus-api بدل الحالة العابرة.
5. **ترتيب التنفيذ المقترح:** دفعة P0 (جداول + كتابة + قراءة داشبورد) → ثم P1 جدولاً جدولاً مع اختبار لكل دفعة، وكل دفعة commit+push فوري.

## 4) مخاطر يجب حسمها قبل التنفيذ
- **لا PostgreSQL الآن:** إدخال قاعدة ثانية يعني كاتباً متزامنين لمنطق واحد — ضد قاعدة الكاتب الأحادي الموثقة.
- **لا جداول بلا كاتب:** يُمنع إنشاء أي جدول P1/P2 قبل أن يكون الكود الذي يكتبه جاهزاً في نفس الدفعة.
- **UUID مقابل الأنواع الحالية:** DuckDB يدعم UUID — يُعتمد كما في الوثيقة لسهولة الترحيل مستقبلاً.
