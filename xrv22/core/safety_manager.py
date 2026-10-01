"""
xr200/core/safety_manager.py
─────────────────────────────
Safety Manager industriel — Machine à états formelle.

États robot (9) :
  IDLE          → connecté, en attente, aucun mouvement
  READY         → homes définis + validés, prêt à exécuter
  RUNNING       → séquence ou mouvement en cours
  PAUSED        → exécution suspendue, reprise possible
  SOFT_STOP     → arrêt propre, finit le mouvement en cours
  COMM_LOST     → liaison série perdue PENDANT l'exécution
  ERROR         → erreur hardware ou validation (reset explicite requis)
  EMERGENCY_STOP → arrêt immédiat, reset manuel uniquement
  LOCKED        → verrouillé opérateur, aucune commande

Transitions autorisées : matrice explicite (pas de if-elif cascade).

Règle incontournable :
  safe_home() passe TOUJOURS par HOME_WORK avant HOME_MACHINE.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from xrv22.config import MOTOR_RANGE_MIN, MOTOR_RANGE_MAX
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL
from xrv22.core.state_store import store

_LOG = get_logger("SafetyManager")

# Tolérance (mm) du garde-fou anticollision « conscient du recul » : une cible
# n'est bloquée que si elle approfondit la pénétration de plus que ça vs la pose
# actuelle. Petit (bruit servo) pour empêcher le creep dans la surface, mais
# non nul pour autoriser maintien/recul sans jitter.
_RETREAT_EPS_MM = 0.5


# ── États ────────────────────────────────────────────────────────

class RobotState:
    IDLE            = "IDLE"
    READY           = "READY"
    RUNNING         = "RUNNING"
    PAUSED          = "PAUSED"
    SOFT_STOP       = "SOFT_STOP"
    COMM_LOST       = "COMM_LOST"
    ERROR           = "ERROR"
    EMERGENCY_STOP  = "EMERGENCY_STOP"
    LOCKED          = "LOCKED"


# Transitions autorisées : {état_source: [états_cibles autorisés]}
_TRANSITIONS: Dict[str, List[str]] = {
    RobotState.IDLE:           [RobotState.READY, RobotState.RUNNING, RobotState.ERROR, RobotState.LOCKED, RobotState.EMERGENCY_STOP, RobotState.COMM_LOST],
    RobotState.READY:          [RobotState.RUNNING, RobotState.IDLE, RobotState.LOCKED, RobotState.EMERGENCY_STOP, RobotState.ERROR, RobotState.COMM_LOST],
    RobotState.RUNNING:        [RobotState.RUNNING, RobotState.IDLE, RobotState.PAUSED, RobotState.SOFT_STOP, RobotState.LOCKED, RobotState.COMM_LOST, RobotState.EMERGENCY_STOP, RobotState.ERROR, RobotState.READY],
    RobotState.PAUSED:         [RobotState.RUNNING, RobotState.SOFT_STOP, RobotState.EMERGENCY_STOP, RobotState.IDLE],
    RobotState.SOFT_STOP:      [RobotState.IDLE, RobotState.READY, RobotState.EMERGENCY_STOP],
    RobotState.COMM_LOST:      [RobotState.EMERGENCY_STOP, RobotState.IDLE],
    RobotState.ERROR:          [RobotState.IDLE, RobotState.EMERGENCY_STOP],
    RobotState.EMERGENCY_STOP: [],   # Aucune transition automatique — reset manuel uniquement
    RobotState.LOCKED:         [RobotState.IDLE],
}


# ── Violations ───────────────────────────────────────────────────

class SafetyViolation:
    """Violation de règle safety."""

    def __init__(self, severity: str, message: str,
                 motor_id: Optional[int] = None,
                 suggested_action: str = "") -> None:
        self.severity = severity           # "warning" | "error" | "critical"
        self.message = message
        self.motor_id = motor_id
        self.suggested_action = suggested_action

    def __repr__(self) -> str:
        return f"SafetyViolation({self.severity}: {self.message})"


# ── Safety Manager ────────────────────────────────────────────────

class RobotSafetyManager:
    """
    Gère les transitions d'état et les validations pour un robot.
    """

    def __init__(self, robot_id: str, motor_ids: List[int]) -> None:
        self.robot_id = robot_id
        self.motor_ids = motor_ids
        self._lock = threading.Lock()
        self._state = RobotState.IDLE

        # Paramètres de validation
        self.max_speed_ticks_per_s: int = 1000
        self.min_safe_duration_s: float = 0.1
        self.soft_limits: Dict[int, Tuple[int, int]] = {
            mid: (MOTOR_RANGE_MIN, MOTOR_RANGE_MAX) for mid in motor_ids
        }
        # Anticollision boîtes STL (auto-collision + sol) : ON par défaut à
        # chaque boot — une couche de sécurité ne dépend pas d'un fichier de
        # config (et .robot.json est réécrasé par les syncs). Toggle via l'API
        # /api/robots/{rid}/anticollision (onglet Connexion web).
        self.anticollision_enabled: bool = True

        store.register_robot(robot_id)
        store.set_robot_state(robot_id, self._state)

    # ── Propriété état ──────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    # ── Transitions ─────────────────────────────────────────────

    def transition_to(self, new_state: str) -> bool:
        """Effectue une transition si elle est autorisée.
        Store update DANS le lock pour éviter les vues stale."""
        with self._lock:
            if not self._is_allowed(new_state):
                _LOG.warning("[%s] Transition interdite : %s → %s",
                             self.robot_id, self._state, new_state)
                return False
            prev = self._state
            self._state = new_state
            store.set_robot_state(self.robot_id, new_state)
        self._log_transition(prev, new_state)
        return True

    def force_emergency_stop(self, source: str = "operator") -> None:
        """Force EMERGENCY_STOP sans vérifier la matrice (urgence absolue)."""
        with self._lock:
            prev = self._state
            self._state = RobotState.EMERGENCY_STOP
            store.set_robot_state(self.robot_id, RobotState.EMERGENCY_STOP)
        _LOG.log(SAFETY_LEVEL, "[%s] ⚡ EMERGENCY STOP — source: %s (depuis %s)",
                 self.robot_id, source, prev)
        bus.publish("safety.emergency_stop", {
            "robot_id": self.robot_id, "source": source, "prev_state": prev
        })

    def reset_emergency(self) -> bool:
        """Reset manuel depuis EMERGENCY_STOP → IDLE."""
        with self._lock:
            if self._state != RobotState.EMERGENCY_STOP:
                return False
            prev = self._state
            if not self._is_allowed(RobotState.IDLE):
                return False
            self._state = RobotState.IDLE
            store.set_robot_state(self.robot_id, RobotState.IDLE)
        self._log_transition(prev, RobotState.IDLE)
        return True

    def reset_error(self) -> bool:
        """Reset depuis ERROR → IDLE."""
        with self._lock:
            if self._state != RobotState.ERROR:
                return False
            prev = self._state
            if not self._is_allowed(RobotState.IDLE):
                return False
            self._state = RobotState.IDLE
            store.set_robot_state(self.robot_id, RobotState.IDLE)
        self._log_transition(prev, RobotState.IDLE)
        return True

    # ── Commandes safety ────────────────────────────────────────

    def lock(self) -> bool:
        """Verrouille le robot."""
        ok = self.transition_to(RobotState.LOCKED)
        if ok:
            _LOG.log(SAFETY_LEVEL, "[%s] LOCKED", self.robot_id)
            store.set_robot_locked(self.robot_id, True)
        return ok

    def unlock(self) -> bool:
        """Déverrouille le robot (LOCKED → IDLE)."""
        with self._lock:
            if self._state == RobotState.IDLE:
                return True  # Déjà déverrouillé
            if self._state != RobotState.LOCKED:
                _LOG.warning("[%s] unlock impossible depuis %s (requis: LOCKED)",
                             self.robot_id, self._state)
                return False
            prev = self._state
            if not self._is_allowed(RobotState.IDLE):
                return False
            self._state = RobotState.IDLE
            store.set_robot_state(self.robot_id, RobotState.IDLE)
            store.set_robot_locked(self.robot_id, False)
        self._log_transition(prev, RobotState.IDLE)
        _LOG.log(SAFETY_LEVEL, "[%s] UNLOCKED", self.robot_id)
        return True

    def soft_stop(self) -> None:
        """Arrêt propre (finit le mouvement en cours)."""
        self.transition_to(RobotState.SOFT_STOP)
        _LOG.log(SAFETY_LEVEL, "[%s] SOFT STOP demandé", self.robot_id)

    def on_comm_lost(self) -> None:
        """Appelé par le watchdog quand la liaison est perdue."""
        self.transition_to(RobotState.COMM_LOST)
        _LOG.log(SAFETY_LEVEL, "[%s] COMM_LOST", self.robot_id)

    # ── Validation de mouvement ──────────────────────────────────

    def validate_move(self, targets: Dict[int, int], duration_s: float,
                      current_positions: Dict[int, int]) -> Tuple[bool, List[SafetyViolation]]:
        """Valide une commande de mouvement avant envoi série."""
        violations: List[SafetyViolation] = []

        if not self._can_move():
            violations.append(SafetyViolation(
                "critical", f"Robot {self.robot_id} not in moveable state ({self._state})",
                suggested_action="Check robot state before sending move"))
            return False, violations

        if duration_s < self.min_safe_duration_s:
            violations.append(SafetyViolation(
                "warning", f"Duration {duration_s:.2f}s très court",
                suggested_action=f"Augmenter à ≥ {self.min_safe_duration_s}s"))

        violations.extend(self._check_speed(targets, duration_s, current_positions))
        violations.extend(self._check_limits(targets))

        # ── Collision check (zones exclusion) ──────────────────────
        ok, reason, zone_id, zone_name, incursion_mm = self.check_collision_only(
            targets, current_positions, broadcast=True)
        if not ok:
            violations.append(SafetyViolation(
                "error",
                reason,
                suggested_action=f"Eloigner du volume '{zone_name}'",
            ))

        is_safe = not any(v.severity in ("critical", "error") for v in violations)
        self._log_violations(violations)
        return is_safe, violations

    def check_collision_only(self, targets: Dict[int, int],
                             current_positions: Dict[int, int],
                             broadcast: bool = True,
                             retreat_aware: bool = False) -> Tuple[bool, str, str, str, float]:
        """Check collision (réutilisable depuis Direct + validate_move) :
        1) zones d'exclusion (moteur existant), 2) anticollision boîtes STL
        (auto-collision + sol, ON par défaut, toggle par robot).

        retreat_aware : si True (pilotage interactif Direct/jog), on ne bloque la
        cible que si elle AGGRAVE la pénétration vs la pose actuelle → le bras
        peut toujours ressortir d'un contact. Si False (défaut : vérif statique
        check_position, goto/suite), test ABSOLU = on bloque toute pose en
        collision.

        Retour : (ok, reason, zone_id, zone_name, incursion_mm).
        Si broadcast=True, publie 'safety.collision_blocked' sur le bus, rate-limité
        à 1× par seconde max (pour éviter le spam en mode Direct 20Hz).
        """
        ok, reason, zid, zname, inc = self._check_zones_only(
            targets, current_positions, broadcast)
        if not ok:
            return ok, reason, zid, zname, inc
        # ── Anticollision boîtes STL (couche serveur, tous chemins) ──
        if self.anticollision_enabled:
            try:
                from xrv22.core.box_collision import engine as box_engine
                # Pose candidate complète : axes non commandés = position courante.
                merged = {**current_positions, **targets}
                pen_t, label = box_engine.evaluate(merged)
                # retreat_aware (pilotage interactif) : on ne bloque que si la
                # cible AGGRAVE la pénétration vs la pose précédente commandée
                # (current_positions) → recul/maintien/glisse toujours permis.
                # Sinon (statique/goto) : test ABSOLU, toute collision bloque.
                blocked = False
                if pen_t > 0.0:
                    if retreat_aware:
                        pen_c, _ = box_engine.evaluate(current_positions)
                        blocked = pen_t > pen_c + _RETREAT_EPS_MM
                    else:
                        blocked = True
                if blocked:
                    if broadcast:
                        import time
                        now = time.monotonic()
                        if now - getattr(self, "_last_collision_broadcast_t", 0.0) > 1.0:
                            self._last_collision_broadcast_t = now
                            try:
                                bus.publish("safety.collision_blocked", {
                                    "robot_id": self.robot_id,
                                    "kind": "boxes",
                                    "zone_id": "anticollision",
                                    "zone_name": label,
                                    "incursion_mm": 0.0,
                                })
                            except Exception:
                                pass
                    return False, label, "anticollision", label, 0.0
            except Exception as e:
                _LOG.warning("Anticollision boîtes ERROR (fail-open): %s", e)
        return True, "", "", "", inc

    def _check_zones_only(self, targets: Dict[int, int],
                          current_positions: Dict[int, int],
                          broadcast: bool = True) -> Tuple[bool, str, str, str, float]:
        """Check zones d'exclusion uniquement (moteur historique)."""
        try:
            from xrv22.core import collision_checker as cc
            from xrv22.library.library_manager import library
            settings = library.get_project_settings() or {}
            enabled = settings.get("safety", {}).get("collision_check_enabled", True)
            if not enabled:
                return True, "", "", "", 0.0
            zones = [z for z in library.list_zones()
                     if z.zone_type == "exclusion" and z.visible]
            if not zones:
                return True, "", "", "", 0.0
            current_joints = cc.positions_to_joints_3d(current_positions)
            target_joints = cc.positions_to_joints_3d(targets)
            result = cc.check_move(current_joints, target_joints, zones)
            if result.ok:
                return True, "", "", "", result.incursion_mm
            # Rejet : broadcast rate-limité
            if broadcast:
                import time
                now = time.monotonic()
                if now - getattr(self, "_last_collision_broadcast_t", 0.0) > 1.0:
                    self._last_collision_broadcast_t = now
                    try:
                        bus.publish("safety.collision_blocked", {
                            "robot_id": self.robot_id,
                            "zone_id": result.zone_id,
                            "zone_name": result.zone_name,
                            "incursion_mm": result.incursion_mm,
                        })
                    except Exception:
                        pass
            return False, result.reason, result.zone_id, result.zone_name, result.incursion_mm
        except Exception as e:
            import traceback
            _LOG.warning("Collision check ERROR: %s\n%s", e, traceback.format_exc())
            return True, "", "", "", 0.0  # fail-open

    def check_position(self, targets: Dict[int, int]) -> List[Dict[str, str]]:
        """Vérifie une position STATIQUE (limites soft + collision zones) sans
        envoyer de commande au robot. Retourne la liste des conflits
        [{type, severity, message}] (vide si la position est sûre)."""
        conflicts: List[Dict[str, str]] = []
        for v in self._check_limits(targets):
            conflicts.append({"type": "limit",
                              "severity": v.severity,
                              "message": v.message})
        # current == targets : segment dégénéré → évalue la pose cible elle-même.
        ok, reason, _zid, _zname, _inc = self.check_collision_only(
            targets, targets, broadcast=False)
        if not ok:
            conflicts.append({"type": "collision",
                              "severity": "error",
                              "message": reason})
        return conflicts

    def set_soft_limits(self, motor_id: int, min_pos: int, max_pos: int) -> None:
        """Configure les limites physiques d'un moteur."""
        if motor_id in self.motor_ids:
            self.soft_limits[motor_id] = (min_pos, max_pos)

    # ── Privé ────────────────────────────────────────────────────

    def _is_allowed(self, new_state: str) -> bool:
        """Vérifie si la transition est dans la matrice."""
        return new_state in _TRANSITIONS.get(self._state, [])

    def _can_move(self) -> bool:
        """Vrai si l'état courant autorise le mouvement."""
        return self._state in (RobotState.IDLE, RobotState.READY, RobotState.RUNNING)

    def _check_speed(self, targets: Dict[int, int], duration_s: float,
                     current: Dict[int, int]) -> List[SafetyViolation]:
        """Vérifie que la vitesse est dans les limites."""
        out = []
        for mid, target in targets.items():
            if mid not in self.motor_ids:
                out.append(SafetyViolation(
                    "error", f"Motor {mid}: inconnu (IDs valides: {self.motor_ids})",
                    motor_id=mid))
                continue
            if mid not in current:
                continue
            delta = abs(target - current[mid])
            if delta > self.max_speed_ticks_per_s * duration_s:
                req = delta / self.max_speed_ticks_per_s
                out.append(SafetyViolation(
                    "error", f"Motor {mid}: trop rapide ({delta} ticks en {duration_s:.2f}s)",
                    motor_id=mid, suggested_action=f"Durée ≥ {req:.2f}s"))
        return out

    def _check_limits(self, targets: Dict[int, int]) -> List[SafetyViolation]:
        """Vérifie que les positions sont dans les limites physiques."""
        out = []
        for mid, pos in targets.items():
            lo, hi = self.soft_limits.get(mid, (MOTOR_RANGE_MIN, MOTOR_RANGE_MAX))
            if pos < lo:
                out.append(SafetyViolation(
                    "error", f"Motor {mid}: {pos} < min {lo}",
                    motor_id=mid, suggested_action=f"Position ≥ {lo}"))
            elif pos > hi:
                out.append(SafetyViolation(
                    "error", f"Motor {mid}: {pos} > max {hi}",
                    motor_id=mid, suggested_action=f"Position ≤ {hi}"))
        return out

    def _log_violations(self, violations: List[SafetyViolation]) -> None:
        """Log les violations au bon niveau."""
        for v in violations:
            level = {"critical": _LOG.critical, "error": _LOG.error}.get(
                v.severity, _LOG.warning)
            level("[%s] %s", self.robot_id, v.message)

    def _log_transition(self, prev: str, new_state: str) -> None:
        """Log la transition avec le bon niveau."""
        safety_states = {RobotState.EMERGENCY_STOP, RobotState.COMM_LOST,
                         RobotState.ERROR, RobotState.LOCKED}
        if new_state in safety_states:
            _LOG.log(SAFETY_LEVEL, "[%s] %s → %s", self.robot_id, prev, new_state)
        else:
            _LOG.info("[%s] %s → %s", self.robot_id, prev, new_state)


# ── Global Safety Manager (multi-robots) ─────────────────────────

class GlobalSafetyManager:
    """
    Orchestre les SafetyManagers de tous les robots.
    """

    def __init__(self) -> None:
        self._managers: Dict[str, RobotSafetyManager] = {}
        self._lock = threading.Lock()
        self._subscribe_events()

    def add_robot(self, robot_id: str, motor_ids: List[int]) -> RobotSafetyManager:
        """Enregistre un robot et retourne son manager."""
        mgr = RobotSafetyManager(robot_id, motor_ids)
        with self._lock:
            self._managers[robot_id] = mgr
        return mgr

    def get(self, robot_id: str) -> Optional[RobotSafetyManager]:
        """Retourne le manager d'un robot."""
        with self._lock:
            return self._managers.get(robot_id)

    def emergency_stop_all(self, source: str = "operator") -> None:
        """EMERGENCY STOP sur tous les robots."""
        _LOG.log(SAFETY_LEVEL, "⚡ EMERGENCY STOP GLOBAL — source: %s", source)
        with self._lock:
            managers = list(self._managers.values())
        for mgr in managers:
            mgr.force_emergency_stop(source)

    def soft_stop_all(self) -> None:
        """Soft stop sur tous les robots."""
        with self._lock:
            managers = list(self._managers.values())
        for mgr in managers:
            mgr.soft_stop()

    def lock_all(self) -> None:
        """Verrouille tous les robots."""
        with self._lock:
            managers = list(self._managers.values())
        for mgr in managers:
            mgr.lock()

    def unlock_all(self) -> None:
        """Déverrouille tous les robots."""
        with self._lock:
            managers = list(self._managers.values())
        for mgr in managers:
            mgr.unlock()

    # ── Gestion événements bus ──────────────────────────────────

    def _subscribe_events(self) -> None:
        """Souscrit aux événements safety du bus."""
        bus.subscribe("safety.comm_lost", self._on_comm_lost)
        bus.subscribe("safety.emergency_stop", self._on_emergency_stop_event)

    def _on_comm_lost(self, payload: dict) -> None:
        """Réaction à COMM_LOST."""
        robot_id = payload.get("robot_id", "")
        mgr = self.get(robot_id)
        if mgr:
            mgr.on_comm_lost()

    def _on_emergency_stop_event(self, payload: dict) -> None:
        """Réaction à emergency_stop depuis bus (ex: watchdog escalade).
        Ne re-force pas si le robot est déjà en EMERGENCY_STOP (évite boucle)."""
        robot_id = payload.get("robot_id", "")
        source = payload.get("source", "bus")
        mgr = self.get(robot_id)
        if mgr and mgr.state != RobotState.EMERGENCY_STOP:
            mgr.force_emergency_stop(source)


# Singleton global
safety = GlobalSafetyManager()
