export interface MetricTileProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: 'default' | 'warn' | 'danger';
}

export function MetricTile({ label, value, sub, tone = 'default' }: MetricTileProps): JSX.Element {
  const cls = tone === 'default' ? 'tile' : `tile ${tone}`;
  return (
    <div className={cls}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub != null && <div className="sub">{sub}</div>}
    </div>
  );
}
