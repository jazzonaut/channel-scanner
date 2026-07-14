import { useEffect, useMemo, useRef } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import { hzToMHz } from '../lib/format';
import { buildSpectrumData } from '../lib/spectrum';

export interface ChannelMarker {
  id: number;
  centerHz: number;
  label: string;
}

export interface SpectrumChartProps {
  /** X axis frequencies in Hz (converted to MHz internally for the axis). */
  freqsHz: Float64Array | number[];
  /** Power in dB, same length as freqsHz. */
  powerDb: Float64Array | number[];
  noiseFloorDb?: number | null;
  /** Detected candidate channel markers. */
  markers?: ChannelMarker[];
  /** Current scan window [startHz, stopHz] to shade. */
  scanWindowHz?: [number, number] | null;
  height?: number;
}

export function SpectrumChart({
  freqsHz,
  powerDb,
  noiseFloorDb,
  markers = [],
  scanWindowHz,
  height = 320,
}: SpectrumChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotRef = useRef<uPlot | null>(null);

  // Keep the most recent inputs in refs so the draw hook reads live values.
  const markersRef = useRef<ChannelMarker[]>(markers);
  const noiseRef = useRef<number | null>(noiseFloorDb ?? null);
  const windowRef = useRef<[number, number] | null>(scanWindowHz ?? null);
  markersRef.current = markers;
  noiseRef.current = noiseFloorDb ?? null;
  windowRef.current = scanWindowHz ?? null;

  const data = useMemo(() => buildSpectrumData(freqsHz, powerDb), [freqsHz, powerDb]);

  // Create the plot once.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const opts: uPlot.Options = {
      width: el.clientWidth || 640,
      height,
      class: 'uplot',
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: false } },
      legend: { show: true },
      series: [
        { label: 'Freq (MHz)', value: (_u, v) => (v == null ? '—' : `${v.toFixed(4)} MHz`) },
        {
          label: 'Power (dB)',
          stroke: '#38bdf8',
          width: 1,
          fill: 'rgba(56,189,248,0.10)',
          value: (_u, v) => (v == null ? '—' : `${v.toFixed(1)} dB`),
        },
      ],
      axes: [
        {
          stroke: '#9fb0c8',
          grid: { stroke: 'rgba(255,255,255,0.06)' },
          ticks: { stroke: 'rgba(255,255,255,0.12)' },
          values: (_u, splits) => splits.map((s) => `${s.toFixed(3)}`),
        },
        {
          stroke: '#9fb0c8',
          grid: { stroke: 'rgba(255,255,255,0.06)' },
          ticks: { stroke: 'rgba(255,255,255,0.12)' },
        },
      ],
      hooks: {
        draw: [
          (u) => {
            drawOverlays(u, markersRef.current, noiseRef.current, windowRef.current);
          },
        ],
      },
    };

    const plot = new uPlot(opts, data, el);
    plotRef.current = plot;

    const ro = new ResizeObserver(() => {
      if (el.clientWidth > 0) plot.setSize({ width: el.clientWidth, height });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      plot.destroy();
      plotRef.current = null;
    };
    // Intentionally create the plot only once; data updates go through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  // Feed new data to the existing plot.
  useEffect(() => {
    plotRef.current?.setData(data);
  }, [data]);

  return <div ref={containerRef} style={{ width: '100%' }} />;
}

function drawOverlays(
  u: uPlot,
  markers: ChannelMarker[],
  noiseFloorDb: number | null,
  windowHz: [number, number] | null,
): void {
  const { ctx } = u;
  const { left, top, width, height } = u.bbox;
  ctx.save();

  // Shade the active scan window.
  if (windowHz) {
    const x0 = u.valToPos(hzToMHz(windowHz[0]), 'x', true);
    const x1 = u.valToPos(hzToMHz(windowHz[1]), 'x', true);
    ctx.fillStyle = 'rgba(244,114,182,0.10)';
    ctx.fillRect(Math.min(x0, x1), top, Math.abs(x1 - x0), height);
  }

  // Noise-floor reference line.
  if (noiseFloorDb != null && Number.isFinite(noiseFloorDb)) {
    const y = u.valToPos(noiseFloorDb, 'y', true);
    if (y >= top && y <= top + height) {
      ctx.strokeStyle = 'rgba(251,191,36,0.7)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(left + width, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // Candidate channel markers (vertical lines + labels).
  ctx.font = '10px ui-monospace, monospace';
  for (const m of markers) {
    const x = u.valToPos(hzToMHz(m.centerHz), 'x', true);
    if (x < left || x > left + width) continue;
    ctx.strokeStyle = 'rgba(52,211,153,0.75)';
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + height);
    ctx.stroke();
    ctx.fillStyle = '#34d399';
    ctx.fillText(m.label, x + 3, top + 12);
  }

  ctx.restore();
}
