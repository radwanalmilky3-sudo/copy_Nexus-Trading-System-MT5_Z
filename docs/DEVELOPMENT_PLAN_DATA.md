# خطة تطوير خط بيانات NEXUS — النسخة 1.0 (2026-11-09)

> **هذه الوثيقة = الذاكرة الدائمة للتطوير.** تُحدَّث بعد كل مرحلة بإضافة
> الاثبات (لقطة مخرجات فعلية) وتحديث خانة الحالة، ثم تُرفع إلى GitHub.
> لا تُعلن مرحلة "مكتملة" بدون لقطة اثبات مسجّلة في هذا الملف.

---

## قواعد التنفيذ

1. كل مرحلة: **الهدف → تعديلات الكود (ملفات محددة) → الاثبات المطلوب → نقطة التحقق → الاختبارات → الحالة**.
2. `GET` قراءة فقط؛ السحب يتم عبر مسار كتابة صريح مُسجَّل في `ingest_jobs`.
3. أي وقت مستورد **يُرفض بلا منطقة زمنية صريحة** (يُحوَّل إلى UTC كتابةً).
4. تعديلات الخدمة تُكتب أولاً، ثم تُفعَّل بإعادة تشغيل واحدة، ثم تُلتقط لقطة التحقق.
5. كل commit يحمل وصف التعديل، ويُدفع إلى `origin/main` فوراً (قاعدة ثابتة).

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

### E7 — نتائج الاستيراد الفعلية (Before للجودة)

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
| 2 | Ask/Ticks/Spread/RealVolume (مشروطة بالمسبار) | ⬜ تنتظر المسبار | E3 |
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

**الاثبات المطلوب (لقطات):**
- `SELECT COUNT(*) FROM ohlcv WHERE bar_open_utc IS NULL` → 0 (للفترة المستوردة).
- جدول `broker_server_time_offsets` يحوي قيمة الإزاحة المقيسة من المسبار.
- `broker_symbols` → 14/14 رمز بحقل وسيط مؤكَّد.
- اختبار CSV برقم بلا منطقة زمنية → **رفض** (لقطة رسالة الخطأ).

**نقطة التحقق:** `epoch(bar_open_utc) = epoch(server) - utc_offset` لكل صف،
وزيادة/نقصان الإزاحة عند حدود DST موثّقة.
**الاختبارات:** فحصا الوكيل: "وقت مستورد له tz صريحة" + "اختبار تغيّر الإزاحة".
**الحالة:** ⬜

---

## المرحلة 2 — Ask والـ ticks (مشروطة بنتيجة المسبار)

**الهدف:** Ask لكل شمعة + تجميع ticks قابل للتدقيق — **ما دام عمق التاريخ يسمح**.

**الشرط المسبق:** لقطة مسبار `copy_ticks_range` لكل رمز:
`ticks_7d`, `offset_s`, `profit_cur`, `margin_cur` — إن كان `ticks_7d=0`
فالقسم المتعلق بذلك الرمز يُعلَّم `unavailable` ولا يُقدَّر.

**تعديلات الكود:**
1. `mt5_worker.py` — op جديد `ticks_range` (day-chunked، `COPY_TICKS_ALL`).
2. `duckdb_store.py` — أعمدة في `ohlcv`:
   `ask_open, ask_high, ask_low, ask_close, ask_source, spread_points, real_volume`
   (spread/real_volume يأتان من copy_rates **مجاناً** فوراً).
3. `duckdb_store.py` — جدول `bar_tick_aggregates(symbol, timeframe, bar_open_utc,
   tick_count, buy_tick_count, sell_tick_count, first_time_msc, last_time_msc,
   max_gap_ms, spread_min, spread_max, spread_avg)` — سحبة بأيام متتالية.
4. `scripts/backfill_history.py` — `--with-ticks` يفعّل جلب Ask/Ticks بعد تثبيت الشموع.

**الاثبات المطلوب (لقطات):**
- `SUM(tick_count)` من `bar_tick_aggregates` = عدد صفوف `copy_ticks_range` الخام
  لنفس النافذة (لقطة عدّين مقارنين).
- `COUNT(ask_close)/COUNT(*) ≥95%` لكل رمز ذي ticks متوفرة.
- رموز بلا عمق → `ask_source='unavailable'` (لقطة استعلام).

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

**الاثبات المطلوب (لقطات):**
- `COUNT(news_articles WHERE retrieved_at > first bar using it)` = 0 عبر عرض الدمج.
- لقطة أخبار مرتبطة بـ XAUUSD داخل نافذة حدث NFP مع blackout مفعّل.
- `blackout` يمنع عينات التدريب داخل ±15 دقيقة من حدث بتأثير عالٍ.

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
**الحالة:** ⬜ — **تنتظر قرار المالك** (هل تُحفظ الميزات اليوم في DuckDB أم الذاكرة؟ E2 تشير للذاكرة).

---

## سجل تحديثات الوثيقة

| التاريخ | التحديث | الحالة |
|--------|---------|--------|
| 2026-11-09 | إنشاء الخطة v1.0 + لقطات E1-E7 (حالة قبل التطوير) | ⬜ البدء |
