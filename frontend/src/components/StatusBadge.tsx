import type { ChannelStatus } from '../lib/types';

const LABELS: Record<ChannelStatus, string> = {
  active: 'Active',
  recently_active: 'Recently active',
  inactive: 'Inactive',
};

export function StatusBadge({ status }: { status: ChannelStatus }): JSX.Element {
  return (
    <span className={`badge ${status}`}>
      <span className="dot" />
      {LABELS[status]}
    </span>
  );
}

export function GenericBadge({
  tone,
  children,
}: {
  tone: 'ok' | 'warn' | 'danger' | 'dim';
  children: React.ReactNode;
}): JSX.Element {
  return <span className={`badge ${tone}`}>{children}</span>;
}
