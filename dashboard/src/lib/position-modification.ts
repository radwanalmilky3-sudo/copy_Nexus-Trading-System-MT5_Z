export type PositionModificationInput = {
  side: string;
  currentPrice: number;
};

export type PositionModificationPayload = {
  sl?: number;
  tp1?: number;
};

export type PositionModificationResult =
  | { ok: true; payload: PositionModificationPayload }
  | {
      ok: false;
      reason:
        | 'no_changes'
        | 'price_unavailable'
        | 'invalid_stop_loss'
        | 'invalid_take_profit'
        | 'stop_loss_not_protective'
        | 'take_profit_not_profitable';
    };

export function preparePositionModification(
  position: PositionModificationInput,
  slText: string,
  tpText: string,
): PositionModificationResult {
  const hasSl = slText.trim() !== '';
  const hasTp = tpText.trim() !== '';
  if (!hasSl && !hasTp) return { ok: false, reason: 'no_changes' };
  if (!Number.isFinite(position.currentPrice) || position.currentPrice <= 0) {
    return { ok: false, reason: 'price_unavailable' };
  }

  const side = position.side.toUpperCase();
  if (side !== 'BUY' && side !== 'SELL') return { ok: false, reason: 'price_unavailable' };
  const isBuy = side === 'BUY';
  const payload: PositionModificationPayload = {};

  if (hasSl) {
    const sl = Number(slText);
    if (!Number.isFinite(sl) || sl <= 0) return { ok: false, reason: 'invalid_stop_loss' };
    if (isBuy ? sl >= position.currentPrice : sl <= position.currentPrice) {
      return { ok: false, reason: 'stop_loss_not_protective' };
    }
    payload.sl = sl;
  }

  if (hasTp) {
    const tp = Number(tpText);
    if (!Number.isFinite(tp) || tp <= 0) return { ok: false, reason: 'invalid_take_profit' };
    if (isBuy ? tp <= position.currentPrice : tp >= position.currentPrice) {
      return { ok: false, reason: 'take_profit_not_profitable' };
    }
    payload.tp1 = tp;
  }

  return { ok: true, payload };
}
