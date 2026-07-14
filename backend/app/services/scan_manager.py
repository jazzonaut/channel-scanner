"""Scan orchestrator -- the core of the backend.

Runs an async scan loop that, for each dwell:
  1. reads IQ from the SDR backend and computes a Welch PSD OFF the event loop
     (run_in_executor), so DSP never blocks the loop;
  2. tracks the noise floor, detects occupied regions, clusters them into
     candidate channels, and updates recurrence/fingerprint stats;
  3. persists sessions, detections and channels;
  4. pushes throttled, reduced spectrum frames plus reliable channel/event
     updates to the websocket hub, with bounded queues and backpressure.

Supports sweep mode (step across the band) and focus mode (park on one span).
Only REDUCED spectrum frames go to browsers -- never raw IQ.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import structlog

from ..config import Settings
from ..models import schemas
from ..sdr.base import SdrBackend
from ..sdr.factory import create_backend
from ..signal_processing import psd as psd_mod
from ..signal_processing.clustering import ChannelClusterer
from ..signal_processing.detector import detect_regions
from ..signal_processing.fingerprint import build_fingerprint
from ..signal_processing.noise_floor import NoiseFloorEstimator
from ..signal_processing.recurrence import RecurrenceTracker
from ..storage.repositories import Repositories
from ..utils import iso_now, utcnow
from ..websocket.manager import ConnectionManager
from .control_lease import ControlLease

log = structlog.get_logger(__name__)

_MAX_DWELL_SAMPLES = 262_144  # cap IQ block size to bound memory/CPU per dwell


@dataclass
class ScanMetrics:
    fft_rate_hz: float = 0.0
    dropped_frames: int = 0
    scan_progress: float = 0.0
    queue_depth: int = 0
    _fft_times: deque[float] = field(default_factory=lambda: deque(maxlen=64))

    def record_fft(self) -> None:
        self._fft_times.append(time.monotonic())
        if len(self._fft_times) >= 2:
            span = self._fft_times[-1] - self._fft_times[0]
            self.fft_rate_hz = round((len(self._fft_times) - 1) / span, 3) if span > 0 else 0.0


class ScanManager:
    """Owns SDR, DSP pipeline, persistence and live broadcasting."""

    def __init__(
        self,
        settings: Settings,
        repos: Repositories,
        ws: ConnectionManager,
        lease: ControlLease,
    ) -> None:
        self._settings = settings
        self._repos = repos
        self._ws = ws
        self._lease = lease

        self._backend: SdrBackend | None = None
        self._config = self._initial_config(settings)
        self._version = 1

        self._scanning = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._session_id: int | None = None

        self._mode = "sweep"  # or "focus"
        self._focus_center: int | None = None
        self._focus_span: int | None = None
        self._sweep_pos: int = settings.scan_start_hz

        self._noise = NoiseFloorEstimator(alpha=settings.noise_floor_alpha)
        self._clusterer = ChannelClusterer(proximity_hz=self._proximity_hz())
        self._recurrence: dict[int, RecurrenceTracker] = {}
        self._last_persist: dict[int, float] = {}
        self._channel_db_id: dict[int, int] = {}

        self.metrics = ScanMetrics()
        self._last_spectrum_emit = 0.0
        self._last_snapshot_emit = 0.0

    # ------------------------------------------------------------------ config
    @staticmethod
    def _initial_config(s: Settings) -> schemas.ScanConfig:
        return schemas.ScanConfig(
            start_hz=s.scan_start_hz,
            end_hz=s.scan_end_hz,
            step_hz=s.scan_step_hz,
            sample_rate=s.sdr_sample_rate,
            gain=s.sdr_gain,
            ppm=s.sdr_ppm,
            dwell_ms=s.scan_dwell_ms,
            threshold_db=s.detection_threshold_db,
            noise_floor_alpha=s.noise_floor_alpha,
            exclusions=[],
            known_channel_widths_hz=[],
            fft_size=s.fft_size,
            backend=s.sdr_backend,
            simulation=s.effective_simulation(),
        )

    def _proximity_hz(self) -> int:
        widths = self._config.known_channel_widths_hz
        if widths:
            return max(5_000, int(min(widths) / 2))
        return 25_000

    @property
    def config(self) -> schemas.ScanConfig:
        return self._config

    @property
    def version(self) -> int:
        return self._version

    @property
    def scanning(self) -> bool:
        return self._scanning

    @property
    def backend(self) -> SdrBackend | None:
        return self._backend

    def config_dict(self) -> dict:
        return self._config.model_dump(mode="json")

    def device_info(self) -> dict:
        if self._backend is None:
            return {
                "backend": self._config.backend,
                "name": "uninitialized",
                "index": 0,
                "available": False,
                "simulation": self._config.simulation,
                "tuner": "none",
                "gains": [],
                "sample_rates": [],
                "freq_range_hz": [0, 0],
            }
        return self._backend.get_info().to_dict()

    # ------------------------------------------------------------- lifecycle
    async def startup(self) -> None:
        self._backend = create_backend(self._settings)
        self._backend.open()
        # Reconcile config.simulation with the backend that was actually chosen.
        info = self._backend.get_info()
        self._config = self._config.model_copy(
            update={"backend": info.backend, "simulation": info.simulation}
        )
        # Load persisted config version if present.
        latest = await self._repos.receiver_config.latest()
        if latest is not None:
            self._version = latest[0]
        await self._emit_event("startup", f"backend={info.backend} simulation={info.simulation}")
        log.info("scan_manager.startup", backend=info.backend, simulation=info.simulation)

    async def shutdown(self) -> None:
        await self.stop_scan()
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        log.info("scan_manager.shutdown")

    # -------------------------------------------------------------- controls
    async def start_scan(self) -> int:
        if self._scanning:
            assert self._session_id is not None
            return self._session_id
        if self._backend is None:
            await self.startup()
        assert self._backend is not None

        self._noise.reset()
        self._stop_event.clear()
        self._sweep_pos = self._config.start_hz
        self._mode = "sweep"

        self._session_id = await self._repos.sessions.create(
            started_at=iso_now(),
            start_hz=self._config.start_hz,
            end_hz=self._config.end_hz,
            backend=self._config.backend,
            simulation=self._config.simulation,
        )
        self._scanning = True
        self._task = asyncio.create_task(self._run(), name="scan-loop")
        await self._emit_event(
            "scan_start", f"session={self._session_id}", data={"session_id": self._session_id}
        )
        log.info("scan.start", session_id=self._session_id)
        return self._session_id

    async def stop_scan(self) -> None:
        if not self._scanning:
            return
        self._scanning = False
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        if self._session_id is not None:
            await self._repos.sessions.stop(self._session_id, iso_now())
        await self._emit_event("scan_stop", f"session={self._session_id}")
        log.info("scan.stop", session_id=self._session_id)

    async def focus(self, center_hz: int, span_hz: int | None, channel_id: int | None) -> None:
        self._mode = "focus"
        self._focus_center = int(center_hz)
        self._focus_span = int(span_hz) if span_hz else self._config.sample_rate
        await self._emit_event(
            "focus",
            f"center={center_hz} span={self._focus_span}",
            data={"center_hz": center_hz, "span_hz": self._focus_span, "channel_id": channel_id},
        )
        log.info("scan.focus", center_hz=center_hz, span_hz=self._focus_span)

    async def unfocus(self) -> None:
        self._mode = "sweep"
        self._focus_center = None
        self._focus_span = None

    # ------------------------------------------------------- config mutation
    async def update_config(
        self, update: schemas.ScanConfigUpdate, *, client_id: str
    ) -> schemas.ScanConfig:
        """Apply a validated partial config update, bump version, persist, notify."""
        merged = self._config.model_dump()
        for key, value in update.model_dump(exclude_unset=True).items():
            merged[key] = value
        new_config = schemas.ScanConfig(**merged)  # re-validates ranges

        self._config = new_config
        self._version += 1
        self._noise = NoiseFloorEstimator(alpha=new_config.noise_floor_alpha)
        self._clusterer = ChannelClusterer(proximity_hz=self._proximity_hz())

        if self._backend is not None:
            self._backend.set_sample_rate(new_config.sample_rate)
            self._backend.set_gain("auto" if new_config.gain == "auto" else float(new_config.gain))
            self._backend.set_ppm(new_config.ppm)

        config_json = new_config.model_dump_json()
        await self._repos.config_changes.record(
            timestamp=iso_now(),
            version=self._version,
            client_id=client_id,
            config_json=config_json,
        )
        await self._repos.receiver_config.save(
            version=self._version,
            config_json=config_json,
            updated_at=iso_now(),
            changed_by=client_id,
        )
        await self._emit_event(
            "config_change",
            f"version={self._version}",
            client_id=client_id,
            data={"version": self._version},
        )
        self._ws.broadcast_config(self.config_dict(), self._version, client_id)
        log.info("config.updated", version=self._version, client_id=client_id)
        return new_config

    # ------------------------------------------------------------- scan loop
    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        assert self._backend is not None
        try:
            while not self._stop_event.is_set():
                center = self._current_center()
                span = self._current_span()
                n = self._dwell_samples()

                # Read IQ + compute PSD OFF the event loop.
                try:
                    result = await loop.run_in_executor(None, self._read_and_psd, center, n)
                except Exception as exc:  # noqa: BLE001
                    log.warning("scan.dsp_error", error=str(exc))
                    await asyncio.sleep(0.05)
                    continue

                freqs, power_db = result
                self.metrics.record_fft()

                floor = self._noise.update(power_db)
                await self._process_frame(freqs, power_db, floor, center, span)

                # Advance sweep position.
                if self._mode == "sweep":
                    self._advance_sweep(span)

                self.metrics.queue_depth = self._ws.total_queue_depth()
                self.metrics.dropped_frames = self._ws.total_dropped_frames()

                # Cooperative yield; keeps CPU reasonable in sim.
                await asyncio.sleep(0)
                if self._settings.effective_simulation():
                    await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("scan.loop_crashed", error=str(exc))
            await self._emit_event("error", f"scan loop crashed: {exc}")
        finally:
            log.info("scan.loop_exit")

    def _read_and_psd(self, center: int, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Blocking: runs in executor thread. Returns (freqs_hz, power_db)."""
        assert self._backend is not None
        self._backend.set_center_freq(center)
        iq = self._backend.read_iq(n)
        result = psd_mod.compute_psd(
            iq,
            center_hz=center,
            sample_rate=self._config.sample_rate,
            fft_size=self._config.fft_size,
        )
        return result.freqs_hz, result.power_db

    async def _process_frame(
        self,
        freqs: np.ndarray,
        power_db: np.ndarray,
        floor: float,
        center: int,
        span: int,
    ) -> None:
        # Apply exclusion mask (mark excluded bins as floor so no detection).
        if self._config.exclusions:
            for lo, hi in self._config.exclusions:
                mask = (freqs >= lo) & (freqs <= hi)
                power_db = np.where(mask, floor - 1.0, power_db)

        regions = detect_regions(
            freqs,
            power_db,
            noise_floor_db=floor,
            threshold_db=self._config.threshold_db,
            merge_gap_hz=self._config.sample_rate / self._config.fft_size * 3,
        )

        now = time.monotonic()
        ts = iso_now()
        for region in regions:
            state = self._clusterer.ingest(region, ts)
            tracker = self._recurrence.setdefault(state.id, RecurrenceTracker(gap_seconds=1.0))
            tracker.add(utcnow().timestamp())

            # Throttle per-channel detection persistence.
            interval = max(self._config.dwell_ms / 1000.0, 0.2)
            if now - self._last_persist.get(state.id, 0.0) >= interval:
                self._last_persist[state.id] = now
                await self._persist_detection(region, state.id, ts)
                await self._upsert_and_broadcast_channel(state, tracker, floor)

        # Throttled spectrum frame (reduced bins only).
        self._maybe_emit_spectrum(freqs, power_db, floor, center, span)
        # Periodic full channel snapshot.
        await self._maybe_emit_snapshot()

    async def _persist_detection(self, region, channel_id: int, ts: str) -> None:  # noqa: ANN001
        if self._session_id is None:
            return
        db_channel_id = self._channel_db_id.get(channel_id)
        detection = schemas.Detection(
            id=0,
            channel_id=db_channel_id,
            session_id=self._session_id,
            timestamp=ts,
            center_hz=region.center_hz,
            bandwidth_hz=region.bandwidth_hz,
            peak_power_db=region.peak_power_db,
            avg_power_db=region.avg_power_db,
            snr_db=region.snr_db,
            duration_ms=None,
        )
        await self._repos.detections.create(detection)

    async def _upsert_and_broadcast_channel(self, state, tracker, floor: float) -> None:  # noqa: ANN001
        rec = tracker.stats()
        model = self._state_to_model(state, rec, floor)
        db_id = await self._repos.channels.upsert(model)
        self._channel_db_id[state.id] = db_id
        model = model.model_copy(update={"id": db_id})
        self._ws.broadcast_channel_update(model.model_dump(mode="json"))

    def _state_to_model(self, state, rec, floor: float) -> schemas.CandidateChannel:  # noqa: ANN001
        # Confidence blends observation count and recurrence regularity.
        obs_conf = min(1.0, state.observation_count / 20.0)
        reg_conf = 0.0
        if rec.recurrence_interval_s and rec.interval_jitter_s is not None:
            jitter_ratio = rec.interval_jitter_s / max(rec.recurrence_interval_s, 1e-6)
            reg_conf = max(0.0, 1.0 - min(1.0, jitter_ratio))
        confidence = round(min(1.0, 0.6 * obs_conf + 0.4 * reg_conf + 0.05), 4)

        status = self._status_for(state)
        fp = build_fingerprint(
            center_hz=state.center_hz,
            bandwidth_hz=state.bandwidth_hz,
            duration_ms=rec.typical_burst_ms or float(self._config.dwell_ms),
            peak_power_db=state.peak_power_db,
            noise_floor_db=floor,
            repetition_interval_s=rec.recurrence_interval_s,
        )
        db_id = self._channel_db_id.get(state.id, state.id)
        return schemas.CandidateChannel(
            id=db_id,
            center_hz=state.center_hz,
            bandwidth_hz=state.bandwidth_hz,
            current_power_db=state.current_power_db,
            peak_power_db=state.peak_power_db,
            avg_power_db=state.avg_power_db,
            snr_db=state.snr_db,
            observation_count=state.observation_count,
            first_seen=state.first_seen_ts or iso_now(),
            last_seen=state.last_seen_ts or iso_now(),
            typical_burst_ms=rec.typical_burst_ms,
            recurrence_interval_s=rec.recurrence_interval_s,
            confidence=confidence,
            status=status,
            fingerprint=schemas.Fingerprint(**fp.to_dict()),
        )

    @staticmethod
    def _status_for(state) -> str:  # noqa: ANN001
        from datetime import datetime

        if not state.last_seen_ts:
            return "inactive"
        try:
            last = datetime.fromisoformat(state.last_seen_ts.replace("Z", "+00:00"))
        except ValueError:
            return "active"
        age = (utcnow() - last).total_seconds()
        if age <= 3.0:
            return "active"
        if age <= 30.0:
            return "recently_active"
        return "inactive"

    def _maybe_emit_spectrum(
        self, freqs: np.ndarray, power_db: np.ndarray, floor: float, center: int, span: int
    ) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(1, self._settings.spectrum_fps)
        if now - self._last_spectrum_emit < min_interval:
            return
        self._last_spectrum_emit = now

        reduced = psd_mod.reduce_bins(power_db, self._settings.spectrum_bins)
        payload = {
            "session_id": self._session_id,
            "timestamp": iso_now(),
            "f_start_hz": int(freqs[0]),
            "f_stop_hz": int(freqs[-1]),
            "bin_count": int(reduced.shape[0]),
            "power_db": [round(float(x), 2) for x in reduced.tolist()],
            "noise_floor_db": round(float(floor), 2),
            "scan_pos_hz": int(center),
        }
        self._ws.broadcast_spectrum(payload)

    async def _maybe_emit_snapshot(self) -> None:
        now = time.monotonic()
        if now - self._last_snapshot_emit < 1.0:
            return
        self._last_snapshot_emit = now
        self._clusterer.merge_overlapping()
        channels = await self._repos.channels.list()
        self._ws.broadcast_channels([c.model_dump(mode="json") for c in channels])
        # Update scan progress metric.
        span_total = max(1, self._config.end_hz - self._config.start_hz)
        pos = self._sweep_pos - self._config.start_hz
        self.metrics.scan_progress = round(min(1.0, max(0.0, pos / span_total)), 4)

    # ------------------------------------------------------------ sweep math
    def _current_center(self) -> int:
        if self._mode == "focus" and self._focus_center is not None:
            return self._focus_center
        return self._sweep_pos

    def _current_span(self) -> int:
        if self._mode == "focus" and self._focus_span is not None:
            return min(self._focus_span, self._config.sample_rate)
        return self._config.sample_rate

    def _step_hz(self, span: int) -> int:
        if self._config.step_hz > 0:
            return self._config.step_hz
        # Auto: 80% of the window to allow overlap at edges.
        return max(1, int(span * 0.8))

    def _advance_sweep(self, span: int) -> None:
        step = self._step_hz(span)
        self._sweep_pos += step
        if self._sweep_pos + span // 2 >= self._config.end_hz:
            self._sweep_pos = self._config.start_hz + span // 2
            if self._sweep_pos >= self._config.end_hz:
                self._sweep_pos = self._config.start_hz

    def _dwell_samples(self) -> int:
        n = int(self._config.sample_rate * self._config.dwell_ms / 1000.0)
        n = max(self._config.fft_size, n)
        return min(n, _MAX_DWELL_SAMPLES)

    # --------------------------------------------------------------- events
    async def _emit_event(
        self, kind: str, message: str, *, client_id: str | None = None, data: dict | None = None
    ) -> None:
        event_id = await self._repos.events.create(
            timestamp=iso_now(), kind=kind, message=message, client_id=client_id, data=data
        )
        event = schemas.Event(
            id=event_id,
            timestamp=iso_now(),
            kind=kind,
            message=message,
            client_id=client_id,
            data=data,
        )
        self._ws.broadcast_event(event.model_dump(mode="json"))

    # -------------------------------------------------------------- metrics
    async def metrics_dict(self) -> dict:
        db_size = await self._repos.db.db_size_bytes()
        rec_bytes = await self._repos.recordings.total_bytes()
        return {
            "fft_rate_hz": self.metrics.fft_rate_hz,
            "ws_clients": self._ws.client_count,
            "queue_depth": self._ws.total_queue_depth(),
            "dropped_frames": self._ws.total_dropped_frames(),
            "scan_progress": self.metrics.scan_progress,
            "db_size_bytes": db_size,
            "recording_bytes": rec_bytes,
        }
