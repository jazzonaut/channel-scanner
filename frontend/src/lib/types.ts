// TypeScript mirrors of the backend Pydantic / JSON models.
// Field names MUST match the shared CONTRACT.md exactly.
// Frequencies are exact integer Hz everywhere; formatting happens only in the UI.

export type ChannelStatus = 'active' | 'recently_active' | 'inactive';

/** Receiver operating mode: normal band sweeping vs. parked focus (scope) mode. */
export type ScanMode = 'sweep' | 'focus';

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
  device_index: number;
  spectrum_fps: number;
  spectrum_bins: number;
  enable_iq_recording: boolean;
  max_iq_storage_gb: number;
  retention_days: number;
}

/** Allowed receiver backends (mirrors the backend enum). */
export const SCAN_BACKENDS = ['sim', 'rtlsdr', 'rtl_power', 'soapy'] as const;
export type ScanBackend = (typeof SCAN_BACKENDS)[number];

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
  format?: 'cf32' | 'cu8';
}

export interface DecodeFrame {
  id: number;
  timestamp: string;
  decoder: string;
  protocol: string;
  freq_hz: number | null;
  known: boolean;
  fields: Record<string, unknown>;
  session_id: number | null;
}

export interface DecodesResponse {
  decodes: DecodeFrame[];
  decoder_available: boolean;
}

export interface DecoderRunResponse {
  ok: boolean;
  ran: boolean;
  message: string;
  decodes: DecodeFrame[];
}

export interface OccupancyResponse {
  f_start_hz: number;
  f_stop_hz: number;
  freq_bins: number;
  bucket_seconds: number;
  bucket_starts: string[];
  grid: number[][];
}

export interface ModulationHint {
  modulation: 'OOK' | 'FSK' | 'unknown';
  symbol_rate_hz: number | null;
  amplitude_depth: number;
  freq_spread_hz: number;
  confidence: number;
}

export interface CalibrateResponse {
  ok: boolean;
  message: string;
  reference_hz?: number;
  measured_hz?: number;
  offset_hz?: number;
  ppm_error?: number;
  current_ppm?: number;
  suggested_ppm?: number;
  peak_snr_db?: number;
}

export interface WavenisChannelEvidence {
  index: number;
  freq_hz: number;
  noise_db: number | null;
  active: boolean;
  observations: number;
  qualified_observations: number;
  last_seen_s: number | null;
  peak_snr_db: number;
}

export interface WavenisBurstEvidence {
  sequence: number;
  channel_index: number;
  freq_hz: number;
  start_s: number;
  duration_ms: number;
  bandwidth_hz: number;
  peak_snr_db: number;
  noise_db: number;
  above_frames: number;
  qualified: boolean;
  freq_offset_hz: number;
  candidate_reasons: string[];
  candidate_score: number;
  is_candidate: boolean;
}

export interface WavenisCandidateRecord extends WavenisBurstEvidence {
  timestamp: string;
  session_id: number | null;
  receiver_center_hz: number;
}

export interface WavenisCandidatesResponse {
  total: number;
  path: string;
  candidates: WavenisCandidateRecord[];
}

export interface WavenisAcquisitionStatus {
  mode: 'native_continuous' | 'bounded_reads';
  blocks_acquired: number;
  samples_acquired: number;
  sample_cursor: number;
  queue_depth: number;
  queue_capacity: number;
  dropped_blocks: number;
  dropped_samples: number;
  timing_gaps: number;
  estimated_gap_samples: number;
  retunes?: number;
  error: string | null;
}

export interface WavenisCaptureStatus {
  enabled: boolean;
  format: 'cu8';
  buffered_seconds: number;
  pre_trigger_seconds: number;
  post_trigger_seconds: number;
  max_capture_seconds: number;
  capture_pending: boolean;
  pending_triggers: number;
  captures_completed: number;
  captures_aborted_discontinuity: number;
}

export interface WavenisStatus {
  configured: boolean;
  active: boolean;
  message: string;
  center_hz: number;
  receiver_center_hz: number;
  sample_rate: number;
  grid_hz: number[];
  threshold_db: number;
  frame_ms: number | null;
  frames_processed: number;
  channels: WavenisChannelEvidence[];
  recent_bursts: WavenisBurstEvidence[];
  recent_candidates: WavenisBurstEvidence[];
  candidates_flagged: number;
  candidates_persisted?: number;
  acquisition?: WavenisAcquisitionStatus;
  capture?: WavenisCaptureStatus;
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

/**
 * Fine-grained scope frame for the parked "focus" window. Arrives on the same
 * /ws/live socket, only while the receiver is in focus mode, up to ~20/s.
 * The window edges are center -/+ sample_rate/2.
 */
export interface ScopeFrame {
  type: 'scope';
  center_hz: number;
  sample_rate: number;
  f_start_hz: number;
  f_stop_hz: number;
  bin_count: number;
  /** ONE fine spectrogram row across the window (length === bin_count). */
  power_db: number[];
  noise_floor_db: number;
  /** Decimated |IQ| magnitude in dB over the dwell. */
  envelope: number[];
  /** Microseconds per envelope sample. */
  env_dt_us: number;
  seq: number;
  t_ms: number;
  /** Coarse modulation hint for the parked channel (sticky; null until known). */
  modulation?: ModulationHint | null;
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
  /** Current receiver mode. */
  mode: ScanMode;
  /** Parked center when in focus mode, else null. */
  focus_center_hz: number | null;
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

export interface WsDecode {
  type: 'decode';
  decode: DecodeFrame;
}

export type ServerMessage =
  | WsHello
  | SpectrumFrame
  | ScopeFrame
  | WsChannels
  | WsChannelUpdate
  | WsEvent
  | WsStatus
  | WsConfig
  | WsPresence
  | WsControl
  | WsDecode;

export interface ClientIdentify {
  type: 'identify';
  client_id?: string;
  display_name?: string;
}

export interface ClientPing {
  type: 'ping';
}

export type ClientMessage = ClientIdentify | ClientPing;
