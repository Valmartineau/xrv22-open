"""
xr200/timeline/timeline_model.py
──────────────────────────────────
Modèle de données de la timeline. Indépendant du rendu.

Responsabilités :
  - Gérer les pistes et leurs événements
  - Garantir la cohérence (pas de collision intra-piste)
  - Sérialiser / désérialiser pour le projet JSON
  - Notifier l'EventBus sur chaque mutation

L'UI lit ce modèle pour le rendu.
L'ExecutionEngine lit ce modèle pour l'exécution.
Personne n'écrit dans le modèle sauf via ses méthodes publiques.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Optional, Tuple

from xrv22.timeline.timeline_event import (
    TimelineEvent, EventState, EventType
)
from xrv22.timeline.timeline_track import (
    TimelineTrack, TrackType,
    make_robot_track, make_arduino_track, make_sensor_track
)
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger
from xrv22.core.undo_manager import undo_manager, UndoCommand

_LOG = get_logger("TimelineModel")


class TimelineModel:
    """
    Modèle complet de la timeline multi-track.
    Thread-safe en écriture.
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self._tracks: Dict[str, TimelineTrack] = {}
        self._track_order: List[str] = []    # Ordre d'affichage
        self._lock = threading.Lock()
        self._cursor_ms: int = 0             # Position curseur lecture

        # Pistes système toujours présentes
        self._init_system_tracks()

    # ── Initialisation ───────────────────────────────────────────

    def _init_system_tracks(self) -> None:
        """Crée les pistes système (Arduino + Capteurs)."""
        arduino = make_arduino_track()
        sensor = make_sensor_track()
        self._tracks[arduino.track_id] = arduino
        self._tracks[sensor.track_id] = sensor
        self._track_order = [arduino.track_id, sensor.track_id]

    # ── Gestion des pistes ───────────────────────────────────────

    def add_robot_track(self, robot_id: str, label: str,
                        color: str) -> TimelineTrack:
        """Ajoute une piste robot en tête de liste."""
        track_id = f"track_{robot_id}"
        with self._lock:
            if track_id in self._tracks:
                return self._tracks[track_id]
            track = make_robot_track(robot_id, label, color)
            self._tracks[track_id] = track
            # Robot tracks en tête, system tracks en queue
            sys_ids = ["track_arduino", "track_sensors"]
            robot_ids = [t for t in self._track_order if t not in sys_ids]
            robot_ids.append(track_id)
            self._track_order = robot_ids + sys_ids

        bus.publish("timeline.track_added", {"track_id": track_id})
        return track

    def remove_robot_track(self, robot_id: str) -> bool:
        """Supprime une piste robot et ses événements."""
        track_id = f"track_{robot_id}"
        with self._lock:
            if track_id not in self._tracks:
                return False
            del self._tracks[track_id]
            self._track_order = [t for t in self._track_order if t != track_id]

        bus.publish("timeline.track_removed", {"track_id": track_id})
        return True

    def get_track(self, track_id: str) -> Optional[TimelineTrack]:
        with self._lock:
            return self._tracks.get(track_id)

    def ordered_tracks(self) -> List[TimelineTrack]:
        """Retourne les pistes dans l'ordre d'affichage."""
        with self._lock:
            return [self._tracks[tid] for tid in self._track_order
                    if tid in self._tracks]

    def move_track(self, track_id: str, new_index: int) -> bool:
        """Déplace une piste à un nouvel index dans l'ordre d'affichage."""
        with self._lock:
            if track_id not in self._track_order:
                return False
            old_index = self._track_order.index(track_id)
            if old_index == new_index:
                return False
            self._track_order.pop(old_index)
            self._track_order.insert(new_index, track_id)
        bus.publish("timeline.track_reordered", {"track_id": track_id})
        return True

    # ── Gestion des événements ───────────────────────────────────

    def add_event(self, event: TimelineEvent) -> Tuple[bool, str]:
        """Ajoute un événement à sa piste. Retourne (ok, msg)."""
        with self._lock:
            track = self._tracks.get(event.track_id)
            if track is None:
                return False, f"Piste {event.track_id} introuvable"
            ok = track.add_event(event)
            if not ok:
                return False, "Collision détectée sur cette piste"

        _LOG.info("Event ajouté : %s [%s] à %dms",
                  event.label, event.event_type, event.start_ms)
        bus.publish("timeline.event_added", {
            "event_id": event.event_id,
            "track_id": event.track_id,
        })
        # Undo/Redo
        undo_manager.push(UndoCommand(
            description=f"Ajout {event.label}",
            undo_fn=lambda eid=event.event_id: self.remove_event(eid),
            redo_fn=lambda ev=event: self.add_event(ev),
        ))
        return True, "OK"

    def remove_event(self, event_id: str, _push_undo: bool = True) -> bool:
        """Supprime un événement (cherche dans toutes les pistes)."""
        with self._lock:
            for track in self._tracks.values():
                evt = track.get_event(event_id)
                if evt is not None:
                    track.remove_event(event_id)
                    bus.publish("timeline.event_removed", {"event_id": event_id})
                    if _push_undo:
                        import copy
                        evt_copy = copy.deepcopy(evt)
                        undo_manager.push(UndoCommand(
                            description=f"Suppr. {evt.label}",
                            undo_fn=lambda ev=evt_copy: self.add_event(ev),
                            redo_fn=lambda eid=event_id: self.remove_event(eid),
                        ))
                    return True
        return False

    def update_event(self, event: TimelineEvent) -> Tuple[bool, str]:
        """Met à jour un événement existant."""
        with self._lock:
            track = self._tracks.get(event.track_id)
            if track is None:
                return False, "Piste introuvable"
            ok = track.update_event(event)
            if not ok:
                return False, "Collision ou événement introuvable"

        bus.publish("timeline.event_updated", {"event_id": event.event_id})
        return True, "OK"

    def move_event(self, event_id: str,
                   new_start_ms: int) -> Tuple[bool, str]:
        """
        Déplace un événement (drag-drop commit).
        Cherche la piste de l'événement, valide, commit.
        """
        with self._lock:
            track = self._find_track_for_event(event_id)
            if track is None:
                return False, f"Événement {event_id} introuvable"
            evt = track.get_event(event_id)
            old_start = evt.start_ms if evt else 0
            ok, msg = track.move_event(event_id, new_start_ms)

        if ok:
            bus.publish("timeline.event_moved", {
                "event_id": event_id, "new_start_ms": new_start_ms
            })
            undo_manager.push(UndoCommand(
                description=f"Déplacement à {new_start_ms}ms",
                undo_fn=lambda: self.move_event(event_id, old_start),
                redo_fn=lambda: self.move_event(event_id, new_start_ms),
            ))
        return ok, msg

    def get_event(self, event_id: str) -> Optional[TimelineEvent]:
        """Cherche un événement dans toutes les pistes."""
        with self._lock:
            for track in self._tracks.values():
                evt = track.get_event(event_id)
                if evt is not None:
                    return evt
        return None

    # ── Curseur et lecture ───────────────────────────────────────

    @property
    def cursor_ms(self) -> int:
        return self._cursor_ms

    def set_cursor(self, ms: int) -> None:
        """Positionne le curseur de lecture."""
        self._cursor_ms = max(0, ms)
        bus.publish("timeline.cursor_moved", {"cursor_ms": self._cursor_ms})

    def duration_ms(self) -> int:
        """Durée totale de la timeline (fin du dernier événement)."""
        with self._lock:
            durations = [t.duration_ms() for t in self._tracks.values()]
        return max(durations) if durations else 0

    def events_due_at(self, time_ms: int,
                      window_ms: int = 50) -> List[TimelineEvent]:
        """
        Événements à déclencher dans la fenêtre [time_ms, time_ms+window_ms).
        Retourne uniquement les PENDING.
        """
        due = []
        with self._lock:
            for track in self._tracks.values():
                if track.muted:
                    continue
                for evt in track.all_events():
                    if (evt.is_pending
                            and time_ms <= evt.start_ms < time_ms + window_ms):
                        due.append(evt)
        return sorted(due, key=lambda e: e.start_ms)

    def mark_event_state(self, event_id: str, state: str) -> None:
        """Met à jour l'état d'exécution d'un événement."""
        with self._lock:
            track = self._find_track_for_event(event_id)
            if track is None:
                return
            evt = track.get_event(event_id)
            if evt is None:
                return
            import dataclasses
            updated = dataclasses.replace(evt, state=state)
            track._events[event_id] = updated

    def reset_all_states(self) -> None:
        """Remet tous les événements en PENDING (avant lecture)."""
        with self._lock:
            for track in self._tracks.values():
                track.reset_states()

    # ── Sérialisation ────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Sérialise le modèle complet."""
        with self._lock:
            return {
                "name":        self.name,
                "track_order": list(self._track_order),
                "tracks":      [t.to_dict() for t in self._tracks.values()],
            }

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineModel":
        """Désérialise depuis dict JSON."""
        model = cls(name=d.get("name", "default"))
        model._tracks.clear()
        model._track_order.clear()

        for td in d.get("tracks", []):
            track = TimelineTrack.from_dict(td)
            model._tracks[track.track_id] = track

        order = d.get("track_order", [])
        model._track_order = [t for t in order if t in model._tracks]
        # Ajoute les pistes non dans l'ordre
        for tid in model._tracks:
            if tid not in model._track_order:
                model._track_order.append(tid)

        return model

    # ── Stats et debug ───────────────────────────────────────────

    def stats(self) -> dict:
        """Retourne des statistiques sur la timeline."""
        with self._lock:
            total_events = sum(t.event_count() for t in self._tracks.values())
            durations = [t.duration_ms() for t in self._tracks.values()]
            total_ms = max(durations) if durations else 0
            return {
                "name":         self.name,
                "track_count":  len(self._tracks),
                "event_count":  total_events,
                "duration_s":   total_ms / 1000.0,
                "cursor_s":     self._cursor_ms / 1000.0,
            }

    # ── Privé ────────────────────────────────────────────────────

    def _find_track_for_event(self, event_id: str) -> Optional[TimelineTrack]:
        """Trouve la piste d'un événement. Appeler sous _lock."""
        for track in self._tracks.values():
            if track.get_event(event_id) is not None:
                return track
        return None
