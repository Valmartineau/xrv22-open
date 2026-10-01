"""POST /api/stylet/tick republie le tick sur le bus (topic stylet.tick)."""
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from xrv22.server import auth  # noqa: E402
from xrv22.server.api import create_app  # noqa: E402
from xrv22.services.event_bus import bus  # noqa: E402


def test_post_stylet_tick_publie_sur_le_bus():
    recu = []
    h = lambda d: recu.append(d)
    bus.subscribe("stylet.tick", h)
    try:
        client = TestClient(create_app())
        body = {"x": 10, "y": 20, "p": 300, "etat": "CONTACT"}
        resp = client.post("/api/stylet/tick", json=body,
                           headers={"Authorization": f"Bearer {auth.get_token()}"})
    finally:
        bus.unsubscribe("stylet.tick", h)
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert recu and recu[-1]["p"] == 300 and recu[-1]["etat"] == "CONTACT"
