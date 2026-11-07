'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, BellRing, CheckCircle2, Radio, Volume2, VolumeX } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { NewsTickerItemDTO, NewsTickerSettingsDTO, TickerSeverity } from '@/types/fundamental';

const MUTE_UNTIL_KEY = 'nexus.newsTicker.muteUntil';
const DELIVERED_KEY = 'nexus.newsTicker.delivered.v1';
const rank: Record<TickerSeverity, number> = { low: 1, medium: 2, high: 3, critical: 4 };
const severityClass: Record<TickerSeverity, string> = {
  low: 'border-sky-200 bg-sky-50 text-sky-950', medium: 'border-blue-300 bg-blue-50 text-blue-950',
  high: 'border-amber-300 bg-amber-50 text-amber-950', critical: 'border-red-300 bg-red-50 text-red-950',
};
const badgeClass: Record<TickerSeverity, string> = {
  low: 'bg-sky-100 text-sky-800', medium: 'bg-blue-100 text-blue-800', high: 'bg-amber-100 text-amber-900', critical: 'bg-red-100 text-red-800',
};

function directionClass(direction?: string) {
  if (direction === 'bullish') return 'bg-emerald-100 text-emerald-800 border-emerald-300';
  if (direction === 'bearish') return 'bg-red-100 text-red-800 border-red-300';
  if (direction === 'conflicted') return 'bg-amber-100 text-amber-900 border-amber-300';
  return 'bg-sky-100 text-sky-800 border-sky-300';
}
function directionAr(direction?: string) { return direction === 'bullish' ? 'صاعد' : direction === 'bearish' ? 'هابط' : direction === 'conflicted' ? 'متعارض' : direction === 'neutral' ? 'محايد' : 'غير محدد'; }
function shortSpeech(item: NewsTickerItemDTO): string {
  const prefix = item.severity === 'critical' ? 'تنبيه حرج.' : 'خبر مهم.';
  const asset = item.asset_id ? `الأصل ${item.asset_id}.` : '';
  const direction = item.direction && item.direction !== 'unknown' ? `الأثر الأولي ${directionAr(item.direction)}.` : '';
  const blackout = item.blackout_state && item.blackout_state !== 'clear' ? 'حظر الأخبار نشط.' : '';
  const raw = `${prefix} ${asset} ${item.headline_ar}. ${direction} ${blackout}`.replace(/\s+/g, ' ').trim();
  return raw.length > 180 ? `${raw.slice(0, 177)}…` : raw;
}
function isQuiet(settings: NewsTickerSettingsDTO): boolean {
  if (!settings.quiet_hours_enabled) return false;
  const now = new Date(); const minutes = now.getHours() * 60 + now.getMinutes();
  const parse = (v: string) => { const [h,m] = v.split(':').map(Number); return h*60+m; };
  const start = parse(settings.quiet_hours_start), end = parse(settings.quiet_hours_end);
  return start <= end ? minutes >= start && minutes < end : minutes >= start || minutes < end;
}
function topicDomain(topic?: string | null): string {
  if (!topic) return 'news';
  if (['inflation','labor','growth'].includes(topic)) return 'macro';
  if (topic === 'monetary') return 'monetary';
  if (['rates_yields','fx','energy','equities'].includes(topic)) return 'cross_asset';
  if (topic === 'geopolitics') return 'geopolitical';
  return 'news';
}
function ageMinutes(item: NewsTickerItemDTO): number | null {
  const raw = item.published_at ?? item.received_at ?? item.starts_at;
  if (!raw) return null;
  const t = new Date(raw).getTime();
  return Number.isFinite(t) ? Math.max(0, (Date.now()-t)/60_000) : null;
}
function ttlSeconds(settings: NewsTickerSettingsDTO, item: NewsTickerItemDTO): number {
  if (item.severity === 'critical') return settings.critical_ttl_seconds ?? 0;
  if (item.severity === 'high') return settings.high_ttl_seconds ?? 600;
  if (item.severity === 'medium') return settings.medium_ttl_seconds ?? 300;
  return settings.low_ttl_seconds ?? 120;
}

export default function NewsTickerBar() {
  const [items, setItems] = useState<NewsTickerItemDTO[]>([]);
  const [settings, setSettings] = useState<NewsTickerSettingsDTO | null>(null);
  const [muteUntil, setMuteUntil] = useState(0);
  const [ttsHardLimitSeconds, setTtsHardLimitSeconds] = useState(18);
  const delivered = useRef<Map<string, number>>(new Map());
  const acknowledgedIds = useRef<Set<string>>(new Set());
  const repeatTimers = useRef<Map<string, number>>(new Map());
  const lastSpeechAt = useRef(0);

  useEffect(() => {
    try {
      setMuteUntil(Number(localStorage.getItem(MUTE_UNTIL_KEY) || '0'));
      const raw = sessionStorage.getItem(DELIVERED_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          delivered.current = new Map(
            Object.entries(parsed).flatMap(([k, v]) => {
              const timestamp = Number(v);
              return Number.isFinite(timestamp) ? [[k, timestamp] as const] : [];
            }),
          );
        }
      }
    } catch {}
    const handler = (e: Event) => setMuteUntil(Number((e as CustomEvent<{until:number}>).detail?.until || 0));
    window.addEventListener('nexus-news-ticker-mute-change', handler);
    return () => window.removeEventListener('nexus-news-ticker-mute-change', handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try { const res = await apiClient.getNewsTicker(); if (!cancelled) {
        const next = res.data.items ?? []; setItems(next); setSettings(res.data.settings);
        setTtsHardLimitSeconds(Math.min(18, Math.max(1, res.data.tts_hard_limit_seconds || 18)));
        acknowledgedIds.current = new Set(next.filter((x)=>Boolean(x.acknowledged)).map((x)=>x.ticker_item_id));
      } }
      catch { /* keep last real snapshot; never fabricate */ }
    };
    load(); const id = window.setInterval(load, 7_500);
    return () => { cancelled = true; window.clearInterval(id); repeatTimers.current.forEach((t)=>window.clearTimeout(t)); repeatTimers.current.clear(); };
  }, []);

  const filtered = useMemo(() => {
    if (!settings) return [];
    const min = rank[settings.minimum_severity] ?? 2;
    return items.filter((item) => {
      if ((rank[item.severity ?? 'low'] ?? 0) < min) return false;
      if (settings.assets.length && item.asset_id && !settings.assets.includes(item.asset_id)) return false;
      if (settings.domains.length && !settings.domains.includes(topicDomain(item.topic))) return false;
      if ((item.asset_relevance ?? 100) < settings.minimum_relevance) return false;
      if ((item.data_quality ?? 0) < settings.minimum_source_quality) return false;
      if (item.status === 'EXPIRED' || item.status === 'SUPERSEDED') return false;
      if (item.status === 'SCHEDULED' && !settings.show_scheduled) return false;
      if (item.status === 'BREAKING' && !settings.show_breaking) return false;
      if (item.acknowledged && settings.hide_after_ack && !settings.show_acknowledged) return false;
      const age = ageMinutes(item);
      const ttl = ttlSeconds(settings, item);
      if (age != null && ttl > 0 && age * 60 > ttl && item.status !== 'SCHEDULED') return false;
      if (age != null && age > settings.max_news_age_minutes && item.status !== 'SCHEDULED' && ttl <= 0) return false;
      return true;
    }).sort((a,b) => (rank[b.severity]??0)-(rank[a.severity]??0));
  }, [items, settings]);

  useEffect(() => {
    const userMuteUntil = settings?.mute_until ? new Date(settings.mute_until).getTime() : 0;
    const muted = Math.max(muteUntil, Number.isFinite(userMuteUntil) ? userMuteUntil : 0) > Date.now();
    if (!settings?.audio_enabled || muted || isQuiet(settings) || !('speechSynthesis' in window)) return;
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) return;
    if (Date.now() - lastSpeechAt.current < settings.cooldown_seconds * 1000) return;

    const item = filtered.find((x) => {
      if ((delivered.current.get(x.ticker_item_id) ?? 0) !== 0) return false;
      if (x.acknowledged || acknowledgedIds.current.has(x.ticker_item_id)) return false;
      if (x.status === 'SCHEDULED') {
        if (!settings.blackout_alerts || !x.published_at) return false;
        const delta = (new Date(x.published_at).getTime() - Date.now()) / 60_000;
        return delta > 0 && delta <= 5;
      }
      return ['BREAKING','ANALYZING','ANALYZED','UPDATED'].includes(x.status);
    });
    if (!item) return;
    if (settings.verified_source_only_voice && (!item.source_id || (item.data_quality ?? 0) < settings.minimum_source_quality)) return;
    if (settings.two_source_geopolitical_voice && item.topic === 'geopolitics' && (item.independent_source_count ?? 1) < 2) return;
    const allowed = item.severity === 'critical' ? settings.critical_audio : item.severity === 'high' ? settings.high_audio : item.severity === 'medium' ? settings.medium_audio : false;
    if (!allowed) { delivered.current.set(item.ticker_item_id, 1); return; }

    const speak = (target: NewsTickerItemDTO, repeatIndex: number) => {
      if (muteUntil > Date.now()) return;
      const utterance = new SpeechSynthesisUtterance(shortSpeech(target));
      utterance.lang = settings.language === 'ar' ? 'ar-SA' : 'en-US'; utterance.volume = settings.volume; utterance.rate = settings.speech_rate;
      const voices = window.speechSynthesis.getVoices();
      const preferred = voices.find((v) => settings.voice && settings.voice !== 'system_arabic' && v.name === settings.voice) ?? voices.find((v) => v.lang.toLowerCase().startsWith(settings.language === 'ar' ? 'ar' : 'en'));
      if (preferred) utterance.voice = preferred;
      const started = new Date(); lastSpeechAt.current = Date.now();
      let logged = false;
      const hardLimitMs = Math.min(18, Math.max(1, ttsHardLimitSeconds)) * 1000;
      const hardStop = window.setTimeout(() => {
        if (logged) return; logged = true; window.speechSynthesis.cancel(); const finished = new Date(); lastSpeechAt.current = Date.now();
        void apiClient.logTickerDelivery({ ticker_item_id: target.ticker_item_id, channel:'tts', reason:'tts_hard_limit', language:settings.language, voice_id:preferred?.name ?? 'system', started_at:started.toISOString(), finished_at:finished.toISOString(), duration_ms:Math.min(hardLimitMs, finished.getTime()-started.getTime()), repeat_index:repeatIndex, acknowledged_before_send:Boolean(target.acknowledged || acknowledgedIds.current.has(target.ticker_item_id)), result:'cancelled', error:'TTS_HARD_LIMIT_18S' }).catch(()=>undefined);
      }, hardLimitMs);
      window.speechSynthesis.speak(utterance);
      utterance.onend = () => { if (logged) return; logged = true; window.clearTimeout(hardStop); const finished = new Date(); lastSpeechAt.current = Date.now(); void apiClient.logTickerDelivery({ ticker_item_id: target.ticker_item_id, channel:'tts', reason: repeatIndex ? 'ticker_repeat':'ticker_alert', language:settings.language, voice_id:preferred?.name ?? 'system', started_at:started.toISOString(), finished_at:finished.toISOString(), duration_ms:Math.min(hardLimitMs, finished.getTime()-started.getTime()), repeat_index:repeatIndex, acknowledged_before_send:Boolean(target.acknowledged || acknowledgedIds.current.has(target.ticker_item_id)), result:'delivered', error:null }).catch(()=>undefined); };
      utterance.onerror = () => { if (logged) return; logged = true; window.clearTimeout(hardStop); lastSpeechAt.current = Date.now(); void apiClient.logTickerDelivery({ ticker_item_id: target.ticker_item_id, channel:'tts', reason:'speech_error', language:settings.language, repeat_index:repeatIndex, result:'failed', error:'browser_speech_error' }).catch(()=>undefined); };
    };

    delivered.current.set(item.ticker_item_id, 1);
    try { sessionStorage.setItem(DELIVERED_KEY, JSON.stringify(Object.fromEntries(delivered.current))); } catch {}
    speak(item, 0);
    const repeatCount = item.severity === 'critical' ? settings.critical_repeat_count : item.severity === 'high' ? settings.high_repeat_count : 0;
    if (repeatCount > 0 && !item.acknowledged) {
      const timer = window.setTimeout(() => {
        if (!item.acknowledged && !acknowledgedIds.current.has(item.ticker_item_id) && muteUntil <= Date.now() && !window.speechSynthesis.speaking) {
          speak(item, 1); delivered.current.set(item.ticker_item_id, 2);
          try { sessionStorage.setItem(DELIVERED_KEY, JSON.stringify(Object.fromEntries(delivered.current))); } catch {}
        }
        repeatTimers.current.delete(item.ticker_item_id);
      }, settings.repeat_delay_seconds * 1000);
      repeatTimers.current.set(item.ticker_item_id, timer);
    }
  }, [filtered, settings, muteUntil, ttsHardLimitSeconds]);

  const acknowledge = async (tickerItemId: string) => {
    acknowledgedIds.current.add(tickerItemId);
    const timer = repeatTimers.current.get(tickerItemId); if (timer) window.clearTimeout(timer); repeatTimers.current.delete(tickerItemId);
    setItems((prev)=>prev.map((x)=>x.ticker_item_id===tickerItemId?{...x,acknowledged:true,acknowledged_at:new Date().toISOString()}:x));
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    try { await apiClient.acknowledgeTickerItem(tickerItemId, true); } catch { /* keep local ack; next poll reconciles server truth */ }
  };

  const toggleSessionMute = () => {
    const until = muteUntil > Date.now() ? 0 : Date.now() + 24*60*60*1000;
    setMuteUntil(until); try { if (until) localStorage.setItem(MUTE_UNTIL_KEY,String(until)); else localStorage.removeItem(MUTE_UNTIL_KEY); } catch {}
  };

  // حضور دائم: الشريط لا يختفي — عند غياب العناصر يعرض حالة صادقة واضحة
  // (لا بيانات مزيفة أبداً). يختفي فقط إذا عطّله المستخدم صراحة من الإعدادات.
  if (!settings?.enabled) return null;
  const seconds = settings.speed === 'slow' ? 55 : settings.speed === 'fast' ? 22 : 36;
  const content = filtered.length > 1 ? [...filtered, ...filtered] : filtered;
  const muted = muteUntil > Date.now();

  return <div dir="rtl" className={`${settings.position === 'bottom' ? 'fixed bottom-0 left-0 right-0 z-50' : 'relative z-20'} border-b border-sky-300 bg-sky-50 shadow-sm`}>
    <style jsx>{`@keyframes nexusTicker{from{transform:translateX(0)}to{transform:translateX(50%)}} .ticker-track{animation:nexusTicker ${seconds}s linear infinite;width:max-content}.ticker-wrap:hover .ticker-track{animation-play-state:${settings.pause_on_hover?'paused':'running'}} @media(prefers-reduced-motion:reduce){.ticker-track{animation:none}}`}</style>
    {filtered.length === 0 && <div className="flex h-9 items-center gap-2 border-b border-sky-200 bg-sky-50 px-3 text-[11px] text-sky-950" role="status">
      <Radio className="h-3.5 w-3.5 shrink-0" />
      <span className="font-bold">الأخبار الحية:</span>
      <span>لا عناصر نشطة الآن — يظهر الشريط تلقائيًا عند توفر أخبار أو أحداث تقويم ضمن عتبة الأهمية المضبوطة في الإعدادات.</span>
    </div>}
    <div className="ticker-wrap flex h-9 items-center overflow-hidden"><div className="flex h-full shrink-0 items-center gap-2 border-l border-sky-300 bg-sky-100 px-3 text-[11px] font-bold text-sky-950"><Radio className="h-3.5 w-3.5"/> الأخبار الحية<button onClick={toggleSessionMute} className="rounded p-1 hover:bg-sky-200" aria-label={muted?'تشغيل الصوت':'كتم الصوت'}>{muted?<VolumeX className="h-3.5 w-3.5"/>:<Volume2 className="h-3.5 w-3.5"/>}</button></div><div className="min-w-0 flex-1 overflow-hidden"><div className="ticker-track flex h-9 items-center whitespace-nowrap">{content.map((item,idx)=><div key={`${item.ticker_item_id}-${idx}`} className={`mx-1 flex h-7 items-center gap-2 rounded border px-2 text-[11px] ${severityClass[item.severity]}`}>{item.severity==='critical'?<AlertTriangle className="h-3 w-3"/>:<BellRing className="h-3 w-3"/>}<span className={`rounded px-1.5 py-0.5 text-[9px] font-bold ${badgeClass[item.severity]}`}>{item.severity.toUpperCase()}</span>{item.asset_id&&<span className="font-mono font-bold">{item.asset_id}</span>}<span className="max-w-[620px] overflow-hidden text-ellipsis font-medium">{item.headline_ar}</span>{item.actual_value!=null&&<span className="font-mono">فعلي {String(item.actual_value)}</span>}{item.forecast_value!=null&&<span className="font-mono">متوقع {String(item.forecast_value)}</span>}{item.direction&&<span className={`rounded border px-1.5 py-0.5 ${directionClass(item.direction)}`}>{directionAr(item.direction)}</span>}{item.confidence!=null&&<span className="font-mono">ثقة {Math.round(item.confidence)}%</span>}{item.blackout_state&&item.blackout_state!=='clear'&&<span className="rounded bg-red-100 px-1.5 py-0.5 font-bold text-red-800">BLACKOUT</span>}{item.acknowledged?<span className="flex items-center gap-1 rounded border border-emerald-300 bg-emerald-50 px-1.5 py-0.5 text-emerald-800"><CheckCircle2 className="h-3 w-3"/>تم الاطلاع</span>:<button onClick={()=>void acknowledge(item.ticker_item_id)} className="rounded border border-sky-300 bg-white px-1.5 py-0.5 text-sky-900 hover:bg-sky-100">تأكيد</button>}<span className="text-slate-500">{item.source_label??item.source_id??'—'}</span></div>)}</div></div></div>
  </div>;
}
