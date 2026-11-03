# Broker Account Settings — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** تبويب وسيط خاص بكل مستخدم وحساب، يحفظ اختيار الأصول ورد الدعم ومعلومات انتقال الساعة كتفضيلات ومسودات دائمة قابلة للتعديل.

**Architecture:** Gateway يشتق المالك من CurrentUser ويتحقق من RBAC، وnexus-data وحدها تكتب DuckDB. واجهة منفصلة داخل Settings، مع optimistic concurrency وسجل تعديلات. هذه المرحلة لا تبدل MT5 ولا تفعل تقويمًا أو تداولًا؛ فصل saved عن runtime_applied إلزامي.

**Tech Stack:** FastAPI، Pydantic، DuckDB، Next.js 14، React، TypeScript؛ دون اعتمادية OCR في هذه المرحلة.

**Spec:** docs/superpowers/specs/2026-10-19-broker-session-settings-design.md

## Global Constraints

- owner_user_id مشتق من CurrentUser، لا من اسم العرض أو body/query.
- لا تغيير للحساب الفعلي أو صلاحيات التداول أثناء التطوير، ولا تشغيل تداول أو تدريب.
- «هل التغيير أثناء إغلاق السوق؟» بقيم نعم/لا/غير معروف؛ تاريخ اليوم وحده لا يتحول إلى منتصف الليل تلقائيًا.
- الحالة الافتراضية للأصل معطل؛ حفظ allowlist لا يفعل auto_trade ولا يرفع حدود المخاطر.
- لا إدراج الرد في حسابات كل المستخدمين أو ملء مرفق أو published_at أو ساعة انتقال من التخمين.
- لا تنظيف أو إعادة ضبط للتغييرات السابقة، ولا commit أو push دون طلب منفصل.
- لا production build فوق .next لخادم dev حي.

## Scope and handoff boundary

هذه خطة المرحلة الأولى فقط من المواصفة: حسابات وأصول ومسودات توقيت ورد دعم.
تبويبات الاتصال وOCR والجلسات تظهر الحالة الصريحة «غير موصول/غير متاح بعد»،
لا أزرار نجاح وهمية. لا رفع صورة أو فك أسرار أو تنفيذ أوامر في هذه المرحلة.
مرحلة الاتصال المعزول ثم مرحلة استيراد الصورة/اعتماد التقويم تحتاجان خطتيهما
واختبارات قبول منفصلة. لا يُعلن اكتمال طلب استيراد الصورة بنهاية هذه الخطة.

## Review Focus

- تبديل الحساب أثناء save لا يعرض رد المستخدم/الحساب السابق أو يعدله (Task 4).
- معرف حساب مستخدم آخر لا يصل إلى settings أو assets أو events أو profile update (Tasks 2–3).
- رسالة الدعم تحدد تاريخ جلسة لا ساعة UTC؛ null لا يصير 00:00 (Tasks 1،4).
- حفظ أصل على trade لا يفعّل executor العام ولا يدعي سياسة مطبقة (Tasks 1،3–4).
- نسختان مفتوحتان لا تطمسان تعديلًا أحدث؛ 409 يعرض تعارضًا دون مسح المدخلات (Tasks 2–4).

## File map

- Create shared/broker_settings_models.py: عقود المرحلة الأولى فقط.
- Create services/nexus_data/broker_settings_store.py: ملكية، معاملات، نسخ، أحداث.
- Create services/nexus_data/migrations/broker_settings_001.sql: جداول ومفاتيح.
- Create services/nexus_data/broker_settings_router.py: API داخلي موثق.
- Modify services/nexus_data/main.py: تسجيل router عبر store المالك الموجود.
- Create services/nexus_api/routers/broker_settings.py: واجهة موثقة ذات ملكية.
- Modify services/nexus_api/main.py: تسجيل router؛ لا تغيير مسارات تداول legacy.
- Modify services/nexus_api/data_client.py: طلب داخلي محدد للميزة.
- Create dashboard/src/components/settings/broker/{BrokerSettingsTab.tsx,types.ts,api.ts}.
- Modify dashboard/src/app/dashboard/settings/page.tsx: trigger ومكون فقط.
- Create tests/test_data/test_broker_settings_models.py وtest_broker_settings_store.py وtest_broker_settings_route.py.
- Create tests/test_api/test_broker_settings.py وdashboard/tests/broker-settings.test.mjs.

## Task 1: Strict contracts and faithful support-reply fields

**Interfaces:** Produce ProfileCreate(name,broker_name), AccountCreate(profile_id,label,server,login,account_kind), AssetPreference(broker_symbol,mode), SupportTransitionDraft(from_offset_seconds,to_offset_seconds,session_start_date,effective_at_utc,during_market_closure,next_open_utc,support_reply,evidence_received_at). Literal modes disabled|analysis|trade; account_kind demo|live; closure unknown|yes|no. All IDs server-generated UUIDs. Extra fields forbidden.

- [ ] Write failing tests test_rejects_client_owner, test_transition_date_does_not_invent_utc_hour, test_defaults_fail_closed, test_rejects_naive_datetime_and_duplicate_assets. Assert session_start_date="2026-11-02", effective_at_utc is None, during_market_closure="yes" survive JSON round-trip; offsets 10800→7200. Reject utc offset outside ±50400; support_reply max8000 characters; up to256 unique asset preferences, symbol max128.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_data/test_broker_settings_models.py -q`; expect missing contract failure.
- [ ] Implement strict Pydantic contracts in shared/broker_settings_models.py. AccountCreate login is a string1..32 digits for metadata only, never login credentials. PUT uses expected_version:int>=1. Missing fields stay None; session_start_date is a date, not UTC instant. No credential field accepted.
- [ ] Rerun file; expect all pass.

## Task 2: Durable owner-scoped state and revisions

**Interfaces:** Consume Task1 contracts. Produce BrokerSettingsStore(owner_store), async list_profiles(owner_id:str)->list[dict], create_profile(owner_id,payload)->dict, create_account(owner_id,payload)->dict, get_account(owner_id,account_id)->dict, save_settings(owner_id,account_id,expected_version,payload)->dict, list_events(owner_id,account_id)->list[dict]. Typed BrokerNotFound and BrokerConflict. Use the existing store's _execute_locked; no second DB owner.

- [ ] Write failing tests for two owners each with two accounts, cross-owner 404 semantics on all methods, reopen database persistence, transactional version+event update, stale version rejection and explicit None timestamp. Assert each mutation adds exactly one event with actor and account, and failed mutation changes no rows.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_data/test_broker_settings_store.py -q`; expect missing store failure.
- [ ] Implement migration broker_settings_001.sql with profiles/accounts/settings/events. Settings JSON validated via Task1, version monotonic per account; parent lookup and write share transaction. Account unique key scoped owner/profile/server/login; reject duplicate 409. Accounts start unconnected and runtime_applied=false. Do not adopt legacy global config/data or write secrets. Account creation derives owner from parent and verified actor.
- [ ] Run store and models tests; expect pass including real temporary DuckDB reopen.

## Task 3: Authorized transport end to end

**Interfaces:** Produce create_broker_settings_router(store:BrokerSettingsStore)->APIRouter internal prefix /api/data/broker-settings; DataServiceClient.broker_settings(operation:str,owner_id:str,payload:dict)->dict with fixed operation map; public router /api/brokers with profile/account/settings/events paths. Ownership only from Gateway actor; internal operations require X-Nexus-Internal-Secret.

- [ ] Write RED tests GET profiles/POST profile/POST account/GET account/PUT settings/GET events. Reject missing bearer, internal missing/wrong secret, body owner injection, read-only role write, other-owner IDs and account-parent mismatch; stale PUT maps409. Assert save response {persistence:"durable",runtime_effective:false,connection_state:"unconnected",version:2}; no call to MT5 or executor.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_data/test_broker_settings_route.py tests/test_api/test_broker_settings.py -q`; expect absent route/client failure.
- [ ] Implement router/client/main registration per file map. Fixed operations only, bounded payload size and safe errors; GET returns masked_login not complete account metadata to broad viewers. source_manager.view reads own records; source_manager.edit edits own metadata; changing asset list to/from trade additionally requires trading.settings. Events are own-account only, no permission to global audit implied.
- [ ] Rerun route/API tests, then existing data-client/auth tests; expect no regression. Use independent credentials in tests, never print .env.

## Task 4: Settings UI with account-local editable transition draft

**Interfaces:** Consume Task3 API. types.ts mirrors DTOs; api.ts uses getAuthHeaders and existing bounded requests, no credentials localStorage. BrokerSettingsTab is mounted by Settings page under main tab «الوسيط والحسابات».

- [ ] Add failing behavioral tests: create own profile/account, select account, edit asset mode and support reply, save/reload, handle403/409/unavailable, discard late responses on account switch. Use compiled component render/event harness matching project test setup; do not grep component source as proof.
- [ ] Run `node --test dashboard/tests/broker-settings.test.mjs`; expect missing component/API behavior failure.
- [ ] Implement main tab with nested «الحسابات»، «الاتصال»، «الأصول»، «الجلسات والتوقيت»، «الأدلة والسجل». Connected-only sections disabled with reason. Support form exposes from/to UTC offset, session date, exact UTC instant optional, closure tri-state, next open UTC optional, reply and received-at. Display saved/unconnected explicitly; unknown hour shows «غير محددة»، not midnight. Edit affects only selected account and saves versioned draft. «نسخ سؤال الدعم» uses selected server, no outbound email.
- [ ] Provide explicit user action «تعبئة مسودة رد OneRoyal» only for selected own OneRoyal-Demo account; preview the supplied support text and yes/2026-11-02/10800/7200, exact timestamps empty, then require save. Do not preload or save to every account. If no account exists, prompt creation, not auto ownership assignment. This is manual text preset, not OCR import or runtime activation.
- [ ] Run behavioral test then `node --test dashboard/tests/*.test.mjs` and `dashboard/node_modules/.bin/tsc.cmd --noEmit -p dashboard/tsconfig.json`; expect all pass.

## Task 5: Whole-feature verification and deployment handoff

**Interfaces:** Consume Tasks1–4; produce evidence-backed handoff listing active and deferred capabilities.

- [ ] Run `.venv/Scripts/python.exe -m pytest tests -q --maxfail=5 --tb=short` and full frontend tests/typecheck. Inspect all failures; never relabel unrelated failures as pass.
- [ ] Independent review of owner filters, internal auth, transaction boundaries and UI account-switch races; resolve findings with reproductions.
- [ ] Smoke with two disposable users/accounts in isolated service DB; persistence across service restart, cross-owner denial and saved/runtime false assertions. Do not seed accounts into live DB just to demonstrate tests.
- [ ] After verification, back up/checkpoint owner database and reload only web/data components using verified process identities and existing safe procedure; no MT5 restart/account switch. If manager cached environment requires a broader reload, report before broadening rather than force-killing processes.
- [ ] Verify authenticated live own-account GET and Settings rendering. No auto-create profile from current global MT5; no applying a calendar policy or choosing trade assets on user's behalf.
- [ ] Report what is working versus planned: persistent per-user tab and editable support draft working; connection isolation, actual executor enforcement, image extraction and active calendar remain later phases. Link guide and latest verification. Preserve dirty checkout; no unsolicited commits.

## Self-review / execution decision

Scope covers first subsystem, not a claim to complete the remaining two phases.
Contract/model names and owner filters shared across tasks; support date is distinct from UTC instant.
Review Focus cases assigned to tests. No runtime trading policy or clock activation in Phase1.
User review required before implementation. Recommend native execution because store/API/UI contracts are sequential and one final independent review can check ownership end to end.
