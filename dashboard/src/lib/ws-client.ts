import type { WSChannel, WSMessage } from '@/types/api';
import { gatewayWsUrl } from '@/lib/gateway-ws';

type EventCallback<T = unknown> = (data: WSMessage<T>) => void;

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const RECONNECT_MULTIPLIER = 2;

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'error';

/**
 * Backend native WebSocket routes (FastAPI). Channels without a gateway
 * route are never dialed — a subscription attempt is recorded but stays
 * inert so the client never pretends to be connected to a missing feed.
 */
const SUPPORTED_CHANNELS = new Set<WSChannel>([
  'ticks',
  'positions',
  'orders',
  'agents',
  'risk',
  'news',
]);

interface ChannelEntry {
  ws: WebSocket | null;
  authed: boolean;
  reconnectAttempt: number;
  reconnectTimer: ReturnType<typeof setTimeout> | null;
  /** Last subscribe params, re-sent after every reconnect+auth. */
  params?: Record<string, string | number | boolean>;
}

/**
 * Native-WS client matching the gateway protocol:
 * 1. Dial `ws://…/ws/<channel>`.
 * 2. Send `{"type":"auth","token":…}` as the FIRST frame.
 * 3. Wait for `{"type":"auth","ok":true}` — only then is the channel
 *    considered connected (`connected` is never reported from bare TCP open).
 * 4. On every reconnect the auth frame is re-sent; for the ticks channel a
 *    `{"action":"subscribe","symbols":[…]}` frame follows auth when params
 *    were supplied.
 */
class WSClient {
  private channels = new Map<WSChannel, ChannelEntry>();
  private listeners = new Map<string, Set<EventCallback>>();
  private statusCallbacks = new Set<(status: ConnectionStatus) => void>();
  private _status: ConnectionStatus = 'disconnected';
  private manuallyClosed = false;

  get status(): ConnectionStatus {
    return this._status;
  }

  private setStatus(status: ConnectionStatus) {
    if (this._status === status) return;
    this._status = status;
    this.statusCallbacks.forEach((cb) => cb(status));
  }

  /** Derive the aggregate status from per-channel connection state. */
  private recomputeStatus() {
    const entries = [...this.channels.values()];
    if (entries.length === 0) {
      this.setStatus('disconnected');
      return;
    }
    const anyPending = entries.some((e) => e.ws !== null && !e.authed);
    if (entries.every((e) => e.authed)) {
      this.setStatus('connected');
    } else if (anyPending) {
      this.setStatus('connecting');
    } else if (entries.some((e) => e.ws === null && e.reconnectAttempt > 0)) {
      this.setStatus('error');
    } else {
      this.setStatus('disconnected');
    }
  }

  private getToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('nexus-token');
  }

  connect(): void {
    this.manuallyClosed = false;
    this.channels.forEach((_entry, channel) => this.openChannel(channel));
  }

  disconnect(): void {
    this.manuallyClosed = true;
    this.channels.forEach((entry) => {
      if (entry.reconnectTimer) {
        clearTimeout(entry.reconnectTimer);
        entry.reconnectTimer = null;
      }
      entry.authed = false;
      entry.ws?.close();
      entry.ws = null;
    });
    this.setStatus('disconnected');
  }

  private openChannel(channel: WSChannel) {
    if (!SUPPORTED_CHANNELS.has(channel)) return;
    if (typeof window === 'undefined') return;

    const token = this.getToken();
    if (!token) {
      // No JWT — never dial; an unauthenticated socket would just be
      // closed by the gateway (4401).
      this.setStatus('error');
      return;
    }

    let entry = this.channels.get(channel);
    if (!entry) {
      entry = { ws: null, authed: false, reconnectAttempt: 0, reconnectTimer: null };
      this.channels.set(channel, entry);
    }
    if (entry.ws) return;

    this.setStatus('connecting');

    let ws: WebSocket;
    try {
      ws = new WebSocket(gatewayWsUrl(`/${channel}`));
    } catch {
      this.scheduleReconnect(channel);
      return;
    }
    entry.ws = ws;
    entry.authed = false;

    ws.onopen = () => {
      // FIRST frame must be the auth handshake; the gateway rejects any
      // other opening frame with close code 4401.
      ws.send(JSON.stringify({ type: 'auth', token: this.getToken() }));
    };

    ws.onmessage = (event) => {
      let msg: unknown;
      try {
        msg = JSON.parse(event.data as string);
      } catch {
        return; // non-JSON frames are not part of the protocol
      }

      // Auth ack gates the channel — never before it.
      if ((msg as { type?: string; ok?: boolean })?.type === 'auth') {
        if ((msg as { ok?: boolean }).ok === true) {
          entry!.authed = true;
          entry!.reconnectAttempt = 0;
          this.afterAuth(channel, entry!);
          this.recomputeStatus();
        } else {
          ws.close(4401, 'authentication rejected');
        }
        return;
      }

      const payload = msg as WSMessage;
      const ch = payload?.channel ?? channel;
      this.dispatch(ch, payload);
      this.dispatch('*', payload);
    };

    ws.onclose = (event) => {
      // Ignore stale close events from a socket that was already replaced.
      if (entry!.ws !== ws) return;
      entry!.authed = false;
      entry!.ws = null;
      // Auth/permission rejection is terminal until the token changes —
      // do not hammer the gateway with reconnects.
      if (event.code === 4401 || event.code === 4403) {
        this.recomputeStatus();
        this.setStatus('error');
        return;
      }
      this.recomputeStatus();
      if (!this.manuallyClosed) this.scheduleReconnect(channel);
    };

    ws.onerror = () => {
      // onclose follows; reconnect scheduling happens there.
    };
  }

  /** Post-auth hook: re-send channel subscription frames. */
  private afterAuth(channel: WSChannel, entry: ChannelEntry) {
    if (channel === 'ticks' && entry.ws?.readyState === WebSocket.OPEN && entry.params) {
      this.sendTicksSubscribe(entry.ws, entry.params);
    }
  }

  private sendTicksSubscribe(ws: WebSocket, params: Record<string, string | number | boolean>) {
    const raw = params.symbols as string | number | boolean | string[] | undefined;
    const symbols = Array.isArray(raw)
      ? raw
      : typeof raw === 'string'
        ? raw.split(',').map((s) => s.trim()).filter(Boolean)
        : [];
    if (symbols.length > 0) {
      ws.send(JSON.stringify({ action: 'subscribe', symbols }));
    }
  }

  private scheduleReconnect(channel: WSChannel) {
    const entry = this.channels.get(channel);
    if (!entry || this.manuallyClosed) return;

    const delay = Math.min(
      RECONNECT_BASE_DELAY * Math.pow(RECONNECT_MULTIPLIER, entry.reconnectAttempt),
      RECONNECT_MAX_DELAY
    );
    entry.reconnectAttempt++;

    if (entry.reconnectTimer) clearTimeout(entry.reconnectTimer);
    entry.reconnectTimer = setTimeout(() => {
      entry.reconnectTimer = null;
      if (this.manuallyClosed) return;
      // Drop the dead handle, then dial again (auth re-sent on open).
      entry.ws = null;
      this.openChannel(channel);
    }, delay);
  }

  subscribe(channel: WSChannel, params?: Record<string, string | number | boolean>): void {
    this.manuallyClosed = false;
    let entry = this.channels.get(channel);
    if (!entry) {
      entry = { ws: null, authed: false, reconnectAttempt: 0, reconnectTimer: null };
      this.channels.set(channel, entry);
    }
    entry.params = params ?? entry.params;

    if (!SUPPORTED_CHANNELS.has(channel)) {
      // No backend route for this channel — stay inert, never fake a link.
      this.recomputeStatus();
      return;
    }
    if (!entry.ws) this.openChannel(channel);
    else if (entry.authed && channel === 'ticks' && params && entry.ws.readyState === WebSocket.OPEN) {
      this.sendTicksSubscribe(entry.ws, params);
    }
  }

  unsubscribe(channel: WSChannel): void {
    const entry = this.channels.get(channel);
    if (!entry) return;
    if (entry.reconnectTimer) {
      clearTimeout(entry.reconnectTimer);
      entry.reconnectTimer = null;
    }
    entry.ws?.close();
    this.channels.delete(channel);
    this.recomputeStatus();
  }

  on<T = unknown>(channel: WSChannel | '*', callback: EventCallback<T>): () => void {
    if (!this.listeners.has(channel)) {
      this.listeners.set(channel, new Set());
    }
    const set = this.listeners.get(channel)!;
    set.add(callback as EventCallback);

    return () => {
      set.delete(callback as EventCallback);
      if (set.size === 0) {
        this.listeners.delete(channel);
      }
    };
  }

  off(channel: WSChannel | '*', callback: EventCallback): void {
    this.listeners.get(channel)?.delete(callback);
  }

  private dispatch(channel: string, msg: WSMessage): void {
    this.listeners.get(channel)?.forEach((cb) => cb(msg));
  }

  onStatusChange(callback: (status: ConnectionStatus) => void): () => void {
    this.statusCallbacks.add(callback);
    callback(this._status);
    return () => {
      this.statusCallbacks.delete(callback);
    };
  }

  /**
   * Legacy forwarding: sends a raw JSON frame on the ticks channel when it
   * is authenticated. Other channels have no client→server frame in the
   * gateway protocol.
   */
  emit(event: string, data: unknown): void {
    const entry = this.channels.get('ticks');
    if (entry?.authed && entry.ws?.readyState === WebSocket.OPEN) {
      entry.ws.send(JSON.stringify({ event, data }));
    }
  }
}

export const wsClient = new WSClient();
