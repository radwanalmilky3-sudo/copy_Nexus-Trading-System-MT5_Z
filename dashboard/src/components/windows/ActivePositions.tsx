'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import NeonCard from '../shared/NeonCard';
import { apiClient } from '@/lib/api-client';
import { useDashboardStore } from '@/stores/dashboardStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import { gatewayWsUrl } from '@/lib/gateway-ws';
import { getPositionConnectionLabel } from '@/lib/position-status';
import { positionPresentation } from '@/lib/data-presentation';
import { preparePositionModification } from '@/lib/position-modification';

interface LocalPosition {
  id: string;
  symbol: string;
  side: string;
  entry_price: number;
  current_price: number;
  sl: number;
  tp1: number;
  tp2?: number;
  tp3?: number;
  size: number;
  pnl_pips: number;
  pnl_usd: number;
  duration: number;
  conviction: number;
  status: string;
  opened_at: string;
  reasoning?: string;
}

function mapGatewayToLocal(row: Record<string, unknown>): LocalPosition {
  const sym = String(row.symbol ?? '').trim();
  const sideRaw = String(row.side ?? 'BUY').toUpperCase();
  const isLong = !sideRaw.includes('SELL');
  const entry = Number(row.entry_price ?? 0);
  const cur = Number(row.current_price ?? 0);
  let pipMult = 10_000;
  if (sym.includes('JPY')) pipMult = 100;
  else if (sym.includes('XAU') || sym.includes('XAG')) pipMult = 10;
  else if (sym.includes('BTC') || sym.includes('ETH')) pipMult = 1;

  const pipDelta =
    pipMult === 1
      ? (isLong ? cur - entry : entry - cur)
      : (isLong ? cur - entry : entry - cur) * pipMult;

  return {
    id: String(row.id ?? ''),
    symbol: sym,
    side: isLong ? 'BUY' : 'SELL',
    entry_price: entry,
    current_price: cur,
    sl: Number(row.sl ?? 0),
    tp1: Number(row.tp1 ?? row.tp ?? 0),
    tp2: row.tp2 != null ? Number(row.tp2) : undefined,
    tp3: row.tp3 != null ? Number(row.tp3) : undefined,
    size: Number(row.size ?? 0),
    pnl_pips: Number.isFinite(Number(row.pnl_pips)) ? Number(row.pnl_pips) : +pipDelta.toFixed(1),
    pnl_usd: Number(row.pnl_usd ?? 0),
    duration: Number(row.duration ?? 0),
    conviction: Number(row.conviction ?? 0) > 1 ? Number(row.conviction) / 100 : Number(row.conviction ?? 0.65),
    status: String(row.status ?? 'open'),
    opened_at: typeof row.opened_at === 'string' ? row.opened_at : '',
    reasoning: typeof row.reasoning === 'string' ? row.reasoning : undefined,
  };
}

function decimalsForSymbol(sym: string, price: number): number {
  if (sym.includes('JPY')) return 3;
  if (sym.includes('BTC') || sym.includes('ETH')) return 2;
  if (sym.includes('XAU') || sym.includes('XAG') || price >= 50) return 2;
  return 5;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function pnlColor(v: number): string {
  if (v > 0) return 'text-neon-green';
  if (v < 0) return 'text-neon-red';
  return 'text-text-muted';
}

function pnlGlow(v: number): string {
  if (v > 0) return '';
  if (v < 0) return '';
  return '';
}

function sideBadge(side: string) {
  const isLong = side === 'BUY';
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-[10px] font-mono font-bold uppercase ${
        isLong
          ? 'bg-neon-green/10 text-neon-green'
          : 'bg-neon-red/10 text-neon-red'
      }`}
    >
      {isLong ? 'LONG' : 'SHORT'}
    </span>
  );
}

function convictionBar(c: number) {
  const color = c >= 0.7 ? '#00ff88' : c >= 0.5 ? '#ffcc00' : '#ff2255';
  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1 w-12 rounded-full bg-bg-tertiary overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${c * 100}%`, backgroundColor: color }} />
      </div>
      <span className="text-[10px] font-mono" style={{ color }}>{(c * 100).toFixed(0)}%</span>
    </div>
  );
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ActivePositions() {
  const [positions, setPositions] = useState<LocalPosition[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [editingPosition, setEditingPosition] = useState<LocalPosition | null>(null);
  const [editSl, setEditSl] = useState('');
  const [editTp, setEditTp] = useState('');
  const [modifyError, setModifyError] = useState<string | null>(null);
  const [modifyNotice, setModifyNotice] = useState<string | null>(null);
  const [savingModification, setSavingModification] = useState(false);
  const [liveConnected, setLiveConnected] = useState(false);
  const [snapshotStale, setSnapshotStale] = useState(false);
  const [snapshotReceived, setSnapshotReceived] = useState(false);
  const [dataSource, setDataSource] = useState('cache');
  const [accountBroker, setAccountBroker] = useState<string | null>(null);
  const [nexusCount, setNexusCount] = useState(0);
  const [externalCount, setExternalCount] = useState(0);
  const setAccount = useDashboardStore((s) => s.setAccount);

  const refresh = useCallback(async () => {
    try {
      const res = await apiClient.getPositionsSnapshot();
      const mapped = (res.data.positions as Record<string, unknown>[]).map(mapGatewayToLocal).filter((p) => p.id);
      setPositions(mapped);
      setLiveConnected(Boolean(res.data.live_connected));
      setSnapshotStale(false);
      setSnapshotReceived(true);
      setDataSource(String(res.data.source ?? 'unknown'));
      setNexusCount(Number(res.data.nexus_count ?? 0));
      setExternalCount(Number(res.data.external_count ?? 0));
      const account = res.data.account;
      if (account) {
        setAccountBroker(typeof account.broker === 'string' ? account.broker.toUpperCase() : null);
        setAccount({
          balance: Number(account.balance ?? 0),
          equity: Number(account.equity ?? 0),
          margin: Number(account.margin ?? 0),
          freeMargin: Number(account.free_margin ?? 0),
          openPositions: mapped.length,
        });
      } else {
        setAccountBroker(null);
        setAccount({ openPositions: mapped.length });
      }
      setError(null);
    } catch (e) {
      setSnapshotStale(true);
      setError(e instanceof Error ? e.message : 'تعذر تحميل المراكز');
    }
  }, [setAccount]);

  // WebSocket-driven refresh: nexus-api's position_broadcaster pushes an
  // event on every price/PnL update and on close, so we refetch the full
  // snapshot immediately instead of waiting for the next poll tick. The
  // 45s interval below is only a safety net for a dropped/reconnecting
  // socket, not the primary freshness mechanism.
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const wsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { isConnected: wsConnected } = useWebSocket({
    url: gatewayWsUrl('/positions'),
    onMessage: () => {
      // Multiple position updates often arrive back-to-back (one per open
      // position) — coalesce into a single refetch.
      if (wsDebounceRef.current) clearTimeout(wsDebounceRef.current);
      wsDebounceRef.current = setTimeout(() => refreshRef.current(), 250);
    },
  });

  useEffect(() => {
    refresh();
    const pollMs = wsConnected ? 45_000 : 8_000;
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [refresh, wsConnected]);

  const onClose = async (pos: LocalPosition, e: React.MouseEvent) => {
    e.stopPropagation();
    setClosingId(pos.id);
    try {
      await apiClient.closePosition(pos.id);
      await refresh();
    } catch {
      setError(`تعذر إغلاق ${pos.symbol} (#${pos.id})`);
    } finally {
      setClosingId(null);
    }
  };

  const onSaveModification = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!editingPosition || savingModification) return;

    const latestPosition = positions.find((position) => position.id === editingPosition.id);
    if (!latestPosition || snapshotStale || !liveConnected) {
      setModifyError('يلزم لقطة مراكز حديثة من منفّذ التنفيذ. حدّث المراكز قبل الإرسال.');
      return;
    }

    const prepared = preparePositionModification(
      { side: latestPosition.side, currentPrice: latestPosition.current_price },
      editSl,
      editTp,
    );
    if (!prepared.ok) {
      const messages: Record<typeof prepared.reason, string> = {
        no_changes: 'أدخل قيمة جديدة لـ Stop Loss أو Take Profit. الحقول الفارغة تُبقي القيم الحالية.',
        price_unavailable: 'يلزم سعر حي صالح واتجاه المركز للتحقق من هذه المستويات.',
        invalid_stop_loss: 'يجب أن يكون Stop Loss عددًا محدودًا أكبر من صفر.',
        invalid_take_profit: 'يجب أن يكون Take Profit عددًا محدودًا أكبر من صفر.',
        stop_loss_not_protective: 'لهذا الاتجاه يجب أن يكون Stop Loss أبعد من السعر الحالي في اتجاه الحماية.',
        take_profit_not_profitable: 'لهذا الاتجاه يجب أن يكون Take Profit أبعد من السعر الحالي في اتجاه الربح.',
      };
      setModifyError(messages[prepared.reason]);
      return;
    }

    const changes = [
      prepared.payload.sl != null ? `SL ${prepared.payload.sl}` : null,
      prepared.payload.tp1 != null ? `TP ${prepared.payload.tp1}` : null,
    ].filter(Boolean).join(', ');
    if (!window.confirm(`إرسال تعديل ${latestPosition.side} ${latestPosition.symbol} (${changes}) بالسعر الحالي ${latestPosition.current_price} إلى خدمة التنفيذ؟`)) {
      return;
    }

    setSavingModification(true);
    setModifyError(null);
    try {
      const response = await apiClient.modifyPosition(editingPosition.id, prepared.payload);
      const outcome = String(response.data.status ?? '').toUpperCase();
      setModifyNotice(
        outcome === 'FILLED' || outcome === 'PARTIAL'
          ? `تُبلّغ خدمة التنفيذ بحالة ${outcome} لـ ${editingPosition.symbol}.`
          : `طلب التعديل معلّق لـ ${editingPosition.symbol}؛ التنفيذ غير مؤكد بعد.`,
      );
      setEditingPosition(null);
      setEditSl('');
      setEditTp('');
      await refresh();
    } catch (err) {
      setModifyError(err instanceof Error ? err.message : 'تعذّر إرسال طلب تعديل المركز.');
    } finally {
      setSavingModification(false);
    }
  };

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl_usd, 0);
  const presentation = positionPresentation({ received: snapshotReceived, stale: snapshotStale, liveConnected, count: positions.length });

  return (
    <NeonCard
      title="Active Positions"
      glow="green"
      noPadding
      icon={
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M12 2v20M2 12h20" />
        </svg>
      }
      headerRight={
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <span className="text-[10px] font-mono text-neon-green" title="مراكز فيها comment nexus — تُحتسب ضمن risk">
            {presentation.confirmed ? nexusCount : '—'} nexus
          </span>
          {externalCount > 0 && (
            <span className="text-[10px] font-mono text-text-muted" title="مراكز خارجية — تُتجاهل ضمن risk">
              {externalCount} ext
            </span>
          )}
          <span className="text-xs font-mono text-text-muted" dir="rtl">الإجمالي {presentation.confirmed ? positions.length : '—'}</span>
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${
              snapshotStale
                ? 'bg-amber-400/15 text-amber-300'
                : liveConnected
                  ? 'bg-neon-green/15 text-neon-green'
                  : 'bg-neon-red/15 text-neon-red'
            }`}
            title={snapshotStale ? `لقطة قديمة؛ آخر مصدر=${dataSource}` : `المصدر=${dataSource}`}
          >
            {getPositionConnectionLabel({ stale: snapshotStale, liveConnected, accountBroker })}
          </span>
        </div>
      }
      className="h-full flex flex-col"
    >
      {error && (
        <div className="px-3 py-2 text-[10px] font-mono text-neon-red border-b border-neon-red/20 bg-neon-red/5">
          {error}
        </div>
      )}
      {modifyNotice && (
        <div role="status" className="px-3 py-2 text-[10px] font-mono text-neon-green border-b border-neon-green/20 bg-neon-green/5">
          {modifyNotice}
          <button type="button" className="ms-2 underline" onClick={() => setModifyNotice(null)}>إخفاء</button>
        </div>
      )}
      {/* Table */}
      <div className="flex-1 overflow-auto scrollbar-hide">
        <table className="w-full text-[10px] font-mono border-collapse table-fixed">
          <colgroup>
            <col className="w-[72px]" />
            <col className="w-[52px]" />
            <col className="w-[78px]" />
            <col className="w-[78px]" />
            <col className="w-[62px]" />
            <col className="w-[72px]" />
            <col className="w-[72px]" />
            <col className="w-[72px]" />
            <col className="w-[50px]" />
            <col className="w-[70px]" />
            <col className="w-[90px]" />
          </colgroup>
          <thead>
            <tr className="border-b border-border-primary/15 text-text-muted text-[9px] uppercase tracking-wider">
              <th className="sticky top-0 z-10 bg-bg-card px-2 py-1.5 text-start font-semibold">الرمز</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-start font-semibold">الاتجاه</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">Entry</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">الحالي</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">Pips</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">P&L</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">SL</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">TP</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-end font-semibold">الوقت</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-center font-semibold">Conv</th>
              <th className="sticky top-0 z-10 bg-bg-card px-1 py-1.5 text-center font-semibold">إجراءات</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 && (
              <tr>
                <td colSpan={11} className="px-3 py-6 text-center text-[10px] text-text-muted">
                  {presentation.emptyMessage}
                </td>
              </tr>
            )}
            {positions.map((pos) => {
              const isProfit = pos.pnl_usd >= 0;
              const isExpanded = expandedId === pos.id;
              const tps = [pos.tp1, pos.tp2, pos.tp3].filter((v): v is number => v != null && v !== 0);
              const dec = decimalsForSymbol(pos.symbol, pos.entry_price);

              return (
                <React.Fragment key={pos.id}>
                  <tr
                    className={`border-b border-border-primary/5 cursor-pointer transition-colors hover:bg-bg-tertiary/30 ${isProfit ? 'bg-neon-green/[0.02]' : 'bg-neon-red/[0.02]'}`}
                    onClick={() => setExpandedId(isExpanded ? null : pos.id)}
                  >
                    <td className="px-2 py-1.5 text-text-primary font-semibold truncate">{pos.symbol}</td>
                    <td className="px-1 py-1.5">{sideBadge(pos.side)}</td>
                    <td className="px-1 py-1.5 text-right text-text-secondary tabular-nums">{pos.entry_price.toFixed(dec)}</td>
                    <td className="px-1 py-1.5 text-right text-text-primary tabular-nums">{pos.current_price.toFixed(dec)}</td>
                    <td className={`px-1 py-1.5 text-right font-bold tabular-nums ${pnlColor(pos.pnl_pips)}`}>
                      {pos.pnl_pips > 0 ? '+' : ''}{pos.pnl_pips.toFixed(1)}
                    </td>
                    <td className={`px-1 py-1.5 text-right font-bold tabular-nums ${pnlColor(pos.pnl_usd)}`}>
                      {pos.pnl_usd > 0 ? '+' : ''}${pos.pnl_usd.toFixed(2)}
                    </td>
                    <td className="px-1 py-1.5 text-right text-neon-red/70 tabular-nums">{pos.sl > 0 ? pos.sl.toFixed(dec) : '—'}</td>
                    <td className="px-1 py-1.5 text-right text-neon-cyan/70 tabular-nums truncate">
                      {tps.length === 0 ? '—' : tps[0].toFixed(dec)}
                    </td>
                    <td className="px-1 py-1.5 text-right text-text-muted">{formatDuration(pos.duration)}</td>
                    <td className="px-1 py-1.5">{convictionBar(pos.conviction)}</td>
                    <td className="px-1 py-1.5">
                      <div className="flex items-center gap-1 justify-center">
                        <button
                          type="button"
                          className="rounded bg-neon-red/15 px-1.5 py-0.5 text-[9px] font-bold text-neon-red hover:bg-neon-red/25 transition-colors disabled:opacity-40"
                          disabled={closingId === pos.id}
                          onClick={(e) => onClose(pos, e)}
                        >
                          {closingId === pos.id ? '…' : 'إغلاق'}
                        </button>
                        <button
                          type="button"
                          className="rounded bg-neon-purple/15 px-1.5 py-0.5 text-[9px] font-bold text-neon-purple hover:bg-neon-purple/25 transition-colors disabled:opacity-40"
                          disabled={savingModification || snapshotStale || !liveConnected}
                          title={snapshotStale || !liveConnected ? 'يتطلب التعديل لقطة حديثة من منفّذ التنفيذ' : 'تعديل Stop Loss / Take Profit'}
                          onClick={(e) => {
                            e.stopPropagation();
                            setModifyError(null);
                            setModifyNotice(null);
                            setEditSl('');
                            setEditTp('');
                            setEditingPosition(pos);
                          }}
                        >
                          تعديل
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isExpanded && pos.reasoning && (
                    <tr>
                      <td colSpan={11} className="border-b border-border-primary/10 bg-bg-primary/40 px-3 py-2 animate-fade-in">
                        <p className="text-[9px] font-mono text-neon-purple/70 uppercase tracking-wider mb-1">استدلال الوكيل (Agent Reasoning)</p>
                        <p className="text-[10px] font-mono text-text-secondary leading-relaxed whitespace-pre-wrap">{pos.reasoning}</p>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t border-border-primary/10 px-4 py-2.5 flex items-center justify-between">
        <span className="text-[11px] font-mono text-text-muted">P&L غير محقق</span>
        <span className={`text-sm font-mono font-bold ${pnlColor(totalPnl)} ${pnlGlow(totalPnl)}`}>
          {presentation.confirmed ? `${totalPnl > 0 ? '+' : ''}$${totalPnl.toFixed(2)}` : '—'}
        </span>
      </div>
      {editingPosition && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-4"
          onMouseDown={(event) => { if (event.target === event.currentTarget && !savingModification) setEditingPosition(null); }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="position-modify-title"
            className="w-full max-w-md rounded-lg border border-neon-purple/30 bg-bg-card p-5 shadow-2xl"
          >
            <h2 id="position-modify-title" className="text-sm font-bold text-text-primary">Modify {editingPosition.symbol}</h2>
            <p className="mt-1 text-[10px] font-mono text-text-muted">
              {editingPosition.side} · current {Number.isFinite(editingPosition.current_price) ? editingPosition.current_price : 'unavailable'}
            </p>
            <p className="mt-3 text-[10px] text-amber-300">Blank fields keep the current level. Nothing is sent until you save and confirm.</p>
            <form className="mt-4 space-y-3" onSubmit={onSaveModification}>
              <label className="block text-[10px] font-mono text-text-secondary">
                Stop loss <span className="text-text-muted">(current: {editingPosition.sl > 0 ? editingPosition.sl : 'not set'})</span>
                <input
                  type="number"
                  inputMode="decimal"
                  step={10 ** -decimalsForSymbol(editingPosition.symbol, editingPosition.current_price)}
                  autoFocus
                  value={editSl}
                  onChange={(event) => setEditSl(event.target.value)}
                  placeholder="Leave blank to keep current SL"
                  disabled={savingModification}
                  className="mt-1 block w-full rounded border border-border-primary/30 bg-bg-primary px-3 py-2 text-text-primary outline-none focus:border-neon-purple/60"
                />
              </label>
              <label className="block text-[10px] font-mono text-text-secondary">
                Take profit <span className="text-text-muted">(current: {editingPosition.tp1 > 0 ? editingPosition.tp1 : 'not set'})</span>
                <input
                  type="number"
                  inputMode="decimal"
                  step={10 ** -decimalsForSymbol(editingPosition.symbol, editingPosition.current_price)}
                  value={editTp}
                  onChange={(event) => setEditTp(event.target.value)}
                  placeholder="Leave blank to keep current TP"
                  disabled={savingModification}
                  className="mt-1 block w-full rounded border border-border-primary/30 bg-bg-primary px-3 py-2 text-text-primary outline-none focus:border-neon-purple/60"
                />
              </label>
              {modifyError && <p role="alert" className="text-[10px] text-neon-red">{modifyError}</p>}
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" disabled={savingModification} onClick={() => setEditingPosition(null)} className="rounded border border-border-primary/30 px-3 py-2 text-[10px] text-text-secondary disabled:opacity-40">Cancel</button>
                <button type="submit" disabled={savingModification} className="rounded bg-neon-purple/20 px-3 py-2 text-[10px] font-bold text-neon-purple disabled:opacity-40">
                  {savingModification ? 'Sending…' : 'Save SL/TP'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </NeonCard>
  );
}
