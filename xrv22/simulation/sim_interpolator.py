"""
xr200/simulation/sim_interpolator.py
──────────────────────────────────────
Interpolation de positions pour le mode simulation.

Rôle :
  En mode simulation, il n'y a pas de retour série confirmant les positions.
  Ce module simule le mouvement en interpolant les positions courantes
  vers les positions cibles avec un profil smoothstep, et met à jour
  le StateStore à chaque step.

Algorithme :
  x  = t / duration          (t ∈ [0..duration])
  s  = 3x² − 2x³             (smoothstep cubique)
  p  = p_start + s * (p_end − p_start)

Tick rate : 50ms (idem EventScheduler), en thread daemon.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional

from xrv22.core.state_store import store
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("SimInterpolator")

TICK_S = 0.05       # 50ms — résolution interpolation
HZ     = 1.0 / TICK_S


def smoothstep(x: float) -> float:
    """Interpolation cubique smooth."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _interp_positions(start: Dict[int, int], end: Dict[int, int],
                       t: float) -> Dict[int, int]:
    """
    Interpolation linéaire (avec smoothstep) entre deux snapshots.
    Les moteurs absents de `end` ne sont pas touchés.
    """
    result = dict(start)
    for mid, p_end in end.items():
        p_start = start.get(mid, p_end)
        result[mid] = round(p_start + t * (p_end - p_start))
    return result


class SimMove:
    """Représente un mouvement en cours d'interpolation."""
    __slots__ = ("robot_id", "start_pos", "target_pos",
                  "start_time", "duration_s", "done")

    def __init__(self, robot_id: str, start_pos: Dict[int, int],
                  target_pos: Dict[int, int], duration_s: float) -> None:
        self.robot_id  = robot_id
        self.start_pos = dict(start_pos)
        self.target_pos = dict(target_pos)
        self.duration_s = max(0.01, duration_s)
        self.start_time = time.monotonic()
        self.done = False

    def tick(self) -> Dict[int, int]:
        """Calcule les positions à l'instant courant. Marque done si terminé."""
        elapsed = time.monotonic() - self.start_time
        t_norm = elapsed / self.duration_s
        if t_norm >= 1.0:
            self.done = True
            return dict(self.target_pos)
        smooth_t = smoothstep(t_norm)
        return _interp_positions(self.start_pos, self.target_pos, smooth_t)


class SimInterpolator:
    """
    Moteur d'interpolation simulation multi-robots.
    """

    def __init__(self) -> None:
        self._moves: Dict[str, SimMove] = {}   # robot_id → SimMove actif
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── Cycle de vie ─────────────────────────────────────────────

    def start(self) -> None:
        """Démarre le thread d'interpolation."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="SimInterpolator")
        self._thread.start()
        _LOG.info("SimInterpolator démarré")

    def stop(self) -> None:
        """Arrête proprement."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    # ── Enregistrement de mouvements ─────────────────────────────

    def queue_move(self, robot_id: str, target_positions: Dict[int, int],
                    duration_s: float) -> None:
        """Enregistre un nouveau mouvement à interpoler."""
        snap = store.get_robot(robot_id)
        start_pos = dict(snap.positions) if snap else {}
        move = SimMove(robot_id, start_pos, target_positions, duration_s)
        with self._lock:
            self._moves[robot_id] = move
        _LOG.debug("[%s] SimMove queued → %s en %.1fs", robot_id, target_positions, duration_s)

    def cancel_move(self, robot_id: str) -> None:
        """Annule le mouvement en cours pour un robot."""
        with self._lock:
            self._moves.pop(robot_id, None)

    def cancel_all(self) -> None:
        """Annule tous les mouvements."""
        with self._lock:
            self._moves.clear()

    # ── Boucle principale ────────────────────────────────────────

    def _loop(self) -> None:
        """Tick loop : interpole et publie les positions."""
        while self._running:
            t_start = time.monotonic()
            self._tick()
            elapsed = time.monotonic() - t_start
            sleep_s = max(0.0, TICK_S - elapsed)
            time.sleep(sleep_s)

    def _tick(self) -> None:
        """Traite tous les mouvements actifs (lock complet pour atomicité)."""
        done_ids = []
        with self._lock:
            moves = list(self._moves.items())

            for robot_id, move in moves:
                positions = move.tick()
                store.set_positions(robot_id, positions)
                if move.done:
                    done_ids.append(robot_id)

            for rid in done_ids:
                self._moves.pop(rid, None)

        # Publications hors du lock pour éviter les deadlocks
        if moves:
            bus.publish("ui.refresh", {"source": "sim"})
        for rid in done_ids:
            _LOG.debug("[%s] SimMove terminé", rid)
            bus.publish("serial.ack", {"robot_id": rid, "sim": True})


# Singleton
sim_interpolator = SimInterpolator()
