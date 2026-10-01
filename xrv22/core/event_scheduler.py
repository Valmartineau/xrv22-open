"""
xr200/core/event_scheduler.py
───────────────────────────────
Planificateur d'événements temporels.

Rôle :
  - Maintenir un horloge de lecture (elapsed_ms)
  - Interroger la timeline à chaque tick
  - Retourner les événements à déclencher
  - Gérer play / pause / stop / seek

Architecture :
  Le scheduler ne sait PAS comment exécuter les événements.
  Il retourne des listes d'événements via callbacks.
  L'ExecutionEngine les exécute.

Tick rate : 50ms (configurable). Suffisant pour une précision à 50ms,
acceptable pour du robotique non temps-réel strict.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from xrv22.timeline.timeline_model import TimelineModel
from xrv22.timeline.timeline_event import TimelineEvent
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("EventScheduler")

TICK_MS: int = 50          # Résolution temporelle
TICK_S:  float = TICK_MS / 1000.0


class SchedulerState:
    IDLE    = "IDLE"
    PLAYING = "PLAYING"
    PAUSED  = "PAUSED"
    STOPPED = "STOPPED"


EventCallback = Callable[[List[TimelineEvent]], None]


class EventScheduler:
    """
    Horloge de lecture de la timeline.
    """

    def __init__(self, model: TimelineModel) -> None:
        self._model = model
        self._state = SchedulerState.IDLE
        self._elapsed_ms: int = 0
        self._base_ms: int = 0             # Position de départ du play courant
        self._start_wall: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._on_events: Optional[EventCallback] = None
        self._on_tick: Optional[Callable[[int], None]] = None
        self._on_done: Optional[Callable[[], None]] = None
        # Borne superieure deja scannee. Permet une fenetre dynamique pour
        # rattraper les events manques si un tick tarde (GC, swap Raspberry).
        self._last_scan_end_ms: int = 0

    # ── API publique ─────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    @property
    def elapsed_ms(self) -> int:
        return self._elapsed_ms

    @property
    def elapsed_s(self) -> float:
        return self._elapsed_ms / 1000.0

    def set_callbacks(self, on_events: EventCallback,
                      on_tick: Optional[Callable[[int], None]] = None,
                      on_done: Optional[Callable[[], None]] = None) -> None:
        """Enregistre les callbacks de l'ExecutionEngine."""
        self._on_events = on_events
        self._on_tick = on_tick
        self._on_done = on_done

    def play(self, from_ms: int = 0) -> bool:
        """Démarre ou reprend la lecture."""
        with self._lock:
            if self._state == SchedulerState.PLAYING:
                return False
            if self._state == SchedulerState.PAUSED:
                self._resume()
                bus.publish("timeline.play", {"from_ms": self._elapsed_ms, "resumed": True})
                _LOG.info("Timeline RESUME depuis %dms", self._elapsed_ms)
                return True
            self._base_ms = max(0, from_ms)
            self._elapsed_ms = self._base_ms
            self._state = SchedulerState.PLAYING

        self._model.reset_all_states()
        self._start_scheduler_thread()
        bus.publish("timeline.play", {"from_ms": from_ms})
        _LOG.info("Timeline PLAY depuis %dms", from_ms)
        return True

    def pause(self) -> bool:
        """Met la lecture en pause."""
        with self._lock:
            if self._state != SchedulerState.PLAYING:
                return False
            self._state = SchedulerState.PAUSED
        self._stop_event.set()
        bus.publish("timeline.pause", {"elapsed_ms": self._elapsed_ms})
        _LOG.info("Timeline PAUSED à %dms", self._elapsed_ms)
        return True

    def stop(self) -> None:
        """Arrête la lecture et remet à zéro."""
        with self._lock:
            self._state = SchedulerState.STOPPED
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
            if self._thread.is_alive():
                _LOG.warning("Scheduler thread toujours actif après timeout")
            self._thread = None
        self._elapsed_ms = 0
        self._base_ms = 0
        # Ne PAS reset_all_states ici : ecraserait l'etat ERROR/DONE des events
        # qui viennent de finir (notamment celui qui a fait crasher le handler).
        # play() fait deja un reset complet avant chaque nouvelle lecture.
        self._model.set_cursor(0)
        bus.publish("timeline.stop", {})
        _LOG.info("Timeline STOP")

    def seek(self, ms: int) -> None:
        """Positionne le curseur (arrêt + repositionnement)."""
        was_playing = self._state == SchedulerState.PLAYING
        self.stop()
        self._elapsed_ms = max(0, ms)
        self._base_ms = self._elapsed_ms
        self._model.set_cursor(self._elapsed_ms)
        if was_playing:
            self.play(from_ms=self._elapsed_ms)

    # ── Thread de lecture ────────────────────────────────────────

    def _start_scheduler_thread(self) -> None:
        """Démarre le thread de tick."""
        self._stop_event.clear()
        self._start_wall = time.monotonic()
        # Reprend le scan depuis la position courante (play ou resume apres pause)
        self._last_scan_end_ms = self._base_ms
        self._thread = threading.Thread(
            target=self._tick_loop, daemon=True, name="Scheduler")
        self._thread.start()

    def _tick_loop(self) -> None:
        """Boucle principale du scheduler (avec rattrapage de dérive)."""
        duration_ms = self._model.duration_ms()
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            next_tick += TICK_S

            self._process_tick(duration_ms)

            if self._elapsed_ms >= duration_ms:
                self._on_timeline_done()
                break

            sleep_s = max(0, next_tick - time.monotonic())
            if sleep_s > 0:
                time.sleep(sleep_s)

    def _process_tick(self, duration_ms: int) -> None:
        """Traite un tick : collecte + dispatch les événements.

        Fenetre de scan DYNAMIQUE : couvre tout l'intervalle
        [_last_scan_end_ms, elapsed + TICK_MS). Si un tick tarde (GC, swap),
        on rattrape les events rates au lieu de les perdre.
        """
        self._elapsed_ms = self._compute_elapsed()
        self._model.set_cursor(self._elapsed_ms)

        scan_start = self._last_scan_end_ms
        scan_end = self._elapsed_ms + TICK_MS
        if scan_end > scan_start:
            window = scan_end - scan_start
            if window > TICK_MS * 3:
                _LOG.warning(
                    "Scheduler en retard — rattrapage fenetre %dms (tick attendu %dms)",
                    window, TICK_MS,
                )
            due = self._model.events_due_at(scan_start, window_ms=window)
            if due and self._on_events:
                self._on_events(due)
            self._last_scan_end_ms = scan_end

        if self._on_tick:
            self._on_tick(self._elapsed_ms)

    def _compute_elapsed(self) -> int:
        """Calcule le temps écoulé = base + temps depuis le start_wall."""
        wall_ms = int((time.monotonic() - self._start_wall) * 1000)
        return self._base_ms + wall_ms

    def _resume(self) -> None:
        """Reprend depuis PAUSED en repartant du point courant."""
        self._base_ms = self._elapsed_ms
        self._state = SchedulerState.PLAYING
        self._start_scheduler_thread()

    def _on_timeline_done(self) -> None:
        """Appelé quand la timeline est terminée."""
        self._state = SchedulerState.STOPPED
        bus.publish("timeline.done", {"elapsed_ms": self._elapsed_ms})
        _LOG.info("Timeline terminée à %dms", self._elapsed_ms)
        if self._on_done:
            self._on_done()
