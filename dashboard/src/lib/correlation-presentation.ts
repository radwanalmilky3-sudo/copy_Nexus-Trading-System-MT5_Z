// Truth-contract presentation helpers for the correlation window.
// Unknown/insufficient/constant values render as "—" — never as 0.
// Observed correlation is context, not cause or prediction.

export type PairCorrStats = {
  corr: number | null;
  sample_count: number;
  coverage: number;
  constant_series: boolean;
  insufficient_data: boolean;
};

export type CorrWindowPayload = {
  window?: number;
  matrix: Record<string, Record<string, number | null>>;
  pairs: Record<string, PairCorrStats>;
  sample_count: number;
  coverage: number;
};

export type CorrDataLike = {
  windows?: Record<string, CorrWindowPayload>;
  matrices?: Record<string, Record<string, Record<string, number | null>>>;
} | null | undefined;

export type CorrCellView = {
  text: string;
  tone: 'value' | 'insufficient' | 'constant' | 'unavailable';
  title: string;
};

export function availableWindowKeys(data: CorrDataLike): string[] {
  const windows = data?.windows;
  if (windows && typeof windows === 'object') {
    const keys = Object.keys(windows).filter((k) => Number.isFinite(Number(k)));
    if (keys.length > 0) return keys.sort((a, b) => Number(a) - Number(b));
  }
  const matrices = data?.matrices;
  if (matrices && typeof matrices === 'object') return Object.keys(matrices);
  return [];
}

function pct(coverage: number): string {
  return `${Math.round(coverage * 100)}%`;
}

export function corrCellPresentation(
  stats: PairCorrStats | undefined,
  val: number | null,
): CorrCellView {
  if (!stats) {
    return { text: '—', tone: 'unavailable', title: 'لا توجد بيانات — ليست ارتباطًا صفريًا' };
  }
  if (stats.insufficient_data) {
    return {
      text: '—',
      tone: 'insufficient',
      title: `بيانات غير كافية — ${stats.sample_count} عيّنة، تغطية ${pct(stats.coverage)}`,
    };
  }
  if (stats.constant_series) {
    return {
      text: '—',
      tone: 'constant',
      title: `سلسلة ثابتة — الارتباط غير معرّف وليس صفريًا (تغطية ${pct(stats.coverage)})`,
    };
  }
  if (stats.corr === null || val === null) {
    return { text: '—', tone: 'unavailable', title: `تغطية ${pct(stats.coverage)}` };
  }
  const shown = val >= 0 ? `+${val.toFixed(2)}` : val.toFixed(2);
  return {
    text: shown,
    tone: 'value',
    title: `${stats.sample_count} عيّنة · تغطية ${pct(stats.coverage)}`,
  };
}

export type LagPairLike = {
  pair: string;
  direction: string | null;
  lead_asset: string | null;
  lag_candles: number | null;
  best_corr?: number | null;
  insufficient_data?: boolean;
};

export type LagPairView = {
  label: string;
  tone: 'lead' | 'sync' | 'unavailable';
};

export function lagPairPresentation(pair: LagPairLike): LagPairView {
  if (pair.insufficient_data || !pair.direction) {
    return { label: '—', tone: 'unavailable' };
  }
  if (pair.direction === 'IN_SYNC') {
    return { label: `${pair.pair} · متزامن (0)`, tone: 'sync' };
  }
  const lead = pair.lead_asset ?? '?';
  const lag = pair.lag_candles ?? 0;
  return { label: `${lead} يسبق ${pair.pair.split('/')[1]} بـ ${lag} شمعة`, tone: 'lead' };
}

export function correlationDisclaimer(): string {
  return 'ارتباط مُلاحَظ على عوائد متزامنة؛ ليس سببًا ولا ضمانًا للتنبؤ.';
}

export function correlationBasisNote(): string {
  return 'الأساس: عوائد متزامنة (جميع النوافذ 20/60/120).';
}
