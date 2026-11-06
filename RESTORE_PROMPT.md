# برومبت التركيب والاسترجاع — Nexus Trading System (MT5 — PAPER ONLY)
> انسخ ما تحت الخط المتقطع والصقه كاملاً في أي وكيل محلي (أو نفّذ الخطوات يدوياً كما هي مرتبة).
> مصدر النسخة: radwanalmilky3-sudo/copy_Nexus-Trading-System-MT5_Z (خاص). آخر تحديث: 2026-11-06.

---

أنت مهندس DevOps محلي. مهمتك تركيب مشروع **Nexus Trading System (MT5 — PAPER ONLY)** على هذا الجهاز من المستودع الاحتياطي، بدورة كاملة: تجهيز → تركيب → إقلاع → تحقق → تقرير. نفّذ بالترتيب وتوقف بسؤال صريح للمالك عند أي بند معلّم [يحتاج المالك].

**قواعد حمراء قبل أي شيء:**
- تداول ورقي فقط: `NEXUS_TRADING_MODE=paper` لا يُغيَّر مهما كان السبب.
- لا أسرار في أي ملف متتبَّع بgit: التوكنات/كلمات المرور في `.env` فقط (gitignored). لا تطبع أي مفتاح في أي ملف أو مخرجات.
- لا تقتل أي عملية على المنافذ يدوياً — الإيقاف الرسمي: `venv-nexus\Scripts\python run.py --stop`.
- مجلد `AGENT_CHANNEL` سجل تاريخي مُغلق نهائياً (T-026) — لا تكتب فيه شيئاً.

**1) المتطلبات — افحص ثم ثبّت الناقص:**
- Git for Windows (2.40+) — [يحتاج المالك] Personal Access Token بصلاحيات repo للمصادقة على أول clone (عبر نافذة Credential Manager، لا تكتبه في أي ملف).
- Python 3.12: `py -3.12 --version`
- Node.js 22 LTS: `node -v` (npm 10.x)
- Redis للويندوز: redis 5.0.14.1 (tporadowski) في `C:\redis5` — المطلوب PONG على `127.0.0.1:6379` (المشروع يستخدم Streams: XADD/XREADGROUP — تحتاج إصدار 5+).
- MetaTrader 5 طرفية مثبتة — للجسر الحي (اختياري للتركيب نفسه).

**2) الاستنساخ:**
```bat
git clone https://github.com/radwanalmilky3-sudo/copy_Nexus-Trading-System-MT5_Z.git D:\Nexus-Trading-System-MT5_Z
cd /d D:\Nexus-Trading-System-MT5_Z
git log --oneline -3
```
- المتوقع على main: `47d5a57` (فرع `local-worklog-20261106` أرشيف تاريخي لسجل القناة — لا تستخدمه).
- إن كان المجلد موجوداً من نفس المستودع: `git pull --rebase origin main` وواصل (التركيب idempotent).

**3) بيئة بايثون:**
```bat
py -3.12 -m venv venv-nexus
venv-nexus\Scripts\python -m pip install --upgrade pip
venv-nexus\Scripts\python -m pip install -r requirements.txt
venv-nexus\Scripts\python -m pip install pytest pytest-asyncio
venv-nexus\Scripts\python -c "import fastapi, duckdb, redis, torch; print('IMPORTS_OK')"
```
- التثبيت كبير (torch CPU) — خذ وقتها. على ويندوز تبقى حزمة MetaTrader5 ضمن requirements — صحيح ومطلوب محلياً.

**4) الداشبورد:**
```bat
cd dashboard && npm ci --no-audit --no-fund && cd ..
```

**5) ملف .env (انسخ من .env.example ثم املأ):**
- ولّد الأسرار عشوائياً (لا تخترعها بيدك):
```bat
venv-nexus\Scripts\python -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(32)); print(secrets.token_hex(16)); print(secrets.token_hex(16)); print(secrets.token_hex(24))"
```
  ووزّع بالترتيب: `NEXUS_SECRET_KEY` · `NEXUS_JWT_SECRET` (64hex لكل) · `NEXUS_INTERNAL_API_SECRET` · `NEXUS_RISK_APPROVAL_SECRET` (32hex **مختلف** عن السابق) · `BACKUP_PASSPHRASE` (48hex).
- `NEXUS_ADMIN_PIN` (6 أرقام مولدة) + `NEXUS_ADMIN_PASSWORD` (قوي مولد) — **سلّم القيم للمالك كتابعةً في المحادثة فقط**.
- مزود الذكاء (قرار مالك محسوم — سحابي GLM بدل Ollama):
  ```
  NEXUS_LLM_PROVIDER=zai
  NEXUS_LLM_MODEL=glm-4.5-flash
  ZAI_API_KEY=<يلصقه المالك بنفسه في .env — لا يمر عبر رسائل أو ملفات متتبعة>
  ```
- MT5: `MT5_LOGIN=2000020618` · `MT5_SERVER=OneRoyal-Demo` · [يحتاج المالك] `MT5_PASSWORD` (ديمو) · `STREAM_SYMBOLS=XAUUSD`
- لا تضع `NEXUS_DATA_SYNTHETIC_FALLBACK=1` إطلاقاً (preflight يعدّها تحذيراً مقصوداً ضد البيانات المزيفة).

**6) أول إقلاع:**
- شغّل redis ثم: `venv-nexus\Scripts\python run.py --paper`
- إن رسب preflight على `Credenciales MT5` فقط (كلمة مرور الديمو غير مدخلة بعد): الإقلع التشخيصي الموثق `venv-nexus\Scripts\python run.py --paper --skip-preflight` — ولا يُستخدم كوضع دائم.
- المشرف يقلع 9 خدمات (9000–9008) + داشبورد :3100 ويحرسها. **ملاحظة معروفة:** nexus-agents (:9004) يتأخر ~دقيقة ثم healthy — لا تحكم عليه مبكراً.
- الإيقاف: Ctrl+C في نافذة الإقلاع ثم `run.py --stop` للتأكد من تحرر المنافذ.

**7) bootstrap حساب المالك (مرة واحدة على قاعدة فارغة):**
POST إلى `http://127.0.0.1:9000/api/v2/auth/bootstrap` بجسم JSON:
```json
{"admin_pin":"<PIN من .env>","username":"redhwan","full_name":"Owner","password":"<كلمة المرور من .env>","language":"ar","timezone":"Asia/Aden"}
```
المتوقع `{"ok":true}` ثم اختبار دخول حقيقي من `http://localhost:3100`.

**8) بوابات التحقق النهائية (كلها خضراء = تركيب ناجح):**
- الخدمات: لكل منفذ 9000–9008: `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:<port>/health` ← 200 تسع مرات، و`:3100/login` ← 200.
- pytest: `venv-nexus\Scripts\python -m pytest tests -q` ← المتوقع **~1940–1954 passed** (skip يتغير حسب حالتك).
  - مفاخر معروفة على ويندوز: اختبارا POSIX في `tests\test_runner_safety.py` يفشلان بلا حراسة win32 (`os.getpgid` + فرع pgid) — عيب اختبار موثق وليس تشغيلياً؛ و`test_brain_budget_pacing` قد يفشل تحت حِمل متوازٍ و**يمر منفرداً**.
- node: `cd dashboard && node --test tests/*.test.mjs` ← **216/216**.
- الرؤوس: `curl -s -D - -o NUL http://127.0.0.1:9000/health` ← `X-Frame-Options: DENY` + `X-Content-Type-Options: nosniff` + `CSP: frame-ancestors 'none'` (+ `cache-control: no-store` للـAPI)؛ وكذلك `:3100/login` بلا cache-control.
- بناء الداشبورد: **لا تشغّل `npm run build` داخل dashboard أثناء عمل dev server على :3100** (تعارض ENOENT على `.next`) — انسخ مجلد dashboard لخارج المستودع وابنِ في النسخة، أو أوقف الأسطول أولاً.

**9) فخ قاعدة البيانات المعروف (لا تحذف ولا تنسخ ملفات!):**
إن فشل فتح `data\nexus.duckdb` بخطأ `Failure while replaying WAL … GetDefaultDatabase`: عيب duckdb 1.5.6 معروف، والحل الرسمي في `services\nexus_data\duckdb_store.py` (`_open_primary_connection`):
```python
con = duckdb.connect(':memory:')
con.execute("ATTACH '<المسار>/nexus.duckdb' AS nx")
con.execute('USE nx'); con.execute('CHECKPOINT nx')
```
— اتصال واحد فقط يملك الملف، ولا حذف WAL ولا نسخ قواعد قديمة ولا كاتب ثانٍ متزامن.

**10) تقريرك النهائي للمالك:**
نسخ كل مكوّن (git/python/node/redis)، آخر commit، أعداد pytest/node الفعلية، نتيجة الدخول :3100، وبيانات الدخول المولدة (PIN + كلمة المرور + BACKUP_PASSPHRASE) — **في المحادثة فقط**. أي بند تعذّر: السبب الكامل وآخر حالة مستقرة، ولا تكمل على أساس مكسور.
