import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore } from '../store/store';
import { StatusBadge } from '../components/StatusBadge';
import { Modal } from '../components/Modal';
import { api, ApiError } from '../lib/api';
import type { CandidateChannel, Detection } from '../lib/types';
import {
  formatConfidence,
  formatDb,
  formatDuration,
  formatIntervalSeconds,
  formatIso,
  formatRelative,
  formatSnr,
  hzSpanToHuman,
  hzToMHz,
} from '../lib/format';

type SortKey =
  | 'id'
  | 'center_hz'
  | 'bandwidth_hz'
  | 'current_power_db'
  | 'peak_power_db'
  | 'avg_power_db'
  | 'snr_db'
  | 'observation_count'
  | 'first_seen'
  | 'last_seen'
  | 'typical_burst_ms'
  | 'recurrence_interval_s'
  | 'confidence'
  | 'status';

export function Channels(): JSX.Element {
  const channelMap = useStore((s) => s.channels);
  const isOperator = useStore((s) => s.isOperator());
  const navigate = useNavigate();

  const [sortKey, setSortKey] = useState<SortKey>('center_hz');
  const [asc, setAsc] = useState(true);
  const [obsFor, setObsFor] = useState<CandidateChannel | null>(null);

  const channels = useMemo(() => {
    const arr = Array.from(channelMap.values());
    arr.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      // Null/undefined (e.g. burst duration, recurrence not yet known) sort last.
      if (av == null && bv == null) cmp = 0;
      else if (av == null) cmp = -1;
      else if (bv == null) cmp = 1;
      else if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    });
    return arr;
  }, [channelMap, sortKey, asc]);

  // Normalize avg power to 0..1 across the current channels so similar values
  // read as similar-length bars — a block of similar channels stands out,
  // especially when the table is sorted by Avg.
  const avgRange = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const c of channels) {
      if (c.avg_power_db < min) min = c.avg_power_db;
      if (c.avg_power_db > max) max = c.avg_power_db;
    }
    return { min, max, span: max - min };
  }, [channels]);

  function avgNorm(db: number): number {
    if (!Number.isFinite(avgRange.span) || avgRange.span <= 0) return 0.5;
    return Math.min(1, Math.max(0, (db - avgRange.min) / avgRange.span));
  }

  function toggleSort(key: SortKey): void {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  }

  function focus(ch: CandidateChannel): void {
    // Open the Scope page parked on this channel's center; Scope auto-focuses
    // via the ?center query param on mount.
    navigate(`/scope?center=${ch.center_hz}`);
  }

  const sortArrow = (key: SortKey): string => (key === sortKey ? (asc ? ' ▲' : ' ▼') : '');

  return (
    <div>
      <div className="page-header">
        <h1>Candidate channels</h1>
        <div className="row">
          <NoiseFloorIndicator />
          <a className="badge dim" href={api.exportUrl('csv', 'channels')} download>
            Export CSV
          </a>
          <a className="badge dim" href={api.exportUrl('json', 'channels')} download>
            Export JSON
          </a>
        </div>
      </div>

      {!isOperator && (
        <div className="notice warn">
          You are not the control operator. Focus will be applied by the backend but may be
          overridden by the operator&apos;s scan configuration.
        </div>
      )}

      {channels.length === 0 ? (
        <div className="card empty">No candidate channels detected yet.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="num sortable" onClick={() => toggleSort('id')}>
                  ID{sortArrow('id')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('center_hz')}>
                  Center (MHz){sortArrow('center_hz')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('bandwidth_hz')}>
                  Bandwidth{sortArrow('bandwidth_hz')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('current_power_db')}>
                  Current{sortArrow('current_power_db')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('peak_power_db')}>
                  Peak{sortArrow('peak_power_db')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('avg_power_db')}>
                  Avg{sortArrow('avg_power_db')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('snr_db')}>
                  SNR{sortArrow('snr_db')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('observation_count')}>
                  Obs{sortArrow('observation_count')}
                </th>
                <th className="sortable" onClick={() => toggleSort('first_seen')}>
                  First seen{sortArrow('first_seen')}
                </th>
                <th className="sortable" onClick={() => toggleSort('last_seen')}>
                  Last seen{sortArrow('last_seen')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('typical_burst_ms')}>
                  Burst{sortArrow('typical_burst_ms')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('recurrence_interval_s')}>
                  Recurrence{sortArrow('recurrence_interval_s')}
                </th>
                <th className="num sortable" onClick={() => toggleSort('confidence')}>
                  Conf.{sortArrow('confidence')}
                </th>
                <th className="sortable" onClick={() => toggleSort('status')}>
                  Status{sortArrow('status')}
                </th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch) => (
                <tr key={ch.id}>
                  <td className="num mono">{ch.id}</td>
                  <td className="num mono">{hzToMHz(ch.center_hz).toFixed(4)}</td>
                  <td className="num">{hzSpanToHuman(ch.bandwidth_hz)}</td>
                  <td className="num">{formatDb(ch.current_power_db)}</td>
                  <td className="num">{formatDb(ch.peak_power_db)}</td>
                  <td className="num">
                    <div
                      className="heatcell"
                      title={`Normalized avg power: ${avgNorm(ch.avg_power_db).toFixed(2)} (0 = lowest, 1 = highest of listed channels)`}
                    >
                      <div
                        className="heatcell-bar"
                        style={{ width: `${(avgNorm(ch.avg_power_db) * 100).toFixed(0)}%` }}
                      />
                      <span className="heatcell-val">
                        {formatDb(ch.avg_power_db)}{' '}
                        <span className="faint">{avgNorm(ch.avg_power_db).toFixed(2)}</span>
                      </span>
                    </div>
                  </td>
                  <td className="num">{formatSnr(ch.snr_db)}</td>
                  <td className="num">{ch.observation_count}</td>
                  <td title={formatIso(ch.first_seen)}>{formatRelative(ch.first_seen)}</td>
                  <td title={formatIso(ch.last_seen)}>{formatRelative(ch.last_seen)}</td>
                  <td className="num">{formatDuration(ch.typical_burst_ms)}</td>
                  <td className="num">{formatIntervalSeconds(ch.recurrence_interval_s)}</td>
                  <td className="num">{formatConfidence(ch.confidence)}</td>
                  <td>
                    <StatusBadge status={ch.status} />
                  </td>
                  <td>
                    <div className="row" style={{ flexWrap: 'nowrap' }}>
                      <button onClick={() => focus(ch)}>Focus</button>
                      <button onClick={() => setObsFor(ch)}>History</button>
                      <a
                        className="badge dim"
                        href={api.exportUrl('csv', 'detections')}
                        download
                        title="Export related detections"
                      >
                        Export
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {obsFor && <ObservationsModal channel={obsFor} onClose={() => setObsFor(null)} />}
    </div>
  );
}

/** Live noise floor from the latest spectrum frame. Isolated in its own
 *  component so the (large) channels table does not re-render on every frame. */
function NoiseFloorIndicator(): JSX.Element {
  const noiseFloor = useStore((s) => s.spectrum?.noise_floor_db ?? null);
  return (
    <span className="badge dim mono" title="Live noise floor (latest spectrum frame)">
      Noise floor: {noiseFloor == null ? '—' : formatDb(noiseFloor)}
    </span>
  );
}

function ObservationsModal({
  channel,
  onClose,
}: {
  channel: CandidateChannel;
  onClose: () => void;
}): JSX.Element {
  const [obs, setObs] = useState<Detection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .getChannelObservations(channel.id, 200)
      .then((r) => {
        if (!cancelled) setObs(r.observations);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [channel.id]);

  return (
    <Modal
      title={`Channel #${channel.id} · ${hzToMHz(channel.center_hz).toFixed(4)} MHz observations`}
      onClose={onClose}
    >
      {loading && <div className="empty">Loading observations…</div>}
      {error && <div className="notice danger">{error}</div>}
      {obs && obs.length === 0 && <div className="empty">No observations recorded.</div>}
      {obs && obs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th className="num">Center (MHz)</th>
                <th className="num">BW</th>
                <th className="num">Peak</th>
                <th className="num">Avg</th>
                <th className="num">SNR</th>
                <th className="num">Duration</th>
              </tr>
            </thead>
            <tbody>
              {obs.map((d) => (
                <tr key={d.id}>
                  <td title={formatIso(d.timestamp)}>{formatIso(d.timestamp)}</td>
                  <td className="num mono">{hzToMHz(d.center_hz).toFixed(4)}</td>
                  <td className="num">{hzSpanToHuman(d.bandwidth_hz)}</td>
                  <td className="num">{formatDb(d.peak_power_db)}</td>
                  <td className="num">{formatDb(d.avg_power_db)}</td>
                  <td className="num">{formatSnr(d.snr_db)}</td>
                  <td className="num">{formatDuration(d.duration_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}
