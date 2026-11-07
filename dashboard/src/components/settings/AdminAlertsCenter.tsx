'use client';

import { useEffect, useState } from 'react';
import { ImagePlus, Plus, RefreshCcw, ShieldCheck, Trash2, UserCog, Users } from 'lucide-react';

const API = process.env.NEXT_PUBLIC_API_URL || '';
const authHeaders = () => ({ 'Content-Type':'application/json', Authorization:`Bearer ${localStorage.getItem('nexus-token') || ''}` });

type UserRow = { user_id:string; username:string; full_name:string; email?:string|null; role_id?:string|null; active:boolean; avatar_url?:string|null; last_login_at?:string|null };
type RoleRow = { role_id:string; name_ar:string; name_en:string; description_ar?:string; protected:boolean; permissions:string[] };

function Toggle({v,on,label}:{v:boolean;on:(v:boolean)=>void;label:string}) { return <button type="button" onClick={()=>on(!v)} className={`rounded border px-2 py-1 text-[10px] ${v?'border-neon-cyan/40 bg-neon-cyan/10 text-neon-cyan':'border-border-primary text-text-muted'}`}>{v?'●':'○'} {label}</button>; }
function Field({label,children}:{label:string;children:React.ReactNode}) { return <label className="block text-[10px] text-text-muted"><span>{label}</span><div className="mt-1">{children}</div></label>; }

export default function AdminAlertsCenter() {
  const [tab,setTab]=useState<'users'|'roles'|'audit'>('users');
  const [users,setUsers]=useState<UserRow[]>([]); const [roles,setRoles]=useState<RoleRow[]>([]); const [audit,setAudit]=useState<any[]>([]);
  const [status,setStatus]=useState(''); const [showAdd,setShowAdd]=useState(false);
  const [form,setForm]=useState({username:'',full_name:'',email:'',password:'',role_id:'viewer',active:true,avatar_data_url:''});
  const load=async()=>{ try { const [u,r,a]=await Promise.all([
    fetch(`${API}/api/admin/users`,{headers:authHeaders()}), fetch(`${API}/api/admin/roles`,{headers:authHeaders()}), fetch(`${API}/api/admin/audit?limit=100`,{headers:authHeaders()})]);
    if(u.ok)setUsers((await u.json()).users||[]); if(r.ok)setRoles((await r.json()).roles||[]); if(a.ok)setAudit((await a.json()).items||[]);
  } catch(e){setStatus(String(e));}};
  useEffect(()=>{void load();},[]);
  const addUser=async()=>{ const r=await fetch(`${API}/api/admin/users`,{method:'POST',headers:authHeaders(),body:JSON.stringify(form)}); if(r.ok){setShowAdd(false);setForm({username:'',full_name:'',email:'',password:'',role_id:'viewer',active:true,avatar_data_url:''});await load();setStatus('تمت إضافة المستخدم.');}else setStatus(await r.text()); };
  const setActive=async(u:UserRow,v:boolean)=>{ const r=await fetch(`${API}/api/admin/users/${u.user_id}`,{method:'PUT',headers:authHeaders(),body:JSON.stringify({active:v})}); if(r.ok)await load();else setStatus(await r.text()); };
  const del=async(u:UserRow)=>{ if(!confirm(`تعطيل وحذف المستخدم ${u.full_name}؟`))return; const r=await fetch(`${API}/api/admin/users/${u.user_id}`,{method:'DELETE',headers:authHeaders()}); if(r.ok)await load();else setStatus(await r.text()); };
  const avatarFile=async(file?:File)=>{ if(!file)return; if(file.size>2_000_000){setStatus('الصورة أكبر من 2MB.');return;} const reader=new FileReader(); reader.onload=()=>setForm(f=>({...f,avatar_data_url:String(reader.result||'')})); reader.readAsDataURL(file); };
  const roleName=(id?:string|null)=>roles.find(r=>r.role_id===id)?.name_ar||id||'—';
  // Owner 2026-11-07: ticker/audio sub-tabs removed — they duplicated the
  // global news-ticker settings (الإعدادات ← التحكم بالشريط الإخباري والصوت)
  // and their saved per-user values silently overrode the global config.
  const tabs=[['users','المستخدمون',Users],['roles','الأدوار والصلاحيات',ShieldCheck],['audit','سجل النشاط',UserCog]] as const;

  return <div dir="rtl" className="mx-auto w-full max-w-[1500px] p-4 text-text-secondary">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 border border-border-primary bg-bg-secondary/60 p-3"><div><h2 className="text-sm font-bold text-text-primary">مركز المستخدمين والتنبيهات</h2><p className="text-[10px] text-text-muted">المستخدمون والصلاحيات وشريط الأخبار والتنبيهات الناطقة — إعدادات منفصلة لكل حساب.</p></div><button onClick={()=>void load()} className="flex items-center gap-1 border border-border-primary px-2 py-1 text-[10px]"><RefreshCcw className="h-3 w-3"/>تحديث</button></div>
    <div className="mb-4 flex flex-wrap gap-1 border-b border-border-primary">{tabs.map(([id,label,Icon])=><button key={id} onClick={()=>setTab(id)} className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-[10px] ${tab===id?'border-neon-purple text-neon-purple':'border-transparent text-text-muted'}`}><Icon className="h-3.5 w-3.5"/>{label}</button>)}</div>

    {tab==='users' && <div className="space-y-3"><div className="flex justify-end"><button onClick={()=>setShowAdd(true)} className="flex items-center gap-1 rounded bg-neon-purple/20 px-3 py-2 text-[10px] font-bold text-neon-purple"><Plus className="h-3 w-3"/>إضافة مستخدم</button></div><div className="overflow-x-auto border border-border-primary"><table className="w-full text-[10px]"><thead className="bg-bg-tertiary text-text-muted"><tr><th className="p-2 text-right">المستخدم</th><th>الدور</th><th>الحالة</th><th>آخر دخول</th><th>إجراءات</th></tr></thead><tbody>{users.map(u=><tr key={u.user_id} className="border-t border-border-primary"><td className="p-2"><div className="flex items-center gap-2">{u.avatar_url?<img src={`${API}${u.avatar_url}`} className="h-8 w-8 rounded-full object-cover"/>:<div className="grid h-8 w-8 place-items-center rounded-full bg-neon-purple/15 font-bold text-neon-purple">{u.full_name.slice(0,1)}</div>}<div><b className="text-text-primary">{u.full_name}</b><div className="text-text-muted">@{u.username} {u.email?`· ${u.email}`:''}</div></div></div></td><td className="text-center">{roleName(u.role_id)}</td><td className="text-center"><Toggle v={u.active} on={v=>void setActive(u,v)} label={u.active?'نشط':'موقوف'}/></td><td className="text-center text-text-muted">{u.last_login_at?new Date(u.last_login_at).toLocaleString('ar'):'—'}</td><td className="text-center"><button onClick={()=>void del(u)} className="p-1 text-neon-red"><Trash2 className="h-3.5 w-3.5"/></button></td></tr>)}</tbody></table></div></div>}

    {showAdd && <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"><div className="w-full max-w-xl border border-border-primary bg-bg-secondary p-4"><h3 className="mb-3 font-bold text-text-primary">إضافة مستخدم</h3><div className="grid gap-3 md:grid-cols-2"><Field label="الاسم الكامل"><input className="neon-input w-full" value={form.full_name} onChange={e=>setForm(f=>({...f,full_name:e.target.value}))}/></Field><Field label="اسم المستخدم"><input className="neon-input w-full" value={form.username} onChange={e=>setForm(f=>({...f,username:e.target.value}))}/></Field><Field label="البريد"><input className="neon-input w-full" value={form.email} onChange={e=>setForm(f=>({...f,email:e.target.value}))}/></Field><Field label="كلمة مرور مؤقتة (10+)"><input type="password" className="neon-input w-full" value={form.password} onChange={e=>setForm(f=>({...f,password:e.target.value}))}/></Field><Field label="الدور"><select className="neon-input w-full" value={form.role_id} onChange={e=>setForm(f=>({...f,role_id:e.target.value}))}>{roles.map(r=><option key={r.role_id} value={r.role_id}>{r.name_ar}</option>)}</select></Field><Field label="الصورة الشخصية"><label className="flex cursor-pointer items-center gap-2 border border-border-primary p-2"><ImagePlus className="h-4 w-4"/><span>اختيار صورة PNG/JPG/WebP</span><input hidden type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>void avatarFile(e.target.files?.[0])}/></label></Field></div><div className="mt-4 flex justify-end gap-2"><button onClick={()=>setShowAdd(false)} className="border border-border-primary px-3 py-2 text-[10px]">إلغاء</button><button onClick={()=>void addUser()} className="bg-neon-purple/20 px-3 py-2 text-[10px] font-bold text-neon-purple">حفظ المستخدم</button></div></div></div>}

    {tab==='roles' && <div className="grid gap-3 lg:grid-cols-2">{roles.map(r=><div key={r.role_id} className="border border-border-primary bg-bg-secondary/40 p-3"><div className="flex items-center justify-between"><div><b className="text-text-primary">{r.name_ar}</b><div className="text-[9px] text-text-muted">{r.name_en}</div></div>{r.protected&&<span className="text-[9px] text-neon-cyan">محمي</span>}</div><p className="my-2 text-[10px] text-text-muted">{r.description_ar}</p><div className="flex flex-wrap gap-1">{r.permissions.map(p=><span key={p} className="rounded border border-border-primary px-1.5 py-0.5 text-[8px] font-mono">{p}</span>)}</div></div>)}</div>}

    {tab==='audit' && <div className="overflow-x-auto border border-border-primary"><table className="w-full text-[10px]"><thead className="bg-bg-tertiary"><tr><th className="p-2">الوقت</th><th>المستخدم</th><th>العملية</th><th>الهدف</th></tr></thead><tbody>{audit.map((a:any)=><tr key={a.audit_id} className="border-t border-border-primary"><td className="p-2">{new Date(a.created_at).toLocaleString('ar')}</td><td>{a.actor_user_id||'system'}</td><td className="font-mono">{a.action}</td><td>{a.target_type||'—'} / {a.target_id||'—'}</td></tr>)}</tbody></table></div>}

    <div className="mt-4 flex items-center justify-between border border-border-primary bg-bg-secondary/40 p-3"><span className="text-[10px] text-text-muted">{status||'التغييرات الشخصية لا تؤثر على Risk أو Execution.'}</span></div>
  </div>;
}
