import assert from 'node:assert/strict';
import test from 'node:test';
import { buildTradeCsv } from '../src/lib/trade-csv.ts';

test('plain rows and headers join with comma and newline', () => {
  const csv = buildTradeCsv(
    ['Time', 'Symbol'],
    [['2026-10-23T10:00:00Z', 'XAUUSD'], ['2026-10-23T11:00:00Z', 'EURUSD']],
  );
  assert.equal(csv, 'Time,Symbol\n2026-10-23T10:00:00Z,XAUUSD\n2026-10-23T11:00:00Z,EURUSD');
});

test('commas inside cells are quoted', () => {
  const csv = buildTradeCsv(['note'], [['sl, tp done']]);
  assert.equal(csv, 'note\n"sl, tp done"');
});

test('double quotes inside cells are doubled and quoted', () => {
  const csv = buildTradeCsv(['note'], [['he said "hi"']]);
  assert.equal(csv, 'note\n"he said ""hi"""');
});

test('newlines inside cells are preserved inside quotes', () => {
  const csv = buildTradeCsv(['note'], [['line1\nline2']]);
  assert.equal(csv, 'note\n"line1\nline2"');
});

test('spreadsheet formula prefixes are neutralized for string cells', () => {
  assert.equal(buildTradeCsv(['c'], [['=SUM(A1:A2)']]), "c\n'=SUM(A1:A2)");
  assert.equal(buildTradeCsv(['c'], [['+cmd|calc']]), "c\n'+cmd|calc");
  assert.equal(buildTradeCsv(['c'], [['-2+3']]), "c\n'-2+3");
  assert.equal(buildTradeCsv(['c'], [['@user']]), "c\n'@user");
});

test('numeric cells stay unquoted numbers, including negatives', () => {
  const csv = buildTradeCsv(['pnl'], [[-5.5], [12], [0]]);
  assert.equal(csv, 'pnl\n-5.5\n12\n0');
});

test('null and undefined render as empty cells', () => {
  const csv = buildTradeCsv(['a', 'b'], [[null, undefined]]);
  assert.equal(csv, 'a,b\n,');
});

test('empty row set still exports a header-only file', () => {
  const csv = buildTradeCsv(['Time', 'Symbol'], []);
  assert.equal(csv, 'Time,Symbol');
});
