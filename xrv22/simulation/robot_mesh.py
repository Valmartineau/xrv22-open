"""
xrv22/simulation/robot_mesh.py
───────────────────────────────
Rendu des meshes STL segmentés du RXA-200-M.

Chaque pièce est chargée une seule fois, puis transformée à chaque frame
selon les angles articulaires (FK).

Les transformations suivent l'URDF Interbotix :
  base → waist(Z) → shoulder(Y) → elbow(Y) → wrist_angle(Y) → wrist_rotate(X) → gripper

"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple

from xrv22.simulation.stl_loader import load_stl, Triangle
from xrv22.simulation.kinematics import (
    tick_to_rad, BASE_H, SHOULDER_H, UA_X, UA_Z,
    L_FARM, L_WRIST, L_TOOL,
)
from xrv22.services.logger import get_logger

_LOG = get_logger("RobotMesh")

# ── Types ────────────────────────────────────────────────────────
Vertex = Tuple[float, float, float]
TransformedTri = Tuple[Vertex, Vertex, Vertex, str]  # 3 sommets + couleur


# ── Matrice 4x4 simplifiée ──────────────────────────────────────

def _identity() -> List[List[float]]:
    return [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]

def _translate(tx: float, ty: float, tz: float) -> List[List[float]]:
    m = _identity()
    m[0][3] = tx; m[1][3] = ty; m[2][3] = tz
    return m

def _rot_z(a: float) -> List[List[float]]:
    c, s = math.cos(a), math.sin(a)
    m = _identity()
    m[0][0] = c; m[0][1] = -s
    m[1][0] = s; m[1][1] = c
    return m

def _rot_y(a: float) -> List[List[float]]:
    c, s = math.cos(a), math.sin(a)
    m = _identity()
    m[0][0] = c;  m[0][2] = s
    m[2][0] = -s; m[2][2] = c
    return m

def _rot_x(a: float) -> List[List[float]]:
    c, s = math.cos(a), math.sin(a)
    m = _identity()
    m[1][1] = c; m[1][2] = -s
    m[2][1] = s; m[2][2] = c
    return m

def _mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    """Multiplication matrice 4x4."""
    r = [[0.0]*4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            r[i][j] = sum(a[i][k]*b[k][j] for k in range(4))
    return r

def _chain(*matrices) -> List[List[float]]:
    """Chaîne de multiplications."""
    result = matrices[0]
    for m in matrices[1:]:
        result = _mul(result, m)
    return result

def _transform_pt(m: List[List[float]], p: Vertex) -> Vertex:
    """Applique matrice 4x4 à un point 3D."""
    x = m[0][0]*p[0] + m[0][1]*p[1] + m[0][2]*p[2] + m[0][3]
    y = m[1][0]*p[0] + m[1][1]*p[1] + m[1][2]*p[2] + m[1][3]
    z = m[2][0]*p[0] + m[2][1]*p[1] + m[2][2]*p[2] + m[2][3]
    return (x, y, z)


# ── Couleurs par pièce ──────────────────────────────────────────
PART_COLORS = {
    "base":     "#3a3f52",
    "shoulder": "#4a4060",
    "ua":       "#80276c",
    "forearm":  "#80276c",
    "wrist":    "#604080",
    "gripper":  "#505868",
    "prop":     "#606878",
    "bar":      "#606878",
    "finger":   "#707888",
}


# ── Chargement des meshes ───────────────────────────────────────

class RobotMeshSet:
    """Ensemble de meshes STL segmentés pour le RXA-200-M."""

    # Noms de fichiers et pièce associée
    _FILES = [
        ("RXA-200-M-1-Base.stl",         "base"),
        ("RXA-200-M-2-Shoulder.stl",     "shoulder"),
        ("RXA-200-M-3-UA.stl",           "ua"),
        ("RXA-200-M-4-Forearm.stl",      "forearm"),
        ("RXA-200-M-5-Wrist.stl",        "wrist"),
        ("RXA-200-M-6-Gripper.stl",      "gripper"),
        ("RXA-200-M-7-Gripper-Prop.stl", "prop"),
        ("RXA-200-M-8-Gripper-Bar.stl",  "bar"),
        ("RXA-200-M-9-Finger.stl",       "finger"),
    ]

    def __init__(self, mesh_dir: str):
        self._parts: Dict[str, List[Triangle]] = {}
        self._loaded = False
        self._mesh_dir = mesh_dir

    def load(self) -> bool:
        """Charge tous les STL. Retourne True si au moins la base est chargée."""
        for fname, part_name in self._FILES:
            path = os.path.join(self._mesh_dir, fname)
            if os.path.exists(path):
                tris = load_stl(path)
                self._parts[part_name] = tris
                _LOG.info("Mesh %s : %d triangles", part_name, len(tris))
            else:
                _LOG.warning("Mesh manquant : %s", path)
        self._loaded = "base" in self._parts
        return self._loaded

    @property
    def loaded(self) -> bool:
        return self._loaded

    def transform(self, positions: Dict[int, int],
                  max_tris: int = 3000) -> List[TransformedTri]:
        """Positionne chaque mesh sur les joints FK.

        Approche directe : on utilise les joints FK comme ancres et
        on construit un repère local pour chaque segment.
        Les meshes bruts sont :
          - UA : s'étend en Z+ (longueur 218mm)
          - Forearm : s'étend en Y- (longueur 211mm)
          - Wrist : s'étend en Y- (longueur 65mm)
        On les tourne pour les aligner sur la direction FK du segment.
        """
        if not self._loaded:
            return []

        from xrv22.simulation.kinematics import fk as _fk
        joints = _fk(positions)
        # [base(0), waist(1), shoulder(2), elbow(3), wrist(4), gripper(5), TCP(6)]

        a1 = tick_to_rad(positions.get(1, 2048))
        a2 = tick_to_rad(positions.get(2, 2048))
        a3 = tick_to_rad(positions.get(3, 2048))
        a4 = tick_to_rad(positions.get(4, 2048))
        a5 = tick_to_rad(positions.get(5, 2048))

        PI = math.pi
        PI_2 = PI / 2

        # ── Base : au sol, rotation waist a1 ──
        # Mesh brut centré à l'origine, RPY=(0,0,-π/2) pour aligner
        m_base = _chain(_rot_z(a1 - PI_2))

        # ── Shoulder : à J1 (haut du socle) ──
        m_shoulder = _chain(
            _translate(joints[1][0], joints[1][1], joints[1][2]),
            _rot_z(a1 - PI_2),
        )

        # ── Upper Arm : à J2, mesh Z+ → direction J2→J3 ──
        # Le mesh UA s'étend en Z (0→218). Il faut tourner Z vers la
        # direction du segment J2→J3.
        # Direction FK segment : Rz(a1) × Ry(a2) × (0,0,1) = direction Z après rotations
        # Le mesh est déjà en Z, on applique Rz(a1) × Ry(a2) × Rz(π/2) (visual RPY)
        m_ua = _chain(
            _translate(joints[2][0], joints[2][1], joints[2][2]),
            _rot_z(a1),
            _rot_y(a2),
            _rot_z(PI_2),
        )

        # ── Forearm : à J3, mesh Y- → direction J3→J4 ──
        # Mesh forearm s'étend en Y- (0→-211). Direction segment = a2+a3.
        # On doit tourner Y- vers la direction du segment.
        # Rz(π/2) tourne Y- vers X+. Puis Ry(angle) oriente X+ vers le segment.
        # Mais la direction FK est sin(a23)*h, cos(a23)*Z — c'est la même
        # mécanique que pour le UA mais en utilisant l'angle cumulé.
        a23 = a2 + a3
        m_forearm = _chain(
            _translate(joints[3][0], joints[3][1], joints[3][2]),
            _rot_z(a1),
            _rot_y(a23 - PI_2),
            _rot_z(PI_2),
        )

        # ── Wrist : à J4, mesh Y- → direction J4→J5 ──
        a235 = a23 + a5
        m_wrist = _chain(
            _translate(joints[4][0], joints[4][1], joints[4][2]),
            _rot_z(a1),
            _rot_y(a235 - PI_2),
            _rot_z(PI_2),
            _rot_y(PI),
        )

        # ── Gripper : à J5, même direction ──
        m_gripper = _chain(
            _translate(joints[5][0], joints[5][1], joints[5][2]),
            _rot_z(a1),
            _rot_y(a235 - PI_2),
            _rot_z(PI_2),
            _translate(0, 20, 0),
        )

        transforms = [
            (m_base, "base"),
            (m_shoulder, "shoulder"),
            (m_ua, "ua"),
            (m_forearm, "forearm"),
            (m_wrist, "wrist"),
            (m_gripper, "gripper"),
        ]

        result: List[TransformedTri] = []
        total_tris = sum(len(self._parts.get(name, [])) for _, name in transforms)
        step = max(1, total_tris // max_tris)

        for mat, name in transforms:
            tris = self._parts.get(name, [])
            col = PART_COLORS.get(name, "#505868")
            for idx, (v1, v2, v3) in enumerate(tris):
                if idx % step != 0:
                    continue
                t1 = _transform_pt(mat, v1)
                t2 = _transform_pt(mat, v2)
                t3 = _transform_pt(mat, v3)
                result.append((t1, t2, t3, col))

        return result


# ── Singleton ───────────────────────────────────────────────────
_instance: Optional[RobotMeshSet] = None

def get_robot_mesh() -> Optional[RobotMeshSet]:
    """Retourne l'instance unique, chargée depuis assets/rx200_meshes/."""
    global _instance
    if _instance is not None:
        return _instance

    # Chercher le dossier meshes
    import xrv22
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(xrv22.__file__)))
    mesh_dir = os.path.join(pkg_dir, "assets", "rx200_meshes")
    if not os.path.isdir(mesh_dir):
        _LOG.warning("Dossier meshes introuvable : %s", mesh_dir)
        return None

    _instance = RobotMeshSet(mesh_dir)
    if _instance.load():
        _LOG.info("Meshes RXA-200-M chargés depuis %s", mesh_dir)
    else:
        _LOG.warning("Échec chargement meshes")
        _instance = None
    return _instance
