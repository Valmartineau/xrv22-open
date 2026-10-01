"""Tests de caracterisation de la selection de ports d'auto-connexion U2D2.

Couvrent les helpers de xrv22/main_pi.py extraits de auto_connect_all_u2d2 :
l'arithmetique de ports (used / free) est la logique sensible du fallback.
"""
from __future__ import annotations

from xrv22.main_pi import (_compute_free_ports, _used_mapped_ports,
                           resolve_port_for_robot)


class _FakeCtrl:
    def __init__(self, connected=False, port=None):
        self.is_connected = connected
        self.port_name = port


class _FakeRegistry:
    def __init__(self, robots):
        self._robots = robots

    def get(self, rid):
        return self._robots.get(rid)


def test_used_mapped_ports():
    reg = _FakeRegistry({
        "robot_1": _FakeCtrl(connected=True, port="/dev/ttyUSB0"),
        "robot_2": _FakeCtrl(connected=False, port=None),
        "robot_3": _FakeCtrl(connected=True, port="/dev/ttyUSB9"),  # hors `ports`
    })
    ports = {"/dev/ttyUSB0", "/dev/ttyUSB1"}
    assert _used_mapped_ports(reg, ports) == {"/dev/ttyUSB0"}


def test_used_mapped_ports_aucun():
    reg = _FakeRegistry({"robot_1": _FakeCtrl(connected=False)})
    assert _used_mapped_ports(reg, {"/dev/ttyUSB0"}) == set()


def test_compute_free_ports_sans_mapping():
    ports = ["/dev/ttyA", "/dev/ttyB", "/dev/ttyC"]
    free = _compute_free_ports(ports, [], {}, set(), {"/dev/ttyB"})
    assert free == ["/dev/ttyA", "/dev/ttyC"]


def test_compute_free_ports_avec_mapping():
    u2d2 = [("S1", "/dev/ttyA"), ("S2", "/dev/ttyB"), ("S3", "/dev/ttyC")]
    mapping = {"S1": "robot_1"}
    # S2 et S3 hors mapping ; /dev/ttyC deja utilise
    free = _compute_free_ports(
        ["/dev/ttyA", "/dev/ttyB", "/dev/ttyC"], u2d2, mapping,
        unknown_serials={"S2", "S3"}, used_ports={"/dev/ttyC"})
    assert free == ["/dev/ttyB"]


def test_compute_free_ports_tous_utilises():
    free = _compute_free_ports(["/dev/ttyA"], [], {}, set(), {"/dev/ttyA"})
    assert free == []


# ── resolve_port_for_robot : port mappe d'un robot donne (connexion unitaire) ──

def test_resolve_port_for_robot_mappe():
    u2d2 = [("FT94W5W8", "/dev/ttyUSB0"), ("FT94THU9", "/dev/ttyUSB1")]
    mapping = {"FT94W5W8": "robot_1", "FT94THU9": "robot_3"}
    assert resolve_port_for_robot("robot_1", mapping, u2d2) == "/dev/ttyUSB0"
    assert resolve_port_for_robot("robot_3", mapping, u2d2) == "/dev/ttyUSB1"


def test_resolve_port_for_robot_non_mappe():
    u2d2 = [("FT94W5W8", "/dev/ttyUSB0")]
    mapping = {"FT94W5W8": "robot_1"}
    assert resolve_port_for_robot("robot_2", mapping, u2d2) is None


def test_resolve_port_for_robot_mappe_mais_non_branche():
    # robot_2 mappe a un serial absent des U2D2 detectes -> pas de port
    u2d2 = [("FT94W5W8", "/dev/ttyUSB0")]
    mapping = {"FT94W5W8": "robot_1", "FT94VT1T": "robot_2"}
    assert resolve_port_for_robot("robot_2", mapping, u2d2) is None
