'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Eye, EyeOff, Shield, UserPlus, Zap } from 'lucide-react';
import { withRequestTimeout } from '@/lib/request-timeout';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

export default function LoginPage() {
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [bootstrap, setBootstrap] = useState(false);
  const [credentials, setCredentials] = useState({ username: '', password: '' });
  const [firstAdmin, setFirstAdmin] = useState({ admin_pin:'', username:'', full_name:'', password:'', email:'' });
  const [error, setError] = useState('');

  const login = async (e: React.FormEvent) => {
    e.preventDefault(); setIsLoading(true); setError('');
    try {
      const data = await withRequestTimeout(async (signal) => {
        const res = await fetch(`${API}/api/v2/auth/login`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(credentials), signal });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      });
      localStorage.setItem('nexus-token', data.token); router.push('/dashboard');
    } catch (e) { setError(e instanceof Error ? e.message : 'Authentication failed'); } finally { setIsLoading(false); }
  };
  const createFirst = async (e:React.FormEvent) => {
    e.preventDefault(); setIsLoading(true); setError('');
    try {
      await withRequestTimeout(async (signal) => {
        const res=await fetch(`${API}/api/v2/auth/bootstrap`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(firstAdmin),signal});
        if(!res.ok)throw new Error(await res.text());
      });
      setCredentials({username:firstAdmin.username,password:firstAdmin.password}); setBootstrap(false); setError('تم إنشاء أول Super Administrator. سجّل الدخول الآن.');
    } catch(e){setError(e instanceof Error?e.message:'تعذر إنشاء الحساب');} finally{setIsLoading(false);}
  };

  return <div className="flex min-h-screen items-center justify-center bg-bg-primary p-4"><div className="w-full max-w-md space-y-6"><div className="text-center"><div className="inline-flex items-center gap-3"><Zap className="h-9 w-9 text-neon-green"/><h1 className="text-3xl font-black"><span className="gradient-text">NEXUS</span> TRADER</h1></div><p className="mt-2 text-xs text-text-muted">Secure multi-user access</p></div><div className="neon-card p-7"><div className="mb-5 flex items-center justify-between"><div className="flex items-center gap-2"><Shield className="h-5 w-5 text-neon-purple"/><h2 className="font-semibold">{bootstrap?'تهيئة أول مدير':'تسجيل الدخول'}</h2></div><button onClick={()=>{setBootstrap(v=>!v);setError('')}} className="flex items-center gap-1 text-[10px] text-neon-cyan"><UserPlus className="h-3.5 w-3.5"/>{bootstrap?'عودة للدخول':'أول تشغيل'}</button></div>{!bootstrap?<form onSubmit={login} className="space-y-4"><label className="block text-xs">اسم المستخدم<input className="neon-input mt-1 w-full" value={credentials.username} onChange={e=>setCredentials(p=>({...p,username:e.target.value}))} required/></label><label className="block text-xs">كلمة المرور<div className="relative mt-1"><input type={showPassword?'text':'password'} className="neon-input w-full pr-10" value={credentials.password} onChange={e=>setCredentials(p=>({...p,password:e.target.value}))} required/><button type="button" onClick={()=>setShowPassword(v=>!v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted">{showPassword?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div></label><button disabled={isLoading} className="neon-button w-full py-2.5 text-xs">{isLoading?'جارٍ التحقق…':'دخول'}</button></form>:<form onSubmit={createFirst} className="space-y-3"><p className="text-[10px] leading-5 text-text-muted">يعمل مرة واحدة فقط عندما لا يوجد أي مستخدم. يتطلب NEXUS_ADMIN_PIN.</p><input className="neon-input w-full" placeholder="الاسم الكامل" value={firstAdmin.full_name} onChange={e=>setFirstAdmin(p=>({...p,full_name:e.target.value}))} required/><input className="neon-input w-full" placeholder="اسم المستخدم" value={firstAdmin.username} onChange={e=>setFirstAdmin(p=>({...p,username:e.target.value}))} required/><input className="neon-input w-full" placeholder="البريد - اختياري" value={firstAdmin.email} onChange={e=>setFirstAdmin(p=>({...p,email:e.target.value}))}/><input type="password" className="neon-input w-full" placeholder="كلمة مرور 10 أحرف على الأقل" value={firstAdmin.password} onChange={e=>setFirstAdmin(p=>({...p,password:e.target.value}))} required/><input type="password" className="neon-input w-full" placeholder="NEXUS_ADMIN_PIN" value={firstAdmin.admin_pin} onChange={e=>setFirstAdmin(p=>({...p,admin_pin:e.target.value}))} required/><button disabled={isLoading} className="neon-button w-full py-2.5 text-xs">إنشاء Super Administrator</button></form>}{error&&<div className="mt-4 border border-neon-red/30 bg-neon-red/10 p-2 text-[10px] text-neon-red">{error}</div>}</div></div></div>;
}
