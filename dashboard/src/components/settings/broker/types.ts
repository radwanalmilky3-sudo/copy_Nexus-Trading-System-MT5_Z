export type AssetMode = 'disabled' | 'analysis' | 'trade';
export type AssetTimeframe = 'auto' | 'M1' | 'M5' | 'M15' | 'H1' | 'H4' | 'D1';
export interface TransitionDraft {
  from_offset_seconds: number | null; to_offset_seconds: number | null;
  session_start_date: string | null; effective_at_utc: string | null;
  during_market_closure: 'unknown' | 'yes' | 'no'; next_open_utc: string | null;
  support_reply: string; evidence_received_at: string | null;
}
export interface SessionObservation {server:string;broker_symbol:string;captured_at_utc:string;observed_offset_seconds:number;source:string;windows:{day:number;start_seconds:number;end_seconds:number}[]}
export interface AccountSettings { assets: {broker_symbol:string;mode:AssetMode;timeframe?:AssetTimeframe}[]; transition:TransitionDraft;session_observation?:SessionObservation|null;session_observations?:SessionObservation[]|null }
export interface SessionSync {account:BrokerAccount;imported:string[];skipped:string[];captured_at_utc:string;historical_authority:false}
export interface AccountCreate {profile_id:string;label:string;server:string;login:string;account_kind:'demo'|'live'}
export interface BrokerAccount {
  account_id:string;profile_id:string;label:string;server:string;masked_login:string;account_kind:'demo'|'live';
  version:number;settings:AccountSettings;updated_at:string;persistence:'durable';runtime_effective:false;connection_state:'unconnected';
}
export interface BrokerProfile {profile_id:string;name:string;broker_name:string;accounts:BrokerAccount[]}
export interface BrokerEvent {event_id:string;action:string;version:number;created_at:string;payload:unknown}
export interface BrokerSymbol {category:string;name:string;description:string;path?:string;visible?:boolean}
export interface BrokerAPI {
  rememberedAccount?():string|null;
  rememberAccount?(id:string):void;
  identity():string;listProfiles():Promise<BrokerProfile[]>;
  createProfile(value:{name:string;broker_name:string}):Promise<BrokerProfile>;
  createAccount(value:AccountCreate):Promise<BrokerAccount>;
  getAccount(id:string):Promise<BrokerAccount>;
  saveSettings(id:string,version:number,settings:AccountSettings):Promise<BrokerAccount>;
  events(id:string):Promise<BrokerEvent[]>;
  listSymbols?(id:string):Promise<BrokerSymbol[]>;
  syncSessions?(id:string):Promise<SessionSync>;
}
