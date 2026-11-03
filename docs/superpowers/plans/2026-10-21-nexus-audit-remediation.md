# خطة إصلاح Nexus الشاملة المبنية على الفحص المرئي

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** معالجة جميع نتائج تدقيق 20 أكتوبر والنواقص الموثقة، وإثبات تشغيل مستقر ومسار بحث قابل للتتبع، دون تفعيل التداول الحقيقي.

**Architecture:** الإصلاح داخل الخدمات والمكونات الحالية، دون إضافة قوائم رئيسية. مصدر الإعدادات هو مستخدم الموقع وحساب الوسيط المختار؛ تُفصل صحة الاتصال عن جودة البيانات وعن أهلية التحليل وعن صلاحية التداول. تنفذ الخطة على دفعات صغيرة؛ لكل دفعة اختبار فشل سابق ثم إصلاح ثم دليل واجهة.

**Tech Stack:** Windows، Python/FastAPI، DuckDB، Redis، MT5/MQL5 للقراءة المعزولة، Next.js 14.2.5/React/TypeScript، اختبارات pytest وNode.

**Spec:** `project_audit/ui-audit-20261020/REPORT_AR.md` (52 وحدة، 20 ملاحظة، 8 مسارات HTTP مرصودة)؛ `project_audit/ui-audit-20261020/FIX_BATCH_1_AR.md`؛ `project_audit/RUNTIME_HANDOFF_20261021.md`.

## القيود العامة

- لا حذف بيانات ولا استبدال قاعدة ولا تغيير كلمة مرور أو صلاحيات المستخدم الحقيقي ضمن هذه الخطة.
- لا تشغيل executor أو تفعيل LIVE أو تبديل حساب MT5 لإزالة تحذير. الاختبارات المالية في بيئة معزولة فقط وباعتماد منفصل.
- لا نجاح مصطنع: unknown/loading/unavailable/stale/empty حالات مختلفة؛ قيمة مفقودة ليست صفرًا ولا NEUTRAL ولا NORMAL.
- لا أسعار مولدة لملء الفجوات، ولا نقل أسعار مزود آخر إلى سلسلة الوسيط دون فصل المصدر.
- US10Y غير إلزامي الآن. مجموعة سياق الذهب المستهدفة XAUUSD/XAGUSD/WTI/DXY/VIX؛ ربط الرموز الفعلية مثل XAUUSDs من الحساب، لا افتراض لاحقة موحدة.
- تأكيد OneRoyal-Demo لا يُنقل تلقائيًا إلى OneRoyal-Server؛ لا ساعة UTC تاريخية مخمّنة.
- لا إعادة هيكلة شاملة أو ترقية مكتبات جماعية. تعارض requirements يُحل بعقد توافق واختبارات أولًا.
- التغييرات الحالية ملك المستخدم. تسجل قائمة ملفات الدفعة وتراجع الفروق؛ لا commit لتغييرات غير مرتبطة، ولا استعادة Git مدمرة.
- أي ملف/اختبار جديد مسمى أدناه هو مخرج مخطط لا ادعاء بوجوده الآن.

## الحالة المرجعية — ليست نتيجة اختبار جديد

- جولة 20 أكتوبر: زيارة 12 مسارًا، توثيق 52 وحدة، 123 لقطة؛ صفر إصلاحات خلال الجولة نفسها.
- دفعة 21 أكتوبر: UI-02 وUI-03 وUI-06 وAPI-01 لها إصلاح موثق، و86 اختبار واجهة وTypeScript ناجحان وقتها. تتطلب إعادة تحقق بعد الدمج.
- أعيد تشغيل API/data/dashboard؛ أفاد المستخدم بنجاح الدخول. هذا لا يثبت بقية الوظائف أو دوام التشغيل.
- identity_mismatch لملف الجلسات وعيوب التشخيص/CrossAsset/TradeMemory لا تزال تحتاج معالجة مثبتة.
- 16 ملاحظة من السجل الأصلي غير مغلقة بإصلاح موثق؛ ليست كلها انهيارات، وبعضها نقص منتج أو يحتاج قرار نطاق.

## Review Focus

1. خدمة ترد HTTP 200 لكن البيانات قديمة/ناقصة: لا إعلان جاهزية للتحليل (مهمتا 2 و5).
2. تبديل الحساب أثناء طلب سابق: لا تظهر أو تحفظ بيانات الحساب القديم في الجديد (مهمة 4).
3. polling أثناء تعديل مسودة: لا يفقد المستخدم تعديلاته، والتعارض يظهر صراحة (مهمة 4).
4. انتقال توقيت غير معروف/إغلاق أسبوعي/عطلة استثنائية: لا تصنيف فجوة كفساد أو صحة نهائية بلا دليل (مهمة 6).
5. فشل/إلغاء مهمة خلفية بعد نجاح HTTP بدء التشغيل: لا تدريب أو تنزيل مكتمل اعتمادًا على مؤقت (مهمتا 7 و9).

## ترتيب التنفيذ وبوابات القبول

|المرحلة|المهام|المخرج المطلوب|
|---|---|---|
|A — استقرار وصدق|1–3|تشغيل محدود، مصادقة صحيحة، حالات غير مضللة|
|B — إعدادات وبيانات|4–7|عزل حسابات، مصادر موثقة، جلسات وتاريخ، سلسلة بحث قابلة للتتبع|
|C — تحليل ونماذج|8–10|AI واضح الحدود، jobs حقيقية، اختبارات تاريخية قابلة للتكرار|
|D — تجربة وقبول|11–12|إزالة التكرار والقص، إعادة مرور 52 وحدة، تقرير قبول مشروط بالأدلة|

ترتيب إلزامي: 1 ← 2 ← 3، ثم 4 ← 6 ← 7 ← 10. يمكن تنفيذ 5 و8 و11 بالتوازي بعد تثبيت العقود وبملفات غير مشتركة. لا حاجة إلى 15 أو30 وكيلًا؛ فريق صغير محدد الملفات أقل تعارضًا واستهلاكًا. لا يعلن عدد وكلاء لم يُشغّل فعلًا.

## دورة العمل لكل مهمة

- [x] إعادة إنتاج الحالة وتسجيل المدخلات والوقت والحساب والمسار دون أسرار.
- [x] كتابة اختبار regression يفشل بسبب السلوك المطلوب تصحيحه، لا بسبب غياب dependency فقط.
- [x] تشغيل الاختبار وتسجيل الفشل؛ تنفيذ أقل تعديل يحقق العقد.
- [x] تشغيل الاختبار المستهدف ثم الاختبارات المجاورة وTypeScript عند تغيير الواجهة.
- [x] فتح الواجهة واختبار حالات loading/empty/success/error/stale المناسبة، وتسجيل الطلبات الفاشلة.
- [x] حفظ لقطة قبل/بعد وسجل تحقق، ومراجعة الفرق ثم تحديث سجل المهمة. commit انتقائي فقط عند اعتماد حفظ الدفعة في Git.

### المهمة 1 — تشغيل محلي مستدام وآمن (P0)

**الملفات:** `run.py`، `scripts/start_settings_only.py`، `requirements.txt`، `services/nexus_api/requirements.txt`؛ اختبار موجود `tests/test_runner_safety.py` وجديد `tests/test_settings_only_runner.py`.

**العقد:** وضع الإعدادات يشغّل Redis/API/data/dashboard فقط؛ لا broker auto-login ولا منفذ تداول. /health readiness لا يساوي فتح المنفذ. المشغل لا يحذف .next ولا يقتل listener غير مملوك.

- [x] أضف اختبارات تمنع MT5_LOGIN الفعلي وENABLE_IBKR/CCXT والخدمات التداولية في بيئة العمليات التابعة.
- [x] اختبر: Redis غير متاح، منفذ مشغول بعملية أخرى، إقلاع data فاشل، /health=200 مع ready=false، انهيار dashboard، وعدم تكرار التشغيل.
- [x] صحح المشغل بحيث ينتظر ready الحقيقي ويمنع API من سبق مالك DuckDB، ويراقب الواجهة بحد محاولات واضح. لا يترك عمليات يتيمة عند فشل بدء التشغيل.
- [x] حسم تعارض websockets الموثق بين متطلبات الجذر وAPI في بيئة اختبار؛ لا تغيير الإصدار العامل دون اختبار auth/WS. المكتبات الاختيارية لا تثبت غيابها عطلًا.
- [x] تحقق: `.venv\Scripts\python.exe -m pytest tests/test_runner_safety.py tests/test_settings_only_runner.py -q` ثم `python -m pip check` باستخدام Python البيئة نفسها.
- [x] نفّذ إعادة إقلاع مخططة للخدمات المملوكة فقط بعد إبلاغ المستخدم؛ تحقق من /health و/login وعملية الدخول وحفظ الإعدادات. لا إعداد مهمة Windows تلقائية دون طلب منفصل.

**سجل التنفيذ:** إقلاعات ناجحة متتالية ×3، بوابة 200 خلال ~2.4s (مهلة الواجهة = تجميع Next الأول لا Python)،
`pytest tests/test_settings_only_runner.py` 17/17 + `test_runner_safety` ضمن 36/36، `pip check` سليم،
`websockets` مُوائم في `services/nexus_api/requirements.txt` إلى `>=13.0,<14.0` (المثبّت 13.1 لم يتغيّر؛ auth/WS مُختبَر)،
إزالة `rundir /s /q .next` من `run.py:spawn_dashboard`، إعادة كتابة `scripts/start_settings_only.py`.
تقرير التبعيات: `project_audit/DEPENDENCY_AUDIT_20261021.md` (بما فيه polars rtcompat وpsutil).

**القبول:** تشغيل قابل للتكرار دون حذف، لا listener تداول جديد، ثلاثة إقلاعات متتالية ناجحة، ومراقبة 30 دقيقة دون crash أو تزايد غير مبرر للعمليات. الانتهاء لا يضمن العمل بعد نوم/إطفاء الجهاز.

### المهمة 2 — مصادقة وعقود API وحالة الخدمات (P0)

**الملفات:** `dashboard/src/components/windows/SystemDiagnostic.tsx`، `dashboard/src/lib/system-health-status.ts`، `services/nexus_api/routers/{market,agents,ml,risk,intelligence}.py`، `services/nexus_api/routers/admin.py`؛ اختبارات `tests/test_api/test_data_client.py` و`test_admin_data_service.py` و`test_websocket_auth.py` وجديد `dashboard/tests/system-diagnostic-state.test.mjs`.

**العقد:** loading قبل اكتمال الفحص؛ 401 مصادقة، 403 صلاحية، 404 عقد غير موجود، 502 upstream، timeout اتصال، disabled_by_mode توقف مقصود. HTTP 200 يتطلب تحقق الحمولة؛ لا تعديلات جماعية في الأكواد قبل تحديد السبب.

- [x] اختبر خدمات=[] وبداية التحميل: لا يظهر All systems operational. اختبر فحصين متداخلين وانتهاء طلب قديم بعد طلب أحدث.
- [x] أصلح ترويسة مصادقة فحص candles، وامنع تحويل 401 إلى MT5 offline. لا إضعاف حماية endpoint.
- [x] أعد اختبار المسارات الثمانية: agents/decision/XAUUSD، ml/traders/autonomous/status، ml/traders/status، v2/market/candles، trade-memory/metrics، ml/traders/mode، risk/settings، intelligence/institutional/XAUUSD.
- [x] المسار obsolete trade-memory/metrics يجب ألا يطلبه المكوّن بعد الإصلاح السابق؛ لا ضرورة لإنشاء route وهمي. اجعل الرمز تابعًا للحساب في الطلبات القابلة للتخصيص.
- [x] صنف خدمات الوضع المحدود «غير مشغلة في هذا الوضع»، ولا تشغلها لتبدو الحالات خضراء. افحص API/data secrets داخليًا دون عرض قيمها.
- [x] تحقق: `.venv\Scripts\python.exe -m pytest tests/test_api/test_data_client.py tests/test_api/test_admin_data_service.py tests/test_api/test_websocket_auth.py -q`؛ من dashboard شغّل اختبارات Node الجديدة والمجاورة.

**سجل التنفيذ:** `project_audit/REPAIR_TASK2_20261021.md` —
بانر "Checking services…" مُثبَت باللقطة `t2-01-boot-checking-banner.png` (UI-01 مغلق)؛
الثمانية: 6×502 upstream صريح + candles 404 بعد المصادقة + trade-memory/metrics 404 (لا route، والمكون لا يطلبه — تحقق CDP)؛
بدون مصادقة 7×401؛ `classifyUpstreamProbe` جديد (502 → "upstream offline (HTTP 502)")؛
فحصين متداخلين محفوظان بـ `checkSeqRef`؛ رفع probe timeout 8s→12s بسبب ازدحام البوابة الموثَّق (uvicorn عمود واحد + انفجار ~35 طلباً عند التحميل)؛
`dashboard` tests **102/102**، `tsc --noEmit` نظيف، pytest المصادقة **31/31**.

**القبول:** كل طلب من الثمانية له نتيجة موثقة ومبررة؛ عدد أخطاء الخدمات المطلوبة غير المعالجة صفر، أما الخدمات غير المطلوبة فتعرض سبب التعطيل. يغلق UI-01، ويعيد التحقق من API-01.

### المهمة 3 — منع المقاييس الوهمية (P0)

**الملفات:** `dashboard/src/lib/data-presentation.ts`، `dashboard/src/components/windows/{CrossAsset,TradeMemoryPanel,GatewayDiagnostic,ActivePositions,BacktestPanel}.tsx`، `services/nexus_api/routers/intelligence.py`؛ `dashboard/tests/data-presentation.test.mjs`، جديد `dashboard/tests/intelligence-availability.test.mjs`، `tests/test_api/test_trade_memory_availability.py`.

**العقد:** بيانات no_data/مفقودة لا تمنح 3/5 أو NEUTRAL؛ metrics={} لا تعرض undefined؛ صفر صفقات صالح مختلف عن فشل المصدر. لا تغيير في أوزان الاستراتيجية أو قواعد المخاطر ضمن إصلاح العرض.

- [x] اختبر CrossAsset بلا أسعار وبلا updated_at وبمصدر no_data، ونجاح حديث ثم فشل تحديث؛ المتوقع «غير متاح» ودرجة — لا درجة تداول مستنتجة.
- [x] اختبر TradeMemory: metrics={}، صفر صفقات صريح، total_trades مفقود، مقاييس جزئية، حقول غير رقمية، عينة سليمة. لا toFixed على undefined ولا نسب مختلقة.
- [x] أصلح حدود التحويل من API إلى العرض؛ إذا تغيّر عقد Python افحص جميع مستهلكيه قبل تعديل nullability.
- [x] أعد تشغيل regression للصفقات المتقادمة وTilt UNKNOWN وbacktest صفر صفقات وقراءة trades داخل by_session.
- [x] تحقق: من dashboard `node --experimental-strip-types --test tests/*.test.mjs` ثم `node node_modules/typescript/bin/tsc --noEmit`؛ ومن الجذر اختبار Python المذكور.

**سجل التنفيذ (2026-10-21):** السبب الجذري UI-04 مُثبت TDD في `intelligence.py:264-271` (fallback اختلق neutral/3pts/0 → الآن unknown/None/None)؛ `crossAssetPresentation`/`tradeMemoryPresentation`/`sanitizeGroupStats` في `data-presentation.ts`؛ عزل `CrossAsset`+`TradeMemoryPanel`. نتائج: pytest trade-memory 7/7 (المجموعة المركّزة 21/21، الكلية 74/74)، Node **117/117** (منها `intelligence-availability.test.mjs` الجديد 15)، tsc exit 0. إثبات متصفح حيّ: لوحة CROSS-ASSET = "UNKNOWN / Régimen no disponible / -pts / no_data" ومطابقة API `{regime:unknown, pts:null}`؛ TRADE MEMORY ترويسة "—" + "Métricas de memoria incompletas"؛ UI-02 "Tilt: UNKNOWN" مقابل `tilt_status:"normal", available:false`؛ UI-06 زر Ejecutar حقيقي → 0 صفقات → شارة "بيانات غير كافية" بلا تصنيف سلبي (`t3-01..`, `t3v-02..05`). أخطاء متبقية موثقة (risk backend يختلق "normal"، backtest envelope صفائي، حساسية whitelist) في `project_audit/REPAIR_TASK3_20261021.md` — غير حاجبة.

**القبول:** يغلق UI-04 وUI-05، وتثبت UI-02/UI-03/UI-06 مجددًا. لا إعلان الربحية أو المخاطرة الطبيعية دون بيانات.

### المهمة 4 — الوسيط والحساب والأصول والحفظ المعزول (P0)

**الملفات:** `dashboard/src/components/settings/broker/{BrokerSettingsView,BrokerSettingsTab}.tsx`، `services/nexus_api/routers/broker_settings.py`، ملفات broker_settings في `services/nexus_data/` حسب المطابقة الحالية؛ اختبارات `tests/test_api/test_broker_settings.py` و`tests/test_data/test_broker_settings_store.py` و`test_broker_settings_route.py` وجديد `dashboard/tests/broker-draft-persistence.test.mjs`.

**العقد:** المفتاح الفعلي user_id + broker_account_id؛ حفظ الحساب المختار دائم ويستعاد بعد refresh/restart. تعريف broker profile لا يثبت ملكية MT5؛ قراءة الهوية يجب أن تطابق login/server. لا تُطلب كلمة المرور في الواجهة لهذا الاختبار.

- [ ] اختبر مستخدمين بحسابين في قاعدة disposable؛ قراءة/تعديل/تصدير الآخر مرفوضة دون تسريب أسماء أو رموز أو أدلة.
- [ ] اختبر اختيار وسيط ← حساب ← أصول مع تبديل سريع أثناء تحميل سابق؛ تستبعد الاستجابة القديمة ولا تحفظ تحت الحساب الجديد.
- [ ] احمِ المسودة من polling، وأظهر dirty/saving/saved/failed/version_conflict؛ لا «تم الحفظ» قبل إقرار backend. حدد نطاق SaveAll والنماذج المستقلة.
- [ ] اجعل أصول البحث المختارة منفصلة عن إذن التداول. احتفظ بالتفضيلات القديمة دون ترحيل صامت لمعنى disabled؛ وثّق المعنى المعتمد قبل تحويل السجلات.
- [ ] تحقق من picker: تصنيف/رمز/وصف، بحث وفرز وتحديد متعدد، تحقق الرموز من حساب MT5 المطابق، وحالة عدم اتصال صريحة.
- [ ] اختبر حفظ ثم refresh ثم إعادة تشغيل data ثم إعادة الدخول بالحساب نفسه؛ لا تغييرات على حساب المستخدم الحقيقي إلا بالتعديلات التي يقرها في الواجهة.

**القبول:** بيانات الحساب مستقلة وقابلة للاستعادة؛ لا تكرار حقول الاختيار؛ لا بيانات حساب قديم بعد التبديل. توثيق معنى التحليل/التداول/المعطل يغلق لبس الوحدات27–31.

### المهمة 5 — حقيقة المصادر والأخبار والاقتصاد (P1)

**الملفات:** `dashboard/src/components/settings/SourceConnectionManager.tsx`، `dashboard/src/components/fundamental/`، `dashboard/src/lib/fundamental-contract.ts`، `services/nexus_api/routers/fundamental.py`، `services/nexus_news/fundamental/{source_registry,source_base}.py`، `services/nexus_data/fundamental_store.py`؛ اختبارات `tests/test_fundamental/test_source_manager_r3.py` و`test_free_official_sources_r31.py` و`tests/test_api/test_source_manager_ssrf.py` و`test_source_manager_authorization.py` و`tests/test_news/test_timing_quality.py`.

**العقد:** حقول منفصلة configuration_status / connectivity / last_checked_at / data_freshness / analysis_eligible مع reasons ومصدر التحقق؛ أسماء JSON النهائية توافق العقد الحالي ولا تنشأ نسخة متوازية منه. health_only لا يثبت وجود المؤشر أو أهلية التحليل.

- [ ] اختبر اتصال ناجح قديم، مصدر missing_config، health_only، بيانات فارغة، سلسلة سليمة متقادمة، مصدر معطل؛ لا «جاهز للتحليل» دون الشروط اللازمة.
- [ ] أصلح الصف الفارغ وحالات التحميل وعدم توفر الأخبار؛ اعرض آخر تحديث ووقت أول إتاحة والمصدر، وأولوية الإعداد العام مقابل الشخصي.
- [ ] تحقق من كل مصدر مفعّل فعلًا في السجل؛ لا تفعل25 مصدرًا تلقائيًا، ولا تشتر اشتراكات أو ترسل مفاتيح لخدمة جديدة. افتقاد المصدر يُسجل كمتطلب خارجي.
- [ ] اختبر التصفية بالأصل/الأهمية/الفترة، إزالة الأخبار المكررة، تمييز نتيجة اتصال محفوظة عن اختبار حالي، وألا تعني استجابة الصفحة الرئيسية توفر بيانات اقتصادية.
- [ ] شغّل مجموعات pytest المذكورة مع منع الاتصال الخارجي غير المقصود؛ اختبارات المزود الحقيقية منفصلة بأسماء الأدلة ووقت الفحص.

**القبول:** يغلق DATA-01 وUX-02؛ الوحدات4 و7–14 و32 و45 تعطي بيانات موثقة أو سبب نقص محدد، لا أرقامًا مختلقة.

### المهمة 6 — جلسات الوسيط وUTC التاريخي والتوقيت الصيفي (P0)

**الملفات:** `services/nexus_data/` ملفات session_store/session_calendar/session_reader المعينة عبر الاختبارات؛ `services/nexus_data/research_market.py` و`data_loader.py`؛ `dashboard/src/components/settings/broker/BrokerSettingsView.tsx`؛ اختبارات `tests/test_data/test_session_contracts.py` و`test_session_calendar.py` و`test_account_session_sync.py` و`test_research_session_review.py` و`test_mql5_session_enumeration.py`.

**العقد:** جدول offset مؤرخ بتاريخ سريان ومصدر ومستوى ثقة، منفصل عن جلسات الأسبوع وعطلات الاستثناء. تحفظ server_time وUTC وطريقة التحويل؛ قارئ اليوم لا يثبت توقيت التاريخ السابق. تصدير حساب/خادم مختلف أو منتهي لا يعتمد.

- [ ] أعد إنتاج identity_mismatch وحدد login/server/symbols المتوقع والمصدّر دون كشف أسرار. لا تغيّر هوية الحساب إلى0 لمجرد تجاوز المنع؛ افصل تعطيل auto-login عن هوية الحساب المختار إن كانا مختلطين.
- [ ] اختبر اختلاف الحساب والخادم والرمز، ملف تالف/قديم، انتقال UTC+3 إلى UTC+2، ساعة مكررة، فترة انتقال غير محددة، عطل/فتح متأخر/إغلاق مبكر.
- [ ] أبق رد الدعم الخاص بـOneRoyal-Demo مقيدًا بهذا الخادم؛ سجّل الحاجة لتأكيد الخادم الحقيقي أو دليل مطابق. لا تخمّن ساعة التحويل داخل إغلاق السوق.
- [ ] اعرض من الإعدادات جداول السريان والأدلة وسجل التعديل، وأثر التعديل على فترات الشموع؛ تعديل توقيت يولد مراجعة واعتمادًا جديدًا ولا يعيد كتابة التاريخ بصمت.
- [ ] تحقق من تصدير MQL5 الموجود ومخططه وعد الرموز، دون إزالة روبوت تداول أو تغيير حساب المنصة. إعادة الإضافة داخل MT5 ينفذها المستخدم إذا لزمت.
- [ ] شغّل مجموعات الاختبار المذكورة؛ قارن مجموعة ساعات معروفة يدويًا قبل/بعد الانتقال وخارج ساعات السوق.

**القبول:** تنتهي المشكلة المؤكدة أو تظهر فترة غير معتمدة بأسبابها. لا «اجتازت» للفترة التاريخية غير المثبتة. هذه بوابة إلزامية للاختبار التاريخي.

### المهمة 7 — جلب وتنظيف وتتبع قابل للتكرار (P0/P1)

**الملفات:** `dashboard/src/components/research-lab/{DataSourcesWorkspace,ResearchLabShell,ResearchEvidencePanel}.tsx`، `services/nexus_api/routers/{research_lab,broker_settings}.py`، `services/nexus_data/{research_market,research_analysis,data_loader}.py`؛ اختبارات `tests/test_data/test_research_market.py` و`test_quality_automation.py` و`test_quality_repair.py` و`test_research_lineage_migration.py` و`test_pit_availability.py` و`test_research_context_engine.py`.

**العقد:** كل run مربوط بالمستخدم/الحساب/الأصل/الإطار/الفترة والمصدر وإصدارات الإعدادات؛ input_hash وoutput_hash يربطان شهادة الجودة بالبيانات. فشل تحديث لا يمحو آخر نسخة سليمة ولا يخفي التقادم.

- [ ] اختبر جلب متكرر للفترة نفسها، طلبين متزامنين، فشل جزئي لأصل، انقطاع MT5، أكثر من إطار؛ لا تكرار شموع أو ازدواج jobs ولا نسخ بيانات بين الحسابات.
- [ ] اختبر OHLC غير صالح، duplicate متعارض، فجوة أثناء جلسة، إغلاق معروف، وحداثة أثناء إغلاق السوق. أصلح من المصدر نفسه فقط؛ خلاف ذلك اعزل/حذر واحتفظ بالصف الخام وبسبب الإجراء.
- [ ] اجعل المراقبة الآلية ذات retry محدود وbackoff وسجل إجراءات وإمكانية إيقاف؛ النجاح بعد إعادة الفحص على البصمة الجديدة لا بتغيير label.
- [ ] افصل أرشيفًا عامًا موسومًا عن بيانات الحساب؛ لا تعرض0/not-connected عامًا فوق نتائج حساب موجودة. اعرض تبويبات الأصل ثم الإطار وسجل التشغيل دون تكرار نماذج الإدخال.
- [ ] زر «عرض الدليل» يفتح تقرير الصف نفسه بالمعرف والبصمة، مع API يتحقق من الملكية. أصلح الفلاتر الحالية أو اعرضها معطلة بسبب واضح؛ لا زر يوهم بوظيفة غير موجودة.
- [ ] اختبار تحميل CSV/JSON جديد والتحقق من المحتوى والبصمة وعدد الصفوف، لا مجرد وجود ملف قديم في Downloads.
- [ ] شغّل مجموعات الاختبار المذكورة؛ تجربة جلب حقيقية صغيرة للأصول المختارة بإطار M15 وفترة محدودة، ثم اختبار الأطر الأخرى المتاحة بما يعلن حد التاريخ لكل أصل.

**القبول:** يغلق UX-06 وUX-07 وجزء الأرشيف من GAP-01. بيانات خام → تنظيف → تحقق → تتبع → مخرجات مترابطة ببصمة. «الفجوات صفر» ليست شرطًا شكليًا؛ المطلوب تصنيف صحيح وحالة غير مضللة.

### المهمة 8 — المحلل المحلي وسياق الأصول (P1)

**الملفات:** `services/nexus_api/fundamental_local_ai.py`، `services/nexus_api/routers/fundamental.py`، `dashboard/src/components/fundamental/`، `services/nexus_data/research_analysis.py` و`data_loader.py`؛ اختبارات `tests/test_agents/test_local_llm_readiness.py` و`tests/test_llm_factory.py` و`tests/test_data/test_research_context_engine.py`؛ جديد `tests/test_api/test_local_ai_availability.py`.

**العقد:** تمييز خدمة LLM متوقفة/نموذج غير مثبت/مهلة/استجابة غير صالحة/أدلة ناقصة. لا تحويل إلى مزود سحابي أو تنزيل نموذج ضخم دون موافقة. التحليل شرح مستند إلى الأدلة وليس أمر تداول.

- [ ] اختبر كل حالة اتصال، نجاح حقيقي بسؤال واحد، منع الهلوسة عند غياب البيانات، وعرض النموذج ووقت التشغيل ومعرفات الأدلة المستعملة.
- [ ] صحح ConnectError بعد فحص عنوان الخدمة والنموذج المحلي المتوفر، لا باستبدال إجابة ثابتة. حسّن تباين حقل السؤال ضمن مهمة11.
- [ ] احسب الارتباط من العوائد المتزامنة لا مستويات الأسعار، نوافذ20/60/120، مع sample_count/coverage وconstant_series/insufficient_data؛ لا تقديم ارتباط مرصود كسبب أو ضمان تنبؤ.
- [ ] حدد معنى إشارة lag بالاختبار: سلسلة مصطنعة معروفة تسبق الذهب بثلاث شموع تعطي اتجاه lag متفقًا عليه، ولا تسمح بقراءة مستقبل عند as_of. هذه fixtures اختبار لا أسعار إنتاجية.
- [ ] اعرض US10Y كاختياري غير مختار أو أخفه من النتائج الملزمة؛ لا يوقف السياق الحالي. confidence/conflict غير المعايرين يبقيان غير معتمدين؛ لا تفعيل No-Trade آلي من درجة جديدة دون معايرة واعتماد منفصل.
- [ ] شغّل اختبارات AI والسياق المذكورة؛ مرّ على Overview/Macro/Monetary/Cross-assets/Geopolitics/Flows/News/Learning/LocalAI بحالات امتلاء ونقص.

**القبول:** يغلق AI-01 وUX-08، وتصبح حدود التحليل والأدلة واضحة. لا ادعاء تدريب نموذج بمجرد ظهور جواب لغوي.

### المهمة 9 — ML/DL/RL/HMM والوكلاء وحياة المهام (P1/P2)

**الملفات:** `dashboard/src/app/dashboard/{models,model-comparison,ml-models,deep-learning,reinforcement-learning}/page.tsx`، `services/nexus_api/routers/{ml,agents,regime}.py`، `services/nexus_ml/traders_api.py`، `services/nexus_agents/`؛ اختبارات `tests/test_ml/test_traders_api_lifecycle_ownership.py` و`test_walk_forward_validation.py` و`test_model_promotion.py` و`test_model_bundle_validation.py` و`tests/test_agents/test_arbitrator_evidence_gates.py` و`tests/test_api/test_ml_training_authorization.py`.

**العقد:** job_id وحالة queued/running/succeeded/failed/cancelled مبنية على backend، لا مؤقت واجهة. النموذج له dataset_hash/config_version ومقاييس out-of-sample. ملف pickle موجود ليس دليل تدريب أو أمان تحميل.

- [ ] اختبر نجاح بدء job ثم فشل التدريب، إلغاء، تحديث الصفحة، jobs متكررة، انقطاع WS، نموذج بلا بيانات، نموذج غير مطابق للإطار.
- [ ] وحّد واجهات التدريب المكررة ببيانات ومكونات مشتركة وروابط واضحة؛ لا حذف روابط قديمة قبل تحويلاتها. HMM يعرض transition probabilities فقط من نموذج صالح، وإلا «رسم توضيحي».
- [ ] صِل status الخدمات المطلوبة في بيئة بحث معزولة؛ لا تعيد تشغيل loop تداول ضمنيًا. اختبر التدريب بfixture صغيرة قبل مهمة مكلفة على بيانات حقيقية معتمدة.
- [ ] طابق سجل الوكلاء الفعلي مع العدد الظاهر؛ graph أوWS متصل لا يساوي قرارًا صالحًا. القرارات تحتاج مصادر وتوقيت وجودة وموافقة مخاطر موثقة.
- [ ] شغّل مجموعات الاختبار المذكورة؛ سجل زمن المهمة ونوع الجهاز والنتيجة دون ادعاء ربحية.

**القبول:** الوحدات5 و18–24 و48–50 صادقة ومترابطة؛ training unavailable بسبب واضح أو job قابل للتتبع، لا اكتمال بمؤقت.

### المهمة 10 — الاستراتيجيات والاختبارات التاريخية والتاريخ (P1/P2)

**الملفات:** `services/nexus_api/routers/{backtest,strategies,trades}.py` (تتحقق الأسماء الفعلية من التقرير/الشجرة)، `services/nexus_ml/backtester.py`، `dashboard/src/components/windows/BacktestPanel.tsx`، `dashboard/src/components/research-lab/BacktestTable.tsx`، `dashboard/src/app/dashboard/history/page.tsx`؛ اختبارات `tests/test_api/test_backtest_sources.py` و`test_backtest_authorization.py` و`tests/test_ml/test_walk_forward_validation.py`؛ جديد `tests/test_api/test_trade_filter_consistency.py` و`dashboard/tests/history-csv.test.mjs`.

**العقد:** ثلاث وظائف مسماة بوضوح: تجميع صفقات مغلقة، أهلية بيانات، محاكاة استراتيجية على شموع. لا عرض وظيفة على أنها الأخرى. أي محاكاة تحتاج strategy_version وdataset_hash وas_of وسجل تكاليف وافتراضات التنفيذ.

- [ ] اختبر publication_time/available_at وعدم استخدام المستقبل، شمعة الإشارة مقابل شمعة التنفيذ، spread/commission/slippage، baseline، فصل تدريب/تحقق/اختبار زمني.
- [ ] ثبّت المحرك الموجود قبل توصيل UI؛ إن لم يغَطّ متطلبات محاكاة الشموع، يفصل بناء المحرك كمشروع فرعي معتمد، وتبقى الواجهة «أهلية فقط» دون ادعاء اكتمال.
- [ ] اختبر صفر صفقات، عينة صغيرة، خسائر فقط، drawdown، بيانات ناقصة، وتغير إعدادات/بصمة بعد التشغيل؛ التقرير القديم يبقى مرتبطًا بنسخته.
- [ ] تحقق أن symbol/account/date/timeframe filters مشتركة بين جدول التاريخ والإحصاءات وCSV. اختبر quotes/comma/newline وصيغ Excel الخطرة في CSV، والتصفح وتحديد نطاق التصدير صراحة.
- [ ] ResearchCycle/Reevaluate/Activate لا تُجرّب على الإنتاج؛ fixture أو بيئة معزولة دون منفذ تداول. نجاح تحليل ليس موافقة تفعيل.
- [ ] شغّل الاختبارات المذكورة؛ قارن تشغيلين مطابقين للحصول على نتيجة قابلة للتكرار، وتقرير تكاليف ظاهر في الواجهة.

**القبول:** يغلق جزء backtest من GAP-01 فقط عندما توجد محاكاة مستوفية فعلًا، وإلا يصنف «خارج نطاق الإصلاح/مشروع فرعي». الوحدات16–17 و19 و25 و43–44 لا توهم بوظائف غير منفذة.

### المهمة 11 — تنظيم الواجهات والتكرار وإمكانية الوصول (P1)

**الملفات:** `dashboard/src/app/dashboard/{layout,page}.tsx`، `dashboard/src/app/dashboard/settings/page.tsx`، `dashboard/src/components/settings/SourceConnectionManager.tsx`، `dashboard/src/components/progress/ProgressCell.tsx`، `dashboard/src/components/audit/AuditProgressView.tsx`، `dashboard/src/app/progress-state/route.ts`، `services/nexus_api/routers/audit_progress.py`، المكونات المحددة باللقطات الأصلية.

**العقد:** نفس القوائم الرئيسية، RTL/dark متسقان، tab نشط واضح مع أيقونة ونص، القوائم داخل viewport، لا حقول مكررة لنفس المعنى. نسبة الخطة ليست نسبة صحة النظام.

- [ ] أصلح الأبيض والتباين وقص user menu وجدول المصادر وأزرار الإجراءات وعناوين الرسوم؛ اختبر عروض360 و768 و1280 و1920 بتمرير ولوحة مفاتيح وfocus واضح.
- [ ] عرف أولوية إعداد ticker/الصوت: افتراضي عام ثم تجاوز شخصي موضح؛ لا تحفظ المسودات الداخلية بواسطة زر عام يوحي بعكس ذلك.
- [ ] افحص tabs المخفية التي تبقى mounted؛ قِس polling/اشتراكات WS قبل تغييرها، ثم امنع العمل المكرر دون فقد المسودة. لا ادعاء تحسن أداء بلا قياس.
- [ ] متابعة التطوير تعرض planned/implemented/tested/blocked منفصلة؛ علامة الإنجاز لا تستنتج من اسم ملف أو progress قديم. عرض «file_too_large» مع آلية دليل آمنة لا فشل عام.
- [ ] افحص حماية /progress-state ضد الوصول المجهول وتسريب مسارات/أسرار؛ لا تعرض مخططات التقدم كاعتماد مالي.
- [ ] أعد اختبار insertBefore في ملف متصفح نظيف ثم مع ترجمة المتصفح؛ افحص DOM غير صالح ومفاتيح القوائم وتدخل الترجمة قبل اختيار الإصلاح. لا monkey-patch لـNode.insertBefore لإخفاء الخطأ.
- [ ] ميز نوع حساب الوسيط عن وضع التطبيق PAPER/LIVE؛ badge ثابت DEMO ليس دليل نوع الحساب. لا تبديل LIVE في الاختبار المرئي.

**القبول:** يغلق UX-01 وUX-03 وUX-04 وUX-05 وUI-07 وUX-09 بالصور واختبارات وصول مناسبة؛ لا قص للإجراءات ولا labels متناقضة. أي تغيير منتج غير محسوم يعرض للمستخدم قبل التنفيذ.

### المهمة 12 — أمن وسلامة ثم إعادة قبول كاملة (P0 للإطلاق)

**الملفات/المخرجات الجديدة:** `project_audit/remediation-20261021/ACCEPTANCE_MATRIX.md`، `ISSUE_REGISTER.md`، `API_RESULTS.md`، `TEST_RESULTS.md`، `FINAL_REPORT_AR.md`، `screenshots/`؛ تحديث بيانات لوحة الاختبار المنفصلة فقط بعد نتائج حقيقية.

**العقد:** صف لكل وحدة من52 وصف لكل ملاحظة من20؛ كل حالة closed معها اختبار ودليل. أي route/tab جديد يكتشف أثناء الإصلاح يضاف للنطاق ولا يُختزل عدد الحالات.

- [ ] اختبر login/me/session-expiry/logout/bootstrap/password-wrong في قاعدة اختبار؛ فرّق فشل المصادقة عن توقف data؛ لا تغيير بيانات المستخدم الحقيقي.
- [ ] اختبر roles وownership والقراءة/التعديل/التصدير وWS؛ نفّذ اختبارات `tests/test_api/` و`tests/test_data/` و`tests/test_risk/` و`tests/test_executor/` ضد fixtures، لا على حساب حقيقي. الأزرار الخطرة تختبر بالمحاكاة/بيئة disposable فقط.
- [ ] شغّل `.venv\Scripts\python.exe -m pytest tests -q` مع حفظ ملخص passed/failed/skipped وأسباب skip. لا تدّع suite كاملة إن توقف التنفيذ أو نقص متطلبات.
- [ ] من dashboard: `node --experimental-strip-types --test tests/*.test.mjs` و`node node_modules/typescript/bin/tsc --noEmit` و`node node_modules/next/dist/bin/next build`. البناء يحتاج .next منفصلًا عن خادم dev أو نافذة صيانة منسقة؛ لا تمسح دليل المستخدم لحل build.
- [ ] مرر الواجهات أمام المستخدم بالترتيب الأصلي52: افتح وانتظر وافحص ومرّر واختبر القوائم والبحث والجدول والأزرار الآمنة. لقطة لكل مشكلة باسم المسار/التاب/UTC، مع حفظ حالات النجاح المهمة أيضًا.
- [ ] التقط Console وHTTP وWS بوسيلة متاحة فعلًا؛ إن تعذرت HAR اذكر أن الإثبات من سجلات gateway، ولا تسمّه مراقبة شبكة كاملة. تحقق من عدم وجود أسرار بالأدلة.
- [ ] أعد تجربة مستخدمين وحفظ/refresh/restart وجلب حقيقي محدود وفتح شهادة جودة مطابقة البصمة وتنزيل جديد، ثم راقب الاستقرار30دقيقة.
- [ ] أعد التقرير: ما أصلح، ما اختبر، ما فشل، ما تعذر وسببه، والمتطلبات الخارجية. احفظ أمر تشغيل/إيقاف/استرداد الخدمات المملوكة دون استعادة قاعدة المستخدم تلقائيًا.

**القبول:** لا P0/P1 مؤكد مفتوح داخل النطاق الموافق عليه؛ الملاحظات المؤجلة صريحة، لا تحويلها لنجاح. اكتمال زيارة52 ليس52اجتيازًا. التدريب الجيد أو التشغيل المستقر لا يعتمدان التداول الحقيقي.

## مصفوفة إغلاق الملاحظات العشرين

|المعرف|المهمة المالكة|الحالة (محدّثة بعد إغلاق المهام 1–3 يوم 2026-10-21)|
|---|---|---|
|UI-01|2|**مغلق** — بانر Checking + تفصيل صريح، مثبت متصفحياً (t2-01/t2-03/t3v-01)|
|UI-02|3|**مغلق (إعادة تحقق)** — Tilt UNKNOWN في المتصفح؛ تنبيه: الخادم يختلق "normal" مع available:false (باقي موثق)|
|UI-03|3|**مغلق (إعادة تحقق)** — رسائل غير قابل للتأكيد + عدّادات —، مطابق مع /api/positions (t3v-03)|
|UI-04|3|**مغلق** — unknown/None حياً في API والواجهة (t3-01)|
|UI-05|3|**مغلق** — ترويسة — + métricas incompletas (t3-02)|
|API-01|2–3|**مغلق (إعادة تحقق)** — 8 مسارات: 502 upstream/404 route/401 صريح؛ candles محمي بالمصادقة|
|UX-01|8،11|مفتوح|
|UX-02|5|مفتوح|
|AI-01|8|مفتوح|
|UI-06|3،10|**إعادة تحقق ناجحة** — زر حقيقي → 0 صفقات → شارة بيانات غير كافية بلا تصنيف سلبي (t3v-05)؛ envelope الخادم الصفائي يبقى لـ Task 10|
|UX-03|11|مفتوح|
|DATA-01|5|مفتوح|
|UX-04|11|مفتوح|
|UX-05|11|مفتوح|
|UI-07|11|مفتوح|
|UX-06|7|مفتوح|
|UX-07|7|مفتوح|
|GAP-01|7،10|فلاتر إصلاح؛ محرك شموع قد يحتاج مشروعًا فرعيًا|
|UX-08|8|مفتوح|
|UX-09|11|مفتوح|

## تغطية الوحدات الـ52 دون إسقاط

|وحدات التقرير|التغطية|
|---|---|
|1 Overview|1–3،11–12|
|2 Positions و3 Risk|3،11–12؛ الأفعال المالية في العزل فقط|
|4 News و7–14 Fundamental|5،8،11–12|
|5 Agents و18 Console|2،9،12|
|6 Intelligence|3،8–9،12|
|15 LocalAI|8،11–12|
|16 Journal و17 Backtest|3،10،12|
|19 Strategies|9–10،12|
|20–24 Models/Compare و48–50 الصفحات المستقلة|9،11–12|
|25 History|10،12|
|26 General|4،11–12|
|27–31 Broker|4،6،12|
|32 Sources|5،11–12|
|33–37 Users/Roles/Ticker/Sound/Audit|4،5،11–12؛ التغييرات الحساسة في العزل|
|38 Development و47 Audit|11–12|
|39–42 Research datasets/cleaning/validation/provenance|6–7،12|
|43 Research strategies|8،10،12|
|44 Research backtests|10،12|
|45 Research news|5،12|
|46 Research artifacts|7،10،12|
|51 Shared|11–12|
|52 Authentication|1–2،12|

## تنسيق سجل التنفيذ الملزم

لكل task/issue: الحالة (لم يبدأ/جارٍ/نجح اختبارًا/فشل/متوقف خارجيًا/مؤجل معتمد)، الملفات، حساب الاختبار، input hash إن لزم، أمر الاختبار وexit code وملخصه، API ومخرجاتها المنقحة، رابط الدليل، وقتUTC، النواقص، وخطوة الرجوع الآمنة.

درجات القبول مستقلة: **تشغيل مستقر** بعدA، **بحث موثق** بعدB و8، **نماذج ومحاكاة مختبرة** بعدC، **قبول واجهات شامل ضمن النطاق** بعدD. لا توجد خانة قبول LIVE في هذه الخطة.

## التقدير والإدارة

لا وعد بإكمال المشروع كله خلال10دقائق أو قبل نفاد الرصيد. تقاس الدفعة بإغلاق مشكلة موثقة لا بعدد الوكلاء أو الملفات. البدء المقترح مباشرةً بالمهمتين2–3 بعد تثبيت regression للتشغيل في1؛ ثم حساب/توقيت/بيانات4–7. الاحتياج لمصدر أو موافقة خارجية لا يوقف إصلاح UI مستقلًا، لكنه يمنع اعتماد بياناته.

هذه خطة تنفيذ وليست سجل أعمال منجزة. عند نهاية كل دفعة يُحفظ checkpoint قابل للاستكمال؛ لا ضمان لاستمرار عمل المساعد إذا انتهى الرصيد.
