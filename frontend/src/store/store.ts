import { create } from 'zustand';
import type {
  AppEvent,
  CandidateChannel,
  ClientInfo,
  DeviceInfo,
  Metrics,
  ScanConfig,
  SpectrumFrame,
} from '../lib/types';
import { getDisplayName, getOrCreateClientId, setDisplayName } from '../lib/identity';

export type ConnectionStatus = 'connecting' | 'open' | 'closed' | 'reconnecting';

const MAX_EVENTS = 500;

export interface OperatorLease {
  operatorClientId: string | null;
  leaseExpires: string | null;
}

export interface AppState {
  // identity
  clientId: string;
  displayName: string | undefined;
  setDisplayName: (name: string) => void;

  // connection
  connection: ConnectionStatus;
  setConnection: (s: ConnectionStatus) => void;

  // config
  config: ScanConfig | null;
  configVersion: number;
  configChangedBy: string | null;
  setConfig: (config: ScanConfig, version: number, changedBy?: string | null) => void;

  // device + metrics + scanning
  device: DeviceInfo | null;
  metrics: Metrics | null;
  scanning: boolean;
  setStatus: (device: DeviceInfo, metrics: Metrics, scanning: boolean) => void;
  setMetrics: (metrics: Metrics) => void;
  setDevice: (device: DeviceInfo) => void;

  // channels (keyed by id)
  channels: Map<number, CandidateChannel>;
  setChannels: (channels: CandidateChannel[]) => void;
  upsertChannel: (channel: CandidateChannel) => void;

  // events (bounded, newest first)
  events: AppEvent[];
  addEvent: (event: AppEvent) => void;
  setEvents: (events: AppEvent[]) => void;

  // latest spectrum frame only (previous dropped)
  spectrum: SpectrumFrame | null;
  setSpectrum: (frame: SpectrumFrame) => void;

  // presence
  clients: ClientInfo[];
  presenceCount: number;
  setPresence: (clients: ClientInfo[], count: number, operatorClientId: string | null) => void;

  // operator lease
  lease: OperatorLease;
  setLease: (operatorClientId: string | null, leaseExpires: string | null) => void;

  // derived helpers
  isOperator: () => boolean;
}

export const useStore = create<AppState>((set, get) => ({
  clientId: getOrCreateClientId(),
  displayName: getDisplayName(),
  setDisplayName: (name: string) => {
    setDisplayName(name);
    set({ displayName: name.trim() || undefined });
  },

  connection: 'connecting',
  setConnection: (s) => set({ connection: s }),

  config: null,
  configVersion: 0,
  configChangedBy: null,
  setConfig: (config, version, changedBy = null) =>
    set({ config, configVersion: version, configChangedBy: changedBy }),

  device: null,
  metrics: null,
  scanning: false,
  setStatus: (device, metrics, scanning) => set({ device, metrics, scanning }),
  setMetrics: (metrics) => set({ metrics }),
  setDevice: (device) => set({ device }),

  channels: new Map(),
  setChannels: (channels) => {
    const map = new Map<number, CandidateChannel>();
    for (const ch of channels) map.set(ch.id, ch);
    set({ channels: map });
  },
  upsertChannel: (channel) => {
    const map = new Map(get().channels);
    map.set(channel.id, channel);
    set({ channels: map });
  },

  events: [],
  addEvent: (event) => {
    const next = [event, ...get().events];
    if (next.length > MAX_EVENTS) next.length = MAX_EVENTS;
    set({ events: next });
  },
  setEvents: (events) => {
    const sorted = [...events].sort((a, b) => b.timestamp.localeCompare(a.timestamp));
    if (sorted.length > MAX_EVENTS) sorted.length = MAX_EVENTS;
    set({ events: sorted });
  },

  spectrum: null,
  setSpectrum: (frame) => set({ spectrum: frame }),

  clients: [],
  presenceCount: 0,
  setPresence: (clients, count, operatorClientId) =>
    set((state) => ({
      clients,
      presenceCount: count,
      lease: { operatorClientId, leaseExpires: state.lease.leaseExpires },
    })),

  lease: { operatorClientId: null, leaseExpires: null },
  setLease: (operatorClientId, leaseExpires) => set({ lease: { operatorClientId, leaseExpires } }),

  isOperator: () => {
    const state = get();
    return state.lease.operatorClientId != null && state.lease.operatorClientId === state.clientId;
  },
}));
