"""
xrv22/simulation/kinematics.py
───────────────────────────────
Cinématique directe (FK) et inverse (IK) pour le bras XRV22.

Mapping d'axes physique (confirmé 2026-05-19) :
  - Axe 1 : rotation base (autour Z)
  - Axes 2 & 3 : épaule (deux moteurs mécaniquement couplés — un seul
                  degré de liberté ; on n'utilise que l'axe 2 en lecture,
                  l'axe 3 est piloté par le couplage)
  - Axe 4 : coude (plan vertical)
  - Axe 5 : tangage poignet (plan vertical)
  - Axe 6 : rotation poignet (ignoré pour FK/IK 2D)
  - Axe 7 : pince (ignoré pour IK)

Calibration (pose REF_UP "bras droit vers le haut", ticks relevés sur le
robot réel le 2026-05-19) : l'angle de chaque joint est mesuré comme l'écart
en ticks par rapport à REF_UP, converti en radians à l'échelle 360°/4096
(Dynamixel X-series).

Pour un parcours DXF 2D à plat, l'outil pointe vers le bas
(a2+a4+a5 = π), ce qui simplifie en IK 2 liens.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

# ── Géométrie du bras (mm) — alignée sur l'app web (Visu.tsx) ────
# Les sections poignet/outil sont raccourcies par rapport à l'URDF
# RXA-200-M pour coller au robot physique.
BASE_H      = 65.0    # base_link → shoulder_link (Z)
SHOULDER_H  = 38.91   # shoulder_link → upper_arm_link (Z)
UA_X        = 50.0    # offset horizontal épaule → coude
UA_Z        = 200.0   # offset vertical épaule → coude
L_UARM      = math.sqrt(UA_X**2 + UA_Z**2)   # ~206.2 mm (pour IK)
L_FARM      = 200.0   # avant-bras (coude → poignet)
L_WRIST     = 38.0    # poignet → rotation poignet
L_TOOL      = 44.0    # rotation poignet → TCP (bout de pince)
L_TOOL_TOTAL = L_WRIST + L_TOOL   # 82 mm — distance poignet → TCP

# Inclinaison naturelle de l'upper arm (kink horizontal UA_X) — utilisé par
# l'IK pour corriger l'écart entre l'angle motor (a2=0 → kink visible) et
# l'angle "link" du modèle 2 liens planaire (link aligné avec sa direction).
UA_ANGLE = math.atan2(UA_X, UA_Z)   # ~14°

# Rétrocompatibilité (estimation de portée maximale)
REACH = BASE_H + SHOULDER_H + UA_Z + L_FARM + L_WRIST + L_TOOL


# ── Calibration : ticks de référence à la pose "bras droit vers le haut" ──
# À ces valeurs, chaque joint est à angle = 0. Les autres positions
# s'expriment comme un écart en ticks par rapport à cette référence.
REF_UP: Dict[int, int] = {1: 2020, 2: 2081, 4: 1033, 5: 2061, 6: 2042}


# ── Conversion ticks ↔ radians (calibrée par axe) ─────────────────

def _axis_ref(axis: Optional[int]) -> int:
    """Tick de référence pour un axe (REF_UP, ou 2048 par défaut)."""
    if axis is None:
        return 2048
    return REF_UP.get(axis, 2048)


def tick_to_rad(tick: int, axis: Optional[int] = None) -> float:
    """Tick Dynamixel → radians (échelle 360°/4096, calibré sur REF_UP[axis]).

    Sans `axis` : conversion centrée sur 2048 (rétrocompat).
    """
    return math.radians((tick - _axis_ref(axis)) * 360.0 / 4096.0)


def rad_to_tick(rad: float, axis: Optional[int] = None) -> int:
    """Radians → tick Dynamixel (échelle 360°/4096, calibré sur REF_UP[axis]).

    Clampé sur [0, 4095]. Sans `axis` : centré sur 2048.
    """
    deg = math.degrees(rad)
    tick = int(round(_axis_ref(axis) + deg * 4096.0 / 360.0))
    return max(0, min(4095, tick))


def _joint_angle(positions: Dict[int, int], axis: int) -> float:
    """Angle (rad) d'un joint depuis ses positions calibrées."""
    ref = REF_UP.get(axis, 2048)
    return tick_to_rad(positions.get(axis, ref), axis=axis)


# ── Forward Kinematics ────────────────────────────────────────────

def fk(positions: Dict[int, int]) -> List[Tuple[float, float, float]]:
    """FK → 7 points 3D (mm) [base, waist, épaule, coude, poignet, rot. poignet, TCP].

    Convention : épaule = axe 2, coude = axe 4 (l'axe 3 est le slave
    couplé de l'axe 2 et n'est pas utilisé en FK). Repère Z-up.
    """
    a1 = _joint_angle(positions, 1)
    a2 = _joint_angle(positions, 2)
    a4 = _joint_angle(positions, 4)
    a5 = _joint_angle(positions, 5)
    hx, hy = math.sin(a1), math.cos(a1)

    # Base au sol
    j0 = (0.0, 0.0, 0.0)
    # Pivot waist (haut du socle)
    j1 = (0.0, 0.0, BASE_H)
    # Pivot épaule
    j2 = (0.0, 0.0, BASE_H + SHOULDER_H)

    # Upper arm : offset X=50mm + Z=200mm dans le repère épaule.
    # L'axe 2 tourne dans le plan vertical, a2=0 → bras vertical.
    s2, c2 = math.sin(a2), math.cos(a2)
    r_ua = s2 * UA_Z + c2 * UA_X   # composante horizontale (radiale)
    z_ua = c2 * UA_Z - s2 * UA_X   # composante verticale
    j3 = (j2[0] + hx * r_ua, j2[1] + hy * r_ua, j2[2] + z_ua)

    # Avant-bras : L_FARM dans la direction épaule+coude (a2+a4)
    a24 = a2 + a4
    s24, c24 = math.sin(a24), math.cos(a24)
    j4 = (j3[0] + hx * s24 * L_FARM,
          j3[1] + hy * s24 * L_FARM,
          j3[2] + c24 * L_FARM)

    # Poignet : L_WRIST dans la direction a2+a4+a5
    a245 = a24 + a5
    s245, c245 = math.sin(a245), math.cos(a245)
    j5 = (j4[0] + hx * s245 * L_WRIST,
          j4[1] + hy * s245 * L_WRIST,
          j4[2] + c245 * L_WRIST)

    # TCP : L_TOOL dans la même direction
    j6 = (j5[0] + hx * s245 * L_TOOL,
          j5[1] + hy * s245 * L_TOOL,
          j5[2] + c245 * L_TOOL)

    return [j0, j1, j2, j3, j4, j5, j6]


def fk_tcp(positions: Dict[int, int]) -> Tuple[float, float, float]:
    """Retourne uniquement le TCP (bout de pince) en mm."""
    return fk(positions)[-1]


# ── Détection de collision avec zones ────────────────────────────

def point_in_polygon_2d(px: float, py: float,
                         polygon_points: List[List[float]]) -> bool:
    """Test si un point (px, py) est dans un polygone 2D (ray casting)."""
    n = len(polygon_points)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon_points[i][0], polygon_points[i][1]
        xj, yj = polygon_points[j][0], polygon_points[j][1]
        if ((yi > py) != (yj > py)) and \
           (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def check_zone_collision(positions: Dict[int, int],
                          zones: list) -> Optional[str]:
    """Vérifie si le TCP entre dans une zone d'exclusion.
    Retourne le nom de la zone en collision, ou None si OK."""
    tcp = fk_tcp(positions)
    tx, ty = tcp[0], tcp[1]
    for zone in zones:
        if zone.zone_type != "exclusion":
            continue
        if len(zone.points) < 3:
            continue
        if point_in_polygon_2d(tx, ty, zone.points):
            return zone.name
    return None


# ── Inverse Kinematics ────────────────────────────────────────────
#
# Le modèle est planaire (2 liens upper_arm + forearm) une fois fixée
# l'orientation de l'outil. La rotation base (a1) résout la composante
# en azimuth. L'IK travaille en angles relatifs à la pose REF_UP, et
# convertit ensuite en ticks via REF_UP[axis] + offset.

def _solve_planar_two_link(D: float, D_sq: float) -> Optional[float]:
    """Loi des cosinus : angle coude (a4) pour atteindre une distance D
    avec les deux liens L_UARM, L_FARM. Retourne None si hors portée."""
    reach_max = L_UARM + L_FARM
    reach_min = abs(L_UARM - L_FARM)
    if D > reach_max or D < reach_min:
        return None
    cos_a4 = (D_sq - L_UARM**2 - L_FARM**2) / (2.0 * L_UARM * L_FARM)
    cos_a4 = max(-1.0, min(1.0, cos_a4))
    return math.atan2(math.sqrt(1.0 - cos_a4**2), cos_a4)


def _angles_to_ticks(a1: float, a2: float, a4: float, a5: float,
                     gripper_tick: int) -> Optional[Dict[int, int]]:
    """Convertit les 4 angles en ticks. Retourne None si un angle dépasse ±150°.

    Axe 3 = même tick que l'axe 2 (mécanique couplée ; sera de toute façon
    réécrasé par RobotController._apply_coupling). Axe 6 neutre.
    """
    limit = math.radians(150)
    if max(abs(a1), abs(a2), abs(a4), abs(a5)) > limit:
        return None
    tick2 = rad_to_tick(a2, axis=2)
    return {
        1: rad_to_tick(a1, axis=1),
        2: tick2,
        3: tick2,                       # slave couplé de l'axe 2
        4: rad_to_tick(a4, axis=4),
        5: rad_to_tick(a5, axis=5),
        6: REF_UP.get(6, 2048),         # rotation poignet neutre
        7: gripper_tick,
    }


def ik_tool_angle(x: float, y: float, z: float,
                   tool_angle_rad: float = math.pi,
                   gripper_tick: int = 2048) -> Optional[Dict[int, int]]:
    """IK avec angle d'outil configurable.

    tool_angle_rad : angle total a2+a4+a5 par rapport à la verticale.
      - π   = outil vers le bas
      - π/2 = outil horizontal
      - 0   = outil vers le haut

    Retourne les positions moteur ou None si hors portée / hors limites.
    """
    r_horiz = math.sqrt(x * x + y * y)
    a1 = math.atan2(x, y) if r_horiz >= 1.0 else 0.0

    # Position du poignet (épaule comme origine planaire) en tenant compte
    # de l'orientation de l'outil
    shoulder_h = BASE_H + SHOULDER_H
    wrist_r = r_horiz - L_TOOL_TOTAL * math.sin(tool_angle_rad)
    wrist_h = z - shoulder_h - L_TOOL_TOTAL * math.cos(tool_angle_rad)

    D_sq = wrist_r * wrist_r + wrist_h * wrist_h
    D = math.sqrt(D_sq)

    a4_planar = _solve_planar_two_link(D, D_sq)
    if a4_planar is None:
        return None

    alpha = math.atan2(wrist_r, wrist_h)
    beta = math.atan2(L_FARM * math.sin(a4_planar),
                      L_UARM + L_FARM * math.cos(a4_planar))
    a2_planar = alpha - beta

    # Correction de la kink naturelle de l'upper arm (UA_X horizontal) :
    # l'angle motor d'a2 vaut 0 quand l'upper arm est à UA_ANGLE de la
    # verticale, donc on retire UA_ANGLE du « link 1 » du modèle planaire.
    # Le coude motor compense pour conserver la direction de l'avant-bras.
    a2_motor = a2_planar - UA_ANGLE
    a4_motor = a4_planar + UA_ANGLE
    a5_motor = tool_angle_rad - a2_motor - a4_motor

    return _angles_to_ticks(a1, a2_motor, a4_motor, a5_motor, gripper_tick)


def ik_tool_down(x: float, y: float, z: float,
                  gripper_tick: int = 2048) -> Optional[Dict[int, int]]:
    """IK avec outil pointant vers le bas (perpendiculaire au sol)."""
    return ik_tool_angle(x, y, z, tool_angle_rad=math.pi,
                         gripper_tick=gripper_tick)


# ── Utilitaires parcours ─────────────────────────────────────────

def _dist2d(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def dxf_to_waypoints(segments, scale: float = 1.0,
                      offset: Tuple[float, float, float] = (0, 0, 0),
                      z_surface: float = 0.0,
                      tool_angle: float = math.pi,
                      gripper_tick: int = 2048
                      ) -> List[Dict[int, int]]:
    """Convertit des segments DXF en positions moteur (waypoints).

    Parcourt les extrémités de chaque segment, élimine les doublons
    consécutifs, et calcule l'IK pour chaque point. Les points hors portée
    sont ignorés (avec log).
    """
    from xrv22.services.logger import get_logger
    _LOG = get_logger("Kinematics")

    # Collecter les points dans l'ordre des segments
    raw_pts: List[Tuple[float, float]] = []
    for p1, p2 in segments:
        pt1 = (p1[0] * scale + offset[0], p1[1] * scale + offset[1])
        pt2 = (p2[0] * scale + offset[0], p2[1] * scale + offset[1])
        if not raw_pts or _dist2d(raw_pts[-1], pt1) > 0.5:
            raw_pts.append(pt1)
        if _dist2d(raw_pts[-1], pt2) > 0.5:
            raw_pts.append(pt2)

    waypoints: List[Dict[int, int]] = []
    skipped = 0
    for px, py in raw_pts:
        result = ik_tool_angle(px, py, z_surface,
                                tool_angle_rad=tool_angle,
                                gripper_tick=gripper_tick)
        if result is None:
            skipped += 1
            _LOG.warning("IK hors portée : (%.1f, %.1f, %.1f)", px, py, z_surface)
            continue
        waypoints.append(result)

    if skipped:
        _LOG.warning("IK : %d points ignorés (hors portée) sur %d",
                      skipped, len(raw_pts))
    _LOG.info("DXF → %d waypoints moteur", len(waypoints))
    return waypoints


# ── Lissage de trajectoire (Catmull-Rom) ──────────────────────────

def _catmull_rom(p0: float, p1: float, p2: float, p3: float,
                 t: float) -> float:
    """Interpolation Catmull-Rom entre p1 et p2, t ∈ [0,1]."""
    return 0.5 * (
        2*p1
        + (-p0 + p2) * t
        + (2*p0 - 5*p1 + 4*p2 - p3) * t*t
        + (-p0 + 3*p1 - 3*p2 + p3) * t*t*t
    )


def smooth_trajectory(waypoints: List[Dict[int, int]],
                      subdivisions: int = 3
                      ) -> List[Dict[int, int]]:
    """Lisse une trajectoire (liste de positions ticks) par spline Catmull-Rom.

    Insère `subdivisions` points intermédiaires entre chaque paire. Les axes
    sont interpolés indépendamment (dans l'espace articulaire).
    """
    if len(waypoints) < 3 or subdivisions < 1:
        return list(waypoints)

    # Étendre aux bords (duplication du premier/dernier point)
    extended = [waypoints[0]] + list(waypoints) + [waypoints[-1]]
    result: List[Dict[int, int]] = []
    motor_ids = sorted(waypoints[0].keys())

    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i-1], extended[i], extended[i+1], extended[i+2]
        result.append(dict(p1))  # point original
        for s in range(1, subdivisions + 1):
            t = s / (subdivisions + 1)
            pt = {}
            for mid in motor_ids:
                v = _catmull_rom(
                    p0.get(mid, 2048), p1.get(mid, 2048),
                    p2.get(mid, 2048), p3.get(mid, 2048), t)
                pt[mid] = max(0, min(4095, int(round(v))))
            result.append(pt)

    # Dernier point original
    result.append(dict(waypoints[-1]))
    return result
