# أمر الوكيل — تدقيق وتنفيذ مباشر موثق خلال ساعة إجمالية

## 1) طبيعة هذا الملف

هذا الملف موجّه إلى **وكيل التنفيذ** وليس إلى منشئ التقرير. على الوكيل تنفيذ العمل داخل المشروع الهدف مع الحفاظ على المعمارية، وإخراج أدلة Git والبصمات والتغييرات الحقيقية. لا يعتبر أي عمل منجزًا بالوصف فقط.

## 2) نطاق التنفيذ

المشروع الهدف:

```text
C:\Nexus-Trading-System-MT5
```

المشروع المرجعي:

```text
C:\Users\rd66\Documents\Codex\2026-10-16\https-github-com-jlcbk-fx-trading\work\repo\fx-trading-system-main
```

وثيقة التحليل المرجعية:

```text
outputs\nexus-complete-agent-audit-ar.md
```

الهدف: دمج أقوى قدرات `fx-trading-system` في Nexus بصورة متوافقة مع خدماته الحالية، مع تطوير Data Hub واستيراد البيانات وجودتها وربط الأصول والاستراتيجيات والأخبار والواجهات.

## 3) القيد الزمني

المدة القصوى **60 دقيقة إجمالًا للمشروع وجميع الملفات**، وليست ساعة لكل ملف.

التقسيم الإلزامي:

- 0–5 دقائق: baseline وGit وملكية الملفات.
- 5–15 دقيقة: تدقيق سريع وتحديد أعلى تغييرات P0/P1.
- 15–50 دقيقة: تنفيذ التعديلات المباشرة المتاحة، بالتوازي وبنطاقات غير متعارضة.
- 50–60 دقيقة: توثيق Git والبصمات وقاعدة البيانات والواجهات، ثم إصدار التقرير.

إذا لم يكتمل التغيير خلال الساعة، يجب إيقافه وتسجيله `PARTIAL` أو `BLOCKED`. ممنوع تمديد الوقت أو الادعاء بأن كل الملفات اكتملت.

## 4) القيود الصارمة

- مسموح تعديل الشفرة والواجهات ومخطط قاعدة البيانات داخل المشروع الهدف.
- ممنوع تشغيل أي اختبار أو build أو lint أو compile أو notebook.
- ممنوع تشغيل أو إيقاف الخدمات.
- ممنوع الاتصال بوسيط أو MT5 أو تنفيذ تداول حي.
- ممنوع تعديل قاعدة بيانات تشغيلية غير محددة أو غير مملوكة للمشروع.
- قبل تعديل أي قاعدة بيانات يجب تحديد المسار الصريح، أخذ نسخة احتياطية، وحفظ بصمة النسخة.
- لا تستخدم `git reset --hard` أو `git checkout --` أو حذفًا واسعًا.
- لا تنشئ نسخة ثانية كاملة من `fx-trading-system-main` داخل Nexus.
- لا تغيّر Risk/Executor بحيث يسمح البحث بتجاوز الموافقات.
- لا تستخدم بيانات synthetic أو zero-placeholder كبيانات حقيقية.
- لا تعتبر وجود ملف أو class دليلًا على أن الميزة تعمل.
- لا تكتب `DONE` إلا مع diff وبصمات وأدلة قابلة للفحص.

## 5) تشغيل 15 وكيلًا كخلية نحل

شغّل الوكلاء بالتوازي، مع نطاق كتابة منفصل لكل وكيل. كل وكيل يقرأ التقرير المرجعي ويعيد نتيجة منظمة. لا يكرر وكيل عمل وكيل آخر.

| رقم | الوكيل | مهمته المباشرة | نطاق الملفات المقترح |
|---:|---|---|---|
| 1 | المنسق | baseline، توزيع المهام، منع التعارض، دمج الأدلة | Git و`project_audit` فقط |
| 2 | مصدر الميزات | جرد كل وحدات المصدر وتصنيف النقل/التكييف/المنع | `work\repo\...\src\fx_system` |
| 3 | حدود المعمارية | ربط Research مع Data/Features/ML/Agents/News/Risk/Executor | `services/*`, `shared/*` |
| 4 | الاستيراد التاريخي/الحي | Import jobs، backfill، providers، checkpoints، resume | `services/nexus_data` |
| 5 | جودة البيانات | schema، gaps، duplicates، OHLC، outliers، quarantine | data store/schema/quality |
| 6 | الأصول والعقود | symbol mapping، FX/XAU/BTC/indices، pip، contract، sessions | `shared/assets*`, `asset_specs` |
| 7 | الاستراتيجيات | العائلات الست، factors، DSL، labels، lifecycle | `services/nexus_ml`, `nexus_agents` |
| 8 | الإحصاء والتحقق | walk-forward، purge، embargo، FDR، DSR، PBO، SPA | research/validation |
| 9 | الأخبار والماكرو | vintages، CFTC، calendars، DST، blackout، available-at | `services/nexus_news` |
| 10 | التكاليف والمحفظة | bid/ask، spread، swap، commission، slippage، exposure | risk/portfolio/cost contracts |
| 11 | الأحداث وRedis | event schemas، streams، ACK، DLQ، reclaim، correlation | `shared/events.py`, `redis_client.py` |
| 12 | قاعدة البيانات | migrations، writer ownership، snapshots، retention، lineage | DuckDB/schema/migrations |
| 13 | API والواجهات | tabs، tables، filters، URL state، Import/Quality/Trace UI | `services/nexus_api`, `dashboard` |
| 14 | الأمان والتشغيل | auth، roles، secrets، SSRF، kill switch، audit، rollback | shared/services/monitor |
| 15 | المحكم | يراجع diff والأدلة ويصدر verdict نهائي | `project_audit` |

## 6) ترتيب التنفيذ المباشر

### P0 — يجب تنفيذه أولًا

1. عقود `provenance`, `available_at`, `vintage_id`, `dataset_id`, `run_id`.
2. Asset Master وربط raw symbol بالرمز القياسي وbroker symbol.
3. Staging/Quarantine قبل Canonical Data.
4. حدود Research → Proposal → Risk → Executor.
5. منع تسرب المستقبل ومنع synthetic/placeholder من التداول.
6. إصدار schema/version للـ events والـ API.

### P1 — ينفذ إذا بقي وقت

1. Import Quality/Correction tables وعدادات الاستيراد.
2. Research Run/Artifact/Validation/Promotion records.
3. News snapshot/vintage/blackout linkage.
4. Data Hub وImport Center وQuality tables.
5. Strategy catalog وValidation gates.

### P2 — يسجل كـ backlog إذا لم يتسع الوقت

1. تحسينات UX المتقدمة.
2. DSR/PBO/SPA الكاملة إذا لم تكن جاهزة.
3. calendar adapters الإضافية.
4. Dukascopy event-window commissioning الكامل.
5. advanced trace visualization.

## 7) قواعد تعديل الشفرة

- استخدم عقود Nexus الحالية ولا تنشئ event path موازيًا.
- حافظ على `nexus_risk` كمالك القرار النهائي.
- اجعل Research ينتج artifacts/proposals فقط، ولا يرسل إلى `stream:orders`.
- أضف الحقول الجديدة بطريقة backward-compatible مع `schema_version`.
- لا تكسر الواجهات الحالية؛ أضف endpoints أو DTOs versioned.
- لا تستخدم pandas/config objects داخل dashboard؛ استخدم API DTOs.
- افصل `current_vintage` عن `as_published_vintage`.
- افصل `research_only`, `exploratory`, `paper`, `candidate`, `live`.
- سجّل كل correction قبل/بعد وسببها وفاعلها.

## 8) قواعد تعديل قاعدة البيانات

قبل التعديل:

1. حدد المسار المطلق لقاعدة البيانات.
2. تحقق أنها قاعدة المشروع الهدف وليست قاعدة تشغيل خارج النطاق.
3. احفظ `db_before_sha256` ووقت النسخ وحجم الملف.
4. أنشئ migration version واضحًا وقابلًا للرجوع.
5. لا تحذف جداول أو أعمدة قائمة؛ استخدم إضافة متوافقة أو migration صريح.

الجداول ذات الأولوية:

```text
datasets
dataset_sources
dataset_partitions
import_jobs
import_errors
quarantine_rows
quality_runs
quality_checks
correction_actions
asset_lineage
research_runs
research_artifacts
validation_results
promotions
lineage_edges
trace_events
```

بعد التعديل يجب حفظ:

- migration id وملف migration.
- قائمة الجداول والأعمدة قبل وبعد.
- `db_after_sha256`.
- عدد الصفوف المتأثرة، إن وجد.
- تقرير يوضح هل تم تعديل schema فقط أم بيانات فعلية.

إذا تعذر تطبيق migration بأمان خلال الساعة، أنشئ migration موثقًا فقط، وسجله `NOT_APPLIED` مع السبب. لا تعدل قاعدة غير مؤكدة.

## 9) قواعد تعديل الواجهات

أضف أو اربط التبويبات التالية حسب العقود المتاحة:

1. Data Hub.
2. Import Center.
3. Data Quality.
4. Correction Queue.
5. Lineage.
6. Strategies.
7. Research Runs.
8. Validation.
9. News Context.
10. Promotion.

كل جدول يجب أن يدعم قدر الإمكان: filter، sort، pagination، export، empty state، error state، status، details panel. لا تعرض بيانات fabricated أو أصفارًا على أنها نجاح.

دليل الواجهة المطلوب:

- مسار الصفحة أو component path.
- API endpoint وDTO المستخدم.
- أسماء الحقول المعروضة.
- حالة loading/error/empty.
- diff واضح في ملفات TypeScript/React.
- لا تدّعِ تشغيل الواجهة أو نجاحها runtime دون تشغيل مسموح؛ اذكر `STATIC_EVIDENCE_ONLY`.

## 10) دليل Git والبصمات — إلزامي لكل ملف

قبل أي تعديل:

```text
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
```

أنشئ سجلًا لكل ملف سيُعدل:

```text
path
before_exists
before_sha256
before_size
before_git_status
```

بعد التعديل:

```text
git status --short
git diff --name-status
git diff --stat
git diff -- path/to/file
git rev-parse HEAD
```

ثم احسب لكل ملف:

```text
path
after_exists
after_sha256
after_size
changed = before_sha256 != after_sha256
diff_present
evidence_status
```

لا تعتمد على اسم الملف أو وقت التعديل كدليل. الدليل المقبول هو: `before hash + after hash + git diff + file path + reason`.

يُسمح بعمل commit محلي واحد بعد حفظ الأدلة إذا كان المستودع Git صالحًا:

```text
git add <only-approved-files>
git commit -m "feat: integrate research audit contracts"
git rev-parse HEAD
git show --stat --oneline HEAD
```

ممنوع push أو تعديل remote أو إخفاء ملفات غير staged. إذا لم يتم commit، يجب ذكر السبب بوضوح.

## 11) ملف الأدلة النهائي الذي يجب أن ينتجه الوكيل

أنشئ داخل المشروع الهدف، إذا كان ذلك مسموحًا في نطاق التنفيذ:

```text
project_audit/AGENT_EXECUTION_60MIN_REPORT.md
project_audit/AGENT_FILE_HASHES_60MIN.tsv
project_audit/AGENT_GIT_EVIDENCE_60MIN.txt
project_audit/AGENT_DB_EVIDENCE_60MIN.md
project_audit/AGENT_UI_EVIDENCE_60MIN.md
```

يجب أن يتضمن التقرير:

- وقت البداية والنهاية والمنطقة الزمنية.
- حالة كل وكيل من الـ15: completed/partial/blocked.
- commit/hash قبل وبعد.
- كل ملف أُضيف أو عُدل أو لم يُعدل.
- SHA-256 قبل وبعد لكل ملف.
- قاعدة البيانات: قبل/بعد، migration، backup hash، rows/schema أثر.
- الواجهات: components/routes/API DTOs المتغيرة.
- قائمة ما لم يُنفذ.
- عبارة صريحة: `NO TESTS RUN`.
- عبارة صريحة: `NO LIVE TRADING`.
- عبارة صريحة: `EVIDENCE-BASED STATUS ONLY`.

## 12) نموذج حالة الملف

```text
FILE: C:\Nexus-Trading-System-MT5\path\to\file
OWNER_AGENT: 13
ACTION: added | modified | unchanged | blocked
BEFORE_SHA256: <hash>
AFTER_SHA256: <hash>
GIT_DIFF: present | absent
DATABASE_EFFECT: none | schema | data
UI_EFFECT: none | route | component | DTO
STATUS: verified | partial | blocked
EVIDENCE: <report path and line/section>
```

## 13) الحكم النهائي المسموح

لا تستخدم `complete` أو `implemented` إلا إذا كانت البصمات وGit diff وأدلة DB/API/UI موجودة. استخدم:

- `VERIFIED`: تعديل حقيقي وله دليل كامل.
- `PARTIAL`: جزء عدّل، لكن النطاق لم يكتمل.
- `BLOCKED`: لم يمكن التعديل بأمان أو لم يتوفر دليل.
- `UNCHANGED`: لم يتغير الملف.
- `NOT_INSPECTED`: لم يصل إليه الوكيل قبل انتهاء الساعة.

العبارة النهائية الإلزامية:

```text
TOTAL TIMEBOX: 60 MINUTES FOR ALL FILES
DIRECT CODE/UI/SCHEMA CHANGES: ONLY THOSE LISTED WITH HASHES AND DIFFS
NO TESTS RUN
NO SERVICES STARTED
NO LIVE DATABASE UNVERIFIED
NO LIVE TRADING
NO CLAIM WITHOUT EVIDENCE
```
