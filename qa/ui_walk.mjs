// qa/ui_walk.mjs — Nexus Dashboard UI walk (screenshots + console/network error report)
//
// What it does:
//   1. Opens /login, screenshots it (pre-login state)
//   2. Logs in with NEXUS_UI_USER / NEXUS_UI_PASS (defaults: redhwan / from env)
//   3. Walks every main route, screenshots each page (desktop + mobile viewport)
//   4. Collects console errors, page errors, failed network requests per page
//   5. Writes qa/ui_report.json + PNG screenshots into qa/ui_shots/
//
// Setup (one time):
//   cd dashboard
//   npm i -D playwright
//   npx playwright install chromium
//
// Run (from project root, after the system is up on :3100):
//   Windows CMD:
//     set NEXUS_UI_USER=redhwan&& set NEXUS_UI_PASS=your-password&& node qa\ui_walk.mjs
//   Git Bash:
//     NEXUS_UI_USER=redhwan NEXUS_UI_PASS='your-password' node qa/ui_walk.mjs
//
// Never pass real secrets in code — env vars only.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

// Playwright is installed as a dashboard devDependency — resolve from there so
// this script can live in qa/ without duplicating the dependency at the root.
const { chromium } = createRequire(
  new URL('../dashboard/package.json', import.meta.url)
)('playwright');

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = path.join(ROOT, 'qa', 'ui_shots');
const BASE = process.env.NEXUS_UI_URL || 'http://localhost:3100';
const USER = process.env.NEXUS_UI_USER || 'redhwan';
const PASS = process.env.NEXUS_UI_PASS || '';
const REPORT = path.join(ROOT, 'qa', 'ui_report.json');

// Routes walked after login (discovered from dashboard/src/app)
const ROUTES = ['/', '/nexus', '/analytics', '/history', '/settings'];
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
];

fs.mkdirSync(SHOTS, { recursive: true });

const report = { startedAt: new Date().toISOString(), base: BASE, pages: [], login: null };

function attachListeners(page, bucket) {
  page.on('console', (msg) => {
    if (msg.type() === 'error') bucket.consoleErrors.push(msg.text().slice(0, 500));
  });
  page.on('pageerror', (err) => bucket.pageErrors.push(String(err).slice(0, 500)));
  page.on('requestfailed', (req) => {
    const failure = req.failure()?.errorText || 'unknown';
    // Ignore aborted requests (navigation cancels) — they are not real defects.
    if (failure !== 'net::ERR_ABORTED') {
      bucket.networkErrors.push({ url: req.url().slice(0, 300), error: failure });
    }
  });
  page.on('response', (res) => {
    if (res.status() >= 500) {
      bucket.http5xx.push({ url: res.url().slice(0, 300), status: res.status() });
    }
  });
}

async function shot(page, name) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return path.relative(ROOT, file);
}

const browser = await chromium.launch({ headless: true });
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const bucket = { consoleErrors: [], pageErrors: [], networkErrors: [], http5xx: [] };
  attachListeners(page, bucket);

  // ── 1. Login page (pre-login) ────────────────────────────────────────────
  // The dashboard keeps a live WebSocket/SSE open, so 'networkidle' never
  // fires — wait for DOM readiness plus a settle window instead.
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2500);
  report.login = { ...bucket, screenshot: await shot(page, 'login-desktop') };

  if (!PASS) {
    report.login.warning = 'NEXUS_UI_PASS not set — walked login page only.';
    console.warn('[ui-walk] NEXUS_UI_PASS not set — stopping after login page.');
  } else {
    // ── 2. Log in ──────────────────────────────────────────────────────────
    // The login form has two .neon-input fields: username, then password.
    const inputs = page.locator('input.neon-input');
    await inputs.nth(0).fill(USER);
    await inputs.nth(1).fill(PASS);
    await page.getByRole('button', { name: 'دخول' }).click();
    try {
      await page.waitForURL('**/nexus', { timeout: 20000 });
      report.login.loggedIn = true;
    } catch {
      report.login.loggedIn = false;
      report.login.postLoginUrl = page.url();
      report.login.screenshotAfterAttempt = await shot(page, 'login-after-attempt');
      console.error('[ui-walk] Login did not reach /nexus — see login-after-attempt.png');
    }

    // ── 3. Walk routes in both viewports ───────────────────────────────────
    for (const vp of VIEWPORTS) {
      for (const route of ROUTES) {
        const pb = { consoleErrors: [], pageErrors: [], networkErrors: [], http5xx: [] };
        const entry = { viewport: vp.name, route, ...pb };
        try {
          const p = await ctx.newPage();
          await p.setViewportSize({ width: vp.width, height: vp.height });
          attachListeners(p, entry);
          await p.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
          await p.waitForTimeout(2500); // let charts/websockets settle
          entry.screenshot = await shot(p, `${route.replace(/\//g, '_') || 'root'}-${vp.name}`);
          // Horizontal overflow check (a common visual defect)
          entry.horizontalOverflow =
            (await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2)) ||
            false;
          await p.close();
        } catch (err) {
          entry.error = String(err).slice(0, 300);
        }
        report.pages.push(entry);
        console.log(`[ui-walk] ${vp.name} ${route} done`);
      }
    }
  }
} finally {
  await browser.close();
}

report.finishedAt = new Date().toISOString();
fs.writeFileSync(REPORT, JSON.stringify(report, null, 2));

// Console summary
const total = (key) =>
  (report.login?.[key]?.length || 0) + report.pages.reduce((n, p) => n + (p[key]?.length || 0), 0);
console.log('\n──────── ui_walk summary ────────');
console.log(`login ok:        ${report.login?.loggedIn ?? 'n/a'}`);
console.log(`console errors:  ${total('consoleErrors')}`);
console.log(`page errors:     ${total('pageErrors')}`);
console.log(`network errors:  ${total('networkErrors')}`);
console.log(`HTTP 5xx:        ${total('http5xx')}`);
console.log(`report:          ${path.relative(ROOT, REPORT)}`);
console.log(`screenshots:     ${path.relative(ROOT, SHOTS)}\\`);
