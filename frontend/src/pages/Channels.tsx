import { useEffect, useMemo, useState } from 'react';
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

type SortKey = 'id' | 'center_hz' | 'snr_db' | 'confidence' | 'last_seen' | 'observation_count';

export function Channels(): JSX.Element {
  const channelMap = useStore((s) => s.channels);
  const isOperator = useStore((s) => s.isOperator());

  const [sortKey, setSortKey] = useState<SortKey>('center_hz');
  const [asc, setAsc] = useState(true);
  const [obsFor, setObsFor] = useState<CandidateChannel | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const channels = useMemo(() => {
    const arr = Array.from(channelMap.values());
    arr.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp: number;
      if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
      else cmp = String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    });
    return arr;
  }, [channelMap, sortKey, asc]);

  function toggleSort(key: SortKey): void {
    if (key === sortKey) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  }

  async function focus(ch: CandidateChannel): Promise<void> {
    setActionMsg(null);
    try {
      await api.focusScan({ center_hz: ch.center_hz, span_hz: ch.bandwidth_hz * 4, channel_id: ch.id });
      setActionMsg(`Focused scan on channel #${ch.id} (${hzToMHz(ch.center_hz).toFixed(4)} MHz).`);
    } catch (err) {
      setActionMsg(err instanceof ApiError ? err.message : String(err));
    }
  }

  const sortArrow = (key: SortKey): string => (key === sortKey ? (asc ? ' ▲' : ' ▼') : '');

  return (
    <div>
      <div className="page-header">
        <h1>Candidate channels</h1>
        <div className="row">
          <a className="badge dim" href={api.exportUrl('csv', 'channels')} download>
            Export CSV
          </a>
          <a className="badge dim" href={api.exportUrl('json', 'channels')} download>
            Export JSON
          </a>
        </div>
      </div>

      {actionMsg && <div className="notice info">{actionMsg}</div>}
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
                <th className="num" onClick={() => toggleSort('id')}>
                  ID{sortArrow('id')}
                </th>
                <th className="num" onClick={() => toggleSort('center_hz')}>
                  Center (MHz){sortArrow('center_hz')}
                </th>
                <th className="num">Bandwidth</th>
                <th className="num">Current</th>
                <th className="num">Peak</th>
                <th className="num">Avg</th>
                <th className="num" onClick={() => toggleSort('snr_db')}>
                  SNR{sortArrow('snr_db')}
                </th>
                <th className="num" onClick={() => toggleSort('observation_count')}>
                  Obs{sortArrow('observation_count')}
                </th>
                <th>First seen</th>
                <th onClick={() => toggleSort('last_seen')}>
                  Last seen{sortArrow('last_seen')}
                </th>
                <th className="num">Burst</th>
                <th className="num">Recurrence</th>
                <th className="num" onClick={() => toggleSort('confidence')}>
                  Conf.{sortArrow('confidence')}
                </th>
                <th>Status</th>
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
                  <td className="num">{formatDb(ch.avg_power_db)}</td>
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
                      <button onClick={() => void focus(ch)}>Focus</button>
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
