import assert from 'node:assert/strict';
import test from 'node:test';
import {
  newsFeedViewState,
  newsFeedBanners,
  filterNewsItems,
  matchesPeriod,
  matchesSymbol,
  matchesSource,
  newsSourceOptions,
  impactValue,
} from '../src/components/fundamental/news-presentation.ts';

const NOW = Date.parse('2026-10-21T12:00:00Z');

// ── View state: unknown ≠ 0 ≠ ready ─────────────────────────────────────────

test('news: fetch failure is offline, not empty', () => {
  assert.equal(newsFeedViewState(null, true), 'offline');
});

test('news: no payload yet is loading, not empty', () => {
  assert.equal(newsFeedViewState(null, false), 'loading');
});

test('news: payload without explicit state claim is unavailable, not ready', () => {
  assert.equal(newsFeedViewState({}, false), 'unavailable');
  assert.equal(newsFeedViewState({ state: null }, false), 'unavailable');
  assert.equal(newsFeedViewState({ state: 'weird-value' }, false), 'unavailable');
});

test('news: explicit states pass through', () => {
  assert.equal(newsFeedViewState({ state: 'ready' }, false), 'ready');
  assert.equal(newsFeedViewState({ state: 'stale' }, false), 'stale');
  assert.equal(newsFeedViewState({ state: 'empty' }, false), 'empty');
  assert.equal(newsFeedViewState({ state: 'unavailable' }, false), 'unavailable');
});

// ── Banners: last update / first availability / stale / sources ─────────────

test('news banners: ready payload shows last update and first availability', () => {
  const b = newsFeedBanners({
    state: 'ready',
    last_update_at: '2026-10-21T11:55:00Z',
    first_available_at: '2026-10-20T08:00:00Z',
    freshness: { stale: false, age_sec: 300, limit_sec: 900 },
    reason_ar: null,
    sources: [{ source_id: 'gdelt', name_ar: 'GDELT', configuration_status: 'configured', connectivity: 'healthy' }],
  }, 'ready');
  assert.ok(b.lastUpdateLabel);
  assert.ok(b.firstAvailableLabel);
  assert.equal(b.staleWarning, null);
  assert.equal(b.sourceIssues.length, 0);
});

test('news banners: stale chain yields a warning and keeps reason', () => {
  const b = newsFeedBanners({
    state: 'stale',
    freshness: { stale: true, age_sec: 21600, limit_sec: 900 },
    reason_ar: 'اللقطة الحالية قديمة؛ تُعرض كبيانات مخزنة وليست حية.',
  }, 'stale');
  assert.ok(b.staleWarning.includes('الحد المقبول'));
  assert.ok(b.reasonAr.includes('قديمة'));
});

test('news banners: unavailable source shows its external requirement reason', () => {
  const b = newsFeedBanners({
    state: 'unavailable',
    reason_ar: 'لم يبلغ مسار الأخبار بحالة بعد.',
    sources: [
      { source_id: 'newsapi', name_ar: 'NewsAPI', configuration_status: 'missing_config', configuration_reason_ar: 'المصدر يتطلب مفتاحًا خارجيًا (NEWSAPI_KEY) غير مضبوط حاليًا.' },
      { source_id: 'gdelt', name_ar: 'GDELT', configuration_status: 'configured' },
      { source_id: 'gnews', name_ar: 'GNews', configuration_status: 'disabled', configuration_reason_ar: 'المصدر معطل.' },
    ],
  }, 'unavailable');
  assert.equal(b.sourceIssues.length, 2);
  assert.ok(b.sourceIssues[0].includes('NEWSAPI_KEY'));
  assert.ok(b.sourceIssues.some((x) => x.includes('GNews')));
});

// ── Filters: symbol / impact / period ───────────────────────────────────────

const rows = [
  { headline: 'Gold climbs', impact: 'HIGH', timestamp: '2026-10-21T11:30:00Z', affected_currencies: ['XAU', 'USD'] },
  { headline: 'Yen firms', impact: 'MEDIUM', timestamp: '2026-10-21T06:00:00Z', affected_currencies: ['JPY'] },
  { headline: 'Old dollar note', impact: 'LOW', timestamp: '2026-10-15T00:00:00Z', affected_currencies: ['USD'] },
  { headline: 'Untimed headline', impact: 'HIGH', timestamp: null, affected_currencies: ['USD'] },
];

test('news filters: impact values normalise unknown to LOW bucket', () => {
  assert.equal(impactValue('high'), 'HIGH');
  assert.equal(impactValue(undefined), 'LOW');
  assert.equal(impactValue('CRITICAL'), 'LOW');
});

test('news filters: period window keeps recent rows and drops untimed rows', () => {
  const out = filterNewsItems(rows, { period: '24H', now: NOW });
  assert.deepEqual(out.map((r) => r.headline), ['Gold climbs', 'Yen firms']);
  assert.equal(matchesPeriod(rows[3], '24H', NOW), false);
  assert.equal(matchesPeriod(rows[3], 'ALL', NOW), true);
});

test('news filters: symbol filter matches base and full codes', () => {
  assert.equal(matchesSymbol(rows[0], 'XAUUSD', 'SYMBOL'), true);
  assert.equal(matchesSymbol(rows[1], 'XAUUSD', 'SYMBOL'), false);
  assert.equal(matchesSymbol(rows[0], 'XAUUSD', 'ALL'), true);
  const out = filterNewsItems(rows, { symbol: 'XAUUSD', symbolFilter: 'SYMBOL', now: NOW });
  // XAUUSD matches XAU, USD and the full pair; JPY-only rows are excluded.
  assert.deepEqual(out.map((r) => r.headline), ['Gold climbs', 'Old dollar note', 'Untimed headline']);
});

test('news filters: combined impact+symbol+period', () => {
  const out = filterNewsItems(rows, { impact: 'HIGH', symbol: 'XAUUSD', symbolFilter: 'SYMBOL', period: '1H', now: NOW });
  assert.deepEqual(out.map((r) => r.headline), ['Gold climbs']);
});

test('news filters: dedup-adjacent duplicate rows are not invented by filtering', () => {
  const dup = [rows[0], { ...rows[0] }];
  const out = filterNewsItems(dup, { now: NOW });
  assert.equal(out.length, 2); // filter does not dedup; server does. Filter must not drop distinct rows.
});

// ── Source/origin filter (plan checklist: التصفية بالأصل) ──────────────────

const sourced = [
  { headline: 'From GDELT', source: 'gdelt', timestamp: '2026-10-21T11:00:00Z' },
  { headline: 'From NewsAPI', source: 'newsapi', timestamp: '2026-10-21T11:00:00Z' },
  { headline: 'No source claim', source: null, timestamp: '2026-10-21T11:00:00Z' },
];

test('news source filter: narrows rows to the chosen origin, missing source never matches a named one', () => {
  assert.equal(matchesSource(sourced[0], 'ALL'), true);
  assert.equal(matchesSource(sourced[0], 'gdelt'), true);
  assert.equal(matchesSource(sourced[1], 'gdelt'), false);
  assert.equal(matchesSource(sourced[2], 'gdelt'), false); // absent source ≠ gdelt
  const out = filterNewsItems(sourced, { source: 'newsapi', now: NOW });
  assert.deepEqual(out.map((r) => r.headline), ['From NewsAPI']);
});

test('news source filter: options list only real, unique origins', () => {
  assert.deepEqual(newsSourceOptions(sourced), ['gdelt', 'newsapi']);
  assert.deepEqual(newsSourceOptions([]), []);
});
