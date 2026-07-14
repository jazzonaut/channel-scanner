import { NavLink } from 'react-router-dom';

interface Route {
  to: string;
  label: string;
}

const ROUTES: Route[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/spectrum', label: 'Spectrum' },
  { to: '/channels', label: 'Channels' },
  { to: '/timeline', label: 'Timeline' },
  { to: '/recordings', label: 'Recordings' },
  { to: '/settings', label: 'Settings' },
];

export function Nav(): JSX.Element {
  return (
    <nav className="nav" aria-label="Primary">
      {ROUTES.map((r) => (
        <NavLink key={r.to} to={r.to} end={r.to === '/'}>
          {r.label}
        </NavLink>
      ))}
    </nav>
  );
}
