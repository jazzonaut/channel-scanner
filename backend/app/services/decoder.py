"""Optional receive-only decoders (rtl_433 adapter).

Defines a generic ReceiveOnlyDecoder interface and an Rtl433Decoder that shells
out to the `rtl_433` binary (only if present on PATH) to opportunistically label
plainly-decodable, unencrypted device telemetry. Decoding NEVER blocks scanning
(it runs as a separate subprocess reader) and NEVER attempts to bypass
encryption or authentication: unknown/encrypted transmissions are recorded as
`unknown`.

This is passive labelling of what is already receivable in the clear. It does
not transmit, replay, or spoof anything.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import json
import shutil
from dataclasses import dataclass, field

import structlog

from ..utils import iso_now

log = structlog.get_logger(__name__)


@dataclass
class DecodedMessage:
    decoder: str
    protocol: str
    timestamp: str
    freq_hz: int | None
    fields: dict
    known: bool = True


class ReceiveOnlyDecoder(abc.ABC):
    """Interface for passive, receive-only protocol decoders."""

    name: str = "base"

    @abc.abstractmethod
    def available(self) -> bool:
        """Whether this decoder can run in the current environment."""

    @abc.abstractmethod
    async def start(self, *, center_hz: int, sample_rate: int) -> None:
        """Begin decoding (non-blocking)."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Stop decoding and release resources."""

    @abc.abstractmethod
    def drain(self) -> list[DecodedMessage]:
        """Return and clear any messages decoded since the last drain."""


@dataclass
class Rtl433Decoder(ReceiveOnlyDecoder):
    """Adapter around the rtl_433 CLI (JSON output)."""

    binary: str = "rtl_433"
    name: str = "rtl_433"
    _proc: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _reader_task: asyncio.Task | None = field(default=None, repr=False)
    _buffer: list[DecodedMessage] = field(default_factory=list, repr=False)
    _path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._path = shutil.which(self.binary)

    def available(self) -> bool:
        return self._path is not None

    async def start(self, *, center_hz: int, sample_rate: int) -> None:
        if not self.available():
            log.info("decoder.rtl433.unavailable")
            return
        if self._proc is not None:
            return
        cmd = [
            self._path,  # type: ignore[list-item]
            "-f",
            str(center_hz),
            "-s",
            str(sample_rate),
            "-F",
            "json",
        ]
        try:  # pragma: no cover - requires rtl_433 + hardware
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._reader_task = asyncio.create_task(self._read_loop())
            log.info("decoder.rtl433.started", center_hz=center_hz, sample_rate=sample_rate)
        except Exception as exc:  # noqa: BLE001
            log.warning("decoder.rtl433.start_failed", error=str(exc))
            self._proc = None

    async def _read_loop(self) -> None:  # pragma: no cover - requires rtl_433
        assert self._proc is not None and self._proc.stdout is not None
        try:
            async for raw in self._proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                self._buffer.append(self._parse_line(line))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("decoder.rtl433.read_stopped", error=str(exc))

    def _parse_line(self, line: str) -> DecodedMessage:  # pragma: no cover - CLI
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return DecodedMessage(
                decoder=self.name,
                protocol="unknown",
                timestamp=iso_now(),
                freq_hz=None,
                fields={"raw": line},
                known=False,
            )
        model = obj.get("model") or obj.get("protocol") or "unknown"
        freq = obj.get("freq")
        freq_hz = int(float(freq) * 1e6) if isinstance(freq, (int, float)) else None
        return DecodedMessage(
            decoder=self.name,
            protocol=str(model),
            timestamp=iso_now(),
            freq_hz=freq_hz,
            fields=obj,
            known=model != "unknown",
        )

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):  # pragma: no cover
                await self._reader_task
            self._reader_task = None
        if self._proc is not None:  # pragma: no cover - requires rtl_433
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except (TimeoutError, ProcessLookupError):
                pass
            self._proc = None
        log.info("decoder.rtl433.stopped")

    def drain(self) -> list[DecodedMessage]:
        out = self._buffer
        self._buffer = []
        return out


def build_default_decoder() -> ReceiveOnlyDecoder:
    """Return an rtl_433 decoder (inert if the binary is absent)."""
    return Rtl433Decoder()
