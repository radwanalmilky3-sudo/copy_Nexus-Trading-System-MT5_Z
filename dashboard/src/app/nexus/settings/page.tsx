'use client';

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  Settings, Save, RotateCcw, Cpu, Shield, Zap, Brain, Bot,
  ChevronDown, ChevronRight, AlertTriangle, Globe, Database, Bell, BellRing, FlaskConical,
  Activity, RefreshCcw, Search, FolderOpen, Sparkles, Undo2, Upload, FileCog,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { apiClient, getAuthHeaders, type SystemEnvVar } from '@/lib/api-client';
import {
  DEFAULT_UI_SETTINGS, readLocalSettings, writeLocalSettings, type UiSettings,
} from '@/lib/ui-settings';
import NewsTickerControlPanel from '@/components/fundamental/NewsTickerControlPanel';
import { AutoTradeToggle } from '@/components/trade-controls';
import SourceConnectionManager from '@/components/settings/SourceConnectionManager';
import AdminAlertsCenter from '@/components/settings/AdminAlertsCenter';
import BrokerSettingsTab from '@/components/settings/broker/BrokerSettingsTab';
import { EaBridgeView } from '@/components/ea/EABridgeView';
import ResearchLabShell from '@/components/research-lab/ResearchLabShell';
import { ProgressView } from '@/components/project/ProgressView';
import AuditProgressView from '@/components/audit/AuditProgressView';
import type { SourceHealthDTO } from '@/types/fundamental';

const API = process.env.NEXT_PUBLIC_API_URL || '';

// ── Section schema ─────────────────────────────────────────────────────────────
interface SettingField {
  key: string;
  label: string;
  description: string;
  type: 'number' | 'boolean' | 'select' | 'text';
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  unit?: string;
}

interface SettingSection {
  id: string;
  label: string;
  icon: React.ElementType;
  color: string;
  fields: SettingField[];
  /** 2xl grid override — match column count to field count so no row carries an empty dead column (owner: exploit space, no wasted rows). */
  gridCols?: string;
}

const RUNTIME_SECTIONS: SettingSection[] = [
  {
    id: 'trading',
    label: 'نواة التداول (Trading Core)',
    icon: Zap,
    color: 'text-neon-green',
    gridCols: '2xl:grid-cols-4',
    fields: [
      { key: 'trading_mode_type',     label: 'وضع التداول',            type: 'select',  options: ['scalping', 'swing'], description: 'وضع التداول النشط: scalping للتجزئة أو swing للتمويض الربحي.' },
      { key: 'auto_tf_selection',     label: 'اختيار TF تلقائي',       type: 'boolean', description: 'اختيار الإطار الزمني TF للاستغناء ديناميكيًا حسب الجلسة النشطة.' },
      { key: 'operational_tf',        label: 'إطار التشغيل (TF)',      type: 'select',  options: ['M1', 'M5', 'M15', 'H1'], description: 'TF التنفيذ — يتجاوز الاختيار التلقائي إذا كان auto_tf مفعّلًا.' },
      { key: 'require_mtf_confirmation', label: 'تأكيد MTF',           type: 'boolean', description: 'يشترط توافق الإطارات الزمنية الأعلى (MTF) قبل الدخول.' },
      { key: 'min_mtf_agreement',     label: 'أقل TFs توافقًا',        type: 'number',  min: 0, max: 3, step: 1, description: 'عدد الإطارات العليا المطلوب تطابقها (بحد أقصى 3).' },
      { key: 'max_daily_trades',      label: 'أقصى صفقات / يوم',       type: 'number',  min: 1, max: 50, step: 1, description: 'حد العمليات اليومية لكل رمز.' },
      { key: 'off_hours_allowed', label: 'التداول خارج الجلسات (Off-hours)', type: 'boolean', description: 'السماح بالتداول خارج طوكيو/لندن/نيويورك — نفس مفتاح بوابة الجلسات.' },
    ],
  },
  {
    id: 'risk',
    label: 'المخاطرة والحجم (Risk & Sizing)',
    icon: Shield,
    color: 'text-neon-red',
    fields: [
      { key: 'risk_per_trade_pct',    label: 'المخاطرة لكل صفقة',      type: 'number', min: 0.1, max: 5.0, step: 0.1, unit: '%', description: 'نسبة الرصيد المعرّضة لكل عملية (الافتراضي 1%).' },
      { key: 'max_spread_pips',       label: 'أقصى Spread',            type: 'number', min: 0.1, max: 10, step: 0.1, unit: 'pips', description: 'يرفض الدخول إذا تجاوز Spread هذا الحد.' },
      { key: 'sl_atr_multiplier',     label: 'وقف الخسارة (SL × ATR)', type: 'number', min: 1.0, max: 5.0, step: 0.1, description: 'أدنى وقف خسارة Stop-Loss كمضاعف لمؤشر ATR.' },
      { key: 'tp_atr_multiplier',     label: 'جني الأرباح (TP × ATR)', type: 'number', min: 2.0, max: 10.0, step: 0.5, description: 'هدف جني الأرباح Take-Profit كمضاعف لمؤشر ATR.' },
      { key: 'min_rr_ratio',          label: 'أدنى RR',                type: 'number', min: 1.0, max: 5.0, step: 0.1, description: 'أدنى نسبة Risk/Reward مقبولة لدخول الصفقة.' },
      { key: 'max_hold_bars',         label: 'أقصى شموع بالصفقة',      type: 'number', min: 1, max: 48, step: 1, unit: 'bars', description: 'إغلاق زمني للصفقة عند تجاوز هذا الحد.' },
      { key: 'cooling_off_streak',    label: 'توقف بعد خسائر متتالية', type: 'number', min: 2, max: 10, step: 1, unit: 'خسارة', description: 'عدد الخسائر المتتالية الذي يفعّل التوقف المؤقت.' },
      { key: 'sl_floor_atr_mult',     label: 'حد SL الأدنى × ATR',     type: 'number', min: 1.0, max: 5.0, step: 0.1, description: 'الحد الأدنى المطلق للـ SL كمضاعف ATR (افتراضي 2.5) لمنع وقفات ضيقة جدًا.' },
      { key: 'entry_displacement_atr_mult', label: 'أقصى انزياح دخول × ATR', type: 'number', min: 0.5, max: 5.0, step: 0.1, description: 'يرفض الدخول إذا تحرك السعر N×ATR لاتجاه الإشارة مسبقًا (افتراضي 2.0).' },
    ],
  },
  {
    id: 'signals',
    label: 'الإشارات والجودة (Signals & Quality)',
    icon: Cpu,
    color: 'text-neon-purple',
    gridCols: '2xl:grid-cols-4',
    fields: [
      { key: 'quality_score_threshold', label: 'حد Quality score', type: 'number', min: 0, max: 90, step: 5, description: 'حد أدنى يدوي للـ Score. 0 = يعتمد العتبة الديناميكية من TradeMemory (0-100).' },
      { key: 'min_conviction_override', label: 'تجاوز Conviction', type: 'number', min: 0, max: 0.90, step: 0.01, description: '0 = ديناميكي حسب الجلسة. تُثبَّت القيمة إذا كانت أكبر من 0.' },
      { key: 'autonomous_ml',          label: 'خط ML/DL/RL مستقل',   type: 'boolean', description: 'تنفيذ ML/DL/RL دون انتظار تأكيد وكيل GenAI.' },
      { key: 'pre_signal_spread_filter', label: 'فلتر Spread مسبق',  type: 'boolean', description: 'يحجب الإشارات عند ارتفاع Spread قبل الدخول.' },
      { key: 'signal_cooldown_sec',    label: 'Cooldown بين الإشارات', type: 'number', min: 10, max: 300, step: 10, unit: 's', description: 'ثوانٍ كحد أدنى بين إشارات نفس الرمز.' },
      { key: 'min_confidence_floor',   label: 'أدنى Conviction مطلق', type: 'number', min: 0.20, max: 0.70, step: 0.01, description: 'أدنى قاعدة conviction بعد ضبط TradeMemory الديناميكي (افتراضي 0.40).' },
      { key: 'conviction_min',         label: 'Conviction الأساسي',   type: 'number', min: 0.40, max: 0.80, step: 0.01, description: 'أدنى conviction أساسي خارج الجلسة المهيأة (افتراضي 0.55).' },
    ],
  },
  {
    id: 'models',
    label: 'النماذج والتدريب (Models & Training)',
    icon: Brain,
    color: 'text-neon-cyan',
    fields: [
      { key: 'retrain_interval_hours', label: 'إعادة التدريب كل',      type: 'number', min: 1, max: 24, step: 1, unit: 'h', description: 'دورة إعادة تدريب كل النماذج تلقائيًا.' },
      { key: 'outcome_weight',        label: 'أوزان الصفقات الحقيقية', type: 'number', min: 1, max: 10, step: 1, unit: '×', description: 'مضاعف وزن سجلات الصفقات الحقيقية أثناء التدريب.' },
      { key: 'allow_synthetic_training', label: 'بيانات مُولَّدة (Synthetic)', type: 'boolean', description: 'استخدام بيانات مُولَّدة فقط عند غياب البيانات الحقيقية.' },
      { key: 'dl_seq_len',            label: 'طول تسلسل DL',          type: 'number', min: 5, max: 50, step: 5, unit: 'bars', description: 'طول تسلسل الإدخال للمحوّل Transformer.' },
      { key: 'dl_confidence_threshold', label: 'عتبة ثقة DL',         type: 'number', min: 0.30, max: 0.80, step: 0.05, description: 'أدنى ثقة لنموذج DL لإصدار إشارة صالحة.' },
      { key: 'rl_n_epochs',           label: 'RL epochs / دورة',       type: 'number', min: 5, max: 50, step: 5, description: 'دورات تدريب PPO في كل دورة إعادة تدريب.' },
    ],
  },
  {
    id: 'notifications',
    label: 'الإشعارات (Notifications)',
    icon: Bell,
    color: 'text-neon-purple',
    gridCols: '2xl:grid-cols-4',
    fields: [
      { key: 'notif_enable_browser',   label: 'إشعارات المتصفح',      type: 'boolean', description: 'إشعارات نظام التشغيل عندما تكون التبويب غير نشط.' },
      { key: 'notif_blackout',         label: 'إشعارات Blackout',      type: 'boolean', description: 'الإشعار عند تفعيل أو تعطيل حجب أخبار عالية التأثير Blackout.' },
      { key: 'notif_brief',            label: 'إشعار الـ Brief',       type: 'boolean', description: 'الإشعار عند توليد وكيل GenAI لموجز مالي يومي جديد.' },
      { key: 'notif_corr_divergence',  label: 'إشعار تباعد الارتباط',  type: 'boolean', description: 'الإشعار عند رصد تباعد HIGH في مصفوفة الارتباط متعددة الأصول.' },
    ],
  },
  {
    id: 'correlation',
    label: 'الارتباط متعدد الأصول (Correlation)',
    icon: Globe,
    color: 'text-neon-purple',
    fields: [
      { key: 'corr_refresh_sec',           label: 'دورة تحديث الارتباط', type: 'number', min: 60, max: 3600, step: 60, unit: 's', description: 'كل كم ثانية يُعاد حساب مصفوفة الارتباط (افتراضي 300 = 5 دقائق).' },
      { key: 'corr_divergence_threshold',  label: 'عتبة التباعد',       type: 'number', min: 0.10, max: 0.70, step: 0.05, description: 'أدنى فرق بين 7d و 30d لاعتبار التباعد HIGH (افتراضي 0.25).' },
      { key: 'corr_window_default',        label: 'النافذة الافتراضية',  type: 'select', options: ['7d', '30d'], description: 'النافذة الزمنية المعروضة عند فتح لوحة الارتباط.' },
    ],
  },
  {
    id: 'trade_memory',
    label: 'ذاكرة الصفقات (Trade Memory)',
    icon: Brain,
    color: 'text-neon-purple',
    gridCols: '2xl:grid-cols-2',
    fields: [
      { key: 'trade_memory_window',       label: 'حجم ذاكرة الصفقات',  type: 'number', min: 20, max: 500, step: 10, unit: 'trades', description: 'عدد الصفقات الحديثة المحفوظة لحساب العتبات الديناميكية (افتراضي 100).' },
      { key: 'cooling_off_duration_sec',  label: 'مدة Cooling-off',    type: 'number', min: 60, max: 3600, step: 60, unit: 's', description: 'ثوانٍ التوقف بعد بلوغ سلسلة الخسائر المتتالية (افتراضي 300 = 5 دقائق).' },
    ],
  },
  {
    id: 'backtest',
    label: 'الاختبار الخلفي (Backtesting)',
    icon: FlaskConical,
    color: 'text-neon-cyan',
    gridCols: '2xl:grid-cols-2',
    fields: [
      { key: 'backtest_initial_equity',   label: 'رأس المال الابتدائي', type: 'number', min: 500, max: 500000, step: 500, unit: '$', description: 'الرأس المال الافتراضي عند فتح لوحة Backtest.' },
      { key: 'backtest_default_symbol',   label: 'الرمز الافتراضي',      type: 'select', options: ['XAUUSD', 'EURUSD', 'BTCUSD', 'US500'], description: 'الرمز المحدد مسبقًا عند فتح لوحة Backtest.' },
    ],
  },
  {
    id: 'genai',
    label: 'وكيل GenAI والبحث (GenAI Research)',
    icon: Bot,
    color: 'text-yellow-400',
    fields: [
      { key: 'disable_research',      label: 'إيقاف Research مؤقتًا', type: 'boolean', description: 'إيقاف البحث الأسبوعي عن استراتيجيات جديدة.' },
      { key: 'research_interval_sec', label: 'دورة Research',         type: 'number', min: 900, max: 7200, step: 900, unit: 's', description: 'فترة دورة بحث الاستراتيجيات (بحد أقصى 7200 ثانية = ساعتان).' },
      { key: 'strategy_min_profit_factor', label: 'أدنى PF',          type: 'number', min: 1.0, max: 3.0, step: 0.1, description: 'أدنى Profit Factor لترقية استراتيجية جديدة.' },
      { key: 'strategy_min_win_rate', label: 'أدنى WR',               type: 'number', min: 0.40, max: 0.80, step: 0.01, unit: '%', description: 'أدنى Win Rate لاعتماد استراتيجية جديدة.' },
      { key: 'genai_max_calls_per_hour', label: 'طلات GenAI / ساعة',  type: 'number', min: 5, max: 120, step: 5, description: 'حد استدعاءات واجهة GenAI بالساعة.' },
    ],
  },
];

type SettingsTab = 'general' | 'fundamental_sources' | 'users_alerts' | 'brokers' | 'news_ticker' | 'ea_bridge' | 'research_lab' | 'project';

type SourceFilter = 'all' | 'healthy' | 'config_required' | 'degraded' | 'unknown' | 'offline';

const SOURCE_STATUS_AR: Record<string, string> = {
  healthy: 'سليم',
  degraded: 'متدهور',
  rate_limited: 'مقيّد مؤقتًا',
  config_required: 'يتطلب إعدادًا',
  offline: 'غير متصل',
  unknown: 'غير معروف',
  unavailable: 'غير متاح',
  fresh: 'حديث',
  stale: 'قديم',
  live: 'حي',
};

// ── Main Component ─────────────────────────────────────────────────────────────

// Market sessions the risk gate can allow (OFF_HOURS is the separate toggle).
// Names are English on purpose: they are the values the server compares.
const SESSION_CHOICES = ['SYDNEY', 'TOKYO', 'LONDON', 'NEW_YORK', 'OVERLAP'] as const;

const SETTINGS_TAB_KEYS: readonly SettingsTab[] = ['general', 'brokers', 'ea_bridge', 'research_lab', 'fundamental_sources', 'users_alerts', 'news_ticker', 'project'];

export default function SettingsPage() {
  // دعم الوصول المباشر بالتبويب عبر الرابط (?tab=) — تستخدمه إعادة توجيه
  // المسارات القديمة (progress/audit-progress/research-lab/ea-bridge).
  return (
    <React.Suspense fallback={<p role="status">جارٍ تحميل الإعدادات…</p>}>
      <SettingsPageInner />
    </React.Suspense>
  );
}

function SettingsPageInner() {
  // Runtime settings (from Redis via API)
  const [runtime, setRuntime] = useState<Record<string, any>>({});
  const [runtimeOrig, setRuntimeOrig] = useState<Record<string, any>>({});
  // Server-side defaults for keys the user has not stored yet (optional
  // `defaults` sibling of `settings`). Display-only: never merged into
  // `runtime`, so runtimeChanged/save keep pushing only real edits.
  const [runtimeDefaults, setRuntimeDefaults] = useState<Record<string, any>>({});

  // Authoritative PAPER/LIVE mode (GET /api/system/mode). null = unknown
  // (still loading, or the fetch failed) — never guessed or optimistically set.
  const [systemMode, setSystemMode] = useState<'PAPER' | 'LIVE' | null>(null);

  // Local UI settings (SSR renders the defaults; browser prefs hydrate below)
  const [local, setLocal] = useState<UiSettings>({ ...DEFAULT_UI_SETTINGS });
  const [localOrig, setLocalOrig] = useState<UiSettings>({ ...DEFAULT_UI_SETTINGS });

  // Side panel data
  const [dynamicThresholds, setDynamicThresholds] = useState<any>(null);
  const [thresholdsState, setThresholdsState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [mt5Connected, setMt5Connected] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [sessionGate, setSessionGate] = useState<{ offHoursAllowed: boolean; allowedSessions: string[] } | null>(null);
  const [sessionGateUnavailable, setSessionGateUnavailable] = useState(false);

  // ── Settings templates (JSON files in config/settings_templates) ──────
  // The list/path come from GET /api/intelligence/settings/templates; values
  // only ever FILL the form — persistence still goes through the «حفظ الكل»
  // button so the user reviews before anything is written.
  const [templatesPath, setTemplatesPath] = useState('');
  const [templatesList, setTemplatesList] = useState<
    Array<{ file: string; name: string; description: string; builtin: boolean; keys: number; valid: boolean; error: string | null }>
  >([]);
  const [templatesLast, setTemplatesLast] = useState<{ settings: Record<string, unknown>; saved_at: string } | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState('');
  const [templateName, setTemplateName] = useState('');
  const [templateMsg, setTemplateMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // ── .env environment variables (GET/POST /api/system/env) ──────────────
  // Only non-secret entries reach the browser: the gateway strips PIN/JWT/
  // passwords/API keys before answering, and nothing here ever renders them.
  const [envVars, setEnvVars] = useState<SystemEnvVar[]>([]);
  const [envFile, setEnvFile] = useState('');
  const [envSecrets, setEnvSecrets] = useState(0);
  const [envLoading, setEnvLoading] = useState(true);
  const [envError, setEnvError] = useState<string | null>(null);
  // Pending edits + per-row status, keyed by env variable name.
  const [envEdit, setEnvEdit] = useState<Record<string, string>>({});
  const [envRowMsg, setEnvRowMsg] = useState<Record<string, string>>({});
  // Sticky until the operator restarts the system (currently requires approval).
  const [envRestartPending, setEnvRestartPending] = useState(false);

  // UI state
  const [activeTab, setActiveTab] = useState<SettingsTab>('general');
  // قراءة الرابط (?tab=) مرة واحدة عند الإقلاع — تستخدمها إعادة توجيه المسارات
  // القديمة (progress/audit-progress/research-lab/ea-bridge) للوصول المباشر.
  const searchParams = useSearchParams();
  useEffect(() => {
    const requested = searchParams.get('tab');
    if (requested && (SETTINGS_TAB_KEYS as readonly string[]).includes(requested)) {
      setActiveTab(requested as SettingsTab);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [sourceHealth, setSourceHealth] = useState<SourceHealthDTO[]>([]);
  const [sourceHealthLoading, setSourceHealthLoading] = useState(false);
  const [sourceHealthError, setSourceHealthError] = useState<string | null>(null);
  const [sourceHealthUpdatedAt, setSourceHealthUpdatedAt] = useState<Date | null>(null);
  const [sourceQuery, setSourceQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');

  const [expanded, setExpanded] = useState<Record<string, boolean>>({ trading: true, risk: true });
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [runtimeLoadError, setRuntimeLoadError] = useState<string | null>(null);

  const loadSourceHealth = useCallback(async () => {
    setSourceHealthLoading(true);
    setSourceHealthError(null);
    try {
      const res = await apiClient.getFundamentalSourceHealth();
      setSourceHealth(Array.isArray(res.data) ? res.data : []);
      setSourceHealthUpdatedAt(new Date());
    } catch (error) {
      setSourceHealthError(error instanceof Error ? error.message : 'تعذر تحميل إدارة مصادر التحليل الأساسي.');
    } finally {
      setSourceHealthLoading(false);
    }
  }, []);

  // ── Session gate (بوابة الجلسات) ─────────────────────────────────────
  // Parse a /api/risk/settings payload into the ENFORCED policy state. Kept
  // separate from loadAll so a save can re-read it without reloading the page.
  const applySessionGate = useCallback((payload: unknown, ok: boolean) => {
    const gate = ok ? (payload as Record<string, any> | null)?.session_gate : undefined;
    if (typeof gate?.off_hours_allowed === 'boolean' && Array.isArray(gate.allowed_sessions)) {
      setSessionGate({
        offHoursAllowed: gate.off_hours_allowed,
        allowedSessions: gate.allowed_sessions.filter((session: unknown) => typeof session === 'string'),
      });
      setSessionGateUnavailable(false);
    } else {
      setSessionGate(null);
      setSessionGateUnavailable(true);
    }
  }, []);

  const refreshSessionGate = useCallback(async () => {
    const res = await fetch(`${API}/api/risk/settings`, { headers: getAuthHeaders() }).catch(() => null);
    if (!res) {
      applySessionGate(null, false);
      return;
    }
    let payload: unknown = null;
    try { payload = await res.json(); } catch { payload = null; }
    applySessionGate(payload, res.ok);
  }, [applySessionGate]);

  // ── Settings templates ────────────────────────────────────────────────────
  // These helpers only FILL the form; persistence still happens through the
  // existing «حفظ الكل» button (validateRuntime → POST → session-gate refresh).
  const flashTemplateMsg = useCallback((msg: string) => {
    setTemplateMsg(msg);
    setTimeout(() => setTemplateMsg(null), 7000);
  }, []);

  const loadTemplates = useCallback(async () => {
    try {
      const res = await apiClient.getSettingsTemplates();
      const data = res.data;
      if (data && typeof data.path === 'string') {
        setTemplatesPath(data.path);
        setTemplatesList(Array.isArray(data.templates) ? data.templates : []);
        setTemplatesLast(data.last ?? null);
      }
    } catch {
      // Templates are optional: the card just keeps its previous content.
    }
  }, []);

  useEffect(() => { void loadTemplates(); }, [loadTemplates]);

  // Keep only keys the form knows, clamped to the same ranges validateRuntime
  // enforces — a hand-edited file must never be able to break «حفظ الكل».
  const sanitizeTemplateValues = useCallback((values: unknown): Record<string, unknown> => {
    if (!values || typeof values !== 'object' || Array.isArray(values)) return {};
    const known = new Map<string, SettingField>();
    for (const section of RUNTIME_SECTIONS) for (const f of section.fields) known.set(f.key, f);
    known.set('allowed_sessions', {
      key: 'allowed_sessions', label: 'الجلسات المسموحة', description: '', type: 'select', options: [...SESSION_CHOICES],
    });
    const clean: Record<string, unknown> = {};
    for (const [key, raw] of Object.entries(values as Record<string, unknown>)) {
      const f = known.get(key);
      if (!f) continue;
      if (f.type === 'boolean') {
        if (typeof raw === 'boolean') clean[key] = raw;
      } else if (f.type === 'number') {
        const n = typeof raw === 'string' ? Number(raw) : raw;
        if (typeof n !== 'number' || !Number.isFinite(n)) continue;
        let v = n;
        if (f.min !== undefined) v = Math.max(f.min, v);
        if (f.max !== undefined) v = Math.min(f.max, v);
        clean[key] = v;
      } else if (f.type === 'select') {
        if (key === 'allowed_sessions') {
          if (Array.isArray(raw)) {
            clean[key] = raw.filter((s) => typeof s === 'string' && (f.options ?? []).includes(s));
          }
        } else if (f.options && f.options.includes(String(raw))) {
          clean[key] = raw;
        }
      }
    }
    return clean;
  }, []);

  const applyTemplateValues = useCallback((values: unknown, source: string) => {
    const clean = sanitizeTemplateValues(values);
    const count = Object.keys(clean).length;
    if (!count) {
      flashTemplateMsg('⚠ لا يحوي هذا القالب أي قيمة معروفة في النموذج');
      return;
    }
    setRuntime((prev) => ({ ...prev, ...clean }));
    flashTemplateMsg(`✓ عُبّئت ${count} قيمة من «${source}» — راجعها ثم اضغط «حفظ الكل»`);
  }, [sanitizeTemplateValues, flashTemplateMsg]);

  const applyTemplateFile = useCallback(async (file: string) => {
    if (!file) return;
    try {
      const res = await apiClient.loadSettingsTemplate(file);
      const data = res.data as { status?: string; name?: string; settings?: unknown; dropped?: string[] } | null;
      if (data?.status === 'ok') {
        applyTemplateValues(data.settings, data.name || file);
        if (Array.isArray(data.dropped) && data.dropped.length > 0) {
          flashTemplateMsg(`⚠ تُجاهل ${data.dropped.length} مفتاحًا غير معروف: ${data.dropped.slice(0, 4).join(', ')}`);
        }
      } else {
        flashTemplateMsg('⚠ رفض الخادم تحميل هذا القالب');
      }
    } catch (err) {
      const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : 0;
      flashTemplateMsg(
        status === 404 ? '⚠ ملف القالب غير موجود على القرص'
          : status === 403 ? '⚠ لا تملك صلاحية تحميل القوالب (403)'
            : '⚠ تعذّر تحميل القالب من الخادم'
      );
    }
  }, [applyTemplateValues, flashTemplateMsg]);

  const applyLastSettings = useCallback(() => {
    if (!templatesLast?.settings) {
      flashTemplateMsg('⚠ لا توجد نسخة «آخر إعدادات» بعد — تُنشئ مع أول حفظ');
      return;
    }
    const at = templatesLast.saved_at ? ` — ${templatesLast.saved_at}` : '';
    applyTemplateValues(templatesLast.settings, `آخر إعدادات${at}`);
  }, [templatesLast, applyTemplateValues, flashTemplateMsg]);

  const saveTemplate = useCallback(async () => {
    const name = templateName.trim();
    if (!name) {
      flashTemplateMsg('⚠ اكتب اسم القالب أولًا (حروف/أرقام/مسافات)');
      return;
    }
    try {
      const res = await apiClient.saveSettingsTemplate(name);
      const data = res.data as { status?: string; file?: string; keys?: number } | null;
      if (data?.status === 'saved') {
        flashTemplateMsg(`✓ حُفظ القالب «${data.file}» (${data.keys ?? 0} إعدادًا)`);
        setTemplateName('');
        await loadTemplates();
      } else {
        flashTemplateMsg('⚠ رفض الخادم حفظ القالب');
      }
    } catch (err) {
      const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : 0;
      const detail = err instanceof Error && err.message && err.message !== 'Unauthorized' ? ` — ${err.message}` : '';
      flashTemplateMsg(
        status === 403 ? `⚠ لا تملك صلاحية حفظ القوالب (403)${detail}`
          : status === 400 ? `⚠ اسم القالب غير صالح${detail}`
            : status === 503 ? '⚠ القرص غير متاح مؤقتًا (503) — أعد المحاولة'
              : `⚠ تعذّر حفظ ملف القالب${detail}`
      );
    }
  }, [templateName, loadTemplates, flashTemplateMsg]);

  // Browser file picker: read the chosen .json locally and fill the form —
  // no upload involved, the file never leaves this machine.
  const handleFilePick = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.json')) {
      flashTemplateMsg('⚠ اختر ملف قالب بصيغة ‎.json');
      return;
    }
    if (file.size > 1_000_000) {
      flashTemplateMsg('⚠ ملف القالب كبير جدًا (الحد الأقصى 1MB)');
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => flashTemplateMsg('⚠ تعذّرت قراءة الملف المختار');
    reader.onload = () => {
      try {
        const parsed: unknown = JSON.parse(String(reader.result ?? ''));
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          flashTemplateMsg('⚠ محتوى الملف ليس كائن JSON صالحًا');
          return;
        }
        const obj = parsed as Record<string, unknown>;
        const values = obj.settings && typeof obj.settings === 'object' && !Array.isArray(obj.settings)
          ? obj.settings
          : obj;
        applyTemplateValues(values, file.name);
      } catch {
        flashTemplateMsg('⚠ ملف القالب ليس JSON صالحًا');
      }
    };
    reader.readAsText(file);
  }, [applyTemplateValues, flashTemplateMsg]);

  // ── .env environment variables ─────────────────────────────────────────────
  // Non-fatal by design: a failing GET /api/system/env must never take the
  // whole Settings page down — the card falls back to an Arabic notice.
  const loadEnv = useCallback(async () => {
    setEnvLoading(true);
    try {
      const res = await apiClient.getSystemEnv();
      const data = res.data;
      if (data && Array.isArray(data.vars)) {
        setEnvVars(data.vars);
        setEnvFile(typeof data.env_file === 'string' ? data.env_file : '');
        setEnvSecrets(typeof data.secrets_protected === 'number' ? data.secrets_protected : 0);
        setEnvError(null);
      } else {
        setEnvError('أعاد الخادم استجابة غير متوقعة لقائمة متغيرات ملف .env');
      }
    } catch (err) {
      const detail = err instanceof Error && err.message && err.message !== 'Unauthorized' ? ` — ${err.message}` : '';
      setEnvError(`تعذّر تحميل متغيرات ملف .env من الخادم${detail}`);
    } finally {
      setEnvLoading(false);
    }
  }, []);

  useEffect(() => { void loadEnv(); }, [loadEnv]);

  // Value currently shown: a pending edit always wins over the stored one.
  const envDraft = useCallback(
    (v: SystemEnvVar): string => (envEdit[v.key] !== undefined ? envEdit[v.key] : v.value ?? ''),
    [envEdit],
  );

  const setEnvDraft = useCallback((key: string, value: string) => {
    setEnvEdit((prev) => ({ ...prev, [key]: value }));
  }, []);

  const saveEnvVar = useCallback(async (v: SystemEnvVar) => {
    const next = envDraft(v);
    if (next === (v.value ?? '')) return;
    if (v.category === 'danger') {
      const confirmed = window.confirm(
        `⚠ متغيّر خطير في ملف .env\n\n${v.key}\n${v.warning ? `${v.warning}\n\n` : ''}`
        + 'سيُحفظ في ملف .env مع إنشاء نسخة احتياطية أولًا، ولن يُفعَّل قبل إعادة تشغيل النظام.\nهل تريد المتابعة؟',
      );
      if (!confirmed) return;
    }
    try {
      const res = await apiClient.updateSystemEnv(v.key, next);
      const data = res.data as { status?: string } | null;
      if (data?.status === 'saved') {
        setEnvRowMsg((prev) => ({ ...prev, [v.key]: '✓ حُفظ — ⏳ يتطلب إعادة تشغيل' }));
        setEnvRestartPending(true);
        setEnvEdit((prev) => {
          const rest = { ...prev };
          delete rest[v.key];
          return rest;
        });
        await loadEnv(); // re-read this row's stored value from the server
      } else {
        setEnvRowMsg((prev) => ({ ...prev, [v.key]: '⚠ رفض الخادم الحفظ' }));
      }
    } catch (err) {
      const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : 0;
      const detail = err instanceof Error && err.message && err.message !== 'Unauthorized' ? ` — ${err.message}` : '';
      const msg =
        status === 401 || (err instanceof Error && err.message === 'Unauthorized')
          ? 'انتهت صلاحية الجلسة — سجّل الدخول من جديد (401)'
          : status === 403
            ? `لا تملك صلاحية تعديل ملف .env (403)${detail}`
            : status === 400
              ? `قيمة غير صالحة أو متغيّر للقراءة فقط (400)${detail}`
              : `تعذّر حفظ ${v.key}${detail}`;
      setEnvRowMsg((prev) => ({ ...prev, [v.key]: `⚠ ${msg}` }));
    }
  }, [envDraft, loadEnv]);

  // Group whatever the server returned — no hardcoded key list on this side.
  const envGroups = useMemo(() => {
    const core = envVars.filter((v) => v.category !== 'danger' && v.category !== 'readonly');
    return [
      { id: 'env-core', title: 'أساسي (Core)', items: core },
      { id: 'env-danger', title: 'خطير ⚠ (Danger)', items: envVars.filter((v) => v.category === 'danger') },
      { id: 'env-readonly', title: 'للقراءة فقط (Read-only)', items: envVars.filter((v) => v.category === 'readonly') },
    ];
  }, [envVars]);

  // Control for one .env row, chosen by the server-declared type.
  // Every value on the wire is a string (env files are text).
  const envInput = (v: SystemEnvVar, draft: string, disabled: boolean) => {
    const base =
      'w-full bg-bg-tertiary border border-border-primary text-text-secondary text-[10px] font-mono px-2 py-1.5 rounded focus:outline-none focus:border-neon-purple/40';
    const placeholder = draft === '' ? 'غير معرّف في الملف' : undefined;
    const commit = (raw: string) => setEnvDraft(v.key, raw);

    if (v.type === 'bool') {
      const known = draft === '1' || draft === '0';
      return (
        <select
          dir="ltr"
          disabled={disabled}
          value={known ? draft : ''}
          onChange={(e) => commit(e.target.value)}
          className={cn(base, 'cursor-pointer')}
        >
          {!known && <option value="">{placeholder ?? 'غير معرّف في الملف'}</option>}
          <option value="1">نعم (1)</option>
          <option value="0">لا (0)</option>
        </select>
      );
    }

    if (v.type === 'enum') {
      const choices = Array.isArray(v.choices) ? v.choices : [];
      const known = choices.includes(draft);
      return (
        <select
          dir="ltr"
          disabled={disabled}
          value={known ? draft : ''}
          onChange={(e) => commit(e.target.value)}
          className={cn(base, 'cursor-pointer')}
        >
          {!known && <option value="">{placeholder ?? 'غير معرّف في الملف'}</option>}
          {choices.map((choice) => (
            <option key={choice} value={choice}>{choice}</option>
          ))}
        </select>
      );
    }

    if (v.type === 'int' || v.type === 'float') {
      return (
        <input
          dir="ltr"
          type="number"
          value={draft}
          placeholder={placeholder}
          min={v.min}
          max={v.max}
          step={v.type === 'float' ? 'any' : 1}
          disabled={disabled}
          onChange={(e) => commit(e.target.value)}
          className={base}
        />
      );
    }

    return (
      <input
        dir="ltr"
        type="text"
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => commit(e.target.value)}
        className={base}
      />
    );
  };

  const loadAll = useCallback(async () => {
    // Every request is settled individually: one failing endpoint must never
    // abort the others or leave a section stuck on its "loading" state.
    try {
      const [settRes, tRes, healthRes, posRes, riskSettingsRes, modeRes] = await Promise.all([
        fetch(`${API}/api/intelligence/settings`, { headers: getAuthHeaders() }).catch(() => null),
        fetch(`${API}/api/regime/thresholds`, { headers: getAuthHeaders() }).catch(() => null),
        apiClient.getHealth().catch(() => null),
        apiClient.getPositionsSnapshot().catch(() => null),
        fetch(`${API}/api/risk/settings`, { headers: getAuthHeaders() }).catch(() => null),
        apiClient.getSystemMode().catch(() => null),
      ]);

      // ── Runtime settings (Redis via /api/intelligence/settings) ──
      let settPayload: any = null;
      if (!settRes) {
        setRuntimeLoadError('تعذر الوصول إلى الخادم لجلب الإعدادات التشغيلية — تحقق من الاتصال بالشبكة.');
      } else if (settRes.ok) {
        try { settPayload = await settRes.json(); } catch { settPayload = null; }
        const payload = settPayload;
        // HTTP 200 with an error marker means Redis is down: keep the last
        // loaded values and flag the panel instead of showing empty fields
        // that look like confirmed defaults.
        if (payload?.error) {
          setRuntimeLoadError('تعذر قراءة الإعدادات من مخزن الخادم مؤقتًا — القيم المعروضة قد تكون قديمة.');
        } else if (
          payload && typeof payload.settings === 'object' && payload.settings !== null &&
          !Array.isArray(payload.settings)
        ) {
          setRuntime(payload.settings);
          setRuntimeOrig(payload.settings);
          setRuntimeLoadError(null);
        } else {
          setRuntimeLoadError('استجابة غير متوقعة من الخادم — لا يمكن قراءة الإعدادات التشغيلية.');
        }
      } else {
        let detail = '';
        try { detail = String((await settRes.json())?.detail || ''); } catch { /* body already consumed */ }
        setRuntimeLoadError(
          settRes.status === 401
            ? 'انتهت صلاحية الجلسة — سجّل الدخول من جديد لعرض الإعدادات التشغيلية.'
            : settRes.status === 403
              ? `لا تملك صلاحية عرض الإعدادات التشغيلية${detail ? ` — ${detail}` : ''}.`
              : settRes.status === 503
                ? 'مخزن الإعدادات التشغيلية غير متاح مؤقتًا — أعد المحاولة بعد قليل.'
                : `تعذر جلب الإعدادات التشغيلية (HTTP ${settRes.status}).`
        );
      }

      // ── Server defaults (optional `defaults` sibling of `settings`) ──
      // Display-only fallback for keys the user has never stored; kept out of
      // `runtime` on purpose so runtimeChanged/save never push default values.
      if (settPayload && !settPayload.error) {
        const d = settPayload.defaults;
        setRuntimeDefaults(
          d && typeof d === 'object' && !Array.isArray(d) ? d : {}
        );
      }

      // ── Authoritative PAPER/LIVE mode (GET /api/system/mode) ──
      const rawMode = typeof modeRes?.data?.mode === 'string' ? modeRes.data.mode.toUpperCase() : '';
      setSystemMode(rawMode === 'PAPER' || rawMode === 'LIVE' ? rawMode : null);

      // ── Dynamic thresholds (TradeMemory) ──
      if (!tRes) {
        setThresholdsState('error');
      } else if (tRes.ok) {
        try {
          const th = await tRes.json();
          // A 200 {"error": ...} payload means "nothing computed yet" — it is
          // NOT data, and rendering it would show fabricated 0% values.
          if (th && !th.error && typeof th === 'object') {
            setDynamicThresholds(th);
            setThresholdsState('ready');
          } else {
            setDynamicThresholds(null);
            setThresholdsState('empty');
          }
        } catch {
          setDynamicThresholds(null);
          setThresholdsState('error');
        }
      } else {
        setThresholdsState('error');
      }

      // ── Live session gate (risk service) ──
      if (riskSettingsRes?.ok) {
        let riskPayload: unknown = null;
        try { riskPayload = await riskSettingsRes.json(); } catch { riskPayload = null; }
        applySessionGate(riskPayload, true);
      } else {
        applySessionGate(null, false);
      }

      if (healthRes?.data) {
        const redisOk = healthRes.data.components?.some((c: any) => c.name === 'redis' && c.status === 'healthy');
        setWsConnected(Boolean(redisOk));
      }
      if (posRes?.data) setMt5Connected(Boolean(posRes.data.live_connected));
    } catch {
      // Last line of defence: a silent failure must still surface as an error
      // state instead of an empty panel that looks like confirmed defaults.
      setRuntimeLoadError((prev) => prev ?? 'تعذر تحميل الإعدادات التشغيلية من الخادم.');
    }
  }, [applySessionGate]);

  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 30000);
    return () => clearInterval(t);
  }, [loadAll]);


  useEffect(() => {
    loadSourceHealth();
    const t = setInterval(loadSourceHealth, 30000);
    return () => clearInterval(t);
  }, [loadSourceHealth]);

  // localStorage only exists in the browser: hydrate AFTER mount so the first
  // client render matches the server HTML (otherwise React reports a hydration
  // mismatch whenever the stored prefs differ from the defaults).
  useEffect(() => {
    const stored = readLocalSettings();
    setLocal(stored);
    setLocalOrig(stored);
  }, []);

  const filteredSourceHealth = useMemo(() => {
    const q = sourceQuery.trim().toLowerCase();
    return sourceHealth.filter((source) => {
      const matchesFilter = sourceFilter === 'all' || source.health === sourceFilter;
      const haystack = `${source.source_id} ${source.name_ar} ${source.name_en} ${source.health_description_ar}`.toLowerCase();
      return matchesFilter && (!q || haystack.includes(q));
    });
  }, [sourceHealth, sourceFilter, sourceQuery]);

  const setRuntimeField = (key: string, value: any) => setRuntime((previous) => {
    const next = { ...previous };
    if (value == null) delete next[key];
    else next[key] = value;
    return next;
  });
  const setLocalField = <K extends keyof UiSettings>(key: K, value: UiSettings[K]) =>
    setLocal((p) => ({ ...p, [key]: value }));

  const runtimeChanged = JSON.stringify(runtime) !== JSON.stringify(runtimeOrig);
  const localChanged = JSON.stringify(local) !== JSON.stringify(localOrig);

  // Session-gate draft: what the toggle/chips edit before «حفظ». Falls back to
  // the enforced server state while the runtime document is still loading.
  const draftOffHours = typeof runtime.off_hours_allowed === 'boolean' ? runtime.off_hours_allowed : false;
  const draftSessions: string[] = Array.isArray(runtime.allowed_sessions)
    ? runtime.allowed_sessions.filter((s: unknown) => typeof s === 'string')
    : (sessionGate?.allowedSessions ?? []);
  const toggleSession = (name: string) => {
    const next = draftSessions.includes(name)
      ? draftSessions.filter((s) => s !== name)
      : [...draftSessions, name];
    setRuntimeField('allowed_sessions', next);
  };

  // Refuse to push out-of-range values: this route stores what it is given
  // (no clamping), so a bad number would silently become live policy.
  const validateRuntime = (): string | null => {
    for (const section of RUNTIME_SECTIONS) {
      for (const f of section.fields) {
        const v = runtime[f.key];
        if (v === undefined || v === null) continue;
        if (f.type === 'number') {
          if (typeof v !== 'number' || !Number.isFinite(v)) return `قيمة غير صالحة في «${f.label}».`;
          if (f.min !== undefined && v < f.min) return `«${f.label}» أقل من الحد الأدنى (${f.min}${f.unit ? ` ${f.unit}` : ''}).`;
          if (f.max !== undefined && v > f.max) return `«${f.label}» أعلى من الحد الأقصى (${f.max}${f.unit ? ` ${f.unit}` : ''}).`;
        } else if (f.type === 'select' && f.options && !f.options.includes(String(v))) {
          return `قيمة غير مدعومة في «${f.label}»: ${String(v)}.`;
        } else if (f.type === 'boolean' && typeof v !== 'boolean') {
          return `قيمة غير صالحة في «${f.label}» (true/false فقط).`;
        }
      }
    }
    return null;
  };

  const describeSaveError = (err: unknown): string => {
    const status = typeof (err as { status?: unknown })?.status === 'number' ? (err as { status: number }).status : 0;
    const detail = err instanceof Error && err.message && err.message !== 'Unauthorized' ? ` — ${err.message}` : '';
    if (status === 401 || (err instanceof Error && err.message === 'Unauthorized')) {
      return 'انتهت صلاحية الجلسة — سجّل الدخول من جديد (401)';
    }
    if (status === 403) return `لا تملك صلاحية حفظ الإعدادات التشغيلية (403)${detail}`;
    if (status === 503) return 'مخزن الإعدادات غير متاح مؤقتًا (503) — أعد المحاولة لاحقًا';
    if (!status) return `تعذّرت مزامنة الإعدادات التشغيلية — تعذر الوصول إلى الخادم${detail}`;
    return `تعذّرت مزامنة الإعدادات التشغيلية (HTTP ${status})${detail}`;
  };

  const save = async () => {
    const invalid = validateRuntime();
    if (invalid) {
      setSaveMsg(`⚠ ${invalid}`);
      setTimeout(() => setSaveMsg(null), 7000);
      return;
    }
    setSaving(true);
    const messages: string[] = [];
    let runtimeSaved = true;
    try {
      if (runtimeChanged) {
        // Save runtime settings to Redis. The gateway may answer HTTP 200 even
        // on failure with {status:'error'} — only 'saved' means persistence landed.
        try {
          const runtimePatch: Record<string, unknown> = { ...runtime };
          for (const key of Object.keys(runtimeOrig)) {
            if (!(key in runtime)) runtimePatch[key] = null;
          }
          const res = await apiClient.updateDynamicSettings(runtimePatch);
          if (res.data?.status === 'saved') {
            setRuntimeOrig({ ...runtime });
            setRuntimeLoadError(null);
            messages.push('تمت مزامنة الإعدادات التشغيلية');
            // Re-read the enforced gate: nexus-risk caches the document for 5s,
            // so refresh now (in case the TTL already elapsed) and once more
            // after the cache window to show the value actually applied.
            void refreshSessionGate();
            setTimeout(() => { void refreshSessionGate(); }, 5500);
          } else {
            runtimeSaved = false;
            messages.push('لم تُحفظ الإعدادات التشغيلية — رفض الخادم التحديث');
          }
        } catch (err) {
          runtimeSaved = false;
          messages.push(describeSaveError(err));
        }
      }

      // Local preferences live in this browser only (localStorage).
      if (localChanged) {
        if (writeLocalSettings(local)) {
          setLocalOrig({ ...local });
          messages.push('حُفظت التفضيلات المحلية');
        } else {
          messages.push('تعذّر حفظ التفضيلات المحلية (التخزين غير متاح)');
        }
      }

      // A failed runtime sync must not read like a success.
      if (messages.length > 0) {
        setSaveMsg(runtimeSaved ? `✓ ${messages.join(' · ')}` : `⚠ ${messages.join(' · ')}`);
      }
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 7000);
    }
  };

  const reset = () => {
    setRuntime({ ...runtimeOrig });
    setLocal({ ...localOrig });
  };

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Page header */}
      <div dir="rtl" className="sticky top-0 z-10 flex items-center gap-3 px-4 py-3 bg-bg-secondary/95 backdrop-blur border-b border-border-primary">
        <Settings className="h-4 w-4 text-neon-purple" />
        <span className="text-[13px] font-mono font-bold text-text-primary tracking-wider">لوحة الإعدادات</span>
        <ModeBadge mode={systemMode} />
        <span className="text-[9px] font-mono text-text-muted ms-1">لا قيم ثابتة · كل شيء قابل للتعديل</span>
        <div className="flex-1" />
        {saveMsg && (
          <span className={cn('text-[10px] font-mono', saveMsg.startsWith('⚠') ? 'text-neon-gold' : 'text-neon-cyan')}>
            {saveMsg}
          </span>
        )}
        {(runtimeChanged || localChanged) && (
          <button onClick={reset} className="flex items-center gap-1.5 px-3 py-1 rounded text-[10px] font-mono text-text-muted hover:text-text-secondary border border-border-primary transition-all">
            <RotateCcw className="h-3 w-3" />
            تراجع
          </button>
        )}
        <button
          onClick={save}
          disabled={(!runtimeChanged && !localChanged) || saving}
          className={cn(
            'flex items-center gap-1.5 px-4 py-1.5 rounded text-[11px] font-mono font-bold border transition-all',
            (runtimeChanged || localChanged) && !saving
              ? 'bg-neon-purple/20 text-neon-purple border-neon-purple/40 hover:bg-neon-purple/30'
              : 'text-text-muted border-border-primary cursor-not-allowed'
          )}
        >
          {saving
            ? <><span className="animate-pulse">●</span> جارٍ الحفظ...</>
            : <><Save className="h-3 w-3" /> حفظ الكل</>
          }
        </button>
      </div>

      <div className="border-b border-border-primary bg-bg-secondary/70 px-4">
        <div className="mx-auto flex max-w-[1400px] gap-1" dir="rtl">
          <button type="button" onClick={()=>setActiveTab('brokers')}
            className={cn('border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',activeTab==='brokers'?'border-neon-cyan text-neon-cyan':'border-transparent text-text-muted')}>
            الوسيط والحسابات
          </button>
          <button type="button" onClick={()=>setActiveTab('ea_bridge')}
            className={cn('border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',activeTab==='ea_bridge'?'border-neon-cyan text-neon-cyan':'border-transparent text-text-muted')}>
            جسر MT5
          </button>
          <button type="button" onClick={()=>setActiveTab('research_lab')}
            className={cn('border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',activeTab==='research_lab'?'border-neon-cyan text-neon-cyan':'border-transparent text-text-muted')}>
            مختبر البيانات والبحث
          </button>
          <button type="button" onClick={()=>setActiveTab('news_ticker')}
            className={cn('flex items-center gap-2 border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',activeTab==='news_ticker'?'border-neon-gold text-neon-gold':'border-transparent text-text-muted hover:text-text-secondary')}>
            <BellRing className="h-3.5 w-3.5" />
            التحكم بالشريط الإخباري والصوت
          </button>
          <button
            onClick={() => setActiveTab('general')}
            className={cn(
              'border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',
              activeTab === 'general'
                ? 'border-neon-purple text-neon-purple'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            )}
          >
            الإعدادات العامة
          </button>
          <button
            onClick={() => setActiveTab('fundamental_sources')}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',
              activeTab === 'fundamental_sources'
                ? 'border-neon-cyan text-neon-cyan'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            )}
          >
            <Activity className="h-3.5 w-3.5" />
            إدارة مصادر التحليل الأساسي
          </button>
          <button
            onClick={() => setActiveTab('users_alerts')}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',
              activeTab === 'users_alerts'
                ? 'border-neon-purple text-neon-purple'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            )}
          >
            <Bell className="h-3.5 w-3.5" />
            مركز المستخدمين والتنبيهات
          </button>
          <button
            onClick={() => setActiveTab('project')}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-2.5 text-[11px] font-mono font-bold transition-colors',
              activeTab === 'project'
                ? 'border-neon-cyan text-neon-cyan'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            )}
          >
            <Activity className="h-3.5 w-3.5" />
            المشروع والتدقيق
          </button>
        </div>
      </div>

      {activeTab === 'general' ? (
      <div dir="rtl" className="flex flex-col gap-4 p-4 max-w-[1400px] mx-auto w-full lg:flex-row">
        {/* Left: runtime + local sections */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">

          {runtimeLoadError && (
            <div role="alert" className="rounded-lg border border-neon-gold/30 bg-neon-gold/5 px-3 py-2 text-[10px] font-mono text-neon-gold">
              {runtimeLoadError} القيم المعروضة أدناه قد تكون قديمة وليست الحالة الحالية.
            </div>
          )}
          {!runtimeLoadError && Object.keys(runtime).length === 0 && (
            <div role="status" className="rounded-lg border border-border-primary bg-bg-secondary/60 px-3 py-2 text-[10px] font-mono text-text-muted">
              لا توجد تعديلات تشغيلية محفوظة. الخيارات غير المضبوطة تستخدم إعدادات النظام الافتراضية حيثما كانت مدعومة.
            </div>
          )}

          {/* ── Settings templates (JSON files on disk) ── */}
          <SectionCard
            id="templates" label="قوالب الإعدادات (Templates)" icon={FolderOpen} color="text-neon-gold"
            expanded={expanded} setExpanded={setExpanded}
            hint="احفظ إعداداتك كملف JSON وحمّل قالبًا محفوظًا أو افتح ملفًا من جهازك — القوالب تعبئة النموذج فقط، لا يُكتب أي شيء فعليًا إلا بعد «حفظ الكل»"
          >

            {/* Compact template controls — one wrapping flow, no half-empty rows */}
            <div className="flex flex-wrap items-center gap-2">
              {templatesPath && (
                <div
                  title="مسار حفظ القوالب"
                  className="flex items-center gap-1.5 rounded-lg border border-neon-gold/30 bg-neon-gold/5 px-2.5 py-1.5"
                >
                  <FolderOpen className="h-3.5 w-3.5 shrink-0 text-neon-gold" />
                  <span className="text-[9px] font-mono text-neon-gold" dir="ltr">{templatesPath}</span>
                </div>
              )}
              <input
                type="text"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                maxLength={64}
                placeholder="اسم القالب الجديد (حروف/أرقام/مسافات)"
                className="w-[190px] rounded border border-border-primary bg-bg-input px-2.5 py-1.5 text-[10px] font-mono text-text-primary placeholder:text-text-muted focus:border-neon-purple/50 focus:outline-none"
                dir="rtl"
              />
              <button
                type="button"
                onClick={() => void saveTemplate()}
                className="flex items-center gap-1.5 rounded border border-neon-purple/40 bg-neon-purple/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-purple hover:bg-neon-purple/20 transition-all"
              >
                <Save className="h-3 w-3" /> حفظ الإعدادات الحالية كقالب
              </button>
              <select
                value={selectedTemplate}
                onChange={(e) => setSelectedTemplate(e.target.value)}
                className="w-[190px] rounded border border-border-primary bg-bg-input px-2 py-1.5 text-[10px] font-mono text-text-primary focus:border-neon-cyan/50 focus:outline-none"
                dir="rtl"
              >
                <option value="">— اختر قالبًا محفوظًا —</option>
                {templatesList.map((t) => (
                  <option key={t.file} value={t.file} disabled={!t.valid} title={t.description || t.file}>
                    {!t.valid ? '⚠ ' : ''}{t.name}{t.builtin ? ' ★' : ''} ({t.keys} إعدادًا)
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void applyTemplateFile(selectedTemplate)}
                disabled={!selectedTemplate}
                className={cn(
                  'flex items-center gap-1.5 rounded border px-3 py-1.5 text-[10px] font-mono font-bold transition-all',
                  selectedTemplate
                    ? 'border-neon-cyan/40 bg-neon-cyan/10 text-neon-cyan hover:bg-neon-cyan/20'
                    : 'border-border-primary text-text-muted cursor-not-allowed'
                )}
              >
                <Upload className="h-3 w-3" /> تحميل إلى النموذج
              </button>
              <button
                type="button"
                onClick={() => void applyTemplateFile('optimal.json')}
                title="قالب مدمج: مخاطرة 0.5% · RR 2.0 · جلسات سيولة فقط"
                className="flex items-center gap-1.5 rounded border border-yellow-500/40 bg-yellow-500/10 px-3 py-1.5 text-[10px] font-mono font-bold text-yellow-400 hover:bg-yellow-500/20 transition-all"
              >
                <Sparkles className="h-3 w-3" /> أفضل الإعدادات (مدمج)
              </button>
              <button
                type="button"
                onClick={applyLastSettings}
                disabled={!templatesLast}
                className={cn(
                  'flex items-center gap-1.5 rounded border px-3 py-1.5 text-[10px] font-mono font-bold transition-all',
                  templatesLast
                    ? 'border-neon-green/40 bg-neon-green/10 text-neon-green hover:bg-neon-green/20'
                    : 'border-border-primary text-text-muted cursor-not-allowed'
                )}
                title={templatesLast ? `آخر حفظ: ${templatesLast.saved_at}` : 'ستتوفر نسخة بعد أول حفظ'}
              >
                <Undo2 className="h-3 w-3" /> آخر إعدادات (تراجع)
              </button>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex items-center gap-1.5 rounded border border-border-primary bg-bg-input px-3 py-1.5 text-[10px] font-mono font-bold text-text-secondary hover:text-text-primary transition-all"
              >
                <FolderOpen className="h-3 w-3" /> فتح ملف من الجهاز…
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={handleFilePick}
              />
            </div>

            <div className="mt-1 flex items-center justify-between gap-2">
              <span role="status" className="text-[9px] font-mono text-neon-cyan">{templateMsg}</span>
              <button
                type="button"
                onClick={() => void loadTemplates()}
                className="flex items-center gap-1 text-[9px] font-mono text-text-muted hover:text-text-secondary transition-colors"
              >
                <RefreshCcw className="h-3 w-3" /> تحديث القائمة
              </button>
            </div>
          </SectionCard>

          {/* ── .env environment variables (on-disk file, restart-gated) ── */}
          <SectionCard
            id="env" label="بيئة النظام (.env)" icon={FileCog} color="text-neon-gold"
            expanded={expanded} setExpanded={setExpanded}
            hint="قيم ملف .env على القرص — الحفظ ينشئ .env.bak ثم يكتب ذريًا، والتغييرات لا تُفعَّل إلا بعد إعادة تشغيل كاملة (بإذن المشغّل) — الأسرار (PIN · MT5 · مفاتيح API) لا تُعرض ولا تُعدَّل من هنا إطلاقًا"
          >

            <div className="mb-1 flex items-center gap-2 rounded-lg border border-neon-cyan/30 bg-neon-cyan/5 px-3 py-2">
              <Shield className="h-3.5 w-3.5 shrink-0 text-neon-cyan" />
              <span className="text-[10px] font-mono text-neon-cyan" dir="rtl">
                🛡️ {envSecrets} متغيرات أسرار محمية — محجوبة عن هذه الواجهة
              </span>
            </div>

            {envRestartPending && (
              <div
                role="status"
                className="rounded-lg border border-neon-gold/40 bg-neon-gold/10 px-3 py-2 text-[10px] font-mono font-bold text-neon-gold"
              >
                ⏳ تغييرات محفوظة في .env — تُفعَّل بعد إعادة تشغيل النظام فقط (لا تُعِد التشغيل دون إذن)
              </div>
            )}

            {envLoading && envVars.length === 0 && (
              <span role="status" className="text-[9px] font-mono text-text-muted">
                جارٍ تحميل متغيرات ملف .env…
              </span>
            )}

            {envError && (
              <p role="alert" className="rounded-lg border border-neon-red/30 bg-neon-red/5 px-3 py-2 text-[10px] font-mono leading-relaxed text-neon-red">
                {envError}
                {envVars.length > 0 ? ' — القيم أدناه كما هي آخر قراءة ناجحة.' : ' لا توجد قيم لعرضها حاليًا.'}
              </p>
            )}

            {envGroups.map((group) => (
              <div key={group.id} className="flex flex-col gap-2">
                <div className="border-b border-border-primary pb-1 text-[10px] font-mono font-bold text-text-secondary">
                  {group.title}
                </div>
                {group.items.length === 0 && (
                  <span className="text-[9px] font-mono text-text-muted">— لا توجد متغيرات في هذه المجموعة.</span>
                )}
                {/* شبكة متجاوبة: استغلال المساحة الأفقية بدل عمود واحد مهدر */}
                <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3 items-start">
                {group.items.map((v) => {
                  const draft = envDraft(v);
                  const changed = draft !== (v.value ?? '');
                  const locked = !v.editable || v.category === 'readonly';
                  const msg = envRowMsg[v.key];
                  const failed = Boolean(msg && msg.startsWith('⚠'));
                  return (
                    <div
                      key={v.key}
                      className={cn(
                        'flex flex-col gap-1.5 rounded-lg border px-3 py-2',
                        v.category === 'danger'
                          ? 'border-neon-red/40 bg-neon-red/5'
                          : 'border-border-primary bg-bg-secondary/40'
                      )}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[10px] font-mono font-bold text-text-primary" dir="ltr">{v.key}</span>
                        {v.category === 'readonly' && (
                          <span className="rounded border border-border-primary bg-bg-tertiary px-1.5 py-0.5 text-[9px] font-mono text-text-muted">
                            للقراءة فقط
                          </span>
                        )}
                        {v.category === 'danger' && (
                          <span className="rounded border border-neon-red/40 bg-neon-red/10 px-1.5 py-0.5 text-[9px] font-mono font-bold text-neon-red">
                            ⚠ خطير
                          </span>
                        )}
                        {!v.editable && v.category !== 'readonly' && (
                          <span className="rounded border border-border-primary bg-bg-tertiary px-1.5 py-0.5 text-[9px] font-mono text-text-muted">
                            مقفل
                          </span>
                        )}
                      </div>
                      <div className="text-[9px] font-mono text-text-muted leading-relaxed">{v.description}</div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="min-w-[140px] flex-1">{envInput(v, draft, locked)}</div>
                        <button
                          type="button"
                          disabled={!changed || locked}
                          onClick={() => void saveEnvVar(v)}
                          className={cn(
                            'flex items-center gap-1.5 rounded border px-3 py-1.5 text-[10px] font-mono font-bold transition-all',
                            changed && !locked
                              ? v.category === 'danger'
                                ? 'border-neon-red/40 bg-neon-red/10 text-neon-red hover:bg-neon-red/20'
                                : 'border-neon-purple/40 bg-neon-purple/10 text-neon-purple hover:bg-neon-purple/20'
                              : 'border-border-primary text-text-muted cursor-not-allowed'
                          )}
                        >
                          <Save className="h-3 w-3" /> حفظ
                        </button>
                        <span
                          role={failed ? 'alert' : 'status'}
                          className={cn('text-[9px] font-mono', failed ? 'text-neon-red' : 'text-neon-cyan')}
                        >
                          {msg}
                        </span>
                      </div>
                    </div>
                  );
                })}
                </div>
              </div>
            ))}

            <div className="mt-1 flex items-center justify-between gap-2">
              <span className="min-w-0 truncate text-[9px] font-mono text-neon-gold" dir="ltr" title={envFile}>
                {envFile || '—'}
              </span>
              <button
                type="button"
                onClick={() => void loadEnv()}
                disabled={envLoading}
                className={cn(
                  'flex shrink-0 items-center gap-1 text-[9px] font-mono transition-colors',
                  envLoading
                    ? 'text-text-muted cursor-not-allowed'
                    : 'text-text-muted hover:text-text-secondary'
                )}
              >
                <RefreshCcw className="h-3 w-3" /> تحديث
              </button>
            </div>
          </SectionCard>

          {/* ── Local section (notifications only) ── */}
          <SectionCard
            id="local" label="وضع التشغيل" icon={Globe} color="text-text-secondary"
            expanded={expanded} setExpanded={setExpanded}
            hint="PAPER/LIVE لا يُغيّران من هنا — الحالة تُجلب من الخادم (‎/api/system/mode) ولا يُعتمد أي تغيير إلا بعد تأكيد الخادم (الصلاحية/PIN)"
          >
            <div className="flex items-center justify-between gap-3 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="text-[10px] font-mono font-bold text-text-secondary">وضع التداول</div>
                <div className="text-[9px] font-mono text-text-muted mt-0.5 leading-relaxed">
                  الحالة المعتمدة من الخادم (GET /api/system/mode).
                </div>
              </div>
              <ModeBadge mode={systemMode} />
            </div>
            <div className="flex items-center justify-between gap-3 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="text-[10px] font-mono font-bold text-text-secondary">التداول الآلي (Auto-Trade)</div>
                <div className="text-[9px] font-mono text-text-muted mt-0.5 leading-relaxed">
                  التفعيل/الإيقاف يتحقق منه الخادم (صلاحية + PIN) قبل التطبيق.
                </div>
              </div>
              <div className="shrink-0">
                <AutoTradeToggle compact />
              </div>
            </div>
            <FieldRow
              field={{ key: 'soundAlerts', label: 'تنبيهات صوتية', type: 'boolean', description: 'صوت عند تنفيذ الصفقات والإشارات.' }}
              value={local.soundAlerts}
              onChange={(v) => setLocalField('soundAlerts', v)}
            />
            <FieldRow
              field={{ key: 'desktopNotifications', label: 'إشعارات سطح المكتب', type: 'boolean', description: 'إشعارات النظام عندما تكون التبويب غير نشط.' }}
              value={local.desktopNotifications}
              onChange={(v) => setLocalField('desktopNotifications', v)}
            />
          </SectionCard>

          <SectionCard
            id="session_gate" label="بوابة الجلسات الفعلية" icon={Shield} color="text-neon-cyan"
            expanded={expanded} setExpanded={setExpanded}
            hint="تُفرض على مستوى الخادم بساعة الخادم: تُحدد جلسات التداول المسموحة — تُحفظ بزر «حفظ» وتُطبَّق فورًا دون إعادة تشغيل"
          >

            <FieldRow
              field={{
                key: 'off_hours_allowed',
                label: 'السماح خارج الجلسات (OFF_HOURS)',
                type: 'boolean',
                description: 'ON = لا تُحجب الجلسات خارج القائمة أدناه. OFF = تُرفض أي صفقة خارج الجلسات المحددة.',
              }}
              value={draftOffHours}
              onChange={(v) => setRuntimeField('off_hours_allowed', Boolean(v))}
            />

            <div className="py-1.5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-mono font-bold text-text-secondary">الجلسات المسموحة (allowed_sessions)</span>
                <span className="text-[9px] font-mono text-text-muted">{draftSessions.length}/{SESSION_CHOICES.length}</span>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {SESSION_CHOICES.map((name) => {
                  const active = draftSessions.includes(name);
                  return (
                    <button
                      key={name}
                      type="button"
                      aria-pressed={active}
                      onClick={() => toggleSession(name)}
                      title={active ? `إزالة ${name} من المسموح` : `السماح بجلسة ${name}`}
                      className={cn(
                        'px-2.5 py-1 rounded border text-[9px] font-mono font-bold transition-all',
                        active
                          ? 'bg-neon-cyan/10 text-neon-cyan border-neon-cyan/30'
                          : 'bg-bg-input text-text-muted border-border-primary hover:text-text-secondary'
                      )}
                    >
                      {active ? '✓ ' : '+ '}{name}
                    </button>
                  );
                })}
              </div>
              <div className="mt-1.5 text-[9px] font-mono text-text-muted leading-relaxed">
                القيم بالإنجليزية لأن الخادم يقارنها كما هي (SYDNEY · TOKYO · LONDON · NEW_YORK · OVERLAP).
              </div>
            </div>

            {draftSessions.length === 0 && !draftOffHours && (
              <p role="alert" className="rounded-lg border border-neon-red/30 bg-neon-red/5 px-3 py-2 text-[9px] font-mono leading-relaxed text-neon-red">
                لا توجد أي جلسة مسموحة والسماح خارج الجلسات مطفأ — ستُرفض كل الصفقات. أضِف جلسة أو فعّل «السماح خارج الجلسات».
              </p>
            )}

            <div className="mt-1 rounded-lg border border-border-primary bg-bg-secondary/60 px-3 py-2">
              <span className="text-[10px] font-mono font-bold text-text-secondary">الحالة الفعلية المفروضة الآن: </span>
              {sessionGate ? (
                <span className="text-[10px] font-mono text-text-muted">
                  خارج الجلسات:{' '}
                  <b className={cn('font-bold', sessionGate.offHoursAllowed ? 'text-neon-green' : 'text-neon-red')}>
                    {sessionGate.offHoursAllowed ? 'ON' : 'OFF'}
                  </b>{' '}
                  · الجلسات: <b className="font-bold text-neon-cyan">{sessionGate.allowedSessions.join(', ') || 'لا توجد'}</b>
                </span>
              ) : (
                <span role={sessionGateUnavailable ? 'alert' : 'status'} className="text-[10px] font-mono text-text-muted">
                  {sessionGateUnavailable ? 'تعذّر جلبها من خدمة المخاطر.' : 'جارٍ التحميل من خدمة المخاطر…'}
                </span>
              )}
            </div>
          </SectionCard>

          {/* ── Runtime sections from Redis ── */}
          {RUNTIME_SECTIONS.map((section) => (
            <SectionCard
              key={section.id} id={section.id} label={section.label}
              icon={section.icon} color={section.color}
              expanded={expanded} setExpanded={setExpanded}
            >
              {/* شبكة بطاقات مدمجة: عدد الأعمدة يطابق عدد الحقول — لا صف يحمل عمودًا ميتًا */}
              <div className={cn('grid items-start gap-2 sm:grid-cols-2', section.gridCols ?? '2xl:grid-cols-3')}>
                {section.fields.map((f) => (
                  <FieldRow
                    key={f.key}
                    field={f}
                    value={runtime[f.key] !== undefined ? runtime[f.key] : runtimeDefaults[f.key]}
                    onChange={(v) => setRuntimeField(f.key, v)}
                  />
                ))}
              </div>
            </SectionCard>
          ))}

        </div>

        {/* Side panel — under RTL it sits on the left; sticky + capped height so
            it tracks the main column instead of leaving an empty gap. */}
        <div className="w-full shrink-0 flex flex-col gap-3 lg:w-80 2xl:w-96 lg:sticky lg:top-14 lg:self-start lg:max-h-[calc(100vh_-_4.5rem)] lg:overflow-y-auto">
          <div className="border border-neon-purple/20 rounded-lg p-3 bg-neon-purple/5">
            <div className="text-[9px] font-mono text-neon-purple mb-2 tracking-wider font-bold">العتبات الديناميكية (TradeMemory)</div>
            {thresholdsState === 'ready' && dynamicThresholds ? (
              <div className="flex flex-col gap-1.5">
                <ThreshRow label="أدنى Quality score" value={`${dynamicThresholds.quality_score_threshold ?? '--'}/100`} />
                <ThreshRow label="أدنى Conviction" value={`${((dynamicThresholds.conviction_min ?? 0) * 100).toFixed(0)}%`} />
                <ThreshRow
                  label="Win Rate العام"
                  value={`${((dynamicThresholds.overall_wr ?? 0) * 100).toFixed(1)}%`}
                  color={dynamicThresholds.overall_wr >= 0.5 ? 'text-neon-green' : dynamicThresholds.overall_wr >= 0.4 ? 'text-yellow-400' : 'text-neon-red'}
                />
                <ThreshRow label="عدد الصفقات" value={String(dynamicThresholds.total_trades ?? 0)} />
                <ThreshRow
                  label="Risk/Reward (RR)"
                  value={
                    typeof dynamicThresholds.avg_rr === 'number' && Number.isFinite(dynamicThresholds.avg_rr)
                      ? dynamicThresholds.avg_rr.toFixed(2)
                      : '--'
                  }
                />
                {/* ATR (14) intentionally omitted: the /api/regime/thresholds
                    payload carries no ATR value, and the page never prints a
                    fabricated number. */}
              </div>
            ) : (
              <div role={thresholdsState === 'error' ? 'alert' : 'status'} className="text-[9px] font-mono text-text-muted">
                {thresholdsState === 'loading'
                  ? 'جارٍ التحميل...'
                  : thresholdsState === 'empty'
                    ? 'لا توجد بيانات بعد — تُحسب العتبات بعد أول الصفقات.'
                    : 'تعذر جلب العتبات الديناميكية من الخادم.'}
              </div>
            )}
            <div className="mt-2 text-[8px] font-mono text-text-muted">
              تُحسب تلقائيًا من نتائج حقيقية · تُحدَّث بعد كل صفقة.
            </div>
          </div>

          {dynamicThresholds?.bad_hours?.length > 0 && (
            <div className="border border-neon-red/20 rounded-lg p-3 bg-neon-red/5">
              <div className="text-[9px] font-mono text-neon-red mb-1.5 tracking-wider font-bold">ساعات خبيثة (UTC)</div>
              <div className="flex flex-wrap gap-1">
                {dynamicThresholds.bad_hours.map((h: string) => (
                  <span key={h} className="text-[8px] font-mono text-neon-red bg-neon-red/10 px-1.5 py-0.5 rounded">{h}</span>
                ))}
              </div>
            </div>
          )}

          {dynamicThresholds?.good_hours?.length > 0 && (
            <div className="border border-neon-green/20 rounded-lg p-3 bg-neon-green/5">
              <div className="text-[9px] font-mono text-neon-green mb-1.5 tracking-wider font-bold">ساعات جيدة (UTC)</div>
              <div className="flex flex-wrap gap-1">
                {dynamicThresholds.good_hours.map((h: string) => (
                  <span key={h} className="text-[8px] font-mono text-neon-green bg-neon-green/10 px-1.5 py-0.5 rounded">{h}</span>
                ))}
              </div>
            </div>
          )}

          {dynamicThresholds?.regime_min_wr && Object.keys(dynamicThresholds.regime_min_wr).length > 0 && (
            <div className="border border-border-primary rounded-lg p-3">
              <div className="text-[9px] font-mono text-text-muted mb-2 tracking-wider">WR حسب النمط (Regime)</div>
              {Object.entries(dynamicThresholds.regime_min_wr as Record<string, number>)
                .sort((a, b) => b[1] - a[1])
                .map(([regime, wr]) => (
                  <div key={regime} className="flex items-center gap-2 mb-1">
                    <span className="text-[9px] font-mono text-text-muted flex-1 truncate">{regime}</span>
                    <span className={cn('text-[9px] font-mono font-bold',
                      wr >= 0.5 ? 'text-neon-green' : wr >= 0.35 ? 'text-yellow-400' : 'text-neon-red'
                    )}>{wr > 0 ? `${(wr * 100).toFixed(0)}%` : 'لا بيانات'}</span>
                  </div>
                ))}
            </div>
          )}

          <div className="border border-yellow-500/20 rounded-lg p-3 bg-yellow-500/5">
            <div className="flex items-center gap-1.5 mb-1.5">
              <AlertTriangle className="h-3 w-3 text-yellow-400" />
              <span className="text-[9px] font-mono text-yellow-400 font-bold">التجاوزات اليدوية (Manual Overrides)</span>
            </div>
            <p className="text-[9px] font-mono text-text-muted leading-relaxed">
              التجاوزات (quality_score_threshold, min_conviction_override) لا تعمل إلا إذا كانت {'>'} 0.
              القيمة 0 = استخدام العتبة الديناميكية من TradeMemory.
            </p>
          </div>

          {/* ── Connection status (moved into the side panel — no dead space) ── */}
          <SectionCard
            id="connection" label="الاتصال (Conexión)" icon={Database} color="text-text-muted"
            expanded={expanded} setExpanded={setExpanded}
          >
            <div className="flex items-center justify-between py-1.5">
              <span className="text-[10px] font-mono text-text-secondary">MetaTrader 5</span>
              <StatusPill ok={mt5Connected} />
            </div>
            <div className="flex items-center justify-between py-1.5">
              <span className="text-[10px] font-mono text-text-secondary">Redis / WebSocket</span>
              <StatusPill ok={wsConnected} />
            </div>
            <div className="flex items-center justify-between py-1.5">
              <span className="text-[10px] font-mono text-text-secondary">API Endpoint</span>
              <span className="text-[9px] font-mono text-text-muted">{API}</span>
            </div>
            <div className="flex items-center justify-between py-1.5">
              <span className="text-[10px] font-mono text-text-secondary">الذكاء المحلي (Ollama)</span>
              <span className="text-[9px] font-mono text-text-muted">env: NEXUS_LOCAL_LLM_URL / NEXUS_LOCAL_MODEL</span>
            </div>
            <div className="flex items-center justify-between py-1.5">
              <span className="text-[10px] font-mono text-text-secondary">DeepSeek API</span>
              <span className="text-[9px] font-mono text-text-muted">env: DEEPSEEK_API_KEY · NEXUS_LLM_PROVIDER</span>
            </div>
          </SectionCard>
        </div>
      </div>
      ) : activeTab === 'news_ticker' ? (
<div className="w-full max-w-[1400px] mx-auto p-4">
<NewsTickerControlPanel />
</div>
      ) : activeTab === 'brokers' ? (
<BrokerSettingsTab />
      ) : activeTab === 'ea_bridge' ? (
<div className="w-full p-2">
  <EaBridgeView />
</div>
      ) : activeTab === 'research_lab' ? (
<div className="w-full p-2">
  <ResearchLabShell />
</div>
      ) : activeTab === 'project' ? (
<ProjectDevTabs />
      ) : activeTab === 'fundamental_sources' ? (
<SourceConnectionManager />
      ) : (
<AdminAlertsCenter />
      )}
    </div>
  );
}

// تبويب «المشروع والتدقيق» — يدمج شاشتَي المطوّر (متابعة التطوير + نتائج
// التدقيق) اللتين كانتا تزحمتان الشريط العلوي في موضع واحد.
function ProjectDevTabs() {
  const [devTab, setDevTab] = useState<'progress' | 'audit'>('progress');
  const subButton = (id: 'progress' | 'audit', label: string) => (
    <button
      onClick={() => setDevTab(id)}
      className={cn(
        'rounded border px-4 py-1.5 text-[11px] font-mono font-bold transition-colors',
        devTab === id
          ? 'border-neon-cyan bg-neon-cyan/15 text-neon-cyan'
          : 'border-transparent text-text-muted hover:text-text-secondary'
      )}
      aria-pressed={devTab === id}
    >
      {label}
    </button>
  );
  return <div className="space-y-3">
    <div className="flex gap-2 px-4" role="tablist" aria-label="أقسام المشروع والتدقيق">
      {subButton('progress', 'متابعة التطوير')}
      {subButton('audit', 'نتائج التدقيق')}
    </div>
    {devTab === 'progress' ? <ProgressView /> : <AuditProgressView />}
  </div>;
}

function FundamentalSourceHealthTab({
  sources,
  totalSources,
  loading,
  error,
  updatedAt,
  query,
  filter,
  onQueryChange,
  onFilterChange,
  onRefresh,
}: {
  sources: SourceHealthDTO[];
  totalSources: SourceHealthDTO[];
  loading: boolean;
  error: string | null;
  updatedAt: Date | null;
  query: string;
  filter: SourceFilter;
  onQueryChange: (value: string) => void;
  onFilterChange: (value: SourceFilter) => void;
  onRefresh: () => void;
}) {
  const counts = useMemo(() => ({
    total: totalSources.length,
    healthy: totalSources.filter((s) => s.health === 'healthy').length,
    configRequired: totalSources.filter((s) => s.health === 'config_required').length,
    degraded: totalSources.filter((s) => s.health === 'degraded').length,
    unknown: totalSources.filter((s) => s.health === 'unknown').length,
    offline: totalSources.filter((s) => ['offline', 'unavailable'].includes(s.health)).length,
  }), [totalSources]);

  return (
    <div className="mx-auto w-full max-w-[1400px] p-4" dir="rtl">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3 border border-border-primary bg-bg-secondary/50 p-4">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-neon-cyan" />
            <h2 className="text-[13px] font-mono font-bold text-text-primary">إدارة مصادر التحليل الأساسي</h2>
          </div>
          <p className="mt-1 max-w-3xl text-[10px] font-mono leading-5 text-text-muted">
            مراقبة مباشرة للمصادر التي تغذي MACRO وMONETARY وCROSS-ASSET وGEOPOLITICS وFLOWS.
            هذه الشاشة للعرض والتشخيص فقط؛ لا تعرض مفاتيح API ولا تغيّر الإعدادات السرية.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[9px] font-mono text-text-muted">
            آخر تحديث: {updatedAt ? updatedAt.toLocaleString('ar') : '—'}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            disabled={loading}
            className="flex items-center gap-1.5 border border-neon-cyan/30 bg-neon-cyan/10 px-3 py-1.5 text-[10px] font-mono font-bold text-neon-cyan hover:bg-neon-cyan/20 disabled:opacity-50"
          >
            <RefreshCcw className={cn('h-3 w-3', loading && 'animate-spin')} />
            تحديث الآن
          </button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <SourceMetric label="إجمالي المصادر" value={counts.total} tone="neutral" />
        <SourceMetric label="سليم" value={counts.healthy} tone="healthy" />
        <SourceMetric label="يتطلب إعدادًا" value={counts.configRequired} tone="config" />
        <SourceMetric label="متدهور" value={counts.degraded} tone="degraded" />
        <SourceMetric label="غير معروف" value={counts.unknown} tone="unknown" />
        <SourceMetric label="غير متاح/متصل" value={counts.offline} tone="offline" />
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 border border-border-primary bg-bg-secondary/40 p-3">
        <div className="relative min-w-[260px] flex-1">
          <Search className="absolute right-2.5 top-2 h-3.5 w-3.5 text-text-muted" />
          <input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="ابحث باسم المصدر أو المعرّف أو الحالة..."
            className="w-full border border-border-primary bg-bg-tertiary py-1.5 pr-8 pl-3 text-[10px] font-mono text-text-secondary outline-none focus:border-neon-cyan/40"
          />
        </div>
        <select
          value={filter}
          onChange={(e) => onFilterChange(e.target.value as SourceFilter)}
          className="border border-border-primary bg-bg-tertiary px-3 py-1.5 text-[10px] font-mono text-text-secondary outline-none focus:border-neon-cyan/40"
        >
          <option value="all">كل الحالات</option>
          <option value="healthy">سليم</option>
          <option value="config_required">يتطلب إعدادًا</option>
          <option value="degraded">متدهور</option>
          <option value="unknown">غير معروف</option>
          <option value="offline">غير متصل</option>
        </select>
        <span className="text-[9px] font-mono text-text-muted">المعروض: {sources.length}/{totalSources.length}</span>
      </div>

      {error && (
        <div className="mb-3 border border-neon-red/30 bg-neon-red/5 px-3 py-2 text-[10px] font-mono text-neon-red">
          تعذر تحميل بيانات صحة المصادر: {error}
        </div>
      )}

      <div className="overflow-x-auto border border-border-primary bg-bg-primary">
        <table className="w-full min-w-[1180px] text-right text-[10px] font-mono">
          <thead className="bg-bg-secondary text-text-secondary">
            <tr>
              {['المصدر','الحالة','الشرح / المطلوب','الحداثة','الأصل','آخر نجاح','آخر فشل','الاستجابة','المقبول / المستلم'].map((label) => (
                <th key={label} className="whitespace-nowrap border-b border-border-primary px-3 py-2 font-bold">{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.source_id} className="border-b border-border-primary/70 hover:bg-bg-secondary/40">
                <td className="px-3 py-2 align-top">
                  <div className="font-bold text-text-primary">{source.name_ar || source.name_en || source.source_id}</div>
                  <div className="mt-0.5 text-[9px] text-text-muted">{source.name_en}</div>
                  <div className="mt-0.5 text-[9px] text-neon-cyan/80">{source.source_id}</div>
                </td>
                <td className="px-3 py-2 align-top"><SourceStatusBadge status={source.health} /></td>
                <td className="max-w-[360px] px-3 py-2 align-top leading-5 text-text-secondary">{source.health_description_ar || '—'}</td>
                <td className="px-3 py-2 align-top">{SOURCE_STATUS_AR[source.freshness] ?? source.freshness ?? '—'}</td>
                <td className="px-3 py-2 align-top">{source.origin || '—'}</td>
                <td className="whitespace-nowrap px-3 py-2 align-top">{source.last_success_at ? new Date(source.last_success_at).toLocaleString('ar') : '—'}</td>
                <td className="whitespace-nowrap px-3 py-2 align-top">{source.last_failure_at ? new Date(source.last_failure_at).toLocaleString('ar') : '—'}</td>
                <td className="whitespace-nowrap px-3 py-2 align-top">{source.latency_ms == null ? '—' : `${Math.round(source.latency_ms)} ms`}</td>
                <td className="whitespace-nowrap px-3 py-2 align-top">{Number(source.records_accepted ?? 0)} / {Number(source.records_received ?? 0)}</td>
              </tr>
            ))}
            {!loading && sources.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-text-muted">لا توجد مصادر مطابقة للبحث أو الفلتر.</td></tr>
            )}
            {loading && totalSources.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-text-muted">جارٍ تحميل صحة المصادر…</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 border border-yellow-500/20 bg-yellow-500/5 px-3 py-2 text-[9px] font-mono leading-5 text-text-muted">
        <span className="font-bold text-yellow-400">قاعدة الأمان:</span> المصدر غير المتاح أو الذي يتطلب إعدادًا يبقى خارج التحليل الحي ولا يتحول تلقائيًا إلى قيمة محايدة أو بيانات تجريبية.
      </div>
    </div>
  );
}

function SourceMetric({ label, value, tone }: { label: string; value: number; tone: 'neutral' | 'healthy' | 'config' | 'degraded' | 'unknown' | 'offline' }) {
  const toneClass = {
    neutral: 'border-border-primary text-text-primary',
    healthy: 'border-neon-green/30 text-neon-green',
    config: 'border-yellow-400/30 text-yellow-400',
    degraded: 'border-orange-400/30 text-orange-300',
    unknown: 'border-border-secondary text-text-secondary',
    offline: 'border-neon-red/30 text-neon-red',
  }[tone];
  return (
    <div className={cn('border bg-bg-secondary/50 px-3 py-2', toneClass)}>
      <div className="text-[9px] font-mono text-text-muted">{label}</div>
      <div className="mt-1 text-lg font-mono font-bold">{value}</div>
    </div>
  );
}

function SourceStatusBadge({ status }: { status: string }) {
  const style = status === 'healthy'
    ? 'border-neon-green/30 bg-neon-green/10 text-neon-green'
    : status === 'config_required'
      ? 'border-yellow-400/30 bg-yellow-400/10 text-yellow-400'
      : status === 'degraded' || status === 'rate_limited'
        ? 'border-orange-400/30 bg-orange-400/10 text-orange-300'
        : status === 'offline' || status === 'unavailable'
          ? 'border-neon-red/30 bg-neon-red/10 text-neon-red'
          : 'border-border-secondary bg-bg-tertiary text-text-muted';
  return (
    <span className={cn('inline-flex whitespace-nowrap border px-2 py-0.5 font-bold', style)}>
      {SOURCE_STATUS_AR[status] ?? status}
    </span>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SectionCard({
  id, label, icon: Icon, color, expanded, setExpanded, hint, children,
}: {
  id: string; label: string; icon: React.ElementType; color: string;
  expanded: Record<string, boolean>; setExpanded: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  hint?: string;
  children: React.ReactNode;
}) {
  const isExp = expanded[id] !== false;
  return (
    <div className="border border-border-primary rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded((p) => ({ ...p, [id]: !isExp }))}
        className="w-full flex items-center gap-2.5 px-4 py-2.5 bg-bg-secondary/60 hover:bg-bg-secondary transition-colors"
      >
        <Icon className={cn('h-3.5 w-3.5', color)} />
        <span className="text-[11px] font-mono font-bold text-text-secondary shrink-0">{label.toUpperCase()}</span>
        {hint && (
          <span
            title={hint}
            className="hidden md:inline flex-1 min-w-0 truncate text-[9px] font-mono text-text-muted text-right"
          >
            {hint}
          </span>
        )}
        {isExp
          ? <ChevronDown className={cn('h-3 w-3 text-text-muted shrink-0', !hint && 'ml-auto')} />
          : <ChevronRight className={cn('h-3 w-3 text-text-muted shrink-0', !hint && 'ml-auto')} />
        }
      </button>
      {isExp && (
        <div className="px-4 py-3 flex flex-col gap-3">
          {children}
        </div>
      )}
    </div>
  );
}

function FieldRow({ field, value, onChange }: { field: SettingField; value: any; onChange: (v: any) => void }) {
  const isUnset = value === undefined || value === null;
  return (
    <div className="flex flex-col gap-1.5 rounded border border-border-primary/60 bg-bg-secondary/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-mono font-bold text-text-secondary">{field.label}</div>
        <div className="flex w-36 shrink-0 items-start gap-1.5">
        {field.type === 'boolean' ? (
          <>
            <button
              type="button"
              aria-pressed={isUnset ? 'mixed' : value}
              onClick={() => onChange(!value)}
              className={cn(
                'flex min-w-0 flex-1 items-center gap-2 px-2.5 py-1 rounded border text-[10px] font-mono font-bold transition-all justify-center',
                value
                  ? 'bg-neon-green/10 text-neon-green border-neon-green/30'
                  : isUnset
                    ? 'bg-bg-tertiary text-text-muted border-border-primary'
                    : 'bg-bg-tertiary text-text-muted border-border-primary hover:border-border-secondary'
              )}
            >
              <div className={cn('w-2 h-2 rounded-full transition-colors', value ? 'bg-neon-green' : 'bg-text-muted')} />
              {isUnset ? 'افتراضي' : value ? 'ON' : 'OFF'}
            </button>
            {!isUnset && (
              <button
                type="button"
                onClick={() => onChange(null)}
                title="استخدام افتراضي النظام"
                aria-label={`إعادة ${field.label} إلى افتراضي النظام`}
                className="flex h-7 w-7 shrink-0 items-center justify-center border border-border-primary text-text-muted hover:text-text-primary"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            )}
          </>
        ) : field.type === 'select' ? (
          <select
            value={value ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="w-full bg-bg-tertiary border border-border-primary text-text-secondary text-[10px] font-mono px-2 py-1.5 rounded focus:outline-none focus:border-neon-purple/40 cursor-pointer"
          >
            <option value="">افتراضي النظام</option>
            {field.options?.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        ) : (
          <div className="flex items-center gap-1.5">
            <input
              type="number"
              value={value ?? ''}
              placeholder={isUnset ? 'افتراضي النظام' : undefined}
              min={field.min}
              max={field.max}
              step={field.step}
              onChange={(e) => {
                const raw = e.target.value;
                if (!raw) onChange(null);
                else {
                  const parsed = Number(raw);
                  if (Number.isFinite(parsed)) onChange(parsed);
                }
              }}
              className="flex-1 min-w-0 bg-bg-tertiary border border-border-primary text-text-secondary text-[10px] font-mono px-2 py-1.5 rounded focus:outline-none focus:border-neon-purple/40"
            />
            {field.unit && <span className="text-[9px] font-mono text-text-muted shrink-0">{field.unit}</span>}
            {!isUnset && (
              <button
                type="button"
                onClick={() => onChange(null)}
                title="استخدام افتراضي النظام"
                aria-label={`إعادة ${field.label} إلى افتراضي النظام`}
                className="flex h-7 w-7 shrink-0 items-center justify-center border border-border-primary text-text-muted hover:text-text-primary"
              >
                <RotateCcw className="h-3 w-3" />
              </button>
            )}
          </div>
        )}
      </div>
      </div>
      {field.description && (
        <div className="text-[9px] font-mono text-text-muted leading-relaxed">{field.description}</div>
      )}
    </div>
  );
}

function ThreshRow({ label, value, color = 'text-text-secondary' }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[9px] font-mono text-text-muted">{label}</span>
      <span className={cn('text-[9px] font-mono font-bold', color)}>{value}</span>
    </div>
  );
}

function StatusPill({ ok }: { ok: boolean }) {
  return (
    <span className={cn(
      'text-[9px] font-mono px-2 py-0.5 rounded',
      ok ? 'bg-neon-green/10 text-neon-green' : 'bg-neon-red/10 text-neon-red'
    )}>
      {ok ? '● Connected' : '○ Offline'}
    </span>
  );
}

// PAPER/LIVE badge fed by GET /api/system/mode. `null` means the server state
// is unknown (loading or fetch failed) — rendered as `--`, never guessed.
function ModeBadge({ mode }: { mode: 'PAPER' | 'LIVE' | null }) {
  return (
    <span
      title={
        mode === 'PAPER'
          ? 'وضع تجريبي — الحالة مؤكَّدة من الخادم'
          : mode === 'LIVE'
            ? 'وضع حقيقي — الحالة مؤكَّدة من الخادم'
            : 'وضع التداول غير معروف — تعذّر جلبه من الخادم'
      }
      className={cn(
        'inline-flex items-center border px-1.5 py-0.5 text-[9px] font-mono font-bold tracking-wider',
        mode === 'PAPER'
          ? 'border-neon-green/40 bg-neon-green/10 text-neon-green'
          : mode === 'LIVE'
            ? 'border-neon-red/40 bg-neon-red/10 text-neon-red'
            : 'border-border-secondary bg-bg-tertiary text-text-muted'
      )}
    >
      {mode ?? '--'}
    </span>
  );
}
