const REQUIRED_TRADE_STATS = [
  'total_trades', 'winning', 'losing', 'win_rate', 'total_pnl',
  'avg_pnl', 'avg_rr', 'best_trade', 'worst_trade', 'avg_duration_s',
] as const;

export function hasCompleteTradeStats(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const stats = value as Record<string, unknown>;
  return REQUIRED_TRADE_STATS.every((key) => typeof stats[key] === 'number' && Number.isFinite(stats[key]));
}
