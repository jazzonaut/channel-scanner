import { SCAN_BACKENDS, type ScanBackend, type ScanConfig } from './types';

export interface SettingsFormValues {
  // Receiver
  backend: string; // one of SCAN_BACKENDS
  simulation: boolean;
  deviceIndex: string; // integer >= 0
  // Band & sweep
  startMhz: string;
  endMhz: string;
  stepHz: string; // 0 = auto
  sampleRate: string;
  gain: string; // "auto" or number
  ppm: string;
  dwellMs: string;
  thresholdDb: string;
  noiseFloorAlpha: string;
  exclusions: string; // "lowMHz-highMHz, ..." per line/comma
  knownWidthsHz: string; // comma separated Hz
  fftSize: string;
  // Display
  spectrumFps: string; // integer 1..60
  spectrumBins: string; // integer 16..8192
  // Recording & retention
  enableIqRecording: boolean;
  maxIqStorageGb: string; // float >= 0
  retentionDays: string; // integer >= 1
}

/** Keys of the form that hold string values (text/number/select inputs). */
export type StringFieldKey = {
  [K in keyof SettingsFormValues]: SettingsFormValues[K] extends string ? K : never;
}[keyof SettingsFormValues];

/** Keys of the form that hold boolean values (checkbox toggles). */
export type BoolFieldKey = {
  [K in keyof SettingsFormValues]: SettingsFormValues[K] extends boolean ? K : never;
}[keyof SettingsFormValues];

export type FieldErrors = Partial<Record<keyof SettingsFormValues, string>>;

const BACKEND_SET = new Set<string>(SCAN_BACKENDS);

function isBackend(v: string): v is ScanBackend {
  return BACKEND_SET.has(v);
}

export interface ParsedSettings {
  update: Partial<ScanConfig>;
  errors: FieldErrors;
}

const FFT_SIZES = new Set([256, 512, 1024, 2048, 4096, 8192, 16384]);

function num(v: string): number {
  return Number(v.trim());
}

function isInt(n: number): boolean {
  return Number.isFinite(n) && Number.isInteger(n);
}

/** Parse the "low-high, low-high" exclusion string (MHz) into [Hz,Hz][] or error. */
export function parseExclusions(raw: string): { value: [number, number][]; error?: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { value: [] };
  const parts = trimmed
    .split(/[\n,]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  const out: [number, number][] = [];
  for (const part of parts) {
    const m = part.split(/[-–]/).map((s) => s.trim());
    if (m.length !== 2) return { value: [], error: `Bad range "${part}" (use low-high in MHz)` };
    const lo = Number(m[0]);
    const hi = Number(m[1]);
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
      return { value: [], error: `Non-numeric range "${part}"` };
    }
    if (lo >= hi) return { value: [], error: `Range "${part}" must have low < high` };
    out.push([Math.round(lo * 1e6), Math.round(hi * 1e6)]);
  }
  return { value: out };
}

/** Parse comma-separated known widths in kHz into Hz ints. */
export function parseKnownWidths(raw: string): { value: number[]; error?: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { value: [] };
  const parts = trimmed
    .split(/[\n,]+/)
    .map((p) => p.trim())
    .filter(Boolean);
  const out: number[] = [];
  for (const part of parts) {
    const n = Number(part);
    if (!Number.isFinite(n) || n <= 0) return { value: [], error: `Bad width "${part}" (Hz)` };
    out.push(Math.round(n));
  }
  return { value: out };
}

/**
 * Validate + parse form values into a ScanConfig partial.
 * Frequencies are entered in MHz but stored as exact integer Hz.
 */
export function validateSettings(v: SettingsFormValues): ParsedSettings {
  const errors: FieldErrors = {};
  const update: Partial<ScanConfig> = {};

  const backend = v.backend.trim();
  if (!isBackend(backend)) errors.backend = `Must be one of: ${SCAN_BACKENDS.join(', ')}`;
  else update.backend = backend;

  update.simulation = v.simulation;

  const deviceIndex = num(v.deviceIndex);
  if (!isInt(deviceIndex) || deviceIndex < 0) errors.deviceIndex = 'Integer ≥ 0';
  else update.device_index = deviceIndex;

  const startMhz = num(v.startMhz);
  const endMhz = num(v.endMhz);
  if (!Number.isFinite(startMhz)) errors.startMhz = 'Required, in MHz';
  if (!Number.isFinite(endMhz)) errors.endMhz = 'Required, in MHz';
  if (Number.isFinite(startMhz) && startMhz < 0) errors.startMhz = 'Must be ≥ 0';
  if (Number.isFinite(startMhz) && Number.isFinite(endMhz) && endMhz <= startMhz) {
    errors.endMhz = 'End must be greater than start';
  }
  if (Number.isFinite(startMhz)) update.start_hz = Math.round(startMhz * 1e6);
  if (Number.isFinite(endMhz)) update.end_hz = Math.round(endMhz * 1e6);

  const stepHz = num(v.stepHz);
  if (!isInt(stepHz) || stepHz < 0) errors.stepHz = 'Integer Hz ≥ 0 (0 = auto)';
  else update.step_hz = stepHz;

  const sampleRate = num(v.sampleRate);
  if (!isInt(sampleRate) || sampleRate < 225001) errors.sampleRate = 'Integer ≥ 225001 Hz';
  else update.sample_rate = sampleRate;

  const gain = v.gain.trim();
  if (gain.toLowerCase() === 'auto') {
    update.gain = 'auto';
  } else if (Number.isFinite(Number(gain)) && gain !== '') {
    const g = Number(gain);
    if (g < 0 || g > 60) errors.gain = 'Gain 0–60 dB or "auto"';
    else update.gain = String(g);
  } else {
    errors.gain = 'Use "auto" or a dB value';
  }

  const ppm = num(v.ppm);
  if (!isInt(ppm) || Math.abs(ppm) > 500) errors.ppm = 'Integer ppm within ±500';
  else update.ppm = ppm;

  const dwellMs = num(v.dwellMs);
  if (!isInt(dwellMs) || dwellMs < 1 || dwellMs > 60000) errors.dwellMs = 'Integer 1–60000 ms';
  else update.dwell_ms = dwellMs;

  const thresholdDb = num(v.thresholdDb);
  if (!Number.isFinite(thresholdDb) || thresholdDb < 0 || thresholdDb > 60) {
    errors.thresholdDb = 'dB above noise floor, 0–60';
  } else update.threshold_db = thresholdDb;

  const alpha = num(v.noiseFloorAlpha);
  if (!Number.isFinite(alpha) || alpha <= 0 || alpha >= 1) {
    errors.noiseFloorAlpha = 'EMA alpha in (0,1)';
  } else update.noise_floor_alpha = alpha;

  const fftSize = num(v.fftSize);
  if (!FFT_SIZES.has(fftSize)) errors.fftSize = 'Power of two 256–16384';
  else update.fft_size = fftSize;

  const excl = parseExclusions(v.exclusions);
  if (excl.error) errors.exclusions = excl.error;
  else update.exclusions = excl.value;

  const widths = parseKnownWidths(v.knownWidthsHz);
  if (widths.error) errors.knownWidthsHz = widths.error;
  else update.known_channel_widths_hz = widths.value;

  const spectrumFps = num(v.spectrumFps);
  if (!isInt(spectrumFps) || spectrumFps < 1 || spectrumFps > 60) {
    errors.spectrumFps = 'Integer 1–60 fps';
  } else update.spectrum_fps = spectrumFps;

  const spectrumBins = num(v.spectrumBins);
  if (!isInt(spectrumBins) || spectrumBins < 16 || spectrumBins > 8192) {
    errors.spectrumBins = 'Integer 16–8192';
  } else update.spectrum_bins = spectrumBins;

  update.enable_iq_recording = v.enableIqRecording;

  const maxIqStorageGb = num(v.maxIqStorageGb);
  if (!Number.isFinite(maxIqStorageGb) || maxIqStorageGb < 0) {
    errors.maxIqStorageGb = 'Number ≥ 0 (GB)';
  } else update.max_iq_storage_gb = maxIqStorageGb;

  const retentionDays = num(v.retentionDays);
  if (!isInt(retentionDays) || retentionDays < 1) errors.retentionDays = 'Integer ≥ 1 day';
  else update.retention_days = retentionDays;

  return { update, errors };
}

export interface SettingsWarning {
  field: keyof SettingsFormValues | 'general';
  message: string;
}

/**
 * Non-blocking advisories: wide span vs dwell (bursts missed), gain likely to clip.
 */
export function computeWarnings(v: SettingsFormValues): SettingsWarning[] {
  const warnings: SettingsWarning[] = [];
  const startHz = num(v.startMhz) * 1e6;
  const endHz = num(v.endMhz) * 1e6;
  const sampleRate = num(v.sampleRate);
  const dwellMs = num(v.dwellMs);

  if (Number.isFinite(startHz) && Number.isFinite(endHz) && endHz > startHz && sampleRate > 0) {
    const span = endHz - startHz;
    // Approx number of tuner hops to cover the span (usable bandwidth ~ 80% Fs).
    const usable = sampleRate * 0.8;
    const hops = Math.max(1, Math.ceil(span / usable));
    if (Number.isFinite(dwellMs) && dwellMs > 0) {
      const sweepMs = hops * dwellMs;
      const dwellPerHop = dwellMs;
      if (span > 10 * usable && dwellPerHop < 100) {
        warnings.push({
          field: 'dwellMs',
          message: `Wide span (${(span / 1e6).toFixed(1)} MHz ≈ ${hops} hops) with only ${dwellMs} ms dwell per hop. Full sweep ≈ ${(sweepMs / 1000).toFixed(1)} s — short or infrequent transmissions may be missed. Narrow the span or increase dwell.`,
        });
      }
    }
  }

  const gain = v.gain.trim();
  if (gain.toLowerCase() !== 'auto') {
    const g = Number(gain);
    if (Number.isFinite(g) && g >= 40) {
      warnings.push({
        field: 'gain',
        message: `Gain ${g} dB is high and may clip / overload the front end on strong nearby signals. Reduce gain if you see a flat-topped spectrum.`,
      });
    }
  }

  return warnings;
}

/** Build initial form values from a live ScanConfig. */
export function configToForm(c: ScanConfig): SettingsFormValues {
  return {
    backend: c.backend,
    simulation: c.simulation,
    deviceIndex: c.device_index.toString(),
    startMhz: (c.start_hz / 1e6).toString(),
    endMhz: (c.end_hz / 1e6).toString(),
    stepHz: c.step_hz.toString(),
    sampleRate: c.sample_rate.toString(),
    gain: c.gain,
    ppm: c.ppm.toString(),
    dwellMs: c.dwell_ms.toString(),
    thresholdDb: c.threshold_db.toString(),
    noiseFloorAlpha: c.noise_floor_alpha.toString(),
    exclusions: c.exclusions.map(([lo, hi]) => `${lo / 1e6}-${hi / 1e6}`).join(', '),
    knownWidthsHz: c.known_channel_widths_hz.join(', '),
    fftSize: c.fft_size.toString(),
    spectrumFps: c.spectrum_fps.toString(),
    spectrumBins: c.spectrum_bins.toString(),
    enableIqRecording: c.enable_iq_recording,
    maxIqStorageGb: c.max_iq_storage_gb.toString(),
    retentionDays: c.retention_days.toString(),
  };
}

export const PRESETS: Record<string, Partial<SettingsFormValues>> = {
  'near-device': {
    stepHz: '0',
    sampleRate: '2400000',
    gain: 'auto',
    dwellMs: '250',
    thresholdDb: '8',
    noiseFloorAlpha: '0.05',
    fftSize: '2048',
  },
  'long-survey': {
    stepHz: '0',
    sampleRate: '2400000',
    gain: 'auto',
    dwellMs: '1000',
    thresholdDb: '5',
    noiseFloorAlpha: '0.02',
    fftSize: '4096',
  },
};
