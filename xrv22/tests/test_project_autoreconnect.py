"""Garde anti-connexion-fantôme de l'auto-reconnexion par port mémorisé.

Contexte : robot_3.robot.json peut porter un port périmé (= celui de robot_1).
L'auto-reconnexion ne doit PAS rouvrir un robot déjà connecté ni se brancher sur
un port déjà occupé par un autre robot (sinon connexion fantôme sur le mauvais
adaptateur)."""
from __future__ import annotations

from xrv22.services.project_service import ProjectService


class _FakeCtrl:
    def __init__(self, connected=False, port=None):
        self.is_connected = connected
        self.port_name = port


class _FakeRegistry:
    def __init__(self, robots):
        self._robots = robots

    def ids(self):
        return list(self._robots.keys())

    def get(self, rid):
        return self._robots.get(rid)


def test_blocked_si_deja_connecte():
    reg = _FakeRegistry({"robot_1": _FakeCtrl(True, "/dev/ttyUSB0")})
    ctrl = reg.get("robot_1")
    assert ProjectService._reconnect_blocked(reg, "robot_1", "/dev/ttyUSB0", ctrl) is not None


def test_blocked_si_port_pris_par_autre():
    reg = _FakeRegistry({
        "robot_1": _FakeCtrl(True, "/dev/ttyUSB0"),
        "robot_3": _FakeCtrl(False, None),
    })
    ctrl3 = reg.get("robot_3")
    # robot_3 (port stocké périmé ttyUSB0) : ttyUSB0 déjà pris par robot_1 → bloqué
    assert ProjectService._reconnect_blocked(reg, "robot_3", "/dev/ttyUSB0", ctrl3) is not None


def test_autorise_si_libre_et_non_connecte():
    reg = _FakeRegistry({
        "robot_1": _FakeCtrl(True, "/dev/ttyUSB0"),
        "robot_2": _FakeCtrl(False, None),
    })
    ctrl2 = reg.get("robot_2")
    assert ProjectService._reconnect_blocked(reg, "robot_2", "/dev/ttyUSB1", ctrl2) is None
