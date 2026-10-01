"""GET /api/robots/{rid}/anticollision doit rapporter `available` SANS course.

Régression 2026-06-15 : au tout premier appel après (re)démarrage, l'endpoint
lisait `box_engine.available` juste après un `check({})` qui ne fait que LANCER
l'init dans un thread daemon (~1 s) et rend la main aussitôt → `available:false`
transitoire. La session précédente l'a pris pour « init qui échoue / fail-open ».
Le correctif : l'endpoint déclenche l'init de façon SYNCHRONE (idempotente) avant
de rapporter l'état → plus de course.

fastapi n'est installé que côté serveur (Pi) ; ce test est skippé ailleurs.
"""
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from xrv22.core import box_collision  # noqa: E402
from xrv22.core.box_collision import BoxCollisionEngine  # noqa: E402
from xrv22.core.safety_manager import safety  # noqa: E402
from xrv22.server import auth  # noqa: E402
from xrv22.server.api import create_app  # noqa: E402

CALIB_PATH = Path(__file__).parent.parent / "web" / "public" / "calibration.json"


def test_get_anticollision_rapporte_available_sans_course(monkeypatch):
    """1er appel après démarrage → available=true, sans dépendre du thread."""
    eng = BoxCollisionEngine(CALIB_PATH)
    # On neutralise l'init paresseuse en arrière-plan : si l'endpoint s'y fie
    # (ancien `check({})`), `available` reste False → le test capture la course.
    monkeypatch.setattr(eng, "_kick_init", lambda: None)
    monkeypatch.setattr(box_collision, "engine", eng)
    safety.add_robot("robot_avail_test", [1, 2, 3, 4, 5, 6, 7])

    client = TestClient(create_app())  # sans `with` → pas de startup matériel
    resp = client.get(
        "/api/robots/robot_avail_test/anticollision",
        headers={"Authorization": f"Bearer {auth.get_token()}"},
    )

    assert resp.status_code == 200
    assert resp.json()["available"] is True
