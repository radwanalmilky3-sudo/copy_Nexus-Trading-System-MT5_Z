# ARABIC_EXPLANATION_VALIDATION — Paper Fundamental Validation phase

**Component:** Arabic explanation layer + Arabic guard/UX strings · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
ARABIC EXPLANATIONS       PASS (full Arabic explanation chain persisted per
                                prediction; all 17 explanation fields live)
ARABIC GUARD/BLACKOUT     PASS (Redis blackout reason_ar + risk/executor
                                Arabic reason codes verified this phase)
UI ARABIC                 PASS (dashboard tab «التحليل الأساسي» + Arabic
                                components; store fields render natively)
NO TRANSLATION THEATER    PASS (numbers in explanations match the prediction
                                row 1:1 — no decorative prose)
```

## Live explanation (DuckDB `fundamental_explanations`, latest 13:04:31+03, linked to prediction `0a642bee…`)

```text
headline_ar            التحليل الأساسي للذهب: يميل إلى الصعود
what_happened_ar       شدة الحدث 49/100، التصعيد 49/100، ضغط الملاذ الآمن 37/100، والمصادر المستقلة 1.
economic_meaning_ar    تؤثر هذه البيانات في توقعات الفائدة والعوائد والدولار والطلب على
                       الملاذ الآمن، وهي القنوات الرئيسة التي تنتقل عبرها الصدمة الأساسية إلى الذهب.
transmission_to_gold_ar المحاور الأساسية الخمسة → الدمج الديناميكي → العوائد والدولار/الملاذ الآمن → XAUUSD
gold_effect_ar         الاتجاه الحالي للذهب يميل إلى الصعود، بقوة 27/100 وثقة 70/100.
                       الثقة لم تُعتمد بعد كاحتمال تاريخي معاير بالكامل.
simple_summary_ar      الخلاصة: الذهب يميل إلى الصعود. شدة الحدث 49/100، التصعيد 49/100،…
advanced_summary_ar    النتيجة المركبة تشير إلى أن الذهب يميل إلى الصعود. تغطية البيانات 32/100،
                       جودتها 75/100، حداثتها 100/100، ودرجة التعارض 0/100. أقوى عامل معاكس:
                       لا يوجد عامل معاكس موثوق مسجل حاليًا.
why_confidence_changed_ar تغطية البيانات 32/100، جودتها 75/100، حداثتها 100/100، ودرجة التعارض 0/100.
weakening_factors_ar   ["تغطية البيانات أقل من المستوى المثالي."]
invalidation_ar        [انعكاس اتجاه الدولار والعوائد…, ظهور حدث جديد عالي التأثير…, انخفاض جودة/حداثة البيانات…]
expected_horizon_ar    صدمة الحدث: دقائق إلى ساعات؛ التكتيكي: ساعات؛ أما الانحياز الهيكلي فيمتد لأيام…
actual_outcome_ar      لم يتم تقييم النتيجة الفعلية بعد.
lesson_ar              لم تتوفر نتيجة كافية للتعلم بعد.
```

## Number-consistency audit (explanation vs prediction row)

| claim in Arabic text | prediction row value | match |
|---|---|---|
| يميل إلى الصعود / قوة 27/100 | direction=bullish, strength=26.77 → rounds to 27 | ✔ |
| ثقة 70/100 | confidence=69.64 → rounds to 70 | ✔ |
| تغطية 32/100، جودة 75/100، حداثة 100/100، تعارض 0/100 | coverage 32.2, quality 75.0, freshness 100.0, conflict 0.0 | ✔ |
| المصادر المستقلة 1 | independence_group count from geo cluster = 1 | ✔ |
| confidence «لم تُعتمد بعد» | confidence_validation=unvalidated | ✔ |

## Arabic guard strings (live this phase)

- Redis `nexus:fundamental:blackout`: `state=clear, reason_ar=«لا توجد نافذة حظر نشطة لحدث…»` (actively recomputed; written by FundamentalRuntime).
- `source_health_history.description_ar`: «المصدر يعمل وتم جلب بيانات حقيقية.» / «يتطلب المصدر إعدادًا إضافيًا.» per source state.
- `weight_reasons_json` (fusion): full Arabic per-domain factor breakdown (base weight, freshness, quality, fit, reliability, regime, independence).
- Prior-phase (carried): Central Risk REJECT `rule=NEWS_BLACKOUT` + Executor BLOCKED `broker=none` verified with Arabic context in `RISK_GUARD_EVIDENCE.md`.

## API / UI

- `GET :9000/api/fundamental/gold/overview` returns the explanation fields inside the gold bundle (200, 58 KB) — `FundamentalWorkspace` renders headline/effect/invalidation natively in Arabic (dashboard tab «التحليل الأساسي»).
- Encoding note: Arabic stored as proper UTF-8 in DuckDB/JSON (console mojibake is a PowerShell codepage artifact only; file/API bytes verified intact).

```text
ARABIC EXPLANATION VALIDATION: PASS
```
