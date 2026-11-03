import assert from 'node:assert/strict';
import test from 'node:test';
import {
  classifyDiagnosticBanner,
  classifyCandlesProbe,
  classifyUpstreamProbe,
} from '../src/lib/system-health-status.ts';

// UI-01 regression: the banner must NOT read "All systems operational"
// while services are still empty / the first check has not completed.
test('banner is "checking" before the first check completes (services empty)', () => {
  assert.equal(classifyDiagnosticBanner(false, []), 'checking');
});

test('banner is "checking" when checked flag is set but no results yet', () => {
  assert.equal(classifyDiagnosticBanner(true, []), 'checking');
});

test('banner is "healthy" only after a completed check where every service is ok', () => {
  assert.equal(classifyDiagnosticBanner(true, [{ ok: true }, { ok: true }]), 'healthy');
});

test('banner is "fault" when any service is down after a completed check', () => {
  assert.equal(classifyDiagnosticBanner(true, [{ ok: true }, { ok: false }]), 'fault');
});

// Candles probe must distinguish auth (401/403) from upstream (502/503)
// and must never let a 401 masquerade as "MT5 offline".
test('a 401 on candles is an auth problem, not MT5 offline', () => {
  const r = classifyCandlesProbe(401, false);
  assert.equal(r.kind, 'auth');
  assert.match(r.detail, /auth required/);
  assert.doesNotMatch(r.detail, /MT5 offline/);
});

test('a 403 on candles is also an auth problem', () => {
  assert.equal(classifyCandlesProbe(403, false).kind, 'auth');
});

test('a 502 on candles is an upstream/data-service problem', () => {
  const r = classifyCandlesProbe(502, false);
  assert.equal(r.kind, 'upstream');
  assert.match(r.detail, /data service unavailable/);
});

test('a 200 with no bars is no-data, not an error', () => {
  const r = classifyCandlesProbe(200, false);
  assert.equal(r.kind, 'no-data');
});

test('a 200 with bars is ok', () => {
  assert.equal(classifyCandlesProbe(200, true).kind, 'ok');
});

test('a transport failure (status 0) is unreachable', () => {
  assert.equal(classifyCandlesProbe(0, false).kind, 'unreachable');
});

// Upstream probe (ML/Agents): a gateway 502/503 means the internal service is
// not running — the honest settings-mode state, never a fabricated success.
test('a 502 on an upstream probe is "upstream offline", not an opaque HTTP code', () => {
  const r = classifyUpstreamProbe(502);
  assert.equal(r.kind, 'upstream');
  assert.match(r.detail, /upstream offline \(HTTP 502\)/);
});

test('503 and 504 are also classified as upstream offline', () => {
  assert.equal(classifyUpstreamProbe(503).kind, 'upstream');
  assert.equal(classifyUpstreamProbe(504).kind, 'upstream');
});

test('401/403 on an upstream probe are auth problems', () => {
  assert.equal(classifyUpstreamProbe(401).kind, 'auth');
  assert.equal(classifyUpstreamProbe(403).kind, 'auth');
});

test('404 on an upstream probe is a missing route', () => {
  const r = classifyUpstreamProbe(404);
  assert.equal(r.kind, 'not-found');
  assert.match(r.detail, /route not found/);
});

test('a 2xx upstream probe is ok', () => {
  assert.equal(classifyUpstreamProbe(200).kind, 'ok');
  assert.equal(classifyUpstreamProbe(201).kind, 'ok');
});

test('an unexpected 4xx/5xx falls through to a raw HTTP detail', () => {
  const r = classifyUpstreamProbe(418);
  assert.equal(r.kind, 'error');
  assert.equal(r.detail, 'HTTP 418');
});
