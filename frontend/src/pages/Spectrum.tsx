import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../store/store';
import { SpectrumChart, type ChannelMarker } from '../components/SpectrumChart';
import { makeFreqAxis } from '../lib/spectrum';
import { Waterfall } from '../components/Waterfall';
import { formatDb, formatTimeOnly, hzToHuman, hzToMHz } from '../lib/format';
import type { SpectrumFrame } from '../lib/types';

export function Spectrum(): JSX.Element {
  const spectrum = useStore((s) => s.spectrum);
  const channels = useStore((s) => s.channels);
  const scanning = useStore((s) => s.scanning);

  const [paused, setPaused] = useState(false);

  // The frame actually shown. When paused we freeze it; otherwise we follow the
  // store's latest frame via requestAnimationFrame so bursts of WS updates
  // coalesce to at most one render per animation frame (stale frames dropped).
  const [displayFrame, setDisplayFrame] = useState<SpectrumFrame | null>(spectrum);
  const latestRef = useRef<SpectrumFrame | null>(spectrum);
  latestRef.current = spectrum;

  useEffect(() => {
    if (paused) return;
    let raf = 0;
    let shown: SpectrumFrame | null = null;
    const tick = (): void => {
      raf = requestAnimationFrame(tick);
      const f = latestRef.current;
      if (f && f !== shown) {
        shown = f;
        setDisplayFrame(f);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [paused]);

  const freqAxis = useMemo(() => {
    if (!displayFrame) return new Float64Array(0);
    return makeFreqAxis(displayFrame.f_start_hz, displayFrame.f_stop_hz, displayFrame.bin_count);
  }, [displayFrame]);

  const markers = useMemo<ChannelMarker[]>(() => {
    if (!displayFrame) return [];
    const lo = displayFrame.f_start_hz;
    const hi = displayFrame.f_stop_hz;
    const out: ChannelMarker[] = [];
    for (const ch of channels.values()) {
      if (ch.center_hz >= lo && ch.center_hz <= hi) {
        out.push({ id: ch.id, centerHz: ch.center_hz, label: `#${ch.id}` });
      }
    }
    return out;
  }, [channels, displayFrame]);

  const scanWindow = useMemo<[number, number] | null>(() => {
    if (!displayFrame) return null;
    // Highlight a narrow window around the current tuner position.
    const span = (displayFrame.f_stop_hz - displayFrame.f_start_hz) / 12;
    return [displayFrame.scan_pos_hz - span / 2, displayFrame.scan_pos_hz + span / 2];
  }, [displayFrame]);

  const powerArr = displayFrame?.power_db ?? [];

  return (
    <div>
      <div className="page-header">
        <h1>Live spectrum</h1>
        <div className="row">
          <span className="badge dim">
            {scanning ? 'Acquisition running' : 'Acquisition idle'}
          </span>
          <button className={paused ? 'primary' : ''} onClick={() => setPaused((p) => !p)}>
            {paused ? 'Resume display' : 'Pause display'}
          </button>
        </div>
      </div>

      {paused && (
        <div className="notice info">
          Display paused. Acquisition and detection continue in the background — only the on-screen
          plot is frozen.
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="chart-toolbar">
          <span className="legend">
            <span>
              <span className="swatch" style={{ background: '#38bdf8' }} />
              Power
            </span>
            <span>
              <span className="swatch" style={{ background: 'rgba(251,191,36,0.9)' }} />
              Noise floor
            </span>
            <span>
              <span className="swatch" style={{ background: '#34d399' }} />
              Candidate channel
            </span>
            <span>
              <span className="swatch" style={{ background: 'rgba(244,114,182,0.6)' }} />
              Scan window
            </span>
          </span>
          <div className="spacer" style={{ flex: 1 }} />
          {displayFrame && (
            <span className="small faint mono">
              {hzToHuman(displayFrame.f_start_hz)} – {hzToHuman(displayFrame.f_stop_hz)} ·{' '}
              {displayFrame.bin_count} bins · noise {formatDb(displayFrame.noise_floor_db)} · pos{' '}
              {hzToMHz(displayFrame.scan_pos_hz).toFixed(3)} MHz · {formatTimeOnly(displayFrame.timestamp)}
            </span>
          )}
        </div>

        {displayFrame ? (
          <SpectrumChart
            freqsHz={freqAxis}
            powerDb={powerArr}
            noiseFloorDb={displayFrame.noise_floor_db}
            markers={markers}
            scanWindowHz={scanWindow}
            height={340}
          />
        ) : (
          <div className="empty">Waiting for spectrum data from the backend…</div>
        )}
        <div className="hint">Drag horizontally to zoom; double-click to reset.</div>
      </div>

      <div className="card">
        <h2>Waterfall</h2>
        <Waterfall powerDb={powerArr} paused={paused} height={240} minDb={-30} maxDb={40} />
        <div className="hint">Newest frames appear at the top and scroll down over time.</div>
      </div>
    </div>
  );
}
