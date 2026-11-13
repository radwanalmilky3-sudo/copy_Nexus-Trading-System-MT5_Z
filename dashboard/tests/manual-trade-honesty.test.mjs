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

const require = createRequire(import.meta.url);
const SRC = fileURLToPath(new URL('../src/', import.meta.url));

function load(path, sandboxExtras = {}) {
  const code = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const context = {
    exports: {}, console, process: { env: {} },
    require: (name) => {
      const tryExts = (p) => load(existsSync(p + '.tsx') ? p + '.tsx' : p + '.ts', sandboxExtras);
      if (name.startsWith('@/')) return tryExts(resolve(SRC, name.slice(2)));
      if (!name.startsWith('.')) return require(name);
      return tryExts(resolve(dirname(path), name));
    },
    ...sandboxExtras,
  };
  vm.runInNewContext(code, context);
  return context.exports;
}

// zustand persist binds to the host globalThis.localStorage (see stores.test.mjs).
globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };

const { ManualTradePanel } = load(
  resolve(SRC, 'components/trade-controls/ManualTradePanel.tsx'),
);

const markup = renderToStaticMarkup(React.createElement(ManualTradePanel));

test('manual trade panel is wired and states the safety chain honestly', () => {
  // The panel posts to /api/positions/manual-order; buttons are enabled at
  // rest (disabled only while a request is in flight) and the visible note
  // describes the real approval chain instead of pretending instant fills.
  const buttons = markup.match(/<button[^>]*>/g) ?? [];
  const orderButtons = buttons.filter((b) => b.includes('تقييم المخاطر'));
  assert.equal(orderButtons.length, 2, 'both Buy and Sell advertise the approval chain in their title');
  for (const b of orderButtons) {
    assert.equal(/disabled(=|\s|>)/.test(b), false, 'order button must be enabled at rest');
  }
});

test('the panel states the full approval chain and the possibility of safe rejection', () => {
  assert.match(markup, /موافقة موقّعة/, 'signed approval must be named, not hidden');
  assert.match(markup, /حارس التنفيذ/, 'the executor guard must be named');
  assert.match(markup, /قد يُرفض بأمان/, 'honest expectation of safe rejection');
});

test('the panel still shows real price inputs and risk fields', () => {
  assert.match(markup, /Bid/);
  assert.match(markup, /Ask/);
  assert.match(markup, /Lots/);
  assert.match(markup, /SL/);
  assert.match(markup, /TP/);
});
