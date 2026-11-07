'use client';

import { useEffect, useMemo, useState } from 'react';
import { BellRing, Save, Volume2, VolumeX, RotateCcw } from 'lucide-react';
import { apiClient } from '@/lib/api-client';
import type { NewsTickerSettingsDTO, TickerSeverity } from '@/types/fundamental';

const MUTE_UNTIL_KEY = 'nexus.newsTicker.muteUntil';

const FALLBACK: NewsTickerSettingsDTO = {
  enabled: true, position: 'top', speed: 'medium', pause_on_hover: true,
  assets: ['XAUUSD','BTCUSD'], domains: ['macro','monetary','cross_asset','geopolitical','flows','news'],
  minimum_severity: 'medium', minimum_relevance: 40, minimum_source_quality: 50, max_news_age_minutes: 30,
  audio_enabled: true, critical_audio: true, high_audio: true, medium_audio: false,
  language: 'ar', voice: 'system_arabic', volume: .85, speech_rate: 1,
  critical_repeat_count: 1, high_repeat_count: 0, repeat_delay_seconds: 25, cooldown_seconds: 20,
  quiet_hours_enabled: false, quiet_hours_start: '23:00', quiet_hours_end: '07:00',
  blackout_alerts: true, source_outage_alerts: false, verified_source_only_voice: true, two_source_geopolitical_voice: true,
  critical_ttl_seconds: 0, high_ttl_seconds: 600, medium_ttl_seconds: 300, low_ttl_seconds: 120,
  hide_after_ack: true, show_acknowledged: false, show_scheduled: true, show_breaking: true,
  critical_display_mode: 'ticker_banner_tts', high_display_mode: 'ticker_toast_sound',
  medium_display_mode: 'ticker_toast', low_display_mode: 'ticker', require_ack_critical: true,
};

// Design-system tokens only (owner 2026-11-07: unify with the settings page —
// no more hardcoded light sky/slate palette floating on the dark shell).
function Toggle({ value, onChange, label }: { value: boolean; onChange: (v:boolean)=>void; label: string }) {
  return <button type="button" onClick={() => onChange(!value)} className={`rounded border px-2 py-1 text-[10px] font-semibold transition-all ${value ? 'border-neon-green/30 bg-neon-green/10 text-neon-green' : 'border-border-primary bg-bg-tertiary text-text-muted hover:text-text-secondary'}`}>{label}: {value ? 'ON' : 'OFF'}</button>;
}

const inputCls = "mt-1 w-full bg-bg-input border border-border-primary text-text-secondary text-[10px] font-mono px-2 py-1.5 rounded focus:outline-none focus:border-neon-purple/40";
const boxCls = "rounded border border-border-primary/60 bg-bg-secondary/30 px-2 py-2";
const groupCls = "text-[10px] font-mono font-bold text-text-secondary uppercase tracking-wider";

export default function NewsTickerControlPanel() {
  const [settings, setSettings] = useState<NewsTickerSettingsDTO>(FALLBACK);
  const [original, setOriginal] = useState<NewsTickerSettingsDTO>(FALLBACK);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [muteUntil, setMuteUntil] = useState<number>(0);

  useEffect(() => {
    try { setMuteUntil(Number(localStorage.getItem(MUTE_UNTIL_KEY) || '0')); } catch {}
    apiClient.getNewsTickerSettings().then((r) => { setSettings(r.data); setOriginal(r.data); }).catch(() => setStatus('تعذر تحميل إعدادات الشريط من الخدمة.')).finally(() => setLoading(false));
  }, []);

  const dirty = useMemo(() => JSON.stringify(settings) !== JSON.stringify(original), [settings, original]);
  const patch = <K extends keyof NewsTickerSettingsDTO>(k: K, v: NewsTickerSettingsDTO[K]) => setSettings((s) => ({...s,[k]:v}));
  const toggleList = (key: 'assets'|'domains', value: string) => setSettings((prev) => { const list = prev[key]; return {...prev,[key]:list.includes(value)?list.filter((x)=>x!==value):[...list,value]}; });

  const save = async () => {
    setStatus('جارٍ الحفظ…');
    try { const r = await apiClient.updateNewsTickerSettings(settings); setSettings(r.data.settings); setOriginal(r.data.settings); setStatus('تم حفظ إعدادات الشريط في Redis.'); }
    catch { setStatus('فشل حفظ إعدادات الشريط. لم تتغير بيانات التحليل أو التداول.'); }
  };

  const mute = (minutes: number) => {
    const until = minutes > 0 ? Date.now() + minutes * 60_000 : 0;
    setMuteUntil(until);
    try { if (until) localStorage.setItem(MUTE_UNTIL_KEY, String(until)); else localStorage.removeItem(MUTE_UNTIL_KEY); } catch {}
    window.dispatchEvent(new CustomEvent('nexus-news-ticker-mute-change', { detail: { until } }));
  };

  const testVoice = () => {
    if (!('speechSynthesis' in window)) { setStatus('المتصفح لا يدعم SpeechSynthesis.'); return; }
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance('اختبار تنبيه نِكسس. هذا اختبار صوتي فقط ولا يمثل خبرًا أو إشارة تداول.');
    u.lang = settings.language === 'ar' ? 'ar-SA' : 'en-US'; u.volume = settings.volume; u.rate = settings.speech_rate;
    const hardStop = window.setTimeout(()=>window.speechSynthesis.cancel(), 18_000);
    u.onend = () => window.clearTimeout(hardStop); u.onerror = () => window.clearTimeout(hardStop);
    window.speechSynthesis.speak(u);
    setStatus('تم تشغيل اختبار صوتي فقط؛ حد TTS الصلب 18 ثانية.');
  };

  if (loading) return <div className="rounded-lg border border-border-primary bg-bg-primary p-4 text-xs text-text-muted">جارٍ تحميل إعدادات الشريط…</div>;

  return <section dir="rtl" className="rounded-lg border border-border-primary bg-bg-primary text-text-primary overflow-hidden">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border-primary bg-bg-secondary/60 px-4 py-3"><div className="flex items-center gap-2"><BellRing className="h-4 w-4 text-neon-purple"/><div><h3 className="text-sm font-bold text-text-primary">التحكم بالشريط الإخباري والصوت</h3><p className="text-[10px] text-text-muted">إعدادات عرض وتنبيه فقط — لا تغيّر أي Score أو Risk.</p></div></div><div className="flex gap-2"><button onClick={() => setSettings(original)} disabled={!dirty} className="flex items-center gap-1 rounded border border-border-primary px-2 py-1 text-[10px] text-text-muted hover:text-text-secondary disabled:opacity-40 transition-all"><RotateCcw className="h-3 w-3"/> تراجع</button><button onClick={save} disabled={!dirty} className="flex items-center gap-1 rounded border border-neon-purple/40 bg-neon-purple/20 px-3 py-1 text-[10px] font-bold text-neon-purple hover:bg-neon-purple/30 disabled:opacity-40 transition-all"><Save className="h-3 w-3"/> حفظ</button></div></header>
    <div className="grid gap-4 p-4 xl:grid-cols-3">
      <div className="space-y-3"><h4 className={groupCls}>العرض والتصفية</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.enabled} onChange={(v)=>patch('enabled',v)} label="الشريط"/><Toggle value={settings.pause_on_hover} onChange={(v)=>patch('pause_on_hover',v)} label="توقف عند المرور"/></div><div className={boxCls}><div className="mb-1 text-[10px] font-semibold text-text-secondary">الأصول</div><div className="flex flex-wrap gap-1">{['XAUUSD','BTCUSD'].map((x)=><Toggle key={x} value={settings.assets.includes(x)} onChange={()=>toggleList('assets',x)} label={x}/>)}</div></div><div className={boxCls}><div className="mb-1 text-[10px] font-semibold text-text-secondary">المحاور</div><div className="flex flex-wrap gap-1">{[['macro','Macro'],['monetary','Monetary'],['cross_asset','Cross'],['geopolitical','Geo'],['flows','Flows'],['news','News']].map(([v,l])=><Toggle key={v} value={settings.domains.includes(v)} onChange={()=>toggleList('domains',v)} label={l}/>)}</div></div><label className="block text-[10px] text-text-secondary">الموضع<select value={settings.position} onChange={(e)=>patch('position',e.target.value as 'top'|'bottom')} className={inputCls}><option value="top">أعلى</option><option value="bottom">أسفل</option></select></label><label className="block text-[10px] text-text-secondary">السرعة<select value={settings.speed} onChange={(e)=>patch('speed',e.target.value as 'slow'|'medium'|'fast')} className={inputCls}><option value="slow">بطيء</option><option value="medium">متوسط</option><option value="fast">سريع</option></select></label><label className="block text-[10px] text-text-secondary">أقل أهمية<select value={settings.minimum_severity} onChange={(e)=>patch('minimum_severity',e.target.value as TickerSeverity)} className={inputCls}><option value="low">LOW</option><option value="medium">MEDIUM</option><option value="high">HIGH</option><option value="critical">CRITICAL</option></select></label><label className="block text-[10px] text-text-secondary">أقل ملاءمة للأصل {settings.minimum_relevance}%<input type="range" min="0" max="100" value={settings.minimum_relevance} onChange={(e)=>patch('minimum_relevance',Number(e.target.value))} className="mt-1 w-full accent-[var(--neon-purple,#a855f7)]"/></label><label className="block text-[10px] text-text-secondary">أقل جودة مصدر {settings.minimum_source_quality}%<input type="range" min="0" max="100" value={settings.minimum_source_quality} onChange={(e)=>patch('minimum_source_quality',Number(e.target.value))} className="mt-1 w-full accent-[var(--neon-purple,#a855f7)]"/></label><label className="block text-[10px] text-text-secondary">أقصى عمر للخبر (دقيقة)<input type="number" min="1" max="1440" value={settings.max_news_age_minutes} onChange={(e)=>patch('max_news_age_minutes',Number(e.target.value))} className={inputCls}/></label></div>
      <div className="space-y-3"><h4 className={groupCls}>الصوت العربي</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.audio_enabled} onChange={(v)=>patch('audio_enabled',v)} label="الصوت"/><Toggle value={settings.critical_audio} onChange={(v)=>patch('critical_audio',v)} label="CRITICAL"/><Toggle value={settings.high_audio} onChange={(v)=>patch('high_audio',v)} label="HIGH"/><Toggle value={settings.medium_audio} onChange={(v)=>patch('medium_audio',v)} label="MEDIUM"/></div><label className="block text-[10px] text-text-secondary">اللغة<select value={settings.language} onChange={(e)=>patch('language',e.target.value as 'ar'|'en')} className={inputCls}><option value="ar">العربية</option><option value="en">English</option></select></label><label className="block text-[10px] text-text-secondary">الصوت<input value={settings.voice} onChange={(e)=>patch('voice',e.target.value)} className={inputCls} placeholder="system_arabic"/></label><label className="block text-[10px] text-text-secondary">مستوى الصوت {Math.round(settings.volume*100)}%<input type="range" min="0" max="1" step="0.05" value={settings.volume} onChange={(e)=>patch('volume',Number(e.target.value))} className="mt-1 w-full accent-[var(--neon-purple,#a855f7)]"/></label><label className="block text-[10px] text-text-secondary">سرعة النطق {settings.speech_rate.toFixed(2)}<input type="range" min="0.6" max="1.5" step="0.05" value={settings.speech_rate} onChange={(e)=>patch('speech_rate',Number(e.target.value))} className="mt-1 w-full accent-[var(--neon-purple,#a855f7)]"/></label><div className="grid grid-cols-2 gap-2"><label className="text-[10px] text-text-secondary">إعادة Critical<input type="number" min="0" max="1" value={settings.critical_repeat_count} onChange={(e)=>patch('critical_repeat_count',Number(e.target.value))} className={inputCls}/></label><label className="text-[10px] text-text-secondary">إعادة High<input type="number" min="0" max="1" value={settings.high_repeat_count} onChange={(e)=>patch('high_repeat_count',Number(e.target.value))} className={inputCls}/></label><label className="text-[10px] text-text-secondary">فاصل الإعادة (ث)<input type="number" min="10" max="120" value={settings.repeat_delay_seconds} onChange={(e)=>patch('repeat_delay_seconds',Number(e.target.value))} className={inputCls}/></label><label className="text-[10px] text-text-secondary">Cooldown (ث)<input type="number" min="5" max="600" value={settings.cooldown_seconds} onChange={(e)=>patch('cooldown_seconds',Number(e.target.value))} className={inputCls}/></label></div><div className="rounded border border-neon-gold/30 bg-neon-gold/5 p-2 text-[10px] text-neon-gold">حد TTS الصلب: 18 ثانية — غير قابل للرفع من لوحة التحكم.</div><button onClick={testVoice} className="flex items-center gap-1 rounded border border-neon-cyan/30 bg-neon-cyan/10 px-3 py-2 text-[10px] font-bold text-neon-cyan hover:bg-neon-cyan/20 transition-all"><Volume2 className="h-3.5 w-3.5"/> اختبار الصوت</button></div>
      <div className="space-y-3"><h4 className={groupCls}>الحوكمة والكتم</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.quiet_hours_enabled} onChange={(v)=>patch('quiet_hours_enabled',v)} label="ساعات هادئة"/><Toggle value={settings.blackout_alerts} onChange={(v)=>patch('blackout_alerts',v)} label="Blackout"/><Toggle value={settings.source_outage_alerts} onChange={(v)=>patch('source_outage_alerts',v)} label="تعطل المصادر"/><Toggle value={settings.verified_source_only_voice} onChange={(v)=>patch('verified_source_only_voice',v)} label="مصدر موثق للصوت"/><Toggle value={settings.two_source_geopolitical_voice} onChange={(v)=>patch('two_source_geopolitical_voice',v)} label="مصدران للجيوسياسة"/></div><div className="grid grid-cols-2 gap-2"><label className="text-[10px] text-text-secondary">بداية الهدوء<input type="time" value={settings.quiet_hours_start} onChange={(e)=>patch('quiet_hours_start',e.target.value)} className={inputCls}/></label><label className="text-[10px] text-text-secondary">نهاية الهدوء<input type="time" value={settings.quiet_hours_end} onChange={(e)=>patch('quiet_hours_end',e.target.value)} className={inputCls}/></label></div><div className={boxCls}><div className="flex items-center gap-2 text-xs font-semibold text-text-secondary">{muteUntil>Date.now()?<VolumeX className="h-4 w-4 text-neon-gold"/>:<Volume2 className="h-4 w-4 text-neon-cyan"/>} كتم محلي لهذا المتصفح</div><div className="mt-2 flex flex-wrap gap-2"><button onClick={()=>mute(15)} className="rounded border border-border-primary bg-bg-input px-2 py-1 text-[10px] text-text-secondary hover:text-text-primary transition-all">15 دقيقة</button><button onClick={()=>mute(60)} className="rounded border border-border-primary bg-bg-input px-2 py-1 text-[10px] text-text-secondary hover:text-text-primary transition-all">ساعة</button><button onClick={()=>mute(24*60)} className="rounded border border-border-primary bg-bg-input px-2 py-1 text-[10px] text-text-secondary hover:text-text-primary transition-all">الجلسة/اليوم</button><button onClick={()=>mute(0)} className="rounded border border-neon-green/30 bg-neon-green/10 px-2 py-1 text-[10px] text-neon-green hover:bg-neon-green/20 transition-all">إلغاء الكتم</button></div></div><div className={boxCls + " text-[10px] leading-5 text-text-muted"}><b className="text-text-secondary">اختبار الشريط:</b><div className="mt-2 flex h-8 items-center gap-2 overflow-hidden rounded bg-bg-secondary px-2"><span className="rounded bg-neon-red/10 px-1 text-neon-red">TEST</span><span>معاينة تصميم فقط — لا توجد قيمة سوقية أو خبر حقيقي.</span></div></div></div>
    </div>
    {status && <div className="border-t border-border-primary bg-bg-secondary/40 px-4 py-2 text-[10px] text-text-muted">{status}</div>}
  </section>;
}
