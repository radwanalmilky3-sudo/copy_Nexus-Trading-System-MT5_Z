'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { getAuthHeaders } from '@/lib/api-client';

const API = process.env.NEXT_PUBLIC_API_URL || '';

export type AlertSeverity = 'HIGH' | 'MEDIUM' | 'INFO';

export interface SystemAlert {
  type: string;
  message: string;
  severity: AlertSeverity;
  ts: string;
  // optional per-type extra fields
  bias?: string;
  confidence?: number;
  pair?: string;
  corr_7d?: number;
  corr_30d?: number;
  shift?: number;
  events?: { title: string; event_time: string }[];
  ends_at?: string | null;
}

// Notification type → label + icon char
export const ALERT_META: Record<string, { label: string; color: string }> = {
  BLACKOUT_START:  { label: 'Blackout inicio',  color: 'text-neon-red' },
  BLACKOUT_END:    { label: 'Blackout fin',      color: 'text-neon-green' },
  BRIEF_READY:     { label: 'Brief generado',    color: 'text-yellow-400' },
  CORR_DIVERGENCE: { label: 'Divergencia corr.', color: 'text-orange-400' },
  SIGNAL_HIGH:     { label: 'Señal alta calidad',color: 'text-neon-purple' },
  CIRCUIT_BREAKER: { label: 'Circuit breaker',   color: 'text-neon-red' },
};

const STORAGE_PREFS_KEY = 'nexus:notif:prefs';
const STORAGE_READ_KEY  = 'nexus:notif:last_read';

export interface NotifPrefs {
  browser:    boolean;
  blackout:   boolean;
  brief:      boolean;
  divergence: boolean;
}

function loadPrefs(): NotifPrefs {
  if (typeof window === 'undefined') return { browser: true, blackout: true, brief: true, divergence: true };
  try {
    const raw = localStorage.getItem(STORAGE_PREFS_KEY);
    if (raw) return { browser: true, blackout: true, brief: true, divergence: true, ...JSON.parse(raw) };
  } catch {}
  return { browser: true, blackout: true, brief: true, divergence: true };
}

function shouldNotify(alert: SystemAlert, prefs: NotifPrefs): boolean {
  if (alert.type === 'BLACKOUT_START' || alert.type === 'BLACKOUT_END') return prefs.blackout;
  if (alert.type === 'BRIEF_READY') return prefs.brief;
  if (alert.type === 'CORR_DIVERGENCE') return prefs.divergence;
  return true;
}

export function useNotifications() {
  const [alerts, setAlerts] = useState<SystemAlert[]>([]);
  const [unread, setUnread] = useState(0);
  const [connected, setConnected] = useState(false);
  const [prefs, setPrefs] = useState<NotifPrefs>(loadPrefs);
  const streamAbortRef = useRef<AbortController | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastReadRef = useRef<string>(
    typeof window !== 'undefined' ? (localStorage.getItem(STORAGE_READ_KEY) || '') : ''
  );

  const addAlert = useCallback((alert: SystemAlert) => {
    setAlerts(prev => {
      const next = [alert, ...prev].slice(0, 50);
      // Count unread: alerts newer than lastRead
      const unreadCount = next.filter(a => a.ts > lastReadRef.current).length;
      setUnread(unreadCount);
      return next;
    });

    // Browser notification
    if (prefs.browser && shouldNotify(alert, prefs) && typeof window !== 'undefined') {
      if (Notification.permission === 'granted') {
        const meta = ALERT_META[alert.type];
        new Notification(`Nexus — ${meta?.label ?? alert.type}`, {
          body: alert.message,
          icon: '/favicon.ico',
          tag: alert.type,
          silent: alert.severity === 'INFO',
        });
      }
    }
  }, [prefs]);

  // Request browser notification permission on mount
  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission().catch(() => {});
    }
  }, []);

  // SSE connection
  useEffect(() => {
    let disposed = false;
    const connect = async () => {
      const controller = new AbortController();
      let shouldReconnect = true;
      streamAbortRef.current = controller;
      try {
        const response = await fetch(`${API}/api/notifications/stream?prefetch=15`, {
          headers: getAuthHeaders(),
          signal: controller.signal,
        });
        if (response.status === 401) {
          shouldReconnect = false;
          localStorage.removeItem('nexus-token');
          window.location.href = '/login';
          return;
        }
        if (response.status === 403) {
          shouldReconnect = false;
          return;
        }
        if (!response.ok || !response.body) throw new Error(`notification stream HTTP ${response.status}`);
        setConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!disposed && !controller.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? '';
          for (const frame of frames) {
            const data = frame.split(/\r?\n/)
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.slice(5).trimStart())
              .join('\n');
            if (!data) continue;
            try {
              const alert: SystemAlert = JSON.parse(data);
              if (alert.type && alert.message) addAlert(alert);
            } catch { /* Ignore malformed event frames. */ }
          }
        }
        await reader.cancel().catch(() => {});
      } catch {
        if (!controller.signal.aborted) setConnected(false);
      } finally {
        if (!disposed) setConnected(false);
        if (shouldReconnect && !disposed && !controller.signal.aborted) {
          reconnectTimerRef.current = setTimeout(() => void connect(), 5000);
        }
      }
    };

    void connect();
    return () => {
      disposed = true;
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    };
  }, [addAlert]);

  const markAllRead = useCallback(() => {
    const now = new Date().toISOString();
    lastReadRef.current = now;
    setUnread(0);
    if (typeof window !== 'undefined') localStorage.setItem(STORAGE_READ_KEY, now);
  }, []);

  const updatePrefs = useCallback((next: Partial<NotifPrefs>) => {
    setPrefs(prev => {
      const merged = { ...prev, ...next };
      if (typeof window !== 'undefined') localStorage.setItem(STORAGE_PREFS_KEY, JSON.stringify(merged));
      return merged;
    });
  }, []);

  return { alerts, unread, connected, prefs, updatePrefs, markAllRead };
}
