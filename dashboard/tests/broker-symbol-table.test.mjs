import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
const require=createRequire(import.meta.url);
function load(path){
  const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const context={exports:{},AbortController,structuredClone,console,require:(name)=>{
    if(!name.startsWith('.'))return require(name);
    const p=resolve(dirname(path),name);return load(existsSync(p+'.tsx')?p+'.tsx':p+'.ts');
  }};vm.runInNewContext(code,context);return context.exports;
}
const root=fileURLToPath(new URL('../src/components/settings/broker/',import.meta.url));
const {filterSymbols,sortSymbols,nextSortDir}=load(root+'symbol-table.ts');
const rows=[
  {category:'Metals',name:'XAUUSDs',description:'Gold vs USD'},
  {category:'FX',name:'AUDUSDs',description:'Aussie vs USD'},
  {category:'Indices',name:'VIXs',description:'Volatility index'},
  {category:'Metals',name:'XAGUSDs',description:'Silver vs USD'},
  {category:'FX',name:'EURUSDs',description:''},
];
test('filterSymbols narrows by every populated column independently',()=>{
  assert.deepEqual(filterSymbols(rows,{category:'',name:'',description:''}).map(r=>r.name),['XAUUSDs','AUDUSDs','VIXs','XAGUSDs','EURUSDs']);
  assert.deepEqual(filterSymbols(rows,{category:'metals',name:'',description:''}).map(r=>r.name),['XAUUSDs','XAGUSDs']);
  assert.deepEqual(filterSymbols(rows,{category:'',name:'usd',description:''}).map(r=>r.name),['XAUUSDs','AUDUSDs','XAGUSDs','EURUSDs']);
  assert.deepEqual(filterSymbols(rows,{category:'',name:'',description:'aussie'}).map(r=>r.name),['AUDUSDs']);
  assert.deepEqual(filterSymbols(rows,{category:'fx',name:'eur',description:''}).map(r=>r.name),['EURUSDs']);
  assert.deepEqual(filterSymbols(rows,{category:'fx',name:'zzz',description:''}),[]);
});
test('sortSymbols orders by column, asc and desc, with empty descriptions last',()=>{
  assert.deepEqual(sortSymbols(rows,'name','asc').map(r=>r.name),['AUDUSDs','EURUSDs','VIXs','XAGUSDs','XAUUSDs']);
  assert.deepEqual(sortSymbols(rows,'name','desc').map(r=>r.name),['XAUUSDs','XAGUSDs','VIXs','EURUSDs','AUDUSDs']);
  assert.deepEqual(sortSymbols(rows,'category','asc').map(r=>r.name),['AUDUSDs','EURUSDs','VIXs','XAUUSDs','XAGUSDs']);
  const byDescription=sortSymbols(rows,'description','asc');
  assert.equal(byDescription[byDescription.length-1].name,'EURUSDs','empty description sorts last');
  assert.equal(sortSymbols(rows,'description','desc')[0].name,'VIXs','desc puts the last non-empty description first; empty stays last');
});
test('sortSymbols does not mutate its input',()=>{
  const before=rows.map(r=>r.name);
  sortSymbols(rows,'name','desc');
  assert.deepEqual(rows.map(r=>r.name),before);
});
test('nextSortDir starts a new column ascending and toggles the active one',()=>{
  assert.equal(nextSortDir(null,'name'),'asc');
  assert.equal(nextSortDir({key:'name',dir:'asc'},'name'),'desc');
  assert.equal(nextSortDir({key:'name',dir:'desc'},'name'),'asc');
  assert.equal(nextSortDir({key:'name',dir:'asc'},'category'),'asc');
});
