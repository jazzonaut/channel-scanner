import { useEffect, useRef } from 'react';

export interface WaterfallProps {
  /** Latest row of power values (dB). Each new frame scrolls the image down. */
  powerDb: Float64Array | number[] | null;
  /** dB value mapped to the bottom of the colormap. */
  minDb?: number;
  /** dB value mapped to the top of the colormap. */
  maxDb?: number;
  height?: number;
  paused?: boolean;
}

/** Map a normalized 0..1 value to an [r,g,b] "inferno"-ish colormap. */
function colormap(t: number): [number, number, number] {
  const x = t < 0 ? 0 : t > 1 ? 1 : t;
  // Piecewise ramp: black -> purple -> red -> orange -> yellow.
  const r = Math.round(255 * Math.min(1, x * 1.6));
  const g = Math.round(255 * Math.max(0, Math.min(1, (x - 0.35) * 1.7)));
  const b = Math.round(255 * Math.max(0, Math.min(1, (x < 0.4 ? x * 2 : (1 - x) * 1.2))));
  return [r, g, b];
}

/**
 * Scrolling spectrogram rendered on a canvas. New frames are drawn on the top
 * row and the previous content is shifted down by 1px via drawImage(self).
 */
export function Waterfall({
  powerDb,
  minDb = -30,
  maxDb = 40,
  height = 220,
  paused = false,
}: WaterfallProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const lastFrameRef = useRef<Float64Array | number[] | null>(null);

  // Track the latest frame; the RAF loop consumes it.
  if (!paused) lastFrameRef.current = powerDb;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { willReadFrequently: false });
    if (!ctx) return;

    let raf = 0;
    let drawnFrame: Float64Array | number[] | null = null;

    const render = (): void => {
      raf = requestAnimationFrame(render);
      const frame = lastFrameRef.current;
      if (paused || !frame || frame === drawnFrame || frame.length === 0) return;
      drawnFrame = frame;

      const w = frame.length;
      if (canvas.width !== w) canvas.width = w;
      const h = canvas.height;

      // Scroll everything down by one row.
      ctx.drawImage(canvas, 0, 0, w, h - 1, 0, 1, w, h - 1);

      // Draw the new top row.
      const row = ctx.createImageData(w, 1);
      const range = maxDb - minDb || 1;
      for (let i = 0; i < w; i += 1) {
        const v = frame[i] as number;
        const t = (v - minDb) / range;
        const [r, g, b] = colormap(t);
        const o = i * 4;
        row.data[o] = r;
        row.data[o + 1] = g;
        row.data[o + 2] = b;
        row.data[o + 3] = 255;
      }
      ctx.putImageData(row, 0, 0);
    };

    raf = requestAnimationFrame(render);
    return () => cancelAnimationFrame(raf);
  }, [paused, minDb, maxDb]);

  return (
    <div className="waterfall-wrap" style={{ height }}>
      <canvas ref={canvasRef} height={height} style={{ height }} aria-label="Spectrogram waterfall" />
    </div>
  );
}
