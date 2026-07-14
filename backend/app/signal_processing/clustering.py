"""Cluster repeated detections into stable candidate channels.

Detections from many frames are grouped by center-frequency proximity into
candidate channels with stable integer IDs. Each channel keeps running power
statistics and observation counts. Two channels whose centers drift within
tolerance of each other are merged.

A "candidate channel" is an inferred recurring occupied region, not an official
protocol channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .detector import SignalRegion


@dataclass
class CandidateChannelState:
    """Mutable accumulator for one clustered candidate channel."""

    id: int
    center_hz: int
    bandwidth_hz: int
    peak_power_db: float
    avg_power_db: float
    current_power_db: float
    snr_db: float
    observation_count: int = 0
    first_seen_ts: str | None = None
    last_seen_ts: str | None = None
    # Exponential weights for smoothing running stats.
    _center_accum: float = field(default=0.0, repr=False)
    _bw_accum: float = field(default=0.0, repr=False)

    def match_distance_hz(self, region: SignalRegion) -> int:
        return abs(self.center_hz - region.center_hz)


class ChannelClusterer:
    """Assigns detections to candidate channels by center-freq proximity.

    Args:
        proximity_hz: max center-frequency distance to consider a match. If a
            detection is farther than this from every existing channel, a new
            channel is created.
        power_alpha: EMA factor for current/avg power smoothing.
        center_alpha: EMA factor for center-frequency drift tracking.
    """

    def __init__(
        self,
        *,
        proximity_hz: int = 25_000,
        power_alpha: float = 0.2,
        center_alpha: float = 0.1,
    ) -> None:
        self.proximity_hz = int(proximity_hz)
        self.power_alpha = float(power_alpha)
        self.center_alpha = float(center_alpha)
        self._channels: dict[int, CandidateChannelState] = {}
        self._next_id = 1

    @property
    def channels(self) -> list[CandidateChannelState]:
        return list(self._channels.values())

    def get(self, channel_id: int) -> CandidateChannelState | None:
        return self._channels.get(channel_id)

    def _nearest(self, region: SignalRegion) -> CandidateChannelState | None:
        best: CandidateChannelState | None = None
        best_d = self.proximity_hz + 1
        for ch in self._channels.values():
            d = ch.match_distance_hz(region)
            if d < best_d:
                best_d = d
                best = ch
        if best is not None and best_d <= self.proximity_hz:
            return best
        return None

    def ingest(self, region: SignalRegion, timestamp: str) -> CandidateChannelState:
        """Assign a detection to a channel (creating one if needed).

        Returns the channel state that absorbed the detection.
        """
        ch = self._nearest(region)
        if ch is None:
            ch = CandidateChannelState(
                id=self._next_id,
                center_hz=region.center_hz,
                bandwidth_hz=region.bandwidth_hz,
                peak_power_db=region.peak_power_db,
                avg_power_db=region.avg_power_db,
                current_power_db=region.peak_power_db,
                snr_db=region.snr_db,
                observation_count=1,
                first_seen_ts=timestamp,
                last_seen_ts=timestamp,
            )
            self._channels[ch.id] = ch
            self._next_id += 1
            return ch

        # Update existing channel with smoothed statistics.
        a = self.power_alpha
        ca = self.center_alpha
        ch.center_hz = int(round((1 - ca) * ch.center_hz + ca * region.center_hz))
        ch.bandwidth_hz = int(round((1 - ca) * ch.bandwidth_hz + ca * region.bandwidth_hz))
        ch.current_power_db = round(region.peak_power_db, 3)
        ch.avg_power_db = round((1 - a) * ch.avg_power_db + a * region.avg_power_db, 3)
        ch.peak_power_db = round(max(ch.peak_power_db, region.peak_power_db), 3)
        ch.snr_db = round((1 - a) * ch.snr_db + a * region.snr_db, 3)
        ch.observation_count += 1
        ch.last_seen_ts = timestamp
        return ch

    def merge_overlapping(self) -> None:
        """Merge channels whose centers drifted within proximity of each other."""
        ids = sorted(self._channels.keys())
        for i in ids:
            a = self._channels.get(i)
            if a is None:
                continue
            for j in ids:
                if j <= i:
                    continue
                b = self._channels.get(j)
                if b is None:
                    continue
                if abs(a.center_hz - b.center_hz) <= self.proximity_hz:
                    # Merge b into a (keep lower id for stability).
                    total = a.observation_count + b.observation_count or 1
                    a.center_hz = int(
                        round(
                            (a.center_hz * a.observation_count + b.center_hz * b.observation_count)
                            / total
                        )
                    )
                    a.bandwidth_hz = max(a.bandwidth_hz, b.bandwidth_hz)
                    a.peak_power_db = max(a.peak_power_db, b.peak_power_db)
                    a.avg_power_db = round((a.avg_power_db + b.avg_power_db) / 2.0, 3)
                    a.snr_db = max(a.snr_db, b.snr_db)
                    a.observation_count = total
                    if b.first_seen_ts and (
                        a.first_seen_ts is None or b.first_seen_ts < a.first_seen_ts
                    ):
                        a.first_seen_ts = b.first_seen_ts
                    if b.last_seen_ts and (
                        a.last_seen_ts is None or b.last_seen_ts > a.last_seen_ts
                    ):
                        a.last_seen_ts = b.last_seen_ts
                    del self._channels[j]
