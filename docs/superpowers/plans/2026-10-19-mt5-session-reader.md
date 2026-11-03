# MT5 Session Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ربط دليل جلسات الوسيط واستثناءاته بفحص الشموع واستكمالها، دون تداول أو تصنيف مطمئن بلا دليل.

**Architecture:** مؤشر MQL5 يصدّر ملفًا محليًا؛ خدمة البيانات وحدها تتحقق منه وتحفظ نسخه. مصنّف نقي واحد يغذي الشهادة ومخطط الإصلاح، مع احتساب بيانات مسارات MT5 المجمعة. لا استبدال لمحرك جلسات الاستراتيجية الحالي.

**Tech Stack:** MQL5 indicator, Python 3.11/Pydantic v2/zoneinfo, owner-locked DuckDB, FastAPI, Next.js/TypeScript, pytest, Node tests.

**Spec:** `docs/superpowers/specs/2026-10-19-mt5-session-reader-design.md` (معتمد).

## Global Constraints

- دورة الجودة الحالية: 60 ثانية؛ تصدير القارئ: كل خمس دقائق.
- حد الملف 1 MiB؛ صلاحية اللقطة التشغيلية 24 ساعة كحد أقصى.
- لا OrderSend أو CTrade أو DLL أو WebRequest أو كلمات مرور داخل المخرجات.
- لا إعادة تشغيل للمنصة ولا إرفاق/استبدال Expert موجود ولا تغيير صلاحيات الحساب.
- القارئ لا يكتب DuckDB؛ الكتابة والاستيراد تحت قفل مالك البيانات.
- لا تُسند صلاحية تاريخية قبل وقت الالتقاط دون دليل رسمي يغطي تلك الفترة.
- جلسات الأسعار، لا جلسات التداول وحدها، هي مرجع توقع الشموع.
- لا تغيير لـ `shared/sessions.py` أو `config/sessions.yaml` بوصفهما تقويم وسيط.
- لا أسعار اصطناعية ولا إزالة للتحذير عند غياب الدليل أو انتهاء صلاحيته.
- الحفاظ على تغييرات المستخدم الحالية؛ لا stage شامل أو حذف أصول أو استعادة قاعدة.

## Review Focus

1. فرق ساعة مرصود حاليًا قد يسيء تصنيف تاريخ سابق: رفض الاستدلال الرجعي (Task 3).
2. انقطاع المنصة قد ينتج جدولًا فارغًا: لا يُفسر كإغلاق سوق (Tasks 1–3).
3. فجوة backfill قد يغطيها poll: مقارنة السلسلة المجمعة مع ربط بصمتها بالشهادة (Task 4).
4. ملف جديد قد يحل محل ملف أثناء القراءة: قراءة محدودة والتحقق من اكتمال النسخة؛ إبقاء آخر دليل محفوظ دون الادعاء بأنه حديث (Task 2).
5. جلسة أسعار تتقاطع جزئيًا مع شمعة: لا تصنيف كامل الشمعة كإغلاق (Task 3).

## File Structure

- `mql5/Indicators/NexusSessionReader.mq5`: تصدير فقط.
- `services/nexus_data/quality/session_contracts.py`: نماذج الملف والسياسات والاستثناءات.
- `services/nexus_data/quality/session_store.py`: استيراد محدود وحفظ نسخ الأدلة وحالتها.
- `services/nexus_data/quality/session_calendar.py`: التصنيف النقي وحساب بصمة الاعتماد.
- `services/nexus_data/migrations/market_sessions_001.sql`: جداول أدلة إضافية، دون تعديل أسعار.
- `config/broker_calendar.example.json`: مثال معطّل بلا عطلات أو منطقة زمنية معتمدة.
- تعديل `quality/automation.py`, `quality/repair.py`, `quality/stored_audit.py`,
  `research_reader.py`, `main.py`: إدراج التقويم عبر نقاط محددة.
- تعديل واجهة المختبر `types.ts`, `adapters.ts`, `ResearchLabTab.tsx`: عرض الأدلة والحالة.
- `scripts/check_session_reader.py`, `docs/MT5_SESSION_READER.md`: تحقق وتشغيل آمن.

## Task 1: عقد الملف ومؤشر التصدير

**Files:** Create `session_contracts.py`, `mql5/Indicators/NexusSessionReader.mq5`; Test `tests/test_data/test_session_contracts.py`; fixtures تحت `tests/fixtures/mt5_sessions/`.

**Interfaces:**
- `parse_session_export(raw: bytes, *, now: datetime) -> SessionExport`.
- `SessionExport`: `schema_version=1`, `server`, `company`, `captured_at_utc`,
  `connected`, `observed_server_offset_seconds`, `symbols: list[SymbolSessions]`.
- `SymbolSessions`: `broker_symbol`, `days: list[DaySessions]` (الأيام 0–6، الأحد=0).
- `DaySessions`: `day`, `quote_status`, `trade_status`، وكل حالة من
  `ok|no_sessions|error|truncated`، و`quote_error`, `trade_error`، وقوائم
  `quote_sessions`, `trade_sessions` بعناصر `start_seconds`, `end_seconds`.
- حد 32 رمزًا و32 جلسة لكل نوع/يوم؛ أي تجاوز يُعلّم truncated ولا يثبت إغلاقًا.

- [ ] اكتب اختبارات فشل بأسماء `test_rejects_oversize_and_nonfinite_json`,
  `test_requires_seven_unique_days`, `test_failed_or_truncated_day_is_not_closed`,
  `test_preserves_distinct_quote_and_trade_windows`. استخدم حدود 1,048,576 بايت،
  سبعة أيام، 32 جلسة، ورفض حقول مجهولة وأنواع غير صارمة.
- [ ] شغّل `.venv/Scripts/python.exe -m pytest tests/test_data/test_session_contracts.py -q`؛ يجب أن تفشل أولًا لغياب السلوك.
- [ ] نفّذ العقد: UTC واعٍ، نصوص الخادم/الشركة/الرمز بطول 1–128، لا NaN أو
  مفاتيح JSON مكررة؛ بداية الجلسة ضمن 0–86399 ونهاية ضمن 0–86400.
  التساوي الغامض بين البداية والنهاية لا يعني 24 ساعة؛ حالة غير مؤكدة.
- [ ] نفّذ المؤشر بدوال `OnInit`, `OnTimer`, `OnCalculate`, `OnDeinit`؛
  المدخلات `SymbolsCsv`, `ExportEverySeconds=300`, `OutputFileName` باسم ملف
  ثابت دون مسار. لا مسح شامل للرموز أو تغيير اختيار رموز المنصة؛ الرمز غير
  المتاح يسجل خطأ. تصدير UTF-8 JSON إلى FILE_COMMON بملف مؤقت ثم FileMove،
  مع معالجة النصوص والهروب وإغلاق الملف قبل الاستبدال وفشل الاستبدال بأمان.
- [ ] اختبر العقد على fixtures تمثل خرج المؤشر، وشغّل المترجم إن توفر.
  تحقق أن كل أيام/أنواع الجلسات مفصولة وأن فشل API لا ينتج no_sessions.
  مرور اختبارات Python ليس دليلًا على تجميع المؤشر أو صحة جلسته الحية.
- [ ] راجع فرق هذه المهمة فقط؛ عند طلب commit استخدم مساراتها المحددة فقط.

## Task 2: استيراد الدليل وحفظ الحالة تحت مالك البيانات

**Files:** Create `session_store.py`, `migrations/market_sessions_001.sql`,
`config/broker_calendar.example.json`; Modify `main.py` configuration; Test `tests/test_data/test_session_store.py`.

**Interfaces:**
- `load_calendar_policy(path: Path | None) -> CalendarPolicy` في `session_contracts.py`.
- `CalendarPolicy`: `expected_server`, `symbol_map` (logical→broker),
  `clock_evidence`، و`exceptions`. Clock evidence له معرف ومصدر وتاريخ نشر
  وفترة UTC معتمدة وIANA zone أو فترات offset موثقة. Exception له
  `evidence_id`, `source_uri`, `published_at`, `server`, `broker_symbols`,
  `effective_from`, `effective_to`, `kind=closed|modified`, `quote_windows_utc`.
  لا حقل boolean يمنح ملفًا غير موثوق اعتمادًا ذاتيًا؛ الاعتماد من سياسة
  محلية يراجعها المشغّل ومصدرها المسجّل، وليس من ملف القارئ.
- `SessionEvidenceStore(store, export_path: Path | None, policy: CalendarPolicy)`.
- `await refresh(now: datetime) -> CalendarStatus`; `await context(symbol: str, now: datetime) -> CalendarContext`.
- الحالة: `not_configured|unavailable|ready|stale|identity_mismatch|clock_unverified|invalid|conflict`؛
  معها `snapshot_id`, `content_hash`, `captured_at`, `imported_at`, `expires_at`, `reason`.
- `CalendarContext` سجل غير قابل للتعديل بحقوق `export: SessionExport | None`,
  `policy: CalendarPolicy`, `status: CalendarStatus`؛ و`CalendarStatus` نموذج
  يحمل `state` وحقول الحالة المذكورة، بأوقات واعية أو None عند عدم التوفر.

- [ ] اكتب الاختبارات: تكرار المحتوى لا يكرر الحفظ؛ اختلاف الخادم/الرمز يرفض؛
  الملف الجزئي والتبديل أثناء القراءة لا ينشئان لقطة؛ لقطة >24 ساعة stale؛
  ملف مفقود بعد لقطة ناجحة unavailable وليس ready؛ صفر إعدادات not_configured.
- [ ] شغّل ملف الاختبارات وتحقق من الفشل قبل التنفيذ.
- [ ] أنشئ جدول `market_session_snapshots` append-only: ID، SHA-256، JSON
  الأصلي الصحيح، server، captured/imported/expires، status/reason. استخدم
  `_execute_locked` ومعاملة إدراج واحدة؛ لا اتصال DuckDB إضافي. ضع بصمة
  المحتوى ومعرف الاستثناءات في السياق، ولا تكتب إعدادات افتراضية في `.env`.
- [ ] عرّف إعدادين اختياريين: `NEXUS_MT5_SESSION_EXPORT_PATH` و
  `NEXUS_BROKER_CALENDAR_POLICY_PATH`. اقرأ فقط المسار المحلي المحدد، لا مسارًا
  من payload، وبحد 1 MiB+1 قبل JSON. ارفض تاريخ التقاط يزيد عن الآن بـ60 ثانية.
- [ ] شغّل الاختبارات، وتأكد أن الحالة غير الجاهزة لا تسرب آخر دليل كدليل حديث.
- [ ] راجع فرق المهمة فقط قبل أي commit اختياري.

## Task 3: مصنف نقي للجلسات والاستثناءات

**Files:** Create `session_calendar.py`; Test `tests/test_data/test_session_calendar.py`.

**Interfaces:**
- `classify_interval(context: CalendarContext, *, start: datetime, end: datetime) -> IntervalClassification`.
- النتيجة `kind=confirmed_closed|expected_quote|unknown`، مع `reason`,
  `snapshot_id`, `calendar_hash`, `exception_ids`. الفترة `[start,end)`.
- `calendar_dependency_hash(context: CalendarContext) -> str` يغطي نسخة
  الجدول والسياسة ودليل الساعة والاستثناءات وفترة الصلاحية والحالة؛ لا يعتمد
  على وقت polling وحده لخلق شهادة جديدة كل دقيقة.

- [ ] اكتب حالات حرفية: نافذة أسعار الاثنين 09:00–10:00 UTC تعطي expected_quote
  للفترة 09:55–10:05، لا confirmed_closed؛ و10:00–10:05 مغلقة فقط مع تغطية
  كاملة موثقة. جلسة تداول مغلقة وأسعار مفتوحة تعطي expected_quote.
- [ ] أضف اختبارات منتصف الليل، جلسات متعددة، استثناء إغلاق، جلسة معدّلة،
  استثناءات متعارضة، مصدر خطأ، time zone غير معتمد، تاريخ قبل التقاط اللقطة،
  DST له تحويل ملتبس/غير موجود. النتيجة unknown لكل حالة غامضة، لا إغلاق.
- [ ] شغّل الاختبارات أولًا؛ ثم نفّذ تقاطع/اتحاد النوافذ المحولة إلى UTC،
  بالاستثناء الرسمي الفعال أولًا. لا تستخدم `detect_session` أو أيام الأسبوع
  وحدها كدليل، ولا تستخدم observed offset كمرجع تاريخي.
- [ ] شغّل الاختبارات وأثبت أن تغيير الدليل أو انتهاء صلاحيته يغير dependency hash.
- [ ] راجع فرق المهمة فقط قبل أي commit اختياري.

## Task 4: دمج التصنيف مع الفحص والإصلاح

**Files:** Modify `quality/repair.py`, `quality/stored_audit.py`, `quality/automation.py`;
Test `tests/test_data/test_session_quality_integration.py`; existing regression files remain enabled.

**Interfaces:**
- أضف `calendar: CalendarContext | None = None` إلى `repair_pair` و
  `audit_stored_ohlcv`؛ وأضف `calendar_store: SessionEvidenceStore | None = None`
  إلى `QualityAutomation`. None يحافظ على التحذير الحالي والسلوك الآمن.
- أضف `series_dependency_hash` للتغطية المجمعة (timestamp, source, revision
  والقيم المتعارضة) تحت القفل؛ و`calendar_dependency_hash` للشهادة وملخصها.
- `latest_quality` يفحص بصمات الاعتماد الحالية، لا بصمة المصدر وحدها؛ لا جلب
  شبكي أو إنشاء schema في مسار القراءة. تغيّر/انتهاء دليل التقويم يبطل الشهادة.

- [ ] اكتب اختبارات مراقبة السلوك: إغلاق موثق لا يرسل طلب MT5؛ unknown و
  expected_quote يرسلان طلبًا محدودًا؛ غياب backfill المغطى بـpoll لا يرسل طلبًا؛
  تغيير calendar/clock/exception/combined-series يعيد تقييم شهادة لم تتغير صفوفها.
- [ ] شغّلها وتحقق من الفشل، ثم أدرج `refresh` مرة في بداية الدورة وسياقًا
  ثابتًا لكل زوج. أبقِ أقفال المالك/الزوج، حفظ المحاولات عند defer، حدود
  أربع نوافذ ×500، retry backoff، وعزل الأصل قبل الإزالة.
- [ ] خزّن في التقرير أعداد `confirmed_closed`, `covered_elsewhere`,
  `expected_quote_missing`, `unknown` مع الأسباب ومعرفات الأدلة وبصماتها؛
  نقص تاريخي بلا تقويم لا يصبح نجاحًا، ولا يعني expected_quote فساد السعر.
- [ ] قيّم حداثة تغذية الزوج المجمعة منفصلة عن مجموعة backfill التاريخية؛
  لا تحذف التحذير عن نقص تغطية مجموعة إلا إذا احتسب التقرير دليلها وبصمته.
- [ ] شغّل integration و`test_quality_repair.py`, `test_stored_quality_audit.py`,
  `test_quality_automation.py`؛ يجب بقاء المصدر الآخر محفوظًا، والعزل مفتوحًا
  عند التعذر، والقراءة/النشر محجوبين عند الفشل الحاد كما كانا.
- [ ] راجع فرق المهمة فقط قبل أي commit اختياري.

## Task 5: الحالة المقروءة والواجهة

**Files:** Modify `main.py`, `research_reader.py`, `quality/stored_audit.py`,
`dashboard/src/components/research-lab/{types.ts,adapters.ts,ResearchLabTab.tsx}`;
Test `tests/test_data/test_session_status.py`, `dashboard/tests/research-sources.test.mjs`, `dashboard/tests/research-view.test.mjs`.

**Interfaces:**
- أضف `calendar` إلى `/health.quality_automation` كحالة مختصرة بلا أسرار أو
  مسارات محلية؛ وأضف `calendar_summary` و`gap_summary` إلى quality_summary
  للمجموعة عبر البوابة الحالية، دون endpoint كتابة عام جديد.
- الواجهة تعرض الحالة وسببها والتقاط/استيراد/انتهاء الدليل ومعرفه، وأعداد
  الفواصل المصنفة والمجهولة؛ وقت UTC في العقد وعرض Asia/Aden للمستخدم.

- [ ] اكتب اختبارات أن no calendar لا يعرض «موصول»، وstale لا يعرض «جاهز»،
  ولا يسقط التحذير، وفشل مصدر التقويم لا يختبئ كقائمة فارغة ناجحة.
- [ ] شغّل الاختبارات للفشل؛ نفّذ الإسقاط والعرض مع إبقاء issuer/verification
  منفصلين وتحديث الصفحة كل 60 ثانية، وعدم إضافة أزرار تداول أو اعتماد يدوي.
- [ ] شغّل جميع `node --test tests/*.test.mjs` من dashboard، ثم
  `node node_modules/typescript/bin/tsc --noEmit`؛ النجاح exit 0 بلا حالات فاشلة.
- [ ] راجع فرق المهمة فقط قبل أي commit اختياري.

## Task 6: التجميع وتعليمات تشغيل فعلية والتحقق النهائي

**Files:** Create `scripts/check_session_reader.py`, `docs/MT5_SESSION_READER.md`;
Test `tests/test_data/test_session_reader_check.py`.

**Interfaces:** `check_session_reader.py --export <path> --policy <path>` قراءة
فقط، يعرض حالة وهوية وبصمات دون أسرار؛ exit 0 لدليل جاهز، 2 لغير جاهز، 1
لخطأ تحقق. لا يفتح DuckDB محليًا ولا يرفق المؤشر بالمنصة.

- [ ] اكتب اختبارات CLI على ملفات مؤقتة تحقق مخارج 0/1/2 دون معاملات سوق.
  شغّلها للفشل ثم نفّذ الأداة واختبرها.
- [ ] وثّق نسخ المؤشر وتجميعه وإرفاقه يدويًا، المسار الدقيق لـ FILE_COMMON،
  مطابقة الخادم والرمز، إضافة مصدر الساعة والاستثناءات الرسمية، إزالة المؤشر،
  وما يعنيه عدم اتصال المنصة. لا تطلب تفعيل AutoTrading أو DLL أو WebRequest.
- [ ] اكتشف مسار MetaEditor بقراءة إعداد المنصة فقط، وشغّل المترجم في الخلفية
  المخفية مع log إلى مجلد المهمة. راجع الأخطاء والخرج الفعلي ووجود EX5؛ عند
  غياب المترجم تسلّم المصدر مع حالة «لم يُجمّع» لا «جاهز للتشغيل».
- [ ] شغّل `.venv/Scripts/python.exe -m pytest tests/test_data tests/test_api -q`،
  جميع اختبارات dashboard، TypeScript، و`git diff --check` للمسارات المعدلة.
  حاول بقية suite إن كانت dependencies تسمح وسجّل أي تعذر/فشل بالاسم؛ لا
  تدّعِ نجاح root suite إذا تعطل جمع المشروع المرجعي المستورد.
- [ ] اطلب من المستخدم إرفاق المؤشر فقط بعد تسليم EX5 ناجح/تعليمات التجميع.
  اختبر ملفًا حقيقيًا من منصته عبر CLI ثم الاستيراد الآلي ثم الواجهة. دون
  هذه الخطوة تبقى حالة النشر «بانتظار تشغيل المؤشر»، لا مكتملة حيًا.
- [ ] عند إعادة تحميل خدمة البيانات، تحقق من العمليات المقصودة، إيقاف رشيق
  وcheckpoint ونسخة احتياطية قبل أي migration. لا توقف MT5 أو executor ولا
  تشغّل التداول. تحقق أن auto_trade ما زال false.
- [ ] مراجعة نهائية مستقلة للتغييرات المحددة، وإصلاح الملاحظات الحرجة/المهمة
  وإعادة اختبارها. أي commit/دمج/PR لاحق يقتصر على الملفات المقصودة وبعد الطلب.

## Review and execution handoff

الخطة لم تُنفّذ بعد. أوصي بالتنفيذ المباشر داخل هذه المحادثة باستخدام
`superpowers:executing-plans`: العقود والمصنف والإصلاح مترابطة، وتنفيذها
بالترتيب أوفر من توزيع كتابة الواجهات نفسها على وكلاء متعددين. البديل تنفيذ
بواسطة وكلاء لكل مهمة ومراجع مستقل، بعد اختيار المستخدم له.

بعد اعتماد الخطة وطريقة التنفيذ: اقرأ التصميم والخطة كاملين، راجع الحالة
المحلية والتعليمات، ثم نفّذ دورات TDD مهمةً مهمة. النشر الحي مشروط بتوفر
مترجم وملف جلسات حقيقي ودليل ساعة صالح، لا بمجرد نجاح اختبارات Python.
