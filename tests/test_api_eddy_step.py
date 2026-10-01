"""POST /api/eddy/step republie le pas sur le bus (topic eddy.step).

fastapi n'est installé que côté serveur (Pi) ; ce test est skippé ailleurs.
"""
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from xrv22.server import auth  # noqa: E402
from xrv22.server.api import create_app  # noqa: E402
from xrv22.services.event_bus import bus  # noqa: E402


def test_post_eddy_step_publie_sur_le_bus():
    recu = []
    handler = lambda data: recu.append(data)
    bus.subscribe("eddy.step", handler)
    try:
        client = TestClient(create_app())
        payload = {"pas": 1, "positions": {"5": 2080}, "manettes": [2080],
                   "signaux": [1, 2, 47], "pression": 47, "plafond": 500,
                   "manette_active": 4, "delta": -2, "pensee": "x", "note": "y",
                   "bloque": False, "ts": 1.0}
        resp = client.post("/api/eddy/step", json=payload,
                           headers={"Authorization": f"Bearer {auth.get_token()}"})
    finally:
        bus.unsubscribe("eddy.step", handler)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert recu and recu[-1]["pas"] == 1 and recu[-1]["bloque"] is False
