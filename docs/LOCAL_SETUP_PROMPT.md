# LOCAL_SETUP_PROMPT — برومبت تركيب المشروع على جهاز الكمبيوتر (ويندوز)

> انسخ ما بين السطرين المتقطعين والصقه كاملاً في أي وكيل محلي (OPENCODE / Claude Code / Cursor...) على الجهاز المستهدف — أو نفّذ الخطوات يدوياً كما هي مرتبة.
> آخر تحديث: 2026-11-06 (T-022). مصدر الحقيقة: مستودع GitHub نفسه — لا تعتمد على ذاكرة أي جلسة.

---

أنت مهندس DevOps محلي. مهمتك تركيب مشروع **Nexus Trading System (MT5 — PAPER ONLY)** على هذا الجهاز من مستودع GitHub، بدورة كاملة: تجهيز → تركيب → إقلاع → تحقق → تقرير. نفّذ بالترتيب، وتوقف بسؤال صريح للمالك عند أي بند معلّم [يحتاج المالك].

**قواعد حمراء قبل أي شيء:**
- تداول ورقي فقط: `NEXUS_TRADING_MODE=paper` لا يُغيَّر مهما كان السبب. لا يوجد أي سيناريو حي في هذا التركيب.
- لا أسرار في أي ملف متتبَّع بgit: التوكنات/كلمات المرور في `.env` فقط (gitignored أصلاً)، وقيمها لا تُطبع في السجلات ولا تُلزم.
- لا تقتل أي عملية على المنافذ يدوياً — الإيقاف الرسمي `venv-nexus\Scripts\python run.py --stop` أو `stop_nexus.bat`.
- هذا الجهاز **لا يدفع شفرة إلى GitHub**؛ أي تعديل شفرة يُوصف للفريق السحابي عبر القناة. المسموح دفعه لاحقاً (إن أُنشئت القناة): `AGENT_CHANNEL/` فقط وبتعليمات صريحة.

**1) المتطلبات — افحص ثم ثبّت الناقص:**
- Git for Windows (يشمل Credential Manager): `git --version` (2.40+)
- Python 3.12 (المطابق لبيئة السحابة 3.12.16): `py -3.12 --version` — إن لم يوجد ثبّته من python.org (فعّل py launcher). ملاحظة: 3.13/3.14 يعملان لكن بتجاوزات موثقة (eventkit/ib_insync + polars[rtcompat] على المعالجات القديمة بلا AVX2) — لا تدخلها إلا إن اضطررت.
- Node.js 22 LTS: `node -v` (v22.x، npm 10.x)
- Redis للويندوز: الأفضل خدمة **Memurai Developer** أو redis 5.0.14 (tporadowski) كخدمة اسمها `redis5` أو ملف `C:\redis5\redis-server.exe`. المطلوب: PONG على `127.0.0.1:6379`. (المشروع يستخدم Streams: XADD/XREADGROUP — تحتاج إصدار 5+).
- اختياري لاحقاً: MetaTrader 5 terminal — للجسر الحي (خطواته الكاملة في `docs/EA_BRIDGE.md` داخل المستودع).
- **لا حاجة لـOllama إطلاقاً** — قرار المالك 2026-11-06: مزود الذكاء سحابي GLM-4.5-Flash (zai) بدل المحلي.

**2) الاستنساخ (المستودع خاص — أول مرة سيطلب Git توكن/دخول عبر Credential Manager):**
- [يحتاج المالك] أعلمني أن أول clone سيطلب مصادقة لكي أجهّز Personal Access Token بصلاحيات repo (Contents: Read) — لا تطلب التوكن كتابةً في أي ملف، دع نافذة Credential Manager تتكفل.
```bat
git clone https://github.com/radwanmhh-svg/Nexus-Trading-System-MT5.git D:\Nexus-Trading-System-MT5
cd /d D:\Nexus-Trading-System-MT5
git log --oneline -3
```
- إن كان المسار `D:\Nexus-Trading-System-MT5` موجوداً مسبقاً ومنسوخاً من نفس المستودع: لا تعيد الاستنساخ — `git pull --rebase origin main` وواصل (التركيب idempotent).

**3) بيئة بايثون + المكتبات (المجلد venv-nexus داخل المشروع):**
```bat
py -3.12 -m venv venv-nexus
venv-nexus\Scripts\python -m pip install --upgrade pip
venv-nexus\Scripts\python -m pip install -r requirements.txt
```
- على ويندوز تبقى حزمة MetaTrader5 ضمن requirements — هذا صحيح ومطلوب محلياً (لا تحذفها).
- ثبّت أدوات الاختبار (ليست في requirements عمداً): `venv-nexus\Scripts\python -m pip install pytest pytest-asyncio`
- تحقق: `venv-nexus\Scripts\python -c "import fastapi, duckdb, redis, torch; print('IMPORTS_OK')"`

**4) الداشبورد:**
```bat
cd dashboard
npm ci --no-audit --no-fund
cd ..
```

**5) ملف .env (انسخ من النموذج ثم املأ):**
- ابدأ من `.env.example` → `.env`.
- ولّد الأسرار عشوائياً (لا تخترعها بيدك):
```bat
venv-nexus\Scripts\python -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(16)); print(secrets.token_hex(16)); print(secrets.token_hex(24))"
```
  ووزّعها بالترتيب: NEXUS_SECRET_KEY، NEXUS_JWT_SECRET (64hex)، NEXUS_INTERNAL_API_SECRET، NEXUS_RISK_APPROVAL_SECRET (32hex **مختلف** عن السابق)، BACKUP_PASSPHRASE (48hex).
- [يحتاج المالك] من المالك مباشرة (تُكتب في .env فقط): `MT5_LOGIN` و`MT5_PASSWORD` و`MT5_SERVER` (حساب **ديمو** MT5) — واجعل `STREAM_SYMBOLS=XAUUSD`. و**ZAI_API_KEY**: مفتاح مزود GLM — **يلصقه المالك بنفسه في .env** ولا يمر عبر أي رسالة أو ملف متتبَّع أو برومبت.
- مزود الذكاء **محسوم: السحابي GLM-4.5-Flash بدل Ollama** — الأسطر الثلاثة في .env:
  ```
  NEXUS_LLM_PROVIDER=zai
  NEXUS_LLM_MODEL=glm-4.5-flash
  ZAI_API_KEY=<يلصقه المالك مباشرة هنا>
  ```
  لا تثبّت Ollama ولا تفحص :11434 — preflight مع zai+مفتاح يمر دون لمس أي مزود محلي (سلوك موثق منذ T-021).
- حساب المالك الأول: `NEXUS_ADMIN_PIN` (6 أرقام) + `NEXUS_ADMIN_PASSWORD` (قوي مولد) — **سلّم القيم للمالك في نهاية التركيب كتابعةً في المحادثة فقط**؛ هذه هي القناة المعتمدة لتسليم بيانات الدخول.
- لا تضع `NEXUS_DATA_SYNTHETIC_FALLBACK=1` (preflight يعتبرها تحذيراً مقصوداً ضد البيانات المزيفة).

**6) أول إقلاع رسمي (preflight يجب أن يمر بلا تجاوز):**
```bat
start redis / Memurai ثم:
venv-nexus\Scripts\python run.py --paper
```
- لا تستخدم `--skip-preflight` إلا لغرض تشخيصي مؤقت موثق — الإقلاع الرسمي يمر preflight كاملاً.
- المشرف يقلع 9 خدمات (9000–9008) + داشبورد :3100 ويحرسها. الإيقاف: نافذة الإقلاع Ctrl+C ثم `venv-nexus\Scripts\python run.py --stop` للتأكد من تحرر المنافذ.
- تأكد: `http://localhost:3100` يعمل وتظهر شاشة الدخول.

**7) bootstrap حساب المالك (مرة واحدة على قاعدة فارغة):**
- POST إلى `http://127.0.0.1:9000/api/v2/auth/bootstrap` بجسم JSON:
  `{"admin_pin":"<PIN من .env>","username":"redhwan","full_name":"Owner","password":"<كلمة المرور من .env>","language":"ar","timezone":"Asia/Aden"}`
- المتوقع `{"ok":true,...}` — ثم اختبر دخولاً حقيقياً من :3100.
- سكربت شبيه جاهز في `qa/live_gate.sh` (بصيغة bash — على ويندوز نفّذ الـPOST بcurl أو بايثون).

**8) التحقق النهائي (كلها خضراء = تركيب ناجح):**
- الخدمات: لكل منفذ 9000–9008: `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:<port>/health` ← 200 تسع مرات، و:3100 ← 200.
- pytest: `venv-nexus\Scripts\python -m pytest -q` — المتوقع ~1942 passed (عدد skip البيئية يتغير حسب حالتك — اكتب الفعلي).
- node: `cd dashboard && node --test tests/*.test.mjs` ← 216/216.
- Playwright حي (والأسطول منتصب): إن لم يكن playwright مثبتاً: `venv-nexus\Scripts\python -m pip install playwright && venv-nexus\Scripts\python -m playwright install chromium` ثم `venv-nexus\Scripts\python qa\playwright\run_suite.py` ← 5/5.
- رؤوس الأمان: `curl -s -D - -o NUL http://127.0.0.1:9000/health | findstr /I "x-frame x-content referrer permissions content-security"` ← DENY + nosniff + frame-ancestors 'none'.

**9) تقريرك النهائي للمالك (رسالة واحدة):**
- نسخ كل مكون (git/python/node/redis)، آخر commit بعد الاستنساخ، أعداد pytest/node/Playwright الفعلية، نتيجة الدخول :3100، وبيانات الدخول المولدة (PIN + كلمة المرور + BACKUP_PASSPHRASE) — في المحادثة فقط.
- أي بند تعذّر: السبب الكامل وآخر حالة مستقرة، ولا تكمل على أساس مكسور.

**10) لاحقاً (خارج نطاق هذا التركيب، بأمر المالك):** جدولة `update_nexus.bat` (احفظ الملف بترميز CRLF — نهايات أسطر LF تكسر cmd.exe)، جسر MT5 الحي (`docs/EA_BRIDGE.md`)، تدريب النماذج بعد تراكم 24–48 ساعة شموع.
