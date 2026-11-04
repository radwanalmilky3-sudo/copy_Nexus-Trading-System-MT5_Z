# MEMORY — فهرس حالة مشروع Nexus Trader MT5

> الوثيقة الحية التفصيلية: `HANDOFF.md`. هذا الملف فهرس سريع للحالة الثابتة.
> القواعد الثابتة: `PROJECT_RULES.md`. سجل هذه الجلسة: `docs/CHAT_LOG_2026-11-04.md`.

## الهوية
- المستودع: https://github.com/radwanmhh-svg/Nexus-Trading-System-MT5 (خاص)
- الاستنساخ المحلي: `/home/z/my-project/Nexus-Trading-System-MT5`
- المالك: `redhwan` (super_admin، user_id `469087c903cf40298fb3679a2fcc3fb4` — أعيد إنشاؤه 2026-11-04 على القاعدة الجديدة الثانية)

## البيئة (ساندبوكس)
- venv: `Nexus-Trading-System-MT5/venv-nexus` (Python 3.12، torch CPU، PyJWT — مستثناة في .gitignore)
- Redis: `/home/z/my-project/redis/bin/redis-server` — 127.0.0.1:6379 (بناء محلي 7.4.1، بدون sudo)
- **العمليات الدائمة**: حصريًا عبر `scripts/daemonize.py` (خارج المستودع؛ fork مزدوج) — nohup & العادي يُقتل بين الأوامر
- قاعدة البيانات: `data/nexus.duckdb` (`DUCKDB_PATH` مطلق في `.env`)
- الداشبورد: `dashboard/` (Next.js 14، `npm run dev -- --port 3100`، node_modules حاضر)
- مُمرِّر المعاينة: `scripts/port3000_forward.py` (3000 → 3100، خارج المستودع)
- بيانات git للدفع: `/home/z/my-project/.git-credentials` (خارج شجرة المستودع — لا تُرفع أبدًا)

## المنافذ
`9000` api | `9001` data | `9002` features | `9003` ml | `9004` agents | `9005` news | `9006` risk | `9007` executor | `9008` monitor | `3100` dashboard | `3000` proxy | `6379` redis

## محطات رئيسية
- `5d033e3` آخر التزام عرفه المالك قبل انقطاع طويل (TEST_PLAN + HANDOFF)
- `118d201` البند 3 — API tokens + طابور أوامر MT5 (api_tokens/ea_commands + /api/ea/*)
- `eab6067` تحديث HANDOFF بعد الاستعادة السابقة
- `70ed5ef` استعادة PROJECT_RULES.md (فُقدت مع البيئة المحلية القديمة)
- `72aa63d` البند 4 خلفي — مرآة executor → ea_commands + إعادة طوابير العالق + /api/admin/ea-commands
- `001504a` البند 4 كامل — NexusBridgeEA.mq5 + docs/EA_BRIDGE.md + شاشة /nexus/ea-bridge

## مهام مجدولة (كرون)
- **502676** يوميًا 04:00 Asia/Aden — نسخة احتياطية متجددة إلى فرع `backups` (أرشيف يتضمن .env + DuckDB + config) — مُختبرة حيًا (20261104-125133)
- **502675** كل 5 دقائق — شفاء ذاتي (Redis + بروكسي 3000 + إقلاع المنظومة عند الضرورة) — يطبع HEAL_STATUS

## نقاط تحقق سريعة
- `curl http://127.0.0.1:9000/health` = 200 و`...:9001/health` = 200
- `curl -L http://127.0.0.1:3100/` = 200 و`http://127.0.0.1:3000/` = 200
- 9004/health = 503 مقصود حتى توفر `ZAI_API_KEY` (fail-closed، ليس عطلًا)
- E2E الجسر: `python3 scripts/ea_bridge_e2e.py` (يتطلب NEXUS_E2E_PASS)

## إضافات جلسة 2026-11-04 الثانية (إعادة بناء كاملة + بند 5 جولة 1)
- البيئة أُعيد بناؤها من الصفر (صندوق جديد): venv داخل مجلد المشروع + PyJWT (D1: e492767) + Redis 7.4.1 + npm ci + .env بـ 15 متغيرًا + مخطط DuckDB + bootstrap redhwan جديد (دخول 200، bootstrap مغلق 409)
- **العمليات الخلفية العادية تُقتل بين الأوامر** — الحل: `scripts/daemonize.py` fork مزدوج (Redis ينجو ذاتيًا)
- البند 5 جولة 1 (P0): **16/16 شاشة ناجحة، صفر أخطاء** — لقطات في docs/screenshots/round-2026-11-04/ + DEFECTS.md + تقرير docs/TEST_REPORT_ROUND1_2026-11-04.md
- نداءان 404 موثّكان كحالة "لا بيانات بعد" (شموع/قرار وكلاء) وليسا عيبًا — لافتة "services offline 3" فحص fail-closed صحيح على قاعدة فارغة
- كرون جديد: 502676 نسخ يومي 04:00 + 502675 شفاء كل 5 د — ونسخة backups مرفوعة مُختبرة (116KB مشفرة)
- بيانات دخول redhwan الجديدة (PIN وكلمة أولية) أُبلغت للمالك في المحادثة فقط

### (سابق — صباح نفس اليوم، على القاعدة المفقودة القديمة؛ معرّفاتها وكلماتها منتهية)
- النسخ الاحتياطي نُفّذ يدوياً أيضاً: `5e00e03` على فرع `backups` (28KB مشفرة، tar.gz + openssl aes-256-pbkdf2) — السكربت: `/home/z/my-project/scripts/nexus_backup.sh` (خارج المستودع) — التعليمات في رأسه، وفُحص عكسياً (فك/فحص) بنجاح
- تصحيح: معرّف redhwan الحي الحالي هو `56ecb98fe57d4b47b6aaebcbdb7b8638` (المعرف في الفهرس أعلاه من حالة قاعدة سابقة) — تمت إعادة تعيين كلمته عبر UPSERT داخلي (`fundamental/record`) بالسر الداخلي؛ الكلمة الحالية في `.env` باسم `NEXUS_ADMIN_PASSWORD`
- تسجيل دخول redhwan فُحص بنجاح (HTTP 200، role=super_admin)
- EA: `/api/ea/handshake` و `/api/ea/poll` يردان 401 بدون توكن (سلوك صحيح مؤكد حياً)
- ملاحظة أمان: ADMIN_PIN و ADMIN_PASSWORD ظهرا عارضاً في مخرجات محادثة المالك → يُنصح بتدويرهما بعد حفظهما

## استرجاع 2026-11-04 (بعد مسح بيئة الصندوق)
- البيئة مُسحت بالكامل (~18:39)؛ الاسترجاع اكتمل من فرع main عبر PAT جديد من المالك.
- أعيد بناء: redis 7.4.1 المصدرية في `/home/z/redis-bin`، venv في `/home/z/venv-nexus` (شامل torch CPU وsklearn وحزم TA)، وnpm ci للوحة.
- `.env` أعيد توليده: القيم المعروفة (ADMIN_PASSWORD/ADMIN_PIN) + أسرار جديدة مولدة (INTERNAL_API_SECRET، JWT، RISK_APPROVAL، BACKUP_PASSPHRASE). ZAI_API_KEY ما زال معطلاً (9004=503 مقصود).
- `data/nexus.duckdb` **فُقدت نهائياً** — النسخة المشفرة على فرع backups غير قابلة للفك لأن BACKUP_PASSPHRASE القديمة كانت داخل .env المفقود. القاعدة الحالية جديدة فارغة.
- حساب redhwan أعيد إنشاؤه (`fix_admin_user.py` ثم `reset_redhwan_pw.py`): دخول موثق 200 بدور super_admin.
- التوكن مخزّن في `~/.git-credentials` (credential.helper store) لتعمل النسخ الاحتياطية اليومية دون تدخل.
- إصلاح ما بعد الاسترجاع: `.env` يجب أن يتضمن `DASHBOARD_ORIGIN=http://127.0.0.1:3000` — بدونه يفشل preflight الـ CORS (400) عند الدخول من البوابة :3000 والزر يعلق على /login. تم التحقق: دخول متصفح فعلي ناجح → /nexus بحساب redhwan super_admin (لقطة: download/nexus_logged_in.png).
- إصلاح "Failed to fetch" عند المالك: أثناء الاسترجاع كُتب `NEXT_PUBLIC_API_URL=http://127.0.0.1:9000` في dashboard/.env.local فصار الـ bundle ينادي العنوان المطلق من متصفح المالك (غير موجود لديه). الصواب: تُترك المتغيرات UNSET — الواجهة تستخدم مساراً نسبياً /api عبر rewrites في next.config.js (نفس الأصل، بلا CORS، يعمل من أي دومين). أُعيد إقلاع 3100 ووُثّق دخول فعلي: /login → /nexus (redhwan super_admin).
