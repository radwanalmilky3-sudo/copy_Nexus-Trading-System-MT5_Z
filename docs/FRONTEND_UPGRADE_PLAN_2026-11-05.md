# خطة تطوير الواجهة الأمامية — دمج مواصفات المالك + ثيم «طرفية الذهب»

> التاريخ: 2026-11-05 | المصدر: مواصفات المالك (المكتبات والخصائص المؤسسية) + `design-theme-kit (2).zip`
> المبدأ الملتزم: **لا إعادة بناء من الصفر** — دمج تدريجي فوق البنية الحالية، وكل مرحلة تُختبر قبل الانتقال للتالية.
> قاعدة القبول الثابتة: اختبارات node 202/202 + Playwright 5/5 + صفر أخطاء كونسول تبقى خضراء بعد كل مرحلة.

---

## 1. جرد الوضع الحالي (من الكود الفعلي، ليس افتراضًا)

| العنصر | الوضع الحالي | الحكم |
|---|---|---|
| مكوّنات الوصول (Accessibility) | **Radix UI مثبت ومستخدم** (dialog, dropdown, select, switch, tabs, tooltip, popover...) + Tailwind 3.4 | أساس ممتاز — مطابق للبديل «Radix + Tailwind» في مواصفتك |
| الشارت الرئيسي | `LiveChart.tsx` يعتمد تضمين TradingView الثقيل (iframe) — **معطّل افتراضيًا** بسبب عيب D2 (تجميد الذاكرة) | الفجوة الأكبر — الشارت الفعلي غائب افتراضيًا |
| lightweight-charts | **v4.1.7 في package.json لكن غير مستخدم في أي مكوّن** | جاهز للترقية والتوصيل |
| الشبكة القابلة للسحب | `react-grid-layout` v1.4.4 **مثبت وغير موصول** + `DEFAULT_LAYOUT` معرّفة في `dashboardStore` (zustand + persist) | بنية جاهزة نصفها مبني |
| الجداول | `@tanstack/react-table` v8 (بدون virtualization) | يفي الحاجة الأساسية فقط |
| الرسوم الثانوية | recharts (P&L، أساسي، هرمي التقدم) | مناسب — لا تغيير |
| الخطوط | Inter / system-ui — **لا خط عربي مخصص** | فجوة مؤكدة |
| WS | `useWebSocket.ts` فيه إعادة اتصال (محاولات + فاصل) — **لا heartbeat ولا backoff أُسي** | جزئي |
| Error Boundaries | **غير موجودة إطلاقًا** (لا error.tsx ولا global-error.tsx) | فجوة حرجة |
| Virtualization | **غير موجودة** | فجوة حرجة |
| حفظ التخطيط | zustand persist موجود على مستوى المتجر (gridLayout) | جاهز للتوصيل مع RGL |
| التحميل الكسول | `nexus/page.tsx` يستورد ~14 نافذة **استيرادًا ساكنًا** | فجوة أداء |
| الثيم البصري | ثيم «نيون» حالي (NeonCard/GlowText) — Tailwind 3.4 | سيُستبدل تدريجيًا بثيم الذهب |

## 2. محتويات الكيت المرفوع وتوافقه

`design-theme-kit` = ثيم **«طرفية الذهب»**: أسود دافئ + ذهبي عنبري (oklch)، RTL عربي أصلي، خطا IBM Plex Sans Arabic + Mono (7 ملفات TTF جاهزة)، `.num` للأرقام الجدولية (tabular-nums + LTR)، تدرجات وتوهجات ذهبية، shadcn/ui config.
- ⚠️ **توافق Tailwind**: الكيت مكتوب لـ Tailwind 4 (+ tw-animate-css) والمشروع على Tailwind 3.4. **القرار الموصى به**: تكييف التوكنز إلى Tailwind 3 (متغيرات CSS تعمل كما هي؛ الأصناف المساعدة تُعاد كتابتها) — وتأجيل ترقية Tailwind 4 ككل لمشروع منفصل لاحق (مخاطرة عالية في منتصف العمل).
- `components.json` في الكيت يؤكد مسار **shadcn/Radix** — بما يوافق البنية القائمة.

## 3. قرارات المكتبات (توصيات مبررة — تحتاج إشارتك)

| مكتبة المواصفة | التوصية | السبب |
|---|---|---|
| TradingView Lightweight Charts **v5** | ✅ اعتماد — ترقية من v4 واستبدال تضمين iframe في LiveChart | canvas خفيف بلا iframe يعالج عيب D2 جذريًا؛ Candlestick/Volume/MTF/Crosshair/PriceLines/Markers/Live كلها مدعومة |
| AG Grid v36 | ⚠️ **Community فقط** (MIT) | خصائصك المطلوبة (Virtual Scrolling, Sorting, Filtering, Clipboard) في المجانية؛ **Excel Export وServer-Side Row Model تجاريان (رخصة مدفوعة)** — قرار مالك |
| Motion v14 | ✅ اعتماد بحذر | Layout animations + AnimatePresence + Reduced Motion؛ نقفي عند الحد الأدنى من الحركة حفاظًا على 2 vCPU |
| Mantine v9 | ❌ لا — نلتزم بـ **Radix + Tailwind** (البديل في مواصفتك نفسها) | تقديم نظام تصميم موازٍ فوق 35+ مكوّن قائم = ازدواجية ومخاطرة كبيرة؛ Radix يوفر نفس خصائص RTL/Keyboard/Focus |
| IBM Plex Sans Arabic + Mono | ✅ اعتماد فوري من الكيت (next/font/local) | ملفات TTF جاهزة محليًا — بلا اعتماد على CDN |
| cmdk | ✅ اعتماد | ينفذ بند «Global Command Center» (بحث ضبابي + اختصارات + مجموعات) |
| react-resizable-panels | ✅ اعتماد | تقسيم أفقي/عمودي + collapse + تخزين — يكامل RGL |
| react-grid-layout | ✅ توصيل المثبت مسبقًا | Draggable/Resizable/Compact/Persist — المواصفة نفسها تختاره للـ Dashboard Grids |
| Allotment / rc-dock | ❌ لا | تراكب مع RGL + panels؛ rc-dock ثقيل ويكرر الوظيفة |
| React Aria Tabs | ❌ لا | Radix Tabs قائم ويوفر Keyboard/Focus/RTL — نفعّل الأنماط المطلوبة عليه (Lazy + KeepMounted + Scrollable) |

## 4. الخصائص المؤسسية (بند 6 من مواصفتك) → خطة التنفيذ

| الخاصية | الأولوية عندك | الوضع الحالي | المرحلة |
|---|---|---|---|
| Real-Time Data Streaming | حرجة | موجود (WS + SSE عبر البوابة) | — تحسين في M1 |
| WebSocket Reconnection | حرجة | إعادة اتصال أساسية | **M1: + heartbeat (ping/pong كل 25ث) + backoff أُسي + جودة الاتصال في الواجهة** |
| Virtualization | حرجة | غائبة | **M1: @tanstack/react-virtual** على الجداول الكبيرة (المواقع/السجل/العيوب) |
| Layout Persistence | حرجة | zustand persist جاهز | **M1: توصيل RGL بالمتجر (حفظ/استعادة تلقائية لكل مستخدم)** |
| Error Boundaries | عالية | غائبة | **M1: error.tsx + global-error.tsx + حدود على مستوى كل نافذة (عزل انهيار بطاقة عن الداشبورد)** |
| Lazy Loading | عالية | استيراد ساكن لـ14 نافذة | **M1: next/dynamic للنوافذ الثقيلة (TV، RL، Deep Learning، Research)** |
| Offline State | عالية | غير موجود | M3: شارة حالة الاتصال + طوابير محلية للإجراءات |
| Global Command Center | عالية | غير موجود | M3: cmdk (Ctrl+K) — تنقل + أوامر KILL/RESUME + تغيير الرمز |
| Undo/Redo للتخطيط | عالية | غير موجود | M3: تاريخ تخطيط في zustand (حد 20 خطوة) |
| Multi-Workspace | عالية | غير موجود | M4: مساحات مسماة (تداول/مراقبة/بحث) كل منها تخطيط محفوظ |
| Performance Monitoring | عالية | غير موجود | M4: web-vitals + عداد FPS للشارت + تقرير في SystemDiagnostic |
| Accessibility | عالية | Radix يوفر الأساس | M4: تدقيق كيبورد كامل + aria-labels عربية + تباين |
| Multi-Monitor | عالية | غير موجود | M4: فتح نافذة في تبويب/نافذة مستقلة (popout) — بديل عملي عن توزيع حقيقي |

## 5. أهداف الأداء (بند 7) → تقنية التنفيذ

| الهدف | التقنية |
|---|---|
| تحديث لحظي دون إعادة رسم كاملة | استمرار نمط الاشتراكات الانتقائية في zustand (selector per field) — لا setState شامل |
| شارت 60 FPS | Lightweight Charts: `handleScroll/TimeScale` افتراضي؛ تحديث الشمعة الأخيرة عبر `series.update()` فقط (لا setdata كامل) + throttle إلى ~10Hz للأسعار |
| جداول آلاف السجلات | tanstack-virtual (نافذة ~10 صفوف مرسومة) |
| تحديث الخلايا المتغيرة فقط | Cell-level: مقارنة القيمة السابقة في `useMemo` + وميض CSS محصور (بدل إعادة render الصف) |
| استعادة الجلسة | persist مع versioning + merge آمن للإعدادات الناقصة (درس D2: غياب التفضيل يجب ألا يركّب الثقيل) |
| Reconnect + Heartbeat | كما في M1 أعلاه |
| منع تراكم الاشتراكات | قاعدة إغلاق صارمة: كل useEffect اشتراك يرجع cleanup + فحص بـ React DevTools في الجولة |

## 6. مراحل التنفيذ (كل مرحلة: تنفيذ → اختبارات node/playwright → جولة شاشات → توثيق → commit)

### M1 — أساس حرج (الأولوية القصوى، بلا تغيير شكل)
1. Error Boundaries (error.tsx + global-error.tsx + WindowBoundary لكل بطاقة)
2. WS: heartbeat + backoff أُسي + سقف محاولات + حالة الاتصال في الشريط
3. تركيب خطوط IBM Plex من الكيت (next/font/local) + `.num` للأرقام (بلا تغيير الألوان بعد)
4. توصيل react-grid-layout بالمتجر القائم (سحب/تحجيم/حفظ/استعادة) + زر «استعادة التخطيط الافتراضي»
5. Lazy loading (next/dynamic) للنوافذ الثقيلة + Skeleton أثناء التحميل

### M2 — الشارت والجداول (أكبر أثر بصري ووظيفي)
1. lightweight-charts v5: شارت شموع + حجم + MTF + Crosshair + PriceLines للمواقع المفتوحة + Markers للصفقات — **بديل افتراضي لتضمين TV** (يبقى التضمين خيارًا يدويًا كما هو)
2. Virtualization للجداول (المواقع/السجل/ea-commands) + وميض الخلية المتغيرة
3. تحديث الشمعة الأخيرة عبر update() فقط + throttle

### M3 — هوية «طرفية الذهب» + تجربة
1. تكييف توكنز الكيت إلى Tailwind 3 (متغيرات :root oklch + خريطة ألوان في tailwind.config) — استبدال ثيم النيون تدريجيًا بطبقة كاملة (NeonCard → GoldCard بخصائص مطابقة)
2. RTL نصي: html dir=rtl (موجود) + `.num` LTR لكل الأرقام والأسعار
3. cmdk Command Center (Ctrl+K) + react-resizable-panels للأقسام العلوية
4. Motion: انتقالات Layout + AnimatePresence للتبويبات + احترام prefers-reduced-motion
5. Offline State + Undo/Redo للتخطيط

### M4 — مؤسسي متقدم
Multi-Workspace + Performance Monitoring (web-vitals + FPS) + تدقيق A11y + Multi-Monitor (popout) + مراجعة أمنية للـ bundle

## 7. المخاطر والتحوطات

| الخطر | التحوط |
|---|---|
| ذاكرة الصندوق (2 vCPU، درس D2) | الشارت canvas خفيف + Lazy + بلا iframe افتراضيًا + قياس FPS في M4 للتأكد |
| Tailwind 4 في الكيت مقابل 3 في المشروع | تكييف التوكنز لا ترقية الإطار — الترقية قرار لاحق منفصل |
| next@14.2.5 بها ثغرة معلنة (ملاحظة قائمة) | يوصى برفع 14.2.x الأحدث **قبل** M1 (تعديل صغير منفصل) |
| تراخيص AG Grid | Community فقط ما لم توافق على شراء Enterprise |
| انحراف عقود الصدق (qa-honesty-contracts) | كل تغيير واجهة يمر على نفس الاختبارات 202/202 دون تعديل العقود |

## 8. قرارات مطلوبة من المالك قبل البدء

1. **AG Grid**: هل نكتفي بـ Community (موصى به) أم لديك رخصة Enterprise؟
2. **Mantine**: هل توافق على الالتزام بـ Radix+Tailwind بدلها (موصى به)؟
3. **ترقية Next 14.2.5 → أحدث 14.2.x** قبل M1 (إصلاح ثغرة معلنة — تعديل منخفض المخاطر)؟
4. **اعتماد الخطة والبدء بـ M1** (Error Boundaries + WS Heartbeat + الخطوط + توصيل الشبكة + Lazy)؟
