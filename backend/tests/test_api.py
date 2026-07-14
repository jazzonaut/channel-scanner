"""REST API tests against the simulator."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["simulation"] is True
    assert "version" in body


async def test_device(client: AsyncClient) -> None:
    r = await client.get("/api/device")
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "sim"
    assert body["simulation"] is True
    assert len(body["freq_range_hz"]) == 2


async def test_config_get(client: AsyncClient) -> None:
    r = await client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["start_hz"] < body["end_hz"]
    assert body["version"] >= 1


async def test_config_put_requires_control_lease(client: AsyncClient) -> None:
    cfg = (await client.get("/api/config")).json()
    r = await client.put(
        "/api/config",
        json={"version": cfg["version"], "client_id": "nobody", "threshold_db": 8.0},
    )
    assert r.status_code == 403


async def test_config_put_with_lease_and_version(client: AsyncClient) -> None:
    acq = await client.post(
        "/api/control/acquire", json={"client_id": "op1", "display_name": "Operator"}
    )
    assert acq.status_code == 200 and acq.json()["ok"] is True

    cfg = (await client.get("/api/config")).json()
    r = await client.put(
        "/api/config",
        json={"version": cfg["version"], "client_id": "op1", "threshold_db": 9.5},
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["threshold_db"] == 9.5
    assert updated["version"] == cfg["version"] + 1

    # Stale version now conflicts.
    conflict = await client.put(
        "/api/config",
        json={"version": cfg["version"], "client_id": "op1", "threshold_db": 10.0},
    )
    assert conflict.status_code == 409


async def test_scan_start_stop(client: AsyncClient) -> None:
    r = await client.post("/api/scan/start")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["session_id"] > 0

    stop = await client.post("/api/scan/stop")
    assert stop.status_code == 200 and stop.json()["ok"] is True


async def test_channels_and_events_endpoints(client: AsyncClient) -> None:
    assert (await client.get("/api/channels")).status_code == 200
    assert (await client.get("/api/events")).status_code == 200
    assert (await client.get("/api/sessions")).status_code == 200
    assert (await client.get("/api/metrics")).status_code == 200
    assert (await client.get("/api/clients")).status_code == 200


async def test_export_endpoints(client: AsyncClient) -> None:
    csv_r = await client.get("/api/export.csv?kind=channels")
    assert csv_r.status_code == 200
    assert "text/csv" in csv_r.headers["content-type"]
    json_r = await client.get("/api/export.json?kind=events")
    assert json_r.status_code == 200
    assert json_r.json()["kind"] == "events"


async def test_recording_disabled_returns_409(client: AsyncClient) -> None:
    r = await client.post("/api/recordings/start", json={"duration_ms": 100})
    assert r.status_code == 409
