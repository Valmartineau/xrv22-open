"""Tests de caracterisation de RobotRegistry.propagate_from_master.

Figent la replication master -> esclaves AVANT refactor. Les controleurs
sont remplaces par des doubles enregistrant les appels recus.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from xrv22.robots.robot_registry import RobotRegistry


class _FakeRobot:
    """Double de RobotController : enregistre les appels de propagation."""

    def __init__(self):
        self.home_machine: dict = {}
        self.home_work: dict = {}
        self.profile = SimpleNamespace(soft_limits={})
        self.smooth_hz = 60
        self.comfort_vel = 120
        self.comfort_acc = 40
        self.home_duration = 3.0
        self.calls: list = []

    def set_home_machine(self, src, _propagating=False):
        self.calls.append(("set_home_machine", dict(src), _propagating))

    def set_home_work(self, src, _propagating=False):
        self.calls.append(("set_home_work", dict(src), _propagating))

    def set_motor_limit(self, mid, lo, hi, _propagating=False):
        self.calls.append(("set_motor_limit", mid, lo, hi, _propagating))

    def set_motion_params(self, hz, vel, acc, home_duration=None, _propagating=False):
        self.calls.append(
            ("set_motion_params", hz, vel, acc, home_duration, _propagating))

    def names(self):
        return [c[0] for c in self.calls]


def _registry(master, **slaves):
    """RobotRegistry peuple de doubles, master = 'robot_1'."""
    reg = RobotRegistry()
    reg._robots = {"robot_1": master, **slaves}
    reg._master_id = "robot_1"
    return reg


def test_propagate_all():
    master = _FakeRobot()
    master.home_machine = {1: 2048}
    master.home_work = {1: 1000}
    master.profile.soft_limits = {1: (0, 4095), 2: (100, 200)}
    s2, s3 = _FakeRobot(), _FakeRobot()
    reg = _registry(master, robot_2=s2, robot_3=s3)

    reg.propagate_from_master(kind="all")

    for slave in (s2, s3):
        assert ("set_home_machine", {1: 2048}, True) in slave.calls
        assert ("set_home_work", {1: 1000}, True) in slave.calls
        assert ("set_motor_limit", 1, 0, 4095, True) in slave.calls
        assert ("set_motor_limit", 2, 100, 200, True) in slave.calls
        assert "set_motion_params" in slave.names()
        assert slave.profile.soft_limits == {1: (0, 4095), 2: (100, 200)}
    # le master ne se propage pas a lui-meme
    assert master.calls == []


def test_propagate_home_machine_avec_positions():
    master = _FakeRobot()
    master.home_machine = {1: 9999}  # ignore au profit de l'argument positions
    slave = _FakeRobot()
    reg = _registry(master, robot_2=slave)

    reg.propagate_from_master(kind="home_machine", positions={1: 500})

    assert ("set_home_machine", {1: 500}, True) in slave.calls
    assert "set_home_work" not in slave.names()


def test_propagate_soft_limit():
    master = _FakeRobot()
    slave = _FakeRobot()
    reg = _registry(master, robot_2=slave)

    reg.propagate_from_master(kind="soft_limit", motor_id=2, limits=(100, 200))

    assert ("set_motor_limit", 2, 100, 200, True) in slave.calls
    assert slave.profile.soft_limits[2] == (100, 200)
    assert "set_home_machine" not in slave.names()


def test_propagate_motion():
    master = _FakeRobot()
    master.smooth_hz, master.comfort_vel = 75, 150
    slave = _FakeRobot()
    reg = _registry(master, robot_2=slave)

    reg.propagate_from_master(kind="motion")

    motion = [c for c in slave.calls if c[0] == "set_motion_params"]
    assert motion == [("set_motion_params", 75, 150, 40, 3.0, True)]


def test_propagate_pas_de_master():
    reg = RobotRegistry()
    reg._robots = {}
    reg._master_id = ""
    # ne doit pas lever
    reg.propagate_from_master(kind="all")


def test_propagate_exception_isolee():
    master = _FakeRobot()
    master.home_machine = {1: 2048}
    boom = _FakeRobot()
    boom.set_home_machine = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
    ok = _FakeRobot()
    reg = _registry(master, robot_2=boom, robot_3=ok)

    # l'echec d'un esclave n'empeche pas les autres ni ne propage l'exception
    reg.propagate_from_master(kind="home_machine")

    assert ("set_home_machine", {1: 2048}, True) in ok.calls


def test_home_machine_vide_master_non_propage():
    master = _FakeRobot()  # home_machine vide
    slave = _FakeRobot()
    reg = _registry(master, robot_2=slave)

    reg.propagate_from_master(kind="home_machine")

    assert "set_home_machine" not in slave.names()
