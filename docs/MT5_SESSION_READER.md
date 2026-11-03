# قارئ جلسات الوسيط — تشغيل للقراءة فقط

القارئ مؤشر، وليس روبوت تداول. لا يحتاج AutoTrading أو DLL أو WebRequest.
النسخة المصححة 1.01 تعالج ERR_MARKET_SESSION_INDEX (4307) كنهاية تعداد
الجلسات فقط، ولا تخفي بقية أخطاء المنصة. بعد استبدال ملف EX5، إذا استمر
ملف التصدير يحمل 4307، أزل مؤشر NexusSessionReader وحده ثم أعد إضافته إلى
المخطط؛ لا تحذف Expert أو تعِد تشغيل المنصة. استبدال الملف لا يثبت أن
النسخة المحملة في ذاكرة MT5 قد تغيرت؛ ملف التصدير الجديد هو دليل التشغيل.
تجميع الملف لا يثبت اتصال القارئ بمنصتك: يلزم إرفاقه مرة واحدة، ثم إبقاء
المنصة والمؤشر يعملان. التصدير كل 300 ثانية والاستيراد خلال دورة الجودة
كل 60 ثانية بعد ضبط المسارات.

## تشغيل القارئ داخل MT5

1. في MT5 افتح **File → Open Data Folder**، ثم `MQL5/Indicators`.
2. انسخ `mql5/Indicators/NexusSessionReader.ex5` من هذا المشروع إلى ذلك المجلد.
   المصدر `NexusSessionReader.mq5` متوفر أيضًا؛ لا تستبدل ملفًا موجودًا دون
   حفظه. إذا غاب EX5، اجمع المصدر في MetaEditor بـF7 وافحص سجل التجميع.
3. في Navigator اختر Refresh ثم اسحب **NexusSessionReader** من Indicators
   إلى مخطط الرمز. هذا لا يستبدل Expert على المخطط. لا تفعّل أي صلاحيات تداول.
4. اضبط `SymbolsCsv` بأسماء الوسيط الفعلية الموجودة في Market Watch مثل
   `XAUUSD` أو اسم ذي لاحقة، لا أسماء مفترضة. يرفض القارئ اختيار رموز جديدة
   تلقائيًا. حدد حتى 32 رمزًا بفواصل، ودون تكرار.
5. ابقِ `ExportEverySeconds=300`، واسم خرج فريدًا لكل قارئ/خادم. لا تشغّل
   نسختين تكتبان الملف نفسه. الاسم الافتراضي `nexus_sessions_v1.json`.

المكان المعتاد على هذا الجهاز:
`C:/Users/rd66/AppData/Roaming/MetaQuotes/Terminal/Common/Files/nexus_sessions_v1.json`.
المصدر الدقيق للمجلد هو `TERMINAL_COMMONDATA_PATH` في MT5، ثم `Files`، وليس
مجلد البيانات الخاص بحساب واحد. عند الخطأ افحص Experts/Journal. لا يحذف القارئ
ملفًا صالحًا عمدًا عند خطأ الاستبدال؛ يسجل الخطأ، وتمنع الصلاحية استعماله للأبد.

## سياسة الهوية والساعة والعطلات

ابدأ من `config/broker_calendar.example.json` وانسخه إلى ملف محلي باسم
`config/broker_calendar.local.json`. المثال معطل ولا يحتوي عطلات أو ساعة معتمدة.

- `expected_server`: الاسم المطابق لحقل server في ملف المنصة.
- `symbol_map`: الاسم المنطقي للمشروع إلى اسم الوسيط الفعلي، مثل XAUUSD إلى
  الاسم المكتوب فعلًا في `SymbolsCsv`.
- `clock_evidence`: اتركه null إلى أن يتوفر مرجع رسمي لساعة الوسيط يغطي
  الفترة. لا تنسخ observed offset من الملف إلى سياسة تاريخية.
- `exceptions`: تظل [] إلى أن تتوفر مواعيد رسمية فعلية للعطلات/التغييرات.
  HTTPS source_uri يسجل مصدر اعتماد المشغّل؛ لا يتحقق النظام من صحة وثيقة
  على الإنترنت تلقائيًا، ولا يكفي وضع رابط لجعل المصدر رسميًا.

كل دليل ساعة يحتاج `evidence_id`, `source_uri`, `published_at`,
`effective_from`, `effective_to` بأوقات ISO واعية، ومعها أحد الخيارين فقط:
`timezone_name` (IANA موثقة) أو `utc_offset_seconds` لفترة ثابتة موثقة.
دليل offset ليس قاعدة دائمة لتوقيت صيفي أو لكل التاريخ.

استثناء عطلة يحتاج حقول الدليل نفسها مع `server`, `broker_symbols`,
`kind` بقيمة closed أو modified، و`quote_windows_utc` بعناصر start/end.
closed لا يحتوي نوافذ، وmodified يحدد نوافذ الأسعار الفعلية داخل الفترة.
التعارض أو غموض التوقيت يبقيان التصنيف unknown. جدولة اليوم لا تعيد كتابة
التاريخ؛ الفجوات السابقة لالتقاط القارئ تحتاج دليل استثناء رسمي مؤرخ يغطيها.

## التحقق قبل الربط

من جذر المشروع، PowerShell:

```powershell
.venv/Scripts/python.exe scripts/check_session_reader.py --export "C:/Users/rd66/AppData/Roaming/MetaQuotes/Terminal/Common/Files/nexus_sessions_v1.json" --policy "config/broker_calendar.local.json"
```

هذه الأداة لا تفتح MT5 ولا تكتب قاعدة البيانات. الناتج JSON بلا أسرار.
exit 0 يعني لقطة وهوية وساعة جاهزة للتحقق ضمن تغطيتها، لا شهادة تداول.
exit 2 يعني غير جاهز، مثل ساعة غير موثقة أو ملف قديم؛ exit 1 يعني خطأ تحقق.

بعد إنشاء الملفات الحقيقية، عرّف في إعدادات خدمة البيانات:

```text
NEXUS_MT5_SESSION_EXPORT_PATH=C:/Users/rd66/AppData/Roaming/MetaQuotes/Terminal/Common/Files/nexus_sessions_v1.json
NEXUS_BROKER_CALENDAR_POLICY_PATH=D:/Nexus-Trading-System-MT5/config/broker_calendar.local.json
```

يلزم إعادة تحميل خدمة البيانات مرة لقراءة متغيرات البيئة الجديدة، لا إعادة
تشغيل MT5. تعديل سياسة الملف لاحقًا يُقرأ كل دورة. لا تغير أسرار الحساب.
تحقق من `/health.quality_automation.calendar` ومن بطاقة مجموعة البيانات
في المختبر. إذا كان القارئ غير موصول أو الساعة غير موثقة فذلك ليس نجاحًا.

## حدود الأمان والتصنيف

- جلسات الأسعار تقود توقع الشموع؛ إغلاق تنفيذ التداول وحده لا يكفي.
- unknown لا يعني فساد السعر ولا سوقًا مغلقًا؛ يستمر الإصلاح المحدود من MT5.
- الفترات المغلقة بدليل صالح لا تحتاج شموعًا اصطناعية.
- الأصل المعزول يظل محفوظًا، ولا يحوّل التقويم سعرًا تالفًا إلى صالح.
- نافذة جلسات لا تضمن وجود tick لكل شمعة. صالحية اللقطة بحد أقصى 24 ساعة،
  ولا يستخدم النظام آخر لقطة بعد انقطاع/فقد الملف كدليل حالي صامت.
- إزالة المؤشر من المخطط توقف التصدير. لا تحذف بيانات المشروع؛ أزل مسار
  التصدير من إعداد الخدمة عند تعطيل الربط عمدًا.

مراجع: [جلسات الأسعار](https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote)،
[جلسات التداول](https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade)،
[نقل ملف مشترك](https://www.mql5.com/en/docs/files/filemove).
