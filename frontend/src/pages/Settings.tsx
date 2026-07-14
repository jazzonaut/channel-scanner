import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../store/store';
import { ControlLeaseBar } from '../components/ControlLeaseBar';
import { api, ApiError } from '../lib/api';
import {
  computeWarnings,
  configToForm,
  PRESETS,
  validateSettings,
  type FieldErrors,
  type SettingsFormValues,
} from '../lib/settingsValidation';
import { formatIso } from '../lib/format';

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

  function set<K extends keyof SettingsFormValues>(key: K, value: string): void {
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
            <button onClick={() => applyPreset('near-device')} disabled={disabled}>
              Near-device investigation
            </button>
            <button onClick={() => applyPreset('long-survey')} disabled={disabled}>
              Long-duration survey
            </button>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          Near-device: conservative, longer dwell and higher threshold for close strong emitters.
          Long-duration survey: long dwell + low threshold to catch infrequent transmissions.
        </p>
      </div>

      <div className="card">
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
          <Field label="Sample rate (Hz)" error={errors.sampleRate}>
            <input value={form.sampleRate} onChange={(e) => set('sampleRate', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label='Gain ("auto" or dB)' error={errors.gain}>
            <input value={form.gain} onChange={(e) => set('gain', e.target.value)} disabled={disabled} />
          </Field>
          <Field label="Frequency correction (ppm)" error={errors.ppm}>
            <input value={form.ppm} onChange={(e) => set('ppm', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="Dwell (ms)" error={errors.dwellMs}>
            <input value={form.dwellMs} onChange={(e) => set('dwellMs', e.target.value)} disabled={disabled} inputMode="numeric" />
          </Field>
          <Field label="Detection threshold (dB above noise)" error={errors.thresholdDb}>
            <input value={form.thresholdDb} onChange={(e) => set('thresholdDb', e.target.value)} disabled={disabled} inputMode="decimal" />
          </Field>
          <Field label="Noise floor EMA alpha (0–1)" error={errors.noiseFloorAlpha}>
            <input value={form.noiseFloorAlpha} onChange={(e) => set('noiseFloorAlpha', e.target.value)} disabled={disabled} inputMode="decimal" />
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
          <Field label="Exclusions (MHz ranges, e.g. 868.2-868.4)" error={errors.exclusions}>
            <input value={form.exclusions} onChange={(e) => set('exclusions', e.target.value)} disabled={disabled} placeholder="low-high, low-high" />
          </Field>
          <Field label="Known channel widths (Hz, comma-separated)" error={errors.knownWidthsHz}>
            <input value={form.knownWidthsHz} onChange={(e) => set('knownWidthsHz', e.target.value)} disabled={disabled} placeholder="12500, 25000" />
          </Field>
        </div>

        <div className="row" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
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
