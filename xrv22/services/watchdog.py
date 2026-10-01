"""
xr200/services/watchdog.py
───────────────────────────
Watchdog / Heartbeat pour la liaison série.

Principe :
  • Le SerialManager appelle watchdog.ping(robot_id) à chaque ACK reçu.
  • Le watchdog vérifie périodiquement que chaque robot a été pingé
    dans le délai max (défaut : 1500 ms).
  • Si timeout → publie "safety.comm_lost" sur le bus.

Escalade :
  • COMM_LOST pendant N secondes (défaut : 5s) → publie "safety.emergency_stop".
"""
from __future__ import annotations

import threading
import time
from typing import Dict

from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("Watchdog")

# Paramètres par défaut (modifiables via config)
HEARTBEAT_INTERVAL_S: float = 0.5    # Fréquence d'envoi heartbeat
COMM_TIMEOUT_S: float = 1.5          # Délai avant COMM_LOST
ESCALATE_TIMEOUT_S: float = 5.0      # Délai COMM_LOST → EMERGENCY_STOP


class RobotWatchdog:
    """Surveille la liaison d'un robot."""

    def __init__(self, robot_id: str) -> None:
        self.robot_id = robot_id
        self._last_ping: float = time.monotonic()
        self._comm_lost_since: float | None = None
        self._active = False

    # ── API publique ─────────────────────────────────────────────

    def ping(self) -> None:
        """Appelé par SerialManager à chaque ACK/réponse reçue."""
        self._last_ping = time.monotonic()
        if self._comm_lost_since is not None:
            _LOG.info("[%s] Communication rétablie", self.robot_id)
            self._comm_lost_since = None

    def check(self) -> None:
        """Vérifie l'état de la liaison. Appelé par WatchdogService."""
        elapsed = time.monotonic() - self._last_ping
        if elapsed < COMM_TIMEOUT_S:
            return
        if self._comm_lost_since is None:
            self._on_comm_lost()
        elif self._should_escalate():
            self._on_escalate()

    # ── Privé ────────────────────────────────────────────────────

    def _on_comm_lost(self) -> None:
        """Déclenche l'état COMM_LOST (publié une seule fois)."""
        self._comm_lost_since = time.monotonic()
        _LOG.warning("[%s] COMM_LOST — liaison perdue", self.robot_id)
        bus.publish("safety.comm_lost", {"robot_id": self.robot_id})

    def _on_escalate(self) -> None:
        """Escalade vers EMERGENCY_STOP."""
        _LOG.error("[%s] COMM_LOST escalade → EMERGENCY_STOP", self.robot_id)
        bus.publish("safety.emergency_stop", {
            "robot_id": self.robot_id,
            "source": "watchdog_escalation"
        })
        self._comm_lost_since = None  # Reset pour éviter boucle

    def _should_escalate(self) -> bool:
        """Vrai si COMM_LOST dure trop longtemps."""
        if self._comm_lost_since is None:
            return False
        return (time.monotonic() - self._comm_lost_since) >= ESCALATE_TIMEOUT_S


class WatchdogService:
    """Service global qui orchestre tous les RobotWatchdog."""

    def __init__(self) -> None:
        self._dogs: Dict[str, RobotWatchdog] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    def register(self, robot_id: str) -> None:
        """Enregistre un robot à surveiller."""
        with self._lock:
            self._dogs[robot_id] = RobotWatchdog(robot_id)
        _LOG.info("Watchdog enregistré pour %s", robot_id)

    def unregister(self, robot_id: str) -> None:
        """Retire un robot de la surveillance."""
        with self._lock:
            self._dogs.pop(robot_id, None)

    def ping(self, robot_id: str) -> None:
        """Notifie qu'une réponse a été reçue du robot."""
        with self._lock:
            dog = self._dogs.get(robot_id)
        if dog:
            dog.ping()

    def start(self) -> None:
        """Démarre le thread de surveillance."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="WatchdogSvc")
        self._thread.start()
        _LOG.info("WatchdogService démarré")

    def stop(self) -> None:
        """Arrête le thread de surveillance."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    # ── Privé ────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Boucle de vérification périodique."""
        while self._running:
            self._check_all()
            time.sleep(HEARTBEAT_INTERVAL_S)

    def _check_all(self) -> None:
        """Vérifie tous les robots enregistrés."""
        with self._lock:
            dogs = list(self._dogs.values())
        for dog in dogs:
            dog.check()


# Singleton global
watchdog = WatchdogService()
