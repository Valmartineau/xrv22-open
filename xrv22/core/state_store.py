"""
xr200/core/state_store.py
──────────────────────────
Source unique de vérité pour l'état global de l'application.

Principes :
  • Lecture sans lock (snapshots immutables via dict copy).
  • Écriture via méthodes dédiées → publie sur l'EventBus.
  • L'UI souscrit à "ui.refresh" et lit les snapshots.
  • Jamais d'import UI dans ce module.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("StateStore")


# ── Types de données ─────────────────────────────────────────────

@dataclass
class RobotSnapshot:
    """État d'un robot à un instant T (immutable view)."""
    robot_id: str
    state: str           = "IDLE"
    port: str            = ""
    connected: bool      = False
    locked: bool         = False
    home_machine_set: bool = False
    home_work_set: bool  = False
    positions: Dict[int, int] = field(default_factory=dict)
    last_error: str      = ""

@dataclass
class SystemSnapshot:
    """État global du système."""
    simulation_mode: bool       = False
    arduino_connected: bool     = False
    arduino_port: str           = ""
    active_robot_id: str        = "robot_1"
    project_name: str           = "default"
    project_path: str           = ""
    execution_state: str        = "IDLE"   # IDLE / RUNNING / PAUSED / STOPPED


# ── Store ────────────────────────────────────────────────────────

class StateStore:
    """
    Store observable. Thread-safe en écriture, lock-free en lecture.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._robots: Dict[str, RobotSnapshot] = {}
        self._system = SystemSnapshot()

    # ── Lecture (snapshots, thread-safe) ─────────────────────────

    def get_robot(self, robot_id: str) -> Optional[RobotSnapshot]:
        """Retourne un snapshot du robot, ou None s'il n'existe pas."""
        with self._lock:
            r = self._robots.get(robot_id)
            if r is None:
                return None
            # Deep copy positions pour éviter mutation externe
            snap = RobotSnapshot(**r.__dict__)
            snap.positions = dict(snap.positions)
            return snap

    def get_all_robots(self) -> Dict[str, RobotSnapshot]:
        """Retourne un snapshot de tous les robots."""
        with self._lock:
            result = {}
            for rid, r in self._robots.items():
                snap = RobotSnapshot(**r.__dict__)
                snap.positions = dict(snap.positions)
                result[rid] = snap
            return result

    def get_system(self) -> SystemSnapshot:
        """Retourne un snapshot de l'état système."""
        with self._lock:
            return SystemSnapshot(**self._system.__dict__)

    # ── Écriture robots ──────────────────────────────────────────

    def register_robot(self, robot_id: str) -> None:
        """Enregistre un nouveau robot dans le store (idempotent avec warning)."""
        with self._lock:
            if robot_id in self._robots:
                _LOG.warning("Robot déjà enregistré (écrasé) : %s", robot_id)
            self._robots[robot_id] = RobotSnapshot(robot_id=robot_id)
        _LOG.info("Robot enregistré : %s", robot_id)
        self._notify_refresh()

    def unregister_robot(self, robot_id: str) -> None:
        """Supprime un robot du store."""
        with self._lock:
            self._robots.pop(robot_id, None)
        self._notify_refresh()

    def set_robot_state(self, robot_id: str, state: str) -> None:
        """Met à jour l'état safety d'un robot."""
        with self._lock:
            r = self._get_or_create(robot_id)
            if r.state == state:
                return
            prev = r.state
            r.state = state
        _LOG.info("[%s] State : %s → %s", robot_id, prev, state)
        bus.publish("robot.state_changed", {
            "robot_id": robot_id, "state": state, "prev_state": prev
        })
        self._notify_refresh()

    def set_robot_connected(self, robot_id: str, connected: bool, port: str = "") -> None:
        """Met à jour la connexion d'un robot."""
        with self._lock:
            r = self._get_or_create(robot_id)
            r.connected = connected
            r.port = port
        topic = "robot.connected" if connected else "robot.disconnected"
        bus.publish(topic, {"robot_id": robot_id, "port": port})
        self._notify_refresh()

    def set_robot_locked(self, robot_id: str, locked: bool) -> None:
        """Verrouille ou déverrouille un robot."""
        with self._lock:
            r = self._get_or_create(robot_id)
            r.locked = locked
        self._notify_refresh()

    def set_home_machine(self, robot_id: str, defined: bool) -> None:
        """Marque si le home machine est défini."""
        with self._lock:
            self._get_or_create(robot_id).home_machine_set = defined
        self._notify_refresh()

    def set_home_work(self, robot_id: str, defined: bool) -> None:
        """Marque si le home work est défini."""
        with self._lock:
            self._get_or_create(robot_id).home_work_set = defined
        self._notify_refresh()

    def set_positions(self, robot_id: str, positions: Dict[int, int]) -> None:
        """Met à jour les positions courantes d'un robot (avec validation)."""
        validated = {}
        for k, v in positions.items():
            mid = int(k)
            pos = int(v)
            if not (0 <= pos <= 4095):
                _LOG.warning("[%s] Position moteur %d hors bornes : %d (clampé)",
                             robot_id, mid, pos)
                pos = max(0, min(4095, pos))
            validated[mid] = pos
        with self._lock:
            self._get_or_create(robot_id).positions = validated
        self._notify_refresh()

    def set_robot_error(self, robot_id: str, message: str) -> None:
        """Enregistre le dernier message d'erreur d'un robot."""
        with self._lock:
            r = self._get_or_create(robot_id)
            r.last_error = message
            r.state = "ERROR"
        self._notify_refresh()

    # ── Écriture système ─────────────────────────────────────────

    def set_active_robot(self, rid: str) -> bool:
        """Definit le robot actif et publie sur le bus pour synchronisation
        de toutes les UIs (web + Pi tactile).
        Retourne True si la valeur a change, False si idempotent (no-op)."""
        with self._lock:
            if self._system.active_robot_id == rid:
                return False
            self._system.active_robot_id = rid
        _LOG.info("Robot actif -> %s", rid)
        # Publish hors du lock pour eviter deadlock potentiel
        bus.publish("system.active_robot_changed", {"robot_id": rid})
        return True

    def set_system(self, **kwargs: Any) -> None:
        """Met à jour des champs de SystemSnapshot."""
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._system, k):
                    setattr(self._system, k, v)
        self._notify_refresh()

    # ── Privé ────────────────────────────────────────────────────

    def _get_or_create(self, robot_id: str) -> RobotSnapshot:
        """Retourne le robot, le crée si absent. Appeler sous _lock."""
        if robot_id not in self._robots:
            self._robots[robot_id] = RobotSnapshot(robot_id=robot_id)
        return self._robots[robot_id]

    def _notify_refresh(self) -> None:
        """Notifie l'UI qu'une mise à jour est disponible."""
        bus.publish("ui.refresh", {})


# Singleton global
store = StateStore()
