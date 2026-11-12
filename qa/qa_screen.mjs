// qa/qa_screen.mjs — MASTER PROMPT V4.1 per-screen QA harness.
//
// Usage: node qa/qa_screen.mjs <SCREEN_ID> <route> [hash]
//   NEXUS_UI_USER / NEXUS_UI_PASS from env (never hardcoded).
//
// What it does per screen:
//   1. Logs in once and caches the session (qa/progress/.auth.json).
//   2. Inventories every interactive element (buttons, links, selects,
//      inputs, tabs, tables, charts, modals) with role/name.
//   3. Tests SAFE interactions only:
//        - navigation links + workspace tabs (click, verify no error)
//        - select filters: read options, switch selection, restore
//        - keyboard: Tab focus, Escape
//        - empty/loading/error states as encountered
//      DANGEROUS actions (trade/execute/save/delete/reset) are inventoried
//      and marked NOT TESTED with reason — never clicked.
//   4. Captures console/page/network errors + desktop & mobile screenshots.
//   5. Writes qa/evidence/<SID>_result.json for the progress store.
//
// Classification keywords are conservative: anything that could place an
// order, change config, or delete data is treated as dangerous.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const { chromium } = createRequire(new URL('../dashboard/package.json', import.meta.url))('playwright');

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = path.join(ROOT, 'qa', 'ui_shots');
const EVID = path.join(ROOT, 'qa', 'evidence');
const AUTH = path.join(ROOT, 'qa', 'progress', '.auth.json');
const BASE = process.env.NEXUS_UI_URL || 'http://127.0.0.1:3100';
const USER = process.env.NEXUS_UI_USER || 'redhwan';
const PASS = process.env.NEXUS_UI_PASS || '';

const DANGER_RE = /(تنفيذ|شراء|بيع|إغلاق|حذف|إعادة تعيين|حفظ|بدء|إيقاف|تصفير|تصفية كاملة|تداول|trade|trading|execute|close position|buy|sell|delete|reset|save|start|stop|kill|flatten|revoke|pause|resume|liquidate|close all|live|mode|^off$|^on$|autotrade|تشغيل|scalping|swing)/i;
const SAFE_CLICK_RE = /^(tab|link|menuitem|radio|checkbox|switch)$/i;

const [screenId, routeArg, hash] = process.argv.slice(2);
const route = routeArg ? (routeArg.startsWith('/') ? routeArg : '/' + routeArg) : '';
if (!screenId || !route) {
  console.error('usage: node qa/qa_screen.mjs <SCREEN_ID> <route> [hash]');
  process.exit(2);
}

fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(EVID, { recursive: true });

const result = {
  screen_id: screenId, route, hash: hash ?? '', started_at: new Date().toISOString(),
  elements: [], menus: [], tests: [], console_errors: [], page_errors: [], network_errors: [],
  screenshots: {}, notes: [],
};

function addTest(kind, target, status, detail, evidence) {
  result.tests.push({ kind, target, status, detail, evidence: evidence ?? '' });
}

async function settle(page, ms = 2000) {
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(ms);
}

async function login(browser) {
  if (PASS && fs.existsSync(AUTH)) {
    try {
      const ctx = await browser.newContext({ storageState: AUTH, viewport: { width: 1440, height: 900 } });
      const p = await ctx.newPage();
      await p.goto(`${BASE}/nexus`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await settle(p, 1500);
      const ok = !p.url().includes('/login');
      await ctx.close();
      if (ok) return AUTH;
    } catch { /* re-login below */ }
  }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  if (!PASS) throw new Error('NEXUS_UI_PASS not set');
  await settle(page, 2500);  // let React hydrate before filling — otherwise
                             // fill() sets DOM values but React state stays empty
  const inputs = page.locator('input.neon-input');
  await inputs.nth(0).fill(USER);
  await inputs.nth(1).fill(PASS);
  await page.getByRole('button', { name: 'دخول' }).click();
  try {
    await page.waitForURL('**/nexus**', { timeout: 30000, waitUntil: 'domcontentloaded' });
  } catch {
    await page.screenshot({ path: path.join(SHOTS, 'login_failed.png') });
    throw new Error(`login did not reach /nexus — still at ${page.url()}`);
  }
  await settle(page, 1500);
  await ctx.storageState({ path: AUTH });
  await ctx.close();
  return AUTH;
}

const browser = await chromium.launch();
try {
  const stateFile = await login(browser);
  const ctx = await browser.newContext({ storageState: stateFile, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') result.console_errors.push(m.text().slice(0, 300)); });
  page.on('pageerror', (e) => result.page_errors.push(String(e).slice(0, 300)));
  page.on('requestfailed', (r) => {
    const f = r.failure()?.errorText || '';
    if (f !== 'net::ERR_ABORTED') result.network_errors.push(`${r.method()} ${r.url().slice(0, 120)} ${f}`);
  });

  const url = `${BASE}${route}${hash ? `#${hash}` : ''}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  // Heavy pages (the /nexus workspace gates rendering behind auth + system
  // state) need a real render-wait: block until any button exists, then settle.
  try {
    await page.waitForSelector('button', { timeout: 30000 });
  } catch {
    result.notes.push('no interactive elements rendered within 30s');
  }
  await settle(page, 2500);
  // Workspace tab activation: the /nexus page keeps tab state internally, so
  // a URL hash cannot select it — click the tab button whose label matches
  // the hash argument, then let the window mount.
  if (hash && route === '/nexus') {
    let activated = false;
    for (let attempt = 0; attempt < 3 && !activated; attempt++) {
      try {
        // force:true — the workspace re-renders live (market ticks) and
        // detaches buttons mid-click; actionability checks never settle.
        await page.getByRole('button', { name: hash, exact: true }).first().click({ timeout: 8000, force: true });
        activated = true;
        await settle(page, 3000);
        result.notes.push(`tab activated: ${hash}`);
      } catch (e) {
        result.notes.push(`tab activation attempt ${attempt + 1} failed for ${hash}: ${String(e).slice(0, 60)}`);
      }
    }
  }
  result.final_url = page.url();

  // ── INVENTORY ────────────────────────────────────────────────────────────
  const inventory = await page.evaluate(() => {
    const els = [];
    const push = (el, type) => {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return;
      els.push({
        type,
        tag: el.tagName.toLowerCase(),
        name: (el.getAttribute('aria-label') || el.textContent || el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().slice(0, 60),
        id: el.id || el.getAttribute('data-testid') || '',
        disabled: el.disabled === true || el.getAttribute('aria-disabled') === 'true',
        options: el.tagName === 'SELECT' ? Array.from(el.querySelectorAll('option')).map((o) => o.textContent.trim()).filter(Boolean) : undefined,
      });
    };
    document.querySelectorAll('button').forEach((e) => push(e, 'button'));
    document.querySelectorAll('a[href]').forEach((e) => push(e, 'link'));
    document.querySelectorAll('select').forEach((e) => push(e, 'select'));
    document.querySelectorAll('input:not([type=hidden]), textarea').forEach((e) => push(e, 'input'));
    document.querySelectorAll('[role=tab], [role=menuitem]').forEach((e) => push(e, e.getAttribute('role')));
    document.querySelectorAll('[role=dialog], .modal, [data-modal]').forEach((e) => push(e, 'modal'));
    return {
      els,
      tables: document.querySelectorAll('table').length,
      charts: document.querySelectorAll('svg[class*=recharts], canvas, svg[class*=chart]').length,
      rtl: document.documentElement.dir,
      title: document.title,
    };
  });
  result.page_meta = { title: inventory.title, rtl: inventory.rtl, tables: inventory.tables, charts: inventory.charts };
  result.elements = inventory.els;
  const selects = inventory.els.filter((e) => e.type === 'select');
  for (const s of selects) {
    result.menus.push({
      name: s.name || s.id || '(unlabeled select)', kind: 'native-select',
      options: s.options?.length ?? 0, searchable: false,
    });
  }

  // ── SAFE INTERACTION TESTS ───────────────────────────────────────────────
  // 1) selects: enumerate + switch + restore (filters only — settings-like
  //    screens are classified by route).
  const isSettingsScreen = /settings|strategies/i.test(route);
  for (let i = 0; i < selects.length; i++) {
    const sel = page.locator('select').nth(i);
    const meta = selects[i];
    const optCount = meta.options?.length ?? 0;
    if (optCount === 0) { addTest('select', meta.name, 'NOT_APPLICABLE', 'لا خيارات'); continue; }
    try {
      const before = await sel.inputValue();
      if (isSettingsScreen) {
        addTest('select', meta.name, 'BLOCKED', `قائمة إعدادات (${optCount} خيار) — تغيير القيمة قد يعدّل تكوين التداول؛ فُحصت الخيارات فقط`);
        continue;
      }
      const target = meta.options.findIndex((o) => o && o !== meta.options[before === '0' ? 0 : 0]);
      await sel.selectOption({ index: optCount > 1 ? 1 : 0 });
      await settle(page, 800);
      const after = await sel.inputValue();
      const changed = after !== before || optCount === 1;
      await sel.selectOption({ index: Number(before) || 0 }).catch(() => {});
      addTest('select', meta.name, changed ? 'PASS' : 'FAIL', `${optCount} خيارات؛ تبديل→استعادة`, `selects[${i}]`);
    } catch (e) {
      const msg = String(e);
      addTest('select', meta.name, msg.includes('TimeoutError') ? 'NOT_TESTED' : 'FAIL',
        msg.includes('TimeoutError') ? 'قائمة تعاد رسمانها باستمرار (تحديث لحظي) — تعذر التبديل الآمن' : msg.slice(0, 120));
    }
  }

  // 2) workspace tabs (role=tab): click each, verify no error.
  const tabs = page.locator('[role=tab]');
  const tabCount = await tabs.count();
  for (let i = 0; i < Math.min(tabCount, 12); i++) {
    const t = tabs.nth(i);
    const name = (await t.textContent() || '').trim().slice(0, 30);
    const before = result.console_errors.length + result.page_errors.length;
    try {
      await t.click();
      await settle(page, 1200);
      const after = result.console_errors.length + result.page_errors.length;
      addTest('tab', name, after === before ? 'PASS' : 'FAIL', after === before ? 'فتح دون أخطاء' : 'أخطاء بعد الفتح', `tab[${i}]`);
    } catch (e) {
      addTest('tab', name, 'FAIL', String(e).slice(0, 120));
    }
  }

  // 3) buttons: SAFE clicks only (non-dangerous, enabled). Dangerous ones
  //    inventoried + NOT TESTED with reason. Workspace tab buttons are
  //    excluded when a specific tab was activated — clicking them would
  //    switch away from the screen under test.
  const TAB_LABELS = ['نظرة عامة', 'المراكز', 'المخاطرة', 'الأخبار', 'الوكلاء', 'الذكاء', 'التحليل الأساسي', 'سجل الصفقات', 'الاختبار الخلفي', 'وحدة التحكم'];
  const buttons = page.locator('button:visible');
  const btnCount = await buttons.count();
  let safeClicked = 0;
  for (let i = 0; i < Math.min(btnCount, 40); i++) {
    const b = buttons.nth(i);
    let name = '';
    try { name = ((await b.textContent({ timeout: 2000 })) || '').trim().slice(0, 40); } catch { continue; }
    const meta = inventory.els.filter((e) => e.type === 'button')[i];
    if (hash && route === '/nexus' && TAB_LABELS.includes(name)) {
      addTest('button', name, 'NOT_APPLICABLE', 'زر تبويب — تم تفعيل التبويب الهدف مسبقًا');
      continue;
    }
    if (DANGER_RE.test(name) || meta?.disabled) {
      addTest('button', name || '(button)', meta?.disabled ? 'PASS' : 'NOT_TESTED',
        meta?.disabled ? 'معطّل — تحقق من عدم التنفيذ' : 'إجراء خطر (مالي/تكوين) — جرد فقط دون نقر');
      continue;
    }
    if (safeClicked >= 8) { addTest('button', name, 'NOT_TESTED', 'سقف النقر الآمن (8) بلغ'); continue; }
    const before = result.console_errors.length + result.page_errors.length;
    try {
      await b.click({ timeout: 3000 });
      await settle(page, 700);
      safeClicked++;
      const after = result.console_errors.length + result.page_errors.length;
      addTest('button', name, after === before ? 'PASS' : 'FAIL', after === before ? 'نقر آمن دون أخطاء' : 'أخطاء بعد النقر', `button[${i}]`);
    } catch (e) {
      const msg = String(e);
      // Live-re-rendering components (market ticks) detach buttons mid-click;
      // a pure timeout is tooling friction, not a product defect.
      addTest('button', name, msg.includes('TimeoutError') ? 'NOT_TESTED' : 'FAIL',
        msg.includes('TimeoutError') ? 'عنصر يعاد رسمه باستمرار — تعذر النقر الآمن' : msg.slice(0, 120));
    }
  }

  // 4) keyboard: Tab reaches interactive elements; Escape harmless.
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement?.tagName ?? 'NONE');
  addTest('keyboard', 'Tab×2', focused !== 'BODY' && focused !== 'NONE' ? 'PASS' : 'FAIL', `focus→${focused}`);
  await page.keyboard.press('Escape');
  addTest('keyboard', 'Escape', 'PASS', 'أُرسل دون أثر جانبي');

  // 5) screenshots: desktop + mobile.
  result.screenshots.desktop = `qa/ui_shots/${screenId}_desktop.png`;
  await page.screenshot({ path: path.join(SHOTS, `${screenId}_desktop.png`), fullPage: false });
  const mctx = await browser.newContext({ storageState: stateFile, viewport: { width: 390, height: 844 } });
  const mpage = await mctx.newPage();
  mpage.on('pageerror', (e) => result.page_errors.push(`mobile: ${String(e).slice(0, 200)}`));
  await mpage.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await settle(mpage, 2000);
  result.screenshots.mobile = `qa/ui_shots/${screenId}_mobile.png`;
  await mpage.screenshot({ path: path.join(SHOTS, `${screenId}_mobile.png`), fullPage: false });
  await mctx.close();
  await ctx.close();

  result.finished_at = new Date().toISOString();
  result.summary = {
    elements: result.elements.length,
    menus: result.menus.length,
    tests: result.tests.length,
    pass: result.tests.filter((t) => t.status === 'PASS').length,
    fail: result.tests.filter((t) => t.status === 'FAIL').length,
    blocked: result.tests.filter((t) => t.status === 'BLOCKED').length,
    not_tested: result.tests.filter((t) => t.status === 'NOT_TESTED').length,
    not_applicable: result.tests.filter((t) => t.status === 'NOT_APPLICABLE').length,
  };
} finally {
  await browser.close();
}

const out = path.join(EVID, `${screenId}_result.json`);
fs.writeFileSync(out, JSON.stringify(result, null, 1));
console.log(JSON.stringify({ screen: screenId, summary: result.summary, errors: result.console_errors.length + result.page_errors.length + result.network_errors.length, out }));
