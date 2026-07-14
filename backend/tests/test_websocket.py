"""WebSocket tests using Starlette's TestClient (runs lifespan + WS)."""

from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from app.main import create_app

from .conftest import make_settings


def test_identify_then_hello(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as tc, tc.websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "identify", "client_id": "c1", "display_name": "Tester"})
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["client_id"] == "c1"
        assert "config" in hello and hello["version"] >= 1


def test_ping_pong(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as tc, tc.websocket_connect("/ws/live") as ws:
        ws.send_json({"type": "identify", "client_id": "c2"})
        # Drain until hello seen, then ping.
        _ = ws.receive_json()
        ws.send_json({"type": "ping"})
        got_pong = False
        for _ in range(20):
            msg = ws.receive_json()
            if msg.get("type") == "pong":
                got_pong = True
                break
        assert got_pong


def test_receives_spectrum_frames(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as tc:
        started = tc.post("/api/scan/start")
        assert started.status_code == 200
        with tc.websocket_connect("/ws/live") as ws:
            ws.send_json({"type": "identify", "client_id": "viewer"})
            saw_spectrum = False
            for _ in range(200):
                msg = ws.receive_json()
                if msg.get("type") == "spectrum":
                    assert msg["bin_count"] <= 512
                    assert len(msg["power_db"]) == msg["bin_count"]
                    assert "noise_floor_db" in msg
                    saw_spectrum = True
                    break
            assert saw_spectrum
        tc.post("/api/scan/stop")
