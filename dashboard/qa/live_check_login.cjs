/* Live check: login page renders, no console errors, RTL applied. */
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ args: ['--no-proxy-server'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('http://127.0.0.1:3100/login', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForLoadState('load', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(3000);
  const title = await page.title();
  const dir = await page.evaluate(() => document.documentElement.getAttribute('dir'));
  const lang = await page.evaluate(() => document.documentElement.getAttribute('lang'));
  const hasForm = await page.locator('input').count();
  await page.screenshot({ path: 'qa/live_check_login.png', fullPage: false });

  console.log(JSON.stringify({
    title, dir, lang, inputCount: hasForm,
    consoleErrors: errors,
    verdict: errors.length === 0 ? 'PASS' : 'FAIL',
  }, null, 2));
  await browser.close();
})().catch((e) => { console.error('LIVE-CHECK-ERROR', e.message); process.exit(1); });
