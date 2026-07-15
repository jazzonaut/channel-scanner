import { describe, expect, it } from 'vitest';
import {
  computeWarnings,
  configToForm,
  parseExclusions,
  validateSettings,
  type SettingsFormValues,
} from '../lib/settingsValidation';
import type { ScanConfig } from '../lib/types';

const BASE_CONFIG: ScanConfig = {
  start_hz: 867_000_000,
  end_hz: 870_000_000,
  step_hz: 0,
  sample_rate: 2_400_000,
  gain: 'auto',
  ppm: 0,
  dwell_ms: 120,
  threshold_db: 6,
  noise_floor_alpha: 0.05,
  exclusions: [[868_200_000, 868_400_000]],
  known_channel_widths_hz: [12_500, 25_000],
  fft_size: 2048,
  backend: 'sim',
  simulation: true,
  device_index: 0,
  spectrum_fps: 30,
  spectrum_bins: 1024,
  enable_iq_recording: false,
  max_iq_storage_gb: 5,
  retention_days: 30,
};

function validForm(): SettingsFormValues {
  return configToForm(BASE_CONFIG);
}

describe('configToForm', () => {
  it('converts Hz to MHz for display and preserves widths', () => {
    const f = configToForm(BASE_CONFIG);
    expect(f.startMhz).toBe('867');
    expect(f.endMhz).toBe('870');
    expect(f.exclusions).toBe('868.2-868.4');
    expect(f.knownWidthsHz).toBe('12500, 25000');
  });
});

describe('validateSettings', () => {
  it('accepts a valid form and produces integer Hz', () => {
    const { update, errors } = validateSettings(validForm());
    expect(errors).toEqual({});
    expect(update.start_hz).toBe(867_000_000);
    expect(update.end_hz).toBe(870_000_000);
    expect(update.exclusions).toEqual([[868_200_000, 868_400_000]]);
    expect(update.gain).toBe('auto');
  });

  it('rejects end <= start', () => {
    const f = validForm();
    f.endMhz = '866';
    const { errors } = validateSettings(f);
    expect(errors.endMhz).toBeDefined();
  });

  it('rejects an out-of-range gain', () => {
    const f = validForm();
    f.gain = '120';
    const { errors } = validateSettings(f);
    expect(errors.gain).toBeDefined();
  });

  it('accepts numeric gain and normalizes to string', () => {
    const f = validForm();
    f.gain = '30';
    const { update, errors } = validateSettings(f);
    expect(errors.gain).toBeUndefined();
    expect(update.gain).toBe('30');
  });

  it('rejects an invalid FFT size', () => {
    const f = validForm();
    f.fftSize = '1000';
    const { errors } = validateSettings(f);
    expect(errors.fftSize).toBeDefined();
  });

  it('rejects a sample rate below the RTL-SDR minimum', () => {
    const f = validForm();
    f.sampleRate = '1000';
    const { errors } = validateSettings(f);
    expect(errors.sampleRate).toBeDefined();
  });

  it('accepts the new runtime fields and produces typed values', () => {
    const { update, errors } = validateSettings(validForm());
    expect(errors).toEqual({});
    expect(update.backend).toBe('sim');
    expect(update.simulation).toBe(true);
    expect(update.device_index).toBe(0);
    expect(update.spectrum_fps).toBe(30);
    expect(update.spectrum_bins).toBe(1024);
    expect(update.enable_iq_recording).toBe(false);
    expect(update.max_iq_storage_gb).toBe(5);
    expect(update.retention_days).toBe(30);
  });

  it('rejects an unknown backend', () => {
    const f = validForm();
    f.backend = 'hackrf';
    const { errors } = validateSettings(f);
    expect(errors.backend).toBeDefined();
  });

  it('rejects a negative device index', () => {
    const f = validForm();
    f.deviceIndex = '-1';
    const { errors } = validateSettings(f);
    expect(errors.deviceIndex).toBeDefined();
  });

  it('rejects an out-of-range spectrum FPS', () => {
    const f = validForm();
    f.spectrumFps = '90';
    const { errors } = validateSettings(f);
    expect(errors.spectrumFps).toBeDefined();

    f.spectrumFps = '0';
    expect(validateSettings(f).errors.spectrumFps).toBeDefined();
  });

  it('rejects out-of-range spectrum bins', () => {
    const f = validForm();
    f.spectrumBins = '8';
    expect(validateSettings(f).errors.spectrumBins).toBeDefined();
    f.spectrumBins = '9000';
    expect(validateSettings(f).errors.spectrumBins).toBeDefined();
  });

  it('rejects negative retention days and non-integer values', () => {
    const f = validForm();
    f.retentionDays = '-3';
    expect(validateSettings(f).errors.retentionDays).toBeDefined();
    f.retentionDays = '0';
    expect(validateSettings(f).errors.retentionDays).toBeDefined();
    f.retentionDays = '1.5';
    expect(validateSettings(f).errors.retentionDays).toBeDefined();
  });

  it('rejects negative max IQ storage', () => {
    const f = validForm();
    f.maxIqStorageGb = '-1';
    expect(validateSettings(f).errors.maxIqStorageGb).toBeDefined();
  });
});

describe('parseExclusions', () => {
  it('parses MHz ranges to Hz', () => {
    const r = parseExclusions('868.2-868.4, 869.0-869.5');
    expect(r.error).toBeUndefined();
    expect(r.value).toEqual([
      [868_200_000, 868_400_000],
      [869_000_000, 869_500_000],
    ]);
  });
  it('errors on inverted ranges', () => {
    const r = parseExclusions('869-868');
    expect(r.error).toBeDefined();
  });
});

describe('computeWarnings', () => {
  it('warns when span is wide and dwell is short', () => {
    const f = validForm();
    f.startMhz = '80';
    f.endMhz = '900';
    f.dwellMs = '20';
    const warnings = computeWarnings(f);
    expect(warnings.some((w) => w.field === 'dwellMs')).toBe(true);
  });

  it('warns when gain is high enough to clip', () => {
    const f = validForm();
    f.gain = '49';
    const warnings = computeWarnings(f);
    expect(warnings.some((w) => w.field === 'gain')).toBe(true);
  });

  it('no warnings for a conservative narrow-band config', () => {
    const warnings = computeWarnings(validForm());
    expect(warnings).toEqual([]);
  });
});
