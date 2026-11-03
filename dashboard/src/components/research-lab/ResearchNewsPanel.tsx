'use client';
import {useState} from 'react';
import {useResearchScope} from './ResearchScope';
import type {NewsRow,ResearchViewState} from './types';
export function ResearchNewsPanel({rows,state}:{rows:readonly NewsRow[];state:ResearchViewState}){
 const {symbol,start,end}=useResearchScope();const [all,setAll]=useState(false);
 const aliases=[symbol,symbol.endsWith('s')?symbol.slice(0,-1):symbol].map(s=>s.toUpperCase());
 const selected=rows.filter(r=>{const tags=r.relevance.split(',').map(s=>s.trim().toUpperCase());const timestamp=Date.parse(r.publishedAt);return (all||aliases.some(s=>s&&tags.includes(s)))&&Number.isFinite(timestamp)&&timestamp>=Date.parse(start+'T00:00:00Z')&&timestamp<=Date.parse(end+'T23:59:59Z');});
 return <section className="space-y-3 rounded-xl border border-border-primary p-4"><div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">الأخبار المرتبطة بالأصل والفترة</h3><label className="flex gap-2 text-xs"><input type="checkbox" checked={all} onChange={e=>setAll(e.target.checked)}/>عرض أخبار جميع الأصول ضمن الفترة</label></div><p className="text-xs text-text-muted">التصفية حسب وسوم المصدر ووقت النشر UTC؛ أول إتاحة للنظام غير موثقة في عقد الأخبار الحالي.</p>{['error','unavailable','degraded'].includes(state)&&<p role="alert" className="text-neon-gold">حالة مصدر الأخبار: {state}؛ لم تُؤكد قراءة أرشيف كامل.</p>}<div className="overflow-x-auto"><table className="w-full text-right text-xs [&_td]:p-3 [&_th]:p-3"><thead><tr>{['الخبر','المصدر','الأصول المتأثرة','وقت النشر UTC','أول إتاحة','النبرة'].map(s=><th key={s}>{s}</th>)}</tr></thead><tbody>{selected.map(r=><tr key={r.id}><td>{r.headline}</td><td>{r.source}</td><td>{r.relevance}</td><td>{r.publishedAt}</td><td>غير موثقة</td><td>{r.sentiment}</td></tr>)}{!selected.length&&<tr><td colSpan={6}>{state==='loading'?'جارٍ التحميل…':'لا توجد أخبار مطابقة ضمن السجلات المقروءة.'}</td></tr>}</tbody></table></div></section>;
}
