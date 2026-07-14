import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/store';
import { api, ApiError } from '../lib/api';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Modal } from '../components/Modal';
import type { Recording } from '../lib/types';
import {
  formatBytes,
  formatDuration,
  formatIso,
  formatSampleRate,
  hzToHuman,
  hzToMHz,
} from '../lib/format';

interface Filters {
  fromIso: string;
  toIso: string;
  freqLoMhz: string;
  freqHiMhz: string;
  channelId: string;
}

const EMPTY_FILTERS: Filters = {
  fromIso: '',
  toIso: '',
  freqLoMhz: '',
  freqHiMhz: '',
  channelId: '',
};

export function Recordings(): JSX.Element {
  const config = useStore((s) => s.config);
  const isOperator = useStore((s) => s.isOperator());
  const channels = useStore((s) => s.channels);

  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [toDelete, setToDelete] = useState<Recording | null>(null);
  const [inspect, setInspect] = useState<Recording | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);

  const iqEnabled = false; // IQ recording is OFF by default per contract (ENABLE_IQ_RECORDING=false).

  async function reload(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getRecordings();
      setRecordings(res.recordings);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  const filtered = useMemo(() => {
    const fromT = filters.fromIso ? new Date(filters.fromIso).getTime() : null;
    const toT = filters.toIso ? new Date(filters.toIso).getTime() : null;
    const lo = filters.freqLoMhz ? Number(filters.freqLoMhz) * 1e6 : null;
    const hi = filters.freqHiMhz ? Number(filters.freqHiMhz) * 1e6 : null;
    const chId = filters.channelId ? Number(filters.channelId) : null;
    const chCenter = chId != null ? channels.get(chId)?.center_hz ?? null : null;

    return recordings.filter((r) => {
      const t = new Date(r.timestamp).getTime();
      if (fromT != null && t < fromT) return false;
      if (toT != null && t > toT) return false;
      if (lo != null && r.center_hz < lo) return false;
      if (hi != null && r.center_hz > hi) return false;
      if (chCenter != null) {
        // Keep recordings whose center is near the selected channel (±sample_rate/2).
        const half = r.sample_rate / 2;
        if (Math.abs(r.center_hz - chCenter) > half) return false;
      }
      return true;
    });
  }, [recordings, filters, channels]);

  async function startRecording(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const body = config ? { center_hz: Math.round((config.start_hz + config.end_hz) / 2) } : {};
      await api.startRecording(body);
      setRecording(true);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function stopRecording(): Promise<void> {
    setBusy(true);
    try {
      await api.stopRecording();
      setRecording(false);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete(): Promise<void> {
    if (!toDelete) return;
    const id = toDelete.id;
    setToDelete(null);
    try {
      await api.deleteRecording(id);
      setRecordings((rs) => rs.filter((r) => r.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  function setFilter<K extends keyof Filters>(key: K, value: string): void {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <div>
      <div className="page-header">
        <h1>Recordings</h1>
        <div className="row">
          <a className="badge dim" href={api.exportUrl('csv', 'detections')} download>
            Export detections CSV
          </a>
          <a className="badge dim" href={api.exportUrl('json', 'detections')} download>
            Export detections JSON
          </a>
          {recording ? (
            <button className="danger" onClick={() => void stopRecording()} disabled={busy}>
              Stop recording
            </button>
          ) : (
            <button
              className="primary"
              onClick={() => void startRecording()}
              disabled={busy || !isOperator}
              title={!isOperator ? 'Requires control lease' : 'Start an IQ recording'}
            >
              Start IQ recording
            </button>
          )}
        </div>
      </div>

      {!iqEnabled && (
        <div className="notice info">
          IQ recording is disabled by default (ENABLE_IQ_RECORDING=false). Existing recordings are
          still listed and can be inspected, downloaded, or deleted. Starting a recording requires
          the backend to have IQ capture enabled.
        </div>
      )}
      {error && <div className="notice danger">{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Search &amp; filter</h2>
        <div className="form-grid">
          <div className="field">
            <label>From</label>
            <input type="datetime-local" value={filters.fromIso} onChange={(e) => setFilter('fromIso', e.target.value)} />
          </div>
          <div className="field">
            <label>To</label>
            <input type="datetime-local" value={filters.toIso} onChange={(e) => setFilter('toIso', e.target.value)} />
          </div>
          <div className="field">
            <label>Freq low (MHz)</label>
            <input value={filters.freqLoMhz} onChange={(e) => setFilter('freqLoMhz', e.target.value)} inputMode="decimal" />
          </div>
          <div className="field">
            <label>Freq high (MHz)</label>
            <input value={filters.freqHiMhz} onChange={(e) => setFilter('freqHiMhz', e.target.value)} inputMode="decimal" />
          </div>
          <div className="field">
            <label>Channel</label>
            <select value={filters.channelId} onChange={(e) => setFilter('channelId', e.target.value)}>
              <option value="">Any channel</option>
              {Array.from(channels.values()).map((ch) => (
                <option key={ch.id} value={ch.id}>
                  #{ch.id} · {hzToMHz(ch.center_hz).toFixed(4)} MHz
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</button>
          <button onClick={() => void reload()} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Stored recordings</h2>
          <span className="small faint">
            {filtered.length} of {recordings.length}
          </span>
        </div>
        {filtered.length === 0 ? (
          <div className="empty">No recordings match.</div>
        ) : (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th className="num">ID</th>
                  <th>Time</th>
                  <th className="num">Center</th>
                  <th className="num">Sample rate</th>
                  <th>Gain</th>
                  <th className="num">Duration</th>
                  <th>Format</th>
                  <th className="num">Size</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id}>
                    <td className="num mono">{r.id}</td>
                    <td title={formatIso(r.timestamp)}>{formatIso(r.timestamp)}</td>
                    <td className="num mono">{hzToHuman(r.center_hz)}</td>
                    <td className="num">{formatSampleRate(r.sample_rate)}</td>
                    <td>{r.gain}</td>
                    <td className="num">{formatDuration(r.duration_ms)}</td>
                    <td>{r.format}</td>
                    <td className="num">{formatBytes(r.bytes)}</td>
                    <td>
                      <div className="row" style={{ flexWrap: 'nowrap' }}>
                        <button onClick={() => setInspect(r)}>Inspect</button>
                        <button className="danger" onClick={() => setToDelete(r)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {toDelete && (
        <ConfirmDialog
          title="Delete recording"
          danger
          confirmLabel="Delete"
          message={
            <span>
              Permanently delete recording #{toDelete.id} ({formatBytes(toDelete.bytes)}) captured{' '}
              {formatIso(toDelete.timestamp)}? This cannot be undone.
            </span>
          }
          onConfirm={() => void confirmDelete()}
          onCancel={() => setToDelete(null)}
        />
      )}

      {inspect && (
        <Modal title={`Recording #${inspect.id} metadata`} onClose={() => setInspect(null)}>
          <dl className="form-grid" style={{ margin: 0 }}>
            <MetaRow label="Path" value={<span className="mono">{inspect.path}</span>} />
            <MetaRow label="Timestamp" value={formatIso(inspect.timestamp)} />
            <MetaRow label="Center" value={hzToHuman(inspect.center_hz)} />
            <MetaRow label="Sample rate" value={formatSampleRate(inspect.sample_rate)} />
            <MetaRow label="Gain" value={inspect.gain} />
            <MetaRow label="Duration" value={formatDuration(inspect.duration_ms)} />
            <MetaRow label="Format" value={inspect.format} />
            <MetaRow label="Size" value={formatBytes(inspect.bytes)} />
          </dl>
          <h3 style={{ marginTop: 16 }}>SigMF metadata</h3>
          <pre
            className="mono small"
            style={{
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 12,
              overflow: 'auto',
              maxHeight: 240,
            }}
          >
            {inspect.sigmf_meta ? JSON.stringify(inspect.sigmf_meta, null, 2) : 'No SigMF metadata.'}
          </pre>
        </Modal>
      )}
    </div>
  );
}

function MetaRow({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
  return (
    <div className="field" style={{ margin: 0 }}>
      <label>{label}</label>
      <div>{value}</div>
    </div>
  );
}
