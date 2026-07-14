// WebSocket client for /ws/live with auto-reconnect + exponential backoff.
// Sends `identify` on open and dispatches every server message type to the store.

import type { ClientMessage, ServerMessage } from './types';
import { useStore } from '../store/store';

const WS_PATH = '/ws/live';
const BASE_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 15_000;
const PING_INTERVAL_MS = 20_000;

function resolveWsUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured) return configured;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${WS_PATH}`;
}

export class LiveConnection {
  private ws: WebSocket | null = null;
  private backoff = BASE_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private stopped = false;

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    useStore.getState().setConnection('closed');
  }

  private connect(): void {
    if (this.stopped) return;
    const store = useStore.getState();
    store.setConnection(this.backoff === BASE_BACKOFF_MS ? 'connecting' : 'reconnecting');

    let ws: WebSocket;
    try {
      ws = new WebSocket(resolveWsUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = BASE_BACKOFF_MS;
      useStore.getState().setConnection('open');
      const s = useStore.getState();
      this.send({
        type: 'identify',
        client_id: s.clientId,
        ...(s.displayName != null ? { display_name: s.displayName } : {}),
      });
      this.startPing();
    };

    ws.onmessage = (ev) => {
      this.handleMessage(ev.data);
    };

    ws.onerror = () => {
      // onclose will follow; nothing to do here.
    };

    ws.onclose = () => {
      this.clearPing();
      if (!this.stopped) this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    useStore.getState().setConnection('reconnecting');
    this.clearReconnect();
    const jitter = Math.random() * 0.3 * this.backoff;
    const delay = Math.min(this.backoff + jitter, MAX_BACKOFF_MS);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }

  private startPing(): void {
    this.clearPing();
    this.pingTimer = setInterval(() => this.send({ type: 'ping' }), PING_INTERVAL_MS);
  }

  private clearPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearPing();
    this.clearReconnect();
  }

  send(msg: ClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== 'string') return;
    let msg: ServerMessage;
    try {
      msg = JSON.parse(raw) as ServerMessage;
    } catch {
      return;
    }
    dispatch(msg);
  }
}

function dispatch(msg: ServerMessage): void {
  const store = useStore.getState();
  switch (msg.type) {
    case 'hello':
      store.setConfig(msg.config, msg.version);
      store.setLease(msg.operator_client_id, store.lease.leaseExpires);
      break;
    case 'spectrum':
      store.setSpectrum(msg);
      break;
    case 'channels':
      store.setChannels(msg.channels);
      break;
    case 'channel_update':
      store.upsertChannel(msg.channel);
      break;
    case 'event':
      store.addEvent(msg.event);
      break;
    case 'status':
      store.setStatus(msg.device, msg.metrics, msg.scanning);
      break;
    case 'config':
      store.setConfig(msg.config, msg.version, msg.changed_by);
      break;
    case 'presence':
      store.setPresence(msg.clients, msg.count, msg.operator_client_id);
      break;
    case 'control':
      store.setLease(msg.operator_client_id, msg.lease_expires);
      break;
    default: {
      // Exhaustiveness guard: unknown message types are ignored.
      const _never: never = msg;
      void _never;
    }
  }
}

// Singleton connection shared across the app.
export const liveConnection = new LiveConnection();
