"""Géométrie utilitaire pour les zones/plans de l'onglet Visualisation.

Fonctions pures, sans état, faciles à tester. Utilisées par l'endpoint
POST /api/zones pour calculer le plane_axis et vérifier la validité des
points captés.
"""
from __future__ import annotations

import math
from typing import List, Sequence

# Tolérance pour considérer la normale alignée sur un axe principal :
# cos(20°) ≈ 0.9397. Au-delà → "oblique".
_AXIS_THRESHOLD = math.cos(math.radians(20))

# Tolérance pour la magnitude du produit vectoriel : si <= cette valeur,
# les 3 points sont considérés colinéaires.
_COLINEAR_EPS = 1e-6


class ColinearPointsError(ValueError):
    """Les 3 points fournis sont colinéaires : pas de plan défini."""


def compute_centroid(points: Sequence[Sequence[float]]) -> List[float]:
    """Centroïde (moyenne) de N points 3D."""
    n = len(points)
    sx = sum(p[0] for p in points) / n
    sy = sum(p[1] for p in points) / n
    sz = sum(p[2] for p in points) / n
    return [sx, sy, sz]


def _cross_norm(points: Sequence[Sequence[float]]) -> tuple[float, float, float, float]:
    """Renvoie (nx, ny, nz, magnitude) pour la normale au plan des 3 premiers points."""
    p0, p1, p2 = points[0], points[1], points[2]
    v1 = [p1[i] - p0[i] for i in range(3)]
    v2 = [p2[i] - p0[i] for i in range(3)]
    nx = v1[1] * v2[2] - v1[2] * v2[1]
    ny = v1[2] * v2[0] - v1[0] * v2[2]
    nz = v1[0] * v2[1] - v1[1] * v2[0]
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    return nx, ny, nz, mag


def is_colinear(points: Sequence[Sequence[float]]) -> bool:
    """True si les 3 premiers points sont colinéaires (normale nulle)."""
    _, _, _, mag = _cross_norm(points)
    return mag <= _COLINEAR_EPS


def compute_plane_axis(points: Sequence[Sequence[float]]) -> str:
    """Retourne l'axe principal détecté : 'XY' | 'XZ' | 'YZ' | 'oblique'.

    Raise ColinearPointsError si les 3 points sont colinéaires.
    """
    nx, ny, nz, mag = _cross_norm(points)
    if mag <= _COLINEAR_EPS:
        raise ColinearPointsError("Les 3 points sont colinéaires, plan indéfini")
    nx, ny, nz = nx / mag, ny / mag, nz / mag
    anx, any_, anz = abs(nx), abs(ny), abs(nz)
    if anz >= _AXIS_THRESHOLD:
        return "XY"
    if any_ >= _AXIS_THRESHOLD:
        return "XZ"
    if anx >= _AXIS_THRESHOLD:
        return "YZ"
    return "oblique"
