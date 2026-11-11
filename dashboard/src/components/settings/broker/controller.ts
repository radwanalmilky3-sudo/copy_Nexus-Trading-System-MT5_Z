import type { AccountCreate, AccountSettings, AssetMode, AssetTimeframe, BrokerAPI, BrokerAccount, BrokerEvent, BrokerProfile, BrokerSymbol, TransitionDraft } from './types';
export type Section='accounts'|'connection'|'assets'|'timing'|'evidence';
export interface BrokerState {
  selectedProfileId:string;editor:'profile'|'account'|null;
  profiles:BrokerProfile[];account:BrokerAccount|null;draft:AccountSettings|null;latest:BrokerAccount|null;events:BrokerEvent[];
  loading:boolean;busy:boolean;error:string;notice:string;section:Section;dirty:boolean;conflict:boolean;
  symbols:BrokerSymbol[];symbolsLoading:boolean;connectionCheck:{accountId:string;ok:boolean;at:string}|null;
  /** Platform-env check (MT5_LOGIN/MT5_SERVER) — the single account of this
   * deployment; fills الحساب/الخادم/حالة الاتصال/آخر تحقق without any picker. */
  envCheck:{login:string;server:string;ok:boolean;at:string}|null;
  profileForm:{name:string;broker_name:string};accountForm:AccountCreate;
}
const initial=():BrokerState=>({selectedProfileId:'',editor:null,profiles:[],account:null,draft:null,latest:null,events:[],symbols:[],symbolsLoading:false,connectionCheck:null,envCheck:null,loading:false,busy:false,error:'',notice:'',section:'connection',dirty:false,conflict:false,
  profileForm:{name:'',broker_name:''},accountForm:{profile_id:'',label:'',server:'',login:'',account_kind:'demo'}});
function message(error:unknown):string{
  const code=(error as {status?:number})?.status;
  if(code===403)return 'ليست لديك صلاحية لهذا الإجراء.';
  if(code===401)return 'انتهت جلسة الدخول؛ سجّل الدخول مجددًا.';
  if(code===409)return 'تعارض: تغيّرت النسخة أو الحساب موجود مسبقًا. مدخلاتك باقية؛ استخدم مقارنة أحدث نسخة دون حذف مسودتك.';
  if(code===422)return 'راجع الحقول: استخدم توقيت UTC كاملًا، ورموزًا غير مكررة، ولا ترسل كلمات مرور.';
  return 'تعذر الوصول إلى إعدادات الوسيط. لم نؤكد الحفظ؛ أعد التحميل للتحقق قبل إعادة المحاولة.';
}
export function createBrokerController(api:BrokerAPI){
  let state=initial(),epoch=0,identity=api.identity();const listeners=new Set<()=>void>();
  const emit=(patch:Partial<BrokerState>)=>{state={...state,...patch};listeners.forEach(fn=>fn());};
  const checkIdentity=()=>{if(identity!==api.identity()){identity=api.identity();epoch++;state=initial();listeners.forEach(fn=>fn());return true;}return false;};
  const valid=(ticket:number)=>!checkIdentity()&&ticket===epoch;
  const accept=(account:BrokerAccount)=>emit({selectedProfileId:account.profile_id,account,draft:structuredClone(account.settings),latest:null,events:[],dirty:false,conflict:false,
    profiles:state.profiles.map(p=>p.profile_id===account.profile_id?{...p,accounts:[...p.accounts.filter(a=>a.account_id!==account.account_id),account]}:p)});
  const controller={
    getSnapshot:()=>state,subscribe:(fn:()=>void)=>{listeners.add(fn);return ()=>{listeners.delete(fn);};},checkIdentity,
    dispose:()=>{epoch++;listeners.clear();},
    async load(){checkIdentity();const ticket=++epoch;emit({loading:true,error:'',notice:'',account:null,draft:null,latest:null,events:[],dirty:false,conflict:false});
      try{const profiles=await api.listProfiles();if(valid(ticket)){const id=profiles.some(p=>p.profile_id===state.selectedProfileId)?state.selectedProfileId:profiles[0]?.profile_id||'';emit({profiles,selectedProfileId:id,accountForm:{...state.accountForm,profile_id:id}});
        /* Single-account deployment (owner request 2026-11-11): with exactly
         * one account in the store, select + remember it automatically so the
         * connection check runs on load and no broker/account pickers are
         * needed. Multi-account setups keep the remembered manual pick. */
        const all=profiles.flatMap(p=>p.accounts);
        const remembered=api.rememberedAccount?.();
        const target=remembered&&all.some(a=>a.account_id===remembered)?remembered:all.length===1?all[0].account_id:null;
        if(target){if(target!==remembered){try{api.rememberAccount?.(target);}catch{ /* storage blocked — selection still applies for this session */ }}await controller.selectAccount(target);}
        /* No saved account record (owner request 2026-11-11): the platform
         * env card IS the account, so verify MT5_LOGIN/MT5_SERVER directly —
         * the connection table then auto-fills with zero pickers. */
        else if(api.mt5Check){await controller.checkEnvConnection();}
      }}
      catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({loading:false,busy:false});}},
    async selectAccount(id:string){checkIdentity();const ticket=++epoch;emit({account:null,draft:null,latest:null,events:[],symbols:[],symbolsLoading:false,dirty:false,conflict:false,error:'',notice:'',loading:!!id,busy:false});
      if(!id)return;
      try{const account=await api.getAccount(id);if(!valid(ticket))return;accept(account);
        try{const events=await api.events(id);if(valid(ticket))emit({events});}catch{if(valid(ticket))emit({error:'تعذر تحميل سجل الحساب.'});}
        if(valid(ticket))await controller.checkConnection();}
      catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({loading:false});}},
    setSection:(section:Section)=>emit({section}),
    /** Read-only probe of MT5_LOGIN/MT5_SERVER from the platform env card.
     * Fills the connection table (الحساب/الخادم/حالة الاتصال/آخر تحقق) and the
     * symbol list without needing any per-account record or picker. */
    async checkEnvConnection(){if(checkIdentity()||state.symbolsLoading||!api.mt5Check)return;
      const ticket=epoch;emit({symbolsLoading:true,error:''});
      try{const r=await api.mt5Check();if(!valid(ticket))return;
        emit({envCheck:{login:r.login,server:r.server,ok:r.ok,at:new Date().toISOString()},
          symbols:r.ok?r.symbols:state.symbols,
          error:r.ok?'':'تعذر التحقق من اتصال MT5. تأكد من فتح المنصة على الحساب والخادم في بطاقة المنصة ثم أعد الفحص.'});}
      catch(e){if(valid(ticket))emit({envCheck:null,
        error:(e as {status?:number})?.status===409?'MT5_LOGIN و MT5_SERVER غير مضبوطين في بطاقة اتصال المنصة — أضِفهما ثم أعد الفحص.':'تعذر الوصول إلى فحص اتصال MT5. أعد المحاولة بعد تشغيل الواجهة الخلفية.'});}
      finally{if(valid(ticket))emit({symbolsLoading:false});}},
    async syncSessions(){if(checkIdentity()||!state.account||state.busy||state.dirty||!api.syncSessions)return;
      const ticket=epoch,id=state.account.account_id;emit({busy:true,error:'',notice:''});
      try{const result=await api.syncSessions(id);if(!valid(ticket))return;accept(result.account);
        emit({notice:`حُفظت جلسات ${result.imported.length} أصول. ${result.skipped.length?'تعذر استيراد: '+result.skipped.join('، '):'لا أخطاء في الأصول المختارة.'} جدول مرصود، وليس اعتمادًا للتوقيت التاريخي.`});
        const events=await api.events(id);if(valid(ticket))emit({events});
      }catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({busy:false});}},
    async rememberSelection(){if(checkIdentity()||!state.account||state.busy)return;
      if(state.dirty){await controller.save();if(state.dirty||state.error)return;}
      if(!state.account)return;
      try{api.rememberAccount?.(state.account.account_id);emit({notice:'حُفظ الحساب للعمل عليه تلقائيًا بعد التحديث أو إعادة فتح الموقع في هذا المتصفح.'});}
      catch{emit({error:'تعذر تذكر الحساب في هذا المتصفح؛ تحقق من السماح بالتخزين المحلي.'});}},
    async checkConnection(){if(checkIdentity()||!state.account||state.symbolsLoading||!api.listSymbols)return;
      const ticket=epoch,id=state.account.account_id;emit({symbolsLoading:true,connectionCheck:null,error:''});
      try{const symbols=await api.listSymbols(id);if(valid(ticket))emit({symbols,connectionCheck:{accountId:id,ok:true,at:new Date().toISOString()}});}
      catch{if(valid(ticket))emit({symbols:[],connectionCheck:{accountId:id,ok:false,at:new Date().toISOString()},error:'تعذر التحقق من حساب MT5. تأكد من فتح المنصة على الحساب والخادم المختارين.'});}
      finally{if(valid(ticket))emit({symbolsLoading:false});}},
    setEditor:(editor:BrokerState['editor'])=>emit({editor}),
    selectProfile(id:string){if(checkIdentity()||!state.profiles.some(p=>p.profile_id===id))return;epoch++;emit({selectedProfileId:id,account:null,draft:null,latest:null,events:[],dirty:false,conflict:false,loading:false,busy:false,error:'',notice:'',editor:null,accountForm:{...state.accountForm,profile_id:id}});},
    setProfileForm:(patch:Partial<BrokerState['profileForm']>)=>emit({profileForm:{...state.profileForm,...patch}}),
    setAccountForm:(patch:Partial<AccountCreate>)=>emit({accountForm:{...state.accountForm,...patch}}),
    async createProfile(){if(checkIdentity()||state.busy)return;const ticket=epoch,submitted={...state.profileForm};emit({busy:true,error:'',notice:''});
      try{const p=await api.createProfile(submitted);if(valid(ticket)){epoch++;emit({profiles:[...state.profiles,p],selectedProfileId:p.profile_id,editor:null,account:null,draft:null,latest:null,events:[],dirty:false,
        profileForm:state.profileForm.name===submitted.name&&state.profileForm.broker_name===submitted.broker_name?{name:'',broker_name:''}:state.profileForm,
        accountForm:{...state.accountForm,profile_id:p.profile_id},busy:false,notice:'تم حفظ ملف الوسيط الخاص بك.'});}}
      catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({busy:false});}},
    async createAccount(){if(checkIdentity()||state.busy)return;const ticket=epoch,submitted={...state.accountForm};emit({busy:true,error:'',notice:''});
      try{const a=await api.createAccount(submitted);if(valid(ticket)){accept(a);emit({accountForm:{...state.accountForm,
        login:state.accountForm.login===submitted.login?'':state.accountForm.login,label:state.accountForm.label===submitted.label?'':state.accountForm.label},editor:null,notice:'تم حفظ بيانات الحساب فقط؛ الاتصال والتنفيذ غير موصولين.'});}}
      catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({busy:false});}},
    patchTransition(patch:Partial<TransitionDraft>){if(state.draft&&!state.busy)emit({draft:{...state.draft,transition:{...state.draft.transition,...patch}},dirty:true,notice:''});},
    addAsset(symbol:string){symbol=symbol.trim();if(!state.draft||state.busy)return;
      if(!symbol||symbol.length>128||state.draft.assets.length>=256||state.draft.assets.some(a=>a.broker_symbol===symbol)){emit({error:'أدخل رمزًا فريدًا صالحًا؛ الحد 256 أصلًا.'});return;}
      emit({draft:{...state.draft,assets:[...state.draft.assets,{broker_symbol:symbol,mode:'disabled'}]},dirty:true,error:'',notice:''});},
    setAssetMode(symbol:string,mode:AssetMode){if(state.draft&&!state.busy)emit({draft:{...state.draft,assets:state.draft.assets.map(a=>a.broker_symbol===symbol?{...a,mode}:a)},dirty:true,notice:''});},
    setAssetTimeframe(symbol:string,timeframe:AssetTimeframe){if(state.draft&&!state.busy)emit({draft:{...state.draft,assets:state.draft.assets.map(a=>a.broker_symbol===symbol?{...a,timeframe}:a)},dirty:true,notice:''});},
    removeAsset(symbol:string){if(state.draft&&!state.busy)emit({draft:{...state.draft,assets:state.draft.assets.filter(a=>a.broker_symbol!==symbol)},dirty:true,notice:''});},
    /* Gold-correlation analysis pack (owner request 2026-11-06): the asset
     * set required alongside XAUUSD for correlated analysis. Only symbols
     * actually discovered from the owner's MT5 terminal are added — never
     * fabricated names — each as analysis-only; the batch is a single emit. */
    addGoldCorrelationPack(){if(checkIdentity()||!state.draft||state.busy)return;
      if(!state.symbols.length){emit({error:'تحقق من اتصال MT5 أولًا (تبويب الاتصال) حتى نطابق الحزمة على رموز وسيطك المتاحة فعلًا.'});return;}
      const available=new Map(state.symbols.map(sym=>[sym.name,sym]));
      const roles:{role:string;candidates:string[]}[]=[
        {role:'الذهب — الأساس',candidates:['XAUUSD']},
        {role:'الفضة',candidates:['XAGUSD','SILVER']},
        {role:'مؤشر الدولار',candidates:['DXY','USDX','USDIDX']},
        {role:'النفط',candidates:['USOIL','WTI','XTIUSD','USCRUDE']},
        {role:'اليورو/دولار',candidates:['EURUSD']},
        {role:'الدولار/ين',candidates:['USDJPY']},
        {role:'مؤشر S&P 500',candidates:['US500','SPX500']},
        {role:'النحاس',candidates:['XCUUSD','COPPER']},
        {role:'البلاتين',candidates:['XPTUSD']},
        {role:'البيتكوين',candidates:['BTCUSD']},
      ];
      const assets=[...state.draft.assets];const added:string[]=[];const missing:string[]=[];
      for(const {role,candidates} of roles){
        const hit=candidates.map(cand=>available.get(cand)).find(Boolean);
        if(!hit){missing.push(`${role} (${candidates.join('/')})`);continue;}
        if(assets.some(a=>a.broker_symbol===hit.name))continue;
        if(assets.length>=256)break;
        assets.push({broker_symbol:hit.name,mode:'analysis'});added.push(hit.name);
      }
      if(!added.length){emit({notice:missing.length?'لا رمز إضافيًا من حزمة ترابط الذهب: كل المتاح منها موجود في مسودتك، وغير المتاح لدى وسيطك: '+missing.join('؛ '):'حزمة ترابط الذهب موجودة بالكامل في مسودتك بالفعل.'});return;}
      emit({draft:{...state.draft,assets},dirty:true,error:'',
        notice:`أُضيفت ${added.length} أصلًا كـ«للتحليل فقط» (${added.join('، ')}).${missing.length?' غير متاح لدى وسيطك: '+missing.join('؛ '):''} راجع القائمة ثم احفظ صراحة.`});
    },
    fillSupport(){if(state.account?.server!=='OneRoyal-Demo')return;controller.patchTransition({from_offset_seconds:10800,to_offset_seconds:7200,session_start_date:'2026-11-02',effective_at_utc:null,during_market_closure:'yes',next_open_utc:null,evidence_received_at:null,
      support_reply:'بحسب رد دعم OneRoyal الذي نقله المستخدم: سيتم تغيير توقيت خادم OneRoyal-Demo من GMT+3 إلى GMT+2 أثناء إغلاق السوق، ويبدأ العمل بالتوقيت الجديد مع افتتاح جلسة الاثنين 2 نوفمبر 2026. ساعة التحويل الدقيقة غير محددة.'});},
    async compareLatest(){if(checkIdentity()||!state.account||state.busy)return;const ticket=epoch,id=state.account.account_id;emit({busy:true,error:'',notice:''});
      try{const latest=await api.getAccount(id);if(valid(ticket))emit({latest});}catch(e){if(valid(ticket))emit({error:message(e)});}finally{if(valid(ticket))emit({busy:false});}},
    keepLocalOnLatest(){if(checkIdentity()||!state.latest||state.busy)return;emit({account:state.latest,latest:null,dirty:true,error:'',notice:'احتفظت بمسودتك بعد المقارنة، مع تحديث رقم نسخة الأساس. راجع القيم ثم احفظ صراحة.'});},
    discardLocalForLatest(){if(checkIdentity()||!state.latest||state.busy)return;accept(state.latest);emit({error:'',notice:'استُبدلت المسودة المحلية بالنسخة المحفوظة التي اخترتها.'});},
    async save(){if(checkIdentity()||!state.account||!state.draft||state.busy)return;
      const ticket=epoch,a=state.account,payload=structuredClone(state.draft);emit({busy:true,error:'',notice:''});
      try{const saved=await api.saveSettings(a.account_id,a.version,payload);if(!valid(ticket))return;accept(saved);emit({notice:'تم الحفظ الدائم كمسودة خاصة بهذا الحساب؛ التنفيذ غير موصول.'});
        try{const events=await api.events(a.account_id);if(valid(ticket))emit({events});}catch{if(valid(ticket))emit({error:'حُفظت المسودة، لكن تعذر تحديث السجل.'});}}
      catch(e){if(valid(ticket))emit({error:message(e),conflict:(e as {status?:number})?.status===409});}finally{if(valid(ticket))emit({busy:false});}},
  };return controller;
}
export type BrokerController=ReturnType<typeof createBrokerController>;
