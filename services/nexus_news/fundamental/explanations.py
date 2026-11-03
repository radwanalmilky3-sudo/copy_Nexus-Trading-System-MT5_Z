from __future__ import annotations

from shared.fundamental import ArabicExplanation, GoldDirection, GoldImpactResult


_DIRECTION_AR = {
    GoldDirection.BULLISH: "يميل إلى الصعود",
    GoldDirection.BEARISH: "يميل إلى الهبوط",
    GoldDirection.NEUTRAL: "محايد",
    GoldDirection.CONFLICTED: "متعارض",
}


class ArabicExplanationEngine:
    version = "1.0.0"

    def build(self, result: GoldImpactResult) -> ArabicExplanation:
        direction_ar = _DIRECTION_AR[result.direction]
        driver = result.primary_drivers[0] if result.primary_drivers else None
        counter = result.counter_drivers[0] if result.counter_drivers else None
        what = driver.explanation_ar if driver else "لم تتوفر بيانات أساسية كافية لتحديد المحرك الرئيسي."
        why = (
            "تؤثر هذه البيانات في توقعات الفائدة والعوائد والدولار والطلب على الملاذ الآمن، "
            "وهي القنوات الرئيسة التي تنتقل عبرها الصدمة الأساسية إلى الذهب."
        )
        transmission = " → ".join(result.transmission_chain_ar) if result.transmission_chain_ar else (
            "الحدث الأساسي → توقعات الفائدة/المخاطر → العوائد والدولار → تكلفة الفرصة أو طلب الملاذ الآمن → الذهب"
        )
        gold_effect = (
            f"الاتجاه الحالي للذهب {direction_ar}، بقوة {result.strength:.0f}/100 "
            f"وثقة {result.confidence:.0f}/100."
        )
        if result.confidence_validation.value != "calibrated":
            gold_effect += " الثقة لم تُعتمد بعد كاحتمال تاريخي معاير بالكامل."
        confidence_reason = (
            f"تغطية البيانات {result.coverage_score:.0f}/100، جودتها {result.data_quality_score:.0f}/100، "
            f"حداثتها {result.freshness_score:.0f}/100، ودرجة التعارض {result.conflict_score:.0f}/100."
        )
        horizon = "صدمة الحدث: دقائق إلى ساعات؛ التكتيكي: ساعات؛ أما الانحياز الهيكلي فيمتد لأيام أو أسابيع حسب المصدر."
        simple = f"الخلاصة: الذهب {direction_ar}. {what}"
        advanced = (
            f"النتيجة المركبة تشير إلى أن الذهب {direction_ar}. {confidence_reason} "
            f"أقوى عامل معاكس: {counter.explanation_ar if counter else 'لا يوجد عامل معاكس موثوق مسجل حاليًا.'}"
        )
        return ArabicExplanation(
            prediction_id=result.prediction_id,
            headline_ar=f"التحليل الأساسي للذهب: {direction_ar}",
            what_happened_ar=what,
            why_it_matters_ar=why,
            transmission_to_gold_ar=transmission,
            gold_effect_ar=gold_effect,
            confirmations_ar=result.confirmations_ar,
            contradictions_ar=result.contradictions_ar,
            weakening_factors_ar=result.weakening_factors_ar,
            invalidation_ar=result.invalidation_conditions_ar,
            confidence_reason_ar=confidence_reason,
            horizon_ar=horizon,
            simple_summary_ar=simple,
            advanced_summary_ar=advanced,
            explanation_version=self.version,
        )
