# سجل تنفيذ المهمة 2 — مصادقة وعقود API وحالة الخدمات
التاريخ: 2026-10-21 | الخطة: `docs/superpowers/plans/2026-10-21-nexus-audit-remediation.md` | الحالة: منجزة

## ما أُغلق
- **UI-01** (شارة "All systems operational" المبكرة): مغلق بمصدرين —
  1. `classifyDiagnosticBanner(checked, services)` في `dashboard/src/lib/system-health-status.ts`:
     `services=[]` أو `checked=false` → `'checking'` (لا يُعلن صحّة قبل اكتمال الفحص).
  2. حالة تحميل مرئية: بانر ذهبي "Checking services…" مع `Loader2` دوّار
     (لقطة `t2-01-boot-checking-banner.png` — التُقطت عند poll 14، أي قبل اكتمال الفحص).
- **API-01** (إعادة تحقق): فحص candles يستخدم `getAuthHeaders()` الآن؛
  401 يُصنَّف "auth required (token missing/expired)" ولا يتحوّل إلى "MT5 offline"
  (`classifyCandlesProbe` + اختبارات `system-diagnostic-state.test.mjs`).

## عقد التصنيف (مُحقق ومُثبت بالمتصفح)
بعد اكتمال الفحص (`t2-03-details-expanded.png`):

| الخدمة | الحالة المعروضة | الصنف |
|---|---|---|
| nexus-api (gateway) | healthy | 200 + حمولة `/health` مُتحقَّق منها |
| Redis / DuckDB | healthy | مكوِّنات من حمولة الصحة |
| nexus-data (MT5 feed) | HTTP 404 | 404 حقيقي بعد المصادقة ("Historical market data not found") |
| MetaTrader 5 | disconnected — check MT5_LOGIN in .env | `live_connected=false` |
| ML Models | upstream offline (HTTP 502) | 502 من البوابة = الخدمة الداخلية غير شغّالة |
| Agent Pipeline | 0/13 ready · offline | 200 بحمولة وكلاء غير نشطين |

البانر: "4 services offline — trading paused" (أحمر) — لا عدّاد أخطاء صفرية ولا نجاح مصطنع.

## المسارات الثمانية (مع مصادقة، بوابة غير مزدحمة)
| المسار | النتيجة | الزمن |
|---|---|---|
| api/ml/traders/status | 502 nexus-ml unreachable | 2.3s |
| api/ml/traders/autonomous/status | 502 nexus-ml unreachable | 2.3s |
| api/ml/traders/mode | 502 nexus-ml unreachable | 2.3s |
| api/agents/decision/XAUUSD | 502 Agents service unreachable | 2.1s |
| api/risk/settings | 502 nexus-risk unreachable | 2.3s |
| api/intelligence/institutional/XAUUSD | 502 nexus-features unreachable | 2.0s |
| api/v2/market/candles (XAUUSD M15) | 404 no data | 80ms |
| trade-memory/metrics | 404 (لا يوجد route أصلاً) | فوري |

بدون مصادقة: 7×401 + trade-memory/metrics 404. المكوّن **لا يطلب** trade-memory/metrics
(تحقّق CDP: الطلبات الفعلية `/api/intelligence/trade-memory` فقط) — لا يلزم route وهمي.

## سبب جذري مُوثَّق: ازدحام البوابة عند تحميل الصفحة (خارج نطاق إصلاح المهمة 2)
- تحقّق CDP (`Network.*`): الصفحة تطلق عند التحميل ~35 طلباً مصادَقًا (مع preflight OPTIONS لكل منها)،
  وجزء منها استدعاءات proxy لخدمات ميتة تستهلك ~2s كل واحدة على الخادم.
- uvicorn عمودي واحد ⇒ طابور؛ زمن الفحص يتذبذب عشوائياً (مُقاس: 3.6s و5.7s و17.8s لنفس المسار
  على نفس المضيف؛ localhost ≠ أسرع بشكل موثوق — الفرق احتمالي لا بنيوي).
- **القرار**: رفع `PROBE_TIMEOUT_MS` من 8s إلى 12s (ضمن ميزانية 15s العامة للتطبيق) +
  نص أوضح للفشل (`no response in 12s` بدل `unreachable`). لا تعديل على البوابة.
- ملاحظة لمهمة مستقبلية: proxy timeout قصير (30s حالياً في `routers/ml.py`) أو تشغيل uvicorn
  بأكثر من عامل يقلّل الطابور — لم يُنفَّذ هنا عمداً (خارج عقد المهمة 2).

## إضافات ضمن المهمة
- `classifyUpstreamProbe(status)` في `system-health-status.ts`: 502/503/504 →
  `upstream offline (HTTP n)`؛ 401/403 → auth؛ 404 → route not found؛ 2xx → ok.
  مُختبَرة بـ6 اختبارات جديدة (الإجمالي 16 في الملف، 102/102 لملفات dashboard كلها).
- إصلاح سلسلة إسبانية `listos` في تفاصيل Agent Pipeline → `ready`.
- فحصين متداخلين: حارس `checkSeqRef` يتجاهل استجابة تصل بعد بدء فحص أحدث (اختبار + تنفيذ).
- جميع الفحوصات متوازية عبر `Promise.all` مع `AbortController` لكل فحص.

## التحقق الآلي
- `node --experimental-strip-types --test tests/*.test.mjs` (dashboard): **102/102**.
- `node node_modules/typescript/bin/tsc --noEmit`: **exit 0**.
- `.venv\Scripts\python.exe -m pytest tests/test_api/test_data_client.py tests/test_api/test_admin_data_service.py tests/test_api/test_websocket_auth.py -q`: **31/31**.
- بوابة `/health`: 200 (redis/duckdb connected، ready=true).

## اللقطات
`C:\Users\rd66\AppData\Local\Temp\nexus-browse\shots-task2\`:
`t2-01-boot-checking-banner.png` (إثبات UI-01)، `t2-02-after-check.png`،
`t2-03-details-expanded.png` (التصنيفات الصادقة أعلاه)، `t2-04-scrolled.png`.

## الملفات المتغيّرة
- `dashboard/src/lib/system-health-status.ts` (classifyDiagnosticBanner، classifyCandlesProbe، classifyUpstreamProbe)
- `dashboard/src/components/windows/SystemDiagnostic.tsx` (بانر checking، auth، timeout 12s، توازي، seq guard، تفاصيل 502)
- `dashboard/tests/system-diagnostic-state.test.mjs` (16 اختباراً)
- `services/nexus_api/requirements.txt` (مواءمة websockets مع الجذر: `>=13.0,<14.0` — الإصدار المثبّت 13.1 لم يتغيّر؛ اختبار auth/WS ناجح)

## ما لم يُغيَّر عمداً
- لا إشارة mode في `/health` (لاBackend signal) — التصنيف يبقى صادقاً: 502 يعني "الداخلية لا ترد"،
  و"غير مشغلة في هذا الوضع" يظهر كـ upstream offline بدل نجاح مزيّف.
- لا تشغيل خدمات ml/risk/agents لتصبح خضراء.
- لا تعديل حماية endpoints (401/403 تبقيان كما هما).
