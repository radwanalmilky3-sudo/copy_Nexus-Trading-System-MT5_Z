'use client';
import { useEffect, useState } from 'react';
import { LogOut, Settings, UserRound } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import {
  userMenuAvatarLetter,
  userMenuDisplayName,
  userMenuItems,
  userMenuPhase,
  userMenuRoleLabel,
  type UserMenuProfile,
} from '@/lib/user-menu-presentation';

// Same-origin default (empty base): the browser calls the dashboard's own
// origin and next.config.js rewrites /api/* to nexus-api server-side. An
// absolute loopback fallback breaks preview deployments — the owner's
// browser would resolve it against their own machine (see MEMORY.md L64).
const API = process.env.NEXT_PUBLIC_API_URL || '';

export default function UserMenu() {
  const router = useRouter();
  const [u, setU] = useState<UserMenuProfile>(null);
  const [pending, setPending] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!localStorage.getItem('nexus-token')) {
      setU(null);
      return;
    }
    setPending(true);
    // JWT-aware ApiClient (bearer header via fetchPath; 401 clears the token).
    apiClient.getMe()
      .then((data) => setU(data as UserMenuProfile))
      .catch(() => setU(null))
      .finally(() => setPending(false));
  }, []);

  const logout = async () => {
    try {
      await apiClient.logout();
    } catch {
      /* Best-effort server logout; clear the local session regardless. */
    }
    localStorage.removeItem('nexus-token');
    router.push('/login');
  };

  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('nexus-token');
  const phase = userMenuPhase(u, hasToken, pending);
  const displayName = userMenuDisplayName(u);
  const letter = userMenuAvatarLetter(displayName);
  const items = userMenuItems(phase);

  if (phase === 'loading' || phase === 'needs_login') {
    return (
      <span
        role="status"
        aria-label={phase === 'loading' ? 'جارٍ تحميل المستخدم' : 'غير مسجل الدخول'}
        className="inline-flex h-7 w-7 items-center justify-center text-text-muted"
      >
        <UserRound className="h-4 w-4" />
      </span>
    );
  }

  return (
    <div className="relative">
      <button
        onClick={() => (items.length ? setOpen((v) => !v) : undefined)}
        className="flex items-center gap-2 rounded px-1.5 py-1 hover:bg-bg-card"
        aria-haspopup={items.length ? 'menu' : undefined}
        aria-expanded={items.length ? open : undefined}
        title={phase === 'session_broken' ? 'تعذر تحميل الملف الشخصي — يمكنك تسجيل الخروج لمسح الجلسة المحلية' : undefined}
      >
        {u?.avatar_url
          ? <img src={`${API}${u.avatar_url}`} alt="" className="h-7 w-7 rounded-full object-cover" />
          : <div className="grid h-7 w-7 place-items-center rounded-full bg-neon-purple/15 text-[10px] font-bold text-neon-purple">{letter}</div>}
        <div className="hidden text-right sm:block">
          <div className="max-w-32 truncate text-[10px] font-bold text-text-primary">{displayName}</div>
          <div className="text-[8px] text-text-muted">{userMenuRoleLabel(u)}</div>
        </div>
      </button>
      {open && items.length > 0 && (
        <div className="absolute left-0 top-10 z-50 w-56 border border-border-primary bg-bg-secondary p-2 shadow-xl" role="menu">
          {items.includes('settings') && (
            <button
              role="menuitem"
              onClick={() => { setOpen(false); router.push('/nexus/settings'); }}
              className="flex w-full items-center gap-2 px-2 py-2 text-[10px] hover:bg-bg-tertiary"
            >
              <Settings className="h-3.5 w-3.5" />إعدادات الحساب والتنبيهات
            </button>
          )}
          {items.includes('logout') && (
            <button
              role="menuitem"
              onClick={() => void logout()}
              className="flex w-full items-center gap-2 px-2 py-2 text-[10px] text-neon-red hover:bg-bg-tertiary"
            >
              <LogOut className="h-3.5 w-3.5" />تسجيل الخروج
            </button>
          )}
        </div>
      )}
    </div>
  );
}
