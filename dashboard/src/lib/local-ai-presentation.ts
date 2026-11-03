// Truth-contract presentation helpers for the local AI analyst.
// Unreachable endpoint / missing model / timeout / invalid response are
// displayed with their REAL reason — never replaced by canned answers.

export type LocalAiStateLike = {
  state?: string;
  reason?: string | null;
  error?: string | null;
  endpoint?: string | null;
  model_name?: string | null;
  available_models?: string[] | null;
  hallucination_flags?: string[] | null;
  answer?: {
    summary_ar?: string;
    sources?: string[];
    claims_used?: string[];
  } | null;
  schema_valid?: boolean;
  latency_ms?: number | null;
};

export type LocalAiView = {
  kind: 'ready' | 'rejected' | 'unavailable' | 'none';
  headline: string;
  details: string[];
};

const REASON_LABELS: Record<string, string> = {
  ENDPOINT_UNREACHABLE: 'عنوان المحرك المحلي لا يستجيب',
  MODEL_NOT_INSTALLED: 'النموذج المطلوب غير مثبت في المحرك المحلي',
  LLM_TIMEOUT: 'انتهت مهلة الاتصال بالنموذج المحلي',
  INVALID_RESPONSE: 'رد النموذج غير صالح (ليس JSON صحيحًا)',
  INVALID_RESPONSE_SCHEMA: 'رد النموذج لا يطابق المخطط المطلوب',
  LOCAL_AI_GROUNDING_GUARD: 'رفض حارس Grounding الإجابة غير المستندة إلى الأدلة',
};

export function localAiReasonLabel(reason: string | null | undefined): string {
  if (!reason) return 'سبب غير معروف';
  return REASON_LABELS[reason] ?? reason;
}

export function localAiStatePresentation(result: LocalAiStateLike | null | undefined): LocalAiView {
  if (!result || !result.state) return { kind: 'none', headline: '', details: [] };
  if (result.state === 'ready') {
    return {
      kind: 'ready',
      headline: result.answer?.summary_ar ?? '',
      details: [],
    };
  }
  if (result.state === 'rejected') {
    const flags = result.hallucination_flags ?? [];
    return {
      kind: 'rejected',
      headline: localAiReasonLabel(result.reason ?? 'LOCAL_AI_GROUNDING_GUARD'),
      details: flags.length > 0 ? flags : ['لم تُرفق معرفات أدوقة مطابقة'],
    };
  }
  const details: string[] = [];
  if (result.endpoint) details.push(`العنوان: ${result.endpoint}`);
  if (result.error) details.push(result.error);
  if (result.reason === 'MODEL_NOT_INSTALLED' && result.model_name) {
    details.push(`النموذج المطلوب: ${result.model_name}`);
  }
  if (result.available_models && result.available_models.length > 0) {
    details.push(`النماذج المتوفرة محليًا: ${result.available_models.join('، ')}`);
  }
  return {
    kind: 'unavailable',
    headline: localAiReasonLabel(result.reason),
    details,
  };
}

export type EvidenceItem = { label: string; kind: 'source' | 'claim' };

export function evidenceIdItems(
  answer: { sources?: string[]; claims_used?: string[] } | null | undefined,
): EvidenceItem[] {
  if (!answer) return [];
  const items: EvidenceItem[] = [];
  for (const s of answer.sources ?? []) items.push({ label: `مصدر: ${s}`, kind: 'source' });
  for (const c of answer.claims_used ?? []) items.push({ label: `ادعاء: ${c}`, kind: 'claim' });
  return items;
}

export function localAiModelLine(result: LocalAiStateLike | null | undefined): string {
  if (!result) return '—';
  const parts: string[] = [];
  if (result.model_name) parts.push(result.model_name);
  if (result.endpoint) parts.push(result.endpoint);
  if (typeof result.latency_ms === 'number') parts.push(`${Math.round(result.latency_ms)}ms`);
  return parts.length > 0 ? parts.join(' · ') : '—';
}

export function localAiGuardNote(): string {
  return 'شرح وتفسير فقط من الأدلة المسجلة — لا أمر شراء أو بيع ولا اعتماد لأي confidence غير معاير.';
}
