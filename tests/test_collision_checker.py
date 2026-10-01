# tests/test_collision_checker.py
import math
import pytest
from xrv22.library.models import ZoneModel
from xrv22.core.collision_checker import (
    point_in_polygon_2d,
    compute_zone_prism,
    point_in_prism,
    segment_in_prism,
    robot_incursion,
    check_move,
)


# ── point_in_polygon_2d ──────────────────────────────────────────

def test_point_in_polygon_inside_square():
    poly = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon_2d((5, 5), poly) is True


def test_point_in_polygon_outside_square():
    poly = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon_2d((15, 5), poly) is False
    assert point_in_polygon_2d((5, -1), poly) is False


def test_point_in_polygon_triangle():
    poly = [(0, 0), (10, 0), (5, 10)]
    assert point_in_polygon_2d((5, 2), poly) is True
    assert point_in_polygon_2d((5, 15), poly) is False
    assert point_in_polygon_2d((-1, 2), poly) is False


# ── compute_zone_prism ───────────────────────────────────────────

def _make_zone(points, name="z", zone_type="exclusion"):
    z = ZoneModel(name=name, zone_type=zone_type, points=points)
    return z


def test_compute_zone_prism_floor_square():
    # Carré 100×100 au sol (Z=0)
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [100, 100, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Normale doit être (0, 0, ±1)
    assert abs(prism.normal[2]) == pytest.approx(1.0, abs=1e-6)
    assert prism.half_thickness == 50.0  # défaut


# ── point_in_prism ───────────────────────────────────────────────

def test_point_in_prism_inside():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Point au centre du triangle, à 20 mm au-dessus du sol → dans le prisme
    assert point_in_prism((30, 30, 20), prism) is True


def test_point_in_prism_too_far_above():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Point au-dessus de l'épaisseur (>50mm) → hors prisme
    assert point_in_prism((30, 30, 80), prism) is False


def test_point_in_prism_inside_2d_outside_polygon():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Z OK mais XY hors triangle
    assert point_in_prism((150, 150, 20), prism) is False


# ── segment_in_prism ─────────────────────────────────────────────

def test_segment_in_prism_zero_outside():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Segment loin du prisme → pénétration nulle
    assert segment_in_prism((200, 200, 200), (300, 300, 200), prism) == 0.0


def test_segment_in_prism_positive_inside():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [100, 100, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    # Segment qui traverse le centre du prisme → pénétration > 0
    pen = segment_in_prism((50, 50, -30), (50, 50, 30), prism)
    assert pen > 0


# ── robot_incursion ──────────────────────────────────────────────

def test_robot_incursion_zero_far():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    prism = compute_zone_prism(zone)
    joints = [(500, 500, h) for h in [0, 100, 200, 300, 400, 500, 600]]
    assert robot_incursion(joints, [prism]) == 0.0


def test_robot_incursion_positive_when_segment_inside():
    zone = _make_zone([[0, 0, 0], [200, 0, 0], [200, 200, 0], [0, 200, 0]])
    prism = compute_zone_prism(zone)
    # TCP au centre du prisme
    joints = [(0, 0, 0), (50, 50, 50), (100, 100, 100), (100, 100, 20),
              (100, 100, 10), (100, 100, 5), (100, 100, 0)]
    pen = robot_incursion(joints, [prism])
    assert pen > 0


# ── check_move ───────────────────────────────────────────────────

def test_check_move_ok_when_both_outside():
    zone = _make_zone([[0, 0, 0], [100, 0, 0], [0, 100, 0]])
    far = [(500, 500, h) for h in [0, 100, 200, 300, 400, 500, 600]]
    result = check_move(far, far, [zone])
    assert result.ok is True


def test_check_move_blocked_when_entering():
    zone = _make_zone([[0, 0, 0], [200, 0, 0], [200, 200, 0], [0, 200, 0]],
                       name="forbidden")
    far = [(500, 500, h) for h in [0, 100, 200, 300, 400, 500, 600]]
    near = [(0, 0, 0), (50, 50, 30), (100, 100, 30), (100, 100, 20),
            (100, 100, 10), (100, 100, 5), (100, 100, 0)]
    result = check_move(far, near, [zone])
    assert result.ok is False
    assert "forbidden" in result.zone_name
    assert result.incursion_mm > 0


def test_check_move_blocks_even_when_distance_decreases():
    """Blocage strict (Phase 2 hotfix) : tout mouvement avec target_in > 0 est bloqué,
    même si on se rapproche du bord. Sortir d'une zone nécessite de désactiver safety."""
    zone = _make_zone([[0, 0, 0], [200, 0, 0], [200, 200, 0], [0, 200, 0]])
    deep = [(0, 0, 0), (50, 50, 50), (100, 100, 100), (100, 100, 20),
            (100, 100, 10), (100, 100, 5), (100, 100, 0)]
    shallow = [(0, 0, 0), (50, 50, 50), (100, 100, 100), (100, 100, 40),
               (100, 100, 35), (100, 100, 30), (100, 100, 30)]
    result = check_move(deep, shallow, [zone])
    assert result.ok is False  # target_in > 0 -> bloqué quelle que soit current_in


def test_check_move_skips_hidden_zones():
    z_hidden = _make_zone([[0, 0, 0], [200, 0, 0], [200, 200, 0], [0, 200, 0]])
    z_hidden.visible = False
    # Filtrage est dans safety_manager, mais on vérifie qu'une liste vide → OK
    far = [(500, 500, h) for h in [0, 100, 200, 300, 400, 500, 600]]
    near = [(0, 0, 0), (50, 50, 30), (100, 100, 30), (100, 100, 20),
            (100, 100, 10), (100, 100, 5), (100, 100, 0)]
    result = check_move(far, near, [])  # liste vide
    assert result.ok is True
