"""Tests de check_position : limites soft + collision, sans bouger le robot."""
from __future__ import annotations

from xrv22.core.safety_manager import RobotSafetyManager


def test_check_position_dans_limites_ok():
    sm = RobotSafetyManager("robot_x", [1, 2, 3, 4, 5, 6, 7])
    conflicts = sm.check_position({a: 2048 for a in range(1, 8)})
    assert conflicts == []


def test_check_position_hors_limite_basse():
    sm = RobotSafetyManager("robot_x", [1])
    sm.set_soft_limits(1, 1000, 3000)
    conflicts = sm.check_position({1: 50})
    assert any(c["type"] == "limit" for c in conflicts)
    assert conflicts[0]["message"]            # message non vide
    assert conflicts[0]["severity"] == "error"


def test_check_position_hors_limite_haute():
    sm = RobotSafetyManager("robot_x", [1])
    sm.set_soft_limits(1, 1000, 3000)
    conflicts = sm.check_position({1: 4000})
    assert any(c["type"] == "limit" for c in conflicts)
