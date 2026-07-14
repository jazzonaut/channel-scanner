import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { Channels } from '../pages/Channels';
import { useStore } from '../store/store';
import type { CandidateChannel } from '../lib/types';

const CHANNEL: CandidateChannel = {
  id: 7,
  center_hz: 868_300_000,
  bandwidth_hz: 25_000,
  current_power_db: -12.4,
  peak_power_db: -6.1,
  avg_power_db: -15.2,
  snr_db: 18.3,
  observation_count: 42,
  first_seen: '2026-07-14T10:00:00.000Z',
  last_seen: '2026-07-14T12:00:00.000Z',
  typical_burst_ms: 85,
  recurrence_interval_s: 300,
  confidence: 0.87,
  status: 'active',
  fingerprint: null,
};

afterEach(() => {
  cleanup();
  useStore.setState({ channels: new Map(), lease: { operatorClientId: null, leaseExpires: null } });
});

describe('Channels table', () => {
  it('renders every contract column header', () => {
    useStore.getState().setChannels([CHANNEL]);
    render(<Channels />);
    const headerText = screen
      .getAllByRole('columnheader')
      .map((th) => th.textContent ?? '')
      .join('|');
    for (const header of [
      'ID',
      'Center (MHz)',
      'Bandwidth',
      'Current',
      'Peak',
      'Avg',
      'SNR',
      'Obs',
      'First seen',
      'Last seen',
      'Burst',
      'Recurrence',
      'Conf.',
      'Status',
      'Actions',
    ]) {
      expect(headerText).toContain(header);
    }
  });

  it('renders a channel row with formatted values', () => {
    useStore.getState().setChannels([CHANNEL]);
    render(<Channels />);
    const row = screen.getByText('868.3000').closest('tr');
    expect(row).not.toBeNull();
    const cells = within(row as HTMLElement);
    expect(cells.getByText('868.3000')).toBeInTheDocument(); // center MHz
    expect(cells.getByText('25 kHz')).toBeInTheDocument(); // bandwidth
    expect(cells.getByText('18.3 dB')).toBeInTheDocument(); // SNR
    expect(cells.getByText('42')).toBeInTheDocument(); // obs count
    expect(cells.getByText('87%')).toBeInTheDocument(); // confidence
    expect(cells.getByText(/Active/i)).toBeInTheDocument(); // status badge
    expect(cells.getByRole('button', { name: /Focus/i })).toBeInTheDocument();
    expect(cells.getByRole('button', { name: /History/i })).toBeInTheDocument();
  });

  it('shows an empty state when there are no channels', () => {
    render(<Channels />);
    expect(screen.getByText(/No candidate channels detected yet/i)).toBeInTheDocument();
  });
});
