# SOURCE_REGISTRY — مصادر التحليل الأساسي

الحالة هنا تصف **العقد البرمجي**، لا تدعي أن المفتاح/المصدر متاح على جهاز المستخدم. أي مصدر بلا إعداد صالح يظهر `CONFIG_REQUIRED/UNAVAILABLE` ولا يتم اختلاق بيانات بديلة.

| ID | المحور | المصدر | النقل | الإعداد | سياسة أساسية |
|---|---|---|---|---|---|
| `bls` | الاقتصاد الكلي | U.S. Bureau of Labor Statistics | API | `BLS_API_KEY` اختياري | Actual/vintage رسمي؛ لا يُختلق Forecast |
| `bea` | الاقتصاد الكلي | U.S. Bureau of Economic Analysis | API | `BEA_API_KEY` | مسجل؛ يبقى CONFIG_REQUIRED/غير مستخدم حيًا حتى موصل صالح |
| `fred` | الأسواق المترابطة | FRED | API | `FRED_API_KEY` | US2Y/US10Y/Real Yield/VIX/Broad Dollar — origin=real |
| `fed_rss` | السياسة النقدية | Federal Reserve RSS | RSS | لا مفتاح | بيانات Fed الرسمية؛ تحليل نبرة/نوع الحدث |
| `cftc` | التدفقات | CFTC/COT | API configured | `CFTC_COT_ENDPOINT` | أسبوعي/هيكلي؛ لا يطلق M5 مباشرة |
| `treasury` | الأسواق المترابطة | U.S. Treasury | API configured | `TREASURY_DATA_ENDPOINT` | موصل اختياري؛ لا بيانات مزيفة |
| `world_bank` | الاقتصاد الكلي | World Bank | API | لا مفتاح | مسجل للبيانات الهيكلية؛ لا يرفع الثقة بلا ingest صالح |
| `imf` | الاقتصاد الكلي | IMF | SDMX/configured | `IMF_DATA_ENDPOINT` | موصل اختياري |
| `gold_etf` | التدفقات | Gold ETF licensed provider | API configured | `GOLD_ETF_DATA_ENDPOINT` | يحترم الترخيص/التخزين |
| `central_bank_gold` | التدفقات | Official/licensed provider | API configured | `CENTRAL_BANK_GOLD_ENDPOINT` | Structural prior فقط، ليس M5 trigger |
| `market_flow` | التدفقات | OI/Volume/Options/Order Flow provider | API configured | `MARKET_FLOW_DATA_ENDPOINT` | تكتيكي/لحظي حسب المصدر |
| `newsapi` | أفقي News | NewsAPI | API | `NEWSAPI_KEY` | live snapshot؛ `storage_allowed=false` |
| `gnews` | أفقي News | GNews | API | `GNEWS_KEY` | live snapshot؛ `storage_allowed=false` |
| `calendar_secondary` | تقويم | Secondary economic calendar | JSON | لا مفتاح | المصدر الحالي للـcalendar؛ إذا فشل → DEGRADED/Fail-closed |
| `news_secondary` | News | External publisher | API | حسب التنفيذ | لا يُعامل كمصدر مستقل إن كان إعادة نشر |

## قواعد إلزامية

- `Missing != Neutral`.
- `PROXY != REAL` و`SYNTHETIC != REAL`.
- News/FinBERT طبقة أفقية وليست محورًا سادسًا.
- FinBERT sentiment لا يتحول مباشرة إلى Gold direction.
- Actual وForecast/Consensus يحتفظان بـprovenance مستقل.
- المصدر غير الموصول فعليًا يبقى `CONFIG_REQUIRED/UNAVAILABLE` في الشهادة والواجهة.
