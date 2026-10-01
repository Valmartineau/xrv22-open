"""Tests de caracterisation de la migration V21 -> V22 (xrv22/library/migration.py).

Figent le comportement observable de migrate_v21_to_v22 AVANT refactor.
"""
from __future__ import annotations

import json

import pytest

from xrv22.library.library_manager import LibraryManager
from xrv22.library.migration import auto_migrate_if_needed, migrate_v21_to_v22


@pytest.fixture
def lib(tmp_path):
    """LibraryManager isole dans un dossier temporaire."""
    LibraryManager._instance = None
    lm = LibraryManager(library_root=tmp_path / "XRV22_LIBRARY")
    yield lm
    LibraryManager._instance = None


def _v21_tree(root, *, poses=None, suites=None, robots=None,
              sequences=None, timeline=None, hardware=None, flat=None):
    """Construit une arborescence projet V21 dans `root`."""
    def _w(rel, data):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")

    if flat is not None:
        _w("project.json", flat)
        return root
    if poses is not None:
        _w("positions/poses.json", poses)
    if suites is not None:
        _w("suites/suites.json", suites)
    if robots is not None:
        _w("robots/robots.json", robots)
    if sequences is not None:
        _w("scenarios/sequences.json", sequences)
    if timeline is not None:
        _w("timeline/timeline.json", timeline)
    if hardware is not None:
        _w("hardware/hardware.json", hardware)
    return root


def test_migration_structuree(lib, tmp_path):
    src = _v21_tree(
        tmp_path / "v21",
        poses={"home": {"1": 2048, "2": 1000}, "haut": {"1": 3000}},
        suites={"groupe_a": ["home", "haut"]},
        robots=[{"robot_id": "robot_1", "home_machine": {"1": 100}}],
        sequences=[{"id": "seq1", "name": "Demo"}],
    )
    report = migrate_v21_to_v22(lib, src, "migr_test")

    assert report["positions_migrated"] == 2
    assert report["suites_migrated"] == 1
    assert report["robots_migrated"] == 1
    assert report["scenarios_migrated"] == 1
    assert report["warnings"] == []

    home = lib.get_position_by_name("home")
    assert home is not None
    assert home.positions == {1: 2048, 2: 1000}
    assert home.category == "sauvegardees"

    suites = lib.list_suites()
    assert len(suites) == 1
    assert suites[0].name == "groupe_a"
    assert len(suites[0].steps) == 2

    robot = lib.get_robot("robot_1")
    assert robot is not None
    assert robot.home_machine == {1: 100}


def test_migration_flat_v20(lib, tmp_path):
    src = _v21_tree(
        tmp_path / "v20",
        flat={
            "poses": {"p1": {"1": 500}},
            "pose_groups": {"g1": ["p1"]},
            "robots": [{"id": "robot_2"}],
            "sequences": [{"name": "S"}],
        },
    )
    report = migrate_v21_to_v22(lib, src, "flat_test")

    assert report["positions_migrated"] == 1
    assert report["suites_migrated"] == 1
    assert report["robots_migrated"] == 1
    assert report["scenarios_migrated"] == 1
    assert lib.get_robot("robot_2") is not None


def test_suite_position_introuvable(lib, tmp_path):
    src = _v21_tree(
        tmp_path / "v21",
        poses={"home": {"1": 2048}},
        suites={"groupe": ["home", "fantome"]},
    )
    report = migrate_v21_to_v22(lib, src, "warn_test")

    assert report["suites_migrated"] == 1
    assert len(report["warnings"]) == 1
    assert "fantome" in report["warnings"][0]
    # seule la position existante est conservee comme etape
    assert len(lib.list_suites()[0].steps) == 1


def test_groupe_non_groupees_ignore(lib, tmp_path):
    src = _v21_tree(
        tmp_path / "v21",
        poses={"home": {"1": 2048}},
        suites={"Non groupées": ["home"], "vraie_suite": ["home"]},
    )
    report = migrate_v21_to_v22(lib, src, "ng_test")

    assert report["suites_migrated"] == 1
    assert lib.list_suites()[0].name == "vraie_suite"


def test_robot_sans_id_ignore(lib, tmp_path):
    src = _v21_tree(
        tmp_path / "v21",
        robots=[{"name": "anonyme"}, {"robot_id": "robot_1"}],
    )
    report = migrate_v21_to_v22(lib, src, "rid_test")

    assert report["robots_migrated"] == 1


def test_source_vide(lib, tmp_path):
    src = tmp_path / "vide"
    src.mkdir()
    report = migrate_v21_to_v22(lib, src, "empty_test")

    assert report["positions_migrated"] == 0
    assert report["suites_migrated"] == 0
    assert report["robots_migrated"] == 0
    assert report["scenarios_migrated"] == 0


def test_auto_migrate_pas_de_v21(lib):
    # ~/XR200_LIBRARY/projects/default n'existe pas dans l'env de test
    assert auto_migrate_if_needed(lib) is None
