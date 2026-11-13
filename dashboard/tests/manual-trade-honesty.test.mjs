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

test('manual trade panel never presents a working order button while execution is unwired', () => {
  // Both action buttons must be disabled — a console.log-only Buy/Sell was a
  // fabricated trading surface (found during the agentC audit).
  const buttons = markup.match(/<button[^>]*>/g) ?? [];
  const orderButtons = buttons.filter((b) => b.includes('غير موصول'));
  assert.equal(orderButtons.length, 2, 'both Buy and Sell carry the unwired title');
  for (const b of orderButtons) {
    assert.equal(/disabled(=|\s|>)/.test(b), true, 'order button must render disabled');
  }
});

test('the panel states plainly that manual execution is not connected', () => {
  assert.match(markup, /غير موصول بمحرك التنفيذ/,
    'an honest reason must be visible, not a silent dead button');
  assert.match(markup, /معطّلة/);
});

test('the panel still shows real price inputs and risk fields', () => {
  assert.match(markup, /Bid/);
  assert.match(markup, /Ask/);
  assert.match(markup, /Lots/);
  assert.match(markup, /SL/);
  assert.match(markup, /TP/);
});
