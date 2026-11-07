'use client';

/**
 * جسر MT5 (EA Bridge) — إدارة توكنات الإكسبيرت وعرض طابور الأوامر.
 * البند 3 + 4: التوكن يظهر مرة واحدة عند الإنشاء (SHA-256 فقط يُخزَّن)،
 * والأوامر تُطالب من طرف NexusBridgeEA عبر /api/ea/poll.
 */

import { useCallback, useEffect, useState } from 'react';
import { Cable, Copy, KeyRound, RefreshCw, Trash2, TriangleAlert, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import VirtualTable, { type VirtualColumn } from '@/components/shared/VirtualTable';

interface EaToken {
  token_id: string;
  label: string;
  mt5_login: string | null;
  mt5_broker: string | null;
  mt5_server: string | null;
  active: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

interface EaCommand {
  command_id: string;
  symbol: string;
  action: string;
  status: 'pending' | 'claimed' | 'done' | 'failed';
  payload_json: string;
  result_json: string | null;
  created_at: string;
  claimed_at: string | null;
  completed_at: string | null;
}

async function authFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('nexus-token');
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (res.status === 401) throw new Error('انتهت الجلسة — سجّل الدخول من جديد');
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') msg = body.detail;
    } catch {
      /* keep default message */
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

const fmtDate = (v: string | null) =>
  v ? new Date(v).toLocaleString('en-GB', { hour12: false }) : '—';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  claimed: 'bg-sky-500/10 text-sky-400 border-sky-500/30',
  done: 'bg-neon-green/10 text-neon-green border-neon-green/30',
  failed: 'bg-neon-red/10 text-neon-red border-neon-red/30',
};

const STATUS_LABELS: Record<string, string> = {
  pending: 'معلّق',
  claimed: 'مُطالَب',
  done: 'منفَّذ',
  failed: 'فشل',
};

function parseResult(json: string | null): { detail?: string; ticket?: number; price?: number } {
  if (!json) return {};
  try {
    return JSON.parse(json) as { detail?: string; ticket?: number; price?: number };
  } catch {
    return {};
  }
}

// M2 — virtualized command-queue columns.
const COMMAND_COLUMNS: VirtualColumn<EaCommand>[] = [
  { key: 'time', header: 'الوقت', width: '150px', dir: 'ltr', render: (c) => <span className="text-text-muted">{fmtDate(c.created_at)}</span> },
  { key: 'symbol', header: 'الرمز', width: '90px', dir: 'ltr', render: (c) => <span className="font-mono">{c.symbol}</span> },
  { key: 'action', header: 'الإجراء', width: '110px', dir: 'ltr', render: (c) => <span className="font-mono">{c.action}</span> },
  {
    key: 'status',
    header: 'الحالة',
    width: '90px',
    render: (c) => (
      <span className={cn('rounded border px-1.5 py-0.5 text-[10px] font-medium', STATUS_STYLES[c.status] || '')}>
        {STATUS_LABELS[c.status] || c.status}
      </span>
    ),
  },
  {
    key: 'result',
    header: 'النتيجة',
    width: '1fr',
    dir: 'ltr',
    render: (c) => {
      const result = parseResult(c.result_json);
      return (
        <span className="text-text-secondary">
          {result.detail || '—'}
          {result.ticket ? ` #${result.ticket}` : ''}
        </span>
      );
    },
  },
];

export function EaBridgeView() {
  const [tokens, setTokens] = useState<EaToken[]>([]);
  const [commands, setCommands] = useState<EaCommand[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('MT5 Terminal');
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState('');
  // Destructive-action guard — revoking an active token cuts the live MT5
  // bridge immediately, so it always waits for an explicit confirmation.
  const [pendingRevoke, setPendingRevoke] = useState<EaToken | null>(null);
  const [newToken, setNewToken] = useState('');
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const [tokensRes, commandsRes] = await Promise.all([
        authFetch<{ tokens: EaToken[] }>('/api/admin/ea-tokens'),
        authFetch<{ commands: EaCommand[] }>('/api/admin/ea-commands'),
      ]);
      setTokens(tokensRes.tokens || []);
      setCommands(commandsRes.commands || []);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر تحميل بيانات الجسر');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const createToken = async () => {
    setCreating(true);
    setError('');
    try {
      const res = await authFetch<{ token: string }>('/api/admin/ea-tokens', {
        method: 'POST',
        body: JSON.stringify({ label: label.trim() || 'MT5 Terminal' }),
      });
      setNewToken(res.token);
      setCopied(false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر إنشاء التوكن');
    } finally {
      setCreating(false);
    }
  };

  const revokeToken = async (tokenId: string) => {
    setRevokingId(tokenId);
    try {
      await authFetch(`/api/admin/ea-tokens/${tokenId}`, { method: 'DELETE' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'تعذر إلغاء التوكن');
    } finally {
      setRevokingId('');
      setPendingRevoke(null);
    }
  };

  const confirmRevoke = () => {
    if (!pendingRevoke || revokingId) return;
    void revokeToken(pendingRevoke.token_id);
  };

  const copyToken = async () => {
    try {
      await navigator.clipboard.writeText(newToken);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div dir="rtl" className="min-h-full p-3 sm:p-5 space-y-4 bg-bg-primary text-text-primary">
      <header className="flex items-center gap-2.5">
        <Cable className="h-5 w-5 shrink-0 text-neon-purple" />
        <h1 className="text-base font-bold shrink-0">جسر MT5 — توكنات الإكسبيرت وطابور الأوامر</h1>
        <p
          title="أنشئ توكنًا لكل طرف MetaTrader 5، ثم ضعه في مدخلات NexusBridgeEA. التوكن يُعرض مرة واحدة فقط ويُخزَّن على الخادم كبصمة SHA-256 لا رجعة فيها."
          className="hidden md:block flex-1 min-w-0 truncate text-[11px] text-text-muted"
        >
          أنشئ توكنًا لكل طرف MetaTrader 5، ثم ضعه في مدخلات NexusBridgeEA. التوكن يُعرض
          <span className="text-neon-gold font-medium"> مرة واحدة فقط </span>
          ويُخزَّن على الخادم كبصمة SHA-256 لا رجعة فيها.
        </p>
      </header>

      {error && (
        <p role="alert" className="rounded-md border border-neon-red/30 bg-neon-red/10 px-3 py-2 text-xs text-neon-red">
          {error}
        </p>
      )}

      {/* Create token */}
      <section className="rounded-lg border border-border-primary bg-bg-card p-3 sm:p-4 space-y-3">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-secondary">
          <KeyRound className="h-3.5 w-3.5 text-neon-gold" />
          إنشاء توكن جديد
        </div>
        {newToken ? (
          <div className="space-y-2">
            <div className="flex items-start gap-2 rounded-md border border-neon-gold/30 bg-neon-gold/5 px-3 py-2">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-neon-gold" />
              <p className="text-[11px] leading-relaxed text-neon-gold">
                انسخ التوكن الآن — لن يُعرض مرة أخرى بإطلاق. إذا فقده أنشئ توكنًا جديدًا وألغِ هذا.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <code dir="ltr" className="flex-1 overflow-x-auto rounded-md border border-border-primary bg-bg-primary px-3 py-2 font-mono text-xs text-neon-green select-all">
                {newToken}
              </code>
              <div className="flex gap-2">
                <button type="button" onClick={copyToken} className="neon-button px-3 py-2 text-xs flex items-center gap-1.5">
                  <Copy className="h-3 w-3" />
                  {copied ? 'تم النسخ ✓' : 'نسخ'}
                </button>
                <button
                  type="button"
                  onClick={() => { setNewToken(''); setCopied(false); }}
                  className="px-3 py-2 text-xs rounded-md border border-border-primary text-text-muted hover:text-text-secondary"
                >
                  إخفاء
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col sm:flex-row gap-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={80}
              placeholder="اسم الطرف (مثال: MT5-Laptop)"
              className="flex-1 rounded-md border border-border-primary bg-bg-primary px-3 py-2 text-xs outline-none focus:border-neon-purple/50"
            />
            <button
              type="button"
              onClick={createToken}
              disabled={creating}
              className="neon-button px-4 py-2 text-xs disabled:opacity-50"
            >
              {creating ? 'جارٍ الإنشاء…' : 'إنشاء توكن'}
            </button>
          </div>
        )}
      </section>

      {/* Tokens table */}
      <section className="rounded-lg border border-border-primary bg-bg-card overflow-hidden">
        <div className="flex items-center justify-between px-3 sm:px-4 py-2.5 border-b border-border-primary">
          <h2 className="text-xs font-semibold text-text-secondary">التوكنات ({tokens.length})</h2>
          <button type="button" onClick={() => void load()} className="flex items-center gap-1 text-[10px] text-text-muted hover:text-text-secondary">
            <RefreshCw className="h-3 w-3" />
            تحديث
          </button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-text-muted border-b border-border-primary/60">
                <th className="px-3 py-2 text-right font-medium">الاسم</th>
                <th className="px-3 py-2 text-right font-medium">الطرف المرتبط</th>
                <th className="px-3 py-2 text-right font-medium">الحالة</th>
                <th className="px-3 py-2 text-right font-medium">آخر استخدام</th>
                <th className="px-3 py-2 text-right font-medium">أُنشئ</th>
                <th className="px-3 py-2 text-right font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-text-muted">جارٍ التحميل…</td></tr>
              )}
              {!loading && tokens.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-text-muted">لا توكنات بعد — أنشئ توكنك الأول بالأعلى.</td></tr>
              )}
              {tokens.map((t) => (
                <tr key={t.token_id} className="border-b border-border-primary/30 last:border-0">
                  <td className="px-3 py-2 font-medium">{t.label}</td>
                  <td className="px-3 py-2 text-text-secondary" dir="ltr">
                    {t.mt5_login ? `${t.mt5_login} @ ${t.mt5_broker ?? ''}` : '—'}
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn(
                      'rounded border px-1.5 py-0.5 text-[10px] font-medium',
                      t.active ? 'border-neon-green/30 bg-neon-green/10 text-neon-green' : 'border-neon-red/30 bg-neon-red/10 text-neon-red'
                    )}>
                      {t.active ? 'نشط' : 'ملغى'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-text-muted" dir="ltr">{fmtDate(t.last_used_at)}</td>
                  <td className="px-3 py-2 text-text-muted" dir="ltr">{fmtDate(t.created_at)}</td>
                  <td className="px-3 py-2">
                    {t.active && (
                      <button
                        type="button"
                        onClick={() => setPendingRevoke(t)}
                        disabled={revokingId === t.token_id}
                        className="flex items-center gap-1 rounded border border-neon-red/30 px-2 py-1 text-[10px] text-neon-red hover:bg-neon-red/10 disabled:opacity-50"
                      >
                        <Trash2 className="h-3 w-3" />
                        {revokingId === t.token_id ? '…' : 'إلغاء'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Commands table — M2: virtualized */}
      <section className="rounded-lg border border-border-primary bg-bg-card overflow-hidden">
        <div className="px-3 sm:px-4 py-2.5 border-b border-border-primary">
          <h2 className="text-xs font-semibold text-text-secondary">آخر أوامر الطابور (50)</h2>
        </div>
        <div className="px-1 sm:px-2 pb-1">
          <VirtualTable
            rows={commands}
            rowKey={(c) => c.command_id}
            columns={COMMAND_COLUMNS}
            rowHeight={32}
            height="360px"
            minWidth={760}
            emptyMessage={loading ? 'جارٍ التحميل…' : 'لا أوامر بعد — تُضاف أوامر تلقائيًا عند كل صفقة ناجحة للنظام.'}
          />
        </div>
      </section>

      <p className="text-[10px] leading-relaxed text-text-muted">
        إعداد الطرف: انسخ <code dir="ltr" className="font-mono">mql5/Experts/NexusBridgeEA.mq5</code> إلى مجلد
        MQL5/Experts في الطرف، اسمح بعنوان الخادم في WebRequest، ثم أرفق الإكسبيرت على شارت واحد
        وضعه التوكن في المدخل <code dir="ltr" className="font-mono">InpToken</code>. التفاصيل في
        <code dir="ltr" className="font-mono"> docs/EA_BRIDGE.md</code>.
      </p>

      {/* Confirm revoke — destructive action guard */}
      {pendingRevoke && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-bg-overlay animate-fade-in"
          role="dialog"
          aria-modal="true"
          aria-label="تأكيد إلغاء توكن الإكسبيرت"
          onClick={() => { if (!revokingId) setPendingRevoke(null); }}
        >
          <div
            className="relative w-80 rounded-xl border border-neon-red/60 bg-bg-card p-5 shadow-lg shadow-neon-red/20 animate-slide-up"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => { if (!revokingId) setPendingRevoke(null); }}
              className="absolute top-3 left-3 text-text-muted hover:text-text-primary transition-colors"
              aria-label="إغلاق"
            >
              <X className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-2 mb-3">
              <TriangleAlert className="h-5 w-5 text-neon-red" />
              <h3 className="text-sm font-bold text-text-primary">إلغاء توكن الإكسبيرت؟</h3>
            </div>
            <p className="text-xs leading-relaxed text-text-secondary mb-2">
              سيلغي التوكن
              <span className="mx-1 font-semibold text-text-primary">«{pendingRevoke.label}»</span>
              فورًا، وسينقطع اتصال طرف MetaTrader 5 المرتبط به حتى وضع توكن جديد في المدخل
              <code dir="ltr" className="mx-0.5 font-mono">InpToken</code>.
            </p>
            <p className="text-[11px] leading-relaxed text-text-muted mb-4">
              الأوامر المعلّقة في الطابور ستبقى بلا مُطالبة، ولا يمكن استرجاع هذا التوكن بعد الإلغاء —
              أنشئ توكنًا جديدًا لإعادة ربط الطرف.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setPendingRevoke(null)}
                disabled={revokingId !== ''}
                className="flex-1 rounded-lg py-2.5 text-xs font-medium border border-border-primary text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
              >
                تراجع
              </button>
              <button
                type="button"
                onClick={confirmRevoke}
                disabled={revokingId !== ''}
                className="flex-1 rounded-lg py-2.5 text-xs font-bold border border-neon-red bg-neon-red/20 text-neon-red hover:bg-neon-red/30 transition-colors disabled:cursor-wait disabled:opacity-60"
              >
                {revokingId ? 'جارٍ الإلغاء…' : 'نعم، ألغِ التوكن'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
