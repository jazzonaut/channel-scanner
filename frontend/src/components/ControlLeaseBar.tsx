import { useState } from 'react';
import { useStore } from '../store/store';
import { api, ApiError } from '../lib/api';
import { formatIso } from '../lib/format';

/**
 * Shows who holds the control lease and lets the current client acquire/release it.
 * Editing config or scan settings requires holding this lease.
 */
export function ControlLeaseBar(): JSX.Element {
  const clientId = useStore((s) => s.clientId);
  const displayName = useStore((s) => s.displayName);
  const operatorId = useStore((s) => s.lease.operatorClientId);
  const leaseExpires = useStore((s) => s.lease.leaseExpires);
  const clients = useStore((s) => s.clients);
  const setLease = useStore((s) => s.setLease);
  const isOperator = operatorId != null && operatorId === clientId;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function acquire(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const res = await api.acquireControl(clientId, displayName);
      setLease(res.operator_client_id, res.lease_expires);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function release(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await api.releaseControl(clientId);
      setLease(null, null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const operatorName =
    operatorId == null
      ? null
      : clients.find((c) => c.client_id === operatorId)?.display_name || operatorId;

  return (
    <div className={`lease-bar ${isOperator ? 'you' : ''}`}>
      <div className="col" style={{ gap: 2 }}>
        <strong>Control lease</strong>
        <span className="small muted">
          {operatorId == null ? (
            'Nobody currently holds control. Acquire it to change settings.'
          ) : isOperator ? (
            <>
              You hold control{leaseExpires ? ` · expires ${formatIso(leaseExpires)}` : ''}.
            </>
          ) : (
            <>
              Held by <strong>{operatorName}</strong>
              {leaseExpires ? ` · expires ${formatIso(leaseExpires)}` : ''}.
            </>
          )}
        </span>
        {error && <span className="danger-text small">{error}</span>}
      </div>
      <div className="spacer" style={{ flex: 1 }} />
      <div className="row">
        {isOperator ? (
          <button className="danger" onClick={release} disabled={busy}>
            Release control
          </button>
        ) : (
          <button className="primary" onClick={acquire} disabled={busy}>
            {operatorId == null ? 'Acquire control' : 'Take over control'}
          </button>
        )}
      </div>
    </div>
  );
}
