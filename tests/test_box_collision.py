"""Tests du moteur anti-collision boîtes (port Python du moteur TypeScript).

Deux niveaux :
1. Parité dorée : la fixture tests/fixtures/box_collision_parity.json est
   générée par le moteur TS de référence (web/scripts/gen-parity-fixture.ts).
   Le port Python doit produire les MÊMES boîtes monde, exclusions et hits.
2. Tests unitaires SAT (miroir des cas de boxCollision.test.ts).
"""
import json
import math
from pathlib import Path

import pytest

from xrv22.core.box_collision import (
    REF_UP, BoxCollisionEngine, WorldBox, box_bottom, ground_hit, obb_intersect,
    obb_penetration, rest_ground_boxes, sweep_contacts, world_boxes,
)

FIXTURE = Path(__file__).parent / "fixtures" / "box_collision_parity.json"
# Source committée (le chemin par défaut du moteur, server/static/, est un
# artefact de build gitignoré — même contenu une fois déployé).
CALIB_PATH = Path(__file__).parent.parent / "web" / "public" / "calibration.json"

ID_AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
SQ2 = math.sqrt(0.5)
ROT45 = ((SQ2, SQ2, 0.0), (-SQ2, SQ2, 0.0), (0.0, 0.0, 1.0))


def mk(c, half, link=0, axes=ID_AXES):
    return WorldBox(link=link, c=tuple(c), axes=axes, half=tuple(half))


@pytest.fixture(scope="module")
def fx():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def calib():
    return json.loads(CALIB_PATH.read_text())


# ── Parité dorée TS → Python ─────────────────────────────────────

def test_parity_world_boxes(fx, calib):
    for name, pose in fx["poses"].items():
        boxes = world_boxes(pose["ticks"], calib)
        assert len(boxes) == fx["nBoxes"], name
        for i, ref in enumerate(pose["boxes"]):
            b = boxes[i]
            assert b.link == ref["link"], f"{name}[{i}] link"
            for a in range(3):
                assert b.c[a] == pytest.approx(ref["c"][a], abs=1e-6), f"{name}[{i}] c[{a}]"
                assert b.half[a] == pytest.approx(ref["half"][a], abs=1e-9)
                for k in range(3):
                    assert b.axes[a][k] == pytest.approx(ref["axes"][a][k], abs=1e-9), \
                        f"{name}[{i}] axes[{a}][{k}]"
            assert box_bottom(b) == pytest.approx(ref["bottom"], abs=1e-6), f"{name}[{i}] bottom"


def test_parity_exclusions(fx, calib):
    excl = sweep_contacts(calib, fx["margin"])
    assert sorted(excl) == fx["exclusions"]


def test_parity_hits_and_ground(fx, calib):
    margin = fx["margin"]
    excl = sweep_contacts(calib, margin)
    rest = world_boxes(fx["poses"]["rest"]["ticks"], calib)
    g_idx = rest_ground_boxes(rest, fx["refSurfaceZ"], margin)
    assert g_idx == fx["groundIdx"]
    for name, pose in fx["poses"].items():
        boxes = world_boxes(pose["ticks"], calib)
        hits = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if boxes[i].link == boxes[j].link:
                    continue
                if f"{i}-{j}" in excl:
                    continue
                if obb_intersect(boxes[i], boxes[j], margin):
                    hits.append([i, j])
        # le moteur TS teste aussi les paires même-maillon, mais leur pose
        # relative est constante : jamais en collision hors exclusions → les
        # ignorer côté Python donne le même résultat.
        assert hits == pose["hits"], name
        assert ground_hit(boxes, fx["refSurfaceZ"], margin, g_idx) == pose["groundHit"], name


# ── SAT unitaire (miroir boxCollision.test.ts) ───────────────────

def test_sat_axis_aligned():
    a = mk((0, 0, 0), (1, 1, 1))
    assert not obb_intersect(a, mk((3, 0, 0), (1, 1, 1)), 0)
    assert obb_intersect(a, mk((1.9, 0, 0), (1, 1, 1)), 0)


def test_sat_margin():
    a = mk((0, 0, 0), (1, 1, 1))
    b = mk((2.2, 0, 0), (1, 1, 1))
    assert not obb_intersect(a, b, 0)
    assert obb_intersect(a, b, 0.5)


def test_sat_rotated_45():
    a = mk((0, 0, 0), (1, 1, 1))
    assert obb_intersect(a, mk((2.2, 0, 0), (1, 1, 1), axes=ROT45), 0)
    assert not obb_intersect(a, mk((2.6, 0, 0), (1, 1, 1), axes=ROT45), 0)


def test_sat_diagonal_face_axis():
    a = mk((0, 0, 0), (1, 1, 1))
    b = mk((1.9, 1.9, 0), (1, 1, 1), axes=ROT45)
    assert not obb_intersect(a, b, 0)


def test_ground_tilted():
    tilt_x = ((1.0, 0.0, 0.0), (0.0, SQ2, SQ2), (0.0, -SQ2, SQ2))
    b = mk((0, 0, 13), (10, 10, 10), axes=tilt_x)
    assert ground_hit([b], 0, 0, [0])  # descente √2·10 ≈ 14.1 > 13


# ── Moteur intégré ───────────────────────────────────────────────

def test_obb_penetration_monotonic():
    a = mk((0, 0, 0), (10, 10, 10))
    assert obb_penetration(a, mk((30, 0, 0), (10, 10, 10)), 0) == 0.0  # séparé
    p_touch = obb_penetration(a, mk((19, 0, 0), (10, 10, 10)), 0)      # overlap 1
    p_deep = obb_penetration(a, mk((15, 0, 0), (10, 10, 10)), 0)       # overlap 5
    assert 0 < p_touch < p_deep
    assert p_deep == pytest.approx(5.0, abs=1e-6)
    assert p_touch == pytest.approx(1.0, abs=1e-6)


def test_penetration_positive_ssi_collision():
    a = mk((0, 0, 0), (10, 10, 10))
    # pénétration > 0 exactement quand obb_intersect est vrai (gardé)
    for d in (15.0, 19.0, 19.9, 20.1, 25.0, 30.0):
        b = mk((d, 0, 0), (10, 10, 10))
        assert (obb_penetration(a, b, 0) > 0) == obb_intersect(a, b, 0)


def test_evaluate_rest_et_repli(fx):
    eng = BoxCollisionEngine(CALIB_PATH)
    eng.init()
    rest = {int(k): v for k, v in fx["poses"]["rest"]["ticks"].items()}
    pen0, lbl0 = eng.evaluate(rest)
    assert pen0 == 0.0 and lbl0 is None
    fold = {**rest, 5: rest[5] - round(110 * 4096 / 360)}
    penf, lblf = eng.evaluate(fold)
    assert penf > 0 and lblf is not None and "Forearm" in lblf and "Wrist" in lblf
    # plus on replie, plus la pénétration est grande (monotonie → recul possible)
    deeper = {**rest, 5: rest[5] - round(125 * 4096 / 360)}
    pend, _ = eng.evaluate(deeper)
    assert pend > penf


def test_engine_check(fx):
    eng = BoxCollisionEngine(CALIB_PATH)
    eng.init()
    assert eng.available
    ref = {int(k): v for k, v in fx["poses"]["rest"]["ticks"].items()}
    assert eng.check(ref) is None
    # repli du poignet (axe 5 à -100°) → auto-collision Wrist×Forearm
    fold = dict(ref)
    fold[5] = ref[5] - round(100 * 4096 / 360)
    reason = eng.check(fold)
    assert reason is not None and "Wrist" in reason and "Forearm" in reason


def test_engine_fail_open_sans_calibration(tmp_path):
    eng = BoxCollisionEngine(tmp_path / "absent.json")
    eng.init()
    assert not eng.available
    assert eng.check({1: 2048}) is None
