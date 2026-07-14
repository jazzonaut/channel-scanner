// Pure spectrum data helpers, kept separate from the chart component so both
// the component and unit tests can import them (and Fast Refresh stays happy).

import { hzToMHz } from './format';

/**
 * Build the [x, y] data arrays uPlot expects.
 * X is converted from Hz to MHz; non-finite power values become null.
 */
export function buildSpectrumData(
  freqsHz: Float64Array | number[],
  powerDb: Float64Array | number[],
): [number[], (number | null)[]] {
  const n = Math.min(freqsHz.length, powerDb.length);
  const xs: number[] = new Array(n);
  const ys: (number | null)[] = new Array(n);
  for (let i = 0; i < n; i += 1) {
    xs[i] = hzToMHz(freqsHz[i] as number);
    const p = powerDb[i] as number;
    ys[i] = Number.isFinite(p) ? p : null;
  }
  return [xs, ys];
}

/** Linear-spaced frequency bins for a spectrum frame (Hz). */
export function makeFreqAxis(fStartHz: number, fStopHz: number, binCount: number): Float64Array {
  const out = new Float64Array(binCount);
  if (binCount <= 1) {
    out[0] = fStartHz;
    return out;
  }
  const step = (fStopHz - fStartHz) / (binCount - 1);
  for (let i = 0; i < binCount; i += 1) out[i] = fStartHz + step * i;
  return out;
}
