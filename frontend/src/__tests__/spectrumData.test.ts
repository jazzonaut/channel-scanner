import { describe, expect, it } from 'vitest';
import { buildSpectrumData, makeFreqAxis } from '../lib/spectrum';

describe('makeFreqAxis', () => {
  it('creates linearly spaced Hz bins inclusive of endpoints', () => {
    const axis = makeFreqAxis(867_000_000, 870_000_000, 4);
    expect(Array.from(axis)).toEqual([867_000_000, 868_000_000, 869_000_000, 870_000_000]);
  });
  it('handles a single bin', () => {
    const axis = makeFreqAxis(868_000_000, 868_000_000, 1);
    expect(axis.length).toBe(1);
    expect(axis[0]).toBe(868_000_000);
  });
});

describe('buildSpectrumData', () => {
  it('maps Hz to MHz on the x axis and passes power through', () => {
    const freqs = [867_000_000, 868_000_000, 869_000_000];
    const power = [-20, -5, -18];
    const [xs, ys] = buildSpectrumData(freqs, power);
    expect(xs).toEqual([867, 868, 869]);
    expect(ys).toEqual([-20, -5, -18]);
  });

  it('replaces non-finite power with null and truncates to shortest length', () => {
    const freqs = [867_000_000, 868_000_000, 869_000_000];
    const power = [Number.NaN, -5];
    const [xs, ys] = buildSpectrumData(freqs, power);
    expect(xs).toEqual([867, 868]);
    expect(ys).toEqual([null, -5]);
  });

  it('accepts typed arrays', () => {
    const freqs = new Float64Array([868_000_000]);
    const power = new Float64Array([-10]);
    const [xs, ys] = buildSpectrumData(freqs, power);
    expect(xs).toEqual([868]);
    expect(ys).toEqual([-10]);
  });
});
