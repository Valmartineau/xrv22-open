"""
xrv22/core/box_collision.py
───────────────────────────
Moteur anti-collision par boîtes d'encombrement (OBB) — port Python du moteur
TypeScript de référence (web/src/visu/boxCollision.ts + calibKinematics.ts).
La parité est garantie par tests/test_box_collision.py (fixture dorée générée
par web/scripts/gen-parity-fixture.ts).

Principe : chaque pièce STL porte des boîtes calées à la main dans /calibrate
(champ `boxes` de calibration.json : centre/orientation à la pose de repos,
repère calibration). À une pose `ticks` donnée, chaque boîte est transformée
par la chaîne de pivots calibrée ; collision = test OBB-OBB (SAT, Ericson RTCD
§4.4). Auto-collision = paires de maillons différents hors exclusions
STRUCTURELLES (balayage mono-axe ±70° : ce qui frotte en mouvement normal est
exclu, les vrais replis restent détectés). Sol = point bas sous refSurfaceZ.

Périmètre serveur : auto-collision + sol (l'inter-robots exige la disposition
physique des robots, inconnue ici — géré côté web/onglet IA).
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from xrv22.services.logger import get_logger

_LOG = get_logger("BoxCollision")

Vec = Tuple[float, float, float]
Mat = Tuple[Vec, Vec, Vec]  # 3×3, lignes

# Pose de référence (ticks → angle 0), identique à web/src/visu/fk.ts REF_UP.
REF_UP: Dict[int, int] = {1: 2020, 2: 1900, 4: 1180, 5: 2061, 6: 2042}

# Chaîne de pivots (racine → pince) : label calibration, axe ticks, signe —
# identique à calibKinematics.PIVOTS.
PIVOTS: List[Tuple[str, int, int]] = [
    ("1", 1, -1), ("2·3", 2, +1), ("4", 4, -1), ("5", 5, +1), ("6", 6, +1),
]

LINK_NAMES = ["Base", "Shoulder", "UA", "Forearm", "Wrist", "Pince"]

MARGIN_MM = 10.0       # marge serveur (mm), fixe
SWEEP_DEG = 70         # enveloppe de mouvement normale (exclusions)
EPS = 1e-9


# ── Algèbre 3×3 (pure Python : pas de dépendance numpy) ──────────

_IDENT: Mat = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _mat_mul(a: Mat, b: Mat) -> Mat:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )  # type: ignore[return-value]


def _mat_vec(m: Mat, v: Vec) -> Vec:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _euler_xyz(rx: float, ry: float, rz: float) -> Mat:
    """Matrice de rotation pour un Euler three.js d'ordre 'XYZ' : R = Rx·Ry·Rz."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    rxm: Mat = ((1, 0, 0), (0, cx, -sx), (0, sx, cx))
    rym: Mat = ((cy, 0, sy), (0, 1, 0), (-sy, 0, cy))
    rzm: Mat = ((cz, -sz, 0), (sz, cz, 0), (0, 0, 1))
    return _mat_mul(_mat_mul(rxm, rym), rzm)


def _rodrigues(axis: Vec, angle: float) -> Mat:
    """Rotation d'angle `angle` autour de l'axe unitaire `axis`."""
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return (
        (t * x * x + c,     t * x * y - s * z, t * x * z + s * y),
        (t * x * y + s * z, t * y * y + c,     t * y * z - s * x),
        (t * x * z - s * y, t * y * z + s * x, t * z * z + c),
    )


# ── Cinématique calibration ──────────────────────────────────────

def _joint_angle(ticks: Dict[str, float], axis: int) -> float:
    """Angle (rad) d'un axe à partir de ses ticks (REF_UP = 0). Cf. fk.ts."""
    ref = REF_UP.get(axis, 2048)
    tick = ticks.get(str(axis), ref)
    return (tick - ref) * 360.0 / 4096.0 * math.pi / 180.0


def _axis_dir(rot_deg: Sequence[float]) -> Vec:
    """Direction d'un axe calibré : X unitaire tourné par son Euler (XYZ)."""
    m = _euler_xyz(*(d * math.pi / 180.0 for d in rot_deg))
    return (m[0][0], m[1][0], m[2][0])  # colonne 0 = R·X


def _link_frames(ticks: Dict[str, float], calib: dict) -> List[Tuple[Mat, Vec]]:
    """Repères affines F[L] = (R, t) des maillons 0..5 : p_monde = R·p + t pour
    un point exprimé à la pose de repos. F[L] = A_1∘A_2∘…∘A_L où
    A_k(p) = M_k·(p − c_k) + c_k (rotation du pivot k autour de son axe repos)."""
    frames: List[Tuple[Mat, Vec]] = [(_IDENT, (0.0, 0.0, 0.0))]
    for label, axis, sign in PIVOTS:
        ax = calib.get("axes", {}).get(label)
        if ax is None:
            frames.append(frames[-1])
            continue
        angle = sign * _joint_angle(ticks, axis)
        m = _rodrigues(_axis_dir(ax.get("rotDeg", (0, 0, 0))), angle)
        c: Vec = tuple(ax.get("pos", (0, 0, 0)))  # type: ignore[assignment]
        tk = (c[0] - _mat_vec(m, c)[0], c[1] - _mat_vec(m, c)[1], c[2] - _mat_vec(m, c)[2])
        rp, tp = frames[-1]
        rt = _mat_vec(rp, tk)
        frames.append((_mat_mul(rp, m), (rt[0] + tp[0], rt[1] + tp[1], rt[2] + tp[2])))
    return frames


# ── Boîtes monde ─────────────────────────────────────────────────

@dataclass
class WorldBox:
    link: int
    c: Vec
    axes: Tuple[Vec, Vec, Vec]  # axes monde unitaires de la boîte
    half: Vec


def world_boxes(ticks: Dict[str, float], calib: dict) -> List[WorldBox]:
    """Boîtes monde à la pose `ticks` (clés str). Ordre = calibration.json
    (les indices servent de clés d'exclusion "i-j", i<j)."""
    frames = _link_frames(ticks, calib)
    out: List[WorldBox] = []
    for b in calib.get("boxes", []):
        link = int(b["link"])
        r, t = frames[min(link, len(frames) - 1)]
        rest = _euler_xyz(*(d * math.pi / 180.0 for d in b["rotDeg"]))
        m = _mat_mul(r, rest)
        cv = _mat_vec(r, tuple(b["c"]))  # type: ignore[arg-type]
        out.append(WorldBox(
            link=link,
            c=(cv[0] + t[0], cv[1] + t[1], cv[2] + t[2]),
            axes=(
                (m[0][0], m[1][0], m[2][0]),
                (m[0][1], m[1][1], m[2][1]),
                (m[0][2], m[1][2], m[2][2]),
            ),
            half=tuple(b["half"]),  # type: ignore[arg-type]
        ))
    return out


# ── SAT OBB-OBB (Ericson RTCD §4.4) ──────────────────────────────

def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def obb_intersect(a: WorldBox, b: WorldBox, margin: float) -> bool:
    """Test d'intersection par axes séparateurs (3 faces de A, 3 de B,
    9 produits vectoriels). `margin` gonfle chaque boîte de margin/2 par face."""
    m = margin / 2.0
    ah = (a.half[0] + m, a.half[1] + m, a.half[2] + m)
    bh = (b.half[0] + m, b.half[1] + m, b.half[2] + m)
    r = [[_dot(a.axes[i], b.axes[j]) for j in range(3)] for i in range(3)]
    absr = [[abs(r[i][j]) + EPS for j in range(3)] for i in range(3)]
    tw = (b.c[0] - a.c[0], b.c[1] - a.c[1], b.c[2] - a.c[2])
    t = [_dot(tw, a.axes[0]), _dot(tw, a.axes[1]), _dot(tw, a.axes[2])]
    for i in range(3):  # axes de face de A
        if abs(t[i]) > ah[i] + bh[0] * absr[i][0] + bh[1] * absr[i][1] + bh[2] * absr[i][2]:
            return False
    for j in range(3):  # axes de face de B
        if abs(t[0] * r[0][j] + t[1] * r[1][j] + t[2] * r[2][j]) > \
           bh[j] + ah[0] * absr[0][j] + ah[1] * absr[1][j] + ah[2] * absr[2][j]:
            return False
    for i in range(3):  # axes croisés L = Ai × Bj
        i1, i2 = (i + 1) % 3, (i + 2) % 3
        for j in range(3):
            j1, j2 = (j + 1) % 3, (j + 2) % 3
            lhs = abs(t[i2] * r[i1][j] - t[i1] * r[i2][j])
            rhs = (ah[i1] * absr[i2][j] + ah[i2] * absr[i1][j]
                   + bh[j1] * absr[i][j2] + bh[j2] * absr[i][j1])
            if lhs > rhs:
                return False
    return True


def obb_penetration(a: WorldBox, b: WorldBox, margin: float) -> float:
    """Profondeur de pénétration (mm) : 0 si les boîtes ne se touchent pas,
    sinon le plus petit recouvrement le long des 6 axes de FACE (normale d'une
    face de A ou de B). C'est une mesure monotone de « à quel point on est
    enfoncé » — strictement positive ssi collision (gardée par obb_intersect) —
    utilisée pour n'autoriser que les mouvements qui RÉDUISENT la pénétration
    (recul), pas ceux qui l'aggravent."""
    if not obb_intersect(a, b, margin):
        return 0.0
    m = margin / 2.0
    ah = (a.half[0] + m, a.half[1] + m, a.half[2] + m)
    bh = (b.half[0] + m, b.half[1] + m, b.half[2] + m)
    r = [[abs(_dot(a.axes[i], b.axes[j])) for j in range(3)] for i in range(3)]
    tw = (b.c[0] - a.c[0], b.c[1] - a.c[1], b.c[2] - a.c[2])
    t = (_dot(tw, a.axes[0]), _dot(tw, a.axes[1]), _dot(tw, a.axes[2]))
    best = float("inf")
    for i in range(3):  # faces de A : recouvrement le long de l'axe Ai (mm)
        rb = bh[0] * r[i][0] + bh[1] * r[i][1] + bh[2] * r[i][2]
        best = min(best, ah[i] + rb - abs(t[i]))
    for j in range(3):  # faces de B : recouvrement le long de l'axe Bj (mm)
        ra = ah[0] * r[0][j] + ah[1] * r[1][j] + ah[2] * r[2][j]
        tproj = abs(_dot(tw, b.axes[j]))
        best = min(best, ra + bh[j] - tproj)
    return max(0.0, best)


# ── Exclusions structurelles + sol ───────────────────────────────

def rest_box_contacts(boxes: List[WorldBox], margin: float) -> Set[str]:
    """Paires en contact à la pose donnée (clés "i-j", i<j) — toutes paires,
    même-maillon compris (parité avec restBoxContacts TS)."""
    out: Set[str] = set()
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if obb_intersect(boxes[i], boxes[j], margin):
                out.add(f"{i}-{j}")
    return out


def sweep_contacts(calib: dict, margin: float,
                   sweep_deg: int = SWEEP_DEG, step_deg: int = 5) -> Set[str]:
    """Paires STRUCTURELLES à exclure : en contact quelque part dans l'enveloppe
    de mouvement normale (chaque axe balayé SEUL de ±sweep_deg autour du repos).
    Port de sweepContacts (boxCollision.ts)."""
    axes = [1, 2, 4, 5, 6]
    ref = {str(ax): float(REF_UP[ax]) for ax in axes}
    out: Set[str] = set()
    out |= rest_box_contacts(world_boxes(ref, calib), margin)
    for ax in axes:
        for a in range(step_deg, sweep_deg + 1, step_deg):
            for direction in (1, -1):
                t = dict(ref)
                t[str(ax)] = REF_UP[ax] + round(direction * a * 4096 / 360)
                out |= rest_box_contacts(world_boxes(t, calib), margin)
    return out


def box_bottom(b: WorldBox) -> float:
    """Point le plus bas de la boîte (projection des demi-côtés sur Z monde)."""
    return b.c[2] - (b.half[0] * abs(b.axes[0][2])
                     + b.half[1] * abs(b.axes[1][2])
                     + b.half[2] * abs(b.axes[2][2]))


def rest_ground_boxes(boxes: List[WorldBox], z_floor: float, margin: float) -> List[int]:
    """Indices des boîtes qui dégagent le sol à la pose de repos (les seules
    pertinentes à surveiller : la base repose au plancher par construction)."""
    return [i for i, b in enumerate(boxes) if box_bottom(b) >= z_floor + margin]


def ground_hit(boxes: List[WorldBox], z_floor: float, margin: float,
               only_idx: Optional[List[int]] = None) -> bool:
    idx = only_idx if only_idx is not None else range(len(boxes))
    return any(box_bottom(boxes[i]) < z_floor + margin for i in idx)


# ── Moteur intégré (singleton, init paresseuse en thread) ────────

_DEFAULT_CALIB = Path(__file__).resolve().parents[1] / "server" / "static" / "calibration.json"


class BoxCollisionEngine:
    """Charge calibration.json, précalcule exclusions + boîtes au sol, expose
    check(ticks) → None (sûr) ou un libellé ("auto-collision Wrist×Forearm",
    "sol"). FAIL-OPEN : indisponible / pas initialisé / erreur ⇒ None.
    L'init (balayage d'exclusions) prend ~1 s sur Pi → lancée en thread au
    premier check (ou explicitement via init())."""

    def __init__(self, calib_path: Optional[Path] = None) -> None:
        self._path = Path(calib_path) if calib_path else _DEFAULT_CALIB
        self._lock = threading.Lock()
        self._init_started = False
        self._ready = False
        self.available = False
        self._calib: dict = {}
        self._excl: Set[str] = set()
        self._ground_idx: List[int] = []
        self._z_floor = 0.0
        # paires à tester (cross-maillon, hors exclusions) + rayons englobants
        self._pairs: List[Tuple[int, int]] = []
        self._radii: List[float] = []

    # ── Init ────────────────────────────────────────────────────

    def init(self) -> None:
        """Init synchrone (idempotente)."""
        with self._lock:
            if self._ready:
                return
            self._init_started = True
        try:
            calib = json.loads(self._path.read_text())
            boxes_def = calib.get("boxes") or []
            if not boxes_def:
                raise ValueError("calibration sans champ boxes")
            excl = sweep_contacts(calib, MARGIN_MM)
            ref = {str(ax): float(REF_UP[ax]) for ax in (1, 2, 4, 5, 6)}
            rest = world_boxes(ref, calib)
            z_floor = float(calib.get("refSurfaceZ") or 0.0)
            pairs = [
                (i, j)
                for i in range(len(rest)) for j in range(i + 1, len(rest))
                if rest[i].link != rest[j].link and f"{i}-{j}" not in excl
            ]
            radii = [math.sqrt(b.half[0] ** 2 + b.half[1] ** 2 + b.half[2] ** 2)
                     for b in rest]
            with self._lock:
                self._calib = calib
                self._excl = excl
                self._ground_idx = rest_ground_boxes(rest, z_floor, MARGIN_MM)
                self._z_floor = z_floor
                self._pairs = pairs
                self._radii = radii
                self.available = True
                self._ready = True
            _LOG.info("Moteur boîtes prêt : %d boîtes, %d paires surveillées, "
                      "%d exclusions structurelles, sol z=%.1f",
                      len(boxes_def), len(pairs), len(excl), z_floor)
        except Exception as e:  # fail-open : moteur indisponible, on log
            with self._lock:
                self._ready = True
                self.available = False
            _LOG.warning("Moteur boîtes indisponible (%s) — anticollision "
                         "serveur inactive (fail-open)", e)

    def _kick_init(self) -> None:
        with self._lock:
            if self._init_started:
                return
            self._init_started = True
        threading.Thread(target=self.init, name="box-collision-init",
                         daemon=True).start()

    # ── Check ───────────────────────────────────────────────────

    def evaluate(self, ticks: Dict[int, int]) -> Tuple[float, Optional[str]]:
        """Pose candidate COMPLÈTE (clés int) → (pénétration_max_mm, libellé).
        pénétration 0 + libellé None ⟺ pose sûre. La pénétration sert au
        garde-fou « conscient du recul » (cf. safety_manager) : on ne bloque
        que les mouvements qui l'AUGMENTENT. Fail-open avant init."""
        if not self._ready:
            self._kick_init()
            return 0.0, None
        if not self.available:
            return 0.0, None
        try:
            t = {str(k): float(v) for k, v in ticks.items()}
            boxes = world_boxes(t, self._calib)
            margin = MARGIN_MM
            worst = 0.0
            label: Optional[str] = None
            for i, j in self._pairs:
                a, b = boxes[i], boxes[j]
                # préfiltre sphères englobantes (large : élimine les paires loin)
                dx = a.c[0] - b.c[0]
                dy = a.c[1] - b.c[1]
                dz = a.c[2] - b.c[2]
                lim = self._radii[i] + self._radii[j] + margin * 2.0
                if dx * dx + dy * dy + dz * dz > lim * lim:
                    continue
                pen = obb_penetration(a, b, margin)
                if pen > worst:
                    worst = pen
                    label = f"auto-collision {LINK_NAMES[a.link]}×{LINK_NAMES[b.link]}"
            for idx in self._ground_idx:
                pen_g = (self._z_floor + margin) - box_bottom(boxes[idx])
                if pen_g > worst:
                    worst = pen_g
                    label = "sol"
            return worst, label
        except Exception as e:
            _LOG.warning("evaluate boîtes ERROR (fail-open): %s", e)
            return 0.0, None

    def check(self, ticks: Dict[int, int]) -> Optional[str]:
        """Pose candidate COMPLÈTE → None si sûre, sinon le libellé du blocage.
        (Conservé pour la compat / les tests ; le garde-fou runtime utilise
        evaluate pour comparer les pénétrations.)"""
        return self.evaluate(ticks)[1]


# Singleton utilisé par le safety manager.
engine = BoxCollisionEngine()
