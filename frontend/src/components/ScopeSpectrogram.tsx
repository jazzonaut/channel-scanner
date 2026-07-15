import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store/store';
import { dbToColor } from '../lib/colormap';
import { hzToMHz } from '../lib/format';
import type { ScopeFrame } from '../lib/types';

export interface ScopeSpectrogramProps {
  /** Number of time columns kept in the scrolling history. */
  rows?: number;
  /** Canvas CSS height in px. */
  height?: number;
  /** dB span above the noise floor mapped across the colormap. */
  spanDb?: number;
}

interface HoverReadout {
  yFrac: number;
  freqHz: number;
  db: number | null;
}

/**
 * High-resolution scrolling spectrogram for the parked focus window.
 *
 * Time flows LEFT -> RIGHT (newest column on the right, scrolling left), with
 * frequency on the vertical axis (higher frequency at the top). This matches
 * the amplitude-vs-time strip below it so the two read as one scope trace.
 *
 * Hot path: this component NEVER re-renders React per frame. It reads the latest
 * scope frame directly from the store inside a requestAnimationFrame loop and
 * draws imperatively to the canvas, coalescing bursts to at most one column per
 * animation frame (stale frames are dropped). Only the (user-driven) hover
 * readout uses React state.
 */
export function ScopeSpectrogram({
  rows = 512,
  height = 320,
  spanDb = 60,
}: ScopeSpectrogramProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const latestFrameRef = useRef<ScopeFrame | null>(null);
  const [hover, setHover] = useState<HoverReadout | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { willReadFrequently: false });
    if (!ctx) return;

    // Width = time history (columns); height = frequency bins (set per frame).
    canvas.width = rows;

    let raf = 0;
    let drawnSeq: number | null = null;

    const render = (): void => {
      raf = requestAnimationFrame(render);
      const frame = useStore.getState().scope;
      latestFrameRef.current = frame;
      if (!frame || frame.seq === drawnSeq || frame.power_db.length === 0) return;
      drawnSeq = frame.seq;

      const bins = frame.power_db.length;
      if (canvas.height !== bins) canvas.height = bins;
      const w = canvas.width;
      const h = canvas.height;

      // Scroll existing content left by one column.
      ctx.drawImage(canvas, 1, 0, w - 1, h, 0, 0, w - 1, h);

      // Autoscale color range from the reported noise floor.
      const minDb = frame.noise_floor_db;
      const maxDb = frame.noise_floor_db + spanDb;

      // Draw the newest column at the right edge; frequency increases upward,
      // so bin i (low->high freq) maps to y = h-1-i (bottom->top).
      const col = ctx.createImageData(1, h);
      const data = col.data;
      const power = frame.power_db;
      for (let i = 0; i < bins; i += 1) {
        const [r, g, b] = dbToColor(power[i] ?? minDb, minDb, maxDb);
        const o = (h - 1 - i) * 4;
        data[o] = r;
        data[o + 1] = g;
        data[o + 2] = b;
        data[o + 3] = 255;
      }
      ctx.putImageData(col, w - 1, 0);
    };

    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [rows, spanDb]);

  function onMove(ev: React.MouseEvent<HTMLCanvasElement>): void {
    const frame = latestFrameRef.current;
    const canvas = canvasRef.current;
    if (!frame || !canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.height === 0) return;
    const yFrac = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height));
    // Top = f_stop (high), bottom = f_start (low).
    const freqHz = frame.f_stop_hz - yFrac * (frame.f_stop_hz - frame.f_start_hz);
    const bins = frame.power_db.length;
    const bin = Math.min(bins - 1, Math.max(0, Math.floor((1 - yFrac) * bins)));
    const db = frame.power_db[bin] ?? null;
    setHover({ yFrac, freqHz, db });
  }

  return (
    <div className="scope-spectrogram" style={{ height }} onMouseLeave={() => setHover(null)}>
      <canvas
        ref={canvasRef}
        width={rows}
        style={{ height, width: '100%' }}
        aria-label="Focus scope spectrogram"
        onMouseMove={onMove}
      />
      {hover && (
        <div className="scope-hover" style={{ top: `${(hover.yFrac * 100).toFixed(2)}%` }}>
          <span className="mono">{hzToMHz(hover.freqHz).toFixed(4)} MHz</span>
          <span className="mono faint">
            {hover.db == null ? '—' : `${hover.db.toFixed(1)} dB`}
          </span>
        </div>
      )}
    </div>
  );
}
