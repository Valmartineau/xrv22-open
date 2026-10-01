"""Tests de caracterisation de RobotConfigModel.from_dict / to_dict.

Figent la deserialisation des dicts JSON (cles str -> int) AVANT refactor.
"""
from __future__ import annotations

from xrv22.library.models import RobotConfigModel


def test_from_dict_minimal():
    r = RobotConfigModel.from_dict({"robot_id": "robot_1"})
    assert r.robot_id == "robot_1"
    assert r.home_machine == {}
    assert r.home_work == {}
    assert r.soft_limits == {}


def test_from_dict_cles_str_to_int():
    r = RobotConfigModel.from_dict({
        "robot_id": "robot_1",
        "home_machine": {"1": 2048, "2": 1000},
        "home_work": {"1": 500},
        "soft_limits": {"1": [0, 4095], "2": [100, 200]},
    })
    assert r.home_machine == {1: 2048, 2: 1000}
    assert r.home_work == {1: 500}
    assert r.soft_limits == {1: [0, 4095], 2: [100, 200]}


def test_from_dict_cles_invalides_remplacees_par_vide():
    r = RobotConfigModel.from_dict({
        "robot_id": "x",
        "home_machine": {"foo": 1},
    })
    assert r.home_machine == {}


def test_from_dict_dict_vide_garde_vide():
    r = RobotConfigModel.from_dict({"home_machine": {}, "home_work": {}})
    assert r.home_machine == {} and r.home_work == {}


def test_from_dict_champs_inconnus_ignores():
    r = RobotConfigModel.from_dict({"robot_id": "x", "champ_inexistant": 42})
    assert r.robot_id == "x"
    assert not hasattr(r, "champ_inexistant")


def test_to_dict_cles_int_to_str():
    r = RobotConfigModel(
        robot_id="r1",
        home_machine={1: 2048},
        soft_limits={1: [0, 4095]},
    )
    d = r.to_dict()
    assert d["home_machine"] == {"1": 2048}
    assert d["soft_limits"] == {"1": [0, 4095]}


def test_round_trip():
    src = {
        "robot_id": "r1", "name": "Robot 1", "port": "/dev/ttyUSB0",
        "home_machine": {"1": 2048, "2": 1000},
        "soft_limits": {"1": [0, 4095]},
    }
    r = RobotConfigModel.from_dict(src)
    d = r.to_dict()
    r2 = RobotConfigModel.from_dict(d)
    assert r2.home_machine == r.home_machine
    assert r2.soft_limits == r.soft_limits
    assert r2.robot_id == r.robot_id
