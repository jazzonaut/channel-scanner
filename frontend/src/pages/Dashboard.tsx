import { useState } from 'react';
import { useStore } from '../store/store';
import { MetricTile } from '../components/MetricTile';
import { GenericBadge } from '../components/StatusBadge';
import { api, ApiError } from '../lib/api';
import {
  formatBytes,
  formatDb,
  formatSampleRate,
  hzToHuman,
  hzSpanToHuman,
  formatPercent,
} from '../lib/format';

export function Dashboard(): JSX.Element {
  const device = useStore((s) => s.device);
  const metrics = useStore((s) => s.metrics);
  const config = useStore((s) => s.config);
  const scanning = useStore((s) => s.scanning);
  const spectrum = useStore((s) => s.spectrum);
  const connection = useStore((s) => s.connection);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleScan(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      if (scanning) {
        await api.stopScan();
        useStore.getState().setScanning(false); // optimistic; WS status confirms
      } else {
        await api.startScan();
        useStore.getState().setScanning(true);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const sdrAvailable = device?.available ?? false;
  const scanPos = spectrum?.scan_pos_hz ?? null;

  return (
    <div>
      <div className="page-header">
        <h1>Dashboard</h1>
        <div className="row">
          <GenericBadge tone={scanning ? 'ok' : 'dim'}>
            {scanning ? 'Scanning' : 'Idle'}
          </GenericBadge>
          <button className="primary" onClick={toggleScan} disabled={busy}>
            {scanning ? 'Stop scan' : 'Start scan'}
          </button>
        </div>
      </div>

      {error && <div className="notice danger">{error}</div>}

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <div className="col" style={{ gap: 2 }}>
            <h2 style={{ margin: 0 }}>SDR device</h2>
            <span className="muted">
              {device ? device.name : 'Unknown device'}
              {device?.tuner ? ` · tuner ${device.tuner}` : ''}
            </span>
          </div>
          <div className="row">
            {device?.simulation && <GenericBadge tone="warn">Simulation</GenericBadge>}
            <GenericBadge tone={sdrAvailable ? 'ok' : 'danger'}>
              {sdrAvailable ? 'Connected' : 'Not available'}
            </GenericBadge>
            <GenericBadge tone={connection === 'open' ? 'ok' : 'warn'}>
              App {connection === 'open' ? 'healthy' : connection}
            </GenericBadge>
          </div>
        </div>
      </section>

      <div className="grid tiles">
        <MetricTile
          label="Configured range"
          value={
            config ? (
              <span className="mono" style={{ fontSize: '1rem' }}>
                {hzToHuman(config.start_hz)} – {hzToHuman(config.end_hz)}
              </span>
            ) : (
              '—'
            )
          }
          sub={config ? `span ${hzSpanToHuman(config.end_hz - config.start_hz)}` : undefined}
        />
        <MetricTile
          label="Current scan position"
          value={scanPos != null ? hzToHuman(scanPos) : '—'}
          sub={
            metrics != null ? `progress ${formatPercent(metrics.scan_progress)}` : 'awaiting frames'
          }
        />
        <MetricTile
          label="Sample rate"
          value={config ? formatSampleRate(config.sample_rate) : '—'}
          sub={config ? `FFT ${config.fft_size}` : undefined}
        />
        <MetricTile label="Gain" value={config ? config.gain : '—'} sub={`ppm ${config?.ppm ?? 0}`} />
        <MetricTile
          label="Noise floor"
          value={formatDb(spectrum?.noise_floor_db)}
          sub={config ? `threshold ${formatDb(config.threshold_db)}` : undefined}
        />
        <MetricTile
          label="Dropped frames"
          value={metrics ? metrics.dropped_frames.toLocaleString() : '—'}
          tone={metrics && metrics.dropped_frames > 0 ? 'warn' : 'default'}
          sub={metrics ? `queue ${metrics.queue_depth}` : undefined}
        />
        <MetricTile
          label="FFT rate"
          value={metrics ? `${metrics.fft_rate_hz.toFixed(1)} Hz` : '—'}
          sub={metrics ? `${metrics.ws_clients} ws clients` : undefined}
        />
        <MetricTile
          label="Database size"
          value={formatBytes(metrics?.db_size_bytes)}
          sub="detections + events"
        />
        <MetricTile
          label="Recording storage"
          value={formatBytes(metrics?.recording_bytes)}
          sub="IQ recordings"
        />
      </div>
    </div>
  );
}
