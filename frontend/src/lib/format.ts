// Formatting helpers. Frequencies are stored/passed as exact integer Hz and only
// formatted for display here. Never round-trip a displayed value back into Hz.

/**
 * Human-readable frequency. Picks GHz/MHz/kHz/Hz by magnitude.
 * @param hz exact integer Hz
 * @param maxFractionDigits max digits after the decimal point (default 6)
 */
export function hzToHuman(hz: number, maxFractionDigits = 6): string {
  if (!Number.isFinite(hz)) return '—';
  const abs = Math.abs(hz);
  let value: number;
  let unit: string;
  if (abs >= 1e9) {
    value = hz / 1e9;
    unit = 'GHz';
  } else if (abs >= 1e6) {
    value = hz / 1e6;
    unit = 'MHz';
  } else if (abs >= 1e3) {
    value = hz / 1e3;
    unit = 'kHz';
  } else {
    return `${hz} Hz`;
  }
  const s = trimFloat(value, maxFractionDigits);
  return `${s} ${unit}`;
}

/** Frequency in MHz as a number (for chart axes). Keeps full precision. */
export function hzToMHz(hz: number): number {
  return hz / 1e6;
}

/** Convert a MHz value entered by a user back to exact integer Hz. */
export function mhzToHz(mhz: number): number {
  return Math.round(mhz * 1e6);
}

/** Bandwidth / span, formatted with sensible units. */
export function hzSpanToHuman(hz: number): string {
  return hzToHuman(hz, 3);
}

/** dB power with fixed precision and explicit unit. */
export function formatDb(db: number | null | undefined, digits = 1): string {
  if (db == null || !Number.isFinite(db)) return '—';
  return `${db.toFixed(digits)} dB`;
}

/** SNR value (dB). */
export function formatSnr(db: number | null | undefined): string {
  return formatDb(db, 1);
}

/** Confidence 0..1 -> percentage. */
export function formatConfidence(c: number): string {
  if (!Number.isFinite(c)) return '—';
  return `${Math.round(clamp01(c) * 100)}%`;
}

/** Milliseconds -> "12 ms" / "1.20 s" / "2.5 min". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${trimFloat(ms, 1)} ms`;
  const s = ms / 1000;
  if (s < 120) return `${trimFloat(s, 2)} s`;
  return `${trimFloat(s / 60, 1)} min`;
}

/** Seconds interval -> human string. */
export function formatIntervalSeconds(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—';
  if (s < 1) return `${trimFloat(s * 1000, 0)} ms`;
  if (s < 120) return `${trimFloat(s, 1)} s`;
  if (s < 7200) return `${trimFloat(s / 60, 1)} min`;
  return `${trimFloat(s / 3600, 1)} h`;
}

/** ISO 8601 string -> local human timestamp. */
export function formatIso(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** ISO 8601 -> local time only (HH:MM:SS). */
export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

/** "3s ago", "5m ago", relative to now. */
export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const deltaS = Math.max(0, Math.round((now - t) / 1000));
  if (deltaS < 60) return `${deltaS}s ago`;
  if (deltaS < 3600) return `${Math.round(deltaS / 60)}m ago`;
  if (deltaS < 86400) return `${Math.round(deltaS / 3600)}h ago`;
  return `${Math.round(deltaS / 86400)}d ago`;
}

/** Bytes -> "1.5 MB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${trimFloat(v, 1)} ${units[i]}`;
}

/** Percentage 0..1 or 0..100? Interprets input as 0..1 fraction. */
export function formatPercent(frac: number | null | undefined, digits = 0): string {
  if (frac == null || !Number.isFinite(frac)) return '—';
  return `${(clamp01(frac) * 100).toFixed(digits)}%`;
}

/** Sample rate in Hz -> "2.400 MS/s". */
export function formatSampleRate(hz: number | null | undefined): string {
  if (hz == null || !Number.isFinite(hz)) return '—';
  return `${trimFloat(hz / 1e6, 3)} MS/s`;
}

// --- internal helpers -------------------------------------------------------

function trimFloat(value: number, maxFractionDigits: number): string {
  let s = value.toFixed(maxFractionDigits);
  if (s.includes('.')) {
    s = s.replace(/0+$/, '').replace(/\.$/, '');
  }
  return s;
}

export function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}
