'use client';

import { useEffect, useMemo, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { apiClient } from '@/lib/api-client';
import type { AssetImpactSnapshotDTO, GoldOverviewDTO } from '@/types/fundamental';

export default function FundamentalCharts({ overview }: { overview: GoldOverviewDTO }) {
  const [xau, setXau] = useState<AssetImpactSnapshotDTO>();
  const [btc, setBtc] = useState<AssetImpactSnapshotDTO>();
  const [refreshFailed, setRefreshFailed] = useState(false);
  useEffect(()=>{ let live=true; const load=async()=>{ try { const [a,b]=await Promise.all([apiClient.getFundamentalAssetImpact('XAUUSD'),apiClient.getFundamentalAssetImpact('BTCUSD')]); if(live){setXau(a.data);setBtc(b.data);setRefreshFailed(false);} } catch { if(live) setRefreshFailed(true); } }; void load(); const id=window.setInterval(load,15000); return()=>{live=false;window.clearInterval(id);}; },[]);

  const horizons = [
    ['5m', overview.horizons?.m5], ['15m', overview.horizons?.m15], ['60m', overview.horizons?.h1], ['4h', overview.horizons?.h4],
  ].filter(([, v]) => Boolean(v)).map(([h, v]) => { const x = v as { bullish?: number; bearish?: number; neutral?: number }; return { horizon: h, bullish: x.bullish ?? 0, bearish: x.bearish ?? 0, neutral: x.neutral ?? 0 }; });

  const domains = (overview.domains ?? []).filter((d) => d.domain_state !== 'UNAVAILABLE').map((d) => ({ domain: d.domain_ar ?? d.domain, impact: d.gold_impact_score, confidence: d.confidence, coverage: d.coverage_score }));
  const impactChart = useMemo(()=>['5m','15m','60m','4h'].map((h)=>({
    horizon:h,
    XAUUSD:xau?.impacts?.find((x)=>x.horizon===h)?.impact_score ?? null,
    BTCUSD:btc?.impacts?.find((x)=>x.horizon===h)?.impact_score ?? null,
  })).filter((x)=>x.XAUUSD!=null||x.BTCUSD!=null),[xau,btc]);

  return <div className="grid gap-3 xl:grid-cols-2">
    {refreshFailed&&<p role="status" className="border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 xl:col-span-2">تعذر تحديث أثر الأصل؛ الرسوم تعرض آخر لقطة ناجحة إن وُجدت.</p>}
    <section className="border border-sky-200 bg-white p-3"><h3 className="mb-2 text-xs font-semibold text-sky-950">احتمالات اتجاه الذهب حسب الأفق</h3>{horizons.length === 0 ? <div className="flex h-52 items-center justify-center text-xs text-slate-600">UNAVAILABLE — لا توجد احتمالات أفق حقيقية حاليًا.</div> : <ResponsiveContainer width="100%" height={210}><BarChart data={horizons}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="horizon" fontSize={10} /><YAxis domain={[0, 100]} fontSize={10} /><Tooltip /><Legend wrapperStyle={{fontSize:10}} /><Bar dataKey="bullish" name="صاعد" fill="#059669" /><Bar dataKey="bearish" name="هابط" fill="#dc2626" /><Bar dataKey="neutral" name="محايد" fill="#0284c7" /></BarChart></ResponsiveContainer>}</section>
    <section className="border border-sky-200 bg-white p-3"><h3 className="mb-2 text-xs font-semibold text-sky-950">مساهمة المحاور وجودة التغطية</h3>{domains.length === 0 ? <div className="flex h-52 items-center justify-center text-xs text-slate-600">UNAVAILABLE — لا توجد درجات محاور قابلة للرسم.</div> : <ResponsiveContainer width="100%" height={210}><BarChart data={domains}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="domain" fontSize={9} interval={0} /><YAxis domain={[-100, 100]} fontSize={10} /><Tooltip /><Legend wrapperStyle={{fontSize:10}} /><Bar dataKey="impact" name="أثر الذهب" fill="#0369a1" /><Bar dataKey="confidence" name="الثقة" fill="#0f766e" /><Bar dataKey="coverage" name="التغطية" fill="#7c3aed" /></BarChart></ResponsiveContainer>}</section>
    <section className="border border-sky-200 bg-white p-3 xl:col-span-2"><h3 className="mb-2 text-xs font-semibold text-sky-950">أثر الأصل الحقيقي من Backend — XAUUSD مقابل BTCUSD</h3>{impactChart.length===0?<div className="flex h-52 items-center justify-center text-xs text-slate-600">UNAVAILABLE — لا توجد Asset Impact rows حقيقية.</div>:<ResponsiveContainer width="100%" height={220}><BarChart data={impactChart}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="horizon" fontSize={10}/><YAxis domain={[-100,100]} fontSize={10}/><Tooltip/><Legend wrapperStyle={{fontSize:10}}/><Bar dataKey="XAUUSD" name="XAUUSD" fill="#0369a1"/><Bar dataKey="BTCUSD" name="BTCUSD" fill="#7c3aed"/></BarChart></ResponsiveContainer>}<p className="mt-1 text-[9px] text-slate-500">الرسم يقرأ `/api/fundamental/assets/*/latest` فقط؛ لا توجد قيم Demo أو fallback مرئي.</p></section>
  </div>;
}
