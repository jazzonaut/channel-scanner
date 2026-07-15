import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { InfoTip } from '../components/InfoTip';
import { turboColor } from '../lib/colormap';
import { formatTimeOnly, hzToMHz } from '../lib/format';
import type { OccupancyResponse } from '../lib/types';
import './Occupancy.css';

const INFO_TEXT =
  'Shows which parts of the band were active over time, so you can spot infrequent or scheduled transmitters — ' +
  "e.g. a utility meter that reports periodically. Receive-only: the counts are this app's own detections, " +
  'binned by frequency (across) and time (down).';

const MINUTES_OPTIONS = [5, 15, 30, 60, 360] as const;
const FREQ_BIN_OPTIONS = [48, 96, 192] as const;
const BUCKET_OPTIONS = [15, 30, 60] as const;

const DEFAULT_MINUTES = 30;
const DEFAULT_FREQ_BINS = 96;
const DEFAULT_BUCKET_SECONDS = 30;

/** Number of frequency tick labels along the bottom axis. */
const FREQ_TICKS = 5;

/** Background colour for a zero-count cell (reads as empty). */
const EMPTY_CELL: readonly [number, number, number] = [13, 17, 23];

function minutesLabel(m: number): string {
  if (m < 60) return `Last ${m} min`;
  return `Last ${m / 60} h`;
}

export function Occupancy(): JSX.Element {
  const [minutes, setMinutes] = useState<number>(DEFAULT_MINUTES);
  const [freqBins, setFreqBins] = useState<number>(DEFAULT_FREQ_BINS);
  const [bucketSeconds, setBucketSeconds] = useState<number>(DEFAULT_BUCKET_SECONDS);
  const [refreshKey, setRefreshKey] = useState(0);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const [data, setData] = useState<OccupancyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // `silent` reloads keep the current heatmap on screen (no loading flicker) so
  // the live poll updates in place.
  const load = useCallback(
    async (silent: boolean): Promise<void> => {
      if (!silent) setLoading(true);
      try {
        const res = await api.getOccupancy(freqBins, minutes, bucketSeconds);
        if (mounted.current) {
          setData(res);
          setError(null);
        }
      } catch (err) {
        if (mounted.current) setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        if (mounted.current && !silent) setLoading(false);
      }
    },
    [freqBins, minutes, bucketSeconds],
  );

  // Full (non-silent) load on mount, control change, or manual refresh.
  useEffect(() => {
    void load(false);
  }, [load, refreshKey]);

  // Live auto-refresh: silently re-poll every 10 s while enabled.
  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => void load(true), 10_000);
    return () => clearInterval(id);
  }, [autoRefresh, load]);

  const maxCount = useMemo(() => {
    if (!data) return 0;
    let max = 0;
    for (const row of data.grid) {
      for (const count of row) {
        if (count > max) max = count;
      }
    }
    return max;
  }, [data]);

  // Draw the heatmap imperatively. Newest time bucket goes at the TOP; the grid
  // is oldest-first, so canvas row y reads grid[rows - 1 - y].
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data) return;
    const rows = data.grid.length;
    const cols = data.freq_bins;
    if (rows === 0 || cols === 0) return;

    canvas.width = cols;
    canvas.height = rows;
    const ctx = canvas.getContext('2d');
    if (!ctx) return; // jsdom / unsupported: nothing to draw.

    const img = ctx.createImageData(cols, rows);
    const buf = img.data;
    for (let y = 0; y < rows; y += 1) {
      const gridRow = data.grid[rows - 1 - y];
      for (let x = 0; x < cols; x += 1) {
        const count = gridRow?.[x] ?? 0;
        const [r, g, b] =
          count > 0 && maxCount > 0 ? turboColor(count / maxCount) : EMPTY_CELL;
        const o = (y * cols + x) * 4;
        buf[o] = r;
        buf[o + 1] = g;
        buf[o + 2] = b;
        buf[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [data, maxCount]);

  const freqTicks = useMemo(() => {
    if (!data) return [];
    const ticks: number[] = [];
    for (let i = 0; i < FREQ_TICKS; i += 1) {
      const frac = i / (FREQ_TICKS - 1);
      ticks.push(data.f_start_hz + frac * (data.f_stop_hz - data.f_start_hz));
    }
    return ticks;
  }, [data]);

  const hasData = data != null && data.grid.length > 0;
  const isEmpty = hasData && maxCount === 0;

  const starts = data?.bucket_starts ?? [];
  const newestIso = starts.length > 0 ? starts[starts.length - 1] : null;
  const oldestIso = starts.length > 0 ? starts[0] : null;

  return (
    <div>
      <div className="page-header">
        <h1>
          Occupancy <InfoTip text={INFO_TEXT} />
        </h1>
        <div className="row">
          <label className="occ-control">
            <span className="small faint">Window</span>
            <select
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
              style={{ width: 'auto' }}
            >
              {MINUTES_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {minutesLabel(m)}
                </option>
              ))}
            </select>
          </label>
          <label className="occ-control">
            <span className="small faint">Freq bins</span>
            <select
              value={freqBins}
              onChange={(e) => setFreqBins(Number(e.target.value))}
              style={{ width: 'auto' }}
            >
              {FREQ_BIN_OPTIONS.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <label className="occ-control">
            <span className="small faint">Bucket</span>
            <select
              value={bucketSeconds}
              onChange={(e) => setBucketSeconds(Number(e.target.value))}
              style={{ width: 'auto' }}
            >
              {BUCKET_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s} s
                </option>
              ))}
            </select>
          </label>
          <label
            className="small faint"
            style={{ display: 'flex', alignItems: 'center', gap: 4 }}
            title="Automatically re-poll every 10 seconds"
          >
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Live
          </label>
          <button onClick={() => setRefreshKey((k) => k + 1)} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <div className="notice danger">{error}</div>}

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Frequency × time heatmap</h2>
          <span className="small faint">
            {hasData ? `peak ${maxCount} detection${maxCount === 1 ? '' : 's'} / cell` : ''}
          </span>
        </div>

        {!hasData ? (
          <div className="empty">{loading ? 'Loading occupancy…' : 'No occupancy data yet.'}</div>
        ) : isEmpty ? (
          <div className="empty">
            No detections in this window yet — start a scan and let it run.
          </div>
        ) : (
          <>
            <div className="occ-plot" style={{ marginTop: 12 }}>
              <div className="occ-yaxis">
                <span className="small faint mono">{formatTimeOnly(newestIso)}</span>
                <span className="small faint">newest</span>
                <span className="small faint">oldest</span>
                <span className="small faint mono">{formatTimeOnly(oldestIso)}</span>
              </div>
              <div className="occ-canvas-wrap">
                <canvas
                  ref={canvasRef}
                  className="occ-canvas"
                  role="img"
                  aria-label="Frequency by time occupancy heatmap"
                />
              </div>
            </div>
            <div className="occ-xaxis">
              {freqTicks.map((hz, i) => (
                <span className="small faint mono" key={i}>
                  {hzToMHz(hz).toFixed(3)}
                </span>
              ))}
            </div>
            <div className="occ-xcaption small faint">Frequency (MHz)</div>
            <div className="hint" style={{ marginTop: 8 }}>
              Brighter = more detections in that time + frequency cell.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
