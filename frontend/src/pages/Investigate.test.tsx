import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { CandidateChannel } from '../lib/types';

const startScan = vi.fn();
const stopScan = vi.fn();
const focus = vi.fn();
const runDecoder = vi.fn();
const getWavenisStatus = vi.fn();

vi.mock('../lib/api', () => ({
  api: {
    startScan: () => startScan(),
    stopScan: () => stopScan(),
    focus: (centerHz: number) => focus(centerHz),
    runDecoder: () => runDecoder(),
    getWavenisStatus: () => getWavenisStatus(),
  },
  ApiError: class ApiError extends Error {},
}));

// Imported after vi.mock so the mocked api is wired up.
import { Investigate } from './Investigate';
import { useStore } from '../store/store';

function makeChannel(overrides: Partial<CandidateChannel> = {}): CandidateChannel {
  return {
    id: 1,
    center_hz: 868_300_000,
    bandwidth_hz: 12_500,
    current_power_db: -12,
    peak_power_db: -6,
    avg_power_db: -15,
    snr_db: 18,
    observation_count: 12,
    first_seen: '2026-07-14T10:00:00.000Z',
    last_seen: '2026-07-14T12:00:00.000Z',
    typical_burst_ms: 80,
    recurrence_interval_s: 300,
    confidence: 0.8,
    status: 'active',
    fingerprint: null,
    ...overrides,
  };
}

function renderInvestigate(): void {
  render(
    <MemoryRouter>
      <Investigate />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  startScan.mockReset();
  stopScan.mockReset();
  focus.mockReset();
  runDecoder.mockReset();
  getWavenisStatus.mockReset();
  getWavenisStatus.mockImplementation(() => new Promise(() => {}));
  useStore.getState().setChannels([]);
  useStore.getState().setScanning(false);
});

afterEach(() => {
  cleanup();
  useStore.getState().setChannels([]);
  useStore.getState().setScanning(false);
});

describe('Investigate page', () => {
  it('renders all five numbered steps', () => {
    renderInvestigate();
    expect(
      screen.getByRole('heading', { name: /Set conservative near-device settings/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Start a survey/i })).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /Shortlist by pattern & cadence/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Inspect in the scope/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Try to decode/i })).toBeInTheDocument();
  });

  it('shows the candidate empty state with no channels', () => {
    renderInvestigate();
    expect(screen.getByText(/No candidate channels yet/i)).toBeInTheDocument();
  });

  it('previews the top candidate and focuses it', async () => {
    focus.mockResolvedValue({ ok: true });
    useStore.getState().setChannels([makeChannel()]);
    renderInvestigate();
    expect(screen.getByText('868.3000 MHz')).toBeInTheDocument();
    expect(screen.getByText('strong')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Focus' }));
    expect(focus).toHaveBeenCalledWith(868_300_000);
  });

  it('starts a survey and optimistically flips the scanning state', async () => {
    startScan.mockResolvedValue({ ok: true, session_id: 1 });
    renderInvestigate();
    const button = screen.getByRole('button', { name: /Start survey/i });
    await userEvent.click(button);
    expect(startScan).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(useStore.getState().scanning).toBe(true));
  });

  it('runs the decoder and shows its message', async () => {
    runDecoder.mockResolvedValue({ ok: true, ran: true, message: 'Decoder ran', decodes: [] });
    renderInvestigate();
    await userEvent.click(screen.getByRole('button', { name: /Run decoder/i }));
    expect(await screen.findByText('Decoder ran')).toBeInTheDocument();
  });

  it('shows when the Wavenis profile is required', async () => {
    getWavenisStatus.mockResolvedValue({
      configured: false,
      active: false,
      message: 'apply preset',
      center_hz: 868_269_000,
      receiver_center_hz: 868_500_000,
      sample_rate: 2_400_000,
      grid_hz: [],
      threshold_db: 12,
      frame_ms: null,
      frames_processed: 0,
      channels: [],
      recent_bursts: [],
    });
    renderInvestigate();
    expect(await screen.findByText('Wavenis 868 wideband evidence')).toBeInTheDocument();
    expect(screen.getByText('Apply Wavenis 868 preset')).toBeInTheDocument();
  });
});
