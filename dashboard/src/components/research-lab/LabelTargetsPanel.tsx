'use client';
import {useEffect,useState} from 'react';
import {getAuthHeaders} from '@/lib/api-client';

interface LabelTarget {target_id:string;symbol:string;timeframe:string;kind:string;horizon_bars:number;name:string;generated_at:string;labeled:number;status:string}
const kindLabel:Record<string,string>={direction:'الاتجاه بعد N شموع',barrier:'أي حاجز يُضرب أولاً (ATR)'};
const utc=(v:string)=>v?new Date(v).toISOString().replace('T',' ').replace(/\..+$/,' UTC'):'—';

export function LabelTargetsPanel({account,symbol,timeframe}:{account:string;symbol:string;timeframe:string}){
 const [targets,setTargets]=useState<LabelTarget[]>([]),[loading,setLoading]=useState(false),[error,setError]=useState('');
 const [kind,setKind]=useState<'direction'|'barrier'>('direction'),[horizon,setHorizon]=useState(5),[name,setName]=useState('');
 const [tpAtr,setTpAtr]=useState(1.5),[slAtr,setSlAtr]=useState(1.0);
 const [busy,setBusy]=useState(false),[result,setResult]=useState<Record<string,unknown>|null>(null),[genError,setGenError]=useState('');
 const load=()=>{if(!account)return;setLoading(true);setError('');
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
  void fetch((process.env.NEXT_PUBLIC_API_URL||'')+'/api/brokers/accounts/'+encodeURIComponent(account)+'/research-labels',{headers:getAuthHeaders(),signal:controller.signal,cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error();const rows=await r.json();if(!controller.signal.aborted)setTargets(Array.isArray(rows)?rows:[]);}).catch(()=>{if(!controller.signal.aborted)setError('تعذر تحميل التسميات المحفوظة.');}).finally(()=>{clearTimeout(timeout);if(!controller.signal.aborted)setLoading(false);});};
 useEffect(()=>{setTargets([]);setResult(null);},[account]);
 useEffect(()=>{load();},[account]);
 const generate=()=>{if(!account||!symbol||!name.trim())return;setBusy(true);setGenError('');setResult(null);
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),30000);
  void fetch((process.env.NEXT_PUBLIC_API_URL||'')+'/api/brokers/accounts/'+encodeURIComponent(account)+'/research-labels',{method:'POST',headers:{...getAuthHeaders(),'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({symbol,timeframe,kind,horizon_bars:horizon,name:name.trim(),tp_atr:tpAtr,sl_atr:slAtr})}).then(async r=>{const body=await r.json().catch(()=>null);if(!r.ok)throw new Error(body?.detail||'');if(!controller.signal.aborted){setResult(body);load();}}).catch(e=>{if(!controller.signal.aborted)setGenError(typeof e?.message==='string'&&e.message?e.message:'تعذر توليد التسميات.');}).finally(()=>{clearTimeout(timeout);if(!controller.signal.aborted)setBusy(false);});};
 const field='rounded border border-border-primary bg-bg-primary px-2 py-1 text-xs';
 return <section className="space-y-3 border-t border-border-primary pt-4" aria-label="مولد التسميات للتدريب">
  <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">مولّد التسميات — <span className="text-neon-cyan">ml.prediction_targets</span></h3><button type="button" className="rounded border border-border-primary px-3 py-1 text-xs" onClick={load}>تحديث القائمة</button></div>
  <p className="text-xs text-text-muted">تسميات مشتقة من الشموع المخزنة فقط (لا بيانات مولّدة): «الاتجاه» يصنف close بعد N شموع، و«الحاجز» يحدد أي ضرب أولى SL أم TP بمضاعفات ATR(14). آخر N شموع تبقى بلا تسمية بحكم التعريف.</p>
  <div className="flex flex-wrap items-end gap-2">
   <label className="text-xs">النوع<select aria-label="نوع التسمية" className={field} value={kind} onChange={e=>setKind(e.target.value as 'direction'|'barrier')}><option value="direction">الاتجاه بعد N شموع</option><option value="barrier">أي حاجز يُضرب أولاً (ATR)</option></select></label>
   <label className="text-xs">الأفق N<select aria-label="الأفق بالشموع" className={field} value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>{[1,3,5,10,15,30,60].map(h=><option key={h} value={h}>{h}</option>)}</select></label>
   {kind==='barrier'&&<label className="text-xs">TP × ATR<input aria-label="مضاعف TP" type="number" step="0.1" min="0.1" className={`${field} w-20`} value={tpAtr} onChange={e=>setTpAtr(Number(e.target.value))}/></label>}
   {kind==='barrier'&&<label className="text-xs">SL × ATR<input aria-label="مضاعف SL" type="number" step="0.1" min="0.1" className={`${field} w-20`} value={slAtr} onChange={e=>setSlAtr(Number(e.target.value))}/></label>}
   <label className="flex-1 text-xs">اسم الهدف<input aria-label="اسم هدف التسمية" placeholder="مثال: اتجاه الذهب بعد 5 شموع M1" className={`${field} w-full`} maxLength={128} value={name} onChange={e=>setName(e.target.value)}/></label>
   <button type="button" className="rounded border border-neon-gold px-3 py-1 text-xs font-semibold text-neon-gold disabled:opacity-40" disabled={busy||!symbol||!name.trim()} onClick={generate}>{busy?'جارٍ التوليد…':`توليد لـ ${symbol||'—'} / ${timeframe}`}</button>
  </div>
  {genError&&<p role="alert" className="text-xs text-neon-gold">{genError}</p>}
  {result&&<p role="status" className="text-xs text-neon-green">وُلّد الهدف: <bdi dir="ltr">{String(result.target_id)}</bdi> · مُسمّى {String(result.labeled)} من {String(result.bars_total)} شمعة · {kind==='direction'?`صعود ${result.positives} / هبوط ${result.negatives} / محايد ${result.flat}`:`TP أولاً ${result.tp_first} / SL أولاً ${result.sl_first} / انتهاء ${result.timeout} (ATR=${result.atr_at_generation})`}</p>}
  {loading&&<p role="status" className="text-xs">جارٍ التحميل…</p>}{error&&<p role="alert" className="text-xs text-neon-gold">{error}</p>}
  <div className="overflow-x-auto rounded border border-border-primary"><table className="w-full text-right text-xs [&_th]:bg-bg-secondary [&_th]:p-2 [&_td]:p-2 [&_tr]:border-b [&_tr]:border-border-primary" aria-label="أهداف التسميات المحفوظة"><thead><tr><th>الاسم</th><th>الرمز / الإطار</th><th>النوع والأفق</th><th>مُسمّى</th><th>الحالة</th><th>وُلّد UTC</th></tr></thead><tbody>
   {targets.map(t=><tr key={t.target_id}><td>{t.name}</td><td dir="ltr" className="font-mono">{t.symbol} / {t.timeframe}</td><td>{kindLabel[t.kind]||t.kind} · N={t.horizon_bars}</td><td>{t.labeled}</td><td>{t.status==='ok'?'✅ جاهز':t.status}</td><td dir="ltr">{utc(t.generated_at)}</td></tr>)}
   {!targets.length&&!loading&&!error&&<tr><td colSpan={6} className="text-center text-text-muted">لا توجد أهداف تسمية بعد — ولّد أول هدف من الأعلى.</td></tr>}
  </tbody></table></div>
 </section>;
}
