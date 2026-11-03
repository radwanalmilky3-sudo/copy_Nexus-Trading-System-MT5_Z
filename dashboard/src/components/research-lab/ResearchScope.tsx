'use client';
import {createContext,useContext,useState,type ReactNode} from 'react';
import type {BrokerAccount} from '../settings/broker/types';
function useScopeState(){
 const [account,setAccount]=useState(''),[symbol,setSymbol]=useState(''),[tf,setTf]=useState('M15');
 const [start,setStart]=useState(()=>new Date(Date.now()-7*86400000).toISOString().slice(0,10)),[end,setEnd]=useState(()=>new Date().toISOString().slice(0,10));
 const [accounts,setAccounts]=useState<BrokerAccount[]>([]),[symbols,setSymbols]=useState<string[]>([]),[revision,setRevision]=useState(0);
 return {account,setAccount,symbol,setSymbol,tf,setTf,start,setStart,end,setEnd,accounts,setAccounts,symbols,setSymbols,revision,setRevision};
}
const Scope=createContext<ReturnType<typeof useScopeState>|null>(null);
export function ResearchScopeProvider({children}:{children:ReactNode}){return <Scope.Provider value={useScopeState()}>{children}</Scope.Provider>;}
export function useResearchScope(){const scope=useContext(Scope);if(!scope)throw new Error('Missing research scope');return scope;}
export function ResearchScopeBar(){const s=useResearchScope();const input='min-w-0 rounded border border-border-primary bg-bg-primary p-2 text-xs';return <div className="grid grid-cols-2 gap-3 rounded-xl border border-border-primary bg-bg-secondary/30 p-3 sm:grid-cols-3 xl:grid-cols-5" aria-label="نطاق بيانات المختبر">{[
 <label key="account" className="col-span-2 flex flex-col gap-1 text-xs sm:col-span-1">الحساب<select className={input} value={s.account} onChange={e=>s.setAccount(e.target.value)}><option value="">اختر حسابًا</option>{s.accounts.map(a=><option key={a.account_id} value={a.account_id}>{a.label}</option>)}</select></label>,
 <label key="asset" className="flex flex-col gap-1 text-xs">الأصل<select className={input} value={s.symbol} onChange={e=>s.setSymbol(e.target.value)}><option value="">اختر أصلًا</option>{s.symbols.map(a=><option key={a}>{a}</option>)}</select></label>,
 <label key="tf" className="flex flex-col gap-1 text-xs">الإطار<select className={input} value={s.tf} onChange={e=>s.setTf(e.target.value)}>{['M1','M5','M15','M30','H1','H4','D1'].map(a=><option key={a}>{a}</option>)}</select></label>,
 <label key="start" className="flex flex-col gap-1 text-xs">من — وقت المصدر<input className={input} type="date" value={s.start} onChange={e=>s.setStart(e.target.value)}/></label>,
 <label key="end" className="flex flex-col gap-1 text-xs">إلى — وقت المصدر<input className={input} type="date" value={s.end} onChange={e=>s.setEnd(e.target.value)}/></label>
 ]}</div>;}
