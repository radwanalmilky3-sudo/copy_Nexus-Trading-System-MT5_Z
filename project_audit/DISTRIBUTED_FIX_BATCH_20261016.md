# دفعة الإصلاحات الموزعة — 10 وكلاء (2026-10-16)

نفّذت هذه الدفعة تعديلات مباشرة في الملفات الحقيقية دون تشغيل المشروع أو الاختبارات أو البناء، ودون فتح قاعدة DuckDB الحية. نطاق الكتابة كان مفصولًا بين الوكلاء. الإجمالي: **100 ملف، ‎+4739/−1196 سطر** (git diff). التحقق المتاح كان ساكنًا فقط (`py_compile`/`compileall`/AST/JSON) لكل ملف معدَّل.

## الوكلاء ونطاقهم وما نُفِّذ

| الوكيل | النطاق | أبرز الإصلاحات |
|---|---|---|
| Hooke | `shared/` | استرداد Redis Streams المتوافق مع Redis 5 (XPENDING+XCLAIM مع fallback عن XAUTOCLAIM)، DLQ بمحاولات قصوى، هوية idempotency، إصلاح ConfigLoader (risk_rules.yaml، حقول الوكلاء المفقودة، أصول specs الحقيقية)، رفض فتح DuckDB للكتابة من ثانٍ افتراضيًا، إزالة `except: pass` الصامت في safety |
| Hume-Data | `services/nexus_data`, `scripts/apply_schema.py` | فحص اكتمال الشموع (لا شمعة قيد التكوين)، أعمدة provenance (source/quality/fetched_at)، مهمة backfill لكشف الفجوات وتجنّب التكرار، منع حذف WAL نهائيًا، ack صريح في مستهلك trade-close، make schema idempotent ببوابة تأكيد |
| Hume-API | `services/nexus_api` | إزالة استجابات 200 بقيم صفرية/فارغة عند فشل المصدر (502/503 fail-closed عبر 10+ موجّه)، GET /api/config/risk يقرأ من nexus-risk وقت التشغيل، PUT config تُعلن display_only بصدق، تأكيد حماية 41 Mutation + WS + `trading.view` على سوق/أخبار |
| Darwin | `nexus_executor`, `nexus_risk` | سر توقيع موافقة منفصل `NEXUS_RISK_APPROVAL_SECRET` (يتوزع على risk+executor فقط)، رفض التنفيذ عند انقطاع/تقادم لقطة الحساب، ربط الموافقة بعد تعديل الحجم/الانزلاق/الانتهاء، idempotency لكل آثار trade-close (SETNX)، PARTIAL fill بدل رفض مضلل |
| Banach | `services/nexus_ml` | إصلاح تسرب زمني في DL trader (normalizer على 80% الأولى + تحقق زمني)، توحيد التسمية عبر label_next_bar_direction في bootstrap_ensemble، قفل وظائف إعادة التدراك المتداخلة مع استرداد المعلّق، حارس مسار artifact (models_store فقط) لجميع تحميلات pickle/joblib، إثبات provenance للتنبؤات |
| Dalton | `dashboard/src` | إزالة flipsoptimistic لوضع LIVE/التداول الآلي (مزامنة من /api/system/mode بعد الرد + PIN)، رفض حالات "نجاح/صفر" المفبركة (LiveDecision، PLDashboard، Regime، RL، GenAI، settings)، UserMenu عبر ApiClient، ws-client متوافق مع مصافحة JWT的第一帧 |
| Hooke-Agents | `services/nexus_agents` | إزالة حدود ثابتة متعارضة من 6 ملفات prompt، ربط min_conviction/blackout/anti-tilt بالقيم الفعلية، انتقال `_consume_signals` إلى ack صريح + reclaim + DLQ، إصلاح `self.redis` المكسور في risk_manager (killing-breakers كانت ميتة)، circuit breaker وميزانية LLM per-cycle، fail-closed عند غياب الـLLM provider |
| Darwin-Feat | `nexus_features`, `nexus_monitor` | إصلاح أعمدة Ichimoku الموسومة خطأ، إخفاء NaN الإحماء كـregime متوسط، إزالة bfill النظر إلى المستقبل في correlation، حارس -inf في institutional features، ترتيب تسجيل مسار institutional قبل route shadowing، Sortino null+flag بدل صفر، تنظيف NaN من Prometheus، إخفاء توكن تليجرام من نصوص الأخطاء + rate-limit على المحاولات |
| Hume-News | `services/nexus_news`, notebooks 04/05 | حجب تسريب مفاتيح API من نصوص أخطاء URLs (safe_url في fetcher/calendar/adapters — الأسوأ كان يُحفظ في DuckDB source_fetch_runs)، مواءمة news_blackout_minutes=5 مع المُ enforce، collector يُعلن unavailable بدل ready فارغ، notebooks: ترتيب closed_at + تحويل PnL إلى عوائد صريحة لـQuantStats |
| منسق (هذا الدور) | `project_audit/` | توثيق هذه الدفعة وتحديث قائمة العمل المتبقية |

## ما لم يُنفَّذ عن قصد

- لا تشغيل/اختبار/بناء/اتصال شبكي/فتح قاعدة حية (قيد المستخدم الصريح).
- `NEXUS_INTERNAL_API_SECRET` للمصادقة الداخلية بقي كما هو؛ فصل توزيع الأسرار الكامل لم يُمدّ إلى بقية الخدمات (التوقيع فقط هو المنفصل الآن).
- `FILE_MANIFEST.tsv` و`COVERAGE.md` لم تُعاد مطابقتها صفًا بصف بعد هذه الدفعة (554 مسارًا) — يلزم جولة مطابقة منفصلة قبل إعلان اكتمال الأودت.
- اختبارات واجهة/بناء إنتاجي؛ قيود EPERM على المسار العربي في بيئات سابقة.

## مخاطر متبقية حرجة (للتذكير)

1. استرداد pending streams لم يُوصَل بعد بمهلة/ Politik استعادة تلقائية كاملة لكل المستهلكين المتبقيين (nexus_monitor وبعض WS).
2. البيئة النشطة Redis على القرص 5.0.14 — مسار fallback مُختبر ساكنًا فقط، لا على خادم حي.
3. لا شهادة أداء/ربحية للنماذج؛ الإصلاحات سلامة منهجية فقط.
4. المخطط: أعمدة provenance جديدة تُضاف تدريجيًا عند أول تشغيل لمالك البيانات؛ لا توجد تجربة backfill فعلية بعد.
5. الـdashboard أُصلح ساكنًا فقط؛ لازم typecheck/build عند السماح بمرحلة التحقق.
