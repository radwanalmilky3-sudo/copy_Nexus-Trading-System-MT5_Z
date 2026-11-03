export function hasMarketFeedBars(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return false;
  const response = payload as { success?: unknown; data?: unknown };
  return response.success === true && Array.isArray(response.data) && response.data.length > 0;
}
