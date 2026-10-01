"""
xr200/core/execution_engine.py
────────────────────────────────
Moteur d'exécution central — Orchestrateur de la timeline.

Responsabilités :
  - Recevoir les événements du scheduler
  - Les dispatcher vers les handlers par type
  - Coordonner avec le SafetyManager avant chaque action
  - Coordonner avec les RobotControllers pour les MOVE
  - Gérer les sync markers (attente multi-robots)
  - Publier les résultats sur l'EventBus

Règle fondamentale :
  L'UI ne connaît pas l'ExecutionEngine directement.
  Elle publie "engine.command" → l'engine réagit.
  Elle lit le StateStore pour l'état.

Handlers par type d'événement (dispatch table, pas if-elif) :
  MOVE           → _handle_move()
  WAIT           → _handle_wait()
  SENSOR_WAIT    → _handle_sensor_wait()
  ARDUINO_ACTION → _handle_arduino_action()
  CALL_SEQUENCE  → _handle_call_sequence()
  SYNC_MARKER    → _handle_sync_marker()
  PAUSE          → _handle_pause()
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

from xrv22.timeline.timeline_event import TimelineEvent, EventType, EventState
from xrv22.timeline.timeline_model import TimelineModel
from xrv22.core.event_scheduler import EventScheduler
from xrv22.core.safety_manager import safety, RobotState
from xrv22.core.state_store import store
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL
from xrv22.simulation.kinematics import check_zone_collision
from xrv22.library.library_manager import library

_LOG = get_logger("ExecutionEngine")

# Type des handlers
Handler = Callable[[TimelineEvent], None]


class EngineState:
    IDLE    = "IDLE"
    RUNNING = "RUNNING"
    PAUSED  = "PAUSED"
    STOPPED = "STOPPED"
    ERROR   = "ERROR"


class ExecutionEngine:
    """
    Orchestre l'exécution de la timeline.
    """

    def __init__(self) -> None:
        self._model: Optional[TimelineModel] = None
        self._scheduler: Optional[EventScheduler] = None
        self._state = EngineState.IDLE
        self._lock = threading.Lock()
        self._sync_groups: Dict[str, List[str]] = {}  # group_id → [event_ids]
        self._sync_barriers: Dict[str, threading.Barrier] = {}
        self._sensor_callbacks: Dict[str, threading.Event] = {}
        self._handler_threads: List[threading.Thread] = []

        # Dispatch table — pas de if-elif
        self._handlers: Dict[str, Handler] = {
            EventType.MOVE:           self._handle_move,
            EventType.WAIT:           self._handle_wait,
            EventType.SENSOR_WAIT:    self._handle_sensor_wait,
            EventType.ARDUINO_ACTION: self._handle_arduino_action,
            EventType.CALL_SEQUENCE:  self._handle_call_sequence,
            EventType.SYNC_MARKER:    self._handle_sync_marker,
            EventType.PAUSE:          self._handle_pause,
        }

        self._subscribe_bus()

    # ── Configuration ────────────────────────────────────────────

    def set_model(self, model: TimelineModel) -> None:
        """Attache un modèle timeline à l'engine."""
        self._model = model
        self._scheduler = EventScheduler(model)
        self._scheduler.set_callbacks(
            on_events=self._on_events_due,
            on_tick=self._on_tick,
            on_done=self._on_done,
        )

    # ── Commandes publiques ──────────────────────────────────────

    def play(self, from_ms: int = 0) -> bool:
        """Démarre la lecture de la timeline."""
        if self._model is None:
            _LOG.error("Aucun modèle timeline chargé")
            return False
        not_ready = self._robots_not_ready_for_timeline()
        if not_ready:
            _LOG.error("Robots non prets pour la timeline : %s", not_ready)
            bus.publish("engine.error", {
                "event_type": "PLAY",
                "message": "Robot(s) non pret(s) : "
                           + ", ".join(f"{rid}={st}" for rid, st in not_ready),
            })
            return False

        ok = self._scheduler.play(from_ms)
        if ok:
            self._state = EngineState.RUNNING
            store.set_system(execution_state="RUNNING")
        return ok

    def pause(self) -> bool:
        """Pause la lecture."""
        if self._scheduler is None:
            return False
        ok = self._scheduler.pause()
        if ok:
            self._state = EngineState.PAUSED
            store.set_system(execution_state="PAUSED")
        return ok

    def stop(self) -> None:
        """Arrête la lecture, attend les handlers, remet à zéro."""
        if self._scheduler:
            self._scheduler.stop()
        # Attendre la fin des handlers en cours (timeout 2s chacun)
        with self._lock:
            threads = list(self._handler_threads)
            self._handler_threads.clear()
        for t in threads:
            t.join(timeout=2.0)
        # Nettoyer les sync barriers
        with self._lock:
            for barrier in self._sync_barriers.values():
                barrier.abort()
            self._sync_barriers.clear()
            self._sync_groups.clear()
        self._state = EngineState.STOPPED
        store.set_system(execution_state="STOPPED")
        self._release_control()

    def seek(self, ms: int) -> None:
        """Repositionne la lecture."""
        if self._scheduler:
            self._scheduler.seek(ms)

    @property
    def state(self) -> str:
        return self._state

    @property
    def elapsed_ms(self) -> int:
        if self._scheduler:
            return self._scheduler.elapsed_ms
        return 0

    # ── Callbacks scheduler ──────────────────────────────────────

    def _on_events_due(self, events: List[TimelineEvent]) -> None:
        """Dispatche les événements arrivés à échéance."""
        for evt in events:
            self._dispatch(evt)

    def _on_tick(self, elapsed_ms: int) -> None:
        """Notifie l'UI du tick courant."""
        bus.publish("engine.tick", {"elapsed_ms": elapsed_ms})

    def _on_done(self) -> None:
        """Appelé à la fin de la timeline."""
        self._state = EngineState.STOPPED
        store.set_system(execution_state="IDLE")
        self._release_control()
        _LOG.info("Exécution timeline terminée")

    # ── Dispatch ─────────────────────────────────────────────────

    def _dispatch(self, evt: TimelineEvent) -> None:
        """Dispatch via table, dans un thread pour ne pas bloquer le scheduler."""
        handler = self._handlers.get(evt.event_type)
        if handler is None:
            _LOG.warning("Type d'événement inconnu : %s", evt.event_type)
            self._model.mark_event_state(evt.event_id, EventState.SKIPPED)
            return

        self._model.mark_event_state(evt.event_id, EventState.RUNNING)
        bus.publish("timeline.event_started", {
            "event_id": evt.event_id, "track_id": evt.track_id
        })

        t = threading.Thread(
            target=self._run_handler_safe,
            args=(handler, evt),
            daemon=True,
            name=f"Handler-{evt.event_type}-{evt.event_id[:6]}"
        )
        with self._lock:
            self._handler_threads.append(t)
        t.start()

    def _run_handler_safe(self, handler: Handler,
                           evt: TimelineEvent) -> None:
        """Exécute un handler avec protection d'exception et escalade."""
        try:
            handler(evt)
            self._model.mark_event_state(evt.event_id, EventState.DONE)
        except Exception as exc:
            _LOG.error("Handler %s error sur %s : %s",
                       evt.event_type, evt.event_id, exc, exc_info=True)
            self._model.mark_event_state(evt.event_id, EventState.ERROR)
            # Escalade : mettre l'engine en erreur et arrêter
            with self._lock:
                self._state = EngineState.ERROR
            store.set_system(execution_state="ERROR")
            bus.publish("engine.error", {
                "event_id": evt.event_id,
                "event_type": evt.event_type,
                "message": str(exc),
            })
            if self._scheduler:
                self._scheduler.stop()

        bus.publish("timeline.event_done", {"event_id": evt.event_id})

    # ── Handlers par type ────────────────────────────────────────

    def _handle_move(self, evt: TimelineEvent) -> None:
        """Exécute un MOVE sur le robot cible et attend la fin."""
        robot_id = evt.get_param("robot_id") or self._robot_id_from_track(evt.track_id)
        if robot_id is None:
            raise RuntimeError(f"MOVE : robot_id introuvable pour {evt.event_id}")

        from xrv22.robots.robot_registry import registry
        ctrl = registry.get(robot_id)
        if ctrl is None:
            raise RuntimeError(f"MOVE : robot {robot_id} non enregistré")

        positions = evt.get_param("positions", {})
        duration_s = evt.get_param("duration_s", evt.duration_s)
        # Vitesse variable : speed_pct=200 → 2× plus rapide (durée ÷ 2)
        speed_pct = evt.get_param("speed_pct", 100)
        if speed_pct and speed_pct > 0 and speed_pct != 100:
            duration_s = duration_s * 100.0 / speed_pct

        # Vérification collision avec zones d'exclusion
        zones = library.list_zones()
        zone_name = check_zone_collision(positions, zones)
        if zone_name is not None:
            _LOG.warning("MOVE bloqué [%s] : collision zone exclusion '%s'",
                         robot_id, zone_name)
            bus.publish("engine.zone_collision", {
                "event_id": evt.event_id,
                "robot_id": robot_id,
                "zone_name": zone_name,
            })
            raise RuntimeError(
                f"MOVE bloqué [{robot_id}] : TCP dans zone exclusion '{zone_name}'"
            )

        ok, msg = ctrl.move(positions, duration_s)
        if not ok:
            raise RuntimeError(f"MOVE échoué [{robot_id}] : {msg}")

        # Attente bloquante : poll le StateStore jusqu'à fin du mouvement
        self._wait_move_completion(robot_id, positions, duration_s)

    def _handle_wait(self, evt: TimelineEvent) -> None:
        """Pause temporelle pure."""
        time.sleep(evt.duration_s)

    def _handle_sensor_wait(self, evt: TimelineEvent) -> None:
        """Attente signal capteur avec timeout."""
        sensor_id = evt.get_param("sensor_id", "")
        timeout_s = evt.get_param("timeout_ms", 10000) / 1000.0
        on_timeout = evt.get_param("on_timeout", "error")

        trigger = threading.Event()
        with self._lock:
            self._sensor_callbacks[sensor_id] = trigger

        triggered = trigger.wait(timeout=timeout_s)

        with self._lock:
            self._sensor_callbacks.pop(sensor_id, None)

        if not triggered:
            _LOG.warning("SENSOR_WAIT timeout : capteur %s", sensor_id)
            if on_timeout == "error":
                raise TimeoutError(f"Sensor {sensor_id} timeout")

    def _handle_arduino_action(self, evt: TimelineEvent) -> None:
        """Commande Arduino via le bus."""
        bus.publish("arduino.action", {
            "device_name": evt.get_param("device_name", ""),
            "action_name": evt.get_param("action_name", ""),
            "params":      evt.get_param("params", {}),
            "event_id":    evt.event_id,
        })
        time.sleep(evt.duration_s)

    def _handle_call_sequence(self, evt: TimelineEvent) -> None:
        """Exécute une suite (délégation au SequenceEngine)."""
        seq_id = evt.get_param("sequence_id", "")
        bus.publish("engine.call_sequence", {
            "sequence_id": seq_id, "event_id": evt.event_id
        })

    def _handle_sync_marker(self, evt: TimelineEvent) -> None:
        """Attend tous les robots du groupe avec threading.Barrier.

        Sur BrokenBarrierError (timeout ou abort), la barrier est retiree du
        cache pour garantir que le prochain play recree une barrier saine.
        """
        group_id = evt.get_param("group_id", "")
        robot_count = evt.get_param("robot_count", 2)
        timeout_s = evt.get_param("timeout_s", 30.0)

        with self._lock:
            barrier = self._sync_barriers.get(group_id)
            if barrier is None or barrier.broken:
                barrier = threading.Barrier(robot_count)
                self._sync_barriers[group_id] = barrier

        _LOG.info("SYNC_MARKER groupe %s — en attente (parties=%d)", group_id, robot_count)
        try:
            barrier.wait(timeout=timeout_s)
            _LOG.info("SYNC_MARKER groupe %s — synchronisé", group_id)
        except threading.BrokenBarrierError:
            with self._lock:
                self._sync_barriers.pop(group_id, None)
            raise RuntimeError(
                f"SYNC_MARKER groupe {group_id} — barrier cassée (timeout ou erreur)"
            )

    def _handle_pause(self, evt: TimelineEvent) -> None:
        """Pause opérateur (suspend le scheduler)."""
        _LOG.info("PAUSE opérateur")
        self.pause()
        bus.publish("engine.operator_pause", {"event_id": evt.event_id})

    # ── Gestion capteurs (depuis bus) ────────────────────────────

    def _on_sensor_triggered(self, payload: dict) -> None:
        """Libère le SENSOR_WAIT correspondant."""
        sensor_id = payload.get("sensor_id", "")
        with self._lock:
            trigger = self._sensor_callbacks.get(sensor_id)
        if trigger:
            trigger.set()

    # ── Souscriptions bus ────────────────────────────────────────

    def _subscribe_bus(self) -> None:
        """Souscrit aux événements entrants."""
        bus.subscribe("sensor.triggered", self._on_sensor_triggered)
        bus.subscribe("safety.emergency_stop", self._on_emergency_stop)

    def _on_emergency_stop(self, payload: dict) -> None:
        """Arrêt immédiat sur emergency stop."""
        _LOG.log(SAFETY_LEVEL, "ExecutionEngine : EMERGENCY STOP reçu")
        self.stop()

    # ── Utilitaires ──────────────────────────────────────────────

    @staticmethod
    def _positions_at_target(snap, targets: Dict[int, int], tolerance: int) -> bool:
        """True si toutes les positions du snap sont à ±tolerance des cibles."""
        if not (snap and snap.positions):
            return False
        for mid, target in targets.items():
            current = snap.positions.get(mid)
            if current is None or abs(current - target) > tolerance:
                return False
        return True

    def _report_move_timeout(self, robot_id: str, timeout: float) -> None:
        """Après timeout : lève si erreurs HW, sinon log un warning."""
        hw_errors = self._check_motor_hardware_errors(robot_id)
        if hw_errors:
            motors_str = ", ".join(
                f"moteur {mid}: {', '.join(errs)}"
                for mid, errs in hw_errors.items())
            raise RuntimeError(
                f"MOVE echoue [{robot_id}] — moteur(s) en securite : {motors_str}")
        _LOG.warning("MOVE timeout [%s] : positions cibles non atteintes après %.1fs",
                     robot_id, timeout)

    def _wait_move_completion(self, robot_id: str, targets: Dict[int, int],
                               duration_s: float, tolerance: int = 50) -> None:
        """Attend que le mouvement soit terminé (poll StateStore + timeout).
        Détecte les erreurs hardware moteur au lieu de ruminer indéfiniment."""
        timeout = duration_s + 2.0  # Marge de sécurité
        poll_interval = 0.1
        hw_check_interval = 0.5    # Vérification erreurs HW toutes les 500 ms
        deadline = time.time() + timeout
        last_hw_check = 0.0
        while time.time() < deadline:
            if self._state not in (EngineState.RUNNING, EngineState.PAUSED):
                return
            snap = store.get_robot(robot_id)
            if self._positions_at_target(snap, targets, tolerance):
                return
            now = time.time()
            if now - last_hw_check >= hw_check_interval:
                last_hw_check = now
                self._check_motor_hardware_errors(robot_id)
            time.sleep(poll_interval)
        self._report_move_timeout(robot_id, timeout)

    def _check_motor_hardware_errors(self, robot_id: str) -> Dict[int, list]:
        """Verifie les erreurs hardware et publie sur le bus si detectees."""
        from xrv22.robots.robot_registry import registry
        ctrl = registry.get(robot_id)
        if ctrl is None:
            return {}
        hw_errors = ctrl.read_hardware_errors()
        if hw_errors:
            bus.publish("motor.hardware_error", {
                "robot_id": robot_id,
                "errors": {mid: errs for mid, errs in hw_errors.items()},
            })
        return hw_errors

    def _all_robots_ready(self) -> bool:
        """Vérifie que tous les robots sont en état jouable."""
        from xrv22.robots.robot_registry import registry
        playable = {RobotState.IDLE, RobotState.READY}
        return all(ctrl.state in playable for ctrl in registry.all())

    def _robots_used_in_timeline(self) -> List[str]:
        """Liste des robot_id reellement utilises par la timeline courante.

        Permet de ne pas bloquer un play() sur un robot du registry qui n'a
        aucun evenement dans la timeline (ex : robot_4 deconnecte alors que
        l'utilisateur ne joue qu'une suite sur robot_1).
        """
        if self._model is None:
            return []
        used = set()
        for track in self._model.ordered_tracks():
            if not track.robot_id:
                continue
            for evt in track.all_events():
                if evt.event_type == EventType.MOVE:
                    used.add(track.robot_id)
                    break
        return sorted(used)

    def _robots_not_ready_for_timeline(self) -> List[tuple]:
        """Retourne [(robot_id, state)] des robots utilises non prets.

        Liste vide = tout est OK pour lancer. Filtre les robots non utilises
        par la timeline (deconnectes mais inactifs n'empechent plus le play).
        """
        from xrv22.robots.robot_registry import registry
        playable = {RobotState.IDLE, RobotState.READY}
        used = self._robots_used_in_timeline()
        not_ready = []
        for rid in used:
            ctrl = registry.get(rid)
            if ctrl is None:
                not_ready.append((rid, "ABSENT"))
            elif ctrl.state not in playable:
                not_ready.append((rid, ctrl.state))
        return not_ready

    def _release_control(self) -> None:
        """Libere la main prise sur les robots de la timeline au lancement.

        Symetrique du garde-fou anti-conflit pris cote API au play : a la fin
        (stop manuel ou fin naturelle de la timeline) on remet control_owner a
        None et on publie robot.control_changed pour signaler la main libre.
        On ne libere que ce que l'engine avait pris (owner == "engine") : si un
        client a repris la main entre-temps, on ne l'ecrase pas.
        """
        from xrv22.robots.robot_registry import registry
        for rid in self._robots_used_in_timeline():
            ctrl = registry.get(rid)
            if ctrl is None:
                continue
            if getattr(ctrl, "control_owner", None) == "engine":
                ctrl.control_owner = None
                bus.publish("robot.control_changed",
                            {"robot_id": rid, "owner": None})

    def _robot_id_from_track(self, track_id: str) -> Optional[str]:
        """Extrait le robot_id depuis un track_id (track_robot_1 → robot_1)."""
        if not self._model:
            return None
        track = self._model.get_track(track_id)
        if track and track.robot_id:
            return track.robot_id
        return None


# Singleton global
engine = ExecutionEngine()
