/**
 * Pure decision logic for the trade-controls components, extracted so the
 * critical safety invariants are unit-testable without a browser:
 *  - the emergency stop never latches from an unconfirmed server response;
 *  - auto-trade never claims ON/OFF the server did not confirm;
 *  - mode switches only apply the gateway-confirmed mode;
 *  - manual order payloads are numerically valid before anything is sent.
 * The components consume these functions verbatim — this file is the
 * single source of truth for what "server-confirmed" means in the UI.
 */

export interface KillSwitchResponseLike {
  success?: boolean;
  data?: { status?: unknown };
}

export type KillSwitchMode = 'kill' | 'release';

/**
 * Kill-switch confirmation gate. Returns the server status only when it
 * exactly matches the expected latch state for the requested mode; any
 * other shape (network error, unexpected status, missing data) is a
 * rejection — the store must keep its last server-confirmed state.
 */
export function killSwitchOutcome(
  response: KillSwitchResponseLike,
  mode: KillSwitchMode,
): { ok: boolean; status: string } {
  const status =
    response?.success === true && typeof response?.data?.status === 'string'
      ? response.data.status
      : '';
  const expected = mode === 'kill' ? 'kill_switch_activated' : 'kill_switch_released';
  return { ok: status === expected, status };
}

export interface AutoTradeGuardInput {
  isKilled: boolean;
  busy: boolean;
  systemStateStatus: 'loading' | 'confirmed' | 'unavailable';
}

/**
 * Auto-trade toggle is only touchable when the system state is confirmed,
 * the kill switch is not latched, and no request is in flight.
 */
export function autoTradeEnabled(guard: AutoTradeGuardInput): boolean {
  return !guard.isKilled && !guard.busy && guard.systemStateStatus === 'confirmed';
}

export interface AutoTradeResponseLike {
  data?: { auto_trade?: unknown };
}

/**
 * The server answer must equal the requested state exactly — anything else
 * (boolean coercion surprises, stale echo, absent field) is an error so the
 * UI never shows an auto-trade state the backend did not confirm.
 */
export function autoTradeServerCheck(
  response: AutoTradeResponseLike,
  enabled: boolean,
): boolean {
  if (response?.data?.auto_trade !== enabled) {
    throw new Error('الخادم لم يؤكد الحالة المطلوبة للتداول الآلي');
  }
  return response.data.auto_trade as boolean;
}

export interface ModeSwitchResponseLike {
  data?: { mode?: unknown; auto_trade?: unknown; kill_switch?: unknown };
}

export type ModeSwitchOutcome =
  | {
      ok: true;
      mode: 'PAPER';
      autoTrade: boolean;
      killSwitch: boolean;
    }
  | { ok: false };

/**
 * Mode switches are confirmed by the gateway: the echoed process mode must
 * equal the requested one (case-insensitive), and the latch booleans are
 * accepted only when strictly ``true`` — absent/null means off, never a
 * guess. LIVE is never applicable from the dashboard.
 */
export function modeSwitchOutcome(
  response: ModeSwitchResponseLike,
  target: 'paper',
): ModeSwitchOutcome {
  const mode =
    typeof response?.data?.mode === 'string' ? response.data.mode.toLowerCase() : '';
  if (mode !== target) return { ok: false };
  return {
    ok: true,
    mode: 'PAPER',
    autoTrade: response?.data?.auto_trade === true,
    killSwitch: response?.data?.kill_switch === true,
  };
}

export interface ManualOrderInput {
  symbol: string;
  lots: string | number;
  sl: string | number;
  tp: string | number;
  price: number;
}

export interface ManualOrderPayload {
  symbol: string;
  lots: number;
  sl: number;
  tp: number;
  price: number;
}

/**
 * Manual order payload builder. Input fields are strings from the form;
 * they must parse to finite numbers with a positive lot size before any
 * order intent leaves the panel. An empty SL/TP field is rejected — an
 * omitted stop must be an explicit ``0``, never a silent blank. Returns
 * ``null`` for invalid input so callers can refuse to act instead of
 * sending garbage to the executor.
 */
export function manualOrderPayload(input: ManualOrderInput): ManualOrderPayload | null {
  const blank = (v: string | number) => typeof v === 'string' && v.trim() === '';
  if (blank(input.sl) || blank(input.tp)) return null;
  const lots = Number(input.lots);
  const sl = Number(input.sl);
  const tp = Number(input.tp);
  if (!Number.isFinite(lots) || lots <= 0) return null;
  if (!Number.isFinite(sl) || sl < 0) return null;
  if (!Number.isFinite(tp) || tp < 0) return null;
  if (!Number.isFinite(input.price) || input.price <= 0) return null;
  if (!input.symbol) return null;
  return { symbol: input.symbol, lots, sl, tp, price: input.price };
}

export interface ManualOrderResponseLike {
  success?: boolean;
  data?: {
    status?: unknown;
    error?: unknown;
    decision?: unknown;
    message_ar?: unknown;
  };
}

export interface ManualOrderOutcome {
  ok: boolean;
  message: string;
}

/**
 * Map the gateway/executor manual-order response to an honest UI state.
 * The server's status/error text is rendered verbatim — the panel never
 * invents a success the executor did not report, and guard rejections
 * (kill switch, auto-trade off, news blackout, risk approval) surface
 * with their real reason.
 */
export function manualOrderOutcome(response: ManualOrderResponseLike): ManualOrderOutcome {
  const status =
    response?.success === true && typeof response?.data?.status === 'string'
      ? response.data.status
      : '';
  const error = typeof response?.data?.error === 'string' ? response.data.error : '';
  if (!status) {
    return {
      ok: false,
      message: error || 'تعذر إرسال الأمر؛ لم يصل تأكيد من المنفّذ.',
    };
  }
  if (status === 'RISK_REJECTED') {
    const messageAr =
      typeof response?.data?.message_ar === 'string' && response.data.message_ar
        ? response.data.message_ar
        : 'رفضت إدارة المخاطر الصفقة؛ راجع الأسباب في سجل الاستراتيجيات.';
    return { ok: false, message: messageAr };
  }
  if (status.startsWith('GUARD_BLOCKED')) {
    return {
      ok: false,
      message: error || 'منع حارس التنفيذ الصفقة؛ راجع حالة الأمان (المفتاح/التداول الآلي/نافذة الأخبار).',
    };
  }
  if (status === 'FILLED' || status === 'PARTIAL' || status === 'PENDING') {
    return { ok: true, message: `حالة المنفّذ: ${status}` };
  }
  return {
    ok: false,
    message: error || `حالة غير مؤكدة من المنفّذ: ${status}`,
  };
}

export interface TradeSettingsMeta {
  daily_trade_count?: number;
  trades_paused?: boolean;
  daily_loss_pct?: number;
}

export interface TradeSettingsShape {
  max_daily_trades: number;
}

/**
 * When the daily-trade limit banner must show: the backend explicitly
 * paused trading, or the observed daily count reached the configured cap.
 */
export function tradesPausedBanner(
  meta: TradeSettingsMeta,
  settings: TradeSettingsShape | null,
): boolean {
  if (meta.trades_paused) return true;
  return (
    meta.daily_trade_count !== undefined &&
    settings !== null &&
    meta.daily_trade_count >= settings.max_daily_trades
  );
}
