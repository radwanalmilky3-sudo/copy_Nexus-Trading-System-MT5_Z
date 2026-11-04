# DATA FLOW MAP — NEXUS TRADER MT5 (مثبت من الكود والاتصالات الحية)

> 2026-11-04. كل مسار أدناه مُثبت من: استدعاءات HTTP في الكود (http_client/data_client)، مفاتيح Redis الحية، جداول DuckDB، وملاحظة السجلات أثناء الجولات 1–3.

## F1 — بيانات السوق (MT5/مصادر → عرض)
```
MT5 (EA على طرف المالك) / CCXT / YFinance / IBKR
  → nexus-data :9001 (mt5_worker + connectors + dedup/quality)
  → DuckDB (ohlcv, ticks, market_series_observations, data_vintages)  [كاتب وحيد]
  → Redis (nexus:candles:*, nexus:features:*)
  → nexus-features :9002 (مؤشرات/تقلب/جلسات/ارتباط)
  → nexus-api :9000 (routers/market.py, websockets/ticks.py)
  → Dashboard (رسوم + ترويسة أسعار)
```
**حالة الإثبات حالياً:** القاعدة جديدة — ohlcv/ticks = 0 → الواجهة تعرض حالات فارغة صادقة (404 موثق "no data yet"). المسار السابق للاستيعاب البديل (CCXT/YFinance) كود موجود وقابل للاستدعاء عبر /api/v2/market endpoints.

## F2 — دورة الذكاء والقرار
```
Redis nexus:features:history:*
  → nexus-ml :9003 (8 نماذج؛ إن غير مدرّبة → rule_based_signal + حالة "not trained yet" صادقة)
  → nexus-agents :9004 (graph: 13 وكيلاً؛ LLM glm-4.5-flash اختياري)
     - LLM متاح → نقاش كامل A1→A7 (مُثبت: llm ONLINE، latency 5.6s)
     - LLM مرفوض (429) → fail-closed: تحليل خام + NO_TRADE (مُثبت)
  → قرار موثق (agent_logs / redis nexus:decision:*)
  → nexus-api routers/agents.py + websockets/agents.py → LiveDecisionPanel
```

## F3 — المخاطر والتنفيذ التجريبي
```
قرار → nexus-risk :9006 (risk_rules.yaml: حد/ارتباط/جلسات/anti-tilt)
  → قبول: nexus-executor :9007 (paper_executor → trades/positions في DuckDB؛ EA queue للجسر)
  → رفض: سبب موثق للسجل والواجهة
  → nexus-monitor :9008 (مقاييس) + websockets/risk+positions → RiskMonitor/ActivePositions
```
**حماية:** KILL switch (Redis nexus:system:kill_switch) يوقف التنفيذ فوراً — دورة KILL/RELEASE مختبرة حياً (D3 مُصلح، إصدار 7fe9f3d). paper فقط — **لا مسار حقيقي مفعّل في الصندوق**.

## F4 — الأخبار والتنبيهات
```
مصادر خارجية → nexus-news :9005 (fetcher/تقويم/مشاعر/blackout)
  → DuckDB (news_*) + Redis (nexus:news:*)
  → fundamental engines V61 (scoring/impact/توضيحات عربية)
  → routers/news.py + NewsTickerBar/NewsFeed + تنبيهات (alert_delivery_log)
```

## F5 — دورة المستخدم والمصادقة
```
/login → POST /api/auth/login (JWT access+refresh، DuckDB app_users/user_audit_log)
  → الواجهة تحفظ الجلسة → كل نداء عبر Authorization Bearer (middleware/auth.py)
  → WS auth (websockets/auth.py)
  → خروج/انتهاء/إلغاء → رفض صادق 401
```
إثبات: دخول 200، كلمة خاطئة رسالة عربية، توكن ملغى مرفوض (جولة 2)، admin APIs محمية.

## F6 — المراقبة والتشغيل
```
run.py (مشرف) → يبني URLs الأقران + بوابة صحة + إعادة إطلاق <1s (S4)
nexus-monitor :9008 → مقاييس/أداء/Telegram
/api/system/health (تجميعي عبر 9000) → شريط حالة الواجهة
خارج المستودع: scripts/nexus_heal.sh كل 5 د (Job 502675) + backup_nexus.sh يومي (502676 → فرع backups)
```

## جدول القنوات (Communication Matrix)
| من | إلى | الوسيط | الدليل |
|---|---|---|---|
| dashboard | nexus-api | HTTP :3000→9000 | سجلات 22,968 نداء (جولة 1) |
| nexus-api | كل الخدمات | HTTP 127.0.0.1 | data_client.py + env URLs |
| nexus-agents | Z.ai | HTTPS | llm_url في /health |
| كل الخدمات | Redis | TCP 6379 | 123 مفتاحاً حي |
| nexus-data | DuckDB | ملف مقفول | إثبات القفل |
| EA(المالك) | nexus-api | HTTP+توكن | docs/EA_BRIDGE.md — BLOCKED هنا |
