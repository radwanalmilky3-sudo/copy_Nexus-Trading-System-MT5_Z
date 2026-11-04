# MEMORY — فهرس حالة مشروع Nexus Trader MT5

> الوثيقة الحية التفصيلية: `HANDOFF.md`. هذا الملف فهرس سريع للحالة الثابتة.
> القواعد الثابتة: `PROJECT_RULES.md`. سجل هذه الجلسة: `docs/CHAT_LOG_2026-11-04.md`.

## الهوية
- المستودع: https://github.com/radwanmhh-svg/Nexus-Trading-System-MT5 (خاص)
- الاستنساخ المحلي: `/home/z/my-project/Nexus-Trading-System-MT5`
- المالك: `redhwan` (super_admin، user_id `2483dafde1f94b59b14a5f22016b9771`)

## البيئة (ساندبوكس)
- venv: `/home/z/my-project/venv-nexus` (Python 3.12، torch CPU)
- Redis: `/home/z/my-project/redis/redis-server` — 127.0.0.1:6379 (بناء محلي 7.4.1، بدون sudo)
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
- **501366** يوميًا 04:00 Asia/Aden — نسخة احتياطية متجددة إلى فرع `backups` (أرشيف يتضمن .env + DuckDB + config)
- **501367** كل 5 دقائق — شفاء ذاتي (Redis + بروكسي 3000 + إقلاع المنظومة عند الضرورة) — يطبع HEAL_STATUS

## نقاط تحقق سريعة
- `curl http://127.0.0.1:9000/health` = 200 و`...:9001/health` = 200
- `curl -L http://127.0.0.1:3100/` = 200 و`http://127.0.0.1:3000/` = 200
- 9004/health = 503 مقصود حتى توفر `ZAI_API_KEY` (fail-closed، ليس عطلًا)
- E2E الجسر: `python3 scripts/ea_bridge_e2e.py` (يتطلب NEXUS_E2E_PASS)
