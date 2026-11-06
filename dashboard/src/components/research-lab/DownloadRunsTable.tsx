'use client';
import {useEffect,useState} from 'react';
import {getAuthHeaders} from '@/lib/api-client';
interface Run {run_id:string;group_id:string;symbol:string;timeframe:string;mode:string;requested_start?:string;requested_end?:string;started_at:string;finished_at:string|null;status:string;added?:number;existing?:number;received?:number;fetch_rejected?:number;last?:number;error?:string;quality?:{unclassified_gaps:number;fingerprint:string}}
interface AlignmentRow {symbol:string;timeframe?:string;first?:string;last?:string;last_offset_vs_base_seconds?:number;aligned?:boolean;is_base?:boolean;coverage_pct?:number}
interface BatchCertificate {group_id:string;issued_at:string;status:'valid'|'warning'|'invalid';checks:Record<string,boolean>;checks_passed:number;checks_total:number;totals:Record<string,number>;alignment:AlignmentRow[];misaligned_symbols:string[];low_coverage_symbols:string[];note:string}
const utc=(value:string|null|undefined)=>value?new Date(value).toISOString().replace('T',' ').replace('.000Z',' UTC'):'—';
const modeLabel:Record<string,string>={history:'تنزيل تاريخي',live:'تحديث مباشر',unified:'دمج'};
const checkLabel:Record<string,string>={all_runs_completed:'كل العمليات اكتملت',no_fetch_rejected:'صفر شموع مرفوضة من MT5',no_unclassified_gaps:'صفر فواصل غير مصنفة',pack_aligned:'الحزمة متحاذية زمنياً',coverage_complete:'التغطية ≥ 95% للفترة المطلوبة'};
const certStyle:Record<string,string>={valid:'border-neon-green/50 bg-neon-green/5 text-neon-green',warning:'border-neon-gold/50 bg-neon-gold/5 text-neon-gold',invalid:'border-neon-red/50 bg-neon-red/5 text-neon-red'};
const certLabel:Record<string,string>={valid:'شهادة صالحة',warning:'شهادة بتحفظات',invalid:'شهادة غير صالحة'};
const offsetLabel=(s?:number)=>s===undefined?'—':s===0?'(الأساس)':(s>0?'+':'')+Math.round(s/60)+' دقيقة';
export function DownloadRunsTable({account,symbol,refresh}:{account:string;symbol:string;refresh:number}){
 const [allRuns,setRuns]=useState<Run[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(false),[poll,setPoll]=useState(0),[frame,setFrame]=useState('all');
 const [certGroup,setCertGroup]=useState(''),[cert,setCert]=useState<BatchCertificate|null>(null),[certLoading,setCertLoading]=useState(false),[certError,setCertError]=useState('');
 const assetRuns=allRuns.filter(r=>r.symbol===symbol);
 const runs=assetRuns.filter(r=>frame==='all'||r.timeframe===frame);
 const groups=[...new Set(allRuns.map(r=>r.group_id))].slice(0,20);
 useEffect(()=>{if(!runs.some(r=>r.status==='running'&&Date.now()-Date.parse(r.started_at)<120000))return;const timer=setTimeout(()=>setPoll(n=>n+1),5000);return()=>clearTimeout(timer);},[runs]);
 useEffect(()=>{setRuns([]);setCert(null);setCertGroup('');},[account]);
 useEffect(()=>{if(!account)return;const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);setLoading(true);setError('');
 void fetch((process.env.NEXT_PUBLIC_API_URL||'')+'/api/brokers/accounts/'+encodeURIComponent(account)+'/research-runs',{headers:getAuthHeaders(),signal:controller.signal,cache:'no-store'}).then(async r=>{if(!r.ok)throw new Error();const rows=await r.json();if(!controller.signal.aborted){setRuns(rows);setCertGroup(g=>g||rows[0]?.group_id||'');}}).catch(()=>{if(!controller.signal.aborted)setError('تعذر تحميل سجل العمليات.');}).finally(()=>{clearTimeout(timeout);if(!controller.signal.aborted)setLoading(false);});
 return()=>{clearTimeout(timeout);controller.abort();};},[account,refresh,poll]);
 const loadCertificate=(gid:string)=>{if(!account||!gid)return;setCertLoading(true);setCertError('');setCert(null);
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
  void fetch((process.env.NEXT_PUBLIC_API_URL||'')+'/api/brokers/accounts/'+encodeURIComponent(account)+'/research-certificate?group_id='+encodeURIComponent(gid),{headers:getAuthHeaders(),signal:controller.signal,cache:'no-store'}).then(async r=>{const body=await r.json().catch(()=>null);if(!r.ok)throw new Error(body?.detail||'');if(!controller.signal.aborted)setCert(body);}).catch(e=>{if(!controller.signal.aborted)setCertError(e instanceof Error&&e.message?String(e.message):'تعذر استخراج شهادة الدفعة.');}).finally(()=>{clearTimeout(timeout);if(!controller.signal.aborted)setCertLoading(false);});};
 const latest=new Map<string,Run>();for(const r of runs){const key=r.symbol+'/'+r.timeframe;if(r.status==='completed'&&r.mode!=='live'&&!latest.has(key))latest.set(key,r);}
 return <section className="space-y-3 border-t border-border-primary pt-4" aria-label="سجل تنزيل وتحديث البيانات">
 <div className="flex items-center justify-between"><h3 className="font-semibold">سجل عمليات <bdi className="text-neon-cyan">{symbol||'الأصل المختار'}</bdi></h3><button type="button" className="rounded border border-border-primary px-3 py-1 text-xs" onClick={()=>setPoll(n=>n+1)}>تحديث السجل</button></div><p className="text-xs text-text-muted">عمليات الأصل ضمن آخر 200 عملية للحساب · أوقات التشغيل UTC · أوقات الشموع كما وردت من MT5. اكتمال العملية لا يعني اكتمال تغطية الفترة.</p>
 {groups.length>0&&<div className="space-y-2 rounded-lg border border-neon-cyan/30 p-3" aria-label="شهادة جودة الدفعة">
  <div className="flex flex-wrap items-center gap-2">
   <h4 className="text-sm font-semibold text-neon-cyan">شهادة جودة الدفعة — مستنتجة من السجلات المحفوظة فقط</h4>
   <select aria-label="اختر المجموعة" className="rounded border border-border-primary bg-bg-primary px-2 py-1 text-xs" value={certGroup} onChange={e=>setCertGroup(e.target.value)}>
    {groups.map(g=><option key={g} value={g}>{g.slice(0,13)}…</option>)}
   </select>
   <button type="button" className="rounded border border-neon-cyan px-3 py-1 text-xs font-semibold text-neon-cyan disabled:opacity-40" disabled={!certGroup||certLoading} onClick={()=>loadCertificate(certGroup)}>{certLoading?'جارٍ الاستخراج…':'استخراج الشهادة'}</button>
  </div>
  {certError&&<p role="alert" className="text-xs text-neon-gold">{certError}</p>}
  {cert&&<div className="space-y-2 text-xs">
   <div className={`rounded border p-2 font-semibold ${certStyle[cert.status]||''}`}>{certLabel[cert.status]||cert.status} · اجتاز {cert.checks_passed}/{cert.checks_total} فحصاً · صدرت {utc(cert.issued_at)}</div>
   <ul className="grid gap-1 sm:grid-cols-2">{Object.entries(cert.checks).map(([k,v])=><li key={k}>{v?'✅':'⚠️'} {checkLabel[k]||k}</li>)}</ul>
   <p className="text-text-muted">الإجماليات: {cert.totals.runs} عملية · {cert.totals.bars} شمعة · {cert.totals.fetch_rejected} مرفوضة · {cert.totals.unclassified_gaps} فاصل غير مصنف</p>
   <div className="overflow-x-auto"><table className="w-full text-right text-xs [&_th]:bg-bg-secondary [&_th]:p-2 [&_td]:p-2 [&_tr]:border-b [&_tr]:border-border-primary" aria-label="محاذاة الحزمة الزمنية"><thead><tr><th>الرمز</th><th>الإطار</th><th>أول شمعة</th><th>آخر شمعة</th><th>الفرق عن الأساس</th><th>التغطية</th><th>المحاذاة</th></tr></thead><tbody>{cert.alignment.map(a=><tr key={a.symbol}><td dir="ltr" className="font-mono">{a.symbol}{a.is_base?' ★':''}</td><td>{a.timeframe||'—'}</td><td dir="ltr">{a.first?.slice(0,16)||'—'}</td><td dir="ltr">{a.last?.slice(0,16)||'—'}</td><td>{offsetLabel(a.last_offset_vs_base_seconds)}</td><td>{a.coverage_pct!==undefined?a.coverage_pct+'%':'—'}</td><td>{a.aligned?'✅':'⚠️'}</td></tr>)}</tbody></table></div>
   {(cert.misaligned_symbols.length>0||cert.low_coverage_symbols.length>0)&&<p className="text-neon-gold">تحفظات: {cert.misaligned_symbols.length?'رموز غير متحاذية ('+cert.misaligned_symbols.join('، ')+'). ':''}{cert.low_coverage_symbols.length?'تغطية أقل من 95% ('+cert.low_coverage_symbols.join('، ')+').':''}</p>}
   <p className="text-text-muted">{cert.note}</p>
  </div>}
 </div>}
 <nav className="flex gap-2 overflow-x-auto rounded-lg bg-bg-secondary/40 p-2" aria-label="تبويبات أطر سجل العمليات">{['all','M1','M5','M15','M30','H1','H4','D1'].map(value=><button key={value} type="button" aria-pressed={frame===value} onClick={()=>setFrame(value)} className={`flex shrink-0 items-center gap-2 rounded px-3 py-2 text-xs ${frame===value?'bg-neon-cyan/15 font-semibold text-neon-cyan':'text-text-muted'}`}>{value==='all'?'كل الأطر':value}<span className="rounded bg-bg-primary px-1.5 py-0.5">{value==='all'?assetRuns.length:assetRuns.filter(r=>r.timeframe===value).length}</span></button>)}</nav>
 {latest.size>0&&<div className="flex flex-wrap gap-2">{Array.from(latest.values()).map(r=><div key={r.symbol+r.timeframe} className="rounded border border-border-primary p-3 text-xs"><b dir="ltr">{r.symbol} / {r.timeframe}</b><p>آخر تحديث محفوظ ناجح: {utc(r.finished_at)}</p><p>آخر شمعة: {r.last?new Date(r.last*1000).toISOString().replace('T',' ').replace('.000Z',' (MT5)'):'—'}</p></div>)}</div>}
 {loading&&<p role="status" className="text-xs">جارٍ تحميل السجل…</p>}{error&&<p role="alert" className="text-sm text-neon-gold">{error}</p>}
 <div className="overflow-x-auto rounded border border-border-primary"><table className="w-full text-right text-xs [&_th]:p-3 [&_td]:p-3 [&_tr]:border-b [&_tr]:border-border-primary" aria-label="عمليات تنزيل البيانات"><thead><tr>{['الأصل / الإطار','العملية والفترة','البداية / النهاية UTC','النتيجة','الحالة والجودة','التفاصيل'].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{runs.map(r=><tr key={r.run_id}><td><b dir="ltr">{r.symbol} / {r.timeframe}</b></td><td>{modeLabel[r.mode]||r.mode}<p>{r.requested_start?.slice(0,10)||'آخر الشموع'}{r.requested_end?' ← '+r.requested_end.slice(0,10):''}</p></td><td><p>{utc(r.started_at)}</p><p>{utc(r.finished_at)}</p></td><td>{r.mode==='live'?`${r.received??0} مقروءة`:<><p>{r.added??0} جديدة</p><p>{r.existing??0} موجودة سابقًا</p></>}<p>{r.fetch_rejected??0} مرفوضة</p></td><td>{r.status==='completed'?'اكتملت العملية':r.status==='partial'?'جزئية':r.status==='failed'?'فشلت':Date.now()-Date.parse(r.started_at)>120000?'غير مكتملة — تحتاج تحققًا':'قيد التنفيذ'}<p className="text-text-muted">{r.quality?`${r.quality.unclassified_gaps} فاصل غير مصنف`:'—'}</p></td><td><details><summary className="cursor-pointer">عرض</summary><div className="max-w-xs break-all"><p>مجموعة: {r.group_id}</p><p>{r.error}</p><p>آخر شمعة: {r.last?new Date(r.last*1000).toISOString().replace('Z',' (MT5)'):'—'}</p><p>بصمة: {r.quality?.fingerprint||'—'}</p></div></details></td></tr>)}{!runs.length&&!loading&&!error&&<tr><td colSpan={6} className="text-center">لا توجد عمليات مسجلة بعد؛ العمليات السابقة لإنشاء السجل لا تظهر هنا.</td></tr>}</tbody></table></div>
 </section>;
}
