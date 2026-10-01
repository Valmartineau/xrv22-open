"""
xrv22/simulation/dxf_loader.py
───────────────────────────────
Chargeur de fichiers DXF simplifié (ASCII DXF).
Zéro dépendance externe.

Extrait les entités géométriques :
  - LINE → segments
  - POLYLINE / LWPOLYLINE → polylignes
  - 3DFACE → triangles/quads

Retourne des listes de segments et de faces.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

Vertex = Tuple[float, float, float]
Segment = Tuple[Vertex, Vertex]
Face = List[Vertex]   # 3 ou 4 sommets

MAX_DXF_SIZE = 50 * 1024 * 1024  # 50 MB max


def _safe_float(value: str, default: float = 0.0) -> float:
    """Convertit une valeur en float sans crash."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class DxfMesh:
    """Résultat du chargement DXF."""
    __slots__ = ("segments", "faces", "polylines")

    def __init__(self):
        self.segments: List[Segment] = []
        self.faces: List[Face] = []
        self.polylines: List[List[Vertex]] = []

    @property
    def is_empty(self) -> bool:
        return not self.segments and not self.faces and not self.polylines

    def bounds(self) -> Tuple[Vertex, Vertex]:
        """Retourne (min_xyz, max_xyz)."""
        pts: List[Vertex] = []
        for s in self.segments:
            pts.extend(s)
        for f in self.faces:
            pts.extend(f)
        for pl in self.polylines:
            pts.extend(pl)
        if not pts:
            return ((0, 0, 0), (0, 0, 0))
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        return ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    def center(self) -> Vertex:
        mn, mx = self.bounds()
        return ((mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2)

    def size(self) -> float:
        mn, mx = self.bounds()
        return max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2])


def _tokenize(text: str) -> List[Tuple[int, str]]:
    """Tokenise un DXF en paires (code, valeur)."""
    lines = text.splitlines()
    tokens = []
    i = 0
    while i < len(lines) - 1:
        try:
            code = int(lines[i].strip())
        except ValueError:
            i += 1
            continue
        value = lines[i + 1].strip()
        tokens.append((code, value))
        i += 2
    return tokens


# --------------------------------------------------------------------------
# Parseurs d'entités — chacun reçoit l'index du token suivant le 0/<type>
# et retourne (résultat ou None, index du token suivant l'entité).
# --------------------------------------------------------------------------

def _parse_line(tokens: list, i: int) -> Tuple[Segment | None, int]:
    """Parse une entité LINE."""
    vals: Dict[int, float] = {}
    while i < len(tokens):
        code, value = tokens[i]
        if code == 0:  # Prochaine entité
            break
        if code in (10, 20, 30, 11, 21, 31):
            try:
                vals[code] = float(value)
            except ValueError:
                pass
        i += 1
    if 10 in vals and 11 in vals:
        p1 = (vals.get(10, 0), vals.get(20, 0), vals.get(30, 0))
        p2 = (vals.get(11, 0), vals.get(21, 0), vals.get(31, 0))
        return (p1, p2), i
    return None, i


class _LwState:
    """État d'accumulation d'une LWPOLYLINE le long de ses groupes DXF."""
    __slots__ = ("vertices", "elev", "closed", "cx", "cy")

    def __init__(self):
        self.vertices: List[Vertex] = []
        self.elev = 0.0
        self.closed = False
        self.cx = None
        self.cy = None

    def feed(self, code: int, value: str) -> None:
        """Applique un groupe (code, valeur) DXF."""
        if code == 10:
            self._flush()           # un nouveau sommet commence
            self.cx = _safe_float(value)
        elif code == 20:
            self.cy = _safe_float(value)
        elif code in (30, 38):
            self.elev = _safe_float(value)
        elif code == 70:
            self.closed = int(value) & 1 == 1

    def _flush(self) -> None:
        """Pousse le sommet courant dès que son abscisse est connue."""
        if self.cx is not None:
            self.vertices.append((self.cx, self.cy, self.elev))

    def result(self) -> List[Vertex] | None:
        """Sommets finalisés (None si aucun)."""
        if self.cx is not None and self.cy is not None:
            self.vertices.append((self.cx, self.cy, self.elev))
        if self.closed and len(self.vertices) > 1:
            self.vertices.append(self.vertices[0])
        return self.vertices or None


def _parse_lwpolyline(tokens: list, i: int) -> Tuple[List[Vertex] | None, int]:
    """Parse une entité LWPOLYLINE."""
    state = _LwState()
    while i < len(tokens):
        code, value = tokens[i]
        if code == 0:
            break
        state.feed(code, value)
        i += 1
    return state.result(), i


def _parse_polyline_vertex(tokens: list, i: int) -> Tuple[Vertex, int]:
    """Parse un sommet VERTEX (i pointe juste après le token VERTEX)."""
    vx, vy, vz = 0.0, 0.0, 0.0
    while i < len(tokens):
        c, v = tokens[i]
        if c == 0:
            break
        if c == 10:
            vx = _safe_float(v)
        elif c == 20:
            vy = _safe_float(v)
        elif c == 30:
            vz = _safe_float(v)
        i += 1
    return (vx, vy, vz), i


def _parse_polyline(tokens: list, i: int) -> Tuple[List[Vertex] | None, int]:
    """Parse une entité POLYLINE (ancienne syntaxe avec VERTEX/SEQEND)."""
    vertices: List[Vertex] = []
    while i < len(tokens):
        code, value = tokens[i]
        if code == 0 and value == "SEQEND":
            i += 1
            break
        if code == 0 and value == "VERTEX":
            vertex, i = _parse_polyline_vertex(tokens, i + 1)
            vertices.append(vertex)
            continue
        i += 1
    return (vertices if vertices else None), i


def _build_3dface(vals: Dict[int, float]) -> Face | None:
    """Construit la face (3 ou 4 sommets) depuis les groupes 3DFACE collectés."""
    face: Face = []
    for base in (10, 11, 12, 13):
        x = vals.get(base)
        y = vals.get(base + 10)
        z = vals.get(base + 20)
        if x is not None and y is not None:
            face.append((x, y or 0, z or 0))
    # Dédupliquer le 4e point s'il est identique au 3e
    if len(face) == 4 and face[3] == face[2]:
        face = face[:3]
    return face if len(face) >= 3 else None


def _parse_3dface(tokens: list, i: int) -> Tuple[Face | None, int]:
    """Parse une entité 3DFACE (3 ou 4 sommets)."""
    vals: Dict[int, float] = {}
    while i < len(tokens):
        code, value = tokens[i]
        if code == 0:
            break
        if code in (10, 20, 30, 11, 21, 31, 12, 22, 32, 13, 23, 33):
            vals[code] = _safe_float(value)
        i += 1
    return _build_3dface(vals), i


# --------------------------------------------------------------------------
# Dispatch des entités vers le mesh
# --------------------------------------------------------------------------

def _add_polyline(mesh: DxfMesh, pl: List[Vertex]) -> None:
    """Ajoute une polyligne au mesh et la convertit en segments."""
    mesh.polylines.append(pl)
    for j in range(len(pl) - 1):
        mesh.segments.append((pl[j], pl[j + 1]))


def _add_segment(mesh: DxfMesh, seg: Segment) -> None:
    mesh.segments.append(seg)


def _add_face(mesh: DxfMesh, face: Face) -> None:
    mesh.faces.append(face)


# type d'entité DXF -> (parseur, collecteur du résultat dans le mesh)
_ENTITY_PARSERS = {
    "LINE": (_parse_line, _add_segment),
    "LWPOLYLINE": (_parse_lwpolyline, _add_polyline),
    "POLYLINE": (_parse_polyline, _add_polyline),
    "3DFACE": (_parse_3dface, _add_face),
}


def _consume_entity(value: str, tokens: list, i: int, mesh: DxfMesh):
    """Parse l'entité commençant au token 0/<type> d'index i.
    Retourne le nouvel index, ou None si le type n'est pas géré."""
    entry = _ENTITY_PARSERS.get(value)
    if entry is None:
        return None
    parser, collect = entry
    result, new_i = parser(tokens, i + 1)
    if result:
        collect(mesh, result)
    return new_i


def load_dxf(path: str) -> DxfMesh:
    """Charge un fichier DXF ASCII et extrait la géométrie."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_DXF_SIZE:
        raise ValueError(
            f"Fichier DXF trop volumineux "
            f"({size // 1024 // 1024} MB, max {MAX_DXF_SIZE // 1024 // 1024} MB)")
    tokens = _tokenize(p.read_text(encoding="utf-8", errors="replace"))
    mesh = DxfMesh()

    i = 0
    in_entities = False
    while i < len(tokens) - 1:
        code, value = tokens[i]
        if code == 2 and value == "ENTITIES":
            in_entities = True
        elif code == 0 and value == "ENDSEC":
            in_entities = False

        if in_entities and code == 0:
            new_i = _consume_entity(value, tokens, i, mesh)
            if new_i is not None:
                i = new_i
                continue
        i += 1

    return mesh
