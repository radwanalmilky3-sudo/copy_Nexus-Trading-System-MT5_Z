import { getAuthHeaders } from '@/lib/api-client';
import { withRequestTimeout } from '@/lib/request-timeout';
import type { BrokerAPI } from './types';
const BASE=(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000')+'/api/brokers';
function selectionKey():string{
  const token=(getAuthHeaders().Authorization||'').replace(/^Bearer\s+/,'');
  const payload=JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
  if(typeof payload.user_id!=='string')throw new Error('يلزم تسجيل الدخول');
  return 'nexus.broker-account.'+payload.user_id;
}
async function request<T>(path:string,method='GET',body?:unknown):Promise<T>{
  const headers=getAuthHeaders();
  if(!headers.Authorization)throw Object.assign(new Error('يلزم تسجيل الدخول'),{status:401});
  return withRequestTimeout(async signal=>{
    const res=await fetch(BASE+path,{method,signal,headers:{...headers,'Content-Type':'application/json'},
      ...(body===undefined?{}:{body:JSON.stringify(body)}),cache:'no-store'});
    if(!res.ok)throw Object.assign(new Error('تعذر تنفيذ طلب إعدادات الوسيط'),{status:res.status});
    return res.json() as Promise<T>;
  });
}
export const brokerAPI:BrokerAPI={
  rememberedAccount:()=>{try{return localStorage.getItem(selectionKey());}catch{return null;}},
  rememberAccount:id=>localStorage.setItem(selectionKey(),id),
  identity:()=>getAuthHeaders().Authorization || '',
  listProfiles:()=>request('/profiles'),
  createProfile:v=>request('/profiles','POST',v),
  createAccount:v=>request('/accounts','POST',v),
  getAccount:id=>request('/accounts/'+encodeURIComponent(id)),
  saveSettings:(id,version,settings)=>request('/accounts/'+encodeURIComponent(id)+'/settings','PUT',{expected_version:version,settings}),
  events:id=>request('/accounts/'+encodeURIComponent(id)+'/events'),
  listSymbols:id=>request<{symbols:import('./types').BrokerSymbol[]}>('/accounts/'+encodeURIComponent(id)+'/symbols').then(v=>v.symbols),
  syncSessions:id=>request('/accounts/'+encodeURIComponent(id)+'/sessions/sync','POST'),
};
