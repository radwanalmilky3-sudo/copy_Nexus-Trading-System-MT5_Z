import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const nativeRequire = createRequire(import.meta.url);
function load(path) {
  const code = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const context = { exports: {}, require: (name) => {
    if (!name.startsWith('.')) return nativeRequire(name);
    const base = resolve(dirname(path), name);
    return load(existsSync(base + '.tsx') ? base + '.tsx' : base + '.ts');
  } };
  vm.runInNewContext(code, context);
  return context.exports;
}
const { ResearchLabTab } = load(fileURLToPath(new URL('../src/components/research-lab/ResearchLabTab.tsx', import.meta.url)));
function render(state, query = '', rows = []) {
  return renderToStaticMarkup(React.createElement(ResearchLabTab, { state, query, rows,
    definition: { id: 'provenance', arabicLabel: 'التتبّع', englishLabel: 'Provenance', description: '', icon: '04' },
    onQueryChange() {}, onFilterOpen() {},
  }));
}
test('no search matches does not declare the connected source empty', () => {
  const html = render('readonly', 'EURUSD', [{ id: 'd1', asset: 'XAUUSD', origin: 'mt5', hash: 'abc' }]);
  assert.ok(!html.includes('المصدر المقروء فارغ'));
  assert.ok(!html.includes('EMPTY SOURCE'));
  assert.ok(html.includes('مطابقة'));
});
test('degraded empty evidence never claims a healthy empty source', () => {
  const html = render('degraded');
  assert.ok(!html.includes('المصدر المقروء فارغ'));
  assert.ok(!html.includes('EMPTY SOURCE'));
});
test('bar timestamp is not presented as provenance capture time', () => {
  const html = render('readonly', '', [{ id: 'd1', asset: 'XAUUSD', origin: 'mt5', hash: 'abc', capturedAt: '2020-01-01' }]);
  assert.ok(!html.includes('وقت الالتقاط'));
  assert.ok(html.includes('آخر شمعة'));
});

test('dataset distinguishes certificate from verified fingerprint in Aden time', () => {
  const html = renderToStaticMarkup(React.createElement(ResearchLabTab, {
    state:'readonly',query:'',onQueryChange(){},onFilterOpen(){},
    definition:{id:'data-import',arabicLabel:'مصادر البيانات',englishLabel:'Datasets',description:'',icon:'01'},
    rows:[{id:'d1',source:'XAUUSD/M15 · mt5_backfill',format:'OHLCV',rows:10,receivedAt:'old',status:'stored',
      qualityStatus:'warning',qualityCheckedAt:'2026-10-19T14:57:01Z',qualityVerifiedAt:'2026-10-19T15:25:00Z',
      qualityExpiresAt:'2026-10-19T15:57:01Z',historicalSlice:true}],
  }));
  assert.ok(html.includes('إصدار الشهادة'));
  assert.ok(html.includes('آخر مطابقة للبصمة'));
  assert.ok(html.includes('18:25:00'));
  assert.ok(html.includes('عدن'));
  assert.ok(html.includes('استكمال تاريخي'));
});

test('unconnected calendar is not presented as active',()=>{
  const html=renderToStaticMarkup(React.createElement(ResearchLabTab,{
    state:'readonly',query:'',onQueryChange(){},onFilterOpen(){},definition:{id:'data-import',arabicLabel:'مصادر',englishLabel:'Datasets',description:'',icon:'01'},
    rows:[{id:'d1',source:'mt5',format:'OHLCV',rows:2,receivedAt:'old',status:'stored',qualityStatus:'warning',calendarState:'not_configured'}],
  }));
  assert.ok(html.includes('قارئ الجلسات: غير موصول'));
  assert.ok(!html.includes('قارئ الجلسات: جاهز'));
});
