export interface BatchTask {symbol:string;timeframe:string}
export interface BatchRow<T> extends BatchTask {state:'queued'|'running'|'completed'|'partial'|'failed'|'cancelled';result?:T;error?:string}
export function planBatch(symbols:string[],frames:string[]):BatchTask[]{
 const tasks=[...new Set(symbols)].filter(Boolean).flatMap(symbol=>[...new Set(frames)].filter(Boolean).map(timeframe=>({symbol,timeframe})));
 if(!tasks.length||tasks.length>64)throw new Error('اختر أصولًا وأطرًا؛ الحد 64 طلبًا لكل دفعة.');
 return tasks;
}
export async function executeBatch<T extends {count:number;received?:number}>(tasks:BatchTask[],send:(task:BatchTask)=>Promise<T>,signal:AbortSignal,onRow:(row:BatchRow<T>)=>void){
 for(const task of tasks){
  if(signal.aborted){onRow({...task,state:'cancelled'});continue;}
  onRow({...task,state:'running'});
  try{const result=await send(task);onRow({...task,state:result.count>0&&result.received!==0?'completed':'partial',result});}
  catch(error){onRow({...task,state:signal.aborted?'cancelled':'failed',error:error instanceof Error?error.message:String(error)});}
 }
}
export function summarizeReadiness(report:{datasets:Record<string,unknown>[];validation:Record<string,unknown>[]}){
 const assets=report.datasets;
 const symbols=new Set(assets.map(a=>a.symbol));
 const checks=report.validation.filter(row=>symbols.has(row.symbol));
 const missing=assets.filter(a=>!(Number(a.rows)>0)).length;
 const review=checks.filter(row=>row.result!=='passed').length;
 const checked=assets.filter(a=>checks.some(row=>row.symbol===a.symbol)).length;
 return {assets:assets.length,loaded:assets.length-missing,missing,checks:checks.length,review,
  status:!assets.length||missing||checks.some(row=>['failed','blocked'].includes(String(row.result)))?'blocked':review||checked<assets.length?'needs_review':'passed'};
}
