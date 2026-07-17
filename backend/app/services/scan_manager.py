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
from ..sdr.factory import BackendSelection, create_backend
from ..signal_processing import psd as psd_mod
from ..signal_processing.clustering import ChannelClusterer
from ..signal_processing.detector import detect_regions
from ..signal_processing.fingerprint import build_fingerprint
from ..signal_processing.modulation import (
    ModulationEstimate,
    estimate_modulation,
    isolate_and_decimate,
)
from ..signal_processing.noise_floor import NoiseFloorEstimator
from ..signal_processing.recurrence import RecurrenceTracker
from ..signal_processing.wavenis import (
    WAVENIS_CHANNELS_HZ,
    WavenisBurst,
    WavenisWidebandAnalyzer,
    observable_center_hz,
)
from ..storage.repositories import Repositories
from ..utils import iso_now, utcnow
from ..websocket.manager import ConnectionManager
from .candidate_log import CandidateLog
from .control_lease import ControlLease
from .decoder import DecodedMessage, ReceiveOnlyDecoder
from .iq_stream import ContinuousIqStream
from .recorder import Recorder
from .retention import RetentionService
from .triggered_capture import TriggeredCapture, TriggeredCaptureBuffer

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

        # Set post-construction via attach_services() to avoid ctor ordering
        # coupling; update_config() propagates runtime settings to them.
        self._recorder: Recorder | None = None
        self._retention: RetentionService | None = None
        self._decoder: ReceiveOnlyDecoder | None = None
        self._last_decode_emit = 0.0
        self._decode_counter = 0
        self._last_mod_calc = 0.0
        # Sticky last confident modulation hint (bursty signals classify only when
        # a burst is caught; keep the last known so the UI doesn't flap to unknown).
        self._last_modulation: ModulationEstimate | None = None

        self._scanning = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._session_id: int | None = None

        self._mode = "sweep"  # or "focus"
        self._focus_center: int | None = None
        self._focus_span: int | None = None
        # Sweep plan: a precomputed list of window centre frequencies that tiles
        # the configured band. The tuner cycles through these; this guarantees
        # the whole band is covered every pass (a single incrementing position
        # can stall when the auto step overshoots the band edge).
        self._sweep_centers: list[int] = []
        self._sweep_idx: int = 0

        self._noise = NoiseFloorEstimator(alpha=settings.noise_floor_alpha)
        self._clusterer = ChannelClusterer(proximity_hz=self._proximity_hz())
        self._recurrence: dict[int, RecurrenceTracker] = {}
        self._last_persist: dict[int, float] = {}
        self._channel_db_id: dict[int, int] = {}

        self.metrics = ScanMetrics()
        self._last_spectrum_emit = 0.0
        self._last_snapshot_emit = 0.0
        self._last_scope_emit = 0.0
        self._scope_seq = 0

        # Stitched full-band spectrum. A swept receiver only sees one window at a
        # time, so we keep a persistent power buffer spanning the whole band and
        # refresh each segment as the sweep passes over it. The browser then
        # always renders the entire band rather than a single aliased window.
        self._band_freqs: np.ndarray | None = None
        self._band_power: np.ndarray | None = None
        self._band_floor: float = -120.0

        # Dedicated evidence path for the 15-channel Wavenis grid. It is active
        # only when the configured band fits inside one instantaneous RTL-SDR
        # window, so hopping channels are observed continuously rather than by
        # a tuner sweep.
        self._wavenis = WavenisWidebandAnalyzer()
        # Durable, uncapped candidate record on disk; survives restart/reboot.
        self._candidate_log = CandidateLog(settings.logs_dir())
        self._iq_stream: ContinuousIqStream | None = None
        self._last_stream_status: dict[str, object] | None = None
        self._expected_stream_sample: int | None = None
        self._trigger_capture = TriggeredCaptureBuffer(self._config.sample_rate)
        self._polled_blocks = 0
        self._polled_samples = 0
        self._retunes = 0

        # Set when the operator asked for real hardware but the factory had to
        # fall back to the simulator. Surfaced via the health check so a silent
        # sim fallback cannot masquerade as a real capture.
        self._hardware_degraded = False
        self._hardware_reason: str | None = None

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
            device_index=s.sdr_device_index,
            spectrum_fps=s.spectrum_fps,
            spectrum_bins=s.spectrum_bins,
            enable_iq_recording=s.enable_iq_recording,
            max_iq_storage_gb=s.max_iq_storage_gb,
            retention_days=s.retention_days,
        )

    def attach_services(
        self,
        recorder: Recorder,
        retention: RetentionService,
        decoder: ReceiveOnlyDecoder | None = None,
    ) -> None:
        """Wire in services that receive runtime config updates / decoder runs."""
        self._recorder = recorder
        self._retention = retention
        self._decoder = decoder

    async def _reconfigure_backend(self) -> None:
        """Re-open the SDR backend after a receiver/device/sim change.

        Restarts an active scan around the swap. On failure the factory falls
        back to the simulator; the actual backend/simulation are reconciled back
        into the live config so the UI reflects reality.
        """
        was_scanning = self._scanning
        if was_scanning:
            await self.stop_scan()
        if self._backend is not None:
            try:
                self._backend.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("scan.backend_close_error", error=str(exc))
            self._backend = None

        eff = self._settings.model_copy(
            update={
                "sdr_backend": self._config.backend,
                "sdr_device_index": self._config.device_index,
                "simulation_mode": self._config.simulation,
                "sdr_sample_rate": self._config.sample_rate,
                "sdr_gain": self._config.gain,
                "sdr_ppm": self._config.ppm,
                "scan_start_hz": self._config.start_hz,
                "scan_end_hz": self._config.end_hz,
            }
        )
        sel = create_backend(eff)
        await self._activate_selection(sel, event_type="backend_reconfigured")
        if was_scanning:
            await self.start_scan()

    async def _activate_selection(
        self, sel: BackendSelection, *, event_type: str
    ) -> None:
        """Open the selected backend, reconcile config, and flag HW degradation.

        Shared by startup and runtime reconfigure so both paths surface a silent
        sim fallback identically: a warning event plus a sticky degraded flag the
        health check reads. Without this, an operator who set SIMULATION_MODE=false
        could collect days of synthetic data believing it was a real capture.
        """
        self._backend = sel.backend
        self._backend.open()
        info = self._backend.get_info()
        # Reconcile with the backend actually opened (factory may have fallen back).
        self._config = self._config.model_copy(
            update={"backend": info.backend, "simulation": info.simulation}
        )
        self._hardware_degraded = sel.degraded
        self._hardware_reason = sel.reason if sel.degraded else None
        await self._emit_event(
            event_type,
            f"backend={info.backend} simulation={info.simulation}",
            data={"backend": info.backend, "simulation": info.simulation},
        )
        log.info(f"scan_manager.{event_type}", backend=info.backend, simulation=info.simulation)
        if sel.degraded:
            await self._emit_event(
                "sdr_hardware_unavailable",
                f"requested {sel.requested!r} unavailable; running SIMULATION instead: "
                f"{sel.reason}",
                data={"requested": sel.requested, "reason": sel.reason},
            )
            log.error("sdr.hardware_unavailable", requested=sel.requested, reason=sel.reason)

    def _proximity_hz(self) -> int:
        widths = self._config.known_channel_widths_hz
        if widths:
            return max(5_000, int(min(widths) / 2))
        # A single wide/structured signal is often detected as several regions a
        # few tens of kHz apart; 40 kHz collapses those into one channel while
        # keeping genuinely distinct 868-band emitters (typically >100 kHz apart)
        # separate. Override with known_channel_widths_hz for tighter grids.
        return 40_000

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
    def mode(self) -> str:
        return self._mode

    @property
    def focus_center_hz(self) -> int | None:
        return self._focus_center

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

    @property
    def hardware_degraded(self) -> bool:
        """True when hardware was requested but the backend fell back to sim."""
        return self._hardware_degraded

    @property
    def hardware_reason(self) -> str | None:
        return self._hardware_reason

    # ------------------------------------------------------------- lifecycle
    async def startup(self) -> None:
        sel = create_backend(self._settings)
        # Load persisted config version if present.
        latest = await self._repos.receiver_config.latest()
        if latest is not None:
            self._version = latest[0]
        await self._activate_selection(sel, event_type="startup")

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
        self._wavenis.reset()
        self._trigger_capture = TriggeredCaptureBuffer(self._config.sample_rate)
        self._expected_stream_sample = None
        self._last_stream_status = None
        self._polled_blocks = 0
        self._polled_samples = 0
        self._retunes = 0
        self._stop_event.clear()
        self._compute_sweep_plan()
        self._reset_band_buffer()
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
        await self._broadcast_status()  # push new scanning state to all clients now
        return self._session_id

    async def stop_scan(self) -> None:
        if not self._scanning:
            return
        self._scanning = False
        self._stop_event.set()
        if self._iq_stream is not None:
            self._last_stream_status = dict(self._iq_stream.snapshot())
            self._iq_stream.stop()
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
        await self._broadcast_status()  # push idle state to all clients now

    async def focus(self, center_hz: int, span_hz: int | None, channel_id: int | None) -> None:
        # Focus requires the scan loop running; start it if idle so the scope
        # works straight from the Channels/Scope page without a separate start.
        if not self._scanning:
            await self.start_scan()
        self._mode = "focus"
        self._focus_center = int(center_hz)
        self._focus_span = int(span_hz) if span_hz else self._config.sample_rate
        self._last_modulation = None  # clear stale hint for the previous centre
        await self._emit_event(
            "focus",
            f"center={center_hz} span={self._focus_span}",
            data={"center_hz": center_hz, "span_hz": self._focus_span, "channel_id": channel_id},
        )
        log.info("scan.focus", center_hz=center_hz, span_hz=self._focus_span)
        await self._broadcast_status()

    async def unfocus(self) -> None:
        self._mode = "sweep"
        self._focus_center = None
        self._focus_span = None
        await self._emit_event("sweep", "resumed sweep")
        await self._broadcast_status()

    async def clear_all_data(self) -> None:
        """Stop scanning, wipe persisted observations + recordings, and reset all
        in-memory detection state. The current scan configuration is preserved."""
        await self.stop_scan()
        # Reset in-memory detection state.
        self._clusterer = ChannelClusterer(proximity_hz=self._proximity_hz())
        self._recurrence.clear()
        self._channel_db_id.clear()
        self._last_persist.clear()
        self._session_id = None
        self._noise.reset()
        self._reset_band_buffer()
        self.metrics = ScanMetrics()
        self._wavenis.reset()
        # Wipe persisted rows, recording files, and the durable candidate log.
        await self._repos.clear_all_data()
        self._candidate_log.clear()
        removed = self._recorder.delete_all() if self._recorder is not None else 0
        await self._emit_event("data_cleared", f"all data cleared (recordings removed={removed})")
        self._ws.broadcast_channels([])
        await self._broadcast_status()
        log.info("data.cleared", recordings_removed=removed)

    # ------------------------------------------------------- config mutation
    async def update_config(
        self, update: schemas.ScanConfigUpdate, *, client_id: str
    ) -> schemas.ScanConfig:
        """Apply a validated partial config update, bump version, persist, notify."""
        prev = self._config
        merged = self._config.model_dump()
        for key, value in update.model_dump(exclude_unset=True).items():
            merged[key] = value
        new_config = schemas.ScanConfig(**merged)  # re-validates ranges

        acquisition_changed = any(
            getattr(new_config, field) != getattr(prev, field)
            for field in (
                "start_hz",
                "end_hz",
                "step_hz",
                "sample_rate",
                "gain",
                "ppm",
                "dwell_ms",
                "backend",
                "device_index",
                "simulation",
            )
        )
        restart_scan = self._scanning and acquisition_changed
        if restart_scan:
            await self.stop_scan()

        self._config = new_config
        self._version += 1
        self._noise = NoiseFloorEstimator(alpha=new_config.noise_floor_alpha)
        self._wavenis.reset()
        self._trigger_capture = TriggeredCaptureBuffer(new_config.sample_rate)
        self._clusterer = ChannelClusterer(proximity_hz=self._proximity_hz())
        self._compute_sweep_plan()  # band/step/sample-rate may have changed
        self._reset_band_buffer()

        # Switching receiver, device or sim/real requires re-opening the SDR
        # (the device is bound when opened). This restarts an active scan.
        if (
            new_config.backend != prev.backend
            or new_config.device_index != prev.device_index
            or new_config.simulation != prev.simulation
        ):
            await self._reconfigure_backend()
        elif self._backend is not None:
            self._backend.set_sample_rate(new_config.sample_rate)
            self._backend.set_gain("auto" if new_config.gain == "auto" else float(new_config.gain))
            self._backend.set_ppm(new_config.ppm)

        # Propagate recording + retention governance to their services.
        if self._recorder is not None:
            self._recorder.apply_config(
                new_config.enable_iq_recording, new_config.max_iq_storage_gb
            )
        if self._retention is not None:
            self._retention.apply_config(new_config.retention_days)

        config_json = self._config.model_dump_json()
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
        if restart_scan:
            await self.start_scan()
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
                    if self._should_stream_continuously():
                        if self._iq_stream is None:
                            self._iq_stream = ContinuousIqStream(
                                self._backend,
                                center_hz=center,
                                sample_rate=self._config.sample_rate,
                                block_samples=n,
                            )
                            self._iq_stream.start()
                        block = await self._iq_stream.get()
                        if block is None:
                            if self._stop_event.is_set():
                                break
                            error = (
                                self._iq_stream.snapshot().get("error")
                                or "continuous SDR stream ended unexpectedly"
                            )
                            self._last_stream_status = dict(self._iq_stream.snapshot())
                            self._iq_stream.stop()
                            self._iq_stream = None
                            self._expected_stream_sample = None
                            raise RuntimeError(error)
                        if (
                            self._expected_stream_sample is not None
                            and block.start_sample != self._expected_stream_sample
                        ):
                            missing = max(0, block.start_sample - self._expected_stream_sample)
                            self._wavenis.discontinuity(missing)
                            self._trigger_capture.discontinuity()
                        self._expected_stream_sample = block.end_sample
                        iq = block.samples
                        result = await loop.run_in_executor(None, self._analyse_iq, iq, center)
                    else:
                        if self._iq_stream is not None:
                            self._last_stream_status = dict(self._iq_stream.snapshot())
                            self._iq_stream.stop()
                            self._iq_stream = None
                            self._expected_stream_sample = None
                        iq, *analysis = await loop.run_in_executor(
                            None, self._read_and_psd, center, n
                        )
                        result = tuple(analysis)
                except Exception as exc:  # noqa: BLE001
                    log.warning("scan.dsp_error", error=str(exc))
                    await asyncio.sleep(0.05)
                    continue

                freqs, power_db, envelope_db, modulation, wavenis_bursts = result
                if self._wavenis_profile_configured() and WavenisWidebandAnalyzer.can_observe(
                    center, self._config.sample_rate
                ):
                    self._trigger_capture.append(iq)
                self.metrics.record_fft()

                floor = self._noise.update(power_db)
                await self._process_frame(freqs, power_db, floor, center, span)
                for burst in wavenis_bursts:
                    # Record IQ and persist/announce only for auto-flagged
                    # candidates. Triggering on every qualified burst would keep
                    # the recorder firing almost continuously in a busy band (a
                    # dense neighbour is ~9/s), churning IQ storage until the
                    # rare meter capture we actually want is evicted -- and would
                    # flood the event DB over a multi-hour run. Routine qualified
                    # bursts still appear in the live view and snapshot.
                    if not burst.is_candidate:
                        continue
                    if self._recorder is not None and self._recorder.enabled:
                        self._trigger_capture.trigger(burst.to_dict())
                    await self._record_candidate(burst)
                capture = self._trigger_capture.pop_ready()
                if capture is not None and self._recorder is not None and self._recorder.enabled:
                    await self._save_triggered_capture(capture, center)
                # Live scope: fine spectrogram + envelope of the focused window.
                if self._mode == "focus":
                    if modulation is not None and modulation["modulation"] != "unknown":
                        self._last_modulation = modulation
                    self._maybe_emit_scope(
                        freqs, power_db, envelope_db, floor, center, span, self._last_modulation
                    )

                # Simulated decoder output (real rtl_433 runs via run_decoder()).
                await self._maybe_emit_decode()

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
            if self._iq_stream is not None:
                self._last_stream_status = dict(self._iq_stream.snapshot())
                self._iq_stream.stop()
                self._iq_stream = None
            log.info("scan.loop_exit")

    def _read_and_psd(
        self, center: int, n: int
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        ModulationEstimate | None,
        list[WavenisBurst],
    ]:
        """Blocking: runs in executor thread. Returns IQ plus its analysis.

        envelope_db is the decimated |IQ| magnitude over the dwell, in dB, used for
        the time-domain amplitude strip in the live scope. modulation is a coarse
        OOK/FSK + symbol-rate hint computed from the raw IQ (focus mode only; None
        otherwise) so raw IQ never has to leave the backend.
        """
        assert self._backend is not None
        if self._backend.center_freq != center:
            self._backend.set_center_freq(center)
            self._retunes += 1
        iq = self._backend.read_iq(n)
        self._polled_blocks += 1
        self._polled_samples += int(iq.size)
        analysis = self._analyse_iq(iq, center)
        return iq, *analysis

    def _analyse_iq(
        self, iq: np.ndarray, center: int
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        ModulationEstimate | None,
        list[WavenisBurst],
    ]:
        """Run DSP for an already-acquired IQ block without touching the SDR."""
        wavenis_bursts: list[WavenisBurst] = []
        if self._wavenis_profile_configured() and WavenisWidebandAnalyzer.can_observe(
            center, self._config.sample_rate
        ):
            wavenis_bursts = self._wavenis.process(
                iq, center_hz=center, sample_rate=self._config.sample_rate
            )
        result = psd_mod.compute_psd(
            iq,
            center_hz=center,
            sample_rate=self._config.sample_rate,
            fft_size=self._config.fft_size,
        )
        # Time-domain envelope: decimate |IQ| to a fixed number of points.
        mag = np.abs(iq)
        k = max(16, int(self._settings.scope_envelope_points))
        if mag.size >= k:
            trim = (mag.size // k) * k
            env = mag[:trim].reshape(k, -1).mean(axis=1)
        else:
            env = mag
        env_db = 20.0 * np.log10(env + 1e-12)
        # Modulation hint: isolate the parked channel (band-limit around DC +
        # decimate) so we don't classify the whole wideband window, and throttle
        # to ~1/s since it needs an extra FFT. Estimated on a bounded slice.
        modulation: ModulationEstimate | None = None
        if self._mode == "focus":
            now_m = time.monotonic()
            if now_m - self._last_mod_calc >= 1.0:
                self._last_mod_calc = now_m
                seg = iq[:131072]
                iso, rate2 = isolate_and_decimate(seg, int(self._config.sample_rate), 60_000.0)
                modulation = estimate_modulation(iso, int(rate2))
        return result.freqs_hz, result.power_db, env_db, modulation, wavenis_bursts

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
            # Windows overscan the band edges to guarantee full coverage; only
            # report candidate channels whose centre falls within the requested
            # band so the results stay "within a band" as configured.
            if not (self._config.start_hz <= region.center_hz <= self._config.end_hz):
                continue
            state = self._clusterer.ingest(region, ts)
            tracker = self._recurrence.setdefault(state.id, RecurrenceTracker(gap_seconds=1.0))
            tracker.add(utcnow().timestamp())

            # Throttle per-channel detection persistence.
            interval = max(self._config.dwell_ms / 1000.0, 0.2)
            if now - self._last_persist.get(state.id, 0.0) >= interval:
                self._last_persist[state.id] = now
                await self._persist_detection(region, state.id, ts)
                await self._upsert_and_broadcast_channel(state, tracker, floor)

        # Refresh this window's segment of the stitched full-band spectrum,
        # then emit the whole band (throttled).
        self._stitch_into_band(freqs, power_db, floor)
        self._maybe_emit_spectrum(center, span)
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

    def _maybe_emit_spectrum(self, center: int, span: int) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(1, self._config.spectrum_fps)
        if now - self._last_spectrum_emit < min_interval:
            return
        self._last_spectrum_emit = now

        if self._band_freqs is None or self._band_power is None:
            self._reset_band_buffer()
        assert self._band_freqs is not None and self._band_power is not None

        payload = {
            "session_id": self._session_id,
            "timestamp": iso_now(),
            "f_start_hz": int(self._band_freqs[0]),
            "f_stop_hz": int(self._band_freqs[-1]),
            "bin_count": int(self._band_power.shape[0]),
            "power_db": [round(float(x), 2) for x in self._band_power.tolist()],
            "noise_floor_db": round(float(self._band_floor), 2),
            # Where the tuner is parked right now, so the UI can mark the live
            # scan window inside the full-band view.
            "scan_pos_hz": int(center),
            "window_start_hz": int(center - span // 2),
            "window_stop_hz": int(center + span // 2),
        }
        self._ws.broadcast_spectrum(payload)

    def _maybe_emit_scope(
        self,
        freqs: np.ndarray,
        power_db: np.ndarray,
        envelope_db: np.ndarray,
        floor: float,
        center: int,
        span: int,
        modulation: ModulationEstimate | None = None,
    ) -> None:
        """Emit one fine-resolution spectrogram row + amplitude envelope for the
        focused window (the live, triq-style scope). Throttled to scope_fps."""
        now = time.monotonic()
        min_interval = 1.0 / max(1, self._settings.scope_fps)
        if now - self._last_scope_emit < min_interval:
            return
        self._last_scope_emit = now

        row = psd_mod.reduce_bins(power_db, self._settings.scope_bins)
        sr = int(self._config.sample_rate)
        dwell_s = self._config.dwell_ms / 1000.0
        env_dt_us = round(dwell_s * 1e6 / max(1, envelope_db.shape[0]), 3)
        self._scope_seq += 1
        payload = {
            "center_hz": int(center),
            "sample_rate": sr,
            "f_start_hz": int(freqs[0]),
            "f_stop_hz": int(freqs[-1]),
            "bin_count": int(row.shape[0]),
            "power_db": [round(float(x), 2) for x in row.tolist()],
            "noise_floor_db": round(float(floor), 2),
            "envelope": [round(float(x), 2) for x in envelope_db.tolist()],
            "env_dt_us": env_dt_us,
            "seq": self._scope_seq,
            "t_ms": round(now * 1000.0, 1),
            "modulation": modulation,
        }
        self._ws.broadcast_scope(payload)

    async def _maybe_emit_snapshot(self) -> None:
        now = time.monotonic()
        if now - self._last_snapshot_emit < 1.0:
            return
        self._last_snapshot_emit = now
        # Merge near-duplicate channels (drift), then delete the merged-away rows
        # so /api/channels doesn't keep orphaned duplicates.
        for rid in self._clusterer.merge_overlapping():
            db_id = self._channel_db_id.pop(rid, rid)
            self._recurrence.pop(rid, None)
            self._last_persist.pop(rid, None)
            await self._repos.channels.delete(db_id)
        channels = await self._repos.channels.list()
        self._ws.broadcast_channels([c.model_dump(mode="json") for c in channels])
        # Update scan progress metric: how far the current window centre sits
        # through the configured band.
        span_total = max(1, self._config.end_hz - self._config.start_hz)
        pos = self._current_center() - self._config.start_hz
        self.metrics.scan_progress = round(min(1.0, max(0.0, pos / span_total)), 4)
        # Keep the dashboard (device, live metrics, scanning state) fresh ~1/s.
        await self._broadcast_status()

    # ------------------------------------------------------------- Wavenis
    def _should_stream_continuously(self) -> bool:
        """Native continuous mode is safe only while parked on one RTL window."""
        return (
            self._backend is not None
            and self._backend.name == "rtlsdr"
            and self._mode == "sweep"
            and len(self._sweep_centers) == 1
        )

    def _wavenis_profile_configured(self) -> bool:
        """Whether one instantaneous receiver window covers the whole grid."""
        band_width = self._config.end_hz - self._config.start_hz
        return (
            band_width <= self._config.sample_rate
            and self._config.start_hz <= WAVENIS_CHANNELS_HZ[0]
            and self._config.end_hz >= WAVENIS_CHANNELS_HZ[-1]
        )

    async def _record_candidate(self, burst: WavenisBurst) -> None:
        """Persist a flagged candidate durably (disk + events) and announce it."""
        record = {
            "timestamp": iso_now(),
            "session_id": self._session_id,
            "receiver_center_hz": self._current_center(),
            **burst.to_dict(),
        }
        # Append to the uncapped on-disk log so it survives restart/reboot.
        await asyncio.to_thread(self._candidate_log.append, record)
        reasons = ", ".join(burst.candidate_reasons) or "—"
        await self._emit_event(
            "wavenis_candidate",
            f"candidate f={burst.freq_hz} bw={burst.bandwidth_hz}Hz "
            f"dur={burst.duration_ms:.0f}ms snr={burst.peak_snr_db:.1f}dB [{reasons}]",
            data=record,
        )
        log.info(
            "wavenis.candidate",
            freq_hz=burst.freq_hz,
            bandwidth_hz=burst.bandwidth_hz,
            duration_ms=burst.duration_ms,
            reasons=list(burst.candidate_reasons),
            score=burst.candidate_score,
        )

    def candidates(self, limit: int | None = None) -> dict[str, object]:
        """Return the durable candidate record for review after a long run."""
        records = self._candidate_log.read_all(limit=limit)
        return {
            "total": self._candidate_log.count(),
            "path": str(self._candidate_log.path),
            "candidates": records,
        }

    async def _save_triggered_capture(self, capture: TriggeredCapture, center_hz: int) -> None:
        assert self._recorder is not None
        loop = asyncio.get_running_loop()
        annotation = {
            "core:sample_start": 0,
            "core:sample_count": int(capture.samples.size),
            "core:comment": "Qualified wideband RF events; protocol identity unconfirmed",
            "channel_detector:wavenis_bursts": capture.triggers,
        }
        result = await loop.run_in_executor(
            None,
            lambda: self._recorder.capture_iq(
                capture.samples,
                center_hz=center_hz,
                sample_rate=self._config.sample_rate,
                gain=self._config.gain,
                reason="wavenis-qualified-burst",
                fmt="cu8",
                annotations=[annotation],
            ),
        )
        rec = schemas.Recording(
            id=0,
            timestamp=result.timestamp,
            path=result.path,
            center_hz=result.center_hz,
            sample_rate=result.sample_rate,
            gain=result.gain,
            duration_ms=result.duration_ms,
            format=result.format,
            bytes=result.bytes,
            sigmf_meta=result.sigmf_meta,
        )
        rec_id = await self._repos.recordings.create(rec)
        await self._emit_event(
            "wavenis_capture",
            f"recording #{rec_id}: {len(capture.triggers)} candidate burst(s), "
            f"{result.duration_ms} ms",
            data={
                "recording_id": rec_id,
                "trigger_count": len(capture.triggers),
                "duration_ms": result.duration_ms,
                "bytes": result.bytes,
            },
        )

    def recent_iq(self, duration_ms: int) -> tuple[np.ndarray, int, int, str] | None:
        """Return buffered live IQ for a race-free manual recording."""
        iq = self._trigger_capture.recent(duration_ms)
        if iq is None:
            return None
        return iq, self._current_center(), self._config.sample_rate, self._config.gain

    def _acquisition_status(self) -> dict[str, object]:
        if self._iq_stream is not None:
            return dict(self._iq_stream.snapshot())
        if self._last_stream_status is not None and self._polled_blocks == 0:
            return self._last_stream_status
        return {
            "mode": "bounded_reads",
            "blocks_acquired": self._polled_blocks,
            "samples_acquired": self._polled_samples,
            "sample_cursor": self._polled_samples,
            "queue_depth": 0,
            "queue_capacity": 0,
            "dropped_blocks": 0,
            "dropped_samples": 0,
            "timing_gaps": 0,
            "estimated_gap_samples": 0,
            "retunes": self._retunes,
            "error": None,
        }

    def wavenis_status(self) -> dict[str, object]:
        configured = self._wavenis_profile_configured()
        center = self._current_center()
        observable = configured and WavenisWidebandAnalyzer.can_observe(
            center, self._config.sample_rate
        )
        snapshot = self._wavenis.snapshot()
        snapshot.update(
            {
                "configured": configured,
                "active": bool(self._scanning and observable),
                "receiver_center_hz": center,
                "sample_rate": self._config.sample_rate,
                # Durable on-disk total; the in-memory snapshot count only
                # covers the current session, so surface both.
                "candidates_persisted": self._candidate_log.count(),
                "acquisition": self._acquisition_status(),
                "capture": {
                    **self._trigger_capture.snapshot(),
                    "enabled": bool(self._recorder and self._recorder.enabled),
                    "format": "cu8",
                },
                "message": (
                    "continuously observing all 15 candidate channels"
                    if self._scanning and observable
                    else "profile ready; start the scan"
                    if observable
                    else "apply the Wavenis 868 preset so the grid fits one receiver window"
                ),
            }
        )
        return snapshot

    # ------------------------------------------------------------- decoder
    def _make_sim_decode(self) -> schemas.DecodeFrame:
        """Synthesize a plausible decoded meter reading (simulation only)."""
        self._decode_counter += 1
        n = self._decode_counter
        freq = 867_500_000 if n % 2 == 0 else 869_250_000
        return schemas.DecodeFrame(
            timestamp=iso_now(),
            decoder="sim",
            protocol="SimMeter",
            freq_hz=freq,
            known=True,
            fields={
                "model": "SimMeter",
                "id": 100000 + (freq % 1000),
                "reading_kwh": round(1000.0 + n * 0.37, 2),
                "battery_ok": True,
                "note": "simulated decode — no real device",
            },
            session_id=self._session_id,
        )

    async def _store_and_broadcast_decode(self, frame: schemas.DecodeFrame) -> None:
        frame.id = await self._repos.decodes.create(frame)
        self._ws.broadcast_decode(frame.model_dump(mode="json"))

    async def _maybe_emit_decode(self) -> None:
        if not self._settings.effective_simulation():
            return
        now = time.monotonic()
        if now - self._last_decode_emit < 7.0:
            return
        self._last_decode_emit = now
        await self._store_and_broadcast_decode(self._make_sim_decode())

    async def run_decoder(
        self, seconds: float = 6.0
    ) -> tuple[bool, str, list[schemas.DecodeFrame]]:
        """One-shot decode run. Uses rtl_433 when available (it needs exclusive
        device access, so the scan is paused around it); otherwise synthesizes a
        few simulated decodes so the panel is usable without hardware."""
        frames: list[schemas.DecodeFrame] = []
        real = self._decoder is not None and self._decoder.available()
        if not real:
            for _ in range(3):
                frame = self._make_sim_decode()
                await self._store_and_broadcast_decode(frame)
                frames.append(frame)
            msg = (
                "rtl_433 not available — generated simulated decodes"
                if self._settings.effective_simulation()
                else "rtl_433 binary not found; install it to decode real signals"
            )
            return (False, msg, frames)

        assert self._decoder is not None
        was_scanning = self._scanning
        center = self._focus_center or ((self._config.start_hz + self._config.end_hz) // 2)
        if was_scanning:
            await self.stop_scan()
        try:
            await self._decoder.start(center_hz=center, sample_rate=self._config.sample_rate)
            await asyncio.sleep(seconds)
            for m in self._decoder.drain():
                frame = self._decode_to_frame(m)
                await self._store_and_broadcast_decode(frame)
                frames.append(frame)
        finally:
            await self._decoder.stop()
            if was_scanning:
                await self.start_scan()
        return (True, f"rtl_433 ran for {int(seconds)}s; {len(frames)} message(s)", frames)

    def _decode_to_frame(self, m: DecodedMessage) -> schemas.DecodeFrame:
        return schemas.DecodeFrame(
            timestamp=m.timestamp,
            decoder=m.decoder,
            protocol=m.protocol,
            freq_hz=m.freq_hz,
            known=m.known,
            fields=m.fields,
            session_id=self._session_id,
        )

    async def calibrate(self, reference_hz: int, search_hz: int = 50_000) -> dict:
        """Measure the strongest peak near a known reference frequency and derive
        the tuner's ppm error. Pauses the scan for a single dwell read, then
        resumes. Returns a suggestion; applying it is left to the user (PUT config).
        """
        if self._backend is None:
            await self.startup()
        was_scanning = self._scanning
        was_focus = self._mode == "focus"
        focus_center = self._focus_center
        if was_scanning:
            await self.stop_scan()
        try:
            loop = asyncio.get_running_loop()
            freqs, power_db, _env, _mod, _wavenis = await loop.run_in_executor(
                None, self._read_and_psd, int(reference_hz), self._dwell_samples()
            )
        finally:
            if was_scanning:
                await self.start_scan()
                if was_focus and focus_center is not None:
                    await self.focus(focus_center, None, None)

        median = float(np.median(power_db))
        mask = np.abs(freqs - float(reference_hz)) <= float(search_hz)
        idxs = np.flatnonzero(mask)
        if idxs.size == 0:
            return {"ok": False, "message": "reference frequency is outside the tunable window"}
        sub = power_db[idxs]
        peak_local = int(idxs[int(np.argmax(sub))])
        peak_snr = round(float(power_db[peak_local]) - median, 1)
        if peak_snr < 6.0:
            return {
                "ok": False,
                "message": f"no strong signal near {reference_hz / 1e6:.4f} MHz "
                f"(peak only {peak_snr:.1f} dB over noise) — use a known steady carrier",
            }
        measured_hz = int(round(float(freqs[peak_local])))
        offset_hz = measured_hz - int(reference_hz)
        ppm_error = round(offset_hz / reference_hz * 1e6, 2)
        current_ppm = int(self._config.ppm)
        return {
            "ok": True,
            "message": f"measured {measured_hz / 1e6:.5f} MHz (off by {offset_hz} Hz)",
            "reference_hz": int(reference_hz),
            "measured_hz": measured_hz,
            "offset_hz": offset_hz,
            "ppm_error": ppm_error,
            "current_ppm": current_ppm,
            "suggested_ppm": int(round(current_ppm - ppm_error)),
            "peak_snr_db": peak_snr,
        }

    async def _broadcast_status(self) -> None:
        """Broadcast device + live metrics + scanning state + mode to all clients."""
        self._ws.broadcast_status(
            self.device_info(),
            await self.metrics_dict(),
            self._scanning,
            mode=self._mode,
            focus_center_hz=self._focus_center,
        )

    # ------------------------------------------------------------ sweep math
    def _current_center(self) -> int:
        if self._mode == "focus" and self._focus_center is not None:
            return self._focus_center
        if not self._sweep_centers:
            self._compute_sweep_plan()
        if not self._sweep_centers:
            return (self._config.start_hz + self._config.end_hz) // 2
        idx = self._sweep_idx % len(self._sweep_centers)
        return self._sweep_centers[idx]

    def _current_span(self) -> int:
        if self._mode == "focus" and self._focus_span is not None:
            return min(self._focus_span, self._config.sample_rate)
        return self._config.sample_rate

    def _step_hz(self, span: int) -> int:
        if self._config.step_hz > 0:
            return self._config.step_hz
        # Auto: 80% of the window to allow overlap at edges.
        return max(1, int(span * 0.8))

    def _compute_sweep_plan(self) -> None:
        """Build the list of window centre frequencies that tiles the band.

        Each window observes `sample_rate` Hz of instantaneous bandwidth. When
        the requested band is wider than one window the tuner must retune across
        it; the centres are spaced by the (auto or configured) step and chosen so
        the union of windows covers [start_hz, end_hz]. When the band fits inside
        one window the plan is a single parked centre.
        """
        span = int(self._config.sample_rate)
        start = int(self._config.start_hz)
        end = int(self._config.end_hz)
        band = max(1, end - start)

        if band <= span:
            # For the Wavenis single-window profile, park off-grid so the
            # RTL-SDR DC spike does not blind a grid channel (channel 7 sits on
            # the plain midpoint); otherwise centre the requested band.
            if self._wavenis_profile_configured():
                self._sweep_centers = [observable_center_hz(span)]
            else:
                self._sweep_centers = [(start + end) // 2]
            self._sweep_idx = 0
            return

        step = self._step_hz(span)
        centers: list[int] = []
        c = start + span // 2  # first window's lower edge sits at `start`
        while True:
            centers.append(c)
            if c + span // 2 >= end:  # this window already covers the top of the band
                break
            c += step
        self._sweep_centers = centers
        self._sweep_idx = 0

    def _reset_band_buffer(self) -> None:
        """(Re)allocate the stitched full-band spectrum buffer."""
        n = max(16, int(self._config.spectrum_bins))
        self._band_freqs = np.linspace(float(self._config.start_hz), float(self._config.end_hz), n)
        # Start each band bin at a low sentinel; segments fill in as scanned.
        self._band_power = np.full(n, -140.0, dtype=np.float64)

    def _stitch_into_band(self, freqs: np.ndarray, power_db: np.ndarray, floor: float) -> None:
        """Write the current window's PSD into the persistent band buffer."""
        if self._band_freqs is None or self._band_power is None:
            self._reset_band_buffer()
        assert self._band_freqs is not None and self._band_power is not None
        lo, hi = float(freqs[0]), float(freqs[-1])
        mask = (self._band_freqs >= lo) & (self._band_freqs <= hi)
        if mask.any():
            # freqs is ascending; interpolate window PSD onto band bins in range.
            self._band_power[mask] = np.interp(self._band_freqs[mask], freqs, power_db)
        self._band_floor = float(floor)

    def _advance_sweep(self, span: int) -> None:
        if not self._sweep_centers:
            self._compute_sweep_plan()
        if self._sweep_centers:
            self._sweep_idx = (self._sweep_idx + 1) % len(self._sweep_centers)

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
