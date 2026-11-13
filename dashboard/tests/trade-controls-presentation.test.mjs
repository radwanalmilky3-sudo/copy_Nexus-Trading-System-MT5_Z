import assert from 'node:assert/strict';
import test from 'node:test';
import {
  autoTradeEnabled,
  autoTradeServerCheck,
  killSwitchOutcome,
  manualOrderOutcome,
  manualOrderPayload,
  modeSwitchOutcome,
  tradesPausedBanner,
} from '../src/lib/trade-controls-presentation.ts';

// ── Kill switch: the store never latches from an unconfirmed response ──

test('kill switch activates only on the exact server-confirmed status', () => {
  assert.equal(killSwitchOutcome({ success: true, data: { status: 'kill_switch_activated' } }, 'kill').ok, true);
  assert.equal(killSwitchOutcome({ success: true, data: { status: 'kill_switch_released' } }, 'kill').ok, false,
    'a release echo must not latch the kill switch');
  assert.equal(killSwitchOutcome({ success: false, data: { status: 'kill_switch_activated' } }, 'kill').ok, false,
    'success:false with the right status is still a rejection');
});

test('kill switch rejects malformed and absent payloads', () => {
  assert.equal(killSwitchOutcome(null, 'kill').ok, false);
  assert.equal(killSwitchOutcome({}, 'kill').ok, false);
  assert.equal(killSwitchOutcome({ success: true }, 'kill').ok, false);
  assert.equal(killSwitchOutcome({ success: true, data: { status: 123 } }, 'kill').ok, false,
    'a non-string status is not a confirmation');
  assert.equal(killSwitchOutcome({ success: true, data: { status: 'kill_switch_activated ' } }, 'kill').ok, false,
    'no trimming/normalization — exact match or nothing');
});

test('release mirrors the same exactness', () => {
  assert.equal(killSwitchOutcome({ success: true, data: { status: 'kill_switch_released' } }, 'release').ok, true);
  assert.equal(killSwitchOutcome({ success: true, data: { status: 'kill_switch_activated' } }, 'release').ok, false);
});

// ── Auto-trade: guard + server echo must equal the request ──

test('auto-trade is touchable only when confirmed, not killed, not busy', () => {
  assert.equal(autoTradeEnabled({ isKilled: false, busy: false, systemStateStatus: 'confirmed' }), true);
  assert.equal(autoTradeEnabled({ isKilled: true, busy: false, systemStateStatus: 'confirmed' }), false,
    'a latched kill switch blocks the toggle');
  assert.equal(autoTradeEnabled({ isKilled: false, busy: true, systemStateStatus: 'confirmed' }), false);
  assert.equal(autoTradeEnabled({ isKilled: false, busy: false, systemStateStatus: 'loading' }), false,
    'unknown system state must not allow trading changes');
  assert.equal(autoTradeEnabled({ isKilled: false, busy: false, systemStateStatus: 'unavailable' }), false);
});

test('auto-trade server echo must equal the requested state', () => {
  assert.equal(autoTradeServerCheck({ data: { auto_trade: true } }, true), true);
  assert.throws(() => autoTradeServerCheck({ data: { auto_trade: false } }, true),
    /الخادم لم يؤكد الحالة المطلوبة/,
    'server saying false while enabling must surface an error, never a false ON');
  assert.throws(() => autoTradeServerCheck({ data: {} }, true));
  assert.throws(() => autoTradeServerCheck({ data: { auto_trade: 'true' } }, true),
    'string "true" is not a boolean confirmation');
  assert.throws(() => autoTradeServerCheck(null, false));
  assert.equal(autoTradeServerCheck({ data: { auto_trade: false } }, false), false);
});

// ── Mode switch: gateway-confirmed only, LIVE never applicable ──

test('mode switch applies only the confirmed paper mode', () => {
  const ok = modeSwitchOutcome(
    { data: { mode: 'PAPER', auto_trade: true, kill_switch: false } }, 'paper');
  assert.deepEqual(ok, { ok: true, mode: 'PAPER', autoTrade: true, killSwitch: false });
  assert.equal(modeSwitchOutcome({ data: { mode: 'paper' } }, 'paper').ok, true,
    'case-insensitive echo is accepted');
});

test('mode switch rejects mismatched or malformed echoes', () => {
  assert.equal(modeSwitchOutcome({ data: { mode: 'LIVE' } }, 'paper').ok, false,
    'LIVE can never come from the dashboard');
  assert.equal(modeSwitchOutcome({ data: {} }, 'paper').ok, false);
  assert.equal(modeSwitchOutcome(null, 'paper').ok, false);
  assert.equal(modeSwitchOutcome({ data: { mode: 42 } }, 'paper').ok, false);
});

test('mode latch booleans are strict true, absent means off', () => {
  const absent = modeSwitchOutcome({ data: { mode: 'paper' } }, 'paper');
  assert.equal(absent.ok && absent.autoTrade, false);
  assert.equal(absent.ok && absent.killSwitch, false);
  const truthy = modeSwitchOutcome({ data: { mode: 'paper', auto_trade: 'yes', kill_switch: 1 } }, 'paper');
  assert.equal(truthy.ok && truthy.autoTrade, false, 'non-boolean truthy values are not confirmations');
  assert.equal(truthy.ok && truthy.killSwitch, false);
});

// ── Manual order outcome: the server's word is rendered verbatim ──

test('manual order outcome passes executor confirmations through', () => {
  assert.deepEqual(
    manualOrderOutcome({ success: true, data: { status: 'FILLED' } }),
    { ok: true, message: 'حالة المنفّذ: FILLED' },
  );
  assert.equal(manualOrderOutcome({ success: true, data: { status: 'PENDING' } }).ok, true);
  assert.equal(manualOrderOutcome({ success: true, data: { status: 'PARTIAL' } }).ok, true);
});

test('manual order outcome surfaces guard and risk rejections with their real reason', () => {
  const blocked = manualOrderOutcome({
    success: true,
    data: { status: 'GUARD_BLOCKED_AUTO_TRADE_OFF', error: 'تم منع الصفقة لأن التداول الآلي غير مفعل بشكل صريح.' },
  });
  assert.equal(blocked.ok, false);
  assert.match(blocked.message, /التداول الآلي غير مفعل/, 'the guard reason reaches the user verbatim');

  const rejected = manualOrderOutcome({
    success: true,
    data: { status: 'RISK_REJECTED', message_ar: 'رفضت إدارة المخاطر الصفقة؛ راجع الأسباب أعلاه.' },
  });
  assert.equal(rejected.ok, false);
  assert.match(rejected.message, /إدارة المخاطر/);

  const dedup = manualOrderOutcome({ success: true, data: { status: 'DEDUP_SKIPPED', error: 'Duplicate order' } });
  assert.equal(dedup.ok, false, 'a skipped duplicate is NOT a success');
});

test('manual order outcome never invents success from an empty or unknown response', () => {
  assert.equal(manualOrderOutcome(null).ok, false);
  assert.equal(manualOrderOutcome({}).ok, false);
  assert.equal(manualOrderOutcome({ success: false }).ok, false);
  const unknown = manualOrderOutcome({ success: true, data: { status: 'SOMETHING_NEW' } });
  assert.equal(unknown.ok, false, 'an unrecognized status is never reported as a fill');
  assert.match(unknown.message, /SOMETHING_NEW/);
});

// ── Manual order payload: numeric validity before anything is sent ──

test('manual order payload parses form strings into numbers', () => {
  assert.deepEqual(
    manualOrderPayload({ symbol: 'XAUUSD', lots: '0.01', sl: '50', tp: '100', price: 2035.5 }),
    { symbol: 'XAUUSD', lots: 0.01, sl: 50, tp: 100, price: 2035.5 },
  );
});

test('manual order payload rejects invalid orders instead of sending them', () => {
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: '0', sl: '50', tp: '100', price: 2035.5 }), null,
    'zero lots is not an order');
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: '-1', sl: '50', tp: '100', price: 2035.5 }), null);
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: 'abc', sl: '50', tp: '100', price: 2035.5 }), null,
    'unparsable lots must not reach any API');
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: '0.01', sl: '-5', tp: '100', price: 2035.5 }), null,
    'negative SL is invalid');
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: '0.01', sl: '50', tp: '100', price: 0 }), null,
    'a zero price is not a market');
  assert.equal(manualOrderPayload({ symbol: '', lots: '0.01', sl: '50', tp: '100', price: 2035.5 }), null);
  assert.equal(manualOrderPayload({ symbol: 'XAUUSD', lots: '0.01', sl: '', tp: '100', price: 2035.5 }), null,
    'an empty SL must not silently mean "no stop loss" — explicit 0 only');
});

// ── Trade settings: daily-limit banner condition ──

test('daily-limit banner shows on explicit pause or reached cap', () => {
  assert.equal(tradesPausedBanner({ trades_paused: true }, { max_daily_trades: 10 }), true);
  assert.equal(tradesPausedBanner({ daily_trade_count: 10 }, { max_daily_trades: 10 }), true,
    'count reaching the cap shows the banner');
  assert.equal(tradesPausedBanner({ daily_trade_count: 9 }, { max_daily_trades: 10 }), false);
  assert.equal(tradesPausedBanner({ daily_trade_count: 99 }, null), false,
    'no settings yet → no cap comparison');
  assert.equal(tradesPausedBanner({}, { max_daily_trades: 10 }), false);
  assert.equal(tradesPausedBanner({ trades_paused: false, daily_trade_count: 0 }, { max_daily_trades: 10 }), false);
});
