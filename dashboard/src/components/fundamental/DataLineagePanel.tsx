'use client';

import { useEffect, useState } from 'react';
import { GitBranch, Database, CheckCircle2, AlertTriangle } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { AssetLineageDTO } from '@/types/fundamental';

function AssetLineage({ asset, data }: { asset: 'XAUUSD'|'BTCUSD'; data?: AssetLineageDTO }) {
  if (!data || data.state !== 'ready' || !data.impact) return <div className="border border-sky-100 p-3 text-xs text-slate-600">{asset}: Data Lineage غير متاح حاليًا.</div>;
  const outcome = data.outcomes?.[0];
  return <section className="border border-sky-200 bg-white p-3">
    <div className="flex items-center justify-between gap-2"><h4 className="flex items-center gap-1 text-xs font-bold text-sky-950"><GitBranch className="h-3.5 w-3.5"/> {asset} — Data Lineage</h4><span className="font-mono text-[9px] text-slate-500">{data.lineage_version ?? '—'}</span></div>
    <div className="mt-2 grid gap-2 text-[10px] sm:grid-cols-3"><div className="border border-sky-100 p-2"><div className="text-slate-500">Impact ID</div><div className="break-all font-mono">{data.impact.impact_id}</div></div><div className="border border-sky-100 p-2"><div className="text-slate-500">Engine</div><div className="font-mono">{data.impact.engine_version ?? '—'}</div></div><div className="border border-sky-100 p-2"><div className="text-slate-500">Known at</div><div className="font-mono">{String(data.impact.known_at ?? '—')}</div></div></div>
    <div className="mt-3 grid gap-3 lg:grid-cols-3">
      <div><div className="mb-1 flex items-center gap-1 text-[10px] font-semibold text-sky-900"><Database className="h-3 w-3"/> المصادر</div><div className="space-y-1">{data.sources.length?data.sources.map((s,i)=><div key={`${String(s.source_id)}-${i}`} className="border border-sky-100 px-2 py-1 text-[10px]"><span className="font-mono font-semibold">{String(s.source_id ?? '—')}</span> <span className="text-slate-500">{String(s.health_state ?? '')}</span></div>):<div className="text-[10px] text-slate-500">لا توجد مصادر مرتبطة.</div>}</div></div>
      <div><div className="mb-1 text-[10px] font-semibold text-sky-900">مسار الأدلة</div><div className="max-h-36 space-y-1 overflow-auto">{data.edges.length?data.edges.map((e,i)=><div key={`${e.from}-${e.to}-${i}`} className="font-mono text-[9px] text-slate-700">{e.from} → {e.relation} → {e.to}</div>):<div className="text-[10px] text-slate-500">لا توجد حواف Lineage.</div>}</div></div>
      <div><div className="mb-1 text-[10px] font-semibold text-sky-900">Outcome Collector</div>{outcome?<div className="border border-emerald-200 bg-emerald-50 p-2 text-[10px] text-emerald-900"><div className="flex items-center gap-1 font-semibold"><CheckCircle2 className="h-3 w-3"/> {outcome.quality ?? 'partial'}</div><div className="mt-1 font-mono">5m {outcome.return_5m ?? '—'}% · 15m {outcome.return_15m ?? '—'}%</div><div className="font-mono">60m {outcome.return_60m ?? '—'}% · 4h {outcome.return_4h ?? '—'}%</div></div>:<div className="flex items-center gap-1 border border-amber-200 bg-amber-50 p-2 text-[10px] text-amber-900"><AlertTriangle className="h-3 w-3"/> لا توجد نتيجة سوق مكتملة بعد.</div>}</div>
    </div>
  </section>;
}

export default function DataLineagePanel() {
  const [xau, setXau] = useState<AssetLineageDTO>();
  const [btc, setBtc] = useState<AssetLineageDTO>();
  const [refreshFailed, setRefreshFailed] = useState(false);
  useEffect(()=>{ let live=true; const load=async()=>{ try { const [a,b]=await Promise.all([apiClient.getFundamentalLineage('XAUUSD'),apiClient.getFundamentalLineage('BTCUSD')]); if(live){setXau(a.data);setBtc(b.data);setRefreshFailed(false);} } catch { if(live) setRefreshFailed(true); } }; void load(); const id=window.setInterval(load,15000); return()=>{live=false;window.clearInterval(id);}; },[]);
  return <div className="space-y-2">{refreshFailed&&<p role="status" className="border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">تعذر تحديث مسار البيانات؛ اللقطات المعروضة قديمة إن وُجدت.</p>}<div className="grid gap-3 xl:grid-cols-2"><AssetLineage asset="XAUUSD" data={xau}/><AssetLineage asset="BTCUSD" data={btc}/></div></div>;
}
