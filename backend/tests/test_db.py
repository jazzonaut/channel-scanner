"""Storage tests: migrations applied + repository round-trips."""

from __future__ import annotations

from app.models import schemas
from app.storage.db import Database
from app.storage.repositories import Repositories
from app.utils import iso_now


async def test_migrations_create_tables(db: Database) -> None:
    cur = await db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    rows = await cur.fetchall()
    await cur.close()
    names = {r["name"] for r in rows}
    for expected in (
        "sessions",
        "receiver_config",
        "candidate_channels",
        "detections",
        "bursts",
        "config_changes",
        "client_events",
        "recordings",
    ):
        assert expected in names


async def test_session_and_detection_round_trip(repos: Repositories) -> None:
    session_id = await repos.sessions.create(
        started_at=iso_now(),
        start_hz=867_000_000,
        end_hz=870_000_000,
        backend="sim",
        simulation=True,
    )
    assert session_id > 0
    det = schemas.Detection(
        id=0,
        channel_id=None,
        session_id=session_id,
        timestamp=iso_now(),
        center_hz=868_000_000,
        bandwidth_hz=25_000,
        peak_power_db=-20.0,
        avg_power_db=-25.0,
        snr_db=40.0,
        duration_ms=12.0,
    )
    det_id = await repos.detections.create(det)
    assert det_id > 0
    all_det = await repos.detections.list_all()
    assert any(d.id == det_id for d in all_det)


async def test_channel_upsert_and_get(repos: Repositories) -> None:
    ch = schemas.CandidateChannel(
        id=0,
        center_hz=868_500_000,
        bandwidth_hz=30_000,
        current_power_db=-22.0,
        peak_power_db=-18.0,
        avg_power_db=-25.0,
        snr_db=38.0,
        observation_count=5,
        first_seen=iso_now(),
        last_seen=iso_now(),
        typical_burst_ms=15.0,
        recurrence_interval_s=4.0,
        confidence=0.6,
        status="active",
        fingerprint=None,
    )
    cid = await repos.channels.upsert(ch)
    got = await repos.channels.get(cid)
    assert got is not None
    assert got.center_hz == 868_500_000
    # Update observation count and re-upsert.
    got = got.model_copy(update={"observation_count": 9})
    await repos.channels.upsert(got)
    again = await repos.channels.get(cid)
    assert again is not None and again.observation_count == 9


async def test_event_and_config_change(repos: Repositories) -> None:
    await repos.events.create(timestamp=iso_now(), kind="test", message="hello")
    events = await repos.events.list()
    assert events and events[0].kind == "test"
    await repos.config_changes.record(
        timestamp=iso_now(), version=2, client_id="c1", config_json="{}"
    )
    assert await repos.config_changes.latest_version() == 2


async def test_recording_round_trip(repos: Repositories) -> None:
    rec = schemas.Recording(
        id=0,
        timestamp=iso_now(),
        path="/tmp/x.sigmf-data",
        center_hz=868_000_000,
        sample_rate=2_400_000,
        gain="auto",
        duration_ms=1000,
        format="cf32_le",
        bytes=1024,
        sigmf_meta={"global": {"core:version": "1.0.0"}},
    )
    rid = await repos.recordings.create(rec)
    got = await repos.recordings.get(rid)
    assert got is not None and got.bytes == 1024
    assert await repos.recordings.total_bytes() >= 1024
    assert await repos.recordings.delete(rid) is True
