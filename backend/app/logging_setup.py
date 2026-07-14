"""Structured logging configuration (structlog + stdlib) with file rotation.

Logs go to stdout and to a rotating file under the configured logs dir. Never
logs secrets (there are none in this app; env holds no credentials). JSON in the
file, console-friendly rendering on stdout.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog

_CONFIGURED = False


def configure_logging(*, level: str = "INFO", log_dir: str | Path = "/data/logs") -> None:
    """Idempotently configure structlog + stdlib logging with rotation."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = getattr(logging, str(level).upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        foreign_pre_chain=shared_processors,
    )
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=shared_processors,
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(log_level)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(console_formatter)
    root.addHandler(stream)

    try:
        ldir = Path(log_dir)
        ldir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            ldir / "backend.log",
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)
        root.addHandler(file_handler)
    except OSError:
        # If the logs dir is not writable, keep stdout logging only.
        structlog.get_logger(__name__).warning(
            "logging.file_handler.unavailable", log_dir=str(log_dir)
        )

    _CONFIGURED = True
