'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, GitCompareArrows } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { apiClient } from '@/lib/api-client';
import type { AssetImpactSnapshotDTO } from '@/types/fundamental';

const HORIZONS = ['5m', '15m', '60m', '4h'] as const;

function arDirection(v?: string) {
  return v === 'bullish' ? 'صاعد' : v === 'bearish' ? 'هابط' : v === 'conflicted' ? 'متعارض' : v === 'neutral' ? 'محايد' : 'غير محدد';
}

function score(v: unknown) {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(1) : '—';
}

export default function MultiAssetImpactPanel() {
  const [xau, setXau] = useState<AssetImpactSnapshotDTO | null>(null);
  const [btc, setBtc] = useState<AssetImpactSnapshotDTO | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [a, b] = await Promise.all([
          apiClient.getFundamentalAssetImpact('XAUUSD'),
          apiClient.getFundamentalAssetImpact('BTCUSD'),
        ]);
        if (!cancelled) { setXau(a.data); setBtc(b.data); setError(''); }
      } catch {
        if (!cancelled) setError('تعذر تحميل مقارنة أثر الحدث على الأصول. لا يتم إنشاء قيم بديلة.');
      }
    };
    load();
    const id = window.setInterval(load, 30_000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const chartData = useMemo(() => HORIZONS.map((h) => {
    const a = xau?.impacts?.find((x) => x.horizon === h);
    const b = btc?.impacts?.find((x) => x.horizon === h);
    return { horizon: h, XAUUSD: a?.impact_score ?? null, BTCUSD: b?.impact_score ?? null };
  }), [xau, btc]);

  const hasData = chartData.some((x) => typeof x.XAUUSD === 'number' || typeof x.BTCUSD === 'number');

  return (
    <section className="border border-sky-200 bg-white">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-100 bg-sky-50 px-4 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-sky-950"><GitCompareArrows className="h-4 w-4" /> الأثر الأساسي حسب الأصل</div>
        <span className="text-[10px] text-slate-500">نفس الحدث لا يملك اتجاهًا عالميًا واحدًا</span>
      </header>
      {error && <div className="border-b border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">{error}</div>}
      <div className="grid gap-3 p-3 xl:grid-cols-[1fr_1.4fr]">
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-1">
          {[xau, btc].map((snap, idx) => {
            const asset = idx === 0 ? 'XAUUSD' : 'BTCUSD';
            const row = snap?.impacts?.find((x) => x.horizon === '15m') ?? snap?.impacts?.[0];
            return <div key={asset} className="border border-sky-100 bg-sky-50 p-3">
              <div className="flex items-center justify-between"><b className="font-mono text-sm text-sky-950">{asset}</b><span className="text-[10px] text-slate-500">{snap?.state ?? 'unavailable'}</span></div>
              {!row ? <div className="mt-2 text-xs text-slate-600">UNAVAILABLE — لا توجد نتيجة أثر حتمية لهذا الأصل حاليًا.</div> : <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-slate-500">الاتجاه</span><div className="font-semibold">{arDirection(row.direction)}</div></div>
                <div><span className="text-slate-500">الأثر</span><div className="font-mono font-semibold">{score(row.impact_score)}</div></div>
                <div><span className="text-slate-500">الملاءمة</span><div className="font-mono">{score(row.relevance_score)}%</div></div>
                <div><span className="text-slate-500">الثقة</span><div className="font-mono">{score(row.confidence)}%</div></div>
              </div>}
            </div>;
          })}
        </div>
        <div className="min-h-[230px] border border-sky-100 p-2">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-sky-900"><BarChart3 className="h-3.5 w-3.5" /> أثر حقيقي مسجل حسب الأفق</div>
          {!hasData ? <div className="flex h-[190px] items-center justify-center text-xs text-slate-600">UNAVAILABLE — لا تُرسم بيانات وهمية.</div> : <ResponsiveContainer width="100%" height={195}>
            <BarChart data={chartData} margin={{ top: 5, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="horizon" fontSize={10} />
              <YAxis domain={[-100, 100]} fontSize={10} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="XAUUSD" fill="#0284c7" />
              <Bar dataKey="BTCUSD" fill="#0f766e" />
            </BarChart>
          </ResponsiveContainer>}
        </div>
      </div>
    </section>
  );
}
