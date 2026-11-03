# أولوية الإعدادات (Settings Precedence) — Nexus Trading System

> **ملخص تنفيذي:** هناك ثلاث طبقات للإعدادات. **Redis يفوز فورًا** (live، دون restart)،
> و`.env` يُقرأ **مرة واحدة فقط عند إقلاع `run.py`** ثم يُورَّث للأبناء، و`DEFAULTS` في الكود
> هي شبكة الأمان الأخيرة عند غياب المفتاح في Redis. أي تغيير في `.env` **لا يظهر أبدًا
> قبل إعادة تشغيل النظام كاملًا (full restart)** — وبطاقة البيئة تعيد تشغيل النظام **فقط
> بعد إذن المشغّل**.

---

## 1) الطبقات الثلاث والأدلة في الكود

| # | الطبقة | المخزن | متى تُقرأ | كيف تُعدَّل | سريان الأثر |
|---|--------|--------|-----------|-------------|--------------|
| (أ) | Runtime settings — إعدادات تشغيلية حية | Redis key `nexus:runtime:settings` | عند كل قراءة (مع fallback إلى `DEFAULTS`) | `POST /api/intelligence/settings` من بطاقة الإعدادات | **فوري**، دون restart |
| (ب) | متغيرات البيئة | ملف `.env` في جذر المشروع | **مرة واحدة** عند boot ثم تُورَّث لعمليات الأبناء | تحرير اليد، أو `POST /api/system/env` (بطاقة البيئة) | **full restart فقط** |
| (ج) | القيم الافتراضية في الكود | `DEFAULTS` في `shared\runtime_settings.py` | عند غياب المفتاح من المستند المخزّن | تعديل الكود ثم إعادة تشغيل | **restart** |

**الأدلة (file:line):**

| الوقائع | الموقع |
|---------|--------|
| مفتاح Redis `SETTINGS_KEY = "nexus:runtime:settings"` | `shared\runtime_settings.py:41` |
| قاموس `DEFAULTS` (54 مفتاحًا) | `shared\runtime_settings.py:49` → `:141` |
| القراءة التسامحية: Redis معطّل ⟵ تُعاد `DEFAULTS` | `shared\runtime_settings.py:17-18` |
| `GET /api/intelligence/settings` يعيد `settings` (المستند الخام) + `source` + `defaults` | `services\nexus_api\routers\intelligence.py:321-354` |
| `POST /api/intelligence/settings` (صلاحية `trading.settings` + `sanitize_patch`) | `services\nexus_api\routers\intelligence.py:396-422` |
| كتابة آمنة بأسلوب CAS (WATCH/MULTI) | `services\nexus_api\routers\intelligence.py:357-393` |
| قراءة `.env` عند الإقلاع: `_ensure_dotenv` + `dotenv_values` | `run.py:427-451` (‏`dotenv_values` في `:446`) |
| استدعاؤها مرة واحدة في `_check_prerequisites` | `run.py:485-489` ← مُستدعى من `main()` في `run.py:913` |
| تمريرها للأبناء كـ `env_override = dict(env)` | `run.py:917` |
| الأبناء يرثون `env = {**os.environ}` ثم `env.update(env_override)` | `run.py:589-591` (الخدمات) و `run.py:636-638` (الـ dashboard) |
| متطلبات الإقلاع الإلزامية (`NEXUS_SECRET_KEY` … `NEXUS_JWT_SECRET` …) | `run.py:457-463` |
| بطاقة البيئة: `GET/POST /api/system/env` | `services\nexus_api\routers\env.py:254` و `:450` — مسجّلة في `services\nexus_api\main.py:158` |

> **ملاحظة تقنية مهمة:** لا يوجد `load_dotenv` لاحق في `run.py` ولا `os.environ.update` —
> أي تعديل على `.env` أثناء التشغيل **لن يقرأه أي عملية** حتى لو فُتحت من جديد.
> لذلك `env.py:20-22` يوثّق أن كل كتابة تحمل `restart_required: true`.

---

## 2) قاعدة الأولوية (الترتيب)

1. **إن وُجد المفتاح في Redis** → قيمة Redis هي الحاكمة، وتُطبَّق فورًا على كل الخدمات
   (risk + agents + ml يقرأون المستند نفسه).
2. **إن غاب المفتاح من Redis** → تُستخدم `DEFAULTS`، وبعض هذه القيم **مُزرَع من `.env`
   وقت بناء `DEFAULTS` نفسه** (أي عند استيراد الوحدة أول مرة):
   - `off_hours_allowed` ⟵ `NEXUS_ALLOW_OFF_HOURS` (`shared\runtime_settings.py:82-83`)
   - `allowed_sessions` ⟵ `NEXUS_ALLOWED_SESSIONS` (`shared\runtime_settings.py:84-89`)
3. **إن غاب من `.env` أيضًا** → القيمة الافتراضية المكتوبة في الكود.

**النتيجة العملية:** البيئة (`.env`) تزرع القيمة الابتدائية فقط، و**ما يُحفَظ من الواجهة
يسمى `off_hours_allowed` في Redis يتغلب دائمًا** — وهذا بالضبط ما يجعل البوابة قابلة
للتعديل من UI بدل أن تكون read-only
(تعليق الكود: `shared\runtime_settings.py:78-81`، والتنفيذ
`session_gate_policy()` في `shared\runtime_settings.py:393-429` حيث
`default_off_hours` تُستخدم فقط حين يغيب المفتاح المخزّن — `:428-429`؛
ونداء risk في `services\nexus_risk\main.py:2513-2525`).

---

## 3) أمثلة على توزيع الطبقات

| المفتاح | الطبقة الحاكمة | الدليل | ملاحظات |
|---------|----------------|--------|---------|
| `risk_per_trade_pct` | **Redis — حي** | `shared\runtime_settings.py:51` (الابتدائي) + `POST /settings` `intelligence.py:396` | يُغيَّر من بطاقة «المخاطرة والحجم» ويُطبَّق على الصفقة التالية دون restart |
| `NEXUS_JWT_SECRET` | **`.env` فقط وقت الإقلاع** | `run.py:461` ضمن `REQUIRED_ENV_VARS` | **سر (secret)**: محجوب تمامًا عن بطاقة البيئة (`env.py:55-70`) ولا يظهر ولا يُعدَّل من الواجهة |
| `sl_atr_multiplier` | **`DEFAULTS` + Redis** | `shared\runtime_settings.py:100` | الابتدائي `1.5`؛ أي حفظ من الواجهة يكتبه في Redis ويفوز |
| `max_daily_trades` | **`DEFAULTS` (5) + Redis** | `shared\runtime_settings.py:56` | انظر القسم 7 — **لا يوجد متغيّر env** |
| `require_mtf_confirmation` / `min_mtf_agreement` | **Redis فقط** | `shared\runtime_settings.py:67-68` — حقول الواجهة `dashboard\src\app\dashboard\settings\page.tsx:54-55` | **ليست** من `NEXUS_OHLCV_TIMEFRAME` (انظر القسم 8) |
| `NEXUS_ALLOW_OFF_HOURS` | **بذرة (seed) فقط** | `.env:17` → `runtime_settings.py:82` | Redis يتغلب دائمًا |
| `NEXUS_LLM_MODEL` | **`.env` وقت الإقلاع** | `.env:97` + `shared\llm_factory.py:21,40` | قيمة حالية `qwen2.5:3b`؛ قابل للتعديل من بطاقة البيئة (core) |

---

## 4) دورة حياة `restart` عمليًا

| ما تغيّر | هل يحتاج restart؟ | السبب |
|----------|-------------------|-------|
| حقل من بطاقة **الإعدادات العامة** (Redis) | **لا** | `POST /api/intelligence/settings` يكتب مباشرة في `nexus:runtime:settings` والخدمات تقرأه عند كل دورة |
| متغيّر في **`.env`** (بطاقة البيئة) | **نعم — full restart** | القيم تُقرأ مرة واحدة (`run.py:446`) وتُمرَّر للأبناء عبر `env_override` (`run.py:917` → `:589` / `:636`)؛ العمليات الحيّة لا تُحدِّث `os.environ` |
| قيمة في **`DEFAULTS`** (كود) | **نعم** | تحتاج إعادة بناء/تشغيل للعمليات التي استوردت الوحدة |
| حفظ **قالب** (Template) | **لا** | القالب فقط **يعبّئ النموذج**؛ لا يُكتب شيء قبل «حفظ الكل» |
| قراءة Redis أثناء انقطاعه | لا شيء يتعطّل | `GET /settings` يعود بعلامة خطأ موثّقة بدل 5xx (`intelligence.py:333-340`)، والقراءات تهبط إلى `DEFAULTS` |

**قبل كل حفظ في Redis** تُلتقط نسخة تراجع في `nexus:runtime:settings:last`
(`intelligence.py:409-412` و `:434` و `:445-446`).

---

## 5) بطاقة البيئة (Environment Card) — الكتابة الآمنة على `.env`

الخلفية كاملة في `services\nexus_api\routers\env.py`، والبطاقة في
`dashboard\src\app\dashboard\settings\page.tsx:1102-1235` (`id="env"`).

**دورة الكتابة الآمنة (POST `/api/system/env`):**

1. **الصلاحية أولًا** قبل أي عمل على الملف: `trading.settings` (`env.py:458`).
2. **التحقق من القيمة** حسب نوع المتغيّر (bool/int/float/enum/str + نطاق + نمط + طول
   + منع أحرف التحكم) — `env.py:303-351`.
3. **رفض صريح** للمتغيّرات المجهولة أو للقراءة فقط أو للأسرار برسالة عربية موحّدة
   (لا تُفشي أين المفتاح موجود أصلًا) — `env.py:48-51` و `:462-463`.
4. **نسخة احتياطية أولًا**: `.env` ← `.env.bak.<UTC yyyymmdd_HHMMSS>`؛ فشل النسخ =
   `503` **ولا يُكتب أي شيء** — `env.py:356-367`.
5. **كتابة ذرّية**: استبدال سطر `KEY=` فقط مع الحفاظ على الترتيب والتعليقات ونهايات
   الأسطر (CRLF/LF)، عبر ملف مؤقت + `os.replace` + `fsync` — `env.py:401-447`.
6. **الاستجابة** تحمل `restart_required: true` (`env.py:484`)، والواجهة تعرض شارة
   «⏳ يتطلب إعادة تشغيل» (`page.tsx:511-512` و `:1122-1129`) مع تنبيه صريح بأن
   **إعادة التشغيل غير مسموحة دون إذن المشغّل** (`page.tsx:1110-1111`).
7. **التدقيق** يُسجَّل المفتاح فقط لا القيمة (`env.py:477-478`).

**الحدود الثلاث لمجموعة المتغيّرات (allowlist — `env.py:119-196`):**

| المجموعة | العدد | السلوك في الواجهة |
|----------|-------|-------------------|
| `core` (أساسي) | 27 | قابل للتعديل مع تحقق كامل |
| `danger` (خطير) | 6 | تعديل ممكن + نافذة تأكيد `window.confirm` بتحذير عربي (`page.tsx:500-506`) |
| `readonly` (للقراءة فقط) | 8 | معروض لكنه مقفل — `editable: false` (`env.py:179-195`) |
| **أسرار محجوبة (secrets)** | **12** | لا تُقرأ ولا تُعاد ولا تُسجَّل إطلاقًا (`env.py:55-70` + `:199`) |

**الأسرار الـ12:** `NEXUS_PIN`, `NEXUS_SECRET_KEY`, `NEXUS_JWT_SECRET`,
`NEXUS_INTERNAL_API_SECRET`, `NEXUS_ADMIN_PIN`, `NEXUS_RISK_APPROVAL_SECRET`,
`MT5_PASSWORD`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`NEWSAPI_KEY`, `GNEWS_KEY`.

التجميع في الواجهة يتم من الـ category التي يعيدها الخادم (لا قائمة مُصلَّدة في المتصفح):
`page.tsx:537-545`، وواجهة العميل في `dashboard\src\lib\api-client.ts:110-134` و `:865-877`.

---

## 6) القوالب (Settings Templates)

| العملية | Endpoint | الدليل |
|---------|----------|--------|
| السرد | `GET /api/intelligence/settings/templates` | `intelligence.py:492-537` — يعيد `path` + قائمة الملفات + لقطة `last` |
| الحفظ | `POST /api/intelligence/settings/templates/save` | `intelligence.py:540-588` — يكتب `<name>.json` |
| التحميل | `POST /api/intelligence/settings/templates/load` | `intelligence.py:591-624` — يعيد القيم جاهزة + `dropped` |

- **التخزين:** `config\settings_templates\` (`intelligence.py:433`؛ المجلد يُنشأ عند أول
  استخدام `:486-489`)، ويوجد قالب مدمج `optimal.json`.
- **سلامة الملفات:** اسم القالب يقبل حروفًا/أرقامًا/مسافات/`_`/`-` فقط (`:437`)، منع
  الخروج عن المجلد (`:603-606`)، حدّ 1MB (`:609-610`)، وتمرير القيم عبر
  `sanitize_patch` + `DEFAULTS` فلا يدخل مفتاح مجهول أو خارج النطاق (`:430-431`، `:565`).
- **تجربة الاستخدام (fill-only):** القالب **يعبّئ النموذج فقط** ولا يكتب شيئًا فعليًا إلا
  بعد «حفظ الكل» — نص البطاقة `page.tsx:814-817` والتنفيذ `page.tsx:341-350`.
- **فتح ملف من الجهاز:** file picker محلي بلا رفع (`page.tsx:412-445`)، الحد 1MB
  ومنع ما ليس `.json` (`:418-425`).
- **لقطة التراجع:** قبل كل حفظ يُنسخ المستند الحالي إلى `nexus:runtime:settings:last`
  (`intelligence.py:412`, `:434`, `:445-446`)، وزر «آخر إعدادات (تراجع)» يعيد تعبئة
  النموذج منها (`page.tsx:375-382` و `:886-899`).

---

## 7) قرار `max_daily_trades` (مُسجَّل)

- القيمة الافتراضية في الكود تبقى **`5`**: `shared\runtime_settings.py:56`
  (`"max_daily_trades": 5`).
- **لا يوجد متغيّر `NEXUS_MAX_TRADES_PER_DAY`** — ولم يُضَف إلى `.env` ولا إلى
  allowlist بطاقة البيئة (`env.py:119-196`).
- الرقم **7** الظاهر في الواجهة هو **قيمة Redis حيّة (live override)** محفوظة تحت
  `nexus:runtime:settings`، وليس قيمة افتراضية ولا قيمة env.
- أي «إرجاع للافتراضي» يعني حذف/تصحيح المفتاح في Redis، لا تعديل `.env`.

---

## 8) تصحيحان يجب تثبيتهما

1. **«تأكيد MTF» ليست من `NEXUS_OHLCV_TIMEFRAME`.**
   حقول تأكيد الأطر الزمنية العليا في الواجهة هما `require_mtf_confirmation` +
   `min_mtf_agreement` (`page.tsx:54-55`) وهما **Redis only**
   (`shared\runtime_settings.py:67-68`). أمّا `NEXUS_OHLCV_TIMEFRAME` فتخص **الشموع
   المخزَّنة** وتُقرأ في `services\nexus_data\main.py:328`.
2. **`NEXUS_ALLOW_OFF_HOURS` بذرة فقط (seed-only).** تُزرع `off_hours_allowed`
   وقت بناء `DEFAULTS` (`runtime_settings.py:82-83`)، وما يُحفظ في Redis يتغلب
   (`session_gate_policy` — `runtime_settings.py:428-429`). في بطاقة البيئة تظهر
   **للقراءة فقط** (`env.py:181-183`).

---

*مرجع الاختبارات: `tests\test_settings_contract.py` + `tests\test_settings_templates.py`
= **126 اختبارًا أخضر**. انظر `docs\settings_ui_env_matrix.md` للتفاصيل.*
