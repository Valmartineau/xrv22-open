"""
xr200/robots/robot_registry.py
────────────────────────────────
Registre multi-robots.

Gère la liste des robots enregistrés, le robot maître,
et les commandes globales (all stop, all home, etc.).

ROBOT_COLORS — couleurs par index pour différencier les pistes timeline.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from xrv22.robots.robot_controller import RobotController
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL
from xrv22.core.state_store import store

_LOG = get_logger("RobotRegistry")

ROBOT_COLORS = [
    "#f6a117",   # Robot 1 — ambre
    "#e040fb",   # Robot 2 — magenta vif
    "#00e5ff",   # Robot 3 — cyan
    "#76ff03",   # Robot 4 — lime
    "#ff6e40",   # Robot 5 — corail
    "#4ade80",   # Robot 6 — vert
    "#448aff",   # Robot 7 — bleu roi
    "#f43f5e",   # Robot 8 — rouge
]


# ── Propagation master -> esclaves (helpers) ─────────────────────

def _resolve_home_source(kind: str, target_kind: str,
                         positions: Optional[Dict[int, int]],
                         master_home: Dict[int, int]) -> Optional[Dict[int, int]]:
    """Positions de home à propager : argument explicite, sinon valeur du master."""
    if kind == target_kind and positions:
        return positions
    if master_home:
        return dict(master_home)
    return None


def _propagate_homes(slave: RobotController, master: RobotController,
                     kind: str, positions: Optional[Dict[int, int]]) -> None:
    """Réplique home_machine / home_work du master vers un esclave."""
    if kind in ("home_machine", "all"):
        src = _resolve_home_source(kind, "home_machine", positions,
                                   master.home_machine)
        if src:
            slave.set_home_machine(src, _propagating=True)
    if kind in ("home_work", "all"):
        src = _resolve_home_source(kind, "home_work", positions,
                                   master.home_work)
        if src:
            slave.set_home_work(src, _propagating=True)


def _propagate_soft_limits(slave: RobotController, master: RobotController,
                           kind: str, motor_id: Optional[int],
                           limits: Optional[Tuple[int, int]]) -> None:
    """Réplique les soft limits : un moteur ciblé, ou tous si kind='all'."""
    if kind == "soft_limit" and motor_id is not None and limits is not None:
        slave.profile.soft_limits[motor_id] = limits
        slave.set_motor_limit(motor_id, *limits, _propagating=True)
    elif kind == "all":
        for mid, (lo, hi) in master.profile.soft_limits.items():
            slave.profile.soft_limits[mid] = (lo, hi)
            slave.set_motor_limit(mid, lo, hi, _propagating=True)


def _propagate_motion(slave: RobotController, master: RobotController,
                      kind: str) -> None:
    """Réplique les paramètres de mouvement du master vers un esclave."""
    if kind in ("motion", "all"):
        slave.set_motion_params(
            master.smooth_hz, master.comfort_vel, master.comfort_acc,
            home_duration=master.home_duration, _propagating=True)


class RobotRegistry:
    """
    Registre central des robots.
    """

    def __init__(self) -> None:
        self._robots: Dict[str, RobotController] = {}
        self._master_id: str = ""
        self._lock = threading.Lock()

    # ── Gestion des robots ───────────────────────────────────────

    def add(self, robot_id: str, motor_ids: List[int],
            simulation: bool = False) -> RobotController:
        """Crée et enregistre un robot."""
        color = self._pick_color(robot_id)
        from xrv22.robots.robot_profiles import make_default_profile, profiles
        profile = make_default_profile(robot_id, color)
        profiles.register(profile)

        ctrl = RobotController(robot_id, motor_ids, simulation=simulation)
        with self._lock:
            self._robots[robot_id] = ctrl
            if not self._master_id:
                self._master_id = robot_id

        _LOG.info("Robot ajouté : %s (maître=%s)", robot_id, self._master_id)
        bus.publish("robot.added", {"robot_id": robot_id, "color": color})
        return ctrl

    def remove(self, robot_id: str) -> None:
        """Supprime un robot du registre et nettoie les abonnements bus."""
        with self._lock:
            ctrl = self._robots.pop(robot_id, None)
            if self._master_id == robot_id:
                self._master_id = next(iter(self._robots), "")
        if ctrl:
            ctrl.disconnect()
            bus.unsubscribe_object(ctrl)
            store.unregister_robot(robot_id)
            bus.publish("robot.removed", {"robot_id": robot_id})

    def get(self, robot_id: str) -> Optional[RobotController]:
        """Retourne le contrôleur d'un robot."""
        with self._lock:
            return self._robots.get(robot_id)

    def all(self) -> List[RobotController]:
        """Retourne tous les contrôleurs."""
        with self._lock:
            return list(self._robots.values())

    def ids(self) -> List[str]:
        """Retourne la liste des robot_id."""
        with self._lock:
            return list(self._robots.keys())

    # ── Robot maître ─────────────────────────────────────────────

    @property
    def master_id(self) -> str:
        return self._master_id

    def set_master(self, robot_id: str) -> bool:
        """Définit le robot maître."""
        with self._lock:
            if robot_id not in self._robots:
                return False
            self._master_id = robot_id
        _LOG.info("Robot maître : %s", robot_id)
        store.set_system(active_robot_id=robot_id)
        return True

    def get_master(self) -> Optional[RobotController]:
        """Retourne le contrôleur du robot maître."""
        return self.get(self._master_id)

    # ── Commandes globales ───────────────────────────────────────

    def emergency_stop_all(self) -> None:
        """⚡ EMERGENCY STOP sur tous les robots."""
        _LOG.log(SAFETY_LEVEL, "EMERGENCY STOP GLOBAL — tous les robots")
        for ctrl in self.all():
            ctrl.emergency_stop()

    def soft_stop_all(self) -> None:
        """Soft stop sur tous les robots."""
        for ctrl in self.all():
            ctrl.soft_stop()

    def lock_all(self) -> None:
        """Torque ON sur tous les robots — verrouille les moteurs (V17)."""
        for ctrl in self.all():
            if ctrl.is_connected:
                ctrl.set_torque(True)

    def unlock_all(self) -> None:
        """Torque OFF sur tous les robots — déverrouille les moteurs (V17)."""
        for ctrl in self.all():
            if ctrl.is_connected:
                ctrl.set_torque(False)

    def go_home_work_all(self, duration_s: float = 3.0) -> None:
        """Envoie tous les robots connectés en home work."""
        for ctrl in self.all():
            if ctrl.is_connected:
                ctrl.go_home_work(duration_s)

    def safe_home_all(self, duration_s: float = 3.0) -> None:
        """Retour home machine sécurisé pour tous les robots connectés."""
        for ctrl in self.all():
            if ctrl.is_connected:
                ctrl.safe_home(duration_s)

    # ── Propagation master -> esclaves ───────────────────────────
    def propagate_from_master(self, *,
                              kind: str = "all",
                              positions: Optional[Dict[int, int]] = None,
                              motor_id: Optional[int] = None,
                              limits: Optional[Tuple[int, int]] = None) -> None:
        """Réplique la config du master vers les autres robots.

        kind :
          - "home_machine" : copie home_machine (positions du master)
          - "home_work"    : copie home_work
          - "soft_limit"   : copie soft_limits[motor_id] (limits=(lo,hi))
          - "motion"       : copie motion params (smooth_hz/comfort_vel/acc/home_dur)
          - "all"          : copie tout (utilise les valeurs courantes du master)

        SSOT backend : appelé depuis controller.set_home_machine/work/motor_limit/
        motion_params si self est master, ou directement par UI/services.
        """
        master_rid = self._master_id
        if not master_rid:
            return
        master = self._robots.get(master_rid)
        if master is None:
            return
        for rid, slave in list(self._robots.items()):
            if rid == master_rid:
                continue
            try:
                _propagate_homes(slave, master, kind, positions)
                _propagate_soft_limits(slave, master, kind, motor_id, limits)
                _propagate_motion(slave, master, kind)
            except Exception as exc:
                _LOG.warning("propagate %s -> %s : %s", kind, rid, exc)

    def color_for(self, robot_id: str) -> str:
        """Retourne la couleur associée à un robot."""
        from xrv22.robots.robot_profiles import profiles
        p = profiles.get(robot_id)
        return p.color if p else ROBOT_COLORS[0]

    # ── Privé ────────────────────────────────────────────────────

    def _pick_color(self, robot_id: str) -> str:
        """Couleur d'un robot derivee du numero dans son id
        (robot_1 -> 1re couleur, robot_3 -> 3e), et non de l'ordre d'ajout.
        Identique a colorForRobot() de l'UI web -> couleurs coherentes
        entre le web et le Pi."""
        import re
        m = re.search(r"(\d+)$", robot_id)
        idx = (int(m.group(1)) - 1) if m else 0
        return ROBOT_COLORS[idx % len(ROBOT_COLORS)]


# Singleton global
registry = RobotRegistry()
