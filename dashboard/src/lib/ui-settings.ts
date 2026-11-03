/** Browser persistence for Settings page (survives reloads). */
export const UI_SETTINGS_STORAGE_KEY = 'nexus-trader-ui-settings-v1';

/** Strategy Config panel (agents / assets toggles). */
export const CONFIG_PANEL_STORAGE_KEY = 'nexus-config-panel-v1';

/**
 * Local (browser-side) preferences hydrated on the General Settings tab.
 * Every field MUST have a default — a missing/legacy field must never
 * produce `undefined` in the UI.
 */
export interface UiSettings {
  /** Play sound on trade/signal execution. */
  soundAlerts: boolean;
  /** Show OS-level desktop notifications while the tab is unfocused. */
  desktopNotifications: boolean;
}

/**
 * Field-by-field schema: canonical defaults + declared runtime type.
 * Kept in one place so the reader, the writer and the page agree on the shape
 * (guards against schema drift between versions).
 */
export const UI_SETTINGS_SCHEMA = {
  soundAlerts: { type: 'boolean', default: true },
  desktopNotifications: { type: 'boolean', default: false },
} as const satisfies Record<keyof UiSettings, { type: 'boolean'; default: boolean }>;

/** Canonical defaults (typed, frozen — never mutate). */
export const DEFAULT_UI_SETTINGS: Readonly<UiSettings> = Object.freeze({
  soundAlerts: UI_SETTINGS_SCHEMA.soundAlerts.default,
  desktopNotifications: UI_SETTINGS_SCHEMA.desktopNotifications.default,
});

// ── Back-compat aliases (page.tsx historically declared these locally) ────────
/** @deprecated Use `UiSettings`. */
export type LocalSettings = UiSettings;
/** @deprecated Use `DEFAULT_UI_SETTINGS`. */
export const DEFAULT_LOCAL: Readonly<LocalSettings> = DEFAULT_UI_SETTINGS;

/**
 * Coerce one stored value to boolean, tolerating schema drift from older
 * writers that stored `'true'`/`'1'`/`0` instead of real booleans.
 * Anything unrecognised falls back to the schema default.
 */
function coerceBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === '1' || value === 1) return true;
  if (value === 'false' || value === '0' || value === 0) return false;
  return fallback;
}

function defaultSettings(): UiSettings {
  return { ...DEFAULT_UI_SETTINGS };
}

function resolveStorage(storage?: Storage | null): Storage | null {
  if (storage) return storage;
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage ?? null;
  } catch {
    // Storage access can throw (privacy mode / disabled cookies).
    return null;
  }
}

/**
 * Read local UI settings safely.
 *
 * Robustness guarantees:
 * - SSR safe (returns defaults when there is no `window`).
 * - `JSON.parse` wrapped in try/catch — corrupt localStorage can never crash
 *   the Settings page, it degrades to defaults.
 * - Non-object payloads (`null`, arrays, strings) → defaults.
 * - Unknown/legacy fields are dropped; missing fields fall back to defaults.
 * - Wrong-typed fields (e.g. `"true"` from an older version) are coerced or
 *   replaced by the default instead of leaking into the UI.
 *
 * @param storage Optional storage override (tests); defaults to `localStorage`.
 */
export function readLocalSettings(storage?: Storage | null): UiSettings {
  try {
    const store = resolveStorage(storage);
    const raw = store?.getItem(UI_SETTINGS_STORAGE_KEY);
    if (!raw) return defaultSettings();

    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return defaultSettings();
    }

    const saved = parsed as Record<string, unknown>;
    return {
      soundAlerts: coerceBoolean(saved.soundAlerts, DEFAULT_UI_SETTINGS.soundAlerts),
      desktopNotifications: coerceBoolean(
        saved.desktopNotifications,
        DEFAULT_UI_SETTINGS.desktopNotifications
      ),
    };
  } catch {
    // Corrupt JSON, blocked storage, quota errors — all degrade to defaults.
    return defaultSettings();
  }
}

/** Alias kept for readers written against the newer module name. */
export const readUiSettings = readLocalSettings;

/**
 * Persist local UI settings. Stores only known schema fields (drops legacy
 * extras) and never throws — returns `false` when storage is unavailable
 * (e.g. private mode / quota exceeded).
 */
export function writeLocalSettings(
  settings: Partial<UiSettings> | null | undefined,
  storage?: Storage | null
): boolean {
  try {
    const store = resolveStorage(storage);
    if (!store) return false;
    const merged: UiSettings = {
      soundAlerts: coerceBoolean(settings?.soundAlerts, DEFAULT_UI_SETTINGS.soundAlerts),
      desktopNotifications: coerceBoolean(
        settings?.desktopNotifications,
        DEFAULT_UI_SETTINGS.desktopNotifications
      ),
    };
    store.setItem(UI_SETTINGS_STORAGE_KEY, JSON.stringify(merged));
    return true;
  } catch {
    return false;
  }
}
