'use client';
import * as React from 'react';
import { getAuthHeaders } from '../../../lib/api-client';

// بطاقة اتصال منصة MT5 — تُظهر المتغيرات غير السرية (حساب/خادم/مسار) وتحفظها
// عبر POST /api/system/env، وكلمة المرور عبر POST /api/system/mt5-password
// (تُكتب فقط ولا تُقرأ ولا تُعرض إطلاقًا). كل حفظ يتطلب إعادة تشغيل كاملة.

type EnvVar = { key: string; description: string; editable: boolean; value: string | null; unset: boolean };
type EnvPayload = { env_file: string; vars: EnvVar[]; secrets_protected: number; mode: string };

const input='w-full rounded border border-border-primary bg-bg-primary p-2 text-sm text-text-primary';
const button='rounded border border-border-primary px-3 py-2 text-sm hover:border-neon-cyan disabled:opacity-40';
const PLATFORM_KEYS=['MT5_LOGIN','MT5_SERVER','MT5_PATH'] as const;

export default function PlatformConnectionCard(){
  const [vars,setVars]=React.useState<Record<string,string>>({});
  const [descriptions,setDescriptions]=React.useState<Record<string,string>>({});
  const [drafts,setDrafts]=React.useState<Record<string,string>>({});
  const [loaded,setLoaded]=React.useState(false);
  const [password,setPassword]=React.useState('');
  const [msg,setMsg]=React.useState<{tone:'ok'|'err';text:string}|null>(null);
  const [busy,setBusy]=React.useState(false);

  const authHeaders=()=>getAuthHeaders();

  const load=async()=>{
    try{
      const res=await fetch('/api/system/env',{cache:'no-store',headers:authHeaders()});
      if(!res.ok)throw new Error('load failed');
      const p:EnvPayload=await res.json();
      const next:Record<string,string>={};const desc:Record<string,string>={};
      for(const k of PLATFORM_KEYS){
        const v=p.vars.find(x=>x.key===k);
        next[k]=v?.value??'';desc[k]=v?.description??k;
      }
      setVars(next);setDescriptions(desc);setDrafts({...next});setLoaded(true);
    }catch{ setLoaded(true); setMsg({tone:'err',text:'تعذر قراءة متغيرات المنصة — تأكد من الصلاحية ثم أعد المحاولة.'}); }
  };
  React.useEffect(()=>{void load();},[]);

  const saveField=async(key:string)=>{
    setBusy(true);setMsg(null);
    try{
      const res=await fetch('/api/system/env',{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},
        body:JSON.stringify({key,value:drafts[key]})});
      const body=await res.json().catch(()=>null);
      if(!res.ok)throw new Error(body?.detail||'تعذر الحفظ');
      setVars(v=>({...v,[key]:drafts[key]}));
      setMsg({tone:'ok',text:`حُفظ ${key} — يعمل بعد إعادة تشغيل النظام كاملاً.`});
    }catch(e){setMsg({tone:'err',text:e instanceof Error?e.message:'تعذر الحفظ'});}
    finally{setBusy(false);}
  };

  const savePassword=async()=>{
    setBusy(true);setMsg(null);
    try{
      const res=await fetch('/api/system/mt5-password',{method:'POST',headers:{...authHeaders(),'Content-Type':'application/json'},
        body:JSON.stringify({password})});
      const body=await res.json().catch(()=>null);
      if(!res.ok)throw new Error(body?.detail||'تعذر حفظ كلمة المرور');
      setPassword('');
      setMsg({tone:'ok',text:'حُفظت كلمة مرور MT5 — تُكتب فقط ولا تُعرض أبدًا؛ تعمل بعد إعادة تشغيل النظام كاملاً.'});
    }catch(e){setMsg({tone:'err',text:e instanceof Error?e.message:'تعذر حفظ كلمة المرور'});}
    finally{setBusy(false);}
  };

  return <div className="space-y-3 rounded border border-border-primary bg-bg-secondary/30 p-4" aria-label="اتصال منصة MT5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="font-bold">اتصال منصة MT5 — بيانات البيئة العامة</h3>
      <span className="text-xs text-text-muted">بدل البحث في سطور ملف .env — كل حفظ يولّد نسخة .env.bak تلقائيًا</span>
    </div>
    {!loaded&&<p role="status">جارٍ قراءة إعدادات المنصة…</p>}
    {loaded&&<div className="space-y-2">
      {PLATFORM_KEYS.map(k=><div key={k} className="flex flex-wrap items-end gap-2">
        <label className="min-w-64 flex-1 space-y-1 text-sm">
          <span className="font-semibold">{k}</span>
          <span className="block text-xs text-text-muted">{descriptions[k]}</span>
          <input className={input} dir="ltr" value={drafts[k]} onChange={e=>setDrafts(d=>({...d,[k]:e.target.value}))}/>
        </label>
        <button type="button" className={button} disabled={busy||drafts[k]===vars[k]} onClick={()=>void saveField(k)}>حفظ {k}</button>
      </div>)}
    </div>}
    <div className="flex flex-wrap items-end gap-2 border-t border-border-primary pt-3">
      <label className="min-w-64 flex-1 space-y-1 text-sm">
        <span className="font-semibold">MT5_PASSWORD — كلمة مرور منصة MT5</span>
        <span className="block text-xs text-text-muted">تُكتب فقط: لا تُعرض ولا تُقرأ من الخادم مطلقًا، والخانة تُفرغ بعد الحفظ. اتركها فارغة إن كان حسابك يُرفق دون كلمة مرور.</span>
        <input className={input} dir="ltr" type="password" autoComplete="new-password" value={password} onChange={e=>setPassword(e.target.value)}/>
      </label>
      <button type="button" className={button} disabled={busy||!password.trim()} onClick={()=>void savePassword()}>حفظ كلمة المرور</button>
    </div>
    {msg&&<p role={msg.tone==='ok'?'status':'alert'} className={`rounded border p-3 text-sm ${msg.tone==='ok'?'border-neon-green/40 text-neon-green':'border-neon-red/40 text-neon-red'}`}>{msg.text}</p>}
    <p className="text-xs text-text-muted">هذه قيم بيئة التشغيل للمنصة الكاملة (وليست حساب الموقع أعلاه). التغييرات لا تُفعَّل إلا بعد إعادة تشغيل النظام كاملاً — وإعادة التشغيل تحتاج إذنك أنت.</p>
  </div>;
}
