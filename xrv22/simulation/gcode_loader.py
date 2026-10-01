"""
xrv22/simulation/gcode_loader.py
=================================
Parseur G-code basique pour XRV22.

Supporte les commandes courantes :
  G0/G1  — déplacement linéaire (rapide/travail)
  G2/G3  — arcs circulaires (approximés en segments)
  G28    — retour origine
  G90/G91 — mode absolu / relatif
  F      — vitesse (feed rate mm/min)
  M3/M5  — outil ON/OFF (mappé sur la pince)

Retourne une liste de waypoints (x, y, z, feed_rate)
utilisables par la cinématique inverse.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from xrv22.services.logger import get_logger

_LOG = get_logger("XRV22.GCodeLoader")


@dataclass
class GCodeWaypoint:
    """Un point de passage G-code."""
    x: float
    y: float
    z: float
    feed_rate: float = 1000.0   # mm/min
    is_rapid: bool = False      # G0 = rapide
    tool_on: bool = True        # M3 = on, M5 = off


@dataclass
class GCodeProgram:
    """Programme G-code parsé."""
    waypoints: List[GCodeWaypoint] = field(default_factory=list)
    bounds_min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    line_count: int = 0
    errors: List[str] = field(default_factory=list)


@dataclass
class _ParseState:
    """État courant du parseur le long du flux G-code."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    feed: float = 1000.0
    tool_on: bool = True
    absolute: bool = True  # G90 absolu / G91 relatif


# Regex pour extraire les paramètres G-code
MAX_GCODE_SIZE = 20 * 1024 * 1024  # 20 MB max

_PARAM_RE = re.compile(r'([A-Z])([+-]?\d+\.?\d*)')


def _parse_params(line: str) -> dict:
    """Extrait les paramètres d'une ligne G-code."""
    return {m.group(1): float(m.group(2)) for m in _PARAM_RE.finditer(line)}


def _arc_to_segments(cx: float, cy: float,
                     x0: float, y0: float,
                     x1: float, y1: float,
                     z: float, clockwise: bool,
                     segments: int = 16) -> List[Tuple[float, float, float]]:
    """Approxime un arc circulaire en segments linéaires."""
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    r = math.hypot(x0 - cx, y0 - cy)

    if clockwise:
        if a1 >= a0:
            a1 -= 2 * math.pi
    else:
        if a1 <= a0:
            a1 += 2 * math.pi

    pts = []
    for i in range(1, segments + 1):
        t = i / segments
        a = a0 + (a1 - a0) * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return pts


# --------------------------------------------------------------------------
# Lecture fichier
# --------------------------------------------------------------------------

def _read_gcode_lines(filepath: str, prog: GCodeProgram) -> Optional[List[str]]:
    """Lit les lignes du fichier. Renseigne prog.errors et retourne None en cas d'échec."""
    p = Path(filepath)
    try:
        fsize = p.stat().st_size
    except OSError as exc:
        prog.errors.append(f"Lecture fichier : {exc}")
        return None
    if fsize > MAX_GCODE_SIZE:
        prog.errors.append(
            f"Fichier G-code trop volumineux "
            f"({fsize // 1024 // 1024} MB, max {MAX_GCODE_SIZE // 1024 // 1024} MB)")
        return None
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError as exc:
        prog.errors.append(f"Lecture fichier : {exc}")
        return None


def _clean_line(raw: str) -> str:
    """Normalise une ligne : majuscules, sans commentaire ';' ni '(...)'."""
    line = raw.strip().upper()
    if ";" in line:
        line = line[:line.index(";")]
    if "(" in line:
        line = line[:line.index("(")]
    return line.strip()


# --------------------------------------------------------------------------
# Traitement d'une ligne
# --------------------------------------------------------------------------

def _apply_m_command(state: _ParseState, mi: int) -> None:
    """M3 = outil ON (pince), M5 = outil OFF."""
    if mi == 3:
        state.tool_on = True
    elif mi == 5:
        state.tool_on = False


def _resolve_gcode(params: dict) -> Optional[int]:
    """Code G effectif : explicite, ou G1 implicite si la ligne ne porte que des coords."""
    if "G" in params:
        return int(params["G"])
    if any(k in params for k in ("X", "Y", "Z")):
        return 1  # mouvement implicite -> G1
    return None


def _handle_home(state: _ParseState, prog: GCodeProgram) -> None:
    """G28 : retour à l'origine."""
    state.x = state.y = state.z = 0.0
    prog.waypoints.append(
        GCodeWaypoint(0, 0, 0, state.feed, is_rapid=True, tool_on=state.tool_on))


def _handle_move(state: _ParseState, gi: int, params: dict, prog: GCodeProgram) -> None:
    """G0 (rapide) / G1 (travail) : déplacement linéaire."""
    if state.absolute:
        nx = params.get("X", state.x)
        ny = params.get("Y", state.y)
        nz = params.get("Z", state.z)
    else:
        nx = state.x + params.get("X", 0.0)
        ny = state.y + params.get("Y", 0.0)
        nz = state.z + params.get("Z", 0.0)
    state.x, state.y, state.z = nx, ny, nz
    prog.waypoints.append(
        GCodeWaypoint(nx, ny, nz, state.feed, is_rapid=(gi == 0), tool_on=state.tool_on))


def _handle_arc(state: _ParseState, gi: int, params: dict, prog: GCodeProgram) -> None:
    """G2 (horaire) / G3 (anti-horaire) : arc approximé en segments."""
    nx = params.get("X", state.x)
    ny = params.get("Y", state.y)
    nz = params.get("Z", state.z)
    # Centre relatif au point courant via I, J
    ci = state.x + params.get("I", 0.0)
    cj = state.y + params.get("J", 0.0)
    arc_pts = _arc_to_segments(
        ci, cj, state.x, state.y, nx, ny, nz, clockwise=(gi == 2))
    for ax, ay, az in arc_pts:
        prog.waypoints.append(
            GCodeWaypoint(ax, ay, az, state.feed, is_rapid=False, tool_on=state.tool_on))
    state.x, state.y, state.z = nx, ny, nz


# G0/G1 -> mouvement linéaire, G2/G3 -> arc
_MOVE_HANDLERS = {0: _handle_move, 1: _handle_move, 2: _handle_arc, 3: _handle_arc}


def _process_line(state: _ParseState, line: str, prog: GCodeProgram) -> None:
    """Applique une ligne G-code nettoyée à l'état courant."""
    params = _parse_params(line)

    # Commande M : traitée puis ligne ignorée pour le reste
    if "M" in params:
        _apply_m_command(state, int(params["M"]))
        return

    gi = _resolve_gcode(params)
    if gi is None:
        return

    # Changement de mode absolu / relatif
    if gi in (90, 91):
        state.absolute = (gi == 90)
        return

    if gi == 28:
        _handle_home(state, prog)
        return

    if "F" in params:
        state.feed = params["F"]

    handler = _MOVE_HANDLERS.get(gi)
    if handler is not None:
        handler(state, gi, params, prog)


def _compute_bounds(prog: GCodeProgram) -> None:
    """Renseigne bounds_min / bounds_max à partir des waypoints."""
    if not prog.waypoints:
        return
    xs = [w.x for w in prog.waypoints]
    ys = [w.y for w in prog.waypoints]
    zs = [w.z for w in prog.waypoints]
    prog.bounds_min = (min(xs), min(ys), min(zs))
    prog.bounds_max = (max(xs), max(ys), max(zs))


def load_gcode(filepath: str) -> GCodeProgram:
    """Parse un fichier G-code et retourne un GCodeProgram."""
    prog = GCodeProgram()

    lines = _read_gcode_lines(filepath, prog)
    if lines is None:
        return prog
    prog.line_count = len(lines)

    state = _ParseState()
    for raw in lines:
        line = _clean_line(raw)
        if line:
            _process_line(state, line, prog)

    _compute_bounds(prog)

    _LOG.info("G-code chargé : %d lignes → %d waypoints, bornes=%s→%s",
              prog.line_count, len(prog.waypoints),
              prog.bounds_min, prog.bounds_max)
    return prog


def gcode_to_waypoints(prog: GCodeProgram,
                       scale: float = 1.0,
                       offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
                       ) -> List[Tuple[float, float, float, float]]:
    """Convertit un GCodeProgram en liste (x, y, z, feed_mm_min) pour IK."""
    result = []
    for wp in prog.waypoints:
        result.append((
            wp.x * scale + offset[0],
            wp.y * scale + offset[1],
            wp.z * scale + offset[2],
            wp.feed_rate,
        ))
    return result
