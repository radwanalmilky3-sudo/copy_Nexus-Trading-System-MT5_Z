import * as React from 'react';
import { AssetDropDown } from './AssetDropDown';
import PlatformConnectionCard from './PlatformConnectionCard';
import SystemHealthStrip from './SystemHealthStrip';
import type { BrokerController, BrokerState, Section } from './controller';
import type { AssetMode, AssetTimeframe, TransitionDraft } from './types';

const input='w-full rounded border border-border-primary bg-bg-primary p-2 text-sm text-text-primary';
const button='rounded border border-border-primary px-3 py-2 text-sm hover:border-neon-cyan disabled:opacity-40';
const field=(label:string,control:React.ReactNode)=><label className="flex flex-col gap-1 text-sm">{label}{control}</label>;
const tableClass='w-full text-right text-sm [&_th]:bg-bg-secondary [&_th]:p-3 [&_td]:p-3 [&_tr]:border-b [&_tr]:border-border-primary';
const tabIcons:Record<Section,string>={
  accounts:'M3 7h18M5 7v14h14V7M8 3h8l2 4H6l2-4m1 8h6m-6 4h6',
  connection:'M8 12h8m-6-4 2-2 2 2m-4 8 2 2 2-2M6 20h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z',
  assets:'M4 7h16M4 12h16M4 17h16M7 7v10',
  timing:'M12 6v6l4 2m5-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  evidence:'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Zm3 4h5M8 11h7M8 15h5'
};
function TabIcon({section}:{section:Section}){return <svg aria-hidden="true" className="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={tabIcons[section]}/></svg>;}
function FieldTable({children,label}:{children:React.ReactNode;label:string}){
  return <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label={label}><thead><tr><th scope="col">الحقل</th><th scope="col">القيمة</th></tr></thead><tbody>{React.Children.toArray(children).map((child,index)=>{
    if(!React.isValidElement<{children:React.ReactNode[]}>(child))return null;
    const [name,control]=child.props.children;const id=`broker-field-${index}`;
    return <tr key={index}><th scope="row"><label htmlFor={id}>{name}</label></th><td>{React.isValidElement<{id?:string}>(control)?React.cloneElement(control,{id}):control}</td></tr>;
  })}</tbody></table></div>;
}
const utcValue=(v:string|null)=>v?v.replace(/Z$/,''):'';
const utcInput=(v:string)=>v?v+'Z':null;
const tabs:{id:Section;label:string}[]=[{id:'accounts',label:'الوسطاء والحسابات'},{id:'connection',label:'الاتصال'},{id:'assets',label:'الأصول'},{id:'timing',label:'الجلسات والتوقيت'},{id:'evidence',label:'الأدلة والسجل'}];

export function BrokerSettingsView({controller:c,state:s}:{controller:BrokerController;state:BrokerState}){
  const t=s.draft?.transition;
  const profile=s.profiles.find(p=>p.profile_id===s.selectedProfileId);
  const connection=s.connectionCheck?.accountId===s.account?.account_id?s.connectionCheck:null;
  const canLeave=()=>!s.dirty||window.confirm('لديك تعديلات غير محفوظة لهذا الحساب. هل تريد تجاهلها والمتابعة؟');
  const patch=(key:keyof TransitionDraft,value:unknown)=>c.patchTransition({[key]:value});
  return <section dir="rtl" className="mx-auto w-full max-w-[1400px] space-y-4 p-4 text-text-primary" aria-label="إعدادات الوسيط والحسابات">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-bold shrink-0">الوسيط والحسابات — حساب الموقع الحالي</h2>
      <p className="min-w-0 max-w-3xl flex-1 rounded border border-neon-gold/30 bg-neon-gold/5 px-3 py-1.5 text-xs">إعدادات مستخدم الموقع وحساب الوسيط المختار — حفظ دائم كمسودة، لا يربط MT5 ولا يفعّل التداول.</p>
    </div>
    <div className="flex items-end gap-3 overflow-x-auto rounded-lg border border-border-primary bg-bg-secondary/30 p-3">
      <label className="min-w-48 flex-1 space-y-2 text-sm">الوسيط المختار
        <select className={input} aria-label="الوسيط المختار" value={s.selectedProfileId} disabled={s.busy||s.loading} onChange={e=>{if(canLeave())c.selectProfile(e.target.value);}}>
          <option value="">اختر وسيطًا</option>{s.profiles.map(p=><option key={p.profile_id} value={p.profile_id}>{p.broker_name} · {p.name}</option>)}
        </select>
      </label>
      <label className="min-w-64 flex-[2] space-y-2 text-sm">حساب الوسيط المختار
        <select className={input} aria-label="حساب الوسيط المختار" value={s.account?.account_id||''} disabled={s.busy||s.loading} onChange={e=>{if(canLeave())void c.selectAccount(e.target.value);}}>
          <option value="">اختر حسابًا — لا يُختار حساب MT5 العام تلقائيًا</option>
          {s.profiles.filter(p=>p.profile_id===s.selectedProfileId).map(p=><optgroup key={p.profile_id} label={`${p.name} · ${p.broker_name}`}>
            {p.accounts.map(a=><option key={a.account_id} value={a.account_id}>{a.label} · {a.server} · {a.masked_login} · {a.account_kind==='demo'?'تجريبي':'حقيقي'}</option>)}
          </optgroup>)}
        </select>
      </label>
      <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
        <button type="button" className={`${button} border-neon-cyan bg-neon-cyan/10 font-semibold text-neon-cyan`} disabled={!s.account||s.loading||s.busy} onClick={()=>void c.rememberSelection()}>حفظ الحساب للعمل عليه</button>
        <button type="button" className={button} disabled={s.loading||s.busy} onClick={()=>{if(canLeave())void c.load();}}>تحديث القائمة</button>
      </div>
    </div>
    {s.loading&&<p role="status">جارٍ تحميل بيانات حسابك…</p>}
    {s.error&&<p role="alert" className="rounded border border-neon-red/40 p-3 text-sm">{s.error}</p>}
    {s.notice&&<p role="status" className="rounded border border-neon-green/40 p-3 text-sm">{s.notice}</p>}
    <nav className="flex gap-2 overflow-x-auto rounded-lg border border-border-primary bg-bg-secondary/30 p-2" aria-label="أقسام الوسيط">{tabs.map(tab=>{const active=s.section===tab.id;return <button key={tab.id} type="button" data-tab={tab.id} className={`${button} inline-flex min-h-12 flex-1 shrink-0 items-center justify-center gap-2 whitespace-nowrap transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan ${active?'border-neon-cyan bg-neon-cyan/15 font-semibold text-neon-cyan shadow-[0_0_12px_rgba(34,211,238,0.18)]':'text-text-muted'}`} aria-pressed={active} aria-current={active?'page':undefined} onClick={()=>c.setSection(tab.id)}><TabIcon section={tab.id}/><span>{tab.label}</span></button>;})}</nav>

    {s.section==='accounts'&&<div className="space-y-5">
      <div className="flex items-center justify-between"><h3 className="font-bold">الوسطاء الخاصون بحسابك</h3><button type="button" className={button} disabled={s.busy||s.loading} onClick={()=>{if(canLeave())c.setEditor('profile');}}>إضافة وسيط</button></div>
      <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label="جدول الوسطاء"><thead><tr><th scope="col">الوسيط</th><th scope="col">الاسم التعريفي</th><th scope="col">عدد الحسابات</th><th scope="col">الإجراء</th></tr></thead><tbody>
        {s.profiles.map(p=><tr key={p.profile_id} aria-selected={p.profile_id===s.selectedProfileId} className={p.profile_id===s.selectedProfileId?'bg-neon-cyan/10':''}><td>{p.broker_name}</td><td>{p.name}</td><td>{p.accounts.length}</td><td><button type="button" className={button} disabled={s.busy||s.loading} onClick={()=>{if(p.profile_id!==s.selectedProfileId&&canLeave())c.selectProfile(p.profile_id);}}>{p.profile_id===s.selectedProfileId?'الوسيط المختار':'عرض الحسابات'}</button></td></tr>)}
        {!s.profiles.length&&<tr><td colSpan={4}>لا يوجد وسيط محفوظ بعد. اضغط «إضافة وسيط» للبدء.</td></tr>}
      </tbody></table></div>
      <div className="flex items-center justify-between"><h3 className="font-bold">حسابات {profile?.broker_name||'الوسيط المختار'}</h3><button type="button" className={button} disabled={!profile||s.busy||s.loading} onClick={()=>{if(canLeave()){c.setAccountForm({profile_id:s.selectedProfileId});c.setEditor('account');}}}>إضافة حساب</button></div>
      <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label="جدول حسابات الوسيط"><thead><tr><th scope="col">اسم الحساب</th><th scope="col">الخادم</th><th scope="col">رقم الحساب</th><th scope="col">النوع</th><th scope="col">الإجراء</th></tr></thead><tbody>
        {profile?.accounts.map(a=><tr key={a.account_id} aria-selected={a.account_id===s.account?.account_id} className={a.account_id===s.account?.account_id?'bg-neon-cyan/10':''}><td>{a.label}</td><td dir="ltr">{a.server}</td><td dir="ltr">{a.masked_login}</td><td>{a.account_kind==='live'?'حقيقي':'تجريبي'}</td><td><button type="button" className={button} disabled={s.busy||s.loading} onClick={()=>{if(a.account_id!==s.account?.account_id&&canLeave())void c.selectAccount(a.account_id);}}>{a.account_id===s.account?.account_id?'الحساب المختار':'اختيار الحساب'}</button></td></tr>)}
        {!profile?.accounts.length&&<tr><td colSpan={5}>{profile?'لا توجد حسابات لهذا الوسيط. اضغط «إضافة حساب».':'اختر وسيطًا لعرض حساباته.'}</td></tr>}
      </tbody></table></div>
      {s.editor&&<div role="region" aria-label={s.editor==='profile'?'إضافة وسيط':'إضافة حساب'} className="rounded border border-neon-cyan/40 p-4"><div className="mb-3 flex justify-end"><button type="button" className={button} disabled={s.busy} onClick={()=>c.setEditor(null)}>إغلاق نموذج الإضافة</button></div>
      {s.editor==='profile'&&
      <form className="space-y-3 rounded border border-border-primary p-4" onSubmit={e=>{e.preventDefault();void c.createProfile();}}>
        <h3 className="font-bold">إضافة ملف وسيط خاص بك</h3>
        {field('الاسم التعريفي للوسيط',<input className={input} required maxLength={128} value={s.profileForm.name} onChange={e=>c.setProfileForm({name:e.target.value})}/>)}
        {field('اسم الوسيط',<input className={input} required maxLength={128} value={s.profileForm.broker_name} onChange={e=>c.setProfileForm({broker_name:e.target.value})}/>)}
        <button className={button} disabled={s.busy||s.loading} type="submit">حفظ ملف الوسيط</button>
      </form>}
      {s.editor==='account'&&
      <form className="space-y-3 rounded border border-border-primary p-4" onSubmit={e=>{e.preventDefault();void c.createAccount();}}>
        <h3 className="font-bold">إضافة بيانات حساب — دون تسجيل اتصال</h3>
        {field('الوسيط',<select className={input} required value={s.accountForm.profile_id} onChange={e=>c.setAccountForm({profile_id:e.target.value})}><option value="">اختر وسيطًا</option>{s.profiles.map(p=><option key={p.profile_id} value={p.profile_id}>{p.broker_name} · {p.name}</option>)}</select>)}
        {field('اسم الحساب',<input className={input} required maxLength={128} value={s.accountForm.label} onChange={e=>c.setAccountForm({label:e.target.value})}/>)}
        {field('اسم خادم الوسيط',<input className={input} required dir="ltr" maxLength={128} placeholder="OneRoyal-Demo" value={s.accountForm.server} onChange={e=>c.setAccountForm({server:e.target.value})}/>)}
        {field('رقم حساب الوسيط — بيانات تعريف فقط',<input className={input} required dir="ltr" inputMode="numeric" pattern="[0-9]{1,32}" maxLength={32} autoComplete="off" value={s.accountForm.login} onChange={e=>c.setAccountForm({login:e.target.value})}/>)}
        {field('نوع الحساب',<select className={input} value={s.accountForm.account_kind} onChange={e=>c.setAccountForm({account_kind:e.target.value as 'demo'|'live'})}><option value="demo">تجريبي</option><option value="live">حقيقي — لا يفعّل التداول الحقيقي</option></select>)}
        <p className="text-xs text-text-muted">لا تدخل كلمة مرور. الحسابات منفصلة حسب مستخدم الموقع، ولا نبدّل حساب المنصة الحالية.</p>
        <button className={button} disabled={s.busy||s.loading||!s.profiles.length} type="submit">حفظ بيانات الحساب</button>
      </form>}
      </div>}
    </div>}

    {s.section==='connection'&&<div className="space-y-4">
      <SystemHealthStrip />
      <PlatformConnectionCard />
      {!s.account&&!s.loading&&<div className="space-y-2 rounded border border-neon-gold/40 bg-neon-gold/5 p-4 text-sm">
        <p className="font-bold">لا يوجد حساب مختار بعد — ثلاث خطوات:</p>
        <ol className="list-decimal space-y-1 pr-5 text-text-secondary">
          <li>افتح قسم «الوسطاء والحسابات» واختر وسيطًا ثم حسابًا من جدوله.</li>
          <li>اضغط «حفظ الحساب للعمل عليه» في شريط الاختيار أعلى الصفحة.</li>
          <li>عد إلى تبويب «الاتصال» واضغط «التحقق من اتصال MT5».</li>
        </ol>
        <button type="button" className={`${button} border-neon-gold/50 font-semibold text-neon-gold`} onClick={()=>c.setSection('accounts')}>الانتقال إلى الوسطاء والحسابات</button>
      </div>}
      <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label="حالة اتصال الحساب"><thead><tr><th scope="col">الحساب</th><th scope="col">الخادم</th><th scope="col">حالة الاتصال</th><th scope="col">آخر تحقق UTC</th></tr></thead><tbody><tr><td>{s.account?.label||'اختر حسابًا'}</td><td dir="ltr">{s.account?.server||'—'}</td><td className={connection?.ok?'text-neon-green':'text-neon-gold'}>{s.symbolsLoading?'جارٍ التحقق…':connection?.ok?'نجح اتصال القراءة — الحساب والخادم متطابقان':connection?'تعذر التحقق من الاتصال':s.account?'جاهز للفحص — اضغط الزر أدناه':'لم يُفحص بعد'}</td><td dir="ltr">{connection?.at||'—'}</td></tr></tbody></table></div>
      <p>يفحص الموقع الحساب والخادم في منصة MT5 المفتوحة ويقرأ قائمة الأصول. النتيجة تعبّر عن وقت الفحص الموضح، والتداول الآلي غير مفعّل.</p>
      <button type="button" className={button} disabled={!s.account||s.loading||s.symbolsLoading||s.busy} onClick={()=>void c.checkConnection()}>{s.symbolsLoading?'جارٍ الفحص…':'التحقق من اتصال MT5'}</button>
    </div>}
    {['assets','timing','evidence'].includes(s.section)&&!s.account&&!s.loading&&<p>اختر حسابًا أو أنشئ بيانات حسابك أولًا.</p>}

    {s.section==='assets'&&s.draft&&<fieldset disabled={s.busy||s.loading} className="space-y-3">
      <legend className="font-bold">أصول الحساب</legend>
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-sm text-text-muted">ابحث عن الأصل واختره، ثم حدّد استخدامه في القائمة أدناه.</p>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={`${button} border-neon-gold bg-neon-gold/10 font-semibold text-neon-gold`} title="يضيف تلقائيًا الأصول المرتبطة بالذهب المكتشفة فعلًا في MT5 (الفضة، مؤشر الدولار، النفط، EURUSD، USDJPY، US500، النحاس، البلاتين، البيتكوين) بوضع «للتحليل فقط»" disabled={s.busy||s.loading||!s.symbols.length} onClick={()=>c.addGoldCorrelationPack()}>إضافة حزمة ترابط الذهب</button>
          <span className="rounded border border-border-primary px-3 py-1 text-xs">{s.draft.assets.length} مختار · {connection?.ok?s.symbols.length+' متاح من MT5':'بانتظار التحقق من MT5'}</span>
        </div>
      </div>
      <AssetDropDown key={s.account?.account_id} symbols={s.symbols} loading={s.symbolsLoading} selected={s.draft.assets.map(a=>a.broker_symbol)} onToggle={name=>s.draft!.assets.some(a=>a.broker_symbol===name)?c.removeAsset(name):c.addAsset(name)} onClear={()=>s.draft!.assets.forEach(a=>c.removeAsset(a.broker_symbol))}/>
      <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label="جدول أصول الحساب"><thead><tr><th scope="col">الأصل المختار</th><th scope="col">الاستخدام</th><th scope="col">الفريم</th><th scope="col">المصدر</th><th scope="col"><span className="sr-only">الإجراء</span></th></tr></thead><tbody>
        {s.draft.assets.map(a=>{const symbol=connection?.ok?s.symbols.find(row=>row.name===a.broker_symbol):undefined;return <tr key={a.broker_symbol}><td><div dir="ltr" className="font-mono font-semibold">{a.broker_symbol}</div>{symbol&&<div className="mt-1 text-xs text-text-muted">{symbol.category} · {symbol.description}</div>}</td><td><select className={input} aria-label={`تفضيل ${a.broker_symbol}`} value={a.mode} onChange={e=>c.setAssetMode(a.broker_symbol,e.target.value as AssetMode)}><option value="disabled">معطل</option><option value="analysis">للتحليل فقط</option><option value="trade">تفضيل التداول</option></select></td><td><select className={input} aria-label={`فريم ${a.broker_symbol}`} value={a.timeframe??'auto'} onChange={e=>c.setAssetTimeframe(a.broker_symbol,e.target.value as AssetTimeframe)}><option value="auto">افتراضي النظام (تلقائي)</option><option value="M1">M1</option><option value="M5">M5</option><option value="M15">M15</option><option value="H1">H1</option><option value="H4">H4</option><option value="D1">D1</option></select></td><td className="text-xs">{symbol?'موجود في MT5':'غير متحقق حاليًا'}</td><td><button type="button" className={button} aria-label={`إزالة ${a.broker_symbol}`} onClick={()=>c.removeAsset(a.broker_symbol)}>إزالة</button></td></tr>;})}
        {!s.draft.assets.length&&<tr><td colSpan={5} className="text-center text-text-muted">ابدأ باختيار أصل من القائمة أعلاه.</td></tr>}
      </tbody></table></div>
      <p className="text-xs text-text-muted">معنيات الاستخدام: «معطل» = الرمز محفوظ في إعدادات الحساب فقط، لا يدخل التحليل ولا يُسجَّل كتفضيل تداول. «للتحليل فقط» = يدخل البحث والتحليل ولا يمنح صلاحية تداول. «تفضيل التداول» = تفضيل عرض فقط ولا يفعّل التداول؛ التنفيذ يبقى معطّلًا. الفريم: «افتراضي النظام (تلقائي)» يتبع اختيار الجلسة التلقائي للنظام؛ القيم الثابتة (M1…D1) تثبّت هذا الأصل على فريم واحد. نطاق الحفظ: مسودة إعدادات حساب واحد فقط (الأصول والجلسات والانتقال معًا)؛ نماذج إضافة الوسيط والحساب مستقلة ولا تُحفظ ضمن هذه المسودة.</p>
    </fieldset>}

    {s.section==='timing'&&t&&<fieldset disabled={s.busy||s.loading} className="space-y-4">
      <legend className="font-bold">الجلسات والتوقيت — مسودة خاصة بالحساب</legend>
      <button type="button" className={button} disabled={!s.account||s.busy||s.loading||s.dirty} onClick={()=>void c.syncSessions()}>مزامنة جلسات الأصول من MT5</button>
      {s.dirty&&<p className="text-xs text-neon-gold">احفظ تعديلاتك قبل المزامنة حتى لا تُستبدل المسودة.</p>}
      {(s.draft?.session_observations??(s.draft?.session_observation?[s.draft.session_observation]:[])).map(observation=><div key={observation.broker_symbol} className="space-y-2 rounded border border-border-primary p-3">
        <h3 className="font-semibold">جلسات {observation.broker_symbol}</h3>
        <p className="text-xs">{observation.server} · التصدير UTC: {observation.captured_at_utc} · فرق مرصود UTC{observation.observed_offset_seconds>=0?'+':''}{observation.observed_offset_seconds/3600}</p>
        <table className={tableClass} aria-label={`جلسات ${observation.broker_symbol}`}><thead><tr><th>اليوم</th><th>الافتتاح — وقت الخادم</th><th>الإغلاق — وقت الخادم</th></tr></thead><tbody>{['الأحد','الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت'].map((day,index)=>{const windows=observation.windows.filter(w=>w.day===index);const time=(seconds:number)=>`${String(Math.floor(seconds/3600)).padStart(2,'0')}:${String(Math.floor(seconds%3600/60)).padStart(2,'0')}`;return windows.length?windows.map((w,i)=><tr key={`${index}-${i}`}><td>{day}</td><td dir="ltr">{time(w.start_seconds)}</td><td dir="ltr">{time(w.end_seconds)}</td></tr>):<tr key={index}><td>{day}</td><td colSpan={2}>لا جلسات بحسب التصدير الأسبوعي</td></tr>;})}</tbody></table>
      </div>)}
      <p className="text-sm">الجلسات المرصودة مرتبطة بفحص فواصل كل أصل. مطابقة الإغلاق الأسبوعي استرشادية؛ العطلات والتوقيت التاريخي يحتاجان دليلًا مؤرخًا، ولا نعدّل أسعار الشموع.</p>
      {s.account?.server==='OneRoyal-Demo'&&<button className={button} type="button" onClick={()=>c.fillSupport()}>تعبئة مسودة رد OneRoyal</button>}
      <FieldTable label="جدول الجلسات والتوقيت">
        {field('فرق التوقيت السابق عن UTC (بالساعات)',<input className={input} dir="ltr" type="number" min={-14} max={14} step="any" value={t.from_offset_seconds===null?'':t.from_offset_seconds/3600} onChange={e=>patch('from_offset_seconds',e.target.value===''?null:Math.round(Number(e.target.value)*3600))}/>)}
        {field('فرق التوقيت الجديد عن UTC (بالساعات)',<input className={input} dir="ltr" type="number" min={-14} max={14} step="any" value={t.to_offset_seconds===null?'':t.to_offset_seconds/3600} onChange={e=>patch('to_offset_seconds',e.target.value===''?null:Math.round(Number(e.target.value)*3600))}/>)}
        {field('تاريخ الجلسة التي يبدأ فيها التوقيت الجديد — ليس ساعة تحويل',<input className={input} type="date" value={t.session_start_date||''} onChange={e=>patch('session_start_date',e.target.value||null)}/>)}
        {field('هل يتغير توقيت الخادم أثناء إغلاق السوق؟',<select className={input} value={t.during_market_closure} onChange={e=>patch('during_market_closure',e.target.value)}><option value="unknown">غير معروف</option><option value="yes">نعم — أكدها الدعم</option><option value="no">لا</option></select>)}
        {field('تاريخ وساعة التحويل الدقيقة — UTC فقط',<input className={input} type="datetime-local" step={1} value={utcValue(t.effective_at_utc)} onChange={e=>patch('effective_at_utc',utcInput(e.target.value))}/>)}
        {field('وقت افتتاح الجلسة التالي — UTC فقط (اختياري)',<input className={input} type="datetime-local" step={1} value={utcValue(t.next_open_utc)} onChange={e=>patch('next_open_utc',utcInput(e.target.value))}/>)}
        {field('وقت استلام تأكيد الدعم — UTC (اختياري)',<input className={input} type="datetime-local" step={1} value={utcValue(t.evidence_received_at)} onChange={e=>patch('evidence_received_at',utcInput(e.target.value))}/>)}
      </FieldTable>
      <p className="text-sm text-neon-gold">ساعة التحويل: {t.effective_at_utc||'غير محددة'}. الحقول الموسومة UTC لا تستخدم توقيت جهازك المحلي؛ لا نفترض منتصف الليل.</p>
      {field('نص تأكيد الدعم وملاحظاتك',<textarea className={input} rows={6} maxLength={8000} value={t.support_reply} onChange={e=>patch('support_reply',e.target.value)}/>)}
      <button type="button" className={button} onClick={()=>{
        const question=`بالنسبة لخادم MT5 ${s.account?.server}، في أي تاريخ وساعة بالتوقيت العالمي UTC يحدث تغيير التوقيت؟ وهل يتم أثناء إغلاق السوق قبل افتتاح الجلسة التالية؟`;
        void navigator.clipboard.writeText(question).catch(()=>window.alert('تعذر النسخ؛ انسخ السؤال يدويًا: '+question));
      }}>نسخ سؤال الدعم</button>
    </fieldset>}

    {s.section==='evidence'&&s.account&&<div className="space-y-3">
      <h3>سجل الحساب — آخر 100 تعديل</h3><p className="text-sm">أوقات السجل UTC. رفع الصور واستخراج الجداول غير متاحين بعد؛ نص الدعم المحفوظ ليس تحققًا مستقلًا من مصدره.</p>
      <button className={button} type="button" disabled>اختيار صورة من الجهاز — مرحلة لاحقة</button>
      <div className="overflow-x-auto rounded border border-border-primary"><table className={tableClass} aria-label="جدول الأدلة والسجل"><thead><tr><th scope="col">التاريخ UTC</th><th scope="col">التعديل</th><th scope="col">النسخة</th><th scope="col">التفاصيل</th></tr></thead><tbody>{s.events.map(e=><tr key={e.event_id}><td dir="ltr">{e.created_at}</td><td>{e.action}</td><td>{e.version}</td><td><details><summary>عرض النسخة المحفوظة</summary><pre dir="ltr" className="max-h-64 max-w-lg overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(e.payload,null,2)}</pre></details></td></tr>)}{!s.events.length&&<tr><td colSpan={4}>لا توجد أحداث محملة.</td></tr>}</tbody></table></div>
    </div>}

    {s.account&&s.draft&&<div className="flex flex-wrap items-center gap-3 border-t border-border-primary pt-4">
      <button type="button" className={button} disabled={s.busy||s.loading} onClick={()=>void c.compareLatest()}>مقارنة أحدث نسخة دون حذف مسودتي</button>
      {s.latest&&<div className="w-full space-y-2 rounded border border-neon-gold/40 p-3">
        <p>نسختك الأساسية {s.account.version}، وأحدث نسخة {s.latest.version}. راجع الاختلافات قبل اختيار ما تحتفظ به.</p>
        <div className="grid gap-3 md:grid-cols-2"><div><h4>مسودتي المحلية</h4><pre dir="ltr" className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(s.draft,null,2)}</pre></div><div><h4>أحدث نسخة محفوظة</h4><pre dir="ltr" className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(s.latest.settings,null,2)}</pre></div></div>
        <button type="button" className={button} onClick={()=>c.keepLocalOnLatest()}>أحتفظ بمسودتي بعد المقارنة — لا حفظ تلقائي</button>
        <button type="button" className={button} onClick={()=>c.discardLocalForLatest()}>أتجاهل مسودتي وأختار النسخة المحفوظة</button>
      </div>}
      <button type="button" className={button} disabled={s.busy||s.loading||!s.dirty} onClick={()=>void c.save()}>{s.busy?'جارٍ الحفظ…':'حفظ مسودة إعدادات الحساب'}</button>
      <button type="button" className={button} disabled={s.busy||s.loading} onClick={()=>{if(canLeave())void c.selectAccount(s.account!.account_id);}}>إعادة تحميل الحساب وإلغاء التعديلات المحلية</button>
      <span className="text-sm">نسخة {s.account.version} · {s.dirty?'تعديلات غير محفوظة':'مسودة محفوظة'} · التنفيذ غير موصول</span>
      {s.conflict&&<span role="alert" className="rounded border border-red-400/50 bg-red-400/10 px-3 py-1 text-xs font-semibold text-red-300">تعارض نسخة — تغيّرت النسخة على الخادم؛ راجع المقارنة قبل الحفظ</span>}
      <p className="w-full text-xs text-text-muted">تبديل الحساب أو إعادة التحميل يلغي التعديلات المحلية غير المحفوظة. بعد أي تعديل يلزم الحفظ؛ لا اعتماد أو تفعيل تلقائي.</p>
    </div>}
  </section>;
}
