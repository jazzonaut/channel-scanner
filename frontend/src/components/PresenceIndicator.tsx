import { useStore } from '../store/store';

export function PresenceIndicator(): JSX.Element {
  const count = useStore((s) => s.presenceCount);
  const clients = useStore((s) => s.clients);
  const title = clients.length
    ? clients.map((c) => `${c.display_name || c.client_id}${c.is_operator ? ' (operator)' : ''}`).join('\n')
    : 'No connected clients';
  return (
    <span className="conn" title={title} aria-label={`${count} connected clients`}>
      <span aria-hidden>👥</span>
      <span className="mono">{count}</span>
      <span className="faint small">online</span>
    </span>
  );
}
