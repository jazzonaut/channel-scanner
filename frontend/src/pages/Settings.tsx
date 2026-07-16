import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/store';
import { ControlLeaseBar } from '../components/ControlLeaseBar';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { api, ApiError } from '../lib/api';
import {
  computeWarnings,
  configToForm,
  PRESETS,
  validateSettings,
  type BoolFieldKey,
  type FieldErrors,
  type SettingsFormValues,
  type StringFieldKey,
} from '../lib/settingsValidation';
import { SCAN_BACKENDS, type CalibrateResponse } from '../lib/types';
import { formatDb, formatIso, hzToHuman } from '../lib/format';

const BACKEND_LABELS: Record<(typeof SCAN_BACKENDS)[number], string> = {
  sim: 'Simulator (sim)',
  rtlsdr: 'RTL-SDR (rtlsdr)',
  rtl_power: 'rtl_power',
  soapy: 'SoapySDR (soapy)',
};

export function Settings(): JSX.Element {
  const config = useStore((s) => s.config);
  const version = useStore((s) => s.configVersion);
  const changedBy = useStore((s) => s.configChangedBy);
  const clientId = useStore((s) => s.clientId);
  const isOperator = useStore((s) => s.isOperator());
  const setConfig = useStore((s) => s.setConfig);
  const events = useStore((s) => s.events);

  const [form, setForm] = useState<SettingsFormValues | null>(config ? configToForm(config) : null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: 'info' | 'danger' | 'warn'; text: string } | null>(
    null,
  );
  const [conflictVersion, setConflictVersion] = useState<number | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Frequency calibration (PPM) tool state.
  const [calRefMhz, setCalRefMhz] = useState<string>(() =>
    config ? (((config.start_hz + config.end_hz) / 2) / 1e6).toFixed(4) : '868.9500',
  );
  const [calibrating, setCalibrating] = useState(false);
  const [calResult, setCalResult] = useState<CalibrateResponse | null>(null);
  const [calError, setCalError] = useState<string | null>(null);

  async function clearAllData(): Promise<void> {
    setConfirmClear(false);
    setClearing(true);
    try {
      await api.clearAllData(clientId);
      setMessage({ tone: 'info', text: 'All recorded data cleared. Scan settings were kept.' });
    } catch (err) {
      setMessage({
        tone: 'danger',
        text: err instanceof ApiError ? err.message : String(err),
      });
    } finally {
      setClearing(false);
    }
  }

  async function measureCalibration(): Promise<void> {
    const mhz = Number(calRefMhz);
    if (!Number.isFinite(mhz) || mhz <= 0) {
      setCalResult(null);
      setCalError('Enter a valid reference frequency in MHz.');
      return;
    }
    setCalibrating(true);
    setCalError(null);
    setCalResult(null);
    try {
      const result = await api.calibrate(Math.round(mhz * 1e6));
      setCalResult(result);
    } catch (err) {
      setCalError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setCalibrating(false);
    }
  }

  function applySuggestedPpm(): void {
    if (!calResult || calResult.suggested_ppm == null) return;
    set('ppm', String(calResult.suggested_ppm));
    setMessage({
      tone: 'info',
      text: `Applied suggested ppm ${calResult.suggested_ppm}. Review and press Save to apply.`,
    });
  }

  // Sync form when config first loads (but don't clobber unsaved edits after that).
  useEffect(() => {
    if (config && form === null) setForm(configToForm(config));
  }, [config, form]);

  const warnings = useMemo(() => (form ? computeWarnings(form) : []), [form]);

  // Recent config-change events (who changed what).
  const configEvents = useMemo(
    () => events.filter((e) => e.kind === 'config' || e.kind === 'config_changed').slice(0, 5),
    [events],
  );

  if (!config || !form) {
    return (
      <div>
        <h1>Settings</h1>
        <div className="card empty">Loading configuration…</div>
      </div>
    );
  }

  function set<K extends StringFieldKey>(key: K, value: string): void {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function setBool<K extends BoolFieldKey>(key: K, value: boolean): void {
    setForm((f) => (f ? { ...f, [key]: value } : f));
  }

  function applyPreset(name: keyof typeof PRESETS): void {
    const preset = PRESETS[name];
    if (!preset) return;
    setForm((f) => (f ? { ...f, ...preset } : f));
    setMessage({ tone: 'info', text: `Applied preset: ${name}. Review and save to apply.` });
  }

  function reset(): void {
    if (config) setForm(configToForm(config));
    setErrors({});
    setMessage(null);
    setConflictVersion(null);
  }

  async function save(): Promise<void> {
    if (!form) return;
    const { update, errors: errs } = validateSettings(form);
    setErrors(errs);
    if (Object.keys(errs).length > 0) {
      setMessage({ tone: 'danger', text: 'Fix the highlighted fields before saving.' });
      return;
    }
    setSaving(true);
    setMessage(null);
    try {
      const result = await api.updateConfig(update, version, clientId);
      setConfig(result, result.version);
      setForm(configToForm(result));
      setConflictVersion(null);
      setMessage({ tone: 'info', text: `Saved. Config is now version ${result.version}.` });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflictVersion(version);
        setMessage({
          tone: 'warn',
          text: 'Version conflict (409): another operator changed the config. Reload to get the latest, then reapply your edits.',
        });
      } else if (err instanceof ApiError && err.status === 403) {
        setMessage({
          tone: 'danger',
          text: 'Rejected: you must hold the control lease to change settings.',
        });
      } else {
        setMessage({ tone: 'danger', text: err instanceof ApiError ? err.message : String(err) });
      }
    } finally {
      setSaving(false);
    }
  }

  const disabled = !isOperator || saving;

  const receiverChanged =
    form.backend !== config.backend ||
    form.simulation !== config.simulation ||
    form.deviceIndex !== String(config.device_index);

  return (
    <div>
      <div className="page-header">
        <h1>Settings</h1>
        <div className="row">
          <span className="badge dim">Config v{version}</span>
          {changedBy && <span className="small faint">last changed by {changedBy}</span>}
        </div>
      </div>

      <ControlLeaseBar />

      {!isOperator && (
        <div className="notice warn">
          Editing is disabled until you acquire the control lease above.
        </div>
      )}
      {message && <div className={`notice ${message.tone}`}>{message.text}</div>}
      {conflictVersion != null && (
        <div className="notice warn">
          <button onClick={reset} style={{ marginRight: 8 }}>
            Reload latest
          </button>
          Discards your local edits and loads the current server config (v{version}).
        </div>
      )}

      {warnings.map((w, i) => (
        <div className="notice warn" key={i}>
          {w.message}
        </div>
      ))}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Presets</h2>
          <div className="row">
            <button onClick={() => applyPreset('wavenis-868')} disabled={disabled}>
              Wavenis 868 wideband
            </button>
            <button onClick={() => applyPreset('near-device')} disabled={disabled}>
              Near-device investigation
            </button>
            <button onClick={() => applyPreset('long-survey')} disabled={disabled}>
              Long-duration survey
            </button>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          Wavenis: parks one 2.4 MS/s window across the full 15-channel candidate grid for
          continuous hop evidence and enables capped triggered IQ retention. Near-device:
          conservative settings for close strong emitters.
          Long-duration survey: long dwell + low threshold to catch infrequent transmissions.
        </p>
      </div>

      <section className="settings-section">
        <h2 className="section-head">Receiver</h2>
        <p className="section-note">
          Source device and tuner front-end. Simulation generates synthetic spectra without
          hardware.
        </p>
        {receiverChanged && (
          <div className="notice warn inline-warn">
            Changing the receiver, device or simulation mode re-opens the SDR and restarts an active
            scan.
          </div>
        )}
        <div className="form-grid">
          <Field label="Backend" error={errors.backend}>
            <select value={form.backend} onChange={(e) => set('backend', e.target.value)} disabled={disabled}>
              {SCAN_BACKENDS.map((b) => (
                <option key={b} value={b}>
                  {BACKEND_LABELS[b]}
                </option>
              ))}
            </select>
          </Field>
          <Checkbox
            label="Simulation mode"
            checked={form.simulation}
            onChange={(v) => setBool('simulation', v)}
            disabled={disabled}
          />
          <Field label="Device index" error={errors.deviceIndex}>
            <input value={form.deviceIndex} onChange={(e) => set('deviceIndex', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="Sample rate (Hz)" error={errors.sampleRate}>
            <input value={form.sampleRate} onChange={(e) => set('sampleRate', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label='Gain ("auto" or dB)' error={errors.gain}>
            <input value={form.gain} onChange={(e) => set('gain', e.target.value)} disabled={disabled} />
          </Field>
          <Field label="Frequency correction (ppm)" error={errors.ppm}>
            <input value={form.ppm} onChange={(e) => set('ppm', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="section-head">Band &amp; sweep</h2>
        <p className="section-note">
          Frequency range and per-hop dwell. Frequencies are entered in MHz and stored as exact Hz.
        </p>
        <div className="form-grid">
          <Field label="Start (MHz)" error={errors.startMhz}>
            <input value={form.startMhz} onChange={(e) => set('startMhz', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="End (MHz)" error={errors.endMhz}>
            <input value={form.endMhz} onChange={(e) => set('endMhz', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="Step (Hz, 0 = auto)" error={errors.stepHz}>
            <input value={form.stepHz} onChange={(e) => set('stepHz', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="Dwell (ms)" error={errors.dwellMs}>
            <input value={form.dwellMs} onChange={(e) => set('dwellMs', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="FFT size" error={errors.fftSize}>
            <select value={form.fftSize} onChange={(e) => set('fftSize', e.target.value)} disabled={disabled}>
              {['256', '512', '1024', '2048', '4096', '8192', '16384'].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="section-head">Detection</h2>
        <p className="section-note">
          Thresholding, noise-floor tracking and the bands to ignore.
        </p>
        <div className="form-grid">
          <Field label="Detection threshold (dB above noise)" error={errors.thresholdDb}>
            <input value={form.thresholdDb} onChange={(e) => set('thresholdDb', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="Noise floor EMA alpha (0–1)" error={errors.noiseFloorAlpha}>
            <input value={form.noiseFloorAlpha} onChange={(e) => set('noiseFloorAlpha', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="Exclusions (MHz ranges, e.g. 868.2-868.4)" error={errors.exclusions}>
            <input value={form.exclusions} onChange={(e) => set('exclusions', e.target.value)} disabled={disabled} placeholder="low-high, low-high" />
          </Field>
          <Field label="Known channel widths (Hz, comma-separated)" error={errors.knownWidthsHz}>
            <input value={form.knownWidthsHz} onChange={(e) => set('knownWidthsHz', e.target.value)} disabled={disabled} placeholder="12500, 25000" />
          </Field>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="section-head">Display</h2>
        <p className="section-note">
          These control the live spectrum refresh rate and resolution shown in the UI; they do not
          affect detection.
        </p>
        <div className="form-grid">
          <Field label="Spectrum FPS (1–60)" error={errors.spectrumFps}>
            <input value={form.spectrumFps} onChange={(e) => set('spectrumFps', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="Spectrum bins (16–8192)" error={errors.spectrumBins}>
            <input value={form.spectrumBins} onChange={(e) => set('spectrumBins', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
        </div>
      </section>

      <section className="settings-section">
        <h2 className="section-head">Recording &amp; retention</h2>
        <p className="section-note">
          IQ recording is off by default. When enabled, older recordings are pruned once storage or
          retention limits are hit.
        </p>
        <div className="form-grid">
          <Checkbox
            label="Enable IQ recording"
            checked={form.enableIqRecording}
            onChange={(v) => setBool('enableIqRecording', v)}
            disabled={disabled}
          />
          <Field label="Max IQ storage (GB)" error={errors.maxIqStorageGb}>
            <input value={form.maxIqStorageGb} onChange={(e) => set('maxIqStorageGb', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="Retention (days)" error={errors.retentionDays}>
            <input value={form.retentionDays} onChange={(e) => set('retentionDays', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
        </div>
      </section>

      <div className="card">
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button onClick={reset} disabled={saving}>
            Reset
          </button>
          <button className="primary" onClick={() => void save()} disabled={disabled}>
            {saving ? 'Saving…' : 'Save configuration'}
          </button>
        </div>
      </div>

      {configEvents.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <h2>Recent configuration changes</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Message</th>
                  <th>Changed by</th>
                </tr>
              </thead>
              <tbody>
                {configEvents.map((ev) => (
                  <tr key={ev.id}>
                    <td>{formatIso(ev.timestamp)}</td>
                    <td style={{ whiteSpace: 'normal' }}>{ev.message}</td>
                    <td className="mono faint">{ev.client_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h2 style={{ marginTop: 0 }}>Frequency calibration (PPM)</h2>
        <p className="small faint" style={{ marginTop: 0 }}>
          Cheap RTL-SDR dongles have crystals that drift, so tuned frequencies sit slightly off.
          Point the receiver at a <strong>known, steady carrier</strong> (e.g. a signal generator or
          a reference transmitter on an exact frequency) and this estimates the tuner&apos;s ppm
          error. Receive-only measurement — nothing is transmitted.
        </p>
        <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'wrap', gap: 12 }}>
          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="cal-ref-mhz">Reference frequency (MHz)</label>
            <input
              id="cal-ref-mhz"
              value={calRefMhz}
              onChange={(e) => setCalRefMhz(e.target.value)}
              disabled={calibrating}
              inputMode="decimal"
            />
          </div>
          <button onClick={() => void measureCalibration()} disabled={calibrating}>
            {calibrating ? 'Measuring…' : 'Measure'}
          </button>
        </div>

        {calError && (
          <div className="notice danger" style={{ marginTop: 12 }}>
            {calError}
          </div>
        )}

        {calResult && !calResult.ok && (
          <div className="notice warn" style={{ marginTop: 12 }}>
            {calResult.message}
          </div>
        )}

        {calResult && calResult.ok && (
          <div style={{ marginTop: 12 }}>
            {calResult.message && (
              <p className="small faint" style={{ marginTop: 0 }}>
                {calResult.message}
              </p>
            )}
            <div className="table-wrap">
              <table>
                <tbody>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Measured</th>
                    <td className="mono">
                      {calResult.measured_hz != null ? hzToHuman(calResult.measured_hz) : '—'}
                    </td>
                  </tr>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Offset</th>
                    <td className="mono">
                      {calResult.offset_hz != null ? `${calResult.offset_hz} Hz` : '—'}
                    </td>
                  </tr>
                  <tr>
                    <th style={{ textAlign: 'left' }}>PPM error</th>
                    <td className="mono">
                      {calResult.ppm_error != null ? calResult.ppm_error.toFixed(2) : '—'}
                    </td>
                  </tr>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Peak SNR</th>
                    <td className="mono">{formatDb(calResult.peak_snr_db)}</td>
                  </tr>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Current ppm</th>
                    <td className="mono">
                      {calResult.current_ppm != null ? calResult.current_ppm : '—'}
                    </td>
                  </tr>
                  <tr>
                    <th style={{ textAlign: 'left' }}>Suggested ppm</th>
                    <td className="mono">
                      {calResult.suggested_ppm != null ? calResult.suggested_ppm : '—'}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="row" style={{ marginTop: 12, alignItems: 'center' }}>
              <button
                onClick={applySuggestedPpm}
                disabled={!isOperator || calResult.suggested_ppm == null}
                title={
                  !isOperator
                    ? 'acquire the control lease to apply'
                    : 'Set the frequency-correction (ppm) field to the suggested value'
                }
              >
                Apply suggested ppm
              </button>
              {calResult.suggested_ppm != null && isOperator && (
                <span className="small faint">
                  Fills the frequency-correction (ppm) field above — press Save to apply.
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="card danger-zone" style={{ marginTop: 16 }}>
        <h2>Danger zone</h2>
        <p className="small faint" style={{ marginTop: 0 }}>
          Permanently delete all recorded data — candidate channels, detections, bursts, events,
          sessions, and IQ recordings (files included). Your scan configuration is kept. This cannot
          be undone.
        </p>
        <button
          className="danger"
          onClick={() => setConfirmClear(true)}
          disabled={!isOperator || clearing}
          title={!isOperator ? 'Requires the control lease' : 'Delete all recorded data'}
        >
          {clearing ? 'Clearing…' : 'Clear all data'}
        </button>
        {!isOperator && (
          <span className="small faint" style={{ marginLeft: 8 }}>
            Acquire the control lease above to enable.
          </span>
        )}
      </div>

      {confirmClear && (
        <ConfirmDialog
          title="Clear all data"
          danger
          confirmLabel="Delete everything"
          message={
            <span>
              This permanently deletes <strong>all</strong> candidate channels, detections, bursts,
              events, sessions, and IQ recordings (including files on disk). Your scan configuration
              is preserved. This cannot be undone. Continue?
            </span>
          }
          onConfirm={() => void clearAllData()}
          onCancel={() => setConfirmClear(false)}
        />
      )}
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled: boolean;
}): JSX.Element {
  return (
    <div className="field checkbox">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <label>{label}</label>
    </div>
  );
}
