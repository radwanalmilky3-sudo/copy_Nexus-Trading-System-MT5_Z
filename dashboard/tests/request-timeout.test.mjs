import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import { withRequestTimeout } from '../src/lib/request-timeout.ts';

const compiledClient = ts.transpileModule(
  readFileSync(new URL('../src/lib/api-client.ts', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText;

function clientWith(fetch, storage = { getItem: () => null, removeItem() {} }) {
  const context = {
    exports: {}, process: { env: {} }, fetch, localStorage: storage,
    window: { location: { href: '' } },
    require: () => ({ withRequestTimeout }),
  };
  vm.runInNewContext(compiledClient, context);
  return { client: context.exports.apiClient, window: context.window };
}

const compiledLogin = ts.transpileModule(
  readFileSync(new URL('../src/app/login/page.tsx', import.meta.url), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } },
).outputText;

function loginForm(fetch, bootstrap = false) {
  const updates = new Map();
  const routes = [];
  const tokens = [];
  let stateIndex = 0;
  const jsx = (type, props) => ({ type, props });
  const context = {
    exports: {}, process: { env: {} }, fetch, Error,
    localStorage: { setItem: (...args) => tokens.push(args) },
    require: (name) => {
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
      if (name === 'react') return { useState: (initial) => {
        const index = stateIndex++;
        return [index === 2 ? bootstrap : initial, (value) => updates.set(index, value)];
      } };
      if (name === 'next/navigation') return { useRouter: () => ({ push: (path) => routes.push(path) }) };
      if (name === 'lucide-react') return {};
      if (name === '@/lib/request-timeout') return { withRequestTimeout };
      throw new Error(`Unexpected dependency: ${name}`);
    },
  };
  vm.runInNewContext(compiledLogin, context);
  function findForm(node) {
    if (!node || typeof node !== 'object') return;
    if (node.type === 'form') return node;
    for (const child of [node.props?.children].flat()) {
      const form = findForm(child);
      if (form) return form;
    }
  }
  const form = findForm(context.exports.default());
  assert.ok(form);
  return { submit: () => form.props.onSubmit({ preventDefault() {} }), updates, routes, tokens };
}

for (const bootstrap of [false, true]) {
  test(`${bootstrap ? 'bootstrap' : 'login'} timeout shows a message and releases the loading state`, async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    let signal;
    const form = loginForm(async (url, options) => {
      assert.equal(url, `http://localhost:9000/api/v2/auth/${bootstrap ? 'bootstrap' : 'login'}`);
      assert.equal(options.method, 'POST');
      signal = options.signal;
      return new Promise(() => {});
    }, bootstrap);
    const pending = form.submit();
    assert.equal(form.updates.get(1), true);
    t.mock.timers.tick(15000);
    await pending;
    assert.equal(signal.aborted, true);
    assert.equal(form.updates.get(1), false);
    assert.match(form.updates.get(5), /15/);
    assert.deepEqual(form.tokens, []);
    assert.deepEqual(form.routes, []);
    assert.equal(form.updates.has(2), false);
  });
}

test('successful login still saves the token and routes to the dashboard', async () => {
  const form = loginForm(async () => Response.json({ token: 'example' }));
  await form.submit();
  assert.deepEqual(form.tokens, [['nexus-token', 'example']]);
  assert.deepEqual(form.routes, ['/dashboard']);
  assert.equal(form.updates.get(1), false);
});

test('successful bootstrap still returns to login without saving a token or routing', async () => {
  const form = loginForm(async () => new Response(null, { status: 201 }), true);
  await form.submit();
  assert.equal(form.updates.get(2), false);
  assert.ok(form.updates.get(3));
  assert.match(form.updates.get(5), /Super Administrator/);
  assert.equal(form.updates.get(1), false);
  assert.deepEqual(form.tokens, []);
  assert.deepEqual(form.routes, []);
});

test('getMe bounds a stalled body and does not redirect on timeout', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let fetched;
  const { client, window } = clientWith(async (url, options) => {
    fetched = { url, options };
    return new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{')); } }));
  });
  const pending = client.getMe();
  const rejected = assert.rejects(pending, { name: 'TimeoutError' });
  await Promise.resolve();
  t.mock.timers.tick(15000);
  await rejected;
  assert.equal(fetched.url, 'http://localhost:9000/api/v2/auth/me');
  assert.equal(fetched.options.signal.aborted, true);
  assert.equal(window.location.href, '');
});

test('fetchPath still forwards caller cancellation', async () => {
  const caller = new AbortController();
  const reason = new Error('stop request');
  let signal;
  const { client } = clientWith(async (_url, options) => {
    signal = options.signal;
    return new Promise(() => {});
  });
  const pending = client.fetchPath('/example', { signal: caller.signal });
  const rejected = assert.rejects(pending, (error) => error === reason);
  caller.abort(reason);
  await rejected;
  assert.equal(signal.reason, reason);
});

test('401 retains token removal and login redirect', async () => {
  let removed;
  const { client, window } = clientWith(async (_url, options) => {
    assert.equal(options.headers.Authorization, 'Bearer example');
    return new Response(null, { status: 401 });
  }, { getItem: () => 'example', removeItem: (key) => { removed = key; } });
  await assert.rejects(client.getMe(), /Unauthorized/);
  assert.equal(removed, 'nexus-token');
  assert.equal(window.location.href, '/login');
});

test('a stalled request times out at 15 seconds and aborts its signal', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let signal;
  const pending = withRequestTimeout((s) => {
    signal = s;
    return new Promise(() => {});
  });
  const rejected = assert.rejects(pending, (error) => {
    assert.equal(error.name, 'TimeoutError');
    assert.match(error.message, /15/);
    return true;
  });
  t.mock.timers.tick(14999);
  assert.equal(signal.aborted, false);
  t.mock.timers.tick(1);
  await rejected;
  assert.equal(signal.aborted, true);
});

test('the same deadline includes response body parsing', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const response = new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{')); } }));
  const pending = withRequestTimeout(async () => {
    t.mock.timers.tick(10000);
    return response.json();
  });
  const rejected = assert.rejects(pending, { name: 'TimeoutError' });
  t.mock.timers.tick(5000);
  await rejected;
});

test('caller cancellation preserves its reason and removes the listener', async (t) => {
  const caller = new AbortController();
  const remove = t.mock.method(caller.signal, 'removeEventListener');
  let signal;
  const pending = withRequestTimeout((s) => {
    signal = s;
    return new Promise(() => {});
  }, caller.signal);
  const reason = new Error('caller cancelled');
  const rejected = assert.rejects(pending, (error) => error === reason);
  caller.abort(reason);
  await rejected;
  assert.equal(signal.reason, reason);
  assert.equal(remove.mock.callCount(), 1);
});

test('an already aborted caller does not start the request', async () => {
  const caller = new AbortController();
  caller.abort();
  let started = false;
  await assert.rejects(withRequestTimeout(async () => { started = true; }, caller.signal), { name: 'AbortError' });
  assert.equal(started, false);
});

for (const fails of [false, true]) {
  test(`cleanup on ${fails ? 'failure' : 'success'} clears the timer and caller listener`, async (t) => {
    const clear = t.mock.method(globalThis, 'clearTimeout');
    const caller = new AbortController();
    const remove = t.mock.method(caller.signal, 'removeEventListener');
    const reason = new Error('network failure');
    const pending = withRequestTimeout(async () => {
      if (fails) throw reason;
      return 42;
    }, caller.signal);
    if (fails) await assert.rejects(pending, (error) => error === reason);
    else assert.equal(await pending, 42);
    assert.equal(clear.mock.callCount(), 1);
    assert.equal(remove.mock.callCount(), 1);
  });
}
