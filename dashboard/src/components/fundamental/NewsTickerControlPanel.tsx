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

function Toggle({ value, onChange, label }: { value: boolean; onChange: (v:boolean)=>void; label: string }) {
  return <button type="button" onClick={() => onChange(!value)} className={`rounded border px-2 py-1 text-[10px] font-semibold ${value ? 'border-emerald-300 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-white text-slate-500'}`}>{label}: {value ? 'ON' : 'OFF'}</button>;
}

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

  if (loading) return <div className="border border-sky-200 bg-white p-4 text-xs text-slate-600">جارٍ تحميل إعدادات الشريط…</div>;

  return <section dir="rtl" className="border border-sky-200 bg-white text-slate-800">
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-100 bg-sky-50 px-4 py-3"><div className="flex items-center gap-2"><BellRing className="h-4 w-4 text-sky-700"/><div><h3 className="text-sm font-bold text-sky-950">التحكم بالشريط الإخباري والصوت</h3><p className="text-[10px] text-slate-500">إعدادات عرض وتنبيه فقط — لا تغيّر أي Score أو Risk.</p></div></div><div className="flex gap-2"><button onClick={() => setSettings(original)} disabled={!dirty} className="flex items-center gap-1 rounded border border-sky-200 px-2 py-1 text-[10px] disabled:opacity-40"><RotateCcw className="h-3 w-3"/> تراجع</button><button onClick={save} disabled={!dirty} className="flex items-center gap-1 rounded bg-sky-700 px-3 py-1 text-[10px] font-bold text-white disabled:opacity-40"><Save className="h-3 w-3"/> حفظ</button></div></header>
    <div className="grid gap-4 p-4 xl:grid-cols-3">
      <div className="space-y-3"><h4 className="text-xs font-bold text-sky-900">العرض والتصفية</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.enabled} onChange={(v)=>patch('enabled',v)} label="الشريط"/><Toggle value={settings.pause_on_hover} onChange={(v)=>patch('pause_on_hover',v)} label="توقف عند المرور"/></div><div className="border border-sky-100 p-2"><div className="mb-1 text-[10px] font-semibold text-sky-900">الأصول</div><div className="flex flex-wrap gap-1">{['XAUUSD','BTCUSD'].map((x)=><Toggle key={x} value={settings.assets.includes(x)} onChange={()=>toggleList('assets',x)} label={x}/>)}</div></div><div className="border border-sky-100 p-2"><div className="mb-1 text-[10px] font-semibold text-sky-900">المحاور</div><div className="flex flex-wrap gap-1">{[['macro','Macro'],['monetary','Monetary'],['cross_asset','Cross'],['geopolitical','Geo'],['flows','Flows'],['news','News']].map(([v,l])=><Toggle key={v} value={settings.domains.includes(v)} onChange={()=>toggleList('domains',v)} label={l}/>)}</div></div><label className="block text-[10px]">الموضع<select value={settings.position} onChange={(e)=>patch('position',e.target.value as 'top'|'bottom')} className="mt-1 w-full border border-sky-200 p-2"><option value="top">أعلى</option><option value="bottom">أسفل</option></select></label><label className="block text-[10px]">السرعة<select value={settings.speed} onChange={(e)=>patch('speed',e.target.value as 'slow'|'medium'|'fast')} className="mt-1 w-full border border-sky-200 p-2"><option value="slow">بطيء</option><option value="medium">متوسط</option><option value="fast">سريع</option></select></label><label className="block text-[10px]">أقل أهمية<select value={settings.minimum_severity} onChange={(e)=>patch('minimum_severity',e.target.value as TickerSeverity)} className="mt-1 w-full border border-sky-200 p-2"><option value="low">LOW</option><option value="medium">MEDIUM</option><option value="high">HIGH</option><option value="critical">CRITICAL</option></select></label><label className="block text-[10px]">أقل ملاءمة للأصل {settings.minimum_relevance}%<input type="range" min="0" max="100" value={settings.minimum_relevance} onChange={(e)=>patch('minimum_relevance',Number(e.target.value))} className="w-full"/></label><label className="block text-[10px]">أقل جودة مصدر {settings.minimum_source_quality}%<input type="range" min="0" max="100" value={settings.minimum_source_quality} onChange={(e)=>patch('minimum_source_quality',Number(e.target.value))} className="w-full"/></label><label className="block text-[10px]">أقصى عمر للخبر (دقيقة)<input type="number" min="1" max="1440" value={settings.max_news_age_minutes} onChange={(e)=>patch('max_news_age_minutes',Number(e.target.value))} className="mt-1 w-full border border-sky-200 p-2"/></label></div>
      <div className="space-y-3"><h4 className="text-xs font-bold text-sky-900">الصوت العربي</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.audio_enabled} onChange={(v)=>patch('audio_enabled',v)} label="الصوت"/><Toggle value={settings.critical_audio} onChange={(v)=>patch('critical_audio',v)} label="CRITICAL"/><Toggle value={settings.high_audio} onChange={(v)=>patch('high_audio',v)} label="HIGH"/><Toggle value={settings.medium_audio} onChange={(v)=>patch('medium_audio',v)} label="MEDIUM"/></div><label className="block text-[10px]">اللغة<select value={settings.language} onChange={(e)=>patch('language',e.target.value as 'ar'|'en')} className="mt-1 w-full border border-sky-200 p-2"><option value="ar">العربية</option><option value="en">English</option></select></label><label className="block text-[10px]">الصوت<input value={settings.voice} onChange={(e)=>patch('voice',e.target.value)} className="mt-1 w-full border border-sky-200 p-2" placeholder="system_arabic"/></label><label className="block text-[10px]">مستوى الصوت {Math.round(settings.volume*100)}%<input type="range" min="0" max="1" step="0.05" value={settings.volume} onChange={(e)=>patch('volume',Number(e.target.value))} className="w-full"/></label><label className="block text-[10px]">سرعة النطق {settings.speech_rate.toFixed(2)}<input type="range" min="0.6" max="1.5" step="0.05" value={settings.speech_rate} onChange={(e)=>patch('speech_rate',Number(e.target.value))} className="w-full"/></label><div className="grid grid-cols-2 gap-2"><label className="text-[10px]">إعادة Critical<input type="number" min="0" max="1" value={settings.critical_repeat_count} onChange={(e)=>patch('critical_repeat_count',Number(e.target.value))} className="mt-1 w-full border border-sky-200 p-2"/></label><label className="text-[10px]">إعادة High<input type="number" min="0" max="1" value={settings.high_repeat_count} onChange={(e)=>patch('high_repeat_count',Number(e.target.value))} className="mt-1 w-full border border-sky-200 p-2"/></label><label className="text-[10px]">فاصل الإعادة (ث)<input type="number" min="10" max="120" value={settings.repeat_delay_seconds} onChange={(e)=>patch('repeat_delay_seconds',Number(e.target.value))} className="mt-1 w-full border border-sky-200 p-2"/></label><label className="text-[10px]">Cooldown (ث)<input type="number" min="5" max="600" value={settings.cooldown_seconds} onChange={(e)=>patch('cooldown_seconds',Number(e.target.value))} className="mt-1 w-full border border-sky-200 p-2"/></label></div><div className="border border-amber-200 bg-amber-50 p-2 text-[10px] text-amber-900">حد TTS الصلب: 18 ثانية — غير قابل للرفع من لوحة التحكم.</div><button onClick={testVoice} className="flex items-center gap-1 rounded border border-sky-300 px-3 py-2 text-[10px] text-sky-900"><Volume2 className="h-3.5 w-3.5"/> اختبار الصوت</button></div>
      <div className="space-y-3"><h4 className="text-xs font-bold text-sky-900">الحوكمة والكتم</h4><div className="flex flex-wrap gap-2"><Toggle value={settings.quiet_hours_enabled} onChange={(v)=>patch('quiet_hours_enabled',v)} label="ساعات هادئة"/><Toggle value={settings.blackout_alerts} onChange={(v)=>patch('blackout_alerts',v)} label="Blackout"/><Toggle value={settings.source_outage_alerts} onChange={(v)=>patch('source_outage_alerts',v)} label="تعطل المصادر"/><Toggle value={settings.verified_source_only_voice} onChange={(v)=>patch('verified_source_only_voice',v)} label="مصدر موثق للصوت"/><Toggle value={settings.two_source_geopolitical_voice} onChange={(v)=>patch('two_source_geopolitical_voice',v)} label="مصدران للجيوسياسة"/></div><div className="grid grid-cols-2 gap-2"><label className="text-[10px]">بداية الهدوء<input type="time" value={settings.quiet_hours_start} onChange={(e)=>patch('quiet_hours_start',e.target.value)} className="mt-1 w-full border border-sky-200 p-2"/></label><label className="text-[10px]">نهاية الهدوء<input type="time" value={settings.quiet_hours_end} onChange={(e)=>patch('quiet_hours_end',e.target.value)} className="mt-1 w-full border border-sky-200 p-2"/></label></div><div className="border border-sky-100 bg-sky-50 p-3"><div className="flex items-center gap-2 text-xs font-semibold text-sky-950">{muteUntil>Date.now()?<VolumeX className="h-4 w-4"/>:<Volume2 className="h-4 w-4"/>} كتم محلي لهذا المتصفح</div><div className="mt-2 flex flex-wrap gap-2"><button onClick={()=>mute(15)} className="rounded border border-sky-200 bg-white px-2 py-1 text-[10px]">15 دقيقة</button><button onClick={()=>mute(60)} className="rounded border border-sky-200 bg-white px-2 py-1 text-[10px]">ساعة</button><button onClick={()=>mute(24*60)} className="rounded border border-sky-200 bg-white px-2 py-1 text-[10px]">الجلسة/اليوم</button><button onClick={()=>mute(0)} className="rounded border border-emerald-200 bg-white px-2 py-1 text-[10px] text-emerald-800">إلغاء الكتم</button></div></div><div className="border border-sky-100 p-3 text-[10px] leading-5 text-slate-600"><b>اختبار الشريط:</b><div className="mt-2 flex h-8 items-center gap-2 overflow-hidden bg-sky-50 px-2"><span className="rounded bg-red-100 px-1 text-red-800">TEST</span><span>معاينة تصميم فقط — لا توجد قيمة سوقية أو خبر حقيقي.</span></div></div></div>
    </div>
    {status && <div className="border-t border-sky-100 px-4 py-2 text-[10px] text-sky-900">{status}</div>}
  </section>;
}
