"""
xrv22/simulation/stl_loader.py
───────────────────────────────
Chargeur de fichiers STL (binaire + ASCII).
Zéro dépendance externe.

Retourne une liste de triangles : [((x1,y1,z1), (x2,y2,z2), (x3,y3,z3)), ...]
Les coordonnées sont en mm (unités STL).
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import List, Tuple

Triangle = Tuple[Tuple[float,float,float], Tuple[float,float,float], Tuple[float,float,float]]


def load_stl(path: str) -> List[Triangle]:
    """Charge un fichier STL (auto-détection binaire/ASCII)."""
    p = Path(path)
    data = p.read_bytes()

    # Détection ASCII vs binaire
    if data[:5] == b"solid" and b"facet" in data[:1000]:
        return _parse_ascii(data.decode("utf-8", errors="replace"))
    return _parse_binary(data)


def _parse_binary(data: bytes) -> List[Triangle]:
    """Parse un STL binaire."""
    if len(data) < 84:
        return []
    n_triangles = struct.unpack_from("<I", data, 80)[0]
    triangles: List[Triangle] = []
    offset = 84
    for _ in range(n_triangles):
        if offset + 50 > len(data):
            break
        # Skip normal (12 bytes), read 3 vertices (36 bytes), skip attr (2 bytes)
        v1 = struct.unpack_from("<fff", data, offset + 12)
        v2 = struct.unpack_from("<fff", data, offset + 24)
        v3 = struct.unpack_from("<fff", data, offset + 36)
        triangles.append((v1, v2, v3))
        offset += 50
    return triangles


def _parse_ascii(text: str) -> List[Triangle]:
    """Parse un STL ASCII."""
    triangles: List[Triangle] = []
    vertices: list = []
    for line in text.splitlines():
        line = line.strip().lower()
        if line.startswith("vertex"):
            parts = line.split()
            if len(parts) >= 4:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            if len(vertices) == 3:
                triangles.append((vertices[0], vertices[1], vertices[2]))
                vertices = []
    return triangles


def mesh_bounds(triangles: List[Triangle]) -> Tuple[
        Tuple[float,float,float], Tuple[float,float,float]]:
    """Retourne (min_xyz, max_xyz) du mesh."""
    xs, ys, zs = [], [], []
    for v1, v2, v3 in triangles:
        for v in (v1, v2, v3):
            xs.append(v[0]); ys.append(v[1]); zs.append(v[2])
    if not xs:
        return ((0,0,0), (0,0,0))
    return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def mesh_center(triangles: List[Triangle]) -> Tuple[float, float, float]:
    """Centre géométrique du mesh."""
    mn, mx = mesh_bounds(triangles)
    return ((mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2)
