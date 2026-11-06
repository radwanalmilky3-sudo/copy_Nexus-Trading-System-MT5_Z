'use client';
import {useEffect,useState} from 'react';
import {getAuthHeaders} from '@/lib/api-client';

interface TrainingRun {run_id:string;symbol:string;timeframe:string;generation:string|null;decision:'promoted'|'rejected'|'failed';reason:string|null;fold_count:number;metrics:Record<string,unknown>;data_window:string|null;dataset_id:string|null;label_target_id:string|null;recorded_at:string}
const utc=(v:string)=>v?new Date(v).toISOString().replace('T',' ').replace(/\..+$/,' UTC'):'—';

export function TrainingRunsTable(){
 const [runs,setRuns]=useState<TrainingRun[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[poll,setPoll]=useState(0);
 useEffect(()=>{const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);setLoading(true);setError('');
  void fetch((process.env.NEXT_PUBLIC_API_URL||'')+'/api/ml/training-runs?limit=100',{headers:getAuthHeaders(),signal:controller.signal,cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error();const rows=await r.json();if(!controller.signal.aborted)setRuns(Array.isArray(rows)?rows:[]);}).catch(()=>{if(!controller.signal.aborted)setError('تعذر تحميل سجل التدريب.');}).finally(()=>{clearTimeout(timeout);if(!controller.signal.aborted)setLoading(false);});
  return()=>{clearTimeout(timeout);controller.abort();};},[poll]);
 return <section className="space-y-2 rounded-lg border border-border-primary p-4" aria-label="سجل دورات تدريب ML">
  <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">سجل دورات التدريب — <span className="text-neon-cyan">ml.training_runs</span></h3><button type="button" className="rounded border border-border-primary px-2 py-1 text-xs" onClick={()=>setPoll(n=>n+1)}>تحديث</button></div>
  <p className="text-xs text-text-muted">كل محاولة تدريب تُسجَّل هنا فور انتهائها (ناجحة الترقية أم مرفوضة) مع سبب الرفض ومقاييس الطيات ونافذة البيانات — من سجلات الخادم المحفوظة فقط.</p>
  {loading&&<p role="status" className="text-xs">جارٍ التحميل…</p>}{error&&<p role="alert" className="text-xs text-neon-gold">{error}</p>}
  <div className="overflow-x-auto"><table className="w-full text-right text-xs [&_th]:bg-bg-secondary [&_th]:p-2 [&_td]:p-2 [&_tr]:border-b [&_tr]:border-border-primary" aria-label="جدول دورات التدريب"><thead><tr><th>الوقت UTC</th><th>الرمز / الإطار</th><th>الجيل</th><th>القرار</th><th>السبب</th><th>الطيات</th><th>نافذة البيانات</th></tr></thead><tbody>
   {runs.map(r=><tr key={r.run_id}><td dir="ltr">{utc(r.recorded_at)}</td><td dir="ltr" className="font-mono">{r.symbol} / {r.timeframe}</td><td dir="ltr" className="font-mono text-[10px]">{r.generation||'—'}</td><td>{r.decision==='promoted'?'✅ تمت الترقية':'⚠️ مرفوضة'}</td><td className="max-w-48 truncate" title={r.reason||''}>{r.reason||'—'}</td><td>{r.fold_count}</td><td dir="ltr" className="text-[10px]">{r.data_window||'—'}</td></tr>)}
   {!runs.length&&!loading&&!error&&<tr><td colSpan={7} className="text-center text-text-muted">لا دورات مسجلة بعد — تُسجَّل تلقائياً بعد كل دورة تدريب في الخلفية.</td></tr>}
  </tbody></table></div>
 </section>;
}
