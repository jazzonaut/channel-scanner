import { describe, expect, it } from 'vitest';
import {
  formatBytes,
  formatConfidence,
  formatDb,
  formatDuration,
  formatIntervalSeconds,
  formatSampleRate,
  hzToHuman,
  hzToMHz,
  mhzToHz,
} from '../lib/format';

describe('hzToHuman', () => {
  it('formats MHz range values', () => {
    expect(hzToHuman(868_000_000)).toBe('868 MHz');
    expect(hzToHuman(867_500_000)).toBe('867.5 MHz');
  });
  it('formats kHz', () => {
    expect(hzToHuman(125_000)).toBe('125 kHz');
  });
  it('formats GHz', () => {
    expect(hzToHuman(1_500_000_000)).toBe('1.5 GHz');
  });
  it('formats raw Hz below 1 kHz', () => {
    expect(hzToHuman(500)).toBe('500 Hz');
  });
  it('handles non-finite input', () => {
    expect(hzToHuman(Number.NaN)).toBe('—');
  });
  it('trims trailing zeros', () => {
    expect(hzToHuman(868_100_000)).toBe('868.1 MHz');
  });
});

describe('hz <-> MHz conversion keeps integer Hz', () => {
  it('round-trips exactly', () => {
    expect(hzToMHz(868_000_000)).toBe(868);
    expect(mhzToHz(868.1)).toBe(868_100_000);
    expect(mhzToHz(867.123456)).toBe(867_123_456);
  });
});

describe('dB / SNR formatting', () => {
  it('formats dB with unit', () => {
    expect(formatDb(6)).toBe('6.0 dB');
    expect(formatDb(-12.34, 2)).toBe('-12.34 dB');
  });
  it('handles null', () => {
    expect(formatDb(null)).toBe('—');
    expect(formatDb(undefined)).toBe('—');
  });
});

describe('confidence', () => {
  it('renders percent and clamps', () => {
    expect(formatConfidence(0.5)).toBe('50%');
    expect(formatConfidence(1.5)).toBe('100%');
    expect(formatConfidence(-1)).toBe('0%');
  });
});

describe('durations & intervals', () => {
  it('formats ms/s/min', () => {
    expect(formatDuration(50)).toBe('50 ms');
    expect(formatDuration(1500)).toBe('1.5 s');
    expect(formatDuration(180_000)).toBe('3 min');
    expect(formatDuration(null)).toBe('—');
  });
  it('formats interval seconds', () => {
    expect(formatIntervalSeconds(0.5)).toBe('500 ms');
    expect(formatIntervalSeconds(30)).toBe('30 s');
    expect(formatIntervalSeconds(300)).toBe('5 min');
    expect(formatIntervalSeconds(null)).toBe('—');
  });
});

describe('bytes & sample rate', () => {
  it('formats bytes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1024)).toBe('1 KB');
    expect(formatBytes(1_572_864)).toBe('1.5 MB');
  });
  it('formats sample rate', () => {
    expect(formatSampleRate(2_400_000)).toBe('2.4 MS/s');
  });
});
