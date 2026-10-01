"""
xr200/ui/tab_visu.py
─────────────────────
Onglet Visualisation 3D — rendu orbitable temps réel du bras XR200.

100% Tkinter Canvas, zéro dépendance externe.
  • Vue 3D principale  : orbit caméra (glisser + molette)
  • Vues ortho mini    : TOP (XY) · FRONT (XZ)
  • Trace outil        : trajectoire TCP colorée
  • Jauges arcs        : angle/tick par axe avec indicateur circulaire
  • Sol perspectif     : grille + ombres portées
  • HUD               : az/el · axes XYZ

CC max : 8
"""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple
from collections import deque

from xrv22.theme import theme as T
from xrv22.core.state_store import store
from xrv22.robots.robot_registry import registry
from xrv22.library.library_manager import library
from xrv22.library.models import ZoneModel
from xrv22.config import MOTOR_IDS_DEFAULT as MOTOR_IDS, PINCE_AXIS, MOTOR_CENTER
from xrv22.simulation.dxf_loader import load_dxf, DxfMesh
from xrv22.simulation.kinematics import dxf_to_waypoints, ik_tool_angle
from xrv22.simulation.robot_mesh import get_robot_mesh
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("UI.Visu")

# ═══════════════════════════════════════════════════════════════════
# GÉOMÉTRIE DU BRAS (mm) — URDF RXA-200-M
# ═══════════════════════════════════════════════════════════════════
from xrv22.simulation.kinematics import (
    BASE_H, SHOULDER_H, UA_X, UA_Z, L_UARM,
    L_FARM, L_WRIST, L_TOOL, REACH,
    fk as _fk_module,
)
# Réexport pour usage local
_BASE_TOTAL = BASE_H + SHOULDER_H  # hauteur pivot épaule

FLOOR_R     = 360   # rayon grille sol (mm)
FLOOR_STEP  = 100   # pas grille (mm)
TRAIL_LEN   = 120   # longueur trace TCP

# ═══════════════════════════════════════════════════════════════════
# PALETTE
# ═══════════════════════════════════════════════════════════════════
AXIS_COLORS = {
    1: T.C_AMB,    2: T.C_MAG,    3: T.C_MAG_2,
    4: T.C_INFO,   5: T.C_OK,     6: T.C_ERR,
}
AXIS_NAMES = {
    1: "Base",  2: "Épaule",  3: "Coude",
    4: "Roulis", 5: "Tangage", 6: "Pince",
}

CANVAS_BG   = "#141824"
LINK_W      = 5
JOINT_R     = 6
DEFAULT_AZ  = math.radians(38)
DEFAULT_EL  = math.radians(24)

_STATE_ICONS = {
    "READY":          ("● READY",      T.C_OK),
    "MOVING":         ("◉ MOVING",     T.C_INFO),
    "ERROR":          ("⊗ ERROR",      T.C_ERR),
    "EMERGENCY_STOP": ("🛑 E-STOP",    T.C_ERR),
    "TORQUE_OFF":     ("◎ TORQUE OFF", T.C_AMB),
    "IDLE":           ("⚬ IDLE",       T.TEXT_DIM),
    "DISCONNECTED":   ("⚬ DISC.",      T.TEXT_DIM),
}


# ═══════════════════════════════════════════════════════════════════
# CINÉMATIQUE DIRECTE (simplifiée, bras planaire + rotation base)
# ═══════════════════════════════════════════════════════════════════

def _deg(tick: int) -> float:
    return (tick - 2048) * 300.0 / 4096.0

def _rad(tick: int) -> float:
    return math.radians(_deg(tick))


def fk(pos: Dict[int, int]) -> List[Tuple[float, float, float]]:
    """FK 6-DOF — délègue à kinematics.py (source de vérité URDF)."""
    return _fk_module(pos)


# ═══════════════════════════════════════════════════════════════════
# UTILITAIRES COULEUR
# ═══════════════════════════════════════════════════════════════════

def _dim(col: str, f: float) -> str:
    """Scale les composantes R/G/B d'un #rrggbb par facteur f."""
    h = col.lstrip("#")
    r = min(255, int(int(h[0:2], 16) * f))
    g = min(255, int(int(h[2:4], 16) * f))
    b = min(255, int(int(h[4:6], 16) * f))
    return f"#{r:02x}{g:02x}{b:02x}"

def _lerp_col(a: str, b: str, t: float) -> str:
    """Interpolation linéaire entre deux couleurs #rrggbb."""
    ah, bh = a.lstrip("#"), b.lstrip("#")
    r = int(int(ah[0:2],16)*(1-t) + int(bh[0:2],16)*t)
    g = int(int(ah[2:4],16)*(1-t) + int(bh[2:4],16)*t)
    b_ = int(int(ah[4:6],16)*(1-t) + int(bh[4:6],16)*t)
    return f"#{r:02x}{g:02x}{b_:02x}"


# ═══════════════════════════════════════════════════════════════════
# CAMÉRA ORBIT
# ═══════════════════════════════════════════════════════════════════

class _Cam:
    """Projection orthographique + caméra orbitale (az, el, scale)."""
    __slots__ = ("az", "el", "scale")

    def __init__(self):
        self.az    = DEFAULT_AZ
        self.el    = DEFAULT_EL
        self.scale = 1.0   # calculé dynamiquement (px/mm)

    def reset(self):
        self.az, self.el = DEFAULT_AZ, DEFAULT_EL

    def project(self, x: float, y: float, z: float,
                cx: int, cy: int) -> Tuple[int, int, float]:
        """Retourne (screen_x, screen_y, depth)."""
        # Rotation azimuth (autour Z)
        x1 =  x * math.cos(self.az) + y * math.sin(self.az)
        y1 = -x * math.sin(self.az) + y * math.cos(self.az)
        # Rotation élévation (inclinaison)
        y2 =  y1 * math.cos(self.el) - z * math.sin(self.el)
        z2 =  y1 * math.sin(self.el) + z * math.cos(self.el)
        return (
            int(cx + x1 * self.scale),
            int(cy - z2 * self.scale),
            y2,
        )


# ═══════════════════════════════════════════════════════════════════
# CANVAS 3D PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

class _Canvas3D(tk.Canvas):
    """
    CC=8 — Vue 3D orbitable.
    Glisser-souris = orbit · Molette = zoom.
    """

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=CANVAS_BG, highlightthickness=0, **kw)
        self.cam = _Cam()
        self._cx = self._cy = 300
        self._trail: deque = deque(maxlen=TRAIL_LEN)
        self._show_trail  = True
        self._show_floor  = True
        self._show_zones  = True
        self._zones: List[ZoneModel] = []
        self._meshes: List[dict] = []   # [{"triangles": [...], "offset": (x,y,z), "scale": f, "color": str}]
        self._dxf_meshes: List[dict] = []  # [{"mesh": DxfMesh, "offset": (x,y,z), "scale": f, "color": str}]
        self._dxf_waypoint_preview: List[Tuple[float, float, float, bool]] = []
        self._drag: Optional[Tuple[int, int, float, float]] = None
        self._zone_polys: List[Tuple[ZoneModel, List[Tuple[int, int]]]] = []
        self._on_zone_context: Optional[Callable] = None  # callback(zone, event)
        self._show_mesh = True
        self._robot_mesh = get_robot_mesh()
        self._selected_joint: Optional[int] = None  # index joint sélectionné
        self._joint_hitboxes: List[Tuple[int, int, int, int, int]] = []  # (ji, mid, px, py, r)
        self._joint_drag: Optional[Tuple[int, int, int, int]] = None  # (ji, mid, cx, cy)
        self._on_joint_drag: Optional[Callable] = None  # callback(motor_id, delta_ticks)

        self.bind("<Configure>",       self._on_cfg)
        self.bind("<ButtonPress-1>",   self._press)
        self.bind("<B1-Motion>",       self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>",          lambda _: self._deselect_joint())
        self.bind("<MouseWheel>",      self._wheel)
        self.bind("<Button-4>",        lambda _: self._zoom(1.12))
        self.bind("<Button-5>",        lambda _: self._zoom(0.88))
        self.bind("<Button-2>",        self._on_right_click)
        self.bind("<Button-3>",        self._on_right_click)

    # ── Caméra ─────────────────────────────────────────────────────

    def _on_cfg(self, e):
        self._cx = e.width  // 2
        self._cy = int(e.height * 0.56)
        self.cam.scale = min(e.width, e.height) * 0.38 / REACH

    def _press(self, e):
        # Vérifier si on clique sur un joint
        for ji, mid, px, py, r in self._joint_hitboxes:
            dx, dy = e.x - px, e.y - py
            if dx*dx + dy*dy <= r*r:
                self._selected_joint = ji
                self._joint_drag = (ji, mid, e.x, e.y)
                self.config(cursor="hand2")
                return
        # Sinon : orbit caméra
        self._joint_drag = None
        self._drag = (e.x, e.y, self.cam.az, self.cam.el)
        self.config(cursor="fleur")

    def _move(self, e):
        if self._joint_drag:
            ji, mid, x0, y0 = self._joint_drag
            # Delta horizontal → ticks (sensibilité ~3 ticks/pixel)
            delta_px = e.x - x0
            delta_ticks = int(delta_px * 3)
            self._joint_drag = (ji, mid, e.x, e.y)
            if self._on_joint_drag and delta_ticks != 0:
                self._on_joint_drag(mid, delta_ticks)
            return
        if not self._drag:
            return
        x0, y0, az0, el0 = self._drag
        self.cam.az = az0 - (e.x - x0) * 0.007
        el = el0 + (e.y - y0) * 0.005
        self.cam.el = max(math.radians(-6), min(math.radians(88), el))

    def _release(self, _):
        self._drag = None
        self._joint_drag = None
        self.config(cursor="")

    def _deselect_joint(self):
        self._selected_joint = None

    def _wheel(self, e):
        self._zoom(1.1 if e.delta > 0 else 0.9)

    def _zoom(self, f: float):
        self.cam.scale = max(0.12, min(4.5, self.cam.scale * f))

    def clear_trail(self):
        self._trail.clear()

    def _on_right_click(self, event):
        """Hit-test sur les zones projetées, appelle le callback si trouvé."""
        if not self._on_zone_context:
            return
        for zone, poly in reversed(self._zone_polys):
            if self._point_in_poly_2d(event.x, event.y, poly):
                self._on_zone_context(zone, event)
                return

    @staticmethod
    def _point_in_poly_2d(px: int, py: int,
                          poly: List[Tuple[int, int]]) -> bool:
        """Ray-casting 2D pour hit-test écran."""
        n = len(poly)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if ((yi > py) != (yj > py)) and \
               (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    # ── Rendu principal ────────────────────────────────────────────

    def set_zones(self, zones: List[ZoneModel]) -> None:
        """Met à jour la liste des zones à dessiner."""
        self._zones = zones

    def add_dxf(self, mesh: DxfMesh, offset: Tuple[float,float,float] = (0,0,0),
                scale: float = 1.0, color: str = "#5588aa") -> int:
        """Ajoute un DXF à afficher. Retourne l'index."""
        self._dxf_meshes.append({
            "mesh": mesh, "offset": offset,
            "scale": scale, "color": color,
        })
        return len(self._dxf_meshes) - 1

    def clear_meshes(self) -> None:
        self._meshes.clear()
        self._dxf_meshes.clear()

    def draw(self, positions: Dict[int, int]) -> Tuple[float, float, float]:
        """CC=6 — Redessine tout. Retourne TCP (x, y, z) mm."""
        self.delete("all")
        if self._cx < 10:
            return (0.0, 0.0, 0.0)

        joints = fk(positions)
        tcp = joints[-1]

        if self._show_trail:
            self._trail.append(tcp)

        if self._show_floor:
            self._draw_floor()

        if self._show_zones:
            self._draw_zones(tcp)

        self._draw_meshes()
        self._draw_dxf()
        self._draw_dxf_preview()
        self._draw_trail()

        if self._show_mesh and self._robot_mesh:
            self._draw_robot_mesh(positions)
        self._draw_arm(joints, positions)

        self._draw_tcp_shadow(tcp)
        self._draw_tcp_marker(tcp)
        self._draw_hud()
        return tcp

    # ── Mesh robot STL ─────────────────────────────────────────────

    def _draw_robot_mesh(self, positions: Dict[int, int]) -> None:
        """CC=4 — Dessine les meshes STL transformés du robot."""
        cx, cy = self._cx, self._cy
        tris = self._robot_mesh.transform(positions, max_tris=2000)
        if not tris:
            return

        # Trier par profondeur (painter's algorithm — faces lointaines d'abord)
        def _depth(tri):
            avg_y = (tri[0][1] + tri[1][1] + tri[2][1]) / 3
            avg_z = (tri[0][2] + tri[1][2] + tri[2][2]) / 3
            # Profondeur dans la direction de la caméra
            return -(avg_y * math.cos(self.cam.az) * math.cos(self.cam.el)
                     + avg_z * math.sin(self.cam.el))

        tris.sort(key=_depth)

        for v1, v2, v3, col in tris:
            s1 = self.cam.project(*v1, cx, cy)
            s2 = self.cam.project(*v2, cx, cy)
            s3 = self.cam.project(*v3, cx, cy)
            self.create_polygon(
                s1[0], s1[1], s2[0], s2[1], s3[0], s3[1],
                fill=_dim(col, 0.7), outline=_dim(col, 1.2), width=1)

    # ── Zones de sécurité ────────────────────────────────────────

    def _draw_zones(self, tcp: Tuple[float, float, float]) -> None:
        """CC=5 — Dessine les zones de sécurité (surfaces semi-transparentes)."""
        cx, cy = self._cx, self._cy
        self._zone_polys.clear()
        for zone in self._zones:
            if not zone.visible or len(zone.points) < 3:
                continue
            # Projeter les points
            proj = [self.cam.project(p[0], p[1], p[2], cx, cy) for p in zone.points]
            coords = []
            for sx, sy, _ in proj:
                coords.extend([sx, sy])

            # Couleur selon type
            is_plane = zone.zone_type == "plane"
            is_excl = zone.zone_type == "exclusion"
            if is_plane:
                fill = _dim("#3080d0", 0.10)
                outline = "#4090e0"
            elif is_excl:
                fill = _dim("#ff2020", 0.15)
                outline = "#ff4040"
            else:
                fill = _dim("#f6a117", 0.15)
                outline = "#f6a117"

            # Dessiner le polygone
            self.create_polygon(*coords, fill=fill, outline=outline,
                                width=2, stipple="gray25")

            # Label au centre
            avg_x = sum(p[0] for p in proj) // len(proj)
            avg_y = sum(p[1] for p in proj) // len(proj)
            label_text = zone.name
            if is_plane and zone.plane_axis:
                label_text = f"{zone.name}\n⟂ {zone.plane_axis}"
            self.create_text(avg_x, avg_y, text=label_text,
                             fill=outline, font=T.F_CAPTION)

            # Stocker le polygone projeté pour hit-test clic droit
            self._zone_polys.append((zone, [(sx, sy) for sx, sy, _ in proj]))

            # Sommets
            for sx, sy, _ in proj:
                r = 3
                self.create_oval(sx-r, sy-r, sx+r, sy+r,
                                 fill=outline, outline="")

    # ── Meshes STL ───────────────────────────────────────────────

    def _draw_meshes(self) -> None:
        """CC=5 — Dessine les meshes STL en wireframe."""
        cx, cy = self._cx, self._cy
        for mesh in self._meshes:
            tris = mesh["triangles"]
            ox, oy, oz = mesh["offset"]
            sc = mesh["scale"]
            col = mesh["color"]
            outline = _dim(col, 0.50)
            fill = _dim(col, 0.10)

            # Limiter le nombre de triangles rendus pour la performance
            step = max(1, len(tris) // 2000)
            for i in range(0, len(tris), step):
                v1, v2, v3 = tris[i]
                pts = []
                for vx, vy, vz in (v1, v2, v3):
                    px = vx * sc + ox
                    py = vy * sc + oy
                    pz = vz * sc + oz
                    sx, sy, _ = self.cam.project(px, py, pz, cx, cy)
                    pts.extend([sx, sy])
                self.create_polygon(*pts, fill=fill, outline=outline, width=1)

    # ── DXF 2D (sur le sol, Z=0) ────────────────────────────────

    def _draw_dxf(self) -> None:
        """CC=4 — Dessine les DXF 2D à plat sur le sol (Z=0)."""
        cx, cy = self._cx, self._cy
        for entry in self._dxf_meshes:
            dxf: DxfMesh = entry["mesh"]
            ox, oy, oz = entry["offset"]
            sc = entry["scale"]
            col = entry["color"]

            # Segments (lignes + polylignes)
            for p1, p2 in dxf.segments:
                sx1, sy1, _ = self.cam.project(
                    p1[0]*sc + ox, p1[1]*sc + oy, oz, cx, cy)
                sx2, sy2, _ = self.cam.project(
                    p2[0]*sc + ox, p2[1]*sc + oy, oz, cx, cy)
                self.create_line(sx1, sy1, sx2, sy2,
                                 fill=col, width=1)

            # Faces (3DFACE) — affichées à plat
            for face in dxf.faces:
                coords = []
                for vx, vy, vz in face:
                    sx, sy, _ = self.cam.project(
                        vx*sc + ox, vy*sc + oy, oz, cx, cy)
                    coords.extend([sx, sy])
                self.create_polygon(*coords, fill=_dim(col, 0.12),
                                    outline=col, width=1)

    # ── Prévisualisation waypoints DXF ─────────────────────────────

    def set_dxf_preview(self, points: List[Tuple[float, float, float, bool]]) -> None:
        """Définit les points de prévisualisation DXF (x, y, z, atteignable)."""
        self._dxf_waypoint_preview = points

    def _draw_dxf_preview(self) -> None:
        """CC=3 — Dessine chaque waypoint DXF : vert si atteignable, rouge sinon."""
        cx, cy = self._cx, self._cy
        r = 4  # rayon en pixels
        for x, y, z, reachable in self._dxf_waypoint_preview:
            sx, sy, _ = self.cam.project(x, y, z, cx, cy)
            col = "#00cc44" if reachable else "#ff3333"
            self.create_oval(sx - r, sy - r, sx + r, sy + r,
                             fill=col, outline=col)

    # ── Sol ────────────────────────────────────────────────────────

    def _draw_floor(self):
        cx, cy = self._cx, self._cy
        p = lambda x, y: self.cam.project(x, y, 0, cx, cy)
        n = int(FLOOR_R / FLOOR_STEP)

        for i in range(-n, n + 1):
            d = abs(i) / max(n, 1)
            base = 0x16
            hi   = 0x28
            g = int(base + (hi - base) * (1.0 - d))
            col = f"#{g:02x}{g+1:02x}{g+4:02x}"
            a, b_ = p(-FLOOR_R, i*FLOOR_STEP), p(FLOOR_R, i*FLOOR_STEP)
            c, d_ = p(i*FLOOR_STEP, -FLOOR_R), p(i*FLOOR_STEP, FLOOR_R)
            self.create_line(a[0],a[1], b_[0],b_[1], fill=col, width=1)
            self.create_line(c[0],c[1], d_[0],d_[1], fill=col, width=1)

        # Axes XYZ au sol
        L = 95
        o = self.cam.project(0, 0, 0, cx, cy)
        for (ax, ay, az, col, lbl) in [
            (L, 0, 0, "#c04040", "X"),
            (0, L, 0, "#40a040", "Y"),
            (0, 0, L, "#3070c0", "Z"),
        ]:
            t = self.cam.project(ax, ay, az, cx, cy)
            self.create_line(o[0],o[1], t[0],t[1], fill=col, width=2, arrow="last")
            self.create_text(t[0]+5, t[1]-4, text=lbl, fill=col, font=T.F_CAPTION)

    # ── Trace TCP ─────────────────────────────────────────────────

    def _draw_trail(self):
        if len(self._trail) < 2: return
        cx, cy = self._cx, self._cy
        pts = [self.cam.project(*p, cx, cy) for p in self._trail]
        n = len(pts)
        for i in range(1, n):
            t = i / n
            col = _lerp_col("#1a0d00", T.C_AMB, t)
            w = max(1, int(t * 3))
            p0, p1 = pts[i-1], pts[i]
            self.create_line(p0[0],p0[1], p1[0],p1[1],
                             fill=col, width=w, capstyle="round")

    # ── Bras ──────────────────────────────────────────────────────

    def _draw_arm(self, joints: list, positions: Dict[int, int]):
        """CC=5 — Rendu épuré : axes fins + joints interactifs (gizmos rotation).
        joints : 7 points [base, shoulder_top, shoulder_pivot, elbow, wrist, gripper, TCP]
        """
        cx, cy = self._cx, self._cy
        pj = [self.cam.project(*j, cx, cy) for j in joints]

        links = [(0,1,1), (1,2,1), (2,3,2), (3,4,3), (4,5,5), (5,6,6)]
        j_ax  = [1, 1, 2, 3, 5, 5, 6]

        # ── Ombres sol ──
        for i0, i1, _ in links:
            f0 = self.cam.project(joints[i0][0], joints[i0][1], 0, cx, cy)
            f1 = self.cam.project(joints[i1][0], joints[i1][1], 0, cx, cy)
            self.create_line(f0[0],f0[1], f1[0],f1[1],
                             fill="#181d2a", width=1, dash=(3,6))

        # ── Axes fins (lignes de structure) ──
        for i0, i1, ax in links:
            p0, p1 = pj[i0], pj[i1]
            col = AXIS_COLORS.get(ax, T.TEXT)
            self.create_line(p0[0],p0[1], p1[0],p1[1],
                             fill=_dim(col, 0.6), width=1, capstyle="round")

        # ── Joints interactifs (gizmos) ──
        # Mapping joint index → motor id pour l'interaction
        # J1=waist(mot1), J2=shoulder(mot2), J3=elbow(mot3), J4=wrist(mot5), J5=gripper(mot4)
        gizmo_joints = {
            1: (1, "Waist"),
            2: (2, "Shoulder"),
            3: (3, "Elbow"),
            4: (5, "Wrist"),
            5: (4, "Gripper"),
        }
        self._joint_hitboxes = []  # pour le hit-test clic

        for ji, (motor_id, label) in gizmo_joints.items():
            if ji >= len(pj):
                continue
            px, py, _ = pj[ji]
            ax = j_ax[ji] if ji < len(j_ax) else 6
            col = AXIS_COLORS.get(ax, T.TEXT)
            is_selected = (self._selected_joint == ji)

            # Rayon du gizmo
            r = 14 if is_selected else 9

            # Arc de rotation (gizmo visuel)
            if is_selected:
                # Cercle complet semi-transparent
                self.create_oval(px-r-6, py-r-6, px+r+6, py+r+6,
                                 fill="", outline=_dim(col, 0.3), width=1, dash=(2,3))
                # Arc de l'angle actuel
                tick = positions.get(motor_id, 2048)
                angle_deg = (tick - 2048) * 300.0 / 4096.0
                start = 90 - angle_deg
                self.create_arc(px-r-4, py-r-4, px+r+4, py+r+4,
                                start=start, extent=-angle_deg,
                                style="arc", outline=col, width=3)
                # Poignée sur l'arc
                handle_angle = math.radians(90 - angle_deg)
                hx_ = px + int((r + 4) * math.cos(handle_angle))
                hy_ = py - int((r + 4) * math.sin(handle_angle))
                self.create_oval(hx_-5, hy_-5, hx_+5, hy_+5,
                                 fill=col, outline="#ffffff", width=2)

            # Point central du joint
            self.create_oval(px-r, py-r, px+r, py+r,
                             fill=_dim(col, 0.35 if is_selected else 0.2),
                             outline=col, width=2 if is_selected else 1)
            self.create_oval(px-2, py-2, px+2, py+2, fill=col, outline="")

            # Label
            self.create_text(px + r + 6, py - r - 2,
                             text=label, fill=col,
                             font=T.F_CAPTION, anchor="w")

            # Stocker hitbox
            self._joint_hitboxes.append((ji, motor_id, px, py, r + 4))

        # ── Pince TCP ──
        self._draw_gripper(joints, pj[-1], positions.get(6, 2048))

    def _draw_body_segment(self, j0_3d: tuple, j1_3d: tuple,
                            p0: tuple, p1: tuple, col: str,
                            width_mm: float, seg_idx: int = 0) -> None:
        """CC=4 — Dessine un segment volumétrique (rectangle 3D projeté)."""
        cx, cy = self._cx, self._cy
        dx = j1_3d[0] - j0_3d[0]
        dy = j1_3d[1] - j0_3d[1]
        dz = j1_3d[2] - j0_3d[2]
        mag = math.sqrt(dx*dx + dy*dy + dz*dz)
        if mag < 1.0:
            return

        # Vecteur perpendiculaire dans le plan horizontal
        hw = width_mm * 0.5
        px_, py_ = -dy, dx
        pmag = math.sqrt(px_**2 + py_**2)
        if pmag < 0.01:
            # Segment purement vertical → perpendiculaire arbitraire
            px_, py_ = hw, 0.0
        else:
            px_, py_ = px_ / pmag * hw, py_ / pmag * hw

        # 4 coins du rectangle 3D
        corners_3d = [
            (j0_3d[0] + px_, j0_3d[1] + py_, j0_3d[2]),
            (j1_3d[0] + px_, j1_3d[1] + py_, j1_3d[2]),
            (j1_3d[0] - px_, j1_3d[1] - py_, j1_3d[2]),
            (j0_3d[0] - px_, j0_3d[1] - py_, j0_3d[2]),
        ]
        proj = [self.cam.project(c[0], c[1], c[2], cx, cy) for c in corners_3d]
        coords = []
        for sx, sy, _ in proj:
            coords.extend([sx, sy])

        # Opacité croissante vers le bas (base plus opaque, extrémité plus légère)
        stipples = ["gray75", "gray75", "gray75", "gray50", "gray50", "gray25"]
        stip = stipples[seg_idx] if seg_idx < len(stipples) else "gray50"
        self.create_polygon(*coords, fill="#ffffff",
                            stipple=stip,
                            outline=col, width=1)

    def _draw_gripper(self, joints: list, proj_tip: tuple, tick: int):
        """Dessine la pince au bout du bras."""
        col = AXIS_COLORS[6]
        opening = 5 + int((tick / 4095.0) * 13)
        j5, j4 = joints[-1], joints[-2]
        dx = j5[0]-j4[0]; dy = j5[1]-j4[1]; dz = j5[2]-j4[2]
        mag = math.sqrt(dx*dx + dy*dy + dz*dz) or 1.0
        dx, dy, dz = dx/mag, dy/mag, dz/mag

        # Perpendiculaire dans le plan horizontal
        px_, py_, pz_ = dy, -dx, 0.0
        pmag = math.sqrt(px_**2 + py_**2) or 1.0
        px_, py_ = px_/pmag, py_/pmag

        cx, cy = self._cx, self._cy
        for s in (-1, 1):
            fb = (j5[0]+s*px_*opening, j5[1]+s*py_*opening, j5[2])
            ft = (fb[0]+dx*20, fb[1]+dy*20, fb[2]+dz*20)
            s1 = self.cam.project(*j5, cx, cy)
            s2 = self.cam.project(*fb,  cx, cy)
            s3 = self.cam.project(*ft,  cx, cy)
            self.create_line(s1[0],s1[1], s2[0],s2[1], fill=col, width=2)
            self.create_line(s2[0],s2[1], s3[0],s3[1],
                             fill=col, width=3, capstyle="round")

    def _draw_tcp_marker(self, tcp: tuple):
        """CC=3 — Marqueur TCP visible : halo + cercle + coordonnées XYZ."""
        cx, cy = self._cx, self._cy
        tx, ty, _ = self.cam.project(*tcp, cx, cy)

        # Halo ambre
        for r, alpha in [(14, 0.08), (10, 0.15), (7, 0.25)]:
            self.create_oval(tx-r, ty-r, tx+r, ty+r,
                             fill=_dim(T.C_AMB, alpha), outline="")
        # Cercle plein
        r = 4
        self.create_oval(tx-r, ty-r, tx+r, ty+r,
                         fill=T.C_AMB, outline="#ffffff", width=1)
        # Coordonnées à côté
        self.create_text(tx + 16, ty - 2,
                         text=f"X{tcp[0]:+.0f}  Y{tcp[1]:+.0f}  Z{tcp[2]:+.0f}",
                         fill=T.C_AMB, font=T.F_CAPTION, anchor="w")

    def _draw_tcp_shadow(self, tcp: tuple):
        """Ligne verticale pointillée + cercle sol sous le TCP."""
        cx, cy = self._cx, self._cy
        sx, sy, _ = self.cam.project(tcp[0], tcp[1], 0,   cx, cy)
        tx, ty, _ = self.cam.project(*tcp,            cx, cy)
        r = 5
        self.create_oval(sx-r, sy-r, sx+r, sy+r,
                         fill="#181d2a", outline=T.C_AMB_DIM2, width=1)
        self.create_line(sx, sy, tx, ty,
                         fill=T.C_AMB_DIM2, width=1, dash=(3,5))

    # ── HUD ───────────────────────────────────────────────────────

    def _draw_hud(self):
        w = self.winfo_width()
        az = math.degrees(self.cam.az) % 360
        el = math.degrees(self.cam.el)
        self.create_text(w - 8, 8,
                         text=f"Az {az:.0f}°  El {el:.0f}°",
                         fill=T.TEXT_DIM, font=T.F_CAPTION, anchor="ne")
        self.create_text(8, 8,
                         text="⟳ Glisser · Molette pour zoomer",
                         fill=T.TEXT_DIM, font=T.F_CAPTION, anchor="nw")


# ═══════════════════════════════════════════════════════════════════
# MINI-VUE ORTHOGONALE
# ═══════════════════════════════════════════════════════════════════

class _OrthoView(tk.Canvas):
    """Vue orthographique compacte (TOP ou FRONT)."""

    _LABELS = {
        "top":   ("TOP",   "→X", "↑Y"),
        "front": ("FRONT", "→X", "↑Z"),
    }

    def __init__(self, parent, axis: str, **kw):
        super().__init__(parent, bg="#101420",
                         highlightthickness=1,
                         highlightbackground=T.BORDER, **kw)
        self._axis = axis

    def _proj(self, j: tuple, cx: int, cy: int, sc: float) -> Tuple[int, int]:
        x, y, z = j
        if self._axis == "top":
            return (int(cx + x*sc), int(cy - y*sc))
        else:  # front
            return (int(cx + x*sc), int(cy - z*sc))

    def draw(self, joints: list, positions: Dict[int, int]):
        """CC=4 — Rendu ortho minimal."""
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10: return

        cx, cy = w // 2, h // 2
        sc = min(w, h) * 0.36 / (REACH * 0.52)

        # Grille
        n = 3
        s = int(FLOOR_STEP * sc)
        for i in range(-n, n + 1):
            col = "#1a1e2c" if i else "#252a3a"
            self.create_line(cx + i*s, 0,   cx + i*s, h,   fill=col)
            self.create_line(0,   cy - i*s, w, cy - i*s, fill=col)

        # Liens (7 joints)
        links = [(0,1,1),(1,2,1),(2,3,2),(3,4,3),(4,5,5),(5,6,6)]
        for i0, i1, ax in links:
            if i0 >= len(joints) or i1 >= len(joints):
                continue
            p0 = self._proj(joints[i0], cx, cy, sc)
            p1 = self._proj(joints[i1], cx, cy, sc)
            col = AXIS_COLORS.get(ax, T.TEXT)
            self.create_line(*p0, *p1, fill=col, width=2, capstyle="round")

        # Joints
        j_ax = [1, 1, 2, 3, 5, 5, 6]
        for i, ax in enumerate(j_ax):
            if i >= len(joints):
                continue
            p = self._proj(joints[i], cx, cy, sc)
            col = AXIS_COLORS.get(ax, T.TEXT)
            r = 3
            self.create_oval(p[0]-r, p[1]-r, p[0]+r, p[1]+r,
                             fill=_dim(col, 0.45), outline=col, width=1)

        # TCP crosshair ambre
        tp = self._proj(joints[-1], cx, cy, sc)
        self.create_oval(tp[0]-5, tp[1]-5, tp[0]+5, tp[1]+5,
                         fill="", outline=T.C_AMB, width=1)
        self.create_line(tp[0]-8, tp[1],   tp[0]+8, tp[1],   fill=T.C_AMB, width=1)
        self.create_line(tp[0],   tp[1]-8, tp[0],   tp[1]+8, fill=T.C_AMB, width=1)

        # Labels
        lbl, ax1, ax2 = self._LABELS.get(self._axis, ("?","?","?"))
        self.create_text(5, 4,   text=lbl, fill=T.TEXT_DIM, font=T.F_CAPTION, anchor="nw")
        self.create_text(w-4, 4, text=f"{ax1} {ax2}",
                         fill=T.TEXT_DIM, font=T.F_CAPTION, anchor="ne")


# ═══════════════════════════════════════════════════════════════════
# PANNEAU INFO : JAUGES ARC + TCP
# ═══════════════════════════════════════════════════════════════════

class _InfoPanel(tk.Frame):
    """CC=5 — Jauges arc par axe + coordonnées TCP."""

    _ARC_SIZE = 40   # px côté canvas jauge

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=T.SURFACE, **kw)
        self._arcs:   Dict[int, tk.Canvas] = {}
        self._deglbl: Dict[int, tk.Label]  = {}
        self._tcplbl: Dict[str, tk.Label]  = {}
        self._build()

    def _build(self):
        pad = T.PAD_XS

        # ── Section articulations ──────────────────────────────────
        tk.Label(self, text="ARTICULATIONS", bg=T.SURFACE,
                 fg=T.TEXT_DIM, font=T.F_CAPTION).pack(
            anchor="w", padx=T.PAD_SM, pady=(T.PAD_SM, 2))

        for mid in range(1, 7):
            col  = AXIS_COLORS[mid]
            name = AXIS_NAMES[mid]

            row = tk.Frame(self, bg=T.SURFACE)
            row.pack(fill="x", padx=T.PAD_SM, pady=1)

            # Jauge arc (canvas carré)
            arc_c = tk.Canvas(row, width=self._ARC_SIZE, height=self._ARC_SIZE,
                              bg=T.SURFACE, highlightthickness=0)
            arc_c.pack(side="left", padx=(0, T.PAD_XS))
            self._arcs[mid] = arc_c

            # Texte
            info = tk.Frame(row, bg=T.SURFACE)
            info.pack(side="left", fill="x", expand=True)

            tk.Label(info, text=name, bg=T.SURFACE, fg=col,
                     font=T.F_CAPTION, anchor="w").pack(fill="x")

            deg_lbl = tk.Label(info, text="0.0°", bg=T.SURFACE,
                               fg=col, font=(T.FONT_MONO, 11, "bold"), anchor="w")
            deg_lbl.pack(fill="x")
            self._deglbl[mid] = deg_lbl

        # ── Section TCP ────────────────────────────────────────────
        tk.Frame(self, bg=T.BORDER, height=1).pack(fill="x", padx=T.PAD_SM,
                                                     pady=(T.PAD_SM, 4))
        tk.Label(self, text="POSITION TCP (mm)", bg=T.SURFACE,
                 fg=T.TEXT_DIM, font=T.F_CAPTION).pack(
            anchor="w", padx=T.PAD_SM, pady=(0, 2))

        for axis, col in [("X","#e05050"),("Y","#40a858"),("Z","#3880d0")]:
            row = tk.Frame(self, bg=T.SURFACE)
            row.pack(fill="x", padx=T.PAD_SM, pady=1)
            tk.Label(row, text=f"{axis}", bg=T.SURFACE, fg=col,
                     font=(T.FONT_MONO, 11, "bold"), width=2,
                     anchor="w").pack(side="left")
            lbl = tk.Label(row, text="—", bg=T.SURFACE, fg=T.TEXT,
                           font=T.F_MONO_MD, anchor="e")
            lbl.pack(side="right")
            self._tcplbl[axis] = lbl

    def _redraw_arc(self, c: tk.Canvas, col: str, tick: int):
        """
        Jauge arc (style voltmètre).
        track: arc 225° → -225° (sweep -270° CW) via 12h.
        fill:  fraction t = tick/4095.
        """
        c.delete("all")
        S = self._ARC_SIZE
        cx, cy = S // 2, S // 2 + 2
        r = S // 2 - 4

        # Fond de la piste (gris sombre)
        c.create_arc(cx-r, cy-r, cx+r, cy+r,
                     start=225, extent=-270,
                     outline=_dim(col, 0.18), width=3, style="arc")

        # Remplissage proportionnel au tick (0→vide, 4095→plein)
        t = tick / 4095.0
        extent = -270 * t
        if abs(extent) > 1.0:
            c.create_arc(cx-r, cy-r, cx+r, cy+r,
                         start=225, extent=extent,
                         outline=col, width=3, style="arc")

        # Repère central (tick=2048 ↔ t=0.5 ↔ extent=-135° ↔ 12 o'clock = 90°)
        zx = cx + int(r * math.cos(math.radians(90)))
        zy = cy - int(r * math.sin(math.radians(90)))
        c.create_oval(zx-1, zy-2, zx+1, zy+2, fill=T.TEXT_DIM, outline="")

        # Point de position courante
        angle_deg = 225 - 270 * t
        ax_ = cx + int(r * math.cos(math.radians(angle_deg)))
        ay_ = cy - int(r * math.sin(math.radians(angle_deg)))
        c.create_oval(ax_-2, ay_-2, ax_+2, ay_+2, fill=col, outline="")

    def update(self, positions: Dict[int, int], tcp: Tuple[float,float,float]):
        """Met à jour toutes les jauges et le TCP."""
        for mid in range(1, 7):
            tick = positions.get(mid, 2048)
            deg  = _deg(tick)
            col  = AXIS_COLORS[mid]
            self._redraw_arc(self._arcs[mid], col, tick)
            self._deglbl[mid].config(text=f"{deg:+.1f}°")

        self._tcplbl["X"].config(text=f"{tcp[0]:+.0f}")
        self._tcplbl["Y"].config(text=f"{tcp[1]:+.0f}")
        self._tcplbl["Z"].config(text=f"{tcp[2]:+.0f}")


# ═══════════════════════════════════════════════════════════════════
# DIALOGUE DXF → TIMELINE
# ═══════════════════════════════════════════════════════════════════

class _DxfTimelineDialog(tk.Toplevel):
    """Paramètres de conversion DXF → événements MOVE."""

    def __init__(self, parent, default_rid: str, robot_ids: list):
        super().__init__(parent)
        self.title("DXF → Timeline")
        self.configure(bg=T.BG)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        pad = {"padx": 8, "pady": 4}
        row = 0

        # Robot
        tk.Label(self, text="Robot :", bg=T.BG, fg=T.TEXT,
                 font=T.FONT_S).grid(row=row, column=0, sticky="e", **pad)
        self._rid_var = tk.StringVar(value=default_rid)
        cb = ttk.Combobox(self, textvariable=self._rid_var,
                          values=robot_ids, state="readonly", width=18)
        cb.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Durée par mouvement
        tk.Label(self, text="Durée / point (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.FONT_S).grid(row=row, column=0, sticky="e", **pad)
        self._dur_var = tk.DoubleVar(value=0.5)
        tk.Spinbox(self, textvariable=self._dur_var,
                   from_=0.1, to=10.0, increment=0.1, width=8,
                   bg=T.BG_2, fg=T.TEXT, font=T.FONT_S
                   ).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Z surface
        tk.Label(self, text="Hauteur surface (mm) :", bg=T.BG, fg=T.TEXT,
                 font=T.FONT_S).grid(row=row, column=0, sticky="e", **pad)
        self._z_var = tk.DoubleVar(value=0.0)
        tk.Spinbox(self, textvariable=self._z_var,
                   from_=-200, to=400, increment=5, width=8,
                   bg=T.BG_2, fg=T.TEXT, font=T.FONT_S
                   ).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Angle outil (assiette)
        tk.Label(self, text="Orientation outil :", bg=T.BG, fg=T.TEXT,
                 font=T.FONT_S).grid(row=row, column=0, sticky="e", **pad)
        self._angle_var = tk.StringVar(value="Vers le bas (180°)")
        angles_menu = ttk.Combobox(self, textvariable=self._angle_var,
                                    values=["Vers le bas (180°)",
                                            "Horizontal (90°)",
                                            "Vers le haut (0°)",
                                            "45° incliné"],
                                    state="readonly", width=18)
        angles_menu.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Boutons
        bf = tk.Frame(self, bg=T.BG)
        bf.grid(row=row, column=0, columnspan=2, pady=10)
        tk.Button(bf, text="Générer", bg=T.C_OK, fg="#fff",
                  font=T.FONT_S, command=self._ok
                  ).pack(side="left", padx=8)
        tk.Button(bf, text="Annuler", bg=T.BG_2, fg=T.TEXT,
                  font=T.FONT_S, command=self.destroy
                  ).pack(side="left", padx=8)

    def _ok(self):
        # Convertir le choix d'angle en radians
        angle_map = {
            "Vers le bas (180°)": math.pi,
            "Horizontal (90°)": math.pi / 2,
            "Vers le haut (0°)": 0.0,
            "45° incliné": math.pi * 0.75,
        }
        self.result = {
            "robot_id": self._rid_var.get(),
            "duration_s": self._dur_var.get(),
            "z_surface": self._z_var.get(),
            "tool_angle": angle_map.get(self._angle_var.get(), math.pi),
        }
        self.destroy()


# ═══════════════════════════════════════════════════════════════════
# PANNEAU SLIDERS (réutilise le même style que tab_positions)
# ═══════════════════════════════════════════════════════════════════

_AXIS_NAMES = {
    1: "Base", 2: "Épaule", 3: "Coude",
    4: "Coude2", 5: "Poignet", 6: "Rot. tête", 7: "Pince",
}
_PINCE_CM_MAX = 5.0
_SL_PAD = 8
_SL_R   = 8


def _sl_ticks_to_deg(t: int) -> float:
    return round(t * 360.0 / 4095.0, 1)

def _sl_ticks_to_cm(t: int, lo: int, hi: int) -> float:
    if hi <= lo:
        return 0.0
    return round(max(0.0, min(_PINCE_CM_MAX, (t - lo) / (hi - lo) * _PINCE_CM_MAX)), 1)


class _VisuSliderPanel(tk.Frame):
    """CC=6 — Panneau de sliders 7 axes pour l'onglet Visualisation.
    Lecture seule par défaut, pilotage direct si robot connecté."""

    HIDDEN_AXES = {3}   # masqué comme dans tab_positions

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=T.SURFACE, **kw)
        self._slider_data: Dict[int, dict] = {}
        self._slider_vars: Dict[int, tk.IntVar] = {}
        self._updating = False
        self._direct = False
        self._build()

    def _build(self) -> None:
        # Titre repliable
        hdr = tk.Frame(self, bg=T.SURFACE)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Axes", bg=T.SURFACE, fg=T.TEXT,
                 font=(T.FONT_UI, 11, "bold")).pack(side="left", padx=6)

        # Direct toggle
        self._direct_var = tk.BooleanVar(value=False)
        self._direct_cb = tk.Checkbutton(
            hdr, text="Direct", variable=self._direct_var,
            bg=T.SURFACE, fg=T.C_AMB, selectcolor=T.BG,
            activebackground=T.SURFACE, font=T.F_CAPTION,
            command=self._on_direct_toggle)
        self._direct_cb.pack(side="right", padx=4)

        self._frame = tk.Frame(self, bg=T.SURFACE)
        self._frame.pack(fill="both", expand=True, padx=2, pady=2)
        self._rebuild()

    def _rebuild(self) -> None:
        for var in self._slider_vars.values():
            for tid in var.trace_info():
                try:
                    var.trace_remove(tid[0], tid[1])
                except Exception:
                    pass
        for w in self._frame.winfo_children():
            w.destroy()
        self._slider_vars.clear()
        self._slider_data.clear()

        rid = store.get_system().active_robot_id
        ctrl = registry.get(rid) if rid else None
        profile = ctrl.profile if ctrl else None
        robot_clr = registry.color_for(rid) if rid else T.C_AMB
        rt = T.robot_theme(robot_clr)

        for mid in MOTOR_IDS:
            if mid in self.HIDDEN_AXES:
                continue
            lo, hi = (0, 4095)
            if profile:
                lo, hi = profile.soft_limits.get(mid, (0, 4095))

            is_pince = (mid == PINCE_AXIS)
            block_bg = rt["bg_med"]
            block = tk.Frame(self._frame, bg=block_bg, padx=4, pady=1)
            block.pack(fill="x", padx=2, pady=1)

            var = tk.IntVar(value=2048)
            self._slider_vars[mid] = var

            # Ligne info : nom + valeur
            info = tk.Frame(block, bg=block_bg)
            info.pack(fill="x")
            tk.Label(info, text=_AXIS_NAMES.get(mid, f"A{mid}"),
                     bg=block_bg, fg=robot_clr,
                     font=(T.FONT_UI, 10, "bold")).pack(side="left")
            val_text = f"{_sl_ticks_to_cm(2048, lo, hi):.1f} cm" if is_pince \
                else f"{_sl_ticks_to_deg(2048):.1f}°"
            hint_fg = T.blend_color("#ffffff", block_bg, 0.45)
            val_lbl = tk.Label(info, text=val_text, bg=block_bg,
                               fg=hint_fg, font=T.F_MONO_SM)
            val_lbl.pack(side="right")

            # Canvas slider
            cvs_h = 22 if is_pince else 16
            cvs = tk.Canvas(block, height=cvs_h, bg=block_bg,
                            highlightthickness=0, bd=0)
            cvs.pack(fill="x")

            cd = {
                "canvas": cvs, "motor_id": mid,
                "lo": lo, "hi": hi, "pos": 2048,
                "is_pince": is_pince, "val_lbl": val_lbl,
                "dragging": None, "ghost_pos": None,
                "robot_clr": robot_clr, "rt": rt,
            }
            self._slider_data[mid] = cd

            cvs.bind("<Configure>", lambda e, d=cd: self._draw(d))
            cvs.bind("<Button-1>", lambda e, d=cd: self._press(e, d))
            cvs.bind("<B1-Motion>", lambda e, d=cd: self._drag(e, d))
            cvs.bind("<ButtonRelease-1>", lambda e, d=cd: self._release(e, d))

            def _on_var(*_, d=cd, v=var):
                t = v.get()
                if d["is_pince"]:
                    d["val_lbl"].config(text=f"{_sl_ticks_to_cm(t, d['lo'], d['hi']):.1f} cm")
                else:
                    d["val_lbl"].config(text=f"{_sl_ticks_to_deg(t):.1f}°")
            var.trace_add("write", _on_var)

    # ── Dessin slider ─────────────────────────────────────────────

    def _pos_to_x(self, cd, pos):
        w = cd["canvas"].winfo_width()
        usable = w - 2 * _SL_PAD
        if usable <= 0:
            return _SL_PAD
        lo, hi = cd["lo"], cd["hi"]
        if hi <= lo:
            return _SL_PAD
        return int(_SL_PAD + max(0.0, min(1.0, (pos - lo) / (hi - lo))) * usable)

    def _x_to_pos(self, cd, x):
        w = cd["canvas"].winfo_width()
        usable = w - 2 * _SL_PAD
        if usable <= 0:
            return cd["lo"]
        ratio = max(0.0, min(1.0, (x - _SL_PAD) / usable))
        return int(cd["lo"] + ratio * (cd["hi"] - cd["lo"]))

    def _draw(self, cd, pos_only=False):
        cvs = cd["canvas"]
        w = cvs.winfo_width()
        h = cvs.winfo_height()
        if w < 20:
            return
        mid_y = h // 2
        r = _SL_R
        x_pos = self._pos_to_x(cd, cd["pos"])
        rt = cd["rt"]

        if pos_only and cvs.find_withtag("pos"):
            cvs.coords("pos", x_pos - r, mid_y - r, x_pos + r, mid_y + r)
            gp = cd.get("ghost_pos")
            if gp is not None and cvs.find_withtag("ghost"):
                gx = self._pos_to_x(cd, gp)
                gr = r - 2
                cvs.coords("ghost", gx - gr, mid_y - gr, gx + gr, mid_y + gr)
            return

        cvs.delete("all")
        x_lo, x_hi = _SL_PAD, w - _SL_PAD
        cvs.create_rectangle(x_lo, mid_y - 2, x_hi, mid_y + 2,
                             fill=rt["bg_vif"], outline="")
        # Centre
        x_mid = (x_lo + x_hi) // 2
        cvs.create_line(x_mid, mid_y - 4, x_mid, mid_y + 4,
                        fill=T.TEXT_DIM, width=1)
        # Ghost
        gp = cd.get("ghost_pos")
        if gp is not None:
            gx = self._pos_to_x(cd, gp)
            gr = r - 2
            cvs.create_oval(gx - gr, mid_y - gr, gx + gr, mid_y + gr,
                            fill=T.TEXT_DIM, outline=T.BORDER_HI, width=1,
                            tags="ghost")
        # Curseur
        cvs.create_oval(x_pos - r, mid_y - r, x_pos + r, mid_y + r,
                        fill="#1a1a2e", outline=cd["robot_clr"], width=2,
                        tags="pos")

    def _press(self, event, cd):
        cd["dragging"] = True
        self._move_to(cd, event.x)

    def _drag(self, event, cd):
        if cd.get("dragging"):
            self._move_to(cd, event.x)

    def _release(self, event, cd):
        cd["dragging"] = None

    def _move_to(self, cd, x):
        pos = self._x_to_pos(cd, x)
        pos = max(cd["lo"], min(cd["hi"], pos))
        cd["pos"] = pos
        mid = cd["motor_id"]
        if not self._updating:
            self._updating = True
            self._slider_vars[mid].set(pos)
            self._updating = False
        self._draw(cd, pos_only=True)
        # Pilotage direct si activé
        if self._direct_var.get():
            self._direct_write(mid, pos)

    def _direct_write(self, mid: int, pos: int):
        rid = store.get_system().active_robot_id
        ctrl = registry.get(rid) if rid else None
        if ctrl and ctrl.is_connected:
            ctrl.move_single(mid, pos, duration_s=0.15)

    def _on_direct_toggle(self):
        if self._direct_var.get():
            rid = store.get_system().active_robot_id
            ctrl = registry.get(rid) if rid else None
            if not ctrl or not ctrl.is_connected:
                self._direct_var.set(False)

    # ── API publique ──────────────────────────────────────────────

    def update_positions(self, positions: Dict[int, int]) -> None:
        """Met à jour les curseurs fantômes depuis les positions hardware."""
        for mid, pos in positions.items():
            cd = self._slider_data.get(mid)
            if cd is None:
                continue
            cd["ghost_pos"] = pos
            # Mettre à jour le curseur principal si pas en drag
            if not cd.get("dragging"):
                cd["pos"] = pos
                if not self._updating:
                    self._updating = True
                    var = self._slider_vars.get(mid)
                    if var:
                        var.set(pos)
                    self._updating = False
                self._draw(cd, pos_only=True)


# ═══════════════════════════════════════════════════════════════════
# ONGLET PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

class VisuTab(tk.Frame):
    """CC=4 — Onglet Visualisation 3D XR200 Pro."""

    def __init__(self, parent: tk.Widget, on_after: Callable,
                 active_robot_fn: Optional[Callable] = None,
                 timeline_model=None) -> None:
        super().__init__(parent, bg=T.BG)
        self._after           = on_after
        self._timeline_model  = timeline_model
        self._positions: Dict[int, int] = {m: 2048 for m in range(1, 7)}

        # Mode capture zone / plan
        self._capture_mode = False
        self._capture_points: List[List[float]] = []
        self._capture_max = 3   # 3 ou 4
        self._capture_is_plane = False

        # Dernier DXF chargé (pour conversion timeline)
        self._last_dxf: Optional[DxfMesh] = None
        self._last_dxf_scale: float = 1.0
        self._last_dxf_offset: Tuple[float, float, float] = (0, 0, 0)
        self._last_gcode = None
        self._last_gcode_scale: float = 1.0
        self._last_gcode_offset: Tuple[float, float, float] = (0, 0, 0)

        self._build()
        self._canvas3d._on_zone_context = self._on_canvas_zone_context
        self._canvas3d._on_joint_drag = self._on_joint_drag
        self._subscribe()
        self._load_zones()
        self._poll()

    # ── Construction ──────────────────────────────────────────────

    def _build(self):
        # Canvas 3D créé en avance (la toolbar le référence)
        main = tk.Frame(self, bg=T.BG)
        self._canvas3d = _Canvas3D(main)

        # Toolbar en haut (packée en premier)
        self._build_toolbar()

        # Puis zone principale
        main.pack(fill="both", expand=True)

        # Colonne gauche : sliders (fixe 200 px)
        left = tk.Frame(main, bg=T.SURFACE, width=200)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self._slider_panel = _VisuSliderPanel(left)
        self._slider_panel.pack(fill="both", expand=True)

        self._canvas3d.pack(side="left", fill="both", expand=True)

        # Colonne droite (fixe 220 px)
        right = tk.Frame(main, bg=T.BG, width=220)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        # Info panel
        self._info = _InfoPanel(right)
        self._info.pack(fill="x")

        # Séparateur
        tk.Frame(right, bg=T.BORDER, height=1).pack(fill="x", padx=4, pady=2)

        # Mini-vues empilées
        views = tk.Frame(right, bg=T.BG)
        views.pack(fill="both", expand=True)

        self._view_top   = _OrthoView(views, "top")
        self._view_top.pack(fill="both", expand=True, padx=T.PAD_XS,
                            pady=(T.PAD_XS, 2))

        self._view_front = _OrthoView(views, "front")
        self._view_front.pack(fill="both", expand=True, padx=T.PAD_XS,
                              pady=(2, T.PAD_XS))

        # Séparateur zones
        tk.Frame(right, bg=T.BORDER, height=1).pack(fill="x", padx=4, pady=2)

        # Panneau zones
        self._build_zone_panel(right)

        # Barre de capture (cachée par défaut)
        self._capture_bar = tk.Frame(self, bg=T.SURFACE_HI, pady=T.PAD_XS)
        self._capture_lbl = tk.Label(self._capture_bar, text="",
                                      bg=T.SURFACE_HI, fg=T.C_AMB,
                                      font=T.F_CONTROL)
        self._capture_lbl.pack(side="left", padx=T.PAD_MD)
        ttk.Button(self._capture_bar, text="Annuler (Échap)",
                   command=self._cancel_capture).pack(side="right", padx=T.PAD_SM)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=T.SURFACE, pady=T.PAD_XS)
        bar.pack(fill="x")

        # Titre
        tk.Label(bar, text="◈ Visualisation 3D",
                 bg=T.SURFACE, fg=T.C_AMB, font=T.F_SECTION).pack(
            side="left", padx=T.PAD_MD)

        # Sélecteur robot
        tk.Label(bar, text="Robot :", bg=T.SURFACE, fg=T.TEXT_MED,
                 font=T.F_CONTROL).pack(side="left", padx=(T.PAD_MD, T.PAD_XS))
        self._robot_var = tk.StringVar()
        self._robot_cb = ttk.Combobox(bar, textvariable=self._robot_var,
                                       width=12, state="readonly")
        self._robot_cb.pack(side="left", padx=(0, T.PAD_SM))
        self._robot_cb.bind("<<ComboboxSelected>>",
                            lambda _: bus.publish("ui.active_robot_changed",
                                                  {"robot_id": self._robot_var.get()}))

        # Badge état
        self._state_lbl = tk.Label(bar, text="⚬ —", bg=T.SURFACE,
                                    fg=T.TEXT_DIM, font=T.F_CONTROL)
        self._state_lbl.pack(side="left", padx=T.PAD_SM)

        # Bouton nouvelle zone (visible, côté gauche)
        zone_btn = tk.Label(bar, text="+ Zone", bg=T.C_OK, fg="#000000",
                            font=T.F_CONTROL, padx=T.PAD_MD, pady=2, cursor="hand2")
        zone_btn.pack(side="left", padx=(T.PAD_MD, T.PAD_XS))
        zone_btn.bind("<Button-1>", lambda _: self._start_zone_capture())

        # Bouton nouveau plan de référence
        plane_btn = tk.Label(bar, text="+ Plan", bg=T.C_INFO, fg="#000000",
                             font=T.F_CONTROL, padx=T.PAD_MD, pady=2, cursor="hand2")
        plane_btn.pack(side="left", padx=(0, T.PAD_XS))
        plane_btn.bind("<Button-1>", lambda _: self._start_plane_capture())

        # Bouton charger DXF
        dxf_btn = tk.Label(bar, text="DXF", bg=T.SURFACE_HI, fg=T.C_INFO,
                           font=T.F_CONTROL, padx=T.PAD_MD, pady=2, cursor="hand2")
        dxf_btn.pack(side="left", padx=(0, T.PAD_XS))
        dxf_btn.bind("<Button-1>", lambda _: self._load_dxf_file())
        dxf_btn.bind("<Enter>", lambda _: dxf_btn.config(fg="#ffffff"))
        dxf_btn.bind("<Leave>", lambda _: dxf_btn.config(fg=T.C_INFO))

        # Bouton DXF → Timeline
        tl_btn = tk.Label(bar, text="DXF → Timeline", bg=T.C_AMB, fg="#000000",
                          font=T.F_CONTROL, padx=T.PAD_MD, pady=2, cursor="hand2")
        tl_btn.pack(side="left", padx=(0, T.PAD_SM))
        tl_btn.bind("<Button-1>", lambda _: self._dxf_to_timeline())

        # Bouton charger G-code
        gc_btn = tk.Label(bar, text="G-code", bg=T.SURFACE_HI, fg=T.C_INFO,
                          font=T.F_CONTROL, padx=T.PAD_MD, pady=2, cursor="hand2")
        gc_btn.pack(side="left", padx=(0, T.PAD_XS))
        gc_btn.bind("<Button-1>", lambda _: self._load_gcode_file())
        gc_btn.bind("<Enter>", lambda _: gc_btn.config(fg="#ffffff"))
        gc_btn.bind("<Leave>", lambda _: gc_btn.config(fg=T.C_INFO))

        # Bouton preview timeline (joue la timeline en mode sim)
        play_btn = tk.Label(bar, text="▶ Preview", bg=T.C_OK, fg="#000000",
                            font=T.F_CONTROL, padx=T.PAD_MD, pady=2,
                            cursor="hand2")
        play_btn.pack(side="left", padx=(0, T.PAD_XS))
        play_btn.bind("<Button-1>", lambda _: self._preview_timeline())
        play_btn.bind("<Enter>", lambda _: play_btn.config(bg="#55dd55"))
        play_btn.bind("<Leave>", lambda _: play_btn.config(bg=T.C_OK))

        # Légende axes
        legend = tk.Frame(bar, bg=T.SURFACE)
        legend.pack(side="left", padx=T.PAD_MD)
        for mid in range(1, 7):
            col = AXIS_COLORS[mid]
            tk.Label(legend, text=f"● J{mid}", bg=T.SURFACE, fg=col,
                     font=T.F_CAPTION).pack(side="left", padx=2)

        # Bouton clear trail
        self._btn(bar, "✕ Trail",  T.C_ERR,   self._canvas3d.clear_trail)
        # Bouton reset vue
        self._btn(bar, "⟳ Vue",    T.C_INFO,  lambda: self._canvas3d.cam.reset())

    @staticmethod
    def _btn(parent, text, hover_col, cmd):
        """Petit bouton hover léger."""
        lbl = tk.Label(parent, text=text, bg=T.SURFACE_HI, fg=T.TEXT_MED,
                       font=T.F_CAPTION, padx=T.PAD_SM, pady=2, cursor="hand2")
        lbl.pack(side="right", padx=(0, T.PAD_XS))
        lbl.bind("<Button-1>",  lambda _: cmd())
        lbl.bind("<Enter>",     lambda _: lbl.config(fg=hover_col))
        lbl.bind("<Leave>",     lambda _: lbl.config(fg=T.TEXT_MED))

    # ── Panneau zones ─────────────────────────────────────────────

    def _build_zone_panel(self, parent):
        """Construit la liste des zones avec menu contextuel."""
        tk.Label(parent, text="ZONES", bg=T.SURFACE,
                 fg=T.TEXT_DIM, font=T.F_CAPTION).pack(
            anchor="w", padx=T.PAD_SM, pady=(T.PAD_XS, 2))
        self._zone_list = tk.Listbox(parent, height=5, font=T.F_MONO_SM,
                                      bg=T.SURFACE, fg=T.TEXT,
                                      selectbackground=T.C_AMB_DIM2,
                                      highlightthickness=0, activestyle="none")
        self._zone_list.pack(fill="x", padx=T.PAD_SM, pady=(0, T.PAD_XS))
        self._zone_list.bind("<Button-2>", self._zone_context_menu)
        self._zone_list.bind("<Button-3>", self._zone_context_menu)

    def _refresh_zone_list(self):
        """Met à jour la listbox des zones."""
        self._zone_list.delete(0, tk.END)
        for zone in library.list_zones():
            if zone.zone_type == "plane":
                icon = "🔵"
            elif zone.zone_type == "exclusion":
                icon = "🔴"
            else:
                icon = "🟡"
            self._zone_list.insert(tk.END, f"{icon} {zone.name}")

    def _zone_context_menu(self, event):
        """CC=4 — Menu contextuel sur une zone (clic droit)."""
        idx = self._zone_list.nearest(event.y)
        if idx < 0:
            return
        self._zone_list.selection_clear(0, tk.END)
        self._zone_list.selection_set(idx)

        zones = library.list_zones()
        if idx >= len(zones):
            return
        zone = zones[idx]

        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT,
                       activebackground=T.SURFACE_HI, activeforeground=T.TEXT)
        if zone.zone_type == "warning":
            menu.add_command(label="Convertir en zone de sécurité",
                             command=lambda: self._convert_zone(zone, "exclusion"))
        else:
            menu.add_command(label="Convertir en zone d'avertissement",
                             command=lambda: self._convert_zone(zone, "warning"))
        menu.add_command(label="Masquer" if zone.visible else "Afficher",
                         command=lambda: self._toggle_zone_visible(zone))
        menu.add_separator()
        menu.add_command(label="Supprimer", command=lambda: self._delete_zone(zone))
        menu.post(event.x_root, event.y_root)

    def _convert_zone(self, zone: ZoneModel, new_type: str):
        """Convertit le type de zone et sauvegarde."""
        zone.zone_type = new_type
        zone.color = "#ff2020" if new_type == "exclusion" else "#f6a117"
        library.save_zone(zone)
        self._load_zones()

    def _toggle_zone_visible(self, zone: ZoneModel):
        zone.visible = not zone.visible
        library.save_zone(zone)
        self._load_zones()

    def _delete_zone(self, zone: ZoneModel):
        library.delete_zone(zone.id)
        self._load_zones()

    def _on_canvas_zone_context(self, zone: ZoneModel, event):
        """Menu contextuel sur une zone cliquée dans le canvas 3D."""
        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)
        menu.add_command(label=f"📍 {zone.name}", state="disabled")
        menu.add_separator()
        if zone.zone_type == "warning" or zone.zone_type == "plane":
            menu.add_command(label="Convertir en zone de sécurité",
                             command=lambda: self._convert_zone(zone, "exclusion"))
        elif zone.zone_type == "exclusion":
            menu.add_command(label="Convertir en avertissement",
                             command=lambda: self._convert_zone(zone, "warning"))
        menu.add_command(label="Masquer" if zone.visible else "Afficher",
                         command=lambda: self._toggle_zone_visible(zone))
        menu.add_separator()
        menu.add_command(label="Supprimer", command=lambda: self._delete_zone(zone))
        menu.post(event.x_root, event.y_root)

    def _load_zones(self):
        """Charge les zones depuis la library et les transmet au canvas."""
        zones = library.list_zones()
        self._canvas3d.set_zones(zones)
        self._refresh_zone_list()

    # ── Capture de zone ───────────────────────────────────────────

    def _start_zone_capture(self):
        """CC=3 — Ouvre un menu pour choisir le nombre de points, puis lance la capture."""
        self._capture_is_plane = False
        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)
        menu.add_command(label="▲  3 points (triangle)",
                         command=lambda: self._begin_capture(3))
        menu.add_command(label="◆  4 points (quadrilatère)",
                         command=lambda: self._begin_capture(4))
        menu.add_separator()
        menu.add_command(label="Annuler")
        # Afficher sous le bouton zone
        try:
            menu.tk_popup(self.winfo_rootx() + 120, self.winfo_rooty() + 30)
        finally:
            menu.grab_release()

    def _begin_capture(self, n_points: int):
        """Lance le mode capture avec n_points sommets."""
        self._capture_max = n_points
        self._capture_points.clear()
        self._capture_mode = True
        self._capture_bar.pack(fill="x", before=self.winfo_children()[1])
        self._update_capture_label()
        # Binder espace pour capturer, échap pour annuler
        self.winfo_toplevel().bind("<space>", self._on_space_capture)
        self.winfo_toplevel().bind("<Escape>", lambda _: self._cancel_capture())

    def _update_capture_label(self):
        n = len(self._capture_points)
        remaining = self._capture_max - n
        self._capture_lbl.config(
            text=f"🔴 Capture zone : {n}/{self._capture_max} — "
                 f"Appuie sur ESPACE pour capturer ({remaining} restant{'s' if remaining > 1 else ''})  |  Échap = annuler")

    def _on_space_capture(self, event=None):
        """Capture le TCP courant sur appui espace."""
        if not self._capture_mode:
            return
        self._capture_point()

    def _capture_point(self):
        """CC=4 — Capture le TCP courant comme sommet de zone."""
        tcp = fk(self._positions)[-1]
        self._capture_points.append(list(tcp))
        n = len(self._capture_points)
        self._update_capture_label()
        _LOG.info("Zone capture point %d/%d : (%.0f, %.0f, %.0f)",
                  n, self._capture_max, tcp[0], tcp[1], tcp[2])
        if n >= self._capture_max:
            self._finish_capture()

    def _unbind_capture_keys(self):
        """Retire les bindings clavier de capture."""
        top = self.winfo_toplevel()
        top.unbind("<space>")
        top.unbind("<Escape>")

    def _finish_capture(self):
        """CC=3 — Termine la capture et sauvegarde la zone."""
        if self._capture_is_plane:
            return self._finish_plane_capture()
        self._unbind_capture_keys()
        from tkinter import simpledialog
        name = simpledialog.askstring("Nom de la zone", "Nom :",
                                       initialvalue=f"Zone {len(library.list_zones())+1}",
                                       parent=self)
        if not name:
            name = f"Zone {len(library.list_zones())+1}"
        zone = ZoneModel(
            name=name,
            zone_type="warning",
            points=self._capture_points[:],
            color="#f6a117",
        )
        library.save_zone(zone)
        self._capture_mode = False
        self._capture_points.clear()
        self._capture_bar.pack_forget()
        self._load_zones()
        _LOG.info("Zone '%s' créée (%d points)", name, len(zone.points))

    def _cancel_capture(self):
        """Annule le mode capture."""
        self._unbind_capture_keys()
        self._capture_mode = False
        self._capture_points.clear()
        self._capture_bar.pack_forget()

    # ── Capture de plan de référence ─────────────────────────────

    def _start_plane_capture(self):
        """Lance la capture de 3 points pour définir un plan de référence."""
        self._capture_is_plane = True
        self._begin_capture(3)

    def _finish_plane_capture(self):
        """CC=5 — Termine la capture d'un plan : calcule la normale, demande le label."""
        self._unbind_capture_keys()
        pts = self._capture_points[:]

        # Calcul de la normale du plan (produit vectoriel)
        p0, p1, p2 = pts[0], pts[1], pts[2]
        v1 = [p1[i] - p0[i] for i in range(3)]
        v2 = [p2[i] - p0[i] for i in range(3)]
        nx = v1[1]*v2[2] - v1[2]*v2[1]
        ny = v1[2]*v2[0] - v1[0]*v2[2]
        nz = v1[0]*v2[1] - v1[1]*v2[0]
        nmag = math.sqrt(nx*nx + ny*ny + nz*nz)
        if nmag > 0.001:
            nx, ny, nz = nx/nmag, ny/nmag, nz/nmag
        else:
            nx, ny, nz = 0, 0, 1

        # Détection de l'axe le plus proche
        axis = self._detect_plane_axis(nx, ny, nz)

        # Dialog choix du label
        labels_by_axis = {
            "XY": ["Plan bas (sol)", "Plan haut (plafond)", "Personnalisé..."],
            "XZ": ["Plan côté gauche", "Plan côté droit", "Personnalisé..."],
            "YZ": ["Plan avant", "Plan arrière", "Personnalisé..."],
            "oblique": ["Plan oblique", "Personnalisé..."],
        }
        options = labels_by_axis.get(axis, labels_by_axis["oblique"])

        dlg = tk.Toplevel(self)
        dlg.title(f"Plan de référence — {axis}")
        dlg.geometry("340x220")
        dlg.configure(bg=T.BG)
        dlg.transient(self.winfo_toplevel())

        tk.Label(dlg, text=f"Axe détecté : {axis}",
                 bg=T.BG, fg=T.C_INFO, font=T.F_CONTROL).pack(pady=(T.PAD_MD, T.PAD_XS))
        tk.Label(dlg, text=f"Normale : ({nx:.2f}, {ny:.2f}, {nz:.2f})",
                 bg=T.BG, fg=T.TEXT_DIM, font=T.F_CAPTION).pack()

        tk.Label(dlg, text="Label du plan :",
                 bg=T.BG, fg=T.TEXT, font=T.F_CONTROL).pack(pady=(T.PAD_MD, T.PAD_XS))

        selected = tk.StringVar(value=options[0])
        for opt in options:
            tk.Radiobutton(dlg, text=opt, variable=selected, value=opt,
                           bg=T.BG, fg=T.TEXT, selectcolor=T.SURFACE,
                           activebackground=T.BG, activeforeground=T.TEXT,
                           font=T.F_CONTROL).pack(anchor="w", padx=T.PAD_LG)

        custom_entry = tk.Entry(dlg, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL,
                                insertbackground=T.TEXT)

        def _on_select(*_):
            if selected.get() == "Personnalisé...":
                custom_entry.pack(fill="x", padx=T.PAD_LG, pady=T.PAD_XS)
                custom_entry.focus_set()
            else:
                custom_entry.pack_forget()
        selected.trace_add("write", _on_select)

        result = {"ok": False}

        def _ok():
            result["ok"] = True
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg=T.BG)
        btn_frame.pack(pady=T.PAD_MD)
        tk.Button(btn_frame, text="OK", command=_ok,
                  bg=T.C_OK, fg="#000", font=T.F_CONTROL, width=8).pack(side="left", padx=T.PAD_SM)
        tk.Button(btn_frame, text="Annuler", command=dlg.destroy,
                  bg=T.SURFACE_HI, fg=T.TEXT, font=T.F_CONTROL, width=8).pack(side="left")

        self.wait_window(dlg)

        if not result["ok"]:
            self._capture_mode = False
            self._capture_points.clear()
            self._capture_bar.pack_forget()
            return

        label = selected.get()
        if label == "Personnalisé...":
            label = custom_entry.get().strip() or f"Plan {axis}"

        # Étendre les 3 points en rectangle coplanaire pour la visualisation
        extended_pts = self._extend_plane_points(pts, nx, ny, nz)

        zone = ZoneModel(
            name=label,
            zone_type="plane",
            points=extended_pts,
            color="#3080d0",
            plane_label=label,
            plane_axis=axis,
        )
        library.save_zone(zone)
        self._capture_mode = False
        self._capture_points.clear()
        self._capture_bar.pack_forget()
        self._load_zones()
        _LOG.info("Plan '%s' créé (axe=%s, normale=(%.2f,%.2f,%.2f))",
                  label, axis, nx, ny, nz)

    @staticmethod
    def _detect_plane_axis(nx: float, ny: float, nz: float) -> str:
        """Détecte l'axe orthogonal le plus proche de la normale (tolérance 20°)."""
        threshold = math.cos(math.radians(20))  # ~0.94
        anx, any_, anz = abs(nx), abs(ny), abs(nz)
        if anz >= threshold:
            return "XY"
        if any_ >= threshold:
            return "XZ"
        if anx >= threshold:
            return "YZ"
        return "oblique"

    @staticmethod
    def _extend_plane_points(pts: List[List[float]],
                              nx: float, ny: float, nz: float,
                              extent: float = 200.0) -> List[List[float]]:
        """CC=4 — Étend 3 points en 4 coins d'un rectangle coplanaire centré."""
        # Centre des 3 points
        cx = sum(p[0] for p in pts) / 3
        cy = sum(p[1] for p in pts) / 3
        cz = sum(p[2] for p in pts) / 3

        # Deux vecteurs tangents au plan
        # t1 = direction P0→P1 normalisée
        dx = pts[1][0] - pts[0][0]
        dy = pts[1][1] - pts[0][1]
        dz = pts[1][2] - pts[0][2]
        mag = math.sqrt(dx*dx + dy*dy + dz*dz)
        if mag < 0.01:
            dx, dy, dz = 1, 0, 0
            mag = 1
        t1 = (dx/mag, dy/mag, dz/mag)

        # t2 = normale × t1
        t2 = (ny*t1[2] - nz*t1[1],
              nz*t1[0] - nx*t1[2],
              nx*t1[1] - ny*t1[0])

        # 4 coins du rectangle
        half = extent
        corners = []
        for s1, s2 in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
            corners.append([
                cx + t1[0]*half*s1 + t2[0]*half*s2,
                cy + t1[1]*half*s1 + t2[1]*half*s2,
                cz + t1[2]*half*s1 + t2[2]*half*s2,
            ])
        return corners

    # ── Chargement DXF ────────────────────────────────────────────

    def _load_dxf_file(self):
        """CC=5 — Charge un fichier DXF 2D et l'affiche à plat sur le sol."""
        from tkinter import filedialog, simpledialog
        path = filedialog.askopenfilename(
            title="Charger un plan DXF",
            filetypes=[("DXF files", "*.dxf"), ("Tous", "*.*")],
            parent=self,
        )
        if not path:
            return

        try:
            dxf = load_dxf(path)
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showerror("Erreur DXF", f"Impossible de charger :\n{exc}",
                                 parent=self)
            return

        if dxf.is_empty:
            from tkinter import messagebox
            messagebox.showinfo("DXF", "Aucune géométrie trouvée dans le fichier.",
                                parent=self)
            return

        size = dxf.size()
        n_seg = len(dxf.segments)
        n_face = len(dxf.faces)

        # Échelle : DXF en mm → monde robot en mm (1:1 par défaut)
        user_scale = simpledialog.askfloat(
            "Échelle DXF",
            f"Fichier : {n_seg} segments, {n_face} faces\n"
            f"Taille : {size:.0f} mm\n\n"
            f"Facteur d'échelle (1.0 = mm réels) :",
            initialvalue=1.0,
            minvalue=0.001, maxvalue=1000.0,
            parent=self,
        )
        if user_scale is None:
            return

        # Centrer le DXF à l'origine (sur le sol Z=0)
        center = dxf.center()
        offset = (-center[0] * user_scale,
                  -center[1] * user_scale,
                  0.0)

        self._canvas3d.add_dxf(dxf, offset=offset, scale=user_scale,
                                color="#4488cc")
        # Conserver pour conversion timeline
        self._last_dxf = dxf
        self._last_dxf_scale = user_scale
        self._last_dxf_offset = offset

        # Prévisualisation IK des waypoints DXF
        ox, oy, oz = offset
        seen: set = set()
        preview_points: List[Tuple[float, float, float, bool]] = []
        for p1, p2 in dxf.segments:
            for pt in (p1, p2):
                wx = pt[0] * user_scale + ox
                wy = pt[1] * user_scale + oy
                key = (round(wx, 2), round(wy, 2))
                if key in seen:
                    continue
                seen.add(key)
                result = ik_tool_angle(wx, wy, 0.0)
                preview_points.append((wx, wy, 0.0, result is not None))
        self._canvas3d.set_dxf_preview(preview_points)
        _LOG.info("DXF preview : %d points (%d atteignables)",
                  len(preview_points),
                  sum(1 for _, _, _, r in preview_points if r))

        _LOG.info("DXF chargé : %s (%d segments, %d faces, scale=%.3f)",
                  path, n_seg, n_face, user_scale)

    # ── Chargement G-code ──────────────────────────────────────────

    def _load_gcode_file(self):
        """CC=5 — Charge un fichier G-code et l'affiche dans la visu 3D."""
        from tkinter import filedialog, simpledialog, messagebox
        from xrv22.simulation.gcode_loader import load_gcode

        path = filedialog.askopenfilename(
            title="Charger un fichier G-code",
            filetypes=[("G-code", "*.gcode *.nc *.ngc *.tap"),
                       ("Tous", "*.*")],
            parent=self,
        )
        if not path:
            return

        prog = load_gcode(path)
        if not prog.waypoints:
            messagebox.showinfo("G-code", "Aucun waypoint trouvé.",
                                parent=self)
            return

        user_scale = simpledialog.askfloat(
            "Échelle G-code",
            f"{len(prog.waypoints)} waypoints\n"
            f"Bornes : {prog.bounds_min} → {prog.bounds_max}\n\n"
            f"Facteur d'échelle :",
            initialvalue=1.0,
            minvalue=0.001, maxvalue=1000.0,
            parent=self,
        )
        if user_scale is None:
            return

        # Centrer
        bmin, bmax = prog.bounds_min, prog.bounds_max
        cx = (bmin[0] + bmax[0]) / 2
        cy = (bmin[1] + bmax[1]) / 2
        offset = (-cx * user_scale, -cy * user_scale, 0.0)

        # Convertir en segments pour le rendu DXF (réutilise le même pipeline)
        from xrv22.simulation.dxf_loader import DxfMesh
        gcode_mesh = DxfMesh()
        for i in range(len(prog.waypoints) - 1):
            w0 = prog.waypoints[i]
            w1 = prog.waypoints[i + 1]
            gcode_mesh.segments.append(
                ((w0.x, w0.y, w0.z), (w1.x, w1.y, w1.z)))
        self._canvas3d.add_dxf(gcode_mesh, offset=offset,
                                scale=user_scale, color="#cc8844")

        # Preview IK
        ox, oy, oz = offset
        preview: List[Tuple[float, float, float, bool]] = []
        seen: set = set()
        for wp in prog.waypoints:
            wx = wp.x * user_scale + ox
            wy = wp.y * user_scale + oy
            wz = wp.z * user_scale + oz
            key = (round(wx, 1), round(wy, 1), round(wz, 1))
            if key in seen:
                continue
            seen.add(key)
            result = ik_tool_angle(wx, wy, wz)
            preview.append((wx, wy, wz, result is not None))
        self._canvas3d.set_dxf_preview(preview)

        # Stocker pour conversion timeline
        self._last_gcode = prog
        self._last_gcode_scale = user_scale
        self._last_gcode_offset = offset

        _LOG.info("G-code chargé : %s (%d waypoints, scale=%.3f)",
                  path, len(prog.waypoints), user_scale)

    # ── DXF → Timeline ────────────────────────────────────────────

    def _dxf_to_timeline(self):
        """CC=6 — Convertit le DXF chargé en événements MOVE sur la timeline."""
        from tkinter import messagebox, simpledialog

        if self._last_dxf is None:
            messagebox.showwarning("DXF → Timeline",
                                   "Aucun DXF chargé.\nChargez un fichier DXF d'abord.",
                                   parent=self)
            return
        if self._timeline_model is None:
            messagebox.showerror("DXF → Timeline",
                                 "Timeline non disponible.", parent=self)
            return

        # Choisir le robot
        robot_ids = sorted(registry.ids())
        if not robot_ids:
            messagebox.showwarning("DXF → Timeline",
                                   "Aucun robot enregistré.", parent=self)
            return

        rid = self._robot_var.get()
        if not rid or rid not in robot_ids:
            rid = robot_ids[0]

        # Dialog paramètres
        dlg = _DxfTimelineDialog(self, rid, robot_ids)
        self.wait_window(dlg)
        if not dlg.result:
            return

        rid = dlg.result["robot_id"]
        duration_s = dlg.result["duration_s"]
        z_surface = dlg.result["z_surface"]
        tool_angle = dlg.result.get("tool_angle", math.pi)

        # Calcul IK → waypoints
        waypoints = dxf_to_waypoints(
            self._last_dxf.segments,
            scale=self._last_dxf_scale,
            offset=self._last_dxf_offset,
            z_surface=z_surface,
            tool_angle=tool_angle,
        )

        if not waypoints:
            messagebox.showwarning("DXF → Timeline",
                                   "Aucun waypoint calculable (hors portée).",
                                   parent=self)
            return

        # S'assurer que la piste robot existe
        color = registry.color_for(rid)
        self._timeline_model.add_robot_track(rid, rid, color)
        track_id = f"track_{rid}"

        # Trouver le dernier instant occupé sur la piste
        track = self._timeline_model.get_track(track_id)
        t_ms = 0
        if track and track.events:
            t_ms = max(e.end_ms for e in track.events)

        # Créer les événements MOVE
        from xrv22.timeline.timeline_event import make_move_event
        dur_ms = int(duration_s * 1000)
        added = 0
        for i, positions in enumerate(waypoints):
            evt = make_move_event(
                track_id=track_id,
                start_ms=t_ms,
                positions=positions,
                duration_s=duration_s,
                label=f"DXF {i+1}/{len(waypoints)}",
            )
            ok, msg = self._timeline_model.add_event(evt)
            if ok:
                added += 1
                t_ms += dur_ms
            else:
                _LOG.warning("DXF event %d rejeté : %s", i, msg)

        _LOG.info("DXF → Timeline : %d/%d waypoints ajoutés sur %s",
                  added, len(waypoints), rid)
        messagebox.showinfo("DXF → Timeline",
                            f"{added} mouvements ajoutés sur {rid}\n"
                            f"Durée totale : {added * duration_s:.1f}s",
                            parent=self)

    # ── Interaction joints (gizmo rotation) ────────────────────────

    def _on_joint_drag(self, motor_id: int, delta_ticks: int) -> None:
        """Applique un delta de ticks sur un moteur depuis le drag gizmo."""
        rid = self._robot_var.get()
        ctrl = registry.get(rid) if rid else None
        if ctrl is None:
            return

        # Lire la position actuelle
        snap = store.get_robot(rid)
        if snap and snap.positions:
            current = snap.positions.get(motor_id, 2048)
        else:
            current = 2048

        # Appliquer le delta, clamper aux limites
        new_pos = current + delta_ticks
        lo, hi = ctrl.profile.soft_limits.get(motor_id, (0, 4095))
        new_pos = max(lo, min(hi, new_pos))

        # Mettre à jour le store (visu immédiate)
        store.set_positions(rid, {motor_id: new_pos})

        # Si connecté, envoyer au robot
        if ctrl.is_connected:
            ctrl.move_single(motor_id, new_pos, duration_s=0.1)

    # ── Boucle de mise à jour ──────────────────────────────────────

    def _poll(self):
        """CC=4 — Polling 200 ms : lecture positions + rendu."""
        # Sync liste robots
        ids = sorted(registry.ids())
        if ids != list(self._robot_cb["values"]):
            self._robot_cb["values"] = ids
            if ids and not self._robot_var.get():
                self._robot_var.set(ids[0])

        # Lire snapshot robot actif
        rid  = self._robot_var.get()
        snap = store.get_robot(rid) if rid else None
        if snap:
            if snap.positions:
                self._positions = dict(snap.positions)
            icon, col = _STATE_ICONS.get(snap.state, ("⚬ —", T.TEXT_DIM))
            self._state_lbl.config(text=icon, fg=col)

        # Mise à jour sliders
        self._slider_panel.update_positions(self._positions)

        # Rendu 3D + ortho + info
        tcp    = self._canvas3d.draw(self._positions)
        joints = fk(self._positions)
        self._info.update(self._positions, tcp)
        self._view_top.draw(joints,   self._positions)
        self._view_front.draw(joints, self._positions)

        self._after(200, self._poll)

    # ── Bus événements ─────────────────────────────────────────────

    def _subscribe(self):
        bus.subscribe("ui.active_robot_changed", self._on_robot_changed)

    def destroy(self) -> None:
        bus.unsubscribe_object(self)
        super().destroy()

    def _preview_timeline(self):
        """CC=6 — Lance la lecture de la timeline en mode simulation (preview 3D)."""
        from tkinter import messagebox
        if self._timeline_model is None:
            messagebox.showinfo("Preview",
                                "Aucune timeline chargée.",
                                parent=self)
            return
        stats = self._timeline_model.stats()
        if stats["event_count"] == 0:
            messagebox.showinfo("Preview",
                                "La timeline est vide.",
                                parent=self)
            return
        # Reset tous les événements
        self._timeline_model.reset_all_states()
        self._timeline_model.set_cursor(0)
        # Déclencher la lecture via le bus
        bus.publish("engine.play_request", {})
        _LOG.info("Preview timeline lancée (%d events, %.1fs)",
                  stats["event_count"], stats["duration_s"])

    def _on_robot_changed(self, payload: dict):
        rid = payload.get("robot_id", "")
        if rid:
            self._after(0, lambda: self._robot_var.set(rid))
