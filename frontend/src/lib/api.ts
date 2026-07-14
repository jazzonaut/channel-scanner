// Typed REST client covering every endpoint in CONTRACT.md.
// All paths are under /api. In production this is same-origin; in dev the Vite
// proxy forwards /api to the backend at :8080.

import type {
  AcquireResponse,
  AppEvent,
  CandidateChannel,
  ClientsResponse,
  Detection,
  DeviceInfo,
  ExportKind,
  FocusRequest,
  HealthResponse,
  Metrics,
  OkResponse,
  Recording,
  RecordingStartRequest,
  ReleaseResponse,
  ScanConfigUpdate,
  ScanConfigVersioned,
  ScanStartResponse,
  Session,
} from './types';

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

/** Thrown for any non-2xx response. `status` lets callers special-case 409, etc. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

function url(path: string): string {
  return `${API_BASE}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url(path), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init?.body != null ? { 'Content-Type': 'application/json' } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(0, `Network error: ${String(err)}`, null);
  }

  if (!res.ok) {
    const body = await safeParse(res);
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : res.statusText;
    throw new ApiError(res.status, `${res.status} ${detail}`, body);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function safeParse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function jsonBody(data: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(data) };
}

export const api = {
  // --- health / metrics / device ---
  getHealth: (): Promise<HealthResponse> => request('/api/health'),
  getMetrics: (): Promise<Metrics> => request('/api/metrics'),
  getDevice: (): Promise<DeviceInfo> => request('/api/device'),

  // --- config ---
  getConfig: (): Promise<ScanConfigVersioned> => request('/api/config'),
  updateConfig: (
    update: ScanConfigUpdate,
    version: number,
    clientId: string,
  ): Promise<ScanConfigVersioned> =>
    request('/api/config', {
      method: 'PUT',
      body: JSON.stringify({ ...update, version, client_id: clientId }),
    }),

  // --- scan control ---
  startScan: (): Promise<ScanStartResponse> => request('/api/scan/start', { method: 'POST' }),
  stopScan: (): Promise<OkResponse> => request('/api/scan/stop', { method: 'POST' }),
  focusScan: (body: FocusRequest): Promise<OkResponse> => request('/api/scan/focus', jsonBody(body)),

  // --- channels ---
  getChannels: (): Promise<{ channels: CandidateChannel[] }> => request('/api/channels'),
  getChannel: (id: number): Promise<CandidateChannel> => request(`/api/channels/${id}`),
  getChannelObservations: (id: number, limit = 200): Promise<{ observations: Detection[] }> =>
    request(`/api/channels/${id}/observations?limit=${encodeURIComponent(limit)}`),

  // --- events / sessions ---
  getEvents: (opts?: { limit?: number; since?: string }): Promise<{ events: AppEvent[] }> => {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set('limit', String(opts.limit));
    if (opts?.since != null) params.set('since', opts.since);
    const qs = params.toString();
    return request(`/api/events${qs ? `?${qs}` : ''}`);
  },
  getSessions: (): Promise<{ sessions: Session[] }> => request('/api/sessions'),

  // --- export (returns download URLs; the browser handles the download) ---
  exportUrl: (format: 'csv' | 'json', kind: ExportKind): string =>
    url(`/api/export.${format}?kind=${encodeURIComponent(kind)}`),

  // --- recordings ---
  startRecording: (body: RecordingStartRequest): Promise<Recording> =>
    request('/api/recordings/start', jsonBody(body)),
  stopRecording: (): Promise<OkResponse> => request('/api/recordings/stop', { method: 'POST' }),
  getRecordings: (): Promise<{ recordings: Recording[] }> => request('/api/recordings'),
  deleteRecording: (id: number): Promise<OkResponse> =>
    request(`/api/recordings/${id}`, { method: 'DELETE' }),

  // --- clients / control lease ---
  getClients: (): Promise<ClientsResponse> => request('/api/clients'),
  acquireControl: (clientId: string, displayName?: string): Promise<AcquireResponse> =>
    request(
      '/api/control/acquire',
      jsonBody(
        displayName != null
          ? { client_id: clientId, display_name: displayName }
          : { client_id: clientId },
      ),
    ),
  releaseControl: (clientId: string): Promise<ReleaseResponse> =>
    request('/api/control/release', jsonBody({ client_id: clientId })),
};

export type Api = typeof api;
