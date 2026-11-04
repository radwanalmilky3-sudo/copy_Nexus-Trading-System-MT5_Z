# TEST CASES — NEXUS TRADER MT5 (M.2)

> صيغة كل حالة: **ID | المكوّن | الوظيفة | خطوات | متوقع | فعلي | الحالة | خطورة الفشل | دليل**.
> الحالات المعتمدة: PASS / FAIL / BLOCKED / NOT TESTED / FIXED-PENDING RETEST / FIXED-VERIFIED.

## TC-AD — نظام الأدمن (المرحلة 4)
| ID | الوظيفة | الخطوات | المتوقع |
|---|---|---|---|
| TC-AD-01 | دخول المالك redhwan | POST /api/auth/login ببيانات صحيحة | 200 + access/refresh + role=admin |
| TC-AD-02 | حماية API إدارية | نداء admin endpoint بلا توكن / بمستخدم غير مصرح | 401/403 (لا 200) |
| TC-AD-03 | أدوار وصلاحيات | قراءة app_roles/app_role_permissions من النسخة المعزولة | 7 أدوار + 36 صلاحية مرتبطة |
| TC-AD-04 | تدقيق عمليات | user_audit_log يزيد بعد عمليات دخول/خروج | سجلات بأزمنة صحيحة |
| TC-AD-05 | bootstrap مغلق | POST bootstrap ثانية | 409 |

## TC-AU — المصادقة والتوكنات (المرحلة 5)
| ID | الوظيفة | الخطوات | المتوقع |
|---|---|---|---|
| TC-AU-01 | دخول صحيح | login صحيح | 200 + توكنان |
| TC-AU-02 | كلمة خاطئة | login خاطئ | 401 + رسالة عربية، لا توكن |
| TC-AU-03 | توكن غير صالح | GET محمي بـBearer garbage | 401 |
| TC-AU-04 | بلا توكن | GET محمي بلا ترويسة | 401 |
| TC-AU-05 | توكن ملغى/منتهي | تلاعب exp أو token ملغى | 401 |
| TC-AU-06 | تجديد | refresh → access جديد يعمل | 200 |
| TC-AU-07 | خروج | logout ثم استخدام القديم | رفض حسب التصميم (revoke إن وُجد) |
| TC-AU-08 | توكن EA دورة | إنشاء → نشط → إلغاء → ملغى | حالات صحيحة بالخادم |
| TC-AU-09 | RBAC خلفي | مستخدم عادي × endpoint إداري | 403 — لا تجاوز بتغيير الواجهة |
| TC-AU-10 | PIN العمليات الحساسة | kill release بـPIN خاطئ | 403 |

## TC-MT — تكامل MT5 (المرحلة 6) — منفذة 2026-11-04 ✅
| ID | الوظيفة | الخطوات | المتوقع |
|---|---|---|---|
| TC-MT-01 | جسر حي على طرف المالك | — | **BLOCKED** (يتطلب MT5 terminal) — موثق بأسباب ومتطلبات |
| TC-MT-02 | APIs الجسر المتاحة | ea tokens/queue/status عبر 9000 | تعمل صحيحاً |
| TC-MT-03 | مخطط EA | مراجعة NexusBridgeEA.mq5 مقابل docs/EA_BRIDGE.md | اتساق endpoints/توكن |
| TC-MT-04 | paper-only | فحص executor mode | paper فقط، لا مسار حقيقي مفعّل |

**نتائج المرحلة 6 (حي — أدلة `qa/evidence/tc_mt_results.json`):**
| ID | فعلي | الحالة | دليل |
|---|---|---|---|
| TC-MT-01 | لا MT5 terminal في الصندوق؛ اختُبرت بدائل API الحية بدلاً منه؛ المتطلبات على طرف المالك وفق docs/EA_BRIDGE.md | **BLOCKED** | قيد بيئي (DEFECT_REGISTER §د) |
| TC-MT-02 | 7/7: إنشاء توكن (200 + raw nexus_ea_ مرة واحدة) → القائمة بلا توكن خام (SHA-256 فقط) → handshake يربط الهوية (200 + user=redhwan + heartbeat=3 + protocol=1) → هوية ثانية بنفس التوكن 409 → poll (200 + commands[] + server_time) → طابور الأوامر 200 → إبطال DELETE 200 ثم poll = **401 فوري** | **PASS** | `qa/evidence/tc_mt_results.json` (سكربت `scripts/tc_mt_bridge_live.py`) |
| TC-MT-03 | اتساق كامل EA↔OpenAPI↔EA_BRIDGE.md: handshake body (mt5_login/broker/server/terminal_version) = HandshakeIn؛ poll body results[{command_id,ok,detail,ticket,price}] = PollIn؛ توكن nexus_ea_ (EA يتحقق prefix+طول، الخادم يخزن SHA-256)؛ أوامر OPEN/CLOSE/PARTIAL_CLOSE/MODIFY؛ حد المطالبة 20 = `LIMIT 20` في ea_pending_commands؛ استعادة العالق 5 دقائق = `INTERVAL 5 MINUTE`؛ منع مزدوج = journal replay (سطر 477)؛ توقف بعد 20×401 | **PASS** | فحص ثابت موثق (ea.py:138-213، fundamental_store.py:187، NexusBridgeEA.mq5:7-29,463-494,505-566) |
| TC-MT-04 | `.env` NEXUS_TRADING_MODE=paper + run.py يفرض paper افتراضياً (950-961) + LIVE_MODE_VALUES={live,production,prod} + executor: effective_broker=paper عند عدم live_mode_enabled؛ **حي 9007/health: broker=paper, trading_mode=paper, real_broker_execution_enabled=false** | **PASS** | جسم استجابة 9007/health حي + shared/safety.py + services/nexus_executor/main.py:569 |

## TC-SC-01..16 — الشاشات (المرحلة 7) — منفذة 2026-11-04 ليلًا ✅ **17/17 PASS**
لكل شاشة من المصفوفة: تحميل + صفر أخطاء كونسول/صفحة + نداءات شبكة + لقطة + زمن تحميل. (التفاصيل في SCREEN_COVERAGE_MATRIX).

**نتائج الجولة الحية (أدلة `qa/evidence/tc_sc_results.json` + لقطات `docs/screenshots/round-m2-phase7/`):**
| الشاشات | فعلي | الحالة | دليل |
|---|---|---|---|
| TC-SC-01 /login | load 840ms + دخول → /nexus + صفر أخطاء | **PASS** | tc_sc_results.json + لقطة 01 |
| TC-SC-02..15 (14 شاشة) | load 1.3–4.6s (dev compile-on-demand) + صفر أخطاء صفحة؛ /nexus أعاد قياسه بعد إصلاحي D16/D17: صفر أخطاء WS + صفر تحذيرات مفاتيح + 404 صادق-فارغ فقط (موثق) | **PASS** | tc_sc_results.json + لقطة postfix + d16_ws_broadcast_results.json (4/4) |
| TC-SC-16a/b التحويلان | بجلسة → /nexus/history و/nexus/settings بـ200 وصفر أخطاء؛ بلا جلسة → /login (حماية) | **PASS** | إعادة قياس معزولة + بجلسة |
| موبايل 390×844 | /login و/nexus بلا أخطاء (لقطة) | **PASS** | mob__login.png, mob__nexus.png |

## TC-SV — الخدمات التسع (المرحلة 8) — منفذة 2026-11-04 ليلًا ✅ **9/9 PASS**
لكل خدمة SV-01..09: /health + openapi + نداء وظيفي حقيقي + حالة خطأ (مدخل خاطئ) + سجل.
**نتائج حية (أدلة `qa/evidence/tc_sv_results.json`، التقرير الكامل `qa/COMPONENT_QA_REPORT.md`):** جميعها 200 health + OpenAPI حي + نداء وظيفي أو 403 حماية داخلية (نمط أمني صحيح) + 404 صادق للأمعرفات الزائفة؛ 9004 = 503 fail-closed موثق بجسمه؛ P2-2 أُصلحت أثناء المرحلة (news/monitor unknown → healthy) — FIXED-VERIFIED.
| إضافي | الوظيفة | المتوقع |
|---|---|---|
| TC-SV-10 | تدهور رشيق | (مُستوفى: S4 جولة 3 — إسقاط 9003 → شفاء <1s) |
| TC-SV-11 | Redis الأساسي | ping + get/set + pub/sub keys | يعمل |

## TC-DB — قاعدة البيانات (المرحلة 9)
| ID | الفحص | المتوقع |
|---|---|---|
| TC-DB-01 | جرد 62 جدولاً | عدّ الأعمدة + PK (مُحدّث مساءً — كان 58) |
| TC-DB-02 | اتساق مستخدم/أدوار | العدد الحالي **43 نشطاً من 53 إجمالاً** (10 محذوفون منطقياً بروابطهم لمسار إحياء D10-c) مع ربط 1:1 تام و7 أدوار و36 صلاحية — منفذ ✅ (المرحلة 9) |
| TC-DB-03 | api_tokens حالة | سجل نشط/ملغى منطقي (revoked_at) |
| TC-DB-04 | تدقيق مستخدم | أزمنة UTC صحيحة، ترتيب |
| TC-DB-05 | سوق فارغ صادق | ohlcv/ticks/trades=0 → 404 صادق لا بيانات وهمية |
| TC-DB-06 | تكرار في الجداول المملوءة | فحص duplicates على مفاتيح |
| TC-DB-07 | كاتب وحيد | فتح ثانٍ = قفل (مثبت) |

## TC-E2E — التكامل الشامل (المرحلة 10)
| ID | السيناريو | المتوقع |
|---|---|---|
| TC-E2E-01 | S1 دورة قرار | features→ml→agents→قرار موثق (NO_TRADE مقبول) |
| TC-E2E-02 | S3 مخاطرة ترفض | قرار خارج القواعد → رفض موثق |
| TC-E2E-03 | S4 تدهور رشيق | (مُستوفى سابقاً بلقطات) |
| TC-E2E-04 | S5 جلسة مستخدم | دخول→وصول→خروج→رفض بعد الخروج |
| TC-E2E-05 | S6 أدوار | حماية إدارية فعّالة |
| TC-E2E-06 | S2 صفقة تجريبية كاملة | يتطلب بيانات سوق/نماذج — إن تعذر: BLOCKED موثق بسببه (قاعدة صفرية) |
| TC-E2E-07 | أخبار | pipeline news → واجهة/تخزين |

## TC-SEC — الأمن (المرحلة 11)
أسرار في الشيفرة/الواجهة، حماية مسارات إدارية، رؤوس أمان، فصل paper/live، فحص اعتماديات معروف الثغرات (إن توفرت أداة)، بلا اختبارات تخريبية.

## TC-PF — الأداء (المرحلة 11)
قياس: زمن /health لكل خدمة، login، candles، dashboard load؛ CPU/RAM للعمليات؛ عتبات قبول معلنة مسبقاً (health<300ms، login<2s، شاشة<8s dev).

## TC-RG — الانحدار (المرحلة 14)
pytest كامل + node unit tests + Playwright suite بعد كل إصلاح، وأي إصلاح في الدورة يُعيد العناصر المرتبطة.
