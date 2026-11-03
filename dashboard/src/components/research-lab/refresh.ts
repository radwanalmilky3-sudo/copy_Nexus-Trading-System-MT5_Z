/** Owned by the mounted lab: stop polling when it unmounts. */
export function startResearchRefresh(refresh: () => void, timers: Pick<Window, 'setInterval' | 'clearInterval'> = window): () => void {
  const id = timers.setInterval(refresh, 60_000);
  return () => timers.clearInterval(id);
}

export function qualityTime(value?: string): string {
  if (!value || !Number.isFinite(Date.parse(value))) return '—';
  return new Intl.DateTimeFormat('en-GB', { timeZone:'Asia/Aden', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23' }).format(new Date(value)) + ' (عدن)';
}
