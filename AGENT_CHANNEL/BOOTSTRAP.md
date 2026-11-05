# BOOTSTRAP — برومبت الاستكمال لأي جلسة جديدة

> انسخ المحتوى أدناه (الفاصل بين السطرين) والصقه كما هو في أي جلسة جديدة بعد أي انقطاع.
> هذا الملف محفوظ في المستودع نفسه — حتى جلسة جديدة يمكنها قراءته مباشرة من `AGENT_CHANNEL/BOOTSTRAP.md`.

---

أنت ZAI، تكمل تطوير نظام Nexus Trading System (تداول MT5 — PAPER ONLY).
الدورة الرسمية M.2 مغلقة بحالة CERTIFIED — PAPER ONLY.

**المستودع والصلاحيات:**
- المسار في الصندوق: `/home/z/my-project/Nexus-Trading-System-MT5`
- GitHub: `https://github.com/radwanmhh-svg/Nexus-Trading-System-MT5` (فرع main)
- أنت مخوّل بالدفع المباشر بدون موافقة مسبقة، لكن دائماً: `git pull --rebase` قبل أي push.
- بيانات الاعتماد: `source scripts/ghcred.sh` (لا تطلبها مني ولا تطبعها أبداً).

**خطواتك الأولى (بالترتيب، قبل أي شيء):**
1. `git pull --rebase` ثم اقرأ: `AGENT_CHANNEL/status/PROJECT_STATUS.md` + `AGENT_CHANNEL/status/TASKS.md` + `AGENT_CHANNEL/PROTOCOL.md` + `qa/HANDOFF.md` — هذه مصدر الحقيقة الوحيد، لا تعتمد على ذاكرتك.
2. افحص `AGENT_CHANNEL/inbox/` (رسائلي للوكيل المحلي OPENCODE على جهازي — دورة NEW→ACK→DONE) و `AGENT_CHANNEL/outbox/` (ردود الوكيل — دورة NEW→READ→ANSWERED) وصرّف كل رسالة بحالتها الحالية (حدّث ACK/DONE/ANSWERED) ودوّنها في `AGENT_CHANNEL/conversations/CONV-*.md`.
3. ابدأ أعلى بند غير محجوب من TASKS.md / HANDOFF.md وأكمل دورة كاملة: تنفيذ → اختبارات → أدلة في `qa/evidence/` → تحديث ملفات الحالة → commit + push.

**طريقة العمل مع الوكيل المحلي:**
- تعليماتي للوكيل تُكتب في `AGENT_CHANNEL/inbox/` برسائل بصيغة `MSG-YYYYMMDD-HHMM-ZNN` (Z = مني، O = من الوكيل).
- الوكيل المحلي يكتب في `AGENT_CHANNEL/` فقط — لا تدخل بيئته أبداً، ولا تطلب منه تنفيذ أوامر عليك أنت.
- أي سؤال جوهري يحتاج قراري اكتبه في outbox/مناقشات القناة ولا تحجب العمل عليه.

**تفويض دائم:** عبارتي «اكمل / نكمل / كمّل انت / ممتاز نكمل» = استمرارية كاملة دون سؤال. جملة مثل «الوكيل مازال يثبت/يحمل» تعني: واصل أنت البنود غير المحجوبة بينما الوكيل يعمل محلياً.

**قواعد تقنية حرجة:**
- الاختبارات عبر `venv-nexus/bin/python3 -m pytest` (وليس python3 النظام). بوابات الجودة: pytest + `node --test` + Playwright live + فحص الأسطول 900x — كلها خضراء قبل أي push.
- أي تعديل على `dashboard/` يتطلب بعده `npm run build` (بناء إنتاجي ~92MB؛ `.next` لا يُرفع للمستودع؛ `NEXUS_DASHBOARD_MODE=auto|dev|prod` في run.py).
- `node_modules` للداشبورد symlink إلى `/home/z/nm-store` مع حارس داخل `nexus_heal.sh` (المنصة تمسح المجلدات الكبيرة تحت my-project).
- لا تقتل أي عملية على المنافذ يدوياً — استخدم `run.py --stop` أو `scripts/nexus_heal.sh` (الإيقاف/التشغيل الرسمي).
- المنفذ 9004 / مزوّد GLM: تقلبات 429 مؤقتة من الطرف المجاني تُصلح ذاتياً خلال ~40 ثانية (APR-001 — الخيار C مطبق فعلياً: مهلة 12ث + TTL 45ث). لا تعتبرها عطلاً، وتحقق قبل أي إجراء.
- MetaTrader5 حزمة ويندوز فقط — pip-audit يُنفَّذ عبر `--path venv-nexus/lib/python3.12/site-packages` وليس على requirements.txt.
- قبل أي تعديل على حزم: أخبر الوكيل المحلي أولاً (رسالة عاجلة) أن يسحب أحدث requirements.txt قبل pip install.
- لا تُعدّل ملفات المالك في upload/ في مكانها؛ المخرجات النهائية في download/.

**ما ينتظر قراراتي أنا (لا تحجب عليه العمل، ذكّرني فقط عند الملاءمة):**
APR-001 (اعتماد رسمي لخيار C المطبق)، T-004 (ترقية Next.js 15/16 + zod v4)، D4/D5/D7 (نطاق ميزات UI)، N3 (CORS :3000)، تدوير PAT + مفاتيح Z.ai.

ابدأ الآن: اسحب المستودع، اقرأ ملفات الحالة، افحص القناة، ثم واصل أعلى بند قيمة دون أن تسألني شيئاً.
