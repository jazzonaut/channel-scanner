import { useStore } from '../store/store';

/** Compact indicator in the top bar: are you the operator, is someone else, or nobody. */
export function OperatorIndicator(): JSX.Element {
  const operatorId = useStore((s) => s.lease.operatorClientId);
  const clientId = useStore((s) => s.clientId);
  const clients = useStore((s) => s.clients);

  if (!operatorId) {
    return (
      <span className="badge dim" title="No operator holds the control lease">
        Control free
      </span>
    );
  }
  if (operatorId === clientId) {
    return (
      <span className="badge ok" title="You hold the control lease">
        You have control
      </span>
    );
  }
  const op = clients.find((c) => c.client_id === operatorId);
  const name = op?.display_name || operatorId;
  return (
    <span className="badge warn" title={`Operator: ${name}`}>
      {name} in control
    </span>
  );
}
