'use client'
import { useEffect, useState, useCallback } from 'react'
import { getAuthHeaders } from '@/lib/api-client'

interface HurstData {
  H: number
  regime: string
  tradeable: boolean
  preferred_model: string
  conviction_adjustment: number
  hurst_confidence: number
}

interface InstFeatures {
  hurst: HurstData
  perm_entropy: { permutation_entropy: number; structured: boolean; conviction_adjustment: number; edge_quality: number }
  lyapunov: { horizon_bars: number; lyapunov_exponent: number | null; horizon_minutes_m5: number; reliable: boolean }
  matrix_profile: { novelty: number; novel_pattern: boolean; ml_ensemble_weight: number; position_size_mult: number }
  change_points: { recent_shift: boolean; bars_since: number; ensemble_weight: number; disable_lstm: boolean; disable_hmm: boolean }
  tick_imbalance: { tick_imbalance: number; directional_bias: string; strength: number }
  rv_ratio: { rv_fast: number; rv_slow: number; rv_ratio: number; regime: string }
  ergodic_kelly: { available?: boolean; lot: number; kelly_classic: number | null; kelly_ergodic: number | null; kelly_final: number | null; variance_penalty: number | null }
  temporal_growth: { temporal_growth_g: number | null; arithmetic_mean: number | null; variance_tax: number | null; viable: boolean | null; action: string }
  operability_score: number
  recommendation: 'TRADE_FULL' | 'TRADE_REDUCED' | 'WAIT'
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000'
const SYMBOL = process.env.NEXT_PUBLIC_DEFAULT_SYMBOL || 'XAUUSD'

const REC_CONFIG = {
  TRADE_FULL:    { label: 'تداول كامل',  color: '#22c55e', bg: 'rgba(34,197,94,0.08)' },
  TRADE_REDUCED: { label: 'تداول مخفّض',  color: '#f59e0b', bg: 'rgba(245,158,11,0.08)' },
  WAIT:          { label: 'انتظار',             color: '#ef4444', bg: 'rgba(239,68,68,0.08)' },
}

const HURST_COLORS: Record<string, string> = {
  TRENDING: '#22c55e',
  MEAN_REVERTING: '#3b82f6',
  NOISY: '#ef4444',
}

function MiniBar({ value, max = 100, color }: { value: number; max?: number; color?: string }) {
  const pct = Math.min(100, (value / max) * 100)
  const c = color ?? (pct > 65 ? '#22c55e' : pct > 40 ? '#f59e0b' : '#ef4444')
  return (
    <div style={{ height: 4, background: '#1f2937', borderRadius: 2, overflow: 'hidden', marginTop: 3 }}>
      <div style={{ height: '100%', width: `${pct}%`, background: c, borderRadius: 2, transition: 'width 0.5s ease' }} />
    </div>
  )
}

function StatRow({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', padding: '3px 0', borderBottom: '1px solid #1f2937' }}>
      <span style={{ fontSize: 11, color: '#6b7280' }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: color ?? '#e5e7eb' }}>{value}</span>
        {sub && <span style={{ fontSize: 10, color: '#6b7280', marginInlineStart: 4 }}>{sub}</span>}
      </div>
    </div>
  )
}

export default function ErgodicIntelligencePanel() {
  const [data, setData] = useState<InstFeatures | null>(null)
  const [lastUpdate, setLastUpdate] = useState<string>('')
  const [status, setStatus] = useState<'loading' | 'ok' | 'calculating' | 'error'>('loading')

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/intelligence/institutional/${SYMBOL}`, { headers: getAuthHeaders() })
      const json = await res.json()
      if (json.data) {
        setData(json.data)
        setLastUpdate(new Date().toLocaleTimeString())
        setStatus('ok')
      } else {
        setStatus(json.status === 'calculating' ? 'calculating' : 'error')
      }
    } catch {
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    fetchData()
    // Also listen on WebSocket for push updates
    let ws: WebSocket | null = null
    try {
      const wsUrl = (process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:9000/ws').replace(/^http/, 'ws')
      ws = new WebSocket(wsUrl)
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type === 'institutional_features' && msg.symbol === SYMBOL) {
            setData(msg.data)
            setLastUpdate(new Date().toLocaleTimeString())
            setStatus('ok')
          }
        } catch { /* ignore non-JSON */ }
      }
    } catch { /* WS not available, fallback to polling */ }

    const interval = setInterval(fetchData, 30_000)
    return () => {
      clearInterval(interval)
      ws?.close()
    }
  }, [fetchData])

  // ── Loading states ──────────────────────────────────────────────────────────
  if (status === 'loading') {
    return (
      <div style={{ padding: 16, color: '#6b7280', fontSize: 12 }}>
        Inicializando الذكاء الإرجعي…
      </div>
    )
  }
  if (status === 'calculating') {
    return (
      <div style={{ padding: 16, color: '#f59e0b', fontSize: 12 }}>
        ⏳ جارٍ حساب السمات المؤسسية (المرة الأولى ~60 ث)
      </div>
    )
  }
  if (status === 'error' || !data) {
    return (
      <div style={{ padding: 16, color: '#ef4444', fontSize: 12 }}>
        ⚠ السمات المؤسسية غير متاحة (nexus_features غير متصل)
      </div>
    )
  }

  // ── Computed values ─────────────────────────────────────────────────────────
  const rec = REC_CONFIG[data.recommendation] ?? REC_CONFIG.WAIT
  const hColor = HURST_COLORS[data.hurst.regime] ?? '#6b7280'
  const g = data.temporal_growth.temporal_growth_g
  const kellyAvailable = data.ergodic_kelly.available !== false
  const kellyPercent = (value: number | null, digits: number) =>
    kellyAvailable && value !== null ? `${(value * 100).toFixed(digits)}%` : 'N/A'
  const pe = data.perm_entropy.permutation_entropy
  const peColor = pe < 0.65 ? '#22c55e' : pe < 0.80 ? '#f59e0b' : '#ef4444'
  const tgColor = (data.temporal_growth.viable === true) ? '#22c55e'
                : (data.temporal_growth.viable === false) ? '#ef4444' : '#6b7280'
  const effectiveThreshold = 70 + (data.perm_entropy.conviction_adjustment ?? 0)
                              + (data.hurst.regime === 'NOISY' ? 15 : 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '0 4px' }}>

      {/* Header: Score + recomendación */}
      <div style={{
        borderRadius: 10, padding: '12px 14px',
        border: `1px solid ${rec.color}25`,
        background: rec.bg,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 1 }}>قابلية تداول السوق (Operability)</div>
          <div style={{ fontSize: 36, fontWeight: 600, color: rec.color, lineHeight: 1.1, marginTop: 2 }}>
            {data.operability_score.toFixed(0)}
            <span style={{ fontSize: 14, color: '#6b7280', fontWeight: 400 }}>/100</span>
          </div>
          <MiniBar value={data.operability_score} color={rec.color} />
        </div>
        <div>
          <div style={{
            fontSize: 12, fontWeight: 500, padding: '6px 12px',
            borderRadius: 6, background: `${rec.color}20`, color: rec.color,
          }}>
            {rec.label}
          </div>
          {lastUpdate && (
            <div style={{ fontSize: 10, color: '#4b5563', marginTop: 4, textAlign: 'end' }}>
              ↻ {lastUpdate}
            </div>
          )}
        </div>
      </div>

      {/* Row: Hurst + Entropía */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div style={{ borderRadius: 8, padding: '10px 12px', background: '#111827', border: '1px solid #1f2937' }}>
          <div style={{ fontSize: 10, color: '#6b7280' }}>أُسّ الهيرست (Hurst Exponent)</div>
          <div style={{ fontSize: 26, fontWeight: 600, color: hColor, margin: '4px 0 2px' }}>
            {data.hurst.H.toFixed(3)}
          </div>
          <div style={{ fontSize: 11, color: hColor }}>
            {data.hurst.regime === 'TRENDING' && '↗ اتجاهي (Trend)'}
            {data.hurst.regime === 'MEAN_REVERTING' && '↔ استرجاع المتوسط (Mean Reversion)'}
            {data.hurst.regime === 'NOISY' && '⚡ ضوضاء — بلا ميزة (edge)'}
          </div>
          <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
            النموذج: <span dir="ltr">{data.hurst.preferred_model}</span>
          </div>
        </div>
        <div style={{ borderRadius: 8, padding: '10px 12px', background: '#111827', border: '1px solid #1f2937' }}>
          <div style={{ fontSize: 10, color: '#6b7280' }}>إنتروبيا التبديل (Permutation Entropy)</div>
          <div style={{ fontSize: 26, fontWeight: 600, color: peColor, margin: '4px 0 2px' }}>
            {pe.toFixed(3)}
          </div>
          <div style={{ fontSize: 11, color: peColor }}>
            {pe < 0.65 ? 'مُهيكل' : pe < 0.80 ? 'معتدل' : 'فوضوي'}
          </div>
          <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
            العتبة الفعّالة: {effectiveThreshold}
          </div>
        </div>
      </div>

      {/* Lyapunov horizon */}
      <div style={{
        borderRadius: 8, padding: '10px 14px', background: '#111827', border: '1px solid #1f2937',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div>
          <div style={{ fontSize: 10, color: '#6b7280' }}>أفق ليبونوف (Lyapunov Horizon)</div>
          <div style={{ fontSize: 11, color: '#4b5563', marginTop: 2 }}>الحد الفيزيائي للتنبؤ</div>
        </div>
        {data.lyapunov.reliable ? (
          <div style={{ textAlign: 'end' }}>
            <div style={{ fontSize: 20, fontWeight: 600, color: '#e5e7eb' }}>
              {data.lyapunov.horizon_bars} bars
            </div>
            <div style={{ fontSize: 11, color: '#6b7280' }}>
              ≈ {data.lyapunov.horizon_minutes_m5} دقيقة في M5
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 11, color: '#4b5563' }}>بيانات غير كافية</div>
        )}
      </div>

      {/* Matrix Profile + Change Points */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div style={{
          borderRadius: 8, padding: '10px 12px', background: '#111827',
          border: `1px solid ${data.matrix_profile.novel_pattern ? '#ef444430' : '#1f2937'}`,
        }}>
          <div style={{ fontSize: 10, color: '#6b7280' }}>جدة النمط (Pattern Novelty)</div>
          <div style={{
            fontSize: 22, fontWeight: 600, marginTop: 4,
            color: data.matrix_profile.novel_pattern ? '#ef4444' : '#22c55e',
          }}>
            {(data.matrix_profile.novelty * 100).toFixed(0)}%
          </div>
          <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
            ML weight: {(data.matrix_profile.ml_ensemble_weight * 100).toFixed(0)}%
          </div>
          <div style={{ fontSize: 10, color: '#4b5563' }}>
            Size mult: ×{data.matrix_profile.position_size_mult.toFixed(2)}
          </div>
        </div>
        <div style={{
          borderRadius: 8, padding: '10px 12px', background: '#111827',
          border: `1px solid ${data.change_points.recent_shift ? '#f59e0b30' : '#1f2937'}`,
        }}>
          <div style={{ fontSize: 10, color: '#6b7280' }}>تغيّر Regime</div>
          <div style={{
            fontSize: 13, fontWeight: 500, marginTop: 4,
            color: data.change_points.recent_shift ? '#f59e0b' : '#22c55e',
          }}>
            {data.change_points.recent_shift
              ? `⚠ منذ ${data.change_points.bars_since} شمعة`
              : '✓ مستقر'}
          </div>
          {data.change_points.disable_lstm && (
            <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 2 }}>LSTM معطّل</div>
          )}
          {data.change_points.disable_hmm && (
            <div style={{ fontSize: 10, color: '#ef4444' }}>HMM معطّل</div>
          )}
          <div style={{ fontSize: 10, color: '#4b5563', marginTop: 2 }}>
            Ensemble: {(data.change_points.ensemble_weight * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Tick imbalance + RV ratio */}
      <div style={{ borderRadius: 8, padding: '10px 14px', background: '#111827', border: '1px solid #1f2937' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>Tick Imbalance</div>
            <StatRow
              label="Bias"
              value={data.tick_imbalance.directional_bias}
              color={
                data.tick_imbalance.directional_bias === 'BUY_PRESSURE' ? '#22c55e'
                : data.tick_imbalance.directional_bias === 'SELL_PRESSURE' ? '#ef4444'
                : '#6b7280'
              }
            />
            <StatRow
              label="القيمة"
              value={data.tick_imbalance.tick_imbalance.toFixed(3)}
            />
          </div>
          <div>
            <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>Vol Ratio (RV)</div>
            <StatRow
              label="Ratio"
              value={data.rv_ratio.rv_ratio.toFixed(2)}
              color={
                data.rv_ratio.regime === 'EXPANDING' ? '#f59e0b'
                : data.rv_ratio.regime === 'COMPRESSING' ? '#3b82f6'
                : '#22c55e'
              }
            />
            <StatRow label="Regime" value={data.rv_ratio.regime} />
          </div>
        </div>
      </div>

      {/* Kelly Ergódico */}
      <div style={{ borderRadius: 8, padding: '10px 14px', background: '#111827', border: '1px solid #1f2937' }}>
        <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 8 }}>
          Kelly Criterion — Ergodicity Economics (Peters 2019)
        </div>
        <div style={{ display: 'flex', gap: 0, justifyContent: 'space-between' }}>
          {[
            { label: 'كلاسيكي', value: kellyPercent(data.ergodic_kelly.kelly_classic, 1), color: '#f59e0b' },
            { label: 'إرجعي (Ergodic)', value: kellyPercent(data.ergodic_kelly.kelly_ergodic, 1), color: '#22c55e' },
            { label: 'جزاء التباين', value: kellyPercent(data.ergodic_kelly.variance_penalty === null ? null : -data.ergodic_kelly.variance_penalty, 2), color: '#ef4444' },
            { label: 'Lot النهائي', value: kellyAvailable ? data.ergodic_kelly.lot.toFixed(2) : 'N/A', color: '#e5e7eb' },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#6b7280' }}>{label}</div>
              <div style={{ fontSize: 18, fontWeight: 600, color, marginTop: 2 }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Tasa de crecimiento temporal g */}
      <div style={{
        borderRadius: 8, padding: '12px 14px',
        background: data.temporal_growth.viable === true ? 'rgba(34,197,94,0.05)'
                  : data.temporal_growth.viable === false ? 'rgba(239,68,68,0.05)' : '#111827',
        border: `1px solid ${tgColor}30`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontSize: 10, color: '#6b7280' }}>معدل النمو الزمني g (Temporal Growth)</div>
            <div style={{ fontSize: 10, color: '#4b5563', marginTop: 1 }}>Peters (2019) — log(W_T/W_0)/T</div>
          </div>
          <div style={{ textAlign: 'end' }}>
            <div style={{ fontSize: 28, fontWeight: 600, color: tgColor }}>
              {g !== null ? `${(g * 100).toFixed(3)}%` : 'N/A'}
            </div>
            <div style={{ fontSize: 11, color: tgColor }}>
              {data.temporal_growth.viable === true && '✓ رأس المال ينمو'}
              {data.temporal_growth.viable === false && '⚠ تدمير رأس المال'}
              {data.temporal_growth.viable === null && 'بيانات غير كافية'}
            </div>
          </div>
        </div>
        {data.temporal_growth.action && data.temporal_growth.action !== 'NORMAL' && (
          <div style={{
            marginTop: 8, padding: '4px 8px', borderRadius: 4,
            background: data.temporal_growth.action === 'PAUSE_SYSTEM' ? 'rgba(239,68,68,0.15)'
                      : 'rgba(245,158,11,0.15)',
            fontSize: 11, fontWeight: 500,
            color: data.temporal_growth.action === 'PAUSE_SYSTEM' ? '#ef4444' : '#f59e0b',
          }}>
            {data.temporal_growth.action === 'PAUSE_SYSTEM' && '🛑 النظام متوقف — g سالب بشدة'}
            {data.temporal_growth.action === 'REDUCE_SIZE_50PCT' && '⬇ الحجم مخفّض 50% لأن g < 0'}
            {data.temporal_growth.action === 'CAUTION' && '⚡ حذر — g موجب منخفض'}
          </div>
        )}
        {data.temporal_growth.arithmetic_mean !== null && (
          <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid #1f2937', fontSize: 10, color: '#4b5563', display: 'flex', gap: 12 }}>
            <span>العائد الحسابي: {((data.temporal_growth.arithmetic_mean ?? 0) * 100).toFixed(3)}%</span>
            <span>Variance tax: {((data.temporal_growth.variance_tax ?? 0) * 100).toFixed(3)}%</span>
          </div>
        )}
      </div>

    </div>
  )
}
