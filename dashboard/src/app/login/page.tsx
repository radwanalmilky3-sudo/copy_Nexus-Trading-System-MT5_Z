'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Eye, EyeOff, Shield, UserPlus } from 'lucide-react';
import { withRequestTimeout } from '@/lib/request-timeout';

const API = process.env.NEXT_PUBLIC_API_URL || '';

// Map backend status codes to clear Arabic messages instead of raw JSON dumps.
const friendlyAuthError = async (res: Response): Promise<string> => {
  if (res.status === 409) return 'يوجد حساب مدير مسجل بالفعل في النظام — عد إلى تسجيل الدخول واستخدم بياناتك مباشرة.';
  if (res.status === 403) return 'الـ PIN غير صحيح. تأكد من قيمة NEXUS_ADMIN_PIN.';
  if (res.status === 422) return 'تحقق من الحقول: اسم المستخدم 3 أحرف على الأقل، وكلمة المرور 10 أحرف على الأقل.';
  if (res.status === 503) return 'إعدادات الخادم غير مكتملة (PIN أو JWT) — راجع ملف .env وأعد تشغيل الخدمات.';
  if (res.status === 401) return 'بيانات الدخول غير صحيحة: تحقق من اسم المستخدم وكلمة المرور.';
  try {
    const txt = await res.text();
    const detail = JSON.parse(txt)?.detail;
    return typeof detail === 'string' ? detail : txt;
  } catch { return `خطأ ${res.status}`; }
};

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
        if (!res.ok) throw new Error(await friendlyAuthError(res));
        return res.json();
      });
      localStorage.setItem('nexus-token', data.token); router.push('/nexus');
    } catch (e) { setError(e instanceof Error ? e.message : 'Authentication failed'); } finally { setIsLoading(false); }
  };
  const createFirst = async (e:React.FormEvent) => {
    e.preventDefault(); setIsLoading(true); setError('');
    try {
      await withRequestTimeout(async (signal) => {
        const res=await fetch(`${API}/api/v2/auth/bootstrap`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(firstAdmin),signal});
        if(!res.ok)throw new Error(await friendlyAuthError(res));
      });
      setCredentials({username:firstAdmin.username,password:firstAdmin.password}); setBootstrap(false); setError('تم إنشاء أول Super Administrator. سجّل الدخول الآن.');
    } catch(e){setError(e instanceof Error?e.message:'تعذر إنشاء الحساب');} finally{setIsLoading(false);}
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center p-4 overflow-hidden">
      {/* Yemen Smart backdrop — the banner itself, blurred, ties the page to the brand */}
      <div aria-hidden className="absolute inset-0 -z-10">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/brand/yemen-smart-banner.jpg" alt="" className="h-full w-full scale-110 object-cover opacity-25 blur-3xl" />
        <div className="absolute inset-0 bg-gradient-to-b from-bg-primary/70 via-bg-primary/45 to-bg-primary" />
      </div>

      <div className="w-full max-w-md space-y-5">
        {/* Brand plaque — the owner's Yemen Smart banner as the login logo */}
        <div className="relative text-center">
          <div className="mx-auto rounded-2xl bg-gradient-to-b from-amber-300/40 via-amber-500/15 to-transparent p-px shadow-[0_0_50px_-10px_rgba(245,158,11,0.55)]">
            <div className="relative overflow-hidden rounded-2xl">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="/brand/yemen-smart-banner-soft.jpg"
                alt="يمن سمارت — استثمار أذكى .. لمستقبل أفضل"
                className="w-full"
              />
              <div className="pointer-events-none absolute inset-0 rounded-2xl ring-1 ring-inset ring-amber-200/10" />
            </div>
          </div>
          <p className="mt-2.5 text-[9px] font-mono tracking-[0.35em] text-text-muted select-none" dir="ltr">
            POWERED BY NEXUS TRADER MT5
          </p>
        </div>

        <div className="neon-card p-7"><div className="mb-5 flex items-center justify-between"><div className="flex items-center gap-2"><Shield className="h-5 w-5 text-neon-purple"/><h2 className="font-semibold">{bootstrap?'تهيئة أول مدير':'تسجيل الدخول'}</h2></div><button onClick={()=>{setBootstrap(v=>!v);setError('')}} className="flex items-center gap-1 text-[10px] text-neon-cyan"><UserPlus className="h-3.5 w-3.5"/>{bootstrap?'عودة للدخول':'أول تشغيل'}</button></div>{!bootstrap?<form onSubmit={login} className="space-y-4"><label className="block text-xs">اسم المستخدم<input className="neon-input mt-1 w-full" value={credentials.username} onChange={e=>setCredentials(p=>({...p,username:e.target.value}))} required/></label><label className="block text-xs">كلمة المرور<div className="relative mt-1"><input type={showPassword?'text':'password'} className="neon-input w-full pr-10" value={credentials.password} onChange={e=>setCredentials(p=>({...p,password:e.target.value}))} required/><button type="button" onClick={()=>setShowPassword(v=>!v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-text-muted">{showPassword?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div></label><button disabled={isLoading} className="neon-button w-full py-2.5 text-xs">{isLoading?'جارٍ التحقق…':'دخول'}</button></form>:<form onSubmit={createFirst} className="space-y-3"><p className="text-[10px] leading-5 text-text-muted">يعمل مرة واحدة فقط عندما لا يوجد أي مستخدم. يتطلب NEXUS_ADMIN_PIN.</p><input className="neon-input w-full" placeholder="الاسم الكامل" value={firstAdmin.full_name} onChange={e=>setFirstAdmin(p=>({...p,full_name:e.target.value}))} required/><input className="neon-input w-full" placeholder="اسم المستخدم" value={firstAdmin.username} onChange={e=>setFirstAdmin(p=>({...p,username:e.target.value}))} required/><input className="neon-input w-full" placeholder="البريد - اختياري" value={firstAdmin.email} onChange={e=>setFirstAdmin(p=>({...p,email:e.target.value}))}/><input type="password" className="neon-input w-full" placeholder="كلمة مرور 10 أحرف على الأقل" value={firstAdmin.password} onChange={e=>setFirstAdmin(p=>({...p,password:e.target.value}))} required/><input type="password" className="neon-input w-full" placeholder="NEXUS_ADMIN_PIN" value={firstAdmin.admin_pin} onChange={e=>setFirstAdmin(p=>({...p,admin_pin:e.target.value}))} required/><button disabled={isLoading} className="neon-button w-full py-2.5 text-xs">إنشاء Super Administrator</button></form>}{error&&<div className="mt-4 border border-neon-red/30 bg-neon-red/10 p-2 text-[10px] text-neon-red">{error}</div>}</div>
      </div>
    </div>
  );
}
