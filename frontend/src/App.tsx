import { useEffect } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Nav } from './components/Nav';
import { ConnectionStatus } from './components/ConnectionStatus';
import { PresenceIndicator } from './components/PresenceIndicator';
import { OperatorIndicator } from './components/OperatorIndicator';
import { liveConnection } from './lib/ws';
import { api } from './lib/api';
import { useStore } from './store/store';
import { Dashboard } from './pages/Dashboard';
import { Spectrum } from './pages/Spectrum';
import { Channels } from './pages/Channels';
import { Timeline } from './pages/Timeline';
import { Recordings } from './pages/Recordings';
import { Settings } from './pages/Settings';

export default function App(): JSX.Element {
  const setConfig = useStore((s) => s.setConfig);
  const setStatus = useStore((s) => s.setStatus);
  const setChannels = useStore((s) => s.setChannels);
  const setEvents = useStore((s) => s.setEvents);
  const setPresence = useStore((s) => s.setPresence);

  useEffect(() => {
    liveConnection.start();

    // Prime state from REST so the UI is populated before the first WS snapshot.
    let cancelled = false;
    void (async () => {
      try {
        const [config, device, metrics, channels, events, clients] = await Promise.all([
          api.getConfig(),
          api.getDevice().catch(() => null),
          api.getMetrics().catch(() => null),
          api.getChannels().catch(() => ({ channels: [] })),
          api.getEvents({ limit: 200 }).catch(() => ({ events: [] })),
          api.getClients().catch(() => null),
        ]);
        if (cancelled) return;
        setConfig(config, config.version);
        if (device && metrics) setStatus(device, metrics, false);
        setChannels(channels.channels);
        setEvents(events.events);
        if (clients) setPresence(clients.clients, clients.count, clients.operator_client_id);
      } catch {
        // WS will populate state once connected.
      }
    })();

    return () => {
      cancelled = true;
      liveConnection.stop();
    };
  }, [setConfig, setStatus, setChannels, setEvents, setPresence]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="6" fill="#0b1220" />
            <path
              d="M4 22 L9 22 L11 10 L14 26 L17 16 L20 22 L28 22"
              fill="none"
              stroke="#38bdf8"
              strokeWidth="2"
              strokeLinecap="round"
            />
            <circle cx="24" cy="9" r="2.5" fill="#f472b6" />
          </svg>
          <span>RTL-SDR Channel Detector</span>
        </div>
        <Nav />
        <div className="spacer" />
        <div className="status-cluster">
          <OperatorIndicator />
          <PresenceIndicator />
          <ConnectionStatus />
        </div>
      </header>

      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/spectrum" element={<Spectrum />} />
          <Route path="/channels" element={<Channels />} />
          <Route path="/timeline" element={<Timeline />} />
          <Route path="/recordings" element={<Recordings />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
