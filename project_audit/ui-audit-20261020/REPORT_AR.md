# تقرير الفحص المرئي المباشر — Nexus

الجولة: 20 أكتوبر 2026. الأوقات في فهرس اللقطات UTC، من ملفات الأدلة المحفوظة أثناء هذه الجولة.

## الحكم النهائي

**انتهت زيارة 12 مسار Dashboard مكتشفًا؛ لم يجتز النظام اختبارًا وظيفيًا شاملًا، ولا يوجد اعتماد للتداول.** فُتحت التابات الرئيسية والفرعية الموثقة أدناه أمام المستخدم. توجد20ملاحظة بين أخطاء وحالات مضللة ونواقص، و8مسارات HTTP فاشلة مرصودة. الإصلاحات الإنتاجية خلال الجولة: **0**.

التوثيق:52وحدة تشمل صفحات وتابات وعناصر مشتركة وصف مصادقة لم يُختبر دخوله من جديد؛ لا تساوي52اختبارًا ناجحًا. حُفظت123لقطة، بعضها تحميل/تمهيد أو تكرار. الدليل المعتمد هو المحدد لكل نتيجة.

[لوحة التقدم المستقلة](http://127.0.0.1:4188/) · [فهرس اللقطات](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/SCREENSHOTS.tsv) · [سجل التقدم](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/state.json)

## المنهج وحدود الإثبات

- اتبعت مهارة product-design:audit: تصوير فعلي ثم ملاحظات مرتبطة بالدليل، مع فصل مراجعة الكود عن نتيجة التشغيل. أنشئت لوحة تقدم منفصلة، ولم تعدّل واجهة المنتج لهذا الغرض.
- ساعدت مراجعتان متوازيتان للقراءة فقط في مطابقة React/Python؛ لا ادعاء بتشغيل15أو30وكيلًا.
- حساب الموقع ridwan؛ الحساب المحفوظ5091125 علىOneRoyal-Server. اتصال قراءةMT5 مطابق في تاب الوسيط؛ لا تبديل حساب أو أوامر أو تفعيل تداول.
- اختُبرت الملاحة والتفاصيل والبحث والتصفية والترتيب والتمرير حسب كل وحدة. لا يمكن إثبات صحة النتائج الممتلئة من جدول فارغ أو خدمة متوقفة.
- أعادت قراءة Console في محطات متعددة قائمة خالية. لا يثبت ذلك خلو التطبيق من الأخطاء. لم تتوفر أداةNetwork/HARكاملة؛ حالاتHTTPمن سجلgatewayومطابقة الراوترات، وليست ادعاء مراقبة كل طلب أوWS.
- نقر بعض روابط القائمة لم ينقل عبر أداة المتصفح، لكن فتح المسار مباشرة نجح. قد يكون قيدًا بالأداة؛ لا نصنفه خطأمنتج مؤكدًا. أخطاءselectorليست أخطاءمنتج.
- حدثت مهلة عند توسيع جدولالتطوير؛ استُعيد المتصفح. ليس كل ملف فرعي أو تركيب أصل×إطار×فترة مختبرًا بالكامل.
- لم ننفذ حذفًا أو إعادةتعيين كلماتسر أو صلاحيات أوglobalSaveأوKill/ResetDayأوTrainأوActivateأوResearchCycleأوإغلاق/تعديلصفقة. لم تُحذف شموع أو تُولد أسعارلسدالفجوات.
- LocalAIأرسل سؤال شرح محليًا وقد يكتب سجل تحليل؛ Backtestجمع الصفقات الموجودة وقد يحدثcache، لا محاكاة علىشموع ولا أوامرتداول. اختبارالصوت محلي؛ لا إثباتسمعي بأدواتنا.

## أهم الأولويات

1. صدق الحالة: unavailable/stale/loading لا تتحول إلىصفر أوneutral أوnormal. أصلحPositions وTilt وCrossAsset وBacktestأولًا.
2. أصلحtrade-memory/metrics404، وافحص مصادقةcandles401. افصل توقفrisk/ML/agentsالمقصود بوضعالإعدادات عن تعطلdata. لا تُشغّلexecutorلتغيير لونالحالة.
3. عالجLocalAIConnectErrorبفحصreadinessمستقل. HTTPلمصدر اقتصادي لا يعني جاهزيةتحليلأوحداثة؛ خصوصًاhealth_onlyونتائجالاختباراتالمخزنة.
4. افصل نطاق الحساب عن الأرشيفالعام، ووضح دورdisabledفيالبحث. US10Yغيرالمختارليسشرطًا إلزاميًا.
5. وحّدdark/RTLواللغاتوالتباين، أصلح قصالقائمة وإجراءاتالجدول ورسومالتقدم.
6. قبل الاختبارالمالي: UTCتاريخي وجلسات/عطلاتمؤرخة، إتاحةas-of، baselineوتكاليف، ثمخارجالعينة. الارتباطوالأسبقية مرصودانلااعتمادتنبؤأوربح.

## سجل الملاحظات

|المعرف|الملاحظة|الدليل|
|---|---|---|
|UI-01|شعار جميع الأنظمة تعمل يظهر قبل اكتمال فحص الخدمات|09-trading-overview-top.png ثم 13-trading-health-details.png — تغيّر إلى أربع خدمات غير متاحة|
|UI-02|Tilt يظهر normal رغم أن مصدر Anti-tilt بلا بيانات|14-trading-risk-gateway-details.png|
|UI-03|الصفقات تعرض No open positions و0 رغم STALE وانتهاء مهلة المصدر|15-trading-positions-stale.png|
|UI-04|Cross-Asset يمنح 3/5 ويعرض NEUTRAL رغم no_data|21-trading-intelligence-top.png مع AX لحالة DXY وUS10Y|
|UI-05|Trade Memory يعرض undefined trades|22-trading-intelligence-middle.png|
|API-01|طلب /api/trade-memory/metrics غير موجود: HTTP 404|سجل nexus-api الحالي + مطابقة ملفات Python|
|UX-01|المحلل المحلي: تباين ضعيف في حقل السؤال وتصميم أبيض غير متسق|33-fundamental-local-ai.png|
|UX-02|صحة مصادر التحليل الأساسي تعرض رؤوس جدول فارغًا بلا حالة صف واضحة|25-fundamental-overview.png|
|AI-01|المحلل المحلي يرجع ConnectError عند سؤال فعلي|34-fundamental-local-ai-connect-error.png|
|UI-06|الاختبار التاريخي يصنف أداء صفر صفقات بأنه سلبي ومهمش بدل بيانات غير كافية|37-trading-backtest-zero-results.png|
|UX-03|إعدادات الشريط الأبيض تحجب قراءة الشريط العلوي وبعض الحقول ضعيفة التباين|51-settings-general-section-4.png و52|
|DATA-01|المصادر تعرض جاهز للتحليل رغم يتطلب إعدادًا أو health_only؛ النجاح المعروض اختبار محفوظ قديم|69-settings-sources.png و71 و72|
|UX-04|إجراءات جدول المصادر تتجاوز عرض الشاشة وتتطلب تمريرًا أفقيًا غير واضح|70-settings-source-search.png|
|UX-05|رسوم متابعة التطوير بعناوين متداخلة ومقصوصة|83-development-progress-top.png و84|
|UI-07|علامات مكتملة في متابعة التطوير مع نسب صفرية/جزئية تحتاج تعريفًا واضحًا|85-development-progress-table.png|
|UX-06|ملخص أرشيف عام صفر أو not-connected بجانب بيانات حساب فعلية|97-research-cleaning-current.png و102|
|UX-07|عرض الدليل ينقل إلى تاب التحقق ولا يفتح دليل الصف مباشرة|106-research-backtest-eligibility.png ثم107|
|GAP-01|فلاتر الأرشيف الإضافية غير مفعلة، والاختبار بالمختبر أهلية فقط|زر فلاتر يظهر إشعار عدم التفعيل؛106|
|UX-08|US10Y يظهر في السياق رغم أنه غير مختار وغير مطلوب حاليًا|105-research-correlation-rows.png|
|UX-09|قائمة المستخدم تتجاوز الحافة اليمنى وتقص نص إعدادات الحساب|125-shared-user-menu.png|

الأعداد ليست20انهيارًا أوثغرة. لم نعدإنتاجinsertBeforeالقديم؛ لا يعني إثباتزواله.

## طلبات API الفاشلة

|الطلب المرصود|الحالة|Python/React|التفسير|
|---|---|---|---|
|GET /api/agents/decision/XAUUSD|502|[services/nexus_api/routers/agents.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/agents.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|
|GET /api/ml/traders/autonomous/status|502|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|
|GET /api/ml/traders/status|502|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|
|GET /api/v2/market/candles|401|[services/nexus_api/routers/market.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/market.py)|رفضمصادقة؛ لا يثبت توقفMT5|
|GET /api/trade-memory/metrics|404|[dashboard/src/components/windows/GatewayDiagnostic.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/GatewayDiagnostic.tsx) — لاrouteمطابق|المورد الموجود /api/intelligence/trade-memory يحتاج مواءمةعقد|
|GET /api/ml/traders/mode|502|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|
|GET /api/risk/settings|502|[services/nexus_api/routers/risk.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/risk.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|
|GET /api/intelligence/institutional/XAUUSD|502|[services/nexus_api/routers/intelligence.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/intelligence.py)|upstreamغيرمتاح؛ بعضالخدماتمتوقف عمدًا|

[سجلgateway](D:/Nexus-Trading-System-MT5/data/backups/before_candle_clear_20261020_000307/table-ui-runtime.log). لا تُنشر أسرار. LocalAIConnectErrorمثبت بالواجهة دونstatusHTTPمؤكد عبرNetwork.

## جدول كل صفحة وتاب

التابات المحلية لهاURLواحد؛ لا نختلقhashغيرموجود. APIأدناه مطابقةللكود، والنجاحالفعلّي لا يُفترض إلا حيثنصت النتيجة.

### 1. Trading / Overview

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/SystemDiagnostic.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/SystemDiagnostic.tsx)<br>[dashboard/src/components/windows/GatewayDiagnostic.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/GatewayDiagnostic.tsx)<br>[dashboard/src/components/windows/LiveChart.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/LiveChart.tsx)<br>[dashboard/src/components/windows/PLDashboard.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/PLDashboard.tsx)|
|Python/المصدر|[services/nexus_api/routers/market.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/market.py)<br>[services/nexus_api/routers/performance.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/performance.py)<br>[services/nexus_api/routers/risk.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/risk.py)<br>[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)|
|API|GET /api/performance*; /api/v2/market/candles; /api/risk/settings; /api/ml/traders/status|
|نتيجة المتصفح|أولًا All systems operational ثم أربع خدمات offline؛ PnL incomplete؛ تشخيص ذاكرة 404|
|الاختبارات المنفذة|فتح التشخيص والتفاصيل والتمرير نجح؛ Console المسجل فارغ|
|الأخطاء والنواقص وحدودالاختبار|تصحيح حالة التحميل؛ تفريق 401 عن تعطل الخدمة؛ عدم اعتبار الرسم الخارجي أسعار تنفيذ MT5|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[09](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/09-trading-overview-top.png) — 2026-10-20T20:15:28.635Z<br>[10](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/10-trading-overview-bottom.png) — 2026-10-20T20:15:29.184Z<br>[11](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/11-trading-overview-lower.png) — 2026-10-20T20:16:20.534Z<br>[12](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/12-trading-overview-end.png) — 2026-10-20T20:16:21.131Z<br>[13](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/13-trading-health-details.png) — 2026-10-20T20:16:37.538Z<br>[14](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/14-trading-risk-gateway-details.png) — 2026-10-20T20:17:00.949Z|

### 2. Trading / Positions

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/ActivePositions.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/ActivePositions.tsx)|
|Python/المصدر|[services/nexus_api/routers/positions.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/positions.py)<br>[services/nexus_api/websockets/positions.py](D:/Nexus-Trading-System-MT5/services/nexus_api/websockets/positions.py)|
|API|GET /api/positions; WS /ws/positions|
|نتيجة المتصفح|STALE/timeout مع No open positions و0|
|الاختبارات المنفذة|العرض فُحص؛ لا صفقات متاحة للاختبار|
|الأخطاء والنواقص وحدودالاختبار|لا يجوز استنتاج صفر صفقات من تعذر القراءة؛ close/modify لم يُنفذا|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[15](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/15-trading-positions-stale.png) — 2026-10-20T20:17:57.825Z|

### 3. Trading / Risk

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/RiskMonitor.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/RiskMonitor.tsx)<br>[dashboard/src/components/windows/ActivePositions.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/ActivePositions.tsx)|
|Python/المصدر|[services/nexus_api/routers/risk.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/risk.py)|
|API|GET /api/risk/settings; GET /api/positions|
|نتيجة المتصفح|UNKNOWN OFFLINE؛ عناصر سفلية/شريط صفقات مقصوصة في العرض الحالي|
|الاختبارات المنفذة|فتح وscroll؛ تعذر فحص القيم الحية|
|الأخطاء والنواقص وحدودالاختبار|reset-day/تعديل الحدود متروكة عمدًا؛ إعادة اختبار التخطيط على مقاسات متعددة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[16](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/16-trading-risk.png) — 2026-10-20T20:17:59.354Z<br>[17](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/17-trading-risk-end.png) — 2026-10-20T20:18:09.803Z|

### 4. Trading / News

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/news|
|نتيجة المتصفح|أخبار وتقويم فارغان؛ safety unknown|
|الاختبارات المنفذة|فلتر High جُرّب والتمرير|
|الأخطاء والنواقص وحدودالاختبار|اختبار بيانات أخبار فعلية وإتاحة المصدر|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[18](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/18-trading-news-high-filter.png) — 2026-10-20T20:18:25.919Z|

### 5. Trading / Agents

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/agents.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/agents.py)|
|API|GET /api/agents/status; WS /ws/agents|
|نتيجة المتصفح|offline و0/13؛ graph يعرض الوكلاء|
|الاختبارات المنفذة|تمرير المخطط أعلى وأسفل|
|الأخطاء والنواقص وحدودالاختبار|لا تشغيل للوكلاء أو تدريب أثناء الجولة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[19](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/19-trading-agents.png) — 2026-10-20T20:19:33.179Z<br>[20](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/20-trading-agents-lower.png) — 2026-10-20T20:19:47.184Z|

### 6. Trading / Intelligence

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/TradeMemoryPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/TradeMemoryPanel.tsx)<br>[dashboard/src/components/windows/CorrelationMatrix.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/CorrelationMatrix.tsx)<br>[dashboard/src/components/windows/ModelsByRegime.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/ModelsByRegime.tsx)|
|Python/المصدر|[services/nexus_api/routers/intelligence.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/intelligence.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)|
|API|GET /api/intelligence/{quality,cross-asset,trade-memory,correlation,mtf-context/{symbol},institutional/{symbol},genai-brief}; /api/regime/current|
|نتيجة المتصفح|Cross-asset3/5 وNEUTRAL رغم no_data؛ undefined trades؛ institutional unavailable|
|الاختبارات المنفذة|فلاتر SESSION/SOURCE/REGIME وDirección/Régimen/Horas UTC/Thresholds و7d/30d جُرّبت|
|الأخطاء والنواقص وحدودالاختبار|Generate brief لم يُنفذ؛ معايرة عدم توفر البيانات؛ توحيد الرمز مع الحساب|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[21](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/21-trading-intelligence-top.png) — 2026-10-20T20:19:59.130Z<br>[22](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/22-trading-intelligence-middle.png) — 2026-10-20T20:20:00.548Z<br>[23](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/23-trading-intelligence-bottom.png) — 2026-10-20T20:20:01.064Z<br>[24](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/24-trading-intelligence-filters.png) — 2026-10-20T20:21:06.536Z|

### 7. Trading / Fundamental / Overview

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|تحليل غير متاح؛ صحة المصادر رؤوس جدول فارغة|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[25](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/25-fundamental-overview.png) — 2026-10-20T20:21:15.579Z|

### 8. Trading / Fundamental / Macro

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[26](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/26-fundamental-macro.png) — 2026-10-20T20:21:26.362Z|

### 9. Trading / Fundamental / Monetary

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[27](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/27-fundamental-monetary.png) — 2026-10-20T20:21:27.036Z|

### 10. Trading / Fundamental / Cross-assets

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[28](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/28-fundamental-cross-assets.png) — 2026-10-20T20:21:27.798Z|

### 11. Trading / Fundamental / Geopolitics

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[29](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/29-fundamental-geopolitics.png) — 2026-10-20T20:21:44.050Z|

### 12. Trading / Fundamental / Flows

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[30](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/30-fundamental-flows.png) — 2026-10-20T20:21:44.770Z|

### 13. Trading / Fundamental / News & Calendar

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|عدم توفر معلن؛ لا تحليل موثوق ظاهر|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[31](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/31-fundamental-news-calendar.png) — 2026-10-20T20:21:45.836Z|

### 14. Trading / Fundamental / Learning

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)<br>[dashboard/src/components/fundamental](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/{gold/overview,sources/health,assets/{asset}/latest,lineage/{asset},outcomes/{asset},news}|
|نتيجة المتصفح|نص توضيحي فقط؛ لا نتائج تدريب|
|الاختبارات المنفذة|فتح التاب وفحص الأقسام؛ في الأخبار بحث ذهب ثم مسح البحث|
|الأخطاء والنواقص وحدودالاختبار|مراجعة source health وحالة آخر تحديث؛ النتائج الممتلئة غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[32](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/32-fundamental-learning.png) — 2026-10-20T20:21:46.665Z|

### 15. Trading / Fundamental / Local AI

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/fundamental/LocalAIAnalystPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental/LocalAIAnalystPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|POST /api/fundamental/local-ai/analyze|
|نتيجة المتصفح|سؤال فعلي أعاد المحلل المحلي غير متاح: ConnectError|
|الاختبارات المنفذة|إدخال سؤال شرح غير تنفيذي والنقر حلل؛ فشل الأداة موثق|
|الأخطاء والنواقص وحدودالاختبار|إصلاح اتصال المحلل وإظهار readiness؛ ليس فشلًا مثبتًا لنموذج التداول؛ تباين السؤال ضعيف|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[33](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/33-fundamental-local-ai.png) — 2026-10-20T20:22:23.816Z<br>[34](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/34-fundamental-local-ai-connect-error.png) — 2026-10-20T20:23:15.881Z|

### 16. Trading / Journal

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/TradeJournal.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/TradeJournal.tsx)|
|Python/المصدر|[services/nexus_api/routers/intelligence.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/intelligence.py)|
|API|GET /api/intelligence/trade-memory|
|نتيجة المتصفح|رسالة عدم توفر واضحة|
|الاختبارات المنفذة|فتح وفحص؛ لا تعديل|
|الأخطاء والنواقص وحدودالاختبار|إعادة الاختبار بصفقات مسجلة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[35](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/35-trading-journal.png) — 2026-10-20T20:23:17.244Z|

### 17. Trading / Backtest

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/BacktestPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/BacktestPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/backtest.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/backtest.py)|
|API|GET /api/backtest/{strategies,summary}; POST /api/backtest|
|نتيجة المتصفح|0 trades؛ winrate/PF سلبي وSharpe marginal رغم عدم وجود عينة|
|الاختبارات المنفذة|تشغيل تجميع السجل؛ فلاتر LON/BUY ثم استعادة؛ تابات SESSION/STRATEGY/DIRECTION/HOUR|
|الأخطاء والنواقص وحدودالاختبار|هذا تجميع صفقات مغلقة وليس محاكاة استراتيجية على شموع؛ تصنيف insufficient data بدل سلبي|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[36](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/36-trading-backtest-form.png) — 2026-10-20T20:23:31.710Z<br>[37](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/37-trading-backtest-zero-results.png) — 2026-10-20T20:26:45.475Z|

### 18. Trading / Console

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard](http://localhost:3100/dashboard)|
|React|[dashboard/src/components/windows/AgentConsole.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/windows/AgentConsole.tsx)|
|Python/المصدر|[services/nexus_api/routers/agents.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/agents.py)<br>[services/nexus_api/websockets](D:/Nexus-Trading-System-MT5/services/nexus_api/websockets)|
|API|WS /ws/agents|
|نتيجة المتصفح|live idle 0msgs؛ انتظار نشاط|
|الاختبارات المنفذة|فلاتر All/Analysis/Debate/Decision/Management جُرّبت|
|الأخطاء والنواقص وحدودالاختبار|الاتصال بالقناة لا يثبت جاهزية خط الوكلاء أو وجود قرارات|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[38](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/38-trading-console.png) — 2026-10-20T20:26:53.729Z|

### 19. Strategies

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/strategies](http://localhost:3100/dashboard/strategies)|
|React|[dashboard/src/app/dashboard/strategies/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/strategies/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/strategies.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/strategies.py)<br>[services/nexus_agents/main.py](D:/Nexus-Trading-System-MT5/services/nexus_agents/main.py)|
|API|GET /api/strategies; GET /api/strategies/research/log|
|نتيجة المتصفح|offline؛ صفر استراتيجيات وسجل فارغ|
|الاختبارات المنفذة|كل فلاتر الحالة والترتيب + refresh؛ لا انهيار ظاهر|
|الأخطاء والنواقص وحدودالاختبار|لا يمكن اعتماد فراغ السجل مع تعذر الخدمة؛ ResearchCycle/Reevaluate/Activate لم تُنفذ|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[40](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/40-strategies-offline.png) — 2026-10-20T20:27:54.353Z|

### 20. Models / ML

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/models](http://localhost:3100/dashboard/models)|
|React|[dashboard/src/app/dashboard/models/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/models/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status|
|نتيجة المتصفح|Service unavailable؛ لا افتراض تدريب|
|الاختبارات المنفذة|فتح التاب؛ refresh ونهاية الصفحة|
|الأخطاء والنواقص وحدودالاختبار|النموذج والنتائج والتدريب غير متاحة للاختبار؛ الرسم ليس احتمالات انتقال مثبتة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[41](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/41-models-ml.png) — 2026-10-20T20:29:05.341Z|

### 21. Models / DL

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/models](http://localhost:3100/dashboard/models)|
|React|[dashboard/src/app/dashboard/models/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/models/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status|
|نتيجة المتصفح|Service unavailable؛ لا افتراض تدريب|
|الاختبارات المنفذة|فتح التاب؛ refresh ونهاية الصفحة|
|الأخطاء والنواقص وحدودالاختبار|النموذج والنتائج والتدريب غير متاحة للاختبار؛ الرسم ليس احتمالات انتقال مثبتة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[42](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/42-models-dl.png) — 2026-10-20T20:29:12.624Z|

### 22. Models / RL

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/models](http://localhost:3100/dashboard/models)|
|React|[dashboard/src/app/dashboard/models/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/models/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status|
|نتيجة المتصفح|Service unavailable؛ لا افتراض تدريب|
|الاختبارات المنفذة|فتح التاب؛ refresh ونهاية الصفحة|
|الأخطاء والنواقص وحدودالاختبار|النموذج والنتائج والتدريب غير متاحة للاختبار؛ الرسم ليس احتمالات انتقال مثبتة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[43](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/43-models-rl.png) — 2026-10-20T20:29:13.324Z|

### 23. Models / HMM

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/models](http://localhost:3100/dashboard/models)|
|React|[dashboard/src/app/dashboard/models/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/models/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/regime/current|
|نتيجة المتصفح|UNKNOWN و0% مع graph توضيحي|
|الاختبارات المنفذة|فتح التاب؛ refresh ونهاية الصفحة|
|الأخطاء والنواقص وحدودالاختبار|النموذج والنتائج والتدريب غير متاحة للاختبار؛ الرسم ليس احتمالات انتقال مثبتة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[44](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/44-models-hmm.png) — 2026-10-20T20:29:14.097Z|

### 24. Compare

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/model-comparison](http://localhost:3100/dashboard/model-comparison)|
|React|[dashboard/src/app/dashboard/model-comparison/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/model-comparison/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/comparison|
|نتيجة المتصفح|تعذر التحديث؛ leaderboard unavailable؛ منحنيات بلا بيانات مع نص Train models|
|الاختبارات المنفذة|فحص كامل الصفحة|
|الأخطاء والنواقص وحدودالاختبار|لا TrainAll؛ اختبار المقاييس عند عودة الخدمة؛ لا استنتاج عدم وجود تدريب|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[45](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/45-model-comparison.png) — 2026-10-20T20:29:41.772Z|

### 25. History

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/history](http://localhost:3100/dashboard/history)|
|React|[dashboard/src/app/dashboard/history/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/history/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/trades.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/trades.py)<br>[services/nexus_data/main.py](D:/Nexus-Trading-System-MT5/services/nexus_data/main.py)|
|API|GET /api/trades; GET /api/trades/stats|
|نتيجة المتصفح|0 سجلات؛ CSV معطل|
|الاختبارات المنفذة|مدد24H/1M/3M/All و1W الافتراضي؛ بحث XAUUSDs ومسحه|
|الأخطاء والنواقص وحدودالاختبار|CSV والترقيم ببيانات غير فارغة لم يُختبرا؛ مراجعة الكود: stats لا يرسل symbol مع مرشح الجدول|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[46](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/46-history-top.png) — 2026-10-20T20:30:03.211Z|

### 26. Settings / General

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/app/dashboard/settings/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/settings/page.tsx)<br>[dashboard/src/components/fundamental/NewsTickerControlPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/fundamental/NewsTickerControlPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/intelligence.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/intelligence.py)<br>[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)<br>[services/nexus_api/routers/regime.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/regime.py)|
|API|GET /api/intelligence/settings; /api/fundamental/settings/news-ticker; /api/regime/thresholds|
|نتيجة المتصفح|تعدد أقسام؛ حقول تشغيل كثيرة بلا قيمة؛ الشريط الأبيض يضعف قراءة الرأس والحقول|
|الاختبارات المنفذة|تمرير أقسام التشغيل/TradingCore/Risk/Signals/Models/Notifications/Correlation/Memory/Backtest/GenAI/Connection|
|الأخطاء والنواقص وحدودالاختبار|لم تُغير قيم أو SaveAll؛ قيم المخاطر الفعلية غير متاحة؛ تحقق صلاحية ونطاق وتعمير الحفظ قبل التنفيذ|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[47](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/47-settings-general-top.png) — 2026-10-20T20:30:41.482Z<br>[48](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/48-settings-general-section-1.png) — 2026-10-20T20:30:59.896Z<br>[49](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/49-settings-general-section-2.png) — 2026-10-20T20:31:00.680Z<br>[50](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/50-settings-general-section-3.png) — 2026-10-20T20:31:01.547Z<br>[51](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/51-settings-general-section-4.png) — 2026-10-20T20:31:02.380Z<br>[52](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/52-settings-general-section-5.png) — 2026-10-20T20:31:03.181Z<br>[53](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/53-settings-general-section-6.png) — 2026-10-20T20:31:04.058Z|

### 27. Settings / Broker / الوسطاء والحسابات

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/broker/BrokerSettingsView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/BrokerSettingsView.tsx)<br>[dashboard/src/components/settings/broker/controller.ts](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/controller.ts)<br>[dashboard/src/components/settings/broker/AssetDropDown.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/AssetDropDown.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_data/broker_settings_router.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_router.py)<br>[services/nexus_data/broker_settings_store.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_store.py)|
|API|GET /api/brokers/profiles; /accounts/{id}; /accounts/{id}/{symbols,events}; PUT settings/POSTsessions موجودة وغير منفذة|
|نتيجة المتصفح|OneRoyal وحسابان؛ المحفوظ5091125؛ نسخة12|
|الاختبارات المنفذة|قراءة الجداول والاختيار المحفوظ|
|الأخطاء والنواقص وحدودالاختبار|لم تُنشأ حسابات أو يبدل الحساب|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[55](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/55-settings-broker-loaded.png) — 2026-10-20T20:31:51.889Z|

### 28. Settings / Broker / الاتصال

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/broker/BrokerSettingsView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/BrokerSettingsView.tsx)<br>[dashboard/src/components/settings/broker/controller.ts](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/controller.ts)<br>[dashboard/src/components/settings/broker/AssetDropDown.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/AssetDropDown.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_data/broker_settings_router.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_router.py)<br>[services/nexus_data/broker_settings_store.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_store.py)|
|API|GET /api/brokers/profiles; /accounts/{id}; /accounts/{id}/{symbols,events}; PUT settings/POSTsessions موجودة وغير منفذة|
|نتيجة المتصفح|قراءة متطابقة للحساب5091125 وOneRoyal-Server|
|الاختبارات المنفذة|التحقق من اتصال MT5؛ قائمة2070 أصل|
|الأخطاء والنواقص وحدودالاختبار|ليست صلاحية تداول أو دليل تنفيذ|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[56](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/56-settings-broker-connection.png) — 2026-10-20T20:31:52.816Z|

### 29. Settings / Broker / الأصول

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/broker/BrokerSettingsView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/BrokerSettingsView.tsx)<br>[dashboard/src/components/settings/broker/controller.ts](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/controller.ts)<br>[dashboard/src/components/settings/broker/AssetDropDown.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/AssetDropDown.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_data/broker_settings_router.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_router.py)<br>[services/nexus_data/broker_settings_store.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_store.py)|
|API|GET /api/brokers/profiles; /accounts/{id}; /accounts/{id}/{symbols,events}; PUT settings/POSTsessions موجودة وغير منفذة|
|نتيجة المتصفح|6أصول؛ AUDUSDs تحليل و5معطلة|
|الاختبارات المنفذة|فتح DataGrid وبحث XAUUSDs أعاد أصل الذهب|
|الأخطاء والنواقص وحدودالاختبار|لم تتغير اختيارات أو تحفظ؛ يجب توضيح معنى معطل في نطاق البحث|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[57](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/57-settings-broker-assets.png) — 2026-10-20T20:32:06.838Z|

### 30. Settings / Broker / الجلسات والتوقيت

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/broker/BrokerSettingsView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/BrokerSettingsView.tsx)<br>[dashboard/src/components/settings/broker/controller.ts](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/controller.ts)<br>[dashboard/src/components/settings/broker/AssetDropDown.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/AssetDropDown.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_data/broker_settings_router.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_router.py)<br>[services/nexus_data/broker_settings_store.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_store.py)|
|API|GET /api/brokers/profiles; /accounts/{id}; /accounts/{id}/{symbols,events}; PUT settings/POSTsessions موجودة وغير منفذة|
|نتيجة المتصفح|6جداول أسبوعية UTC+3؛ حقول الانتقال الحقيقي فارغة وunknown|
|الاختبارات المنفذة|التمرير على كل الجداول والحقول ونص الدليل|
|الأخطاء والنواقص وحدودالاختبار|لم تُزامن/تعدل؛ تأكيدDemo السابق لا ينسخ تلقائيًا إلىالخادم الحقيقي|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[60](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/60-settings-broker-timing.png) — 2026-10-20T20:33:11.343Z|

### 31. Settings / Broker / الأدلة والسجل

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/broker/BrokerSettingsView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/BrokerSettingsView.tsx)<br>[dashboard/src/components/settings/broker/controller.ts](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/controller.ts)<br>[dashboard/src/components/settings/broker/AssetDropDown.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/broker/AssetDropDown.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_data/broker_settings_router.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_router.py)<br>[services/nexus_data/broker_settings_store.py](D:/Nexus-Trading-System-MT5/services/nexus_data/broker_settings_store.py)|
|API|GET /api/brokers/profiles; /accounts/{id}; /accounts/{id}/{symbols,events}; PUT settings/POSTsessions موجودة وغير منفذة|
|نتيجة المتصفح|12نسخة؛ JSON النسخة12؛ اختيار الصورة معطل|
|الاختبارات المنفذة|فتح النسخة والتمرير لنهاية السجل|
|الأخطاء والنواقص وحدودالاختبار|OCR/رفع صورة غير منفذ؛ لم تنشأ نسخة جديدة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[66](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/66-settings-broker-evidence.png) — 2026-10-20T20:33:46.727Z|

### 32. Settings / Sources

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/SourceConnectionManager.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/SourceConnectionManager.tsx)|
|Python/المصدر|[services/nexus_api/routers/fundamental.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/fundamental.py)|
|API|GET /api/fundamental/sources/manage|
|نتيجة المتصفح|25مصدر؛ 13اتصال سليم محفوظ،5إعداد،1معطل،12مهيأ؛ health_only أو missingconfig قد يحمل جاهز|
|الاختبارات المنفذة|بحث fred؛ فحص25صفًا؛ فتح نموذج إضافة وإلغاؤه|
|الأخطاء والنواقص وحدودالاختبار|اختبارات الاتصال القديمة ليست اختبارات حالية؛ لم ترسل مفاتيح أو تختبر مزودًا خارجيًا؛ الحفظ/الحذف/التفعيل غير مختبر|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[69](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/69-settings-sources.png) — 2026-10-20T20:34:27.284Z<br>[70](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/70-settings-source-search.png) — 2026-10-20T20:34:39.353Z<br>[71](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/71-settings-sources-section-1.png) — 2026-10-20T20:34:42.159Z<br>[72](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/72-settings-sources-section-2.png) — 2026-10-20T20:34:43.580Z<br>[73](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/73-settings-sources-section-3.png) — 2026-10-20T20:34:44.987Z<br>[74](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/74-settings-sources-section-4.png) — 2026-10-20T20:34:46.389Z<br>[75](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/75-settings-source-editor.png) — 2026-10-20T20:35:03.512Z|

### 33. Settings / Users / المستخدمون

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/AdminAlertsCenter.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/AdminAlertsCenter.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|GET /api/admin/{users,roles,audit}; GET /api/user/notification-preferences|
|نتيجة المتصفح|ridwan super_admin نشط|
|الاختبارات المنفذة|قراءة الجدول|
|الأخطاء والنواقص وحدودالاختبار|إضافة/حذف/تعطيل/كلمةسر لم تُنفذ|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[76](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/76-settings-users.png) — 2026-10-20T20:35:16.353Z|

### 34. Settings / Users / الأدوار والصلاحيات

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/AdminAlertsCenter.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/AdminAlertsCenter.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|GET /api/admin/{users,roles,audit}; GET /api/user/notification-preferences|
|نتيجة المتصفح|7أدوار محمية وبطاقات صلاحيات|
|الاختبارات المنفذة|فتح وقراءة|
|الأخطاء والنواقص وحدودالاختبار|ليست محرر صلاحيات؛ لم تمنح أي وصول|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[77](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/77-settings-roles.png) — 2026-10-20T20:35:25.859Z|

### 35. Settings / Users / شريط الأخبار

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/AdminAlertsCenter.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/AdminAlertsCenter.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|GET /api/admin/{users,roles,audit}; GET /api/user/notification-preferences|
|نتيجة المتصفح|أصول وقطاعات وأهمية وTTL وطرق عرض شخصية|
|الاختبارات المنفذة|التمرير لكل الحقول دون تغيير|
|الأخطاء والنواقص وحدودالاختبار|تداخل مع الإعداد العام؛ الحفظ الشخصي لم يُنفذ|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[78](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/78-settings-user-ticker.png) — 2026-10-20T20:35:26.664Z|

### 36. Settings / Users / التنبيهات والصوت

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/AdminAlertsCenter.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/AdminAlertsCenter.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|GET /api/admin/{users,roles,audit}; GET /api/user/notification-preferences|
|نتيجة المتصفح|TTS ولغة/مستوى/سرعة/تكرار/إقرار/كتم/هدوء|
|الاختبارات المنفذة|النقر اختبارالصوت محليًا دون تغير ظاهر بالواجهة|
|الأخطاء والنواقص وحدودالاختبار|لا إثبات سماعي من الأداة؛ لا حفظ أو كتم|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[80](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/80-settings-user-audio.png) — 2026-10-20T20:35:41.152Z|

### 37. Settings / Users / سجل النشاط

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/settings](http://localhost:3100/dashboard/settings)|
|React|[dashboard/src/components/settings/AdminAlertsCenter.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/settings/AdminAlertsCenter.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|GET /api/admin/{users,roles,audit}; GET /api/user/notification-preferences|
|نتيجة المتصفح|سجلاbootstrap/resetpassword سابقان ومعرف داخلي بدل الاسم|
|الاختبارات المنفذة|قراءة السجل|
|الأخطاء والنواقص وحدودالاختبار|سجل مختصر؛ ليس كل إجراءات النظام ممثلة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[82](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/82-settings-activity.png) — 2026-10-20T20:35:56.916Z|

### 38. متابعة التطوير

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/progress](http://localhost:3100/dashboard/progress)|
|React|[dashboard/src/app/dashboard/progress/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/progress/page.tsx)<br>[dashboard/src/components/progress/HierarchicalTable.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/progress/HierarchicalTable.tsx)<br>[dashboard/src/app/progress-state/route.ts](D:/Nexus-Trading-System-MT5/dashboard/src/app/progress-state/route.ts)|
|Python/المصدر|لا Python لهذا المورد؛ project_audit/DASHBOARD_STATE.json|
|API|GET /progress-state|
|نتيجة المتصفح|تحذير بيانات قديمة؛ نسب جزئية مع علامات مكتملة؛ رسوم بعناوين متداخلة/مقصوصة|
|الاختبارات المنفذة|تمرير الرسوم والجدول ونهايته؛ فتح مجموعات؛ حدثت مهلة أدوات عند توسع طويل|
|الأخطاء والنواقص وحدودالاختبار|ليس كل ملف فرعي مؤكد الاختبار؛ نسب خطة لا قياس جاهزية runtime؛ تحديث المورد لا يعيد احتساب العمل المنجز|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[83](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/83-development-progress-top.png) — 2026-10-20T20:37:27.526Z<br>[84](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/84-development-progress-charts.png) — 2026-10-20T20:37:34.923Z<br>[85](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/85-development-progress-table.png) — 2026-10-20T20:37:36.321Z<br>[86](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/86-development-progress-expanded.png) — 2026-10-20T20:37:53.468Z<br>[90](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/90-development-infrastructure-expanded.png) — 2026-10-20T20:39:16.690Z|

### 39. Research Lab / مصادر البيانات

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/{research-runs,research-analysis}; POSTresearch-market غيرمنفذ|
|نتيجة المتصفح|ستة أصول و2944شمعةM15؛ سجل منفصل للأصل والإطار|
|الاختبارات المنفذة|historical/live/unified فُتحت؛ تفاصيلسجل وبصمة واختيارالذهب|
|الأخطاء والنواقص وحدودالاختبار|لا جلب جديد بهذه الجولة؛ كل تراكيب6أصول×7أطر غير مختبرة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[91](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/91-research-datasets-top.png) — 2026-10-20T20:40:02.627Z|

### 40. Research Lab / التنظيف

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/datasets/quality-runs|
|نتيجة المتصفح|الذهب536صالحة،0غيرصالحة،0مكررة،5فواصل غيرمصنفة؛ لا أسعاربديلة|
|الاختبارات المنفذة|فتح البصمة والتمرير|
|الأخطاء والنواقص وحدودالاختبار|not-connected للأرشيف بجانب بياناتالحساب؛ لا إصلاح أسعار أو سد فجوة تلقائي مثبت|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[97](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/97-research-cleaning-current.png) — 2026-10-20T20:41:02.004Z|

### 41. Research Lab / التحقق

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/quality-runs|
|نتيجة المتصفح|6/6أصول بها شموع؛24فحص مراجعة؛ سلامة/عينات/إتاحة ناجحة؛ تاريخUTCوالجلسات والنشر مراجعة|
|الاختبارات المنفذة|كل صفوف فحوصالذهب وأسبابها|
|الأخطاء والنواقص وحدودالاختبار|لا اعتماد كامل أو نجاح مصطنع؛ المصدرالحالي أسبوعي فقط|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[99](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/99-research-validation-current.png) — 2026-10-20T20:41:17.837Z|

### 42. Research Lab / التتبع

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/datasets|
|نتيجة المتصفح|الذهب536إتاحةموثقة؛ publication_timeغيرموثق؛ الأرشيفالعام0|
|الاختبارات المنفذة|قراءة أول/آخرشمعة والبصمة والوقت|
|الأخطاء والنواقص وحدودالاختبار|وقت الجلب ليس وقت نشر تاريخي؛ الملخصعام خارج scope|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[102](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/102-research-provenance-current.png) — 2026-10-20T20:41:37.171Z|

### 43. Research Lab / الاستراتيجيات

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/strategies|
|نتيجة المتصفح|XAG/WTI/DXY/VIX ارتباط20/60/120 مرصود؛ الثقةوالتعارض غيرمعايرين؛US10Yغيرمتاح|
|الاختبارات المنفذة|قراءةكل الصفوف والأسباب|
|الأخطاء والنواقص وحدودالاختبار|هذا سياق رصد لا استراتيجية قابلةللتنفيذ؛US10Yغيرمختار؛ لاPredictiveLeadمعتمد|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[104](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/104-research-strategies-current.png) — 2026-10-20T20:41:56.567Z|

### 44. Research Lab / الاختبارات التاريخية

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/backtests|
|نتيجة المتصفح|أهليةمتوقفة0؛ لا ربح محسوب|
|الاختبارات المنفذة|زرعرضالدليل نقلإلىتابالتحقق|
|الأخطاء والنواقص وحدودالاختبار|يلزم baseline+costs+UTC+إتاحة؛ ليس backtester مكتملًا|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[106](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/106-research-backtest-eligibility.png) — 2026-10-20T20:42:11.904Z|

### 45. Research Lab / الأخبار

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/research-lab/news|
|نتيجة المتصفح|لا أخبارمطابقة؛ أولإتاحة غيرموثقة|
|الاختبارات المنفذة|فلتركلالأصول ثمإرجاعه والتمرير|
|الأخطاء والنواقص وحدودالاختبار|محتوىأخبارفعلي وتوثيقإتاحةلميتوفرا|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[108](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/108-research-news.png) — 2026-10-20T20:42:39.915Z|

### 46. Research Lab / المخرجات

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/research-lab](http://localhost:3100/dashboard/research-lab)|
|React|[dashboard/src/components/research-lab/ResearchLabShell.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchLabShell.tsx)<br>[dashboard/src/components/research-lab/DataSourcesWorkspace.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/DataSourcesWorkspace.tsx)<br>[dashboard/src/components/research-lab/ResearchEvidencePanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchEvidencePanel.tsx)<br>[dashboard/src/components/research-lab/ResearchNewsPanel.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/research-lab/ResearchNewsPanel.tsx)|
|Python/المصدر|[services/nexus_api/routers/broker_settings.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/broker_settings.py)<br>[services/nexus_api/routers/research_lab.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/research_lab.py)<br>[services/nexus_data/research_analysis.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_analysis.py)<br>[services/nexus_data/data_loader.py](D:/Nexus-Trading-System-MT5/services/nexus_data/data_loader.py)<br>[services/nexus_data/research_market.py](D:/Nexus-Trading-System-MT5/services/nexus_data/research_market.py)|
|API|GET /api/brokers/accounts/{id}/research-analysis; GET /api/research-lab/artifacts; GET /api/brokers/accounts/{id}/research-analysis/{report_id}|
|نتيجة المتصفح|4تقاريرحسابM15 ظاهرة؛الأرشيف50/115؛بصمات؛قائمةقديمهXAUUSD|
|الاختبارات المنفذة|تنزيل محفوظ نُقر؛ فتحبصمة؛ بحثM15؛زرالفلاتريعترف بعدمالتفعيل|
|الأخطاء والنواقص وحدودالاختبار|لمينشأتقريرجديد؛ ملفموجودفيDownloads لايثبتتنزيلجديدبهذهالنقرة؛ لا تفاصيلصف للأرشيف|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[110](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/110-research-artifacts-current.png) — 2026-10-20T20:42:58.277Z|

### 47. نتائج التدقيق

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/audit-progress](http://localhost:3100/dashboard/audit-progress)|
|React|[dashboard/src/components/audit/AuditProgressView.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/components/audit/AuditProgressView.tsx)<br>[dashboard/src/app/progress-state/route.ts](D:/Nexus-Trading-System-MT5/dashboard/src/app/progress-state/route.ts)|
|Python/المصدر|[services/nexus_api/routers/audit_progress.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/audit_progress.py)|
|API|GET /api/audit/progress; GET /progress-state|
|نتيجة المتصفح|223ملفًا مقروءًا؛ تقدم350/586=59.73% خطة وليستاختبارات؛ بعضالأدلةfile_too_large|
|الاختبارات المنفذة|التمرير فيجدولالأدلة ثمخارجهنهايةالخطة؛ إدخالبحثMT5ومسحه|
|الأخطاء والنواقص وحدودالاختبار|لم يُتحقق مستقلًامن محتوى223ملفًا؛ التحديث الآليلايساويإثباتصلاحية؛ حالةملفكبيرليستفشلواجهة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[114](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/114-audit-progress-top.png) — 2026-10-20T20:44:23.591Z<br>[115](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/115-audit-progress-bottom.png) — 2026-10-20T20:44:39.997Z<br>[116](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/116-audit-progress-filter.png) — 2026-10-20T20:44:48.664Z<br>[117](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/117-audit-progress-plan-end.png) — 2026-10-20T20:44:53.988Z|

### 48. ML Models

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/ml-models](http://localhost:3100/dashboard/ml-models)|
|React|[dashboard/src/app/dashboard/ml-models/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/ml-models/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status; POST /api/ml/traders/train غيرمنفذ|
|نتيجة المتصفح|Status unavailable وService unavailable؛Train معطل|
|الاختبارات المنفذة|فُتحالمسار وانتظرتحمّلهوفُحصتالنهاية|
|الأخطاء والنواقص وحدودالاختبار|تكرار وظيفيمعتاباتModels؛ لا تدريبأوتقييمفعلي|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[120](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/120-standalone-ml-loaded.png) — 2026-10-20T20:45:51.354Z|

### 49. Deep Learning

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/deep-learning](http://localhost:3100/dashboard/deep-learning)|
|React|[dashboard/src/app/dashboard/deep-learning/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/deep-learning/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status; POST /api/ml/traders/train غيرمنفذ|
|نتيجة المتصفح|Status unavailable وService unavailable؛Train معطل|
|الاختبارات المنفذة|فُتحالمسار وانتظرتحمّلهوفُحصتالنهاية|
|الأخطاء والنواقص وحدودالاختبار|تكرار وظيفيمعتاباتModels؛ لا تدريبأوتقييمفعلي|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[121](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/121-standalone-dl.png) — 2026-10-20T20:46:19.329Z|

### 50. Reinforcement Learning

|الحقل|التوثيق|
|---|---|
|الرابط|[/dashboard/reinforcement-learning](http://localhost:3100/dashboard/reinforcement-learning)|
|React|[dashboard/src/app/dashboard/reinforcement-learning/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/reinforcement-learning/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/ml.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/ml.py)<br>[services/nexus_ml/traders_api.py](D:/Nexus-Trading-System-MT5/services/nexus_ml/traders_api.py)|
|API|GET /api/ml/traders/status; POST /api/ml/traders/train غيرمنفذ|
|نتيجة المتصفح|Status unavailable وService unavailable؛Train معطل|
|الاختبارات المنفذة|فُتحالمسار وانتظرتحمّلهوفُحصتالنهاية|
|الأخطاء والنواقص وحدودالاختبار|تكرار وظيفيمعتاباتModels؛ لا تدريبأوتقييمفعلي|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[123](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/123-standalone-rl.png) — 2026-10-20T20:46:49.243Z|

### 51. العناصر المشتركة / Notifications وUserMenu

|الحقل|التوثيق|
|---|---|
|الرابط|كل Dashboard|
|React|[dashboard/src/app/dashboard/layout.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/layout.tsx)<br>[dashboard/src/components](D:/Nexus-Trading-System-MT5/dashboard/src/components)|
|Python/المصدر|[services/nexus_api/routers/notifications.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/notifications.py)<br>[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|قنوات الإشعارات ومستخدم الجلسة|
|نتيجة المتصفح|قائمةالإشعاراتliveبلاسجلات؛قائمةالمستخدممقصوصةعندالحافة|
|الاختبارات المنفذة|فتحوإغلاقالقوائم|
|الأخطاء والنواقص وحدودالاختبار|لم يُختبرlogoutأوالتبديلPAPER/LIVE؛ badgeDEMOثابتولايمثلنوعحسابMT5|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|[124](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/124-shared-notifications.png) — 2026-10-20T20:46:49.913Z<br>[125](D:/Nexus-Trading-System-MT5/project_audit/ui-audit-20261020/125-shared-user-menu.png) — 2026-10-20T20:46:55.586Z|

### 52. تسجيل الدخول / أول مستخدم

|الحقل|التوثيق|
|---|---|
|الرابط|[/login](http://localhost:3100/login)|
|React|[dashboard/src/app/login/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/login/page.tsx)|
|Python/المصدر|[services/nexus_api/routers/admin.py](D:/Nexus-Trading-System-MT5/services/nexus_api/routers/admin.py)|
|API|POST /api/v2/auth/login; GET /api/v2/auth/me; bootstrap|
|نتيجة المتصفح|لم تُنفذ جولة دخول جديدة؛الجلسةالحاليةاجتازتAuthGateفيالمسارات|
|الاختبارات المنفذة|مراجعةمصدريةفقط؛لاخروجمنحسابالمستخدم|
|الأخطاء والنواقص وحدودالاختبار|اختباردخول/فشلكلمةسر/استرداد/إنشاءأولمستخدممتبقٍببيئةاختبارمعزولة|
|الإصلاحات|لا إصلاح إنتاجي ضمن جولة التدقيق|
|اللقطات ووقتUTC|—|

## التكرارات والحقول غير الواضحة

- صفحاتML/DL/RLالمستقلةتكررModels؛ يفضّل مدخلواحد وصفحاتتفاصيل دونحالات تدريبمتعددة.
- ActivePositions وRiskMonitorوالساعاتمكررة. [dashboard/src/app/dashboard/page.tsx](D:/Nexus-Trading-System-MT5/dashboard/src/app/dashboard/page.tsx)يبقي التاباتmountedمعdisplay:none(سطر102)، فتستطيعeffectsالاستمرار. لم نقسعددمكررالطلبات، فلاادعاءقياسأداء.
- الشريطوالصوتعامّانفيGeneralوشخصيانفيUsers؛ يحتاجانشرحالأولويةوالنطاق. SaveAllلايحفظبالضرورةنماذجnestedالمستقلة.
- Strategiesالرئيسيةبايبلاينبحث، وStrategiesالمختبرسياقارتباط. BacktestTradingتجميعصفقات، وBacktestsResearchأهليةفقط؛ ليستمحركاتمتكافئة.
- Progressخطة، وAuditProgressخطةمعبصمات.59.73%ليستنسبةاختباراتالنظام.
- نسخة12تظهرAUDUSDsanalysisوخمسةdisabled. وجودالأصلواختيارهنفصلانعنإذنالتداول؛ يحتاجقرارمنتجصريححولمنعdisabledللبحث. لم نعدلالوضع.

## مراجعة كود تحتاج اختبارًا مستقلًا

لا تُحسب هذه كأخطاء جديدة مؤكدة بالمتصفح:

- Historystatsلايرسلsymbolوالجدوليرسله؛CSVيصدرالصفحةالحاليةويحتاجescaping.
- pollingالإعداداتقديستبدلمسودةغيرمحفوظة؛ حفظruntimeذوأثرعامويحتاجتعريفالاستدامةوالصلاحيات.
- مؤقتإنهاءالتدريببالمقارنة/النماذجلايثبتاكتمالjob؛GenAIقديحملdefaultsبدلrecords.
- /progress-stateراوترNextومصدرهملفلاPython. مراجعةتحكمبوصولجلسةمجهولةمتبقية؛ لااختراقأوبايباسمنفذ.
- اختبارHTTPللمصادرلايثبتوجودسلسلةالمؤشرالمطلوبةأوتحديثها.

## ما تحقق من العمل السابق وما بقي

**ظاهر الآن:** الوسيطوالحسابالمحفوظان،2070أداةMT5،pickerبثلاثةأعمدةوبحثالذهب،6أصولوجلساتها،نسخة12وسجل12حدثًا،أوضاعالمصادرالثلاثةوسجلعمليات،2944شمعةM15(558AUDUSDs+487DXYs+293VIXs+535WTIs+535XAGUSDs+536XAUUSDs)،ارتباط20/60/120،4تقاريرحساب،بصماتأدلة.

**غير مثبت من الواجهة وحدها:** اكتمالالتاريخ،سلامةMQLالثنائية،منعتسربلكلاستراتيجية،سدكلفجوةتلقائيًا،تدريبمربح،تنفيذحي،عزلمستخدمآخر،نجاحكلسويتاتسابقة. لم نعدتشغيلتلكالسويتاتهنا.

**بقي قبل قبول شامل:** إصلاحالأولويات؛ تشغيلالخدماتالمطلوبةفقطبقصد؛fixturesلصفقاتوأخبارونماذجوتصدير؛حساباختبارثانٍلعزلالملكية؛اختبارحفظثمrefresh/restartببيئةمعزولة؛UTCتاريخي؛baselineوتكاليف؛responsive/keyboard/a11yمخصص؛HAR/WSكامل؛إعادةاختبارinsertBeforeدونومعترجمةالمتصفح؛تراكيبأصل/إطاروالفروعالهرميةالمتبقية.

**المقترح:** دفعةإصلاحلصدقحالةالبياناتوربطAPIأولًا،ثمإعادةنفسخطواتالصورقبل/بعد. دونقوائمرئيسيةجديدةأوتفعيلتداوللتجاوزتحذير.

