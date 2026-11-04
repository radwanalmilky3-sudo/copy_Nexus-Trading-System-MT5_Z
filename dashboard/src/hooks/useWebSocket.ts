'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface UseWebSocketOptions {
  url: string;
  onMessage?: (data: unknown) => void;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (error: Event) => void;
  reconnectInterval?: number;
  maxReconnectAttempts?: number;
  enabled?: boolean;
  /** Heartbeat ping cadence (ms). 0 disables ping frames. Default 25000. */
  heartbeatIntervalMs?: number;
  /** Socket is considered dead after this much silence (ms). Default 65000. */
  staleAfterMs?: number;
}

export type WsConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'failed';

interface UseWebSocketReturn {
  isConnected: boolean;
  /** Fine-grained state for honest status chips. */
  connectionState: WsConnectionState;
  lastMessage: unknown | null;
  send: (data: unknown) => void;
  reconnect: () => void;
  disconnect: () => void;
  reconnectCount: number;
}

/* ────────────────────────────────────────────────────────────────────────
 * Aggregate registry — lets a status chip mirror the REAL state of every
 * mounted useWebSocket instance without dialing any extra socket.
 * Honest by construction: a state is only ever produced by a live socket.
 * ──────────────────────────────────────────────────────────────────────── */
const instanceStates = new Map<symbol, WsConnectionState>();
const aggregateListeners = new Set<(state: WsConnectionState) => void>();
let aggregateState: WsConnectionState = 'idle';

function recomputeAggregate() {
  const states = [...instanceStates.values()];
  let next: WsConnectionState = 'idle';
  if (states.includes('connected')) next = 'connected';
  else if (states.includes('reconnecting')) next = 'reconnecting';
  else if (states.includes('connecting')) next = 'connecting';
  else if (states.includes('failed')) next = 'failed';
  if (next !== aggregateState) {
    aggregateState = next;
    aggregateListeners.forEach((cb) => cb(next));
  }
}

/** Subscribe to the aggregate state of all live useWebSocket instances. */
export function subscribeWsAggregate(
  cb: (state: WsConnectionState) => void
): () => void {
  aggregateListeners.add(cb);
  cb(aggregateState);
  return () => {
    aggregateListeners.delete(cb);
  };
}

const MAX_BACKOFF_MS = 30_000;
const HEARTBEAT_INTERVAL_MS = 25_000;
const STALE_AFTER_MS = 65_000;

export function useWebSocket({
  url,
  onMessage,
  onOpen,
  onClose,
  onError,
  reconnectInterval = 3000,
  maxReconnectAttempts = 10,
  enabled = true,
  heartbeatIntervalMs = HEARTBEAT_INTERVAL_MS,
  staleAfterMs = STALE_AFTER_MS,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastActivityRef = useRef(0);
  const manualCloseRef = useRef(false);
  const instanceKeyRef = useRef<symbol>(Symbol('ws-instance'));

  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState<WsConnectionState>('idle');
  const [lastMessage, setLastMessage] = useState<unknown | null>(null);
  const [reconnectCount, setReconnectCount] = useState(0);
  const reconnectCountRef = useRef(0);

  /* Register/unregister this instance in the aggregate registry. */
  useEffect(() => {
    const key = instanceKeyRef.current;
    instanceStates.set(key, connectionState);
    recomputeAggregate();
    return () => {
      instanceStates.delete(key);
      recomputeAggregate();
    };
  }, [connectionState]);

  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  onMessageRef.current = onMessage;
  onOpenRef.current = onOpen;
  onCloseRef.current = onClose;
  onErrorRef.current = onError;

  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const cleanup = useCallback(() => {
    clearTimers();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [clearTimers]);

  /** Heartbeat: periodic ping + staleness watchdog. */
  const startHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current) clearInterval(heartbeatTimerRef.current);
    if (heartbeatIntervalMs <= 0) return;
    heartbeatTimerRef.current = setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      // Any frame — including our ping — refreshes lastActivity on reply.
      if (Date.now() - lastActivityRef.current > staleAfterMs) {
        // Silent socket: force-close so onclose schedules a backoff reconnect.
        try {
          ws.close(4000, 'stale connection');
        } catch {
          /* already closing */
        }
        return;
      }
      try {
        ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
      } catch {
        /* send on a closing socket — ignore, watchdog handles it */
      }
    }, heartbeatIntervalMs);
  }, [heartbeatIntervalMs, staleAfterMs]);

  const connect = useCallback(() => {
    if (!enabled) {
      setConnectionState('idle');
      return;
    }
    manualCloseRef.current = false;
    cleanup();

    setConnectionState(
      reconnectCountRef.current === 0 ? 'connecting' : 'reconnecting'
    );

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      lastActivityRef.current = Date.now();

      ws.onopen = () => {
        const token =
          typeof window !== 'undefined'
            ? window.localStorage.getItem('nexus-token')
            : null;
        if (!token) {
          ws.close(4401, 'authentication required');
          return;
        }
        ws.send(JSON.stringify({ type: 'auth', token }));
      };

      ws.onmessage = (event) => {
        lastActivityRef.current = Date.now();
        try {
          const data = JSON.parse(event.data);
          if (data?.type === 'auth' && data?.ok === true) {
            setIsConnected(true);
            reconnectCountRef.current = 0;
            setReconnectCount(0);
            setConnectionState('connected');
            startHeartbeat();
            onOpenRef.current?.();
            return;
          }
          setLastMessage(data);
          onMessageRef.current?.(data);
        } catch {
          setLastMessage(event.data);
          onMessageRef.current?.(event.data);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (heartbeatTimerRef.current) {
          clearInterval(heartbeatTimerRef.current);
          heartbeatTimerRef.current = null;
        }
        onCloseRef.current?.();

        if (manualCloseRef.current || !enabled) {
          setConnectionState('idle');
          return;
        }
        if (reconnectCountRef.current >= maxReconnectAttempts) {
          // Cap reached — stop hammering, surface honest failure.
          setConnectionState('failed');
          return;
        }
        reconnectCountRef.current += 1;
        setReconnectCount(reconnectCountRef.current);
        setConnectionState('reconnecting');
        // Exponential backoff with jitter: 3s → 6s → 12s → 24s → 30s cap.
        const backoff = Math.min(
          reconnectInterval * 2 ** (reconnectCountRef.current - 1),
          MAX_BACKOFF_MS
        );
        const jitter = Math.floor(Math.random() * 250);
        reconnectTimerRef.current = setTimeout(connect, backoff + jitter);
      };

      ws.onerror = (error) => {
        onErrorRef.current?.(error);
      };
    } catch {
      if (reconnectCountRef.current >= maxReconnectAttempts) {
        setConnectionState('failed');
        return;
      }
      reconnectCountRef.current += 1;
      setReconnectCount(reconnectCountRef.current);
      setConnectionState('reconnecting');
      const backoff = Math.min(
        reconnectInterval * 2 ** (reconnectCountRef.current - 1),
        MAX_BACKOFF_MS
      );
      reconnectTimerRef.current = setTimeout(connect, backoff);
    }
  }, [
    url,
    enabled,
    reconnectInterval,
    maxReconnectAttempts,
    cleanup,
    startHeartbeat,
  ]);

  useEffect(() => {
    connect();
    return cleanup;
  }, [connect, cleanup]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
      lastActivityRef.current = Date.now();
    }
  }, []);

  const reconnect = useCallback(() => {
    reconnectCountRef.current = 0;
    setReconnectCount(0);
    connect();
  }, [connect]);

  const disconnect = useCallback(() => {
    manualCloseRef.current = true;
    cleanup();
    setIsConnected(false);
    setConnectionState('idle');
  }, [cleanup]);

  return {
    isConnected,
    connectionState,
    lastMessage,
    send,
    reconnect,
    disconnect,
    reconnectCount,
  };
}
