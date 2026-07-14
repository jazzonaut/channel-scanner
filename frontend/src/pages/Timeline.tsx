import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/store';
import { api } from '../lib/api';
import type { CandidateChannel, Detection } from '../lib/types';
import { formatDuration, formatIso, formatTimeOnly, hzToMHz } from '../lib/format';

const WINDOW_OPTIONS = [
  { label: 'Last 5 min', ms: 5 * 60_000 },
  { label: 'Last 15 min', ms: 15 * 60_000 },
  { label: 'Last hour', ms: 60 * 60_000 },
  { label: 'Last 6 hours', ms: 6 * 60 * 60_000 },
];

const MAX_CHANNELS = 16;

interface Burst {
  detection: Detection;
  startMs: number;
  durationMs: number;
}

export function Timeline(): JSX.Element {
  const channelMap = useStore((s) => s.channels);
  const events = useStore((s) => s.events);
  const [windowMs, setWindowMs] = useState<number>(WINDOW_OPTIONS[1]!.ms);
  const [burstsByChannel, setBurstsByChannel] = useState<Map<number, Burst[]>>(new Map());
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  // Channels most recently active first.
  const channels = useMemo(() => {
    const arr = Array.from(channelMap.values());
    arr.sort((a, b) => b.last_seen.localeCompare(a.last_seen));
    return arr.slice(0, MAX_CHANNELS);
  }, [channelMap]);

  const now = Date.now();
  const windowStart = now - windowMs;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void (async () => {
      const map = new Map<number, Burst[]>();
      await Promise.all(
        channels.map(async (ch) => {
          try {
            const res = await api.getChannelObservations(ch.id, 300);
            const bursts: Burst[] = [];
            for (const d of res.observations) {
              const t = new Date(d.timestamp).getTime();
              if (Number.isNaN(t) || t < windowStart) continue;
              bursts.push({ detection: d, startMs: t, durationMs: d.duration_ms ?? 50 });
            }
            map.set(ch.id, bursts);
          } catch {
            map.set(ch.id, []);
          }
        }),
      );
      if (!cancelled) {
        setBurstsByChannel(map);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // channels identity changes when the map updates; refreshKey forces manual reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowMs, refreshKey, channelMap]);

  return (
    <div>
      <div className="page-header">
        <h1>Burst timeline</h1>
        <div className="row">
          <select
            value={windowMs}
            onChange={(e) => setWindowMs(Number(e.target.value))}
            style={{ width: 'auto' }}
          >
            {WINDOW_OPTIONS.map((o) => (
              <option key={o.ms} value={o.ms}>
                {o.label}
              </option>
            ))}
          </select>
          <button onClick={() => setRefreshKey((k) => k + 1)} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Bursts by channel</h2>
          <span className="small faint mono">
            {formatTimeOnly(new Date(windowStart).toISOString())} → {formatTimeOnly(new Date(now).toISOString())}
          </span>
        </div>
        {channels.length === 0 ? (
          <div className="empty">No candidate channels yet.</div>
        ) : (
          <div className="col" style={{ marginTop: 12 }}>
            {channels.map((ch) => (
              <ChannelTrack
                key={ch.id}
                channel={ch}
                bursts={burstsByChannel.get(ch.id) ?? []}
                windowStart={windowStart}
                windowMs={windowMs}
              />
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Recent events</h2>
        {events.length === 0 ? (
          <div className="empty">No events yet.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Kind</th>
                  <th>Message</th>
                  <th>Client</th>
                </tr>
              </thead>
              <tbody>
                {events.slice(0, 60).map((ev) => (
                  <tr key={ev.id}>
                    <td title={formatIso(ev.timestamp)}>{formatTimeOnly(ev.timestamp)}</td>
                    <td>
                      <span className="badge dim">{ev.kind}</span>
                    </td>
                    <td style={{ whiteSpace: 'normal' }}>{ev.message}</td>
                    <td className="mono faint">{ev.client_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ChannelTrack({
  channel,
  bursts,
  windowStart,
  windowMs,
}: {
  channel: CandidateChannel;
  bursts: Burst[];
  windowStart: number;
  windowMs: number;
}): JSX.Element {
  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
        <span className="small mono">
          #{channel.id} · {hzToMHz(channel.center_hz).toFixed(4)} MHz
        </span>
        <span className="small faint">
          {bursts.length} burst{bursts.length === 1 ? '' : 's'}
        </span>
      </div>
      <div className="timeline-track">
        {bursts.map((b) => {
          const leftPct = ((b.startMs - windowStart) / windowMs) * 100;
          const widthPct = Math.max((b.durationMs / windowMs) * 100, 0.4);
          if (leftPct < 0 || leftPct > 100) return null;
          return (
            <div
              key={b.detection.id}
              className="timeline-burst"
              style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
              title={`${formatIso(b.detection.timestamp)} · ${formatDuration(b.detection.duration_ms)} · SNR ${b.detection.snr_db.toFixed(1)} dB`}
            />
          );
        })}
      </div>
    </div>
  );
}
