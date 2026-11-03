import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
const context={exports:{}};
vm.runInNewContext(ts.transpileModule(readFileSync(new URL('../src/components/research-lab/batch.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,context);
const {planBatch,executeBatch,summarizeReadiness}=context.exports;
test('batch plans unique asset/frame pairs and retains independent failure results',async()=>{
 const tasks=planBatch(['GOLD','OIL','GOLD'],['M15','H1','M15']);
 assert.equal(tasks.length,4);
 const calls=[],rows=[];const abort=new AbortController();
 await executeBatch(tasks,async task=>{calls.push(task.symbol+'/'+task.timeframe);if(task.symbol==='OIL')throw new Error('source offline');return {count:12,added:2,existing:10,quality:{unclassified_gaps:0,rejected:0}};},abort.signal,row=>rows.push(row));
 assert.deepEqual(calls,['GOLD/M15','GOLD/H1','OIL/M15','OIL/H1']);
 assert.equal(rows.filter(r=>r.state==='completed').length,2);
 assert.equal(rows.filter(r=>r.state==='failed').length,2);
 assert.equal(rows.find(r=>r.state==='completed').result.added,2);
});
test('abort stops remaining requests without calling them successful',async()=>{
 const abort=new AbortController(),rows=[];let calls=0;
 await executeBatch(planBatch(['A','B','C'],['M15']),async()=>{calls++;abort.abort();throw new Error('aborted');},abort.signal,row=>rows.push(row));
 assert.equal(calls,1);
 assert.equal(rows.filter(r=>r.state==='completed').length,0);
 assert.equal(rows.filter(r=>r.state==='cancelled').length,3);
});
test('empty results are partial, and oversized or empty plans are rejected',async()=>{
 assert.throws(()=>planBatch([],['M15']));
 assert.throws(()=>planBatch(Array.from({length:65},(_,i)=>String(i)),['M15']));
 const rows=[];
 await executeBatch(planBatch(['A'],['M15']),async()=>({count:0,received:0}),new AbortController().signal,row=>rows.push(row));
 assert.equal(rows.at(-1).state,'partial');
});
test('readiness considers only saved dataset symbols and never hides missing evidence',()=>{
 const report={datasets:[{symbol:'GOLD',rows:150},{symbol:'OIL',rows:0}],validation:[{symbol:'GOLD',result:'passed'},{symbol:'US10Y',result:'blocked'}]};
 assert.equal(summarizeReadiness(report).status,'blocked');
 report.datasets[1].rows=120;report.validation.push({symbol:'OIL',result:'needs_review'});
 assert.equal(summarizeReadiness(report).status,'needs_review');
 report.validation[1].result='passed';report.validation[2].result='passed';
 assert.equal(summarizeReadiness(report).status,'passed');
 assert.equal(summarizeReadiness({datasets:[],validation:[]}).status,'blocked');
});
