# خطة تطوير خط بيانات NEXUS — النسخة 1.1 (2026-11-09)

> **هذه الوثيقة = الذاكرة الدائمة للتطوير.** تُحدَّث بعد كل مرحلة بإضافة
> الاثبات (لقطة مخرجات فعلية) وتحديث خانة الحالة، ثم تُرفع إلى GitHub.
> لا تُعلن مرحلة "مكتملة" بدون لقطة اثبات مسجّلة في هذا الملف.
> **v1.1:** دمج انتقائي لوثيقتَي المالك (أمر الوكيل + الخطة الشاملة 2.0)
> بعد تحقق ميداني من ادعاءاتهما في الكود — انظر "المراجعة الخارجية".

---

## قواعد التنفيذ

1. كل مرحلة: **الهدف → تعديلات الكود (ملفات محددة) → الاثبات المطلوب → نقطة التحقق → الاختبارات → الحالة**.
2. `GET` قراءة فقط؛ السحب يتم عبر مسار كتابة صريح مُسجَّل في `ingest_jobs`.
3. أي وقت مستورد **يُرفض بلا منطقة زمنية صريحة** (يُحوَّل إلى UTC كتابةً).
4. تعديلات الخدمة تُكتب أولاً، ثم تُفعَّل بإعادة تشغيل واحدة، ثم تُلتقط لقطة التحقق.
5. كل commit يحمل وصف التعديل، ويُدفع إلى `origin/main` فوراً (قاعدة ثابتة
   أكّدها المالك 2026-11-09: **الرفع التلقائي يبقى** — وثيقة أمر الوكيل
   ("لا push بدون موافقة") ملغاة في هذا الجانب وتحدد المحتوى التقني فقط).
6. migrations: additive/idempotent أولاً، backup + اختبار restore قبل التطبيق
   على قاعدة حية، وسجل migration id/version/checksum/rollback (انضباط مقبول
   من وثيقة الخطة الشاملة).

---

## المراجعة الخارجية (وثيقتا المالك 2026-11-09) — ما أُدمج وما رُفض

> تقييم بعد **تحقق ميداني من كل ادعاء في الكود أو المسبار** (لا قبول افتراضي).

### تحققات حاسمة

| الادعاء | الدليل الفعلي | الحكم |
|---|---|---|
| التصحيح يغيّر الصف بدل حفظ النسخة | `duckdb_store.py:613-615`: "updated **in place** with revision+1" — القيم القديمة تضيع | ✅ صحيح → `ohlcv_revisions` أُضيف للمرحلة 1 |
| حروف ticks ناقصة | جدول `ticks` = bid/ask/spread/timestamp **بالثوانٍ فقط** (لا time_msc/flags/volume_real) | ✅ صحيح → عقد ticks أُضيف للمرحلة 2 |
| ثوابت retention (7د ticks/365د ohlcv) | موجودة (`:36-38`) لكن `prune_old_data` (`:1681`) **لا يُستدعى في أي ملف** | ⚠️ خطر كامن: سياسة **غير مفعّلة** — تُوثَّق ولا تُفعَّل قبل قرار المالك |
| ملفات contracts/validators/session_calendar موجودة | كلها موجودة و`session_calendar.py` **مُوصَل فعلاً** (`main.py:391-402`) | ✅ إعادة استخدام لا بناء جديد |
| "MT5 يوفّر الوقت وفق UTC" | **المسبار E7 يدحضها**: `tick.time − now_utc ≈ +7167..7516 ث` (≈ +2h) | ❌ مرفوض — نحتفظ بـ`utc_offset_seconds` والوقت الخام معاً |
| `broker_instrument_map` كجدول جديد | القاموس (جدول 40) اسمه `broker.broker_symbols` | ❌ نستخدم اسم القاموس: `broker_symbols` |

### ما أُدمج (9 نقاط)

1. **`ohlcv_revisions`** append-only (old/new values + available_at + fetch_run) → المرحلة 1
2. **عقد ticks كامل**: `time_msc, flags, last, volume, volume_real` + مفتاح idempotent (feed+time_msc) → المرحلة 2
3. **نموذج الوقت** `known_at/available_at` صريح + مراجعات القيم الاقتصادية (actual/forecast/revision بـknown_at) → المرحلة 3
4. **story cluster**: إعادة النشر ≠ تأكيد مستقل (dedup قبل الربط) → المرحلة 3
5. **توثيق خطر الاحتفاظ**: `prune_old_data` غير مستدعى — لا يُفعَّل قبل موافقة صريحة → المرحلة 4
6. **بيانات التنفيذ** `history_deals/orders` (tickets/time_msc/commission/swap/profit) لحساب `cost_bps` فعلياً → المرحلة 5
7. **انضباط migrations** (additive/idempotent/backup/rollback) → قواعد التنفيذ #6
8. **فصل الحجم**: `tick_volume`/`real_volume`/`volume_type` مع إبقاء `volume` legacy دون تغيير معناه → المرحلة 2
9. **عتبات SLA بعد baseline** لكل رمز/فريم — لا أرقام عامة مخترعة → المرحلة 4

### ما رُفض أو أُجّل (بحجة)

- **ادعاء UTC** — مرفوض بالأرقام (E7). 
- **`broker_instrument_map`** — نستخدم اسم القاموس `broker_symbols`.
- **مرحلة الاكتشاف في الوثيقة** — منجزة أصلاً (E1–E8 + مسبار).
- **مشروط/ مؤجَّل (backlog):** أرشيف Parquet، Market Depth (`book_get`)،
  مطابقة feeds متعددة (`feed_reconciliation`)، `execution_quotes`، تعميم
  `asset_id/feed_id` متعدد الوسطاء — كلها مشروطة بوجود وسيط ثانٍ أو أرشيف
  فعلي أو تنفيذ حي. لا تدخل المراحل الحالية.

---

## سجل اللقطات المؤكدة — الحالة الحالية قبل التطوير (Evidence)

> هذه لقطات حقيقية جُمعت من الجهاز في 2026-11-08/09 وتُستخدم أساساً للمقارنة (Before).

### E1 — بنية `ohlcv` الفعلية (11 عموداً فقط)

```sql
-- duckdb_store.py:321-333
CREATE TABLE ohlcv (
  symbol, timeframe, open, high, low, close, volume,
  timestamp TIMESTAMPTZ, source, quality, fetched_at
)
```
**مفقود:** bar_open_utc, bar_open_server_time, utc_offset_seconds,
ask_*, spread_points, real_volume, session_code, row_checksum.

### E2 — حجم الفجوة: 8 جداول مقابل 251

```
duckdb_store.py: 8 CREATE TABLE (ticks, ohlcv, trades, positions, agent_logs,
  ohlcv_manifests, ohlcv_backfill_runs, symbol_property_snapshots)
NEXUS_Data_Dictionary_Reviewed.docx: 251 جدولاً مرقّماً
  broker.*=46 | market.*=14 (47-60) | context.*=19 (61-79)
  features.*=16 (111-126) | ml.*=20 (127-146) | execution.*=16 | risk.*=14 ...
```
**لا يوجد** features.* ولا ml.* ولا context.* ولا broker_symbols في DuckDB الفعلية.

### E3 — قدرات MT5 المهملة (grep دليل)

```
grep: copy_ticks|COPY_TICKS|book_get|history_deals  في services/  → No matches
```
- `mt5_worker.py:141` يبني dict الشمعة بـ(time,o,h,l,c,tick_volume) —
  **يهمل `spread` و`real_volume` الموجودين أصلاً في صف copy_rates**.
- جدول `ticks` (duckdb_store.py:312) يُملأ حياً فقط (`main.py:213`) — لا تاريخ.

### E4 — الأخبار غير مربوطة بالتدريب (grep دليل)

```
grep fundamental|news|calendar في bootstrap_ensemble.py → مطابقة واحدة = تعليق (سطر 185)
nexus_features/ = 12 ملفاً سعرياً فقط (volatility/trend/session/correlation/cross_asset...)
                  لا يوجد module للأخبار/التقويم
```
مصادر الأخبار الحالة كلها معطلة (من سجل run_out.log):
```
calendar_investing_fetch_error: 403 Forbidden
gnews_error: {"status":403} (مرتان)
newsapi_key not configured — skipping NewsAPI
gdelt_rate_limited
```

### E5 — قفل الكتابة يرفض بدل الانتظار (نص حر)

```
RuntimeError: DuckDB owner-store lock busy >60s (held by _exec) ?
  refusing to queue; the long operation must finish or be cancelled
  (duckdb_store.py:_execute_locked ~L1588)
```
أثر مباشر موثّق: طلبات 500 على `/api/data/ohlcv/...` أثناء دفعات كبيرة.

### E6 — فشل اتصال MT5 المتكرر (نص حر)

```
{"event":"startup.mt5_failed","exc_info":["TimeoutError","MT5 worker timed out"]}
{"symbol":"XAUUSD","tf":"M15","failures":20,"RuntimeError('MT5Connector is not connected')"}
```
**لا يعيد الاتصال تلقائياً بعد السقوط** (بوابة `if mt5.connected` في main.py ~680).

### E7 — مسبار القياس (خطوة صفر، read-only) — نتائج فعلية 2026-11-09

سكربت `scripts/probe_mt5_capabilities.py` (مسبار المالك، لا يكتب شيئاً)
اتصل بالطرفية مباشرة (`server: OneRoyal-Demo`) وأخرج لكل الرموز الـ14:

```
XAUUSD  digits=2 point=0.01 tick_size=0.01 tick_value=1.0   contract=100   profit=USD margin=USD offset_s=7167 ticks_7d=0       M1_7d=6886
XAGUSD  digits=3 point=0.001 ...               tick_value=5.0   contract=5000  profit=USD margin=USD offset_s=7274 ticks_7d=1374282 M1_7d=6882
BTCUSD  digits=2 ... tick_value=0.01 contract=1     profit=USD margin=USD offset_s=7300 ticks_7d=0       M1_7d=10076
ETHUSD  ...  contract=10    profit=USD margin=USD offset_s=7407 ticks_7d=2294243 M1_7d=9976
DXY     ...  contract=100   profit=USD margin=USD offset_s=7446 ticks_7d=173363  M1_7d=6269
EURUSD  ...  contract=100000 profit=USD margin=EUR offset_s=7460 ticks_7d=493393 M1_7d=7132
GBPUSD  ...  contract=100000 profit=USD margin=GBP offset_s=7471 ticks_7d=568016 M1_7d=0
USDJPY  ...  tick_value=0.6326711375427053 contract=100000 profit=JPY margin=USD offset_s=7479 ticks_7d=628947 M1_7d=893
USDCHF  ...  tick_value=1.2183087438018543 contract=100000 profit=CHF margin=USD offset_s=7492 ticks_7d=656667 M1_7d=903
AUDUSD  ...  contract=100000 profit=USD margin=AUD offset_s=7503 ticks_7d=392847 M1_7d=7140
USDCAD  ...  tick_value=0.7076339551077019 contract=100000 profit=CAD margin=USD offset_s=7509 ticks_7d=387633 M1_7d=7138
US30    digits=1 point=0.1 contract=1 profit=USD margin=USD offset_s=7516 ticks_7d=2086153 M1_7d=851
US500   digits=1 point=0.1 contract=1 profit=USD margin=USD offset_s=7171 ticks_7d=1746511 M1_7d=6886
WTI     digits=3 point=0.001 contract=1000 profit=USD margin=USD offset_s=7172 ticks_7d=1268371 M1_7d=0
```

**قراءات حاسمة:**
1. **offset_s ≈ 7167–7516 (≈ +2h)** — خادم أوروبي UTC+2؛ الإزاحة تتغيّر مع
   توقيت الصيف → `broker_server_time_offsets` إلزامي (المرحلة 1).
2. **ticks_7d: 12/14 رمزاً يملكون عمقاً هائلاً** (173 ألف – 2.29 مليون tick/7 أيام)
   → تجميع `bar_tick_aggregates` وAsk ممكن. **لكن XAUUSD=0 وBTCUSD=0** —
   تاريخ الـ ticks لهما لم يُنزَّل بعد في الطرفية → تُعلَّم `ask_source='unavailable'`
   ولا تُقدَّر، وتُعاد المحاولة بعد مزامنة الـ tick history.
3. **NOT FOUND: لا شيء** — أسماء الـ14 كلها دقيقة عند الوسيط → جدول
   `broker_symbols` يوثّق الربط (لا تطبيع مطلوب الآن).
4. **عملات مختلطة**: profit/margin ∈ {USD, EUR, GBP, JPY, CHF, AUD, CAD}
   → 8/14 رمزاً يحتاجون تحويل عملات (`fx_route`) لحساب الأرباح بالـ USD.
5. **M1_7d=0 لـ GBPUSD وWTI** و893-903 فقط لـ USDJPY/USDCHF — المزامنة
   الكسولة للـ M1 ناقصة لهذه الرموز (يُعالج بتمريرات الشفاء الحالية).
6. **الحجم**: ~1.4–2.3 مليون tick/7 أيام/رمز → 90 يوماً ≈ 30 مليون صف لرمز
   واحد → تقسيم شهري/منفصل لجدول الـ ticks قرار إلزامي (كما لاحظ المالك).

### E8 — نتائج الاستيراد الفعلية (Before للجودة)

```
import_symbol_metadata.py → captured=14 failed=0 (XAUUSD digits=2 contract=100 ...
  EURUSD contract=100000 ...)
XAUUSD/M1 90d → 26,230 شمعة (bf phase1) | XAUUSD/M1 الجمعة 6نوف → 1,374 شمعة (2s)
EURUSD/M1 provenance → 1,421 شمعة (6-7نوف) بعد أول مزامنة كسولة
12 رمزاً × M1 → 0 شمعة (مطابقة: الرمز غير متزامن التاريخ في ohlcv_range بلا إعادة)
BTCUSD/M1 → 10 شموع فقط
health → {"data_mode":"REAL_MT5","mt5":true}
القاموس: 251 جدولاً (data_dict.txt، 149,755 حرفاً)
```

---

## خارطة المراحل والحالة

| # | المرحلة | الحالة | لقطة الدليل |
|---|---------|--------|-------------|
| 0 | فصل القراءة/الكتابة + ingest_jobs + طابور كتابة واحد | ⬜ لم تبدأ | — |
| 1 | التوقيت والهوية (offsets, broker_symbols, UTC) | ⬜ لم تبدأ | — |
| 2 | Ask/Ticks/Spread/RealVolume (مشروطة بالمسبار) | 🟡 المسبار منجز E7 — جاهزة للكود | E7 |
| 3 | ربط الأخبار/التقويم بالشموع | ⬜ تنتظر إصلاح المصادر | E4 |
| 4 | الجودة والتتبع + اختبارات الوكيل الستة | ⬜ | E1,E5 |
| 5 | طبقة التدريب المحفوظة (training_samples) | ⬜ تحتاج تأكيد المالك | E2 |

### ⏳ معلّق مشروط (قبل مراحل الخدمة): سحبة M1 الحالية جارية في الخلفية
(شفاء 12 رمزاً × 90 يوماً — بعد اكتمالها: تشغيل المسبار، سكربت
`verify_data_readiness.py`، إعادة تشغيل الخدمة لتفعيل المرحلة 0).

---

## المرحلة 0 — شروط مسبقة (Design Fixes)

**الهدف:** أي قراءة لا تغيّر البيانات؛ أي سحبة قابلة لإعادة التشغيل؛ لا عاصفة 500s.

**تعديلات الكود:**
1. `services/nexus_data/main.py`
   - `GET /api/data/ohlcv` يصبح قراءة فقط من DuckDB (لا `_persist_closed_ohlcv`).
   - مسار كتابة صريح جديد: `POST /api/data/ingest/range` (نفس منطق السحبة القديم).
2. `services/nexus_data/duckdb_store.py`
   - جدول `ingest_jobs(id, kind, symbol, timeframe, window_start, window_end,
     status, rows, error, started_at, finished_at)` — إنشاء + دالّتا
     `ingest_job_start/finish`.
   - `_execute_locked`: **انتظار بحد أعلى (5-10 د) + backoff بدل الرفض عند 60 ث**.
3. `scripts/backfill_history.py` → يستدعي مسار الـ POST الجديد.

**الاثبات المطلوب (لقطة):**
- `GET` على range أثناء سحبة جارية → `ingest_jobs` لا تتأثر، والقراءة تعيد من DB.
- سحبة تُقطع (kill) ثم تُستأنف → نفس النافذة تكتمل بلا مكرر (عدّ بعد المكرر = 0).
- لقطة سجل: اختفاء `lock busy >60s refusing to queue` أثناء دفعة كبيرة.

**نقطة التحقق:** `duplicate groups = 0` + `ingest_jobs` يحوي صفوف لكل سحبة.
**الاختبارات:** إضافة إلى `test_historical_import.py`: عزل القراءة/الكتابة.
**الحالة:** ⬜

---

## المرحلة 1 — التوقيت والهوية (أعلى أولوية)

**الهدف:** كل شمعة بوقت UTC غير غامض + ربط مثبت للأسماء.

**تعديلات الكود:**
1. `duckdb_store.py` — أعمدة جديدة في `ohlcv`:
   `bar_open_server_time, bar_open_utc, utc_offset_seconds` +
   جدولا `broker_server_time_offsets(server_code, valid_from, valid_to,
   utc_offset_seconds, method, sampled_at)` (يُملأ عند التغيّر فقط).
2. `duckdb_store.py` — جدول `broker_symbols(instrument_code, broker_symbol,
   server_code, valid_from, valid_to, is_tradable)` + دالّة upsert.
3. `scripts/import_symbol_metadata.py` — يكتب `broker_symbols` من نتائج
   `symbol_info` (استعلام الأسماء عبر `/api/data/mt5/symbols` يسجّل الاسم الفعلي).
4. `services/nexus_data/mt5_worker.py` — يعيد `time` الخام كما هو + يحسب
   `utc_offset_seconds = tick.time - now_utc` في استجابة `symbol_info`.
5. `scripts/import_historical_data.py` — **رفض أي timestamp بلا tz** (خطأ صريح)،
   والتحويل إلى UTC قبل الكتابة.
6. `run.py`/`main.py` — إصلاح بوابة إعادة الاتصال (E6): إعادة محاولة اتصال MT5
   عند `consecutive_failures` حتى لو لم يسبق الاتصال الناجح.
7. **`ohlcv_revisions` (مُضاف v1.1)** — جدول append-only:
   `(symbol, timeframe, timestamp, revision_no, old_open..old_volume,
   new_open..new_volume, available_at, fetch_run_id, reason)` — يُملأ من
   `_apply_ohlcv_upsert` عند كل تعارض يغيّر القيم (الحالي يحدّث الصف
   inplace ويضيّع النسخة القديمة — موثّق `duckdb_store.py:613-615`).

**الاثبات المطلوب (لقطات):**
- `SELECT COUNT(*) FROM ohlcv WHERE bar_open_utc IS NULL` → 0 (للفترة المستوردة).
- جدول `broker_server_time_offsets` يحوي قيمة الإزاحة المقيسة من المسبار.
- `broker_symbols` → 14/14 رمز بحقل وسيط مؤكَّد.
- اختبار CSV برقم بلا منطقة زمنية → **رفض** (لقطة رسالة الخطأ).
- **v1.1:** إعادة سحبة لنفس النافذة بقيمة مصححة → `ohlcv_revisions` يحوي
  النسخة القديمة+الجديدة و`revision` يزداد (لقطة صفّين مقارنين).

**نقطة التحقق:** `epoch(bar_open_utc) = epoch(server) - utc_offset` لكل صف،
وزيادة/نقصان الإزاحة عند حدود DST موثّقة.
**الاختبارات:** فحصا الوكيل: "وقت مستورد له tz صريحة" + "اختبار تغيّر الإزاحة".
**الحالة:** ⬜

---

## المرحلة 2 — Ask والـ ticks (مشروطة بنتيجة المسبار)

**الهدف:** Ask لكل شمعة + تجميع ticks قابل للتدقيق — **ما دام عمق التاريخ يسمح**.

**الشرط المسبق:** ~~لقطة مسبار `copy_ticks_range` لكل رمز~~ ✅ **منجز (E7,
2026-11-09):** 12/14 رمزاً بعمق 173k–2.29M tick/7 أيام؛ **XAUUSD وBTCUSD
ticks_7d=0** → يُعلَّمان `ask_source='unavailable'` ويُعاد فحصهما بعد مزامنة
tick history في الطرفية.

**تعديلات الكود:**
1. `mt5_worker.py` — op جديد `ticks_range` (day-chunked، `COPY_TICKS_ALL`).
2. `duckdb_store.py` — أعمدة في `ohlcv`:
   `ask_open, ask_high, ask_low, ask_close, ask_source, spread_points, real_volume`
   (spread/real_volume يأتان من copy_rates **مجاناً** فوراً).
3. `duckdb_store.py` — جدول `bar_tick_aggregates(symbol, timeframe, bar_open_utc,
   tick_count, buy_tick_count, sell_tick_count, first_time_msc, last_time_msc,
   max_gap_ms, spread_min, spread_max, spread_avg)` — سحبة بأيام متتالية.
4. `scripts/backfill_history.py` — `--with-ticks` يفعّل جلب Ask/Ticks بعد تثبيت الشموع.
5. **عقد ticks كامل (مُضاف v1.1)** — توسيع جدول `ticks` القائم
   (الموجود: bid/ask/spread/timestamp بالثوانٍ فقط):
   `time_msc BIGINT, flags INT, last, volume, volume_real, source_time_utc,
   received_at_utc, fetch_run_id` + مفتاح idempotent
   `(symbol, time_msc, flags)` — لا يُحذف tick ولا يُدمج داخل الثانية.
6. **فصل أنواع الحجم (مُضاف v1.1)** — أعمدة `tick_volume` (الأصل من MT5),
   `real_volume` (NULL إذا غير متاح — **لا يُحوَّل إلى صفر**), `volume_type`
   — مع إبقاء العمود legacy `volume` كما هو بلا تغيير معنى (يُعلَّم أنّه
   tick_volume) لعدم كسر المستهلكين الحاليين.

**الاثبات المطلوب (لقطات):**
- `SUM(tick_count)` من `bar_tick_aggregates` = عدد صفوف `copy_ticks_range` الخام
  لنفس النافذة (لقطة عدّين مقارنين).
- `COUNT(ask_close)/COUNT(*) ≥95%` لكل رمز ذي ticks متوفرة.
- رموز بلا عمق → `ask_source='unavailable'` (لقطة استعلام).
- **v1.1:** عدّ `ticks` الخام لنافذة = `SUM(tick_count)` + اختبار idempotence
  (إعادة استيراد نفس النافذة → عدد صفوف ticks بلا تغيّر).

**نقطة التحقق:** اختبارات الوكيل #5 (tick_count يطابق الخام).
**الاختبارات:** اتساق buy+sell ≤ tick_count، لا ask بلا مصدر.
**الحالة:** ⬜ (تحتاج المسبار)

---

## المرحلة 3 — ربط الأخبار والتقويم بالشموع (للتدريب الدقيق)

**الهدف:** كل ميزة نصية/تقويمية لها وقت إتاحة ≤ وقت القرار، ومرتبطة برمز محدد.

**إصلاح شرطي:** جعل مصدراً واحداً صالحاً يعمل (RSS مثلاً) — الحالة الحالية 403 كامل (E4).

**تعديلات الكود:**
1. `duckdb_store.py` — حزمة context الدنيا:
   `news_articles(id, source, instrument_code, published_at, retrieved_at,
     title, url, content_hash, sentiment)`,
   `news_instrument_impact(news_id, instrument_code, impact_direction, score)`,
   `economic_calendar_events(event_id, country, currency, impact, actual,
     forecast, previous, event_time, imported_at)`,
   `economic_blackout_windows(instrument_code, starts_at, ends_at, reason)`.
2. `services/nexus_news/` — كتابة الجداول الجديدة بدل `fundamental/record` الحالي
   (مع إبقاء القديم متوافقاً)، + مصدر بديل صالح.
3. عرض دمج للتدريب (view): `feature_available_at = COALESCE(retrieved_at, event_time)`
   — **الخبر لا يُستخدم قبل وصوله فعلياً** (منع التسرّب).
4. **story cluster + known_at (مُضاف v1.1)**: `news_story_clusters(cluster_id,
   original_source, independent_source_count)` — إعادة النشر تُجمَّع ولا
   تُعدّ تأكيدات مستقلة؛ + `known_at` صريح لكل خبر/قيمة اقتصادية، وعمود
   `revision` مع `revision_known_at` لقيم التقويم (actual/forecast/previous)
   — **لا تدخل مراجعة لم تكن منشورة بعد وقت القرار**.

**الاثبات المطلوب (لقطات):**
- `COUNT(news_articles WHERE retrieved_at > first bar using it)` = 0 عبر عرض الدمج.
- لقطة أخبار مرتبطة بـ XAUUSD داخل نافذة حدث NFP مع blackout مفعّل.
- `blackout` يمنع عينات التدريب داخل ±15 دقيقة من حدث بتأثير عالٍ.
- **v1.1:** خبر معاد نشره من 3 مواقع → cluster واحد `independent_source_count=1`
  (لقطة) + اختبار سلبي: revision اقتصادي وصل بعد القرار → غير ظاهر في العينة.

**نقطة التحقق:** فحص الوكيل #11 (لا تسرّب) + اختبار سلبي (خبر وصل بعد الشمعة → لا يظهر).
**الاختبارات:** "فحص أن وقت الإتاحة ≤ وقت القرار" + فحص blackout.
**الحالة:** ⬜ (تحتاج إصلاح المصادر أولاً)

---

## المرحلة 4 — الجودة والتتبع

**الهدف:** كل صف قابل للكشف عن التغيير الصامت ولتفسير الفجوة.

**تعديلات الكود:**
1. `ohlcv`: `row_checksum, terminal_id, last_error_code, session_code,
   is_outlier_price, is_spread_outlier` (تُحسب عند الكتابة).
2. `market_data_gaps(symbol, timeframe, gap_start, gap_end, cause)` تُملأ من
   `ohlcv_backfill_runs` + جودة الفحوصات.
3. `test_historical_import.py` — الاختبارات الستة كاملة (tz، الشمعة المتكونة،
   عدد متوقع − فجوات مسجّلة، ربط broker_symbols 14/14، tick_count=خام، تغيّر الإزاحة).
4. **إعادة استخدام تقويم الجلسات (مُضاف v1.1)** — `quality/session_calendar.py`
   موجود ومُوصَل (`main.py:391-402`)؛ نبني `session_code` وتصنيف الفجوات
   فوق `classify_interval` الحالي بدل جدول مكرر.
5. **خطر الاحتفاظ الموثّق (مُضاف v1.1)** — `TICK_RETENTION_DAYS=7` و
   `OHLCV_RETENTION_DAYS=365` موجودان مع `DELETE FROM ticks` في
   `prune_old_data` (`duckdb_store.py:36-38,1681`) **ولا يُستدعى من أي ملف**
   (grep شامل). القرار: تُوثَّق السياسة هنا، **ولا تُفعَّل حذف ticks قبل
   وجود أرشيف Parquet وموافقة صريحة** — وإلا ضاع تاريخ الـ ticks خلال أسبوع.
6. **عتبات SLA بعد baseline (مُضاف v1.1)**: تُقاس التغطية/التأخير لكل
   رمز/فريم أولاً، ثم تُوضع العتبات — لا نسب عامة مخترعة.

**الاثبات المطلوب (لقطات):**
- `verify_data_readiness.py --days 7` → **SUMMARY: READY** (لقطة كاملة).
- تقرير فجوات M1 لكل رمز مع سبب مسجّل لكل فجوة.

**نقطة التحقق:** جاهزية READY + صفر مكرر + صفر شمعة متكونة.
**الحالة:** ⬜

---

## المرحلة 5 — طبقة التدريب المحفوظة (تحت تأكيد المالك)

**الهدف:** كل عينة تدريب قابلة للتدقيق زمنياً ومسجّلة.

**تعديلات الكود:**
1. `training_samples(decision_time, feature_available_at, label_end_time,
   horizon_bars, cost_bps, split)` — قيود CHECK في الدالة نفسها.
2. تثبيت مصفوفات الميزات المحسوبة (`feature_values` دفعة لكل `feature_calculation_run`).
3. تحقّق: `feature_available_at ≤ decision_time` و`label_end_time < اختبار`.

**الاثبات المطلوب:** لقطة عدّ التسرّب = 0 + عدّ العينات لكل split.

**تعديلات مُضافة v1.1 (بيانات التنفيذ الفعلية):**
4. `execution_deals/execution_orders` — سحبة `history_deals_get`/
   `history_orders_get` من MT5 (ticket, time_msc, price, volume, commission,
   swap, profit, reason) → حساب `cost_bps` الفعلي (spread+عمولة+سواب)
   بدل تقديره من الشمعة. مشروط: حساب demo يملك صفقات تاريخية تكفي.

**الاثبات المطلوب (v1.1):** `cost_bps` في `training_samples` مشتق من صفقة
حقيقية معروفة (لقطة: صفقة + الحساب المطابق ±0.1 bps).

**الحالة:** ⬜ — **تنتظر قرار المالك** (هل تُحفظ الميزات اليوم في DuckDB أم الذاكرة؟ E2 تشير للذاكرة).

---

## سجل تحديثات الوثيقة

| التاريخ | التحديث | الحالة |
|--------|---------|--------|
| 2026-11-09 | إنشاء الخطة v1.0 + لقطات E1-E6, E8 (حالة قبل التطوير) | ⬜ البدء |
| 2026-11-09 | E7: مسبار read-only مكتمل لكل الـ14 — offset≈+2h، ticks متوفرة 12/14 (XAUUSD/BTCUSD=0)، عملات مختلطة، صفر NOT FOUND | ✅ |
| 2026-11-09 | **v1.1**: مراجعة وثيقتَي المالك بتحقق ميداني — أُدمج 9 نقاط (ohlcv_revisions، عقد ticks كامل، known_at/story-cluster، خطر retention كامن، execution_deals لـcost_bps، انضباط migrations، فصل الحجم، SLA، إعادة استخدام session_calendar)؛ رُفض ادعاء UTC (مدحض بالأرقام E7) و`broker_instrument_map` (القاموس: broker_symbols)؛ backlog مشروط: Parquet/book/feeds متعددة؛ قاعدة الرفع التلقائي أُعيد تأكيدها | ✅ |
