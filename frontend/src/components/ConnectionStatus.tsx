import { useStore } from '../store/store';

const LABEL: Record<string, string> = {
  connecting: 'Connecting…',
  open: 'Live',
  reconnecting: 'Reconnecting…',
  closed: 'Offline',
};

export function ConnectionStatus(): JSX.Element {
  const status = useStore((s) => s.connection);
  return (
    <span className={`conn ${status}`} aria-live="polite">
      <span className="dot" />
      <span className="small">{LABEL[status] ?? status}</span>
    </span>
  );
}
