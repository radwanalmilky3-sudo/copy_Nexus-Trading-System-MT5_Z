export interface PositionSnapshotStatus {
  stale: boolean;
  liveConnected: boolean;
  accountBroker: string | null;
}

export function getPositionConnectionLabel(status: PositionSnapshotStatus): string {
  if (status.stale) return 'STALE';
  return status.liveConnected
    ? `LIVE${status.accountBroker ? `:${status.accountBroker}` : ''}`
    : 'OFFLINE';
}
