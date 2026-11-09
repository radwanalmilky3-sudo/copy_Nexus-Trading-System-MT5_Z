# دليل إدخال البيانات التاريخية واختبار المشروع 📊

## نظرة عامة

هذا الدليل يشرح كيفية إدخال بيانات OHLCV تاريخية (XAUUSD/BTCUSD) إلى Nexus Trader
بدءًا من حساب MT5 الخاص بك، ثم تشغيل النظام للاختبار في **وضع Paper**.

---

## 📋 المتطلبات المسبقة

1. **MT5 مفتوح ومتصل بنفس الحساب**:
   - Login: `2000020618`
   - Server: `OneRoyal-Demo`
   - Symbol: `XAUUSD` (تأكد من اختياره في لوحة المراقب)

2. **تشغيل خادم MT5 على منفذ مختلف** (لا يؤثر على عمل الميتاترادر):
   ```
   C:\Program Files\MetaTrader 5\terminal64.exe --from-command
   ```

3. **التأكد من تفعيل الرموز**:
   ```
   View → Market Watch → Right-click → Show All
   ```

---

## 🚀 الخطوة 1: تشغيل النظام بالكامل

من مجلد المشروع (root)، قم بتشغيل أسطول الخدمات الكامل:

```powershell
cd D:\Nexus-Trading-System-MT5_Z
python bootstrap_ensemble.py
```

هذا الملف يقوم بـ:
- تشغيل 9 microservices + الـ dashboard
- حقن عناوين الخدمات المتبادلة
- إعادة تشغيل أي خدمة تتعطل تلقائيًا

أو شغّل الخدمات فقط التي تحتاجها للاختبار:

```powershell
python run.py --services nexus-data,nexus-features,nexus-api
```

---

## 📥 الخطوة 2: استخراج البيانات من MT5

### الخيار الأول: إدخال مباشر من MT5 (موصى به)

> **ملاحظة مهمة:** `scripts/import_historical_data.py` لم يعد مدعومًا لبيانات MT5 —
> لا توجد نهاية HTTP للإدخال في `nexus-data`. الطريقة الصحيحة هي السكربت أدناه:
> نافذة `nexus-data` لديها قفل كتابة DuckDB الوحيد، والسحب عبر `GET
> /api/data/ohlcv/{symbol}/{tf}?start=&end=&limit=5000` ينقل الشموع من MT5 إلى
> المخزن تلقائيًا (`_persist_closed_ohlcv`).

يستخدم السكربت خادم `nexus-data` المتصل بحساب MT5 تلقائيًا، وينفّذ تمريرتين
(الثانية تُكمل النوافذ التي أعادت MT5 بيانات ناقصة بسبب مزامنة التاريخ الكسولة):

```powershell
# كل الفترات لرمز واحد وطول 365 يومًا
.\venv-nexus\Scripts\python.exe scripts\backfill_history.py --symbols XAUUSD --timeframes M1,M5,M15,M30,H1,H4,D1 --days 365

# أو مجموعة رموز الافتراض بالكامل
.\venv-nexus\Scripts\python.exe scripts\backfill_history.py --days 365
```

**الإحداثيات المتاحة:**
| المعامل | القيمة الافتراضية | الوصف |
|---------|-------------------|-------|
| `--symbols` | مجموعة الخدمة | رموز مفصولة بفواصل (XAUUSD/BTCUSD/...) |
| `--timeframes` | كل الفترات | M1/M5/M15/M30/H1/H4/D1 |
| `--days` | `365` | عمق التاريخ المطلوب |

---

### مجموعة الأصول المعتمدة (14 رمزاً) والأعماق

مجموعة مركزة بالذهب للتدريب متعدد الأصول (معتمدة من المالك):

| # | الرمز | الأصل |
|---|-------|-------|
| 1 | XAUUSD | الذهب |
| 2 | XAGUSD | الفضة |
| 3 | BTCUSD | بيتكوين |
| 4 | ETHUSD | إيثريوم |
| 5 | DXY | مؤشر الدولار |
| 6 | EURUSD | يورو/دولار |
| 7 | GBPUSD | باوند/دولار |
| 8 | USDJPY | دولار/ين |
| 9 | USDCHF | دولار/فرنك |
| 10 | AUDUSD | أسترالي/دولار |
| 11 | USDCAD | دولار/كندي |
| 12 | US30 | مؤشر داو جونز |
| 13 | US500 | مؤشر S&P 500 |
| 14 | WTI | نفط خام |

**الأعماق المعتمدة:**
```powershell
# المرحلة 1 — M1 لـ90 يوماً
.\venv-nexus\Scripts\python.exe scripts\backfill_history.py --symbols XAUUSD,XAGUSD,BTCUSD,ETHUSD,DXY,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,US30,US500,WTI --timeframes M1 --days 90

# المرحلة 2 — بقية الفريمات لـ365 يوماً
.\venv-nexus\Scripts\python.exe scripts\backfill_history.py --symbols XAUUSD,XAGUSD,BTCUSD,ETHUSD,DXY,EURUSD,GBPUSD,USDJPY,USDCHF,AUDUSD,USDCAD,US30,US500,WTI --timeframes M5,M15,M30,H1,H4,D1 --days 365
```

> الرموز غير الموجودة في Market Watch تُضاف تلقائياً عند أول طلب
> (`symbol_select` داخل worker) — لا حاجة لتفعيل يدوي.

### لقطات خصائص الرموز (symbol_info → DuckDB)

جدول `symbol_property_snapshots` (append-only، متوافق مع القاموس
`broker.symbol_property_snapshots`) يُملأ عبر:

```powershell
.\venv-nexus\Scripts\python.exe scripts\import_symbol_metadata.py                # الرموز الـ14
.\venv-nexus\Scripts\python.exe scripts\import_symbol_metadata.py --symbols XAUUSD,BTCUSD
```

كل استدعاء يلتقط لقطة جديدة (`captured_at` يفرّق بينها): digits, point,
spread, contract size, tick sizes, volume/margin/swap limits, trade_mode...
النقطة: `GET /api/data/symbols/{symbol}/snapshot` (internal secret مطلوب).

---

### الخيار الثاني: استيراد ملف CSV/JSON

إذا كنت تفضّل العمل بملف محلي:

```powershell
python scripts/import_historical_data.py --source csv --path data/XAUUSD_H1_2026.csv --symbol XAUUSD --timeframe H1
python scripts/import_historical_data.py --source json --path data/btc_candles.json --symbol BTCUSD --timeframe H1
```

**صيغة CSV المطلوبة** (مع ترويسة):

| timestamp | open | high | low | close | volume |
|-----------|------|-------|-----|-------|--------|
| 2026-10-01 00:00:00 | 2650.50 | 2652.00 | 2649.00 | 2651.20 | 1523 |

**صيغة JSON:**

```json
[
  {
    "timestamp": "2026-10-01T00:00:00Z",
    "open": 2650.50,
    "high": 2652.00,
    "low": 2649.00,
    "close": 2651.20,
    "volume": 1523
  }
]
```

**ملاحظة:** السكربت يتعرّف على تنسيقات تواريخ متعددة، ويعمل مع **Unix timestamps** (بالثواني أو بالميليثانية).

---

### الخيار الثالث: الجلب المباشر من MT5 عبر الأوامر اليدوية

```python
import MetaTrader5 as mt5
mt5.initialize()
rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start_dt, end_dt)
```

---

## ✅ الخطوة 3: التحقق من البيانات

بعد الإدخال، تأكد من تخزين البيانات:

```powershell
# عبر API
curl http://localhost:9001/ohlcv/XAUUSD/H1/provenance

# فحص شامل للبيانات
python scripts/test_historical_import.py --symbol XAUUSD --timeframe H1

# أو فحص كل الرموز
python scripts/test_historical_import.py
```

---

## 🧪 الخطوة 4: اختبار النظام

### 4a. اختبار توصيل MT5

افتح الداشبورد في المتصفح:
```
http://localhost:3100
```
من القائمة: **الإعدادات → الاتصال → تحقق من اتصال MT5**

### 4b. تشغيل Bootstrap لتوليد إشارات ML

```powershell
python bootstrap_ensemble.py --symbol XAUUSD --min-samples 500 --dry-run
```

هذا يفحص عدد records في Redis ويبدأ التدريب تلقائيًا إذا كانت البيانات كافية.

### 4c. فحص حالة الـ dashboard

```powershell
curl http://localhost:3100/api/system-diagnostics
```

---

## 🛠️ عيوب معروفة وحلولها

| الخطأ | السبب | الحل |
|-------|-------|------|
| `-6 Authorization failed` | terminal64.exe مفتوح بصلاحيات مسؤول | أعد فتحه بصلاحيات عادية نفس المستخدم |
| `No history available` | التاريخ غير محمل في MT5 | افتح MT5 وانتظر، أو استخدم `--days` أقصر |
| `429 Too Many Requests` | ضغط LLM | انتظر دقيقة — يزول تلقائيًا |
| `1006 Connection closed` | MT5 غير متصل | تأكد من اتصال MT5 بالشبكة |

---

## 📌 ملاحظات هامة

1. **وضع Paper مفعل افتراضيًا**: لا يتم تنفيذ أوامر حقيقية على MT5.
2. **البيانات لا تُحفظ في Git**: `.env` و `data/nexus.duckdb` في `.gitignore`.
3. **الحد الأقصى**: MT5 يرفض أكثر من 50000 شمعة في طلب واحد.

---

## 📂 الملفات المستخدمة

| الملف | الوصف |
|------|-------|
| `scripts/backfill_history.py` | سحب التاريخ من MT5 عبر نهاية الـ range (طرقتان للمزامنة الكسولة) |
| `scripts/import_symbol_metadata.py` | التقاط لقطات symbol_info للرموز الـ14 → `symbol_property_snapshots` |
| `scripts/sample_import_month.py` | استيراد عينة شهر واحدة بكتابة مباشرة (الخدمة متوقفة) |
| `scripts/test_historical_import.py` | فحص صحة البيانات المدخلة |
| `run.py` | تشغيل الأسطول الكامل |
| `bootstrap_ensemble.py` | تهيئة ML + البيانات التدريبية |
| `services/nexus_data/mt5_worker.py` | خادم MT5 المعزول (ops: research_history / symbol_info / ...) |
| `data/nexus.duckdb` | قاعدة البيانات التاريخية |
