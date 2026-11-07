import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require=createRequire(import.meta.url);
function load(path){
  const code=ts.transpileModule(readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
  const context={exports:{},AbortController,structuredClone,console,process:{env:{}},require:(name)=>{
    if(!name.startsWith('.'))return require(name);
    const p=resolve(dirname(path),name);return load(existsSync(p+'.tsx')?p+'.tsx':p+'.ts');
  }};vm.runInNewContext(code,context);return context.exports;
}
const root=fileURLToPath(new URL('../src/components/settings/broker/',import.meta.url));
const {createBrokerController}=load(root+'controller.ts');
const {BrokerSettingsView}=load(root+'BrokerSettingsView.tsx');
function fixture(){
 const empty={assets:[],transition:{from_offset_seconds:null,to_offset_seconds:null,session_start_date:null,effective_at_utc:null,during_market_closure:'unknown',next_open_utc:null,support_reply:'',evidence_received_at:null}};
 const accounts={a:{account_id:'a',profile_id:'p',label:'Demo A',server:'OneRoyal-Demo',masked_login:'••••1234',account_kind:'demo',settings:structuredClone(empty),version:1,persistence:'durable',runtime_effective:false,connection_state:'unconnected'}};
 accounts.b={...structuredClone(accounts.a),account_id:'b',label:'Demo B'};
 let failure=0,identity='u1',profileCalls=0;
 const api={identity:()=>identity,listProfiles:async()=>{profileCalls++;return [{profile_id:'p',name:'Mine',broker_name:'OneRoyal',accounts:Object.values(accounts)}];},
 createProfile:async v=>({profile_id:'new',...v,accounts:[]}),
 createAccount:async v=>({...structuredClone(accounts.a),...v,account_id:'newAccount'}),
 getAccount:async id=>structuredClone(accounts[id]),events:async()=>[],
 saveSettings:async(id,version,settings)=>{if(failure)throw Object.assign(new Error('failed'),{status:failure});assert.equal(version,accounts[id].version);accounts[id]={...accounts[id],settings:structuredClone(settings),version:version+1};return structuredClone(accounts[id]);}};
 return {api,accounts,c:createBrokerController(api),fail:n=>failure=n,identity:v=>identity=v,profileCalls:()=>profileCalls};
}
function html(c){return renderToStaticMarkup(React.createElement(BrokerSettingsView,{controller:c,state:c.getSnapshot()}));}
// Same check the mounted BrokerSettingsTab runs on its 1s interval / storage / focus events.
function pollTick(c){if(c.checkIdentity())void c.load();}
test('dirty draft survives repeated poll cycles without identity change and without refetching',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
  c.patchTransition({support_reply:'typed while polling'});
  c.addAsset('XAUUSD');c.setAssetMode('XAUUSD','analysis');
  assert.equal(c.getSnapshot().dirty,true);
  const before=f.profileCalls();
  for(let i=0;i<25;i++){pollTick(c);assert.equal(c.getSnapshot().dirty,true);
    assert.equal(c.getSnapshot().account.account_id,'a');
    assert.equal(c.getSnapshot().draft.transition.support_reply,'typed while polling');
    assert.equal(c.getSnapshot().draft.assets[0].mode,'analysis');}
  assert.equal(f.profileCalls(),before,'poll must not refetch or reload while identity is unchanged');
});
test('poll-driven identity change wipes state and a stale load cannot restore the old draft',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
  c.patchTransition({support_reply:'old user draft'});
  let release;f.api.listProfiles=()=>new Promise(r=>release=()=>r([{profile_id:'p',name:'Mine',broker_name:'OneRoyal',accounts:[f.accounts.b]}]));
  f.identity('u2');pollTick(c);
  assert.equal(c.getSnapshot().account,null);assert.equal(c.getSnapshot().draft,null);assert.equal(c.getSnapshot().dirty,false);
  release();await new Promise(r=>setTimeout(r,0));
  assert.equal(c.getSnapshot().account,null,'stale load response must not resurrect the previous identity state');
  assert.equal(c.getSnapshot().draft,null);
});
test('save acknowledgement then polling keeps the persisted state and never re-announces dirty',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
  c.patchTransition({support_reply:'saved note'});await c.save();
  assert.equal(c.getSnapshot().dirty,false);assert.equal(c.getSnapshot().version??c.getSnapshot().account.version,2);
  assert.match(c.getSnapshot().notice,/تم الحفظ الدائم/);
  for(let i=0;i<10;i++){pollTick(c);
    assert.equal(c.getSnapshot().dirty,false);
    assert.equal(c.getSnapshot().account.version,2);
    assert.equal(c.getSnapshot().draft.transition.support_reply,'saved note');
    assert.doesNotMatch(c.getSnapshot().error,/./);}
  assert.equal(f.accounts.a.version,2,'polling must not trigger writes');
});
test('polling during an in-flight save keeps busy and never claims saved before the backend answers',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
  c.patchTransition({support_reply:'pending save'});
  let release;f.api.saveSettings=(id,version,settings)=>new Promise(r=>release=()=>r(structuredClone({account_id:id,profile_id:'p',label:'Demo A',server:'OneRoyal-Demo',masked_login:'••••',account_kind:'demo',settings,version:version+1,persistence:'durable',runtime_effective:false,connection_state:'unconnected'})));
  const saving=c.save();
  for(let i=0;i<10;i++){pollTick(c);
    assert.equal(c.getSnapshot().busy,true);
    assert.equal(c.getSnapshot().notice,'','no success claim before backend acknowledgement');
    assert.equal(c.getSnapshot().dirty,true);}
  release();await saving;
  assert.equal(c.getSnapshot().busy,false);assert.equal(c.getSnapshot().dirty,false);
  assert.match(c.getSnapshot().notice,/تم الحفظ الدائم/);
});
test('version conflict is an explicit state, kept until a successful save or account switch',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
  c.patchTransition({support_reply:'mine'});f.fail(409);await c.save();
  assert.equal(c.getSnapshot().conflict,true,'409 must surface a distinct version_conflict state');
  assert.equal(c.getSnapshot().dirty,true,'conflict must not clear the local draft');
  assert.match(html(c),/تعارض نسخة/);
  for(let i=0;i<5;i++)pollTick(c);
  assert.equal(c.getSnapshot().conflict,true,'polling must not clear an unresolved conflict');
  assert.equal(c.getSnapshot().draft.transition.support_reply,'mine','the draft survives a rejected save');
  f.fail(0);await c.save();
  assert.equal(c.getSnapshot().conflict,false,'a successful save resolves the conflict');
  assert.equal(f.accounts.a.settings.transition.support_reply,'mine','the surviving draft is then persisted');
  c.patchTransition({support_reply:'again'});f.fail(409);await c.save();
  assert.equal(c.getSnapshot().conflict,true);
  await c.selectAccount('b');
  assert.equal(c.getSnapshot().conflict,false,'switching accounts resolves the conflict marker with the old draft gone');
});
test('assets section documents what disabled/analysis/trade mean and that save scope is one account draft',async()=>{
  const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');c.setSection('assets');
  const markup=html(c);
  assert.match(markup,/معطل/);
  assert.match(markup,/لا يدخل التحليل ولا يُسجَّل كتفضيل تداول/,'picker scope must state the adopted meaning of disabled');
  assert.match(markup,/لا يمنح صلاحية تداول/,'analysis mode must not imply trade permission');
  assert.match(markup,/لا يفعّل التداول/,'trade preference must not imply execution');
  assert.match(markup,/نطاق الحفظ/,'save scope must be stated');
  assert.match(markup,/حساب واحد/);
});
