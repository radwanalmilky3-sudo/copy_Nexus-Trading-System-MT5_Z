export type UserMenuProfile = {
  user_id?: string;
  username?: string;
  full_name?: string | null;
  roles?: string[];
  avatar_url?: string | null;
} | null | undefined;

export type UserMenuPhase = 'loading' | 'ready' | 'needs_login' | 'session_broken';

/**
 * Derive the menu state from the loaded profile + local token.
 * A profile that failed to load while a token exists is `session_broken`:
 * the user must still be able to clear the local session (logout).
 */
export function userMenuPhase(
  profile: UserMenuProfile,
  hasToken: boolean,
  pending: boolean,
): UserMenuPhase {
  if (pending) return 'loading';
  if (profile && (profile.user_id || profile.username)) return 'ready';
  if (!hasToken) return 'needs_login';
  return 'session_broken';
}

/** Display name — never invents placeholders like '?'. */
export function userMenuDisplayName(profile: UserMenuProfile): string {
  if (!profile) return '—';
  const name = `${profile.full_name || profile.username || ''}`.trim();
  return name || '—';
}

/** Role label — an absent role stays absent ('—'), never a fabricated 'viewer'. */
export function userMenuRoleLabel(profile: UserMenuProfile): string {
  const roles = profile?.roles;
  if (!Array.isArray(roles)) return '—';
  const first = `${roles[0] ?? ''}`.trim();
  return first || '—';
}

/** Menu entries per phase; logout is kept for session_broken so the token can be cleared. */
export function userMenuItems(
  phase: UserMenuPhase,
): readonly ('settings' | 'logout')[] {
  if (phase === 'ready') return ['settings', 'logout'];
  if (phase === 'session_broken') return ['logout'];
  return [];
}

export function userMenuAvatarLetter(displayName: string): string {
  const trimmed = `${displayName}`.trim();
  if (!trimmed || trimmed === '—') return '';
  return trimmed.slice(0, 1);
}
