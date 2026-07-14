// TypeScript mirrors of the backend Pydantic / JSON models.
// Field names MUST match the shared CONTRACT.md exactly.
// Frequencies are exact integer Hz everywhere; formatting happens only in the UI.

export type ChannelStatus = 'active' | 'recently_active' | 'inactive';

export type ExportKind = 'channels' | 'detections' | 'events';

/** [low_hz, high_hz] inclusive excluded range. */
export type HzRange = [number, number];

export interface ScanConfig {
  start_hz: number;
  end_hz: number;
  step_hz: number;
  sample_rate: number;
  gain: string; // "auto" or float dB as string
  ppm: number;
  dwell_ms: number;
  threshold_db: number;
  noise_floor_alpha: number;
  exclusions: HzRange[];
  known_channel_widths_hz: number[];
  fft_size: number;
  backend: string;
  simulation: boolean;
}

/** All fields optional; only changed fields are sent. */
export type ScanConfigUpdate = Partial<ScanConfig>;

/** GET/PUT /api/config wraps ScanConfig with a version. */
export interface ScanConfigVersioned extends ScanConfig {
  version: number;
}

export interface Fingerprint {
  center_hz: number;
  bandwidth_hz: number;
  duration_ms: number;
  rel_strength_db: number;
  repetition_interval_s: number;
  envelope: number[];
}

export interface CandidateChannel {
  id: number;
  center_hz: number;
  bandwidth_hz: number;
  current_power_db: number;
  peak_power_db: number;
  avg_power_db: number;
  snr_db: number;
  observation_count: number;
  first_seen: string;
  last_seen: string;
  typical_burst_ms: number | null;
  recurrence_interval_s: number | null;
  confidence: number; // 0..1
  status: ChannelStatus;
  fingerprint: Fingerprint | null;
}

export interface Detection {
  id: number;
  channel_id: number | null;
  session_id: number;
  timestamp: string;
  center_hz: number;
  bandwidth_hz: number;
  peak_power_db: number;
  avg_power_db: number;
  snr_db: number;
  duration_ms: number | null;
}

export interface AppEvent {
  id: number;
  timestamp: string;
  kind: string;
  message: string;
  client_id: string | null;
  data: Record<string, unknown> | null;
}

export interface Session {
  id: number;
  started_at: string;
  stopped_at: string | null;
  start_hz: number;
  end_hz: number;
  backend: string;
  simulation: boolean;
}

export interface Recording {
  id: number;
  timestamp: string;
  path: string;
  center_hz: number;
  sample_rate: number;
  gain: string;
  duration_ms: number;
  format: string;
  bytes: number;
  sigmf_meta: Record<string, unknown> | null;
}

export interface ClientInfo {
  client_id: string;
  display_name: string;
  connected_at: string;
  is_operator: boolean;
}

export interface DeviceInfo {
  backend: string;
  name: string;
  index: number;
  available: boolean;
  simulation: boolean;
  tuner: string;
  gains: number[];
  sample_rates: number[];
  freq_range_hz: [number, number];
}

export interface HealthResponse {
  status: string;
  simulation: boolean;
  uptime_s: number;
  version: string;
}

export interface Metrics {
  fft_rate_hz: number;
  ws_clients: number;
  queue_depth: number;
  dropped_frames: number;
  scan_progress: number;
  db_size_bytes: number;
  recording_bytes: number;
}

export interface ClientsResponse {
  clients: ClientInfo[];
  operator_client_id: string | null;
  count: number;
}

export interface AcquireResponse {
  ok: boolean;
  operator_client_id: string;
  lease_expires: string;
}

export interface ReleaseResponse {
  ok: boolean;
}

export interface ScanStartResponse {
  ok: boolean;
  session_id: number;
}

export interface OkResponse {
  ok: boolean;
}

export interface FocusRequest {
  center_hz: number;
  span_hz?: number;
  channel_id?: number;
}

export interface RecordingStartRequest {
  duration_ms?: number;
  center_hz?: number;
}

// ---------------------------------------------------------------------------
// WebSocket protocol (/ws/live)
// ---------------------------------------------------------------------------

export interface SpectrumFrame {
  type: 'spectrum';
  session_id: number;
  timestamp: string;
  f_start_hz: number;
  f_stop_hz: number;
  bin_count: number;
  power_db: number[];
  noise_floor_db: number;
  scan_pos_hz: number;
}

export interface WsHello {
  type: 'hello';
  client_id: string;
  version: number;
  config: ScanConfig;
  operator_client_id: string | null;
}

export interface WsChannels {
  type: 'channels';
  channels: CandidateChannel[];
}

export interface WsChannelUpdate {
  type: 'channel_update';
  channel: CandidateChannel;
}

export interface WsEvent {
  type: 'event';
  event: AppEvent;
}

export interface WsStatus {
  type: 'status';
  device: DeviceInfo;
  metrics: Metrics;
  scanning: boolean;
}

export interface WsConfig {
  type: 'config';
  config: ScanConfig;
  version: number;
  changed_by: string | null;
}

export interface WsPresence {
  type: 'presence';
  clients: ClientInfo[];
  count: number;
  operator_client_id: string | null;
}

export interface WsControl {
  type: 'control';
  operator_client_id: string | null;
  lease_expires: string | null;
}

export type ServerMessage =
  | WsHello
  | SpectrumFrame
  | WsChannels
  | WsChannelUpdate
  | WsEvent
  | WsStatus
  | WsConfig
  | WsPresence
  | WsControl;

export interface ClientIdentify {
  type: 'identify';
  client_id?: string;
  display_name?: string;
}

export interface ClientPing {
  type: 'ping';
}

export type ClientMessage = ClientIdentify | ClientPing;
