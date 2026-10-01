# xrv22/core/collision_checker.py
"""Collision check corps complet du robot contre zones d'exclusion.

Module pur : aucune dépendance hardware, sérialisable, testable.
Consommé par safety_manager.validate_move.

Modèle : chaque zone d'exclusion est un PRISME ÉPAIS = polygone 3D (3-4
points coplanaires) extrudé de ±half_thickness mm de chaque côté de la
normale au plan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from xrv22.library.models import ZoneModel

Vec3 = Tuple[float, float, float]
Pt2 = Tuple[float, float]


def positions_to_joints_3d(positions: Dict[int, int]) -> List[Vec3]:
    """Convertit positions moteur (ticks) → 7 joints 3D via FK simulation."""
    from xrv22.simulation.kinematics import fk
    return [tuple(p) for p in fk(positions)]


@dataclass
class ZonePrism:
    """Prisme épais précalculé pour une zone d'exclusion."""
    zone_id: str
    zone_name: str
    points_2d: List[Pt2] = field(default_factory=list)
    origin: Vec3 = (0.0, 0.0, 0.0)
    normal: Vec3 = (0.0, 0.0, 1.0)
    tangent_u: Vec3 = (1.0, 0.0, 0.0)
    tangent_v: Vec3 = (0.0, 1.0, 0.0)
    half_thickness: float = 50.0


@dataclass
class CheckResult:
    ok: bool
    reason: str = ""
    incursion_mm: float = 0.0
    zone_id: str = ""
    zone_name: str = ""


def _vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _vec_norm(v: Vec3) -> float:
    return math.sqrt(_vec_dot(v, v))


def _vec_normalize(v: Vec3) -> Vec3:
    n = _vec_norm(v)
    if n < 1e-9:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def point_in_polygon_2d(p: Pt2, poly: Sequence[Pt2]) -> bool:
    """Test point-dans-polygone 2D par ray casting (axe X+)."""
    x, y = p
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)):
            x_intersect = xi + (y - yi) * (xj - xi) / (yj - yi + 1e-12)
            if x < x_intersect:
                inside = not inside
        j = i
    return inside


def compute_zone_prism(zone: ZoneModel, half_thickness: float = 50.0) -> ZonePrism:
    """Précalcule le prisme épais d'une zone (3-4 points coplanaires)."""
    pts = [tuple(p) for p in zone.points]
    if len(pts) < 3:
        return ZonePrism(zone_id=zone.id, zone_name=zone.name,
                         half_thickness=half_thickness)
    p0, p1, p2 = pts[0], pts[1], pts[2]
    v1 = _vec_sub(p1, p0)
    v2 = _vec_sub(p2, p0)
    n = _vec_normalize(_vec_cross(v1, v2))
    tu = _vec_normalize(v1)
    tv = _vec_cross(n, tu)
    points_2d: List[Pt2] = []
    for p in pts:
        d = _vec_sub(p, p0)
        u = _vec_dot(d, tu)
        v = _vec_dot(d, tv)
        points_2d.append((u, v))
    return ZonePrism(
        zone_id=zone.id, zone_name=zone.name,
        points_2d=points_2d,
        origin=p0, normal=n,
        tangent_u=tu, tangent_v=tv,
        half_thickness=half_thickness,
    )


def point_in_prism(p: Vec3, prism: ZonePrism) -> bool:
    """True si p est dans le prisme épais."""
    d = _vec_sub(p, prism.origin)
    dist_plan = _vec_dot(d, prism.normal)
    if abs(dist_plan) > prism.half_thickness:
        return False
    u = _vec_dot(d, prism.tangent_u)
    v = _vec_dot(d, prism.tangent_v)
    return point_in_polygon_2d((u, v), prism.points_2d)


def _incursion_depth(p: Vec3, prism: ZonePrism) -> float:
    """Approx de la profondeur d'incursion (mm) d'un point dans le prisme.
    On retourne (half_thickness - |dist_plan|) si dedans, sinon 0.
    Estimation grossière mais monotone (utile pour 'distance décroît').
    """
    d = _vec_sub(p, prism.origin)
    dist_plan = _vec_dot(d, prism.normal)
    return max(0.0, prism.half_thickness - abs(dist_plan))


def segment_in_prism(a: Vec3, b: Vec3, prism: ZonePrism, samples: int = 10) -> float:
    """Profondeur d'incursion max d'un segment dans le prisme (0 si dehors)."""
    max_pen = 0.0
    for i in range(samples + 1):
        t = i / samples
        p = (a[0] + t * (b[0] - a[0]),
             a[1] + t * (b[1] - a[1]),
             a[2] + t * (b[2] - a[2]))
        if point_in_prism(p, prism):
            pen = _incursion_depth(p, prism)
            if pen > max_pen:
                max_pen = pen
    return max_pen


def robot_incursion(joints_3d: Sequence[Vec3], prisms: Sequence[ZonePrism]) -> float:
    """Profondeur d'incursion max du corps complet du robot (6 segments)."""
    max_pen = 0.0
    for i in range(len(joints_3d) - 1):
        a, b = joints_3d[i], joints_3d[i + 1]
        for prism in prisms:
            pen = segment_in_prism(a, b, prism)
            if pen > max_pen:
                max_pen = pen
    return max_pen


def _find_worst_zone(joints_3d: Sequence[Vec3],
                     zones: Sequence[ZoneModel],
                     prisms: Sequence[ZonePrism]) -> ZoneModel:
    """Renvoie la zone avec la pénétration max (pour message d'erreur)."""
    worst_pen = -1.0
    worst = zones[0]
    for zone, prism in zip(zones, prisms):
        pen = 0.0
        for i in range(len(joints_3d) - 1):
            p = segment_in_prism(joints_3d[i], joints_3d[i + 1], prism)
            if p > pen:
                pen = p
        if pen > worst_pen:
            worst_pen = pen
            worst = zone
    return worst


def check_move(current_joints: Sequence[Vec3],
               target_joints: Sequence[Vec3],
               zones: Sequence[ZoneModel]) -> CheckResult:
    """Décide si un mouvement est autorisé (blocage strict).

    Tout mouvement qui laisse le robot avec une incursion > 0 est bloqué.
    Si le robot est déjà dans une zone, désactiver safety pour le sortir.
    """
    if not zones:
        return CheckResult(ok=True)
    prisms = [compute_zone_prism(z) for z in zones]
    target_in = robot_incursion(target_joints, prisms)
    if target_in <= 0:
        return CheckResult(ok=True, incursion_mm=0.0)
    worst = _find_worst_zone(target_joints, zones, prisms)
    return CheckResult(
        ok=False,
        reason=f"Incursion dans '{worst.name}' ({target_in:.1f} mm)",
        incursion_mm=target_in,
        zone_id=worst.id,
        zone_name=worst.name,
    )
