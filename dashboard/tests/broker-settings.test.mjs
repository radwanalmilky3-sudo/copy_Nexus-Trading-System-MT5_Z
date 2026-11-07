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
 const accounts={a:{account_id:'a',profile_id:'p',label:'Demo A',server:'OneRoyal-Demo',masked_login:'••••',account_kind:'demo',settings:structuredClone(empty),version:1,persistence:'durable',runtime_effective:false,connection_state:'unconnected'}};
 accounts.b={...structuredClone(accounts.a),account_id:'b',label:'Demo B'};
 let failure=0,identity='u1';
 const api={identity:()=>identity,listProfiles:async()=>[{profile_id:'p',name:'Mine',broker_name:'OneRoyal',accounts:Object.values(accounts)}],
 createProfile:async v=>({profile_id:'new',...v,accounts:[]}),
 createAccount:async v=>({...structuredClone(accounts.a),...v,account_id:'newAccount'}),
 getAccount:async id=>structuredClone(accounts[id]),events:async()=>[],
 saveSettings:async(id,version,settings)=>{if(failure)throw Object.assign(new Error('failed'),{status:failure});assert.equal(version,accounts[id].version);accounts[id]={...accounts[id],settings:structuredClone(settings),version:version+1};return structuredClone(accounts[id]);}};
 return {api,accounts,c:createBrokerController(api),fail:n=>failure=n,identity:v=>identity=v};
}
function html(c){return renderToStaticMarkup(React.createElement(BrokerSettingsView,{controller:c,state:c.getSnapshot()}));}
function buttons(node,out=[]){if(!node||typeof node!=='object')return out;if(node.type==='button')out.push(node);React.Children.forEach(node.props?.children,c=>buttons(c,out));return out;}
test('saved working account restores on reload and failed settings save does not change preference',async()=>{
 const f=fixture();let remembered='b';f.api.rememberedAccount=()=>remembered;f.api.rememberAccount=id=>{remembered=id;};
 await f.c.load();assert.equal(f.c.getSnapshot().account.account_id,'b');
 await f.c.selectAccount('a');f.c.patchTransition({support_reply:'saved note'});f.fail(503);
 await f.c.rememberSelection();assert.equal(remembered,'b');
 f.fail(0);await f.c.rememberSelection();assert.equal(remembered,'a');
 await f.c.load();assert.equal(f.c.getSnapshot().account.account_id,'a');assert.equal(f.c.getSnapshot().draft.transition.support_reply,'saved note');
});
test('connection checks report identity-verified read success and clear success after failure',async()=>{
 const f=fixture(),c=f.c;
 f.api.listSymbols=async()=>[{category:'Metals',name:'XAUUSDs',description:'Gold'}];
 await c.load();await c.selectAccount('a');c.setSection('connection');
 assert.equal(c.getSnapshot().connectionCheck.ok,true);
 assert.match(html(c),/نجح اتصال القراءة/);
 f.api.listSymbols=async()=>{throw new Error('identity mismatch');};
 await c.checkConnection();assert.equal(c.getSnapshot().connectionCheck.ok,false);
 assert.equal(c.getSnapshot().symbols.length,0);assert.doesNotMatch(html(c),/نجح اتصال القراءة/);
});
test('own account draft edits and support preset persist, without inventing an instant',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');c.setSection('timing');
 const tree=BrokerSettingsView({controller:c,state:c.getSnapshot()});
 const preset=buttons(tree).find(b=>b.props.children==='تعبئة مسودة رد OneRoyal');assert.ok(preset);preset.props.onClick();
 assert.equal(c.getSnapshot().draft.transition.during_market_closure,'yes');
 assert.equal(c.getSnapshot().draft.transition.session_start_date,'2026-11-02');
 assert.equal(c.getSnapshot().draft.transition.effective_at_utc,null);
 assert.match(html(c),/غير محددة/);c.addAsset('XAUUSD');c.setAssetMode('XAUUSD','analysis');await c.save();
 assert.equal(f.accounts.a.version,2);assert.equal(f.accounts.a.settings.assets[0].mode,'analysis');
 await c.selectAccount('b');assert.equal(c.getSnapshot().draft.transition.support_reply,'');
 await c.selectAccount('a');assert.match(c.getSnapshot().draft.transition.support_reply,/أثناء إغلاق السوق/);
 assert.match(html(c),/التنفيذ غير موصول/);
 c.setProfileForm({name:'new profile',broker_name:'OneRoyal'});await c.createProfile();assert.ok(c.getSnapshot().profiles.some(p=>p.profile_id==='new'));
 c.setAccountForm({profile_id:'p',label:'New',server:'Demo',login:'999',account_kind:'demo'});await c.createAccount();assert.equal(c.getSnapshot().account.account_id,'newAccount');
});
test('403 and 409 keep edited draft and expose failures, never saved success',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');c.patchTransition({support_reply:'my unsaved reply'});
 for(const status of [403,409,503]){f.fail(status);await c.save();assert.equal(c.getSnapshot().draft.transition.support_reply,'my unsaved reply');assert.ok(c.getSnapshot().error);assert.equal(c.getSnapshot().notice,'');assert.equal(f.accounts.a.version,1);}
});
test('late save/read responses cannot overwrite a different selected account',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');let resolveSave;
 f.api.saveSettings=()=>new Promise(r=>resolveSave=r);const saving=c.save();await c.selectAccount('b');resolveSave({...f.accounts.a,version:2});await saving;
 assert.equal(c.getSnapshot().account.account_id,'b');assert.equal(c.getSnapshot().draft.transition.support_reply,'');
 let resolveRead;f.api.getAccount=id=>id==='a'?new Promise(r=>resolveRead=r):Promise.resolve(f.accounts.b);
 const reading=c.selectAccount('a');await c.selectAccount('b');resolveRead(f.accounts.a);await reading;assert.equal(c.getSnapshot().account.account_id,'b');
});
test('changed login identity clears cached profiles and pending responses',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');let done;
 f.api.saveSettings=()=>new Promise(r=>done=r);const saving=c.save();f.identity('u2');c.checkIdentity();assert.equal(c.getSnapshot().account,null);assert.equal(c.getSnapshot().profiles.length,0);
 done(f.accounts.a);await saving;assert.equal(c.getSnapshot().account,null);
});
test('409 comparison preserves local edits and requires explicit rebase choice',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');c.patchTransition({support_reply:'local edits'});
 f.accounts.a={...f.accounts.a,version:2,settings:{...f.accounts.a.settings,transition:{...f.accounts.a.settings.transition,support_reply:'remote edits'}}};
 f.fail(409);await c.save();await c.compareLatest();
 assert.equal(c.getSnapshot().draft.transition.support_reply,'local edits');
 assert.equal(c.getSnapshot().account.version,1);assert.equal(c.getSnapshot().latest.version,2);
 c.keepLocalOnLatest();assert.equal(c.getSnapshot().account.version,2);assert.equal(c.getSnapshot().draft.transition.support_reply,'local edits');
 f.fail(0);await c.save();assert.equal(f.accounts.a.version,3);assert.equal(f.accounts.a.settings.transition.support_reply,'local edits');
});
test('creation responses do not clear fields edited after submission',async()=>{
 const f=fixture(),c=f.c;await c.load();c.setProfileForm({name:'First',broker_name:'OneRoyal'});let profileDone;
 f.api.createProfile=()=>new Promise(r=>profileDone=r);const creating=c.createProfile();c.setProfileForm({name:'Next'});
 profileDone({profile_id:'new',name:'First',broker_name:'OneRoyal',accounts:[]});await creating;
 assert.equal(c.getSnapshot().profileForm.name,'Next');
 c.setAccountForm({profile_id:'p',label:'First',server:'Demo',login:'123'});let accountDone;
 f.api.createAccount=()=>new Promise(r=>accountDone=r);const adding=c.createAccount();c.setAccountForm({label:'Next',login:'456'});
 accountDone({...f.accounts.a,account_id:'newAccount'});await adding;
 assert.equal(c.getSnapshot().accountForm.label,'Next');assert.equal(c.getSnapshot().accountForm.login,'456');
});

test('linked broker tables filter accounts and switching broker clears stale account responses',async()=>{
 const f=fixture(),c=f.c;
 const original=f.api.listProfiles;
 f.api.listProfiles=async()=>[...(await original()),{profile_id:'other',name:'Second',broker_name:'Other broker',accounts:[]}];
 await c.load();await c.selectAccount('a');
 assert.match(html(c),/جدول الوسطاء/);assert.match(html(c),/جدول حسابات الوسيط/);
 let finish;f.api.getAccount=()=>new Promise(r=>finish=r);
 const reading=c.selectAccount('b');c.selectProfile('other');finish(f.accounts.b);await reading;
 assert.equal(c.getSnapshot().selectedProfileId,'other');assert.equal(c.getSnapshot().account,null);
 assert.equal(c.getSnapshot().accountForm.profile_id,'other');
 assert.doesNotMatch(html(c),/Demo A|Demo B/);
 assert.match(html(c),/لا توجد حسابات لهذا الوسيط/);
});

test('timing and account history render as labelled tables',async()=>{
 const f=fixture(),c=f.c;await c.load();await c.selectAccount('a');
 c.setSection('timing');assert.match(html(c),/aria-label="جدول الجلسات والتوقيت"/);
 c.setSection('evidence');assert.match(html(c),/aria-label="جدول الأدلة والسجل"/);
 c.setSection('connection');assert.match(html(c),/aria-label="حالة اتصال الحساب"/);
});

test('settings tabs render an icon and identify the active tab',async()=>{
 const f=fixture(),c=f.c;await c.load();
 const markup=html(c);
 assert.match(markup,/aria-label="أقسام الوسيط"/);
 assert.match(markup,/aria-current="page"/);
 assert.match(markup,/aria-hidden="true"/);
 assert.match(markup,/data-tab="accounts"/);
 c.setSection('timing');
 const timing=html(c);
 assert.match(timing,/data-tab="timing"[^>]*aria-current="page"/);
 assert.doesNotMatch(timing,/data-tab="accounts"[^>]*aria-current="page"/);
});
