import assert from 'node:assert/strict';
import test from 'node:test';
import {
  availableWindowKeys,
  corrCellPresentation,
  lagPairPresentation,
  correlationBasisNote,
  correlationDisclaimer,
} from '../src/lib/correlation-presentation.ts';

const FULL_WINDOWS = {
  '20': {
    matrix: { XAUUSD: { BTCUSD: 0.42 }, BTCUSD: { XAUUSD: 0.42 } },
    pairs: {
      'BTCUSD/XAUUSD': { corr: 0.42, sample_count: 19, coverage: 1, constant_series: false, insufficient_data: false },
    },
    sample_count: 19, coverage: 1,
  },
  '60': {
    matrix: { XAUUSD: { BTCUSD: null }, BTCUSD: { XAUUSD: null } },
    pairs: {
      'BTCUSD/XAUUSD': { corr: null, sample_count: 4, coverage: 0.068, constant_series: false, insufficient_data: true },
    },
    sample_count: 4, coverage: 0.068,
  },
  '120': {
    matrix: { XAUUSD: { BTCUSD: null }, BTCUSD: { XAUUSD: null } },
    pairs: {
      'BTCUSD/XAUUSD': { corr: null, sample_count: 90, coverage: 0.756, constant_series: true, insufficient_data: false },
    },
    sample_count: 90, coverage: 0.756,
  },
};

test('availableWindowKeys prefers 20/60/120 windows payload', () => {
  assert.deepEqual(availableWindowKeys({ windows: FULL_WINDOWS, matrices: { '7d': {}, '30d': {} } }), ['20', '60', '120']);
});

test('availableWindowKeys falls back to legacy matrices and never invents keys', () => {
  assert.deepEqual(availableWindowKeys({ matrices: { '7d': { a: {} }, '30d': { a: {} } } }), ['7d', '30d']);
  assert.deepEqual(availableWindowKeys(null), []);
  assert.deepEqual(availableWindowKeys({}), []);
});

test('corrCellPresentation renders value with sign prefix', () => {
  const cell = corrCellPresentation(FULL_WINDOWS['20'].pairs['BTCUSD/XAUUSD'], 0.42);
  assert.equal(cell.text, '+0.42');
  assert.equal(cell.tone, 'value');
  // UI was localized to Arabic: "19 samples · coverage 100%"
  assert.equal(cell.title, '19 عيّنة · تغطية 100%');
});

test('corrCellPresentation negative value keeps minus sign', () => {
  const cell = corrCellPresentation({ corr: -0.55, sample_count: 50, coverage: 1, constant_series: false, insufficient_data: false }, -0.55);
  assert.equal(cell.text, '-0.55');
});

test('corrCellPresentation marks insufficient data honestly', () => {
  const cell = corrCellPresentation(FULL_WINDOWS['60'].pairs['BTCUSD/XAUUSD'], null);
  assert.equal(cell.text, '—');
  assert.equal(cell.tone, 'insufficient');
  assert.match(cell.title, /بيانات غير كافية/i);
  assert.notEqual(cell.text, '0.00');
});

test('corrCellPresentation marks constant series honestly', () => {
  const cell = corrCellPresentation(FULL_WINDOWS['120'].pairs['BTCUSD/XAUUSD'], null);
  assert.equal(cell.text, '—');
  assert.equal(cell.tone, 'constant');
  assert.match(cell.title, /سلسلة ثابتة/i);
});

test('corrCellPresentation unknown pair is unavailable, never zero', () => {
  const cell = corrCellPresentation(undefined, null);
  assert.equal(cell.text, '—');
  assert.equal(cell.tone, 'unavailable');
});

test('lagPairPresentation labels agreed lead direction and lag', () => {
  const p = lagPairPresentation({ pair: 'BTCUSD/XAUUSD', direction: 'X_LEADS', lead_asset: 'BTCUSD', lag_candles: 3, best_corr: 1, insufficient_data: false });
  assert.match(p.label, /BTCUSD/);
  assert.match(p.label, /3/);
  assert.equal(p.tone, 'lead');
});

test('lagPairPresentation labels reference lead and in-sync', () => {
  const ref = lagPairPresentation({ pair: 'BTCUSD/XAUUSD', direction: 'REFERENCE_LEADS', lead_asset: 'XAUUSD', lag_candles: 2, insufficient_data: false });
  assert.match(ref.label, /XAUUSD/);
  const sync = lagPairPresentation({ pair: 'BTCUSD/XAUUSD', direction: 'IN_SYNC', lead_asset: null, lag_candles: 0, insufficient_data: false });
  assert.equal(sync.tone, 'sync');
});

test('lagPairPresentation insufficient lag stays unavailable', () => {
  const p = lagPairPresentation({ pair: 'BTCUSD/XAUUSD', direction: null, lag_candles: null, insufficient_data: true });
  assert.equal(p.tone, 'unavailable');
  assert.equal(p.label, '—');
});

test('correlation disclaimer forbids prediction framing', () => {
  const d = correlationDisclaimer();
  // Arabic disclaimer: "observed correlation on synchronized returns; not a
  // cause nor a guarantee of prediction" — the noun (التنبؤ) may appear, but
  // the disclaimer must never ASSERT that it predicts (verb يتنبأ) or frame
  // the correlation as causal/guaranteed.
  assert.match(d, /ليس سببًا ولا ضمانًا/);
  assert.doesNotMatch(d, /يتنبأ|ضمانًا للربح/);
});

test('correlationBasisNote declares synchronized returns', () => {
  assert.match(correlationBasisNote(), /عوائد متزامنة/);
});
