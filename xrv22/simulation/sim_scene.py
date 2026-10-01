"""
xr200/simulation/sim_scene.py
───────────────────────────────
Scène de simulation complète.

Responsabilités :
  1. Brancher la SimInterpolator sur les commandes MOVE série
  2. Générer des données capteurs fictives (sin wave)
  3. Simuler les réponses Arduino aux actions
  4. Publier des états safe sur le watchdog

La scène écoute sur le bus les événements série/robot et
s'y substitue en mode simulation.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Dict

from xrv22.simulation.sim_interpolator import sim_interpolator
from xrv22.core.state_store import store
from xrv22.services.event_bus import bus
from xrv22.services.watchdog import watchdog
from xrv22.services.logger import get_logger

_LOG = get_logger("SimScene")

SENSOR_UPDATE_HZ = 5.0     # Mise à jour capteurs fictifs
SENSOR_TICK_S    = 1.0 / SENSOR_UPDATE_HZ


class SimScene:
    """
    Scène de simulation.
    Instanciée uniquement en mode simulation.
    """

    def __init__(self) -> None:
        self._running = False
        self._thread: threading.Thread | None = None
        self._t = 0.0                # Temps accumulé pour sinus
        self._robots: Dict[str, bool] = {}  # robot_id → simulé

    # ── Cycle de vie ─────────────────────────────────────────────

    def start(self) -> None:
        """Démarre la scène de simulation."""
        if self._running:
            return
        self._running = True
        sim_interpolator.start()
        self._subscribe()
        self._thread = threading.Thread(
            target=self._sensor_loop, daemon=True, name="SimScene")
        self._thread.start()
        _LOG.info("SimScene démarrée")

    def stop(self) -> None:
        """Arrête la scène et nettoie les abonnements."""
        self._running = False
        sim_interpolator.stop()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._unsubscribe()

    def register_robot(self, robot_id: str) -> None:
        """Enregistre un robot dans la scène."""
        self._robots[robot_id] = True
        _LOG.debug("SimScene : robot %s enregistré", robot_id)

    # ── Souscriptions bus ────────────────────────────────────────

    def _subscribe(self) -> None:
        """Écoute les commandes série pour intercepter les MOVEs."""
        bus.subscribe("serial.move_sent",   self._on_move_sent)
        bus.subscribe("serial.stop_sent",   self._on_stop_sent)
        bus.subscribe("arduino.action",     self._on_arduino_action)

    def _unsubscribe(self) -> None:
        """Retire les abonnements bus (évite doublons sur restart)."""
        bus.unsubscribe("serial.move_sent",   self._on_move_sent)
        bus.unsubscribe("serial.stop_sent",   self._on_stop_sent)
        bus.unsubscribe("arduino.action",     self._on_arduino_action)

    def _on_move_sent(self, payload: dict) -> None:
        """
        Intercepte un MOVE série et démarre l'interpolation.
        payload : { robot_id, positions, duration_ms }
        """
        robot_id   = payload.get("robot_id", "")
        positions  = payload.get("positions", {})
        duration_ms = payload.get("duration_ms", 2000)

        if robot_id not in self._robots:
            return

        sim_interpolator.queue_move(
            robot_id, positions, duration_ms / 1000.0)

    def _on_stop_sent(self, payload: dict) -> None:
        """Annule le mouvement simulé sur STOP/E-STOP."""
        robot_id = payload.get("robot_id", "")
        sim_interpolator.cancel_move(robot_id)

    def _on_arduino_action(self, payload: dict) -> None:
        """
        Simule une réponse Arduino après un délai fictif.
        Publie serial.ack pour débloquer l'ExecutionEngine.
        """
        device = payload.get("device_name", "?")
        action = payload.get("action_name", "?")
        event_id = payload.get("event_id", "")
        _LOG.debug("[SIM] Arduino %s.%s simulé", device, action)

        def _ack():
            time.sleep(0.1)
            bus.publish("serial.ack", {
                "robot_id": "arduino",
                "sim": True,
                "event_id": event_id,
            })

        threading.Thread(target=_ack, daemon=True).start()

    # ── Capteurs fictifs ──────────────────────────────────────────

    def _sensor_loop(self) -> None:
        """Génère des valeurs capteurs fictives (sinus)."""
        while self._running:
            self._t += SENSOR_TICK_S
            self._publish_fake_sensors()
            time.sleep(SENSOR_TICK_S)

    def _publish_fake_sensors(self) -> None:
        """
        Publie des lectures capteurs fictives sur le bus.
        Format identique aux vrais capteurs Arduino.
        """
        for robot_id in self._robots:
            # Capteur de position analogique fictif (sin 0–1023)
            val = int(512 + 511 * math.sin(self._t * 0.5))
            bus.publish("sensor.reading", {
                "robot_id": robot_id,
                "sensor_id": f"sim_analog_{robot_id}",
                "value": val,
                "unit": "raw",
                "sim": True,
            })
            # Keepalive watchdog
            watchdog.ping(robot_id)


# Singleton — instancié uniquement si simulation=True
_scene_instance: SimScene | None = None


def get_scene() -> SimScene:
    """Retourne ou crée la scène de simulation."""
    global _scene_instance
    if _scene_instance is None:
        _scene_instance = SimScene()
    return _scene_instance
