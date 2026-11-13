// Re-measure the S12/S18 "Tab x2 focus->BODY" findings with a *real* click
// sequence (the QA walker used force:true, which does not continue the focus
// chain, so the recorded FAIL was a measurement artifact -- ISS-007/ISS-009).
//
// Usage: node qa/retest_tab_focus.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';

const AUTH = '../qa/progress/.auth.json';
const BASE = 'http://127.0.0.1:3100';

const TARGETS = [
  { id: 'S12', name: 'وحدة التحكم', route: '/nexus#console' },
  { id: 'S18', name: 'مقارنة النماذج', route: '/nexus/model-comparison' },
];

function describe(el) {
  if (!el) return 'NONE';
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'body' || tag === 'html') return 'BODY';
  const label =
    el.getAttribute?.('aria-label') ||
    el.getAttribute?.('data-testid') ||
    (el.textContent || '').trim().slice(0, 40) ||
    el.getAttribute?.('href') ||
    '';
  return `${tag}${label ? ':' + label : ''}`;
}

const browser = await chromium.launch();
const ctx = await browser.newContext({
  storageState: fs.existsSync(AUTH) ? AUTH : undefined,
  viewport: { width: 1440, height: 900 },
});
const page = await ctx.newPage();
const out = [];

for (const t of TARGETS) {
  try {
    await page.goto(BASE + t.route, { waitUntil: 'domcontentloaded', timeout: 90000 });
  } catch (err) {
    out.push({ id: t.id, route: t.route, seq: [], verdict: 'ERROR', error: String(err).slice(0, 120) });
    continue;
  }
  await page.waitForTimeout(4000);

  // Real click (no force) on the page body starts the focus chain properly.
  await page.mouse.click(5, 5);
  await page.waitForTimeout(200);

  const seq = [];
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press('Tab');
    await page.waitForTimeout(120);
    const d = await page.evaluate(() => {
      const a = document.activeElement;
      if (!a) return 'NONE';
      const tag = (a.tagName || '').toLowerCase();
      if (tag === 'body' || tag === 'html') return 'BODY';
      const label =
        a.getAttribute('aria-label') ||
        a.getAttribute('data-testid') ||
        (a.textContent || '').trim().slice(0, 40) ||
        a.getAttribute('href') ||
        '';
      return tag + (label ? ':' + label : '');
    });
    seq.push(d);
  }

  const advanced = seq.filter((x) => x !== 'BODY' && x !== 'NONE').length >= 2;
  out.push({ id: t.id, route: t.route, seq, verdict: advanced ? 'PASS' : 'FAIL' });
}

await browser.close();

console.log(JSON.stringify(out, null, 2));
const fail = out.filter((o) => o.verdict === 'FAIL');
process.exit(fail.length ? 1 : 0);
