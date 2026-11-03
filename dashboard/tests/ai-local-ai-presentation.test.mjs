import assert from 'node:assert/strict';
import test from 'node:test';
import {
  localAiStatePresentation,
  localAiReasonLabel,
  evidenceIdItems,
  localAiGuardNote,
  localAiModelLine,
} from '../src/lib/local-ai-presentation.ts';

test('endpoint unreachable surfaces real reason, never canned answer', () => {
  const p = localAiStatePresentation({
    state: 'unavailable',
    reason: 'ENDPOINT_UNREACHABLE',
    error: 'ConnectError: All connection attempts failed',
    endpoint: 'http://127.0.0.1:11434/v1',
    answer: null,
  });
  assert.equal(p.kind, 'unavailable');
  assert.match(p.headline, /لا يستجيب|غير متاح/);
  assert.ok(p.details.some((d) => d.includes('11434')));
  assert.ok(p.details.some((d) => d.includes('ConnectError')));
});

test('model not installed lists available models', () => {
  const p = localAiStatePresentation({
    state: 'unavailable',
    reason: 'MODEL_NOT_INSTALLED',
    model_name: 'qwen2.5:3b',
    available_models: ['tiny', 'other'],
    answer: null,
  });
  assert.equal(p.kind, 'unavailable');
  assert.ok(p.details.some((d) => d.includes('tiny')));
});

test('timeout and invalid response have distinct labels', () => {
  assert.notEqual(localAiReasonLabel('LLM_TIMEOUT'), localAiReasonLabel('INVALID_RESPONSE'));
  assert.match(localAiReasonLabel('LLM_TIMEOUT'), /مهلة|timeout/i);
  assert.match(localAiReasonLabel('INVALID_RESPONSE'), /صالح|invalid/i);
});

test('rejected state lists hallucination flags', () => {
  const p = localAiStatePresentation({
    state: 'rejected',
    reason: 'LOCAL_AI_GROUNDING_GUARD',
    hallucination_flags: ['UNKNOWN_SOURCE:SRC_INVENTED'],
    answer: null,
  });
  assert.equal(p.kind, 'rejected');
  assert.ok(p.details.some((d) => d.includes('UNKNOWN_SOURCE:SRC_INVENTED')));
});

test('ready state exposes answer without inventing extra details', () => {
  const p = localAiStatePresentation({
    state: 'ready',
    answer: { summary_ar: 'ملخص', sources: ['src_alpha'], claims_used: ['claim_beta'] },
    schema_valid: true,
  });
  assert.equal(p.kind, 'ready');
  assert.equal(p.headline, 'ملخص');
});

test('evidenceIdItems counts sources and claims with labels', () => {
  const items = evidenceIdItems({ sources: ['s1', 's2'], claims_used: ['c1'] });
  assert.equal(items.length, 3);
  assert.ok(items.every((i) => typeof i.label === 'string' && i.label.length > 0));
  assert.deepEqual(evidenceIdItems(null), []);
});

test('model line shows model name and endpoint together', () => {
  const line = localAiModelLine({ model_name: 'qwen2.5:3b', endpoint: 'http://127.0.0.1:11434/v1', latency_ms: 12.5 });
  assert.match(line, /qwen2\.5:3b/);
  assert.match(line, /11434/);
  assert.match(line, /12ms|13ms/);
});

test('guard note forbids execution framing', () => {
  const note = localAiGuardNote();
  assert.match(note, /شرح|تفسير/);
  assert.doesNotMatch(note.toLowerCase(), /buy|sell|order/);
});
