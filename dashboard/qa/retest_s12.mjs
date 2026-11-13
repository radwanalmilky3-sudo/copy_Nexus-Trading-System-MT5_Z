// S12 focus-chain check: click a real focusable control (not page corner) so the
// browser starts a genuine focus chain, then Tab forward.
import { chromium } from 'playwright';
import fs from 'node:fs';

const AUTH = '../qa/progress/.auth.json';
const browser = await chromium.launch();
const ctx = await browser.newContext({
  storageState: fs.existsSync(AUTH) ? AUTH : undefined,
  viewport: { width: 1440, height: 900 },
});
const page = await ctx.newPage();
await page.goto('http://127.0.0.1:3100/nexus#console', {
  waitUntil: 'domcontentloaded',
  timeout: 90000,
});
await page.waitForTimeout(15000);

const summarize = () =>
  page.evaluate(() => {
    const a = document.activeElement;
    if (!a) return 'NONE';
    const tag = (a.tagName || '').toLowerCase();
    if (tag === 'body' || tag === 'html') return 'BODY';
    const l =
      a.getAttribute('aria-label') ||
      a.getAttribute('data-testid') ||
      (a.textContent || '').trim().slice(0, 40) ||
      '';
    return tag + (l ? ':' + l : '');
  });

// Click the first real focusable element to seed the focus chain.
const seeded = await page.evaluate(() => {
  const el = document.querySelector(
    'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  if (!el) return null;
  el.focus();
  return el.tagName.toLowerCase();
});

const seq = [];
for (let i = 0; i < 3; i++) {
  await page.keyboard.press('Tab');
  await page.waitForTimeout(150);
  seq.push(await summarize());
}

const advanced = seq.filter((x) => x !== 'BODY' && x !== 'NONE').length >= 2;
console.log(JSON.stringify({ seeded, seq, verdict: advanced ? 'PASS' : 'FAIL' }, null, 2));
await browser.close();
process.exit(advanced ? 0 : 1);
