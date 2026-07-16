import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useStore } from '../store/store';
import { api, ApiError } from '../lib/api';
import { InfoTip } from '../components/InfoTip';
import { meterScore } from '../lib/meterScore';
import type { MeterScore } from '../lib/meterScore';
import type { CandidateChannel, WavenisStatus } from '../lib/types';
import { formatConfidence, formatSnr, hzToMHz } from '../lib/format';
import './Investigate.css';

const INTRO =
  'This is a guided, receive-only walkthrough for surveying the RF around a device you already own. ' +
  'It listens to the air and highlights recurring narrowband patterns — it never transmits, and it never ' +
  'claims a signal is a specific device. Anything the survey finds is a candidate channel, not a confirmed meter.';

interface ScoredChannel {
  channel: CandidateChannel;
  meter: MeterScore;
}

function Step({
  n,
  title,
  note,
  children,
}: {
  n: number;
  title: string;
  note: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <li className="investigate-step">
      <div className="investigate-step__num" aria-hidden="true">
        {n}
      </div>
      <div className="investigate-step__body">
        <h2 className="investigate-step__title">{title}</h2>
        <p className="investigate-step__note">{note}</p>
        <div className="investigate-step__action">{children}</div>
      </div>
    </li>
  );
}

export function Investigate(): JSX.Element {
  const channelMap = useStore((s) => s.channels);
  const scanning = useStore((s) => s.scanning);
  const navigate = useNavigate();

  const [scanBusy, setScanBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decodeBusy, setDecodeBusy] = useState(false);
  const [decodeMessage, setDecodeMessage] = useState<string | null>(null);
  const [wavenis, setWavenis] = useState<WavenisStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const refresh = async (): Promise<void> => {
      try {
        const status = await api.getWavenisStatus();
        if (!cancelled) setWavenis(status);
      } catch {
        // The generic scanner remains usable if an older backend lacks this
        // optional evidence endpoint.
      }
    };
    void refresh();
    timer = setInterval(() => void refresh(), 2000);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, []);

  const channelCount = channelMap.size;

  // Top 3 candidates by meter-like pattern score (heuristic only — see meterScore).
  const topCandidates = useMemo<ScoredChannel[]>(() => {
    return Array.from(channelMap.values())
      .map((channel) => ({ channel, meter: meterScore(channel) }))
      .sort((a, b) => b.meter.score - a.meter.score)
      .slice(0, 3);
  }, [channelMap]);

  async function toggleScan(): Promise<void> {
    setScanBusy(true);
    setError(null);
    const wasScanning = scanning;
    // Optimistic: flip the store immediately so the UI feels responsive; the
    // WebSocket status frame will confirm (or correct) it shortly.
    useStore.getState().setScanning(!wasScanning);
    try {
      if (wasScanning) await api.stopScan();
      else await api.startScan();
    } catch (err) {
      // Roll back the optimistic flip on failure.
      useStore.getState().setScanning(wasScanning);
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setScanBusy(false);
    }
  }

  async function focus(channel: CandidateChannel): Promise<void> {
    setError(null);
    try {
      await api.focus(channel.center_hz);
    } catch (err) {
      // Even if focus is rejected (e.g. not the control operator) still open the
      // scope parked on this center — Scope re-requests focus via the ?center param.
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      navigate(`/scope?center=${channel.center_hz}`);
    }
  }

  async function runDecoder(): Promise<void> {
    setDecodeBusy(true);
    setError(null);
    setDecodeMessage(null);
    try {
      const res = await api.runDecoder();
      setDecodeMessage(res.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDecodeBusy(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>
          Investigate my meter <InfoTip text={INTRO} />
        </h1>
      </div>

      <div className="notice info">
        Receive-only guide. The scanner listens; it never transmits and never decrypts. Findings are
        inferred candidate channels, not confirmed devices.
      </div>

      {wavenis && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <h2 style={{ margin: 0 }}>Wavenis 868 wideband evidence</h2>
              <p className="small faint" style={{ margin: '5px 0 0' }}>
                {wavenis.message}. All 15 candidate channels are measured from the same IQ timeline;
                qualification is RF evidence, not protocol identity.
              </p>
            </div>
            <span className={`badge ${wavenis.active ? '' : 'dim'}`}>
              {wavenis.active ? 'live' : wavenis.configured ? 'ready' : 'profile required'}
            </span>
          </div>

          {!wavenis.configured ? (
            <div style={{ marginTop: 12 }}>
              <Link className="badge dim" to="/settings">
                Apply Wavenis 868 preset
              </Link>
            </div>
          ) : (
            <>
              <div className="row" style={{ gap: 20, marginTop: 12, flexWrap: 'wrap' }}>
                <span className="small">
                  <strong>{wavenis.frames_processed.toLocaleString()}</strong> time frames
                </span>
                <span className="small">
                  <strong>{wavenis.frame_ms?.toFixed(3) ?? '—'} ms</strong> resolution
                </span>
                <span className="small">
                  <strong>
                    {wavenis.channels.reduce((sum, channel) => sum + channel.qualified_observations, 0)}
                  </strong>{' '}
                  qualified bursts
                </span>
                <span className="small mono">
                  {(wavenis.receiver_center_hz / 1e6).toFixed(3)} MHz @{' '}
                  {(wavenis.sample_rate / 1e6).toFixed(1)} MS/s
                </span>
                {wavenis.acquisition && (
                  <span className="small">
                    <strong>
                      {wavenis.acquisition.mode === 'native_continuous'
                        ? 'continuous stream'
                        : 'bounded reads'}
                    </strong>{' '}
                    · {wavenis.acquisition.dropped_blocks} dropped ·{' '}
                    {wavenis.acquisition.timing_gaps} timing gaps
                  </span>
                )}
                {wavenis.capture && (
                  <span className="small">
                    <strong>
                      {wavenis.capture.enabled
                        ? wavenis.capture.capture_pending
                          ? `capturing (${wavenis.capture.pending_triggers} triggers)`
                          : `${wavenis.capture.captures_completed} IQ captures`
                        : 'IQ capture off'}
                    </strong>{' '}
                    · {wavenis.capture.buffered_seconds.toFixed(1)} s buffered
                  </span>
                )}
              </div>
              {wavenis.acquisition?.error && (
                <div className="notice danger" style={{ marginTop: 12 }}>
                  SDR stream error: {wavenis.acquisition.error}
                </div>
              )}
              {wavenis.capture && !wavenis.capture.enabled && (
                <div className="notice warn" style={{ marginTop: 12 }}>
                  Qualified events are visible but raw IQ is not being preserved. Enable IQ recording
                  in Settings (the Wavenis preset enables it with capped retention).
                </div>
              )}
              <div className="row" style={{ gap: 5, marginTop: 12, flexWrap: 'wrap' }}>
                {wavenis.channels.map((channel) => (
                  <span
                    className={`badge ${channel.active || channel.qualified_observations > 0 ? '' : 'dim'}`}
                    key={channel.index}
                    title={`${(channel.freq_hz / 1e6).toFixed(3)} MHz · noise ${channel.noise_db?.toFixed(1) ?? '—'} dB · peak SNR ${channel.peak_snr_db.toFixed(1)} dB`}
                  >
                    ch{channel.index}: {channel.qualified_observations}
                  </span>
                ))}
              </div>
              {wavenis.recent_bursts.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 12 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Sequence</th>
                        <th>Channel</th>
                        <th className="num">Frequency</th>
                        <th className="num">Start</th>
                        <th className="num">Duration</th>
                        <th className="num">Peak SNR</th>
                        <th className="num">Offset</th>
                        <th>Evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {wavenis.recent_bursts
                        .slice(-10)
                        .reverse()
                        .map((burst) => (
                          <tr key={burst.sequence}>
                            <td className="mono">#{burst.sequence}</td>
                            <td className="mono">ch{burst.channel_index}</td>
                            <td className="num mono">{(burst.freq_hz / 1e6).toFixed(3)} MHz</td>
                            <td className="num mono">{burst.start_s.toFixed(3)} s</td>
                            <td className="num mono">{burst.duration_ms.toFixed(3)} ms</td>
                            <td className="num mono">{burst.peak_snr_db.toFixed(1)} dB</td>
                            <td className="num mono">{burst.freq_offset_hz.toFixed(0)} Hz</td>
                            <td>
                              <span className={`badge ${burst.qualified ? '' : 'dim'}`}>
                                {burst.qualified ? 'qualified' : 'transient'}
                              </span>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {error && <div className="notice danger">{error}</div>}

      <ol className="investigate-steps">
        <Step
          n={1}
          title="Set conservative near-device settings"
          note="Open Settings and apply the “Near-device” preset — conservative gain, longer dwell and a higher threshold so a close, strong emitter does not swamp the receiver. Review and save it there."
        >
          <Link className="badge dim" to="/settings">
            Open Settings
          </Link>
        </Step>

        <Step
          n={2}
          title="Start a survey"
          note="Begin a receive-only sweep across the configured band and let it run for a while so recurring transmissions have time to repeat."
        >
          <div className="row" style={{ gap: 12, alignItems: 'center' }}>
            <button
              className={scanning ? 'danger' : 'primary'}
              onClick={() => void toggleScan()}
              disabled={scanBusy}
            >
              {scanBusy ? 'Working…' : scanning ? 'Stop survey' : 'Start survey'}
            </button>
            <span className="small faint">
              Scanner is <strong>{scanning ? 'running' : 'stopped'}</strong> ·{' '}
              <strong>{channelCount}</strong> candidate channel{channelCount === 1 ? '' : 's'} so far
            </span>
          </div>
        </Step>

        <Step
          n={3}
          title="Shortlist by pattern & cadence"
          note="On the Channels page, sort by the Pattern column and watch for a steady recurrence — a regular, narrowband, short-burst cadence is the pattern of interest. The strongest matches so far are previewed below."
        >
          <div className="row" style={{ gap: 12, alignItems: 'center', marginBottom: 8 }}>
            <Link className="badge dim" to="/channels">
              Open Channels
            </Link>
            <InfoTip text="The Pattern score is a heuristic over cadence, bandwidth, burst length and how often a channel recurs. It is a pattern indicator only — never a claim that a channel is a meter or any specific device." />
          </div>
          {topCandidates.length === 0 ? (
            <div className="empty">No candidate channels yet — start a survey and let it run.</div>
          ) : (
            <ul className="investigate-candidates">
              {topCandidates.map(({ channel, meter }) => (
                <li key={channel.id} className="investigate-candidate">
                  <div className="investigate-candidate__meta">
                    <span className="mono">{hzToMHz(channel.center_hz).toFixed(4)} MHz</span>
                    <span className={`badge meter-${meter.label}`}>{meter.label}</span>
                    <span className="small faint">
                      SNR {formatSnr(channel.snr_db)} · conf {formatConfidence(channel.confidence)} ·{' '}
                      {channel.observation_count} obs
                    </span>
                    {meter.reasons.length > 0 && (
                      <span className="small faint">{meter.reasons.join(', ')}</span>
                    )}
                  </div>
                  <button onClick={() => void focus(channel)}>Focus</button>
                </li>
              ))}
            </ul>
          )}
        </Step>

        <Step
          n={4}
          title="Inspect in the scope"
          note="Park the tuner on a shortlisted channel and watch its fine spectrogram and envelope. Look at the pulse pattern and the “next expected” cadence marker — a repeating shape that lines up with the expected interval is what you are after."
        >
          <Link className="badge dim" to="/scope">
            Open Scope
          </Link>
        </Step>

        <Step
          n={5}
          title="Try to decode"
          note="Optionally run the decoder. When rtl_433 is installed it names known receive-only protocols; anything unknown or encrypted simply stays “unknown”. A protocol name is a decode label, not proof of which physical device sent it."
        >
          <div className="row" style={{ gap: 12, alignItems: 'center' }}>
            <button onClick={() => void runDecoder()} disabled={decodeBusy}>
              {decodeBusy ? 'Running…' : 'Run decoder'}
            </button>
            <Link className="badge dim" to="/decoder">
              Open Decoder
            </Link>
          </div>
          {decodeMessage && (
            <div className="notice info" style={{ marginTop: 8, marginBottom: 0 }}>
              {decodeMessage}
            </div>
          )}
        </Step>
      </ol>
    </div>
  );
}
