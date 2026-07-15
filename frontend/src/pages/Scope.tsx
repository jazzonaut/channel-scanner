import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useStore } from '../store/store';
import { api, ApiError } from '../lib/api';
import { ScopeSpectrogram } from '../components/ScopeSpectrogram';
import { AmplitudeStrip } from '../components/AmplitudeStrip';
import { formatDb, formatSampleRate, hzToMHz, mhzToHz } from '../lib/format';

const DEFAULT_CENTER_HZ = 433_920_000; // mid ISM 433 band fallback.

function bandMidpointHz(startHz?: number, endHz?: number): number {
  if (startHz != null && endHz != null && endHz > startHz) {
    return Math.round((startHz + endHz) / 2);
  }
  return DEFAULT_CENTER_HZ;
}

export function Scope(): JSX.Element {
  const mode = useStore((s) => s.mode);
  const focusCenterHz = useStore((s) => s.focusCenterHz);
  const config = useStore((s) => s.config);
  // Low-frequency selector: this string only changes when the focus window
  // changes, so the page does NOT re-render on every ~20/s scope frame.
  const windowKey = useStore((s) =>
    s.scope ? `${s.scope.f_start_hz}|${s.scope.f_stop_hz}|${s.scope.bin_count}` : null,
  );

  const [searchParams] = useSearchParams();
  const [centerMhz, setCenterMhz] = useState<string>('');
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<boolean>(false);
  const didAutoFocus = useRef(false);

  // Prefill the input from the current focus, band midpoint, or default.
  useEffect(() => {
    if (centerMhz !== '') return;
    const hz = focusCenterHz ?? bandMidpointHz(config?.start_hz, config?.end_hz);
    setCenterMhz(hzToMHz(hz).toFixed(4));
    // Only seed once when empty; user edits take precedence afterwards.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusCenterHz, config]);

  const startFocus = useCallback(async (centerHz: number): Promise<void> => {
    setActionErr(false);
    setActionMsg(null);
    try {
      await api.focus(centerHz);
      // Optimistically flip to focus mode so the UI reacts immediately; the
      // periodic server status tick then confirms/corrects it.
      useStore.getState().setMode('focus', centerHz);
      setActionMsg(`Focusing on ${hzToMHz(centerHz).toFixed(4)} MHz…`);
    } catch (err) {
      setActionErr(true);
      setActionMsg(err instanceof ApiError ? err.message : String(err));
    }
  }, []);

  // Auto-focus when navigated from the Channels page with ?center=<hz>.
  useEffect(() => {
    if (didAutoFocus.current) return;
    const raw = searchParams.get('center');
    if (raw == null) return;
    const hz = Number(raw);
    if (!Number.isFinite(hz) || hz <= 0) return;
    didAutoFocus.current = true;
    setCenterMhz(hzToMHz(hz).toFixed(4));
    void startFocus(Math.round(hz));
  }, [searchParams, startFocus]);

  function onStartClick(): void {
    const mhz = Number(centerMhz);
    if (!Number.isFinite(mhz) || mhz <= 0) {
      setActionErr(true);
      setActionMsg('Enter a valid center frequency in MHz.');
      return;
    }
    void startFocus(mhzToHz(mhz));
  }

  async function onBackToSweep(): Promise<void> {
    setActionErr(false);
    setActionMsg(null);
    try {
      await api.resumeSweep();
      useStore.getState().setMode('sweep', null); // optimistic; status confirms
      setActionMsg('Resumed normal sweeping.');
    } catch (err) {
      setActionErr(true);
      setActionMsg(err instanceof ApiError ? err.message : String(err));
    }
  }

  const inFocus = mode === 'focus';

  // Read exact window edges for axis labels only when the window changes
  // (windowKey drives the re-render; the actual numbers come from the store).
  const axis = useMemo(() => {
    if (windowKey == null) return null;
    const frame = useStore.getState().scope;
    if (!frame) return null;
    const ticks: number[] = [];
    for (let i = 0; i <= 4; i += 1) {
      ticks.push(frame.f_start_hz + ((frame.f_stop_hz - frame.f_start_hz) * i) / 4);
    }
    return {
      startHz: frame.f_start_hz,
      stopHz: frame.f_stop_hz,
      binCount: frame.bin_count,
      sampleRate: frame.sample_rate,
      noiseFloorDb: frame.noise_floor_db,
      envDtUs: frame.env_dt_us,
      envLen: frame.envelope.length,
      ticks,
    };
  }, [windowKey]);

  const dwellMs = axis != null ? (axis.envLen * axis.envDtUs) / 1000 : null;

  return (
    <div>
      <div className="page-header">
        <h1>Signal scope</h1>
        <div className="row">
          <span className={`badge ${inFocus ? 'ok' : 'dim'}`}>
            {inFocus ? 'Focus mode' : 'Sweep mode'}
          </span>
          {focusCenterHz != null && (
            <span className="badge dim mono">{hzToMHz(focusCenterHz).toFixed(4)} MHz</span>
          )}
        </div>
      </div>

      <div className="notice info">
        Receive-only. The scope visualizes received IQ from a single parked window; it never
        transmits, and any payloads are treated as opaque and are not decoded.
      </div>

      <div className="card scope-controls">
        <div className="field" style={{ marginBottom: 0 }}>
          <label htmlFor="scope-center">Focus center (MHz)</label>
          <input
            id="scope-center"
            className="mono"
            inputMode="decimal"
            value={centerMhz}
            onChange={(e) => setCenterMhz(e.target.value)}
            placeholder="433.9200"
            style={{ width: 160 }}
          />
        </div>
        <div className="row">
          <button className="primary" onClick={onStartClick}>
            {inFocus ? 'Re-tune scope' : 'Start scope (focus)'}
          </button>
          {inFocus && (
            <button className="danger" onClick={() => void onBackToSweep()}>
              Stop scope
            </button>
          )}
        </div>
      </div>

      {actionMsg && <div className={`notice ${actionErr ? 'danger' : 'info'}`}>{actionMsg}</div>}

      <div className="card">
        <div className="chart-toolbar">
          <h2 style={{ margin: 0 }}>Spectrogram</h2>
          <div className="spacer" style={{ flex: 1 }} />
          {inFocus && axis && (
            <span className="small faint mono">
              {hzToMHz(axis.startHz).toFixed(3)} – {hzToMHz(axis.stopHz).toFixed(3)} MHz ·{' '}
              {axis.binCount} bins · {formatSampleRate(axis.sampleRate)} · noise{' '}
              {formatDb(axis.noiseFloorDb)}
            </span>
          )}
        </div>

        {inFocus ? (
          <>
            <div className="scope-view" style={{ height: 360 }}>
              {axis && (
                <div className="scope-yaxis mono">
                  {[...axis.ticks].reverse().map((hz, i) => (
                    <span key={i}>{hzToMHz(hz).toFixed(3)}</span>
                  ))}
                </div>
              )}
              <div className="scope-canvas-col">
                <ScopeSpectrogram key={windowKey ?? 'pending'} height={360} rows={512} spanDb={60} />
              </div>
            </div>
            {axis ? (
              <div className="scope-time-axis small faint mono">
                <span>← older</span>
                <span>time</span>
                <span>newest →</span>
              </div>
            ) : (
              <div className="hint">Waiting for the first scope frame…</div>
            )}
            <div className="hint">
              Time flows left → right (newest on the right); frequency (MHz) is on the vertical axis,
              high at the top. Hover for a frequency and level readout.
            </div>
          </>
        ) : (
          <div className="empty">
            Focus a frequency to start the scope. Enter a center above and press{' '}
            <strong>Start scope (focus)</strong>, or use the Focus action on the Channels page.
          </div>
        )}
      </div>

      {inFocus && (
        <div className="card">
          <div className="chart-toolbar">
            <h2 style={{ margin: 0 }}>Amplitude vs time</h2>
            <div className="spacer" style={{ flex: 1 }} />
            {dwellMs != null && (
              <span className="small faint mono">dwell ≈ {dwellMs.toFixed(2)} ms</span>
            )}
          </div>
          <AmplitudeStrip height={140} />
          <div className="hint">
            Envelope (|IQ| in dB) of the latest dwell. Time spans 0 – {dwellMs?.toFixed(2) ?? '—'} ms
            left to right.
          </div>
        </div>
      )}
    </div>
  );
}
