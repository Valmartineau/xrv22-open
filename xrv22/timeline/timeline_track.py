"""
xr200/timeline/timeline_track.py
──────────────────────────────────
Gestion des pistes de la timeline.

Types de pistes :
  ROBOT    — une piste par robot (couleur = couleur du robot)
  ARDUINO  — piste actions Arduino
  SENSOR   — piste conditions/capteurs
  GLOBAL   — cues globaux (pause, sync)

Chaque piste est la source de vérité de ses événements.
Le TimelineModel orchestre l'ensemble des pistes.

Contrainte de collision :
  Sur une même piste, deux blocs ne peuvent pas se chevaucher.
  Entre pistes différentes, les chevauchements sont autorisés.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from xrv22.timeline.timeline_event import TimelineEvent, EventState


# ── Types de pistes ──────────────────────────────────────────────

class TrackType:
    ROBOT   = "ROBOT"
    ARDUINO = "ARDUINO"
    SENSOR  = "SENSOR"
    GLOBAL  = "GLOBAL"


# ── Track ────────────────────────────────────────────────────────

@dataclass
class TimelineTrack:
    """
    Une piste de la timeline.
    """
    track_id:   str
    track_type: str
    label:      str
    color:      str
    robot_id:   str = ""        # Rempli uniquement pour ROBOT
    visible:    bool = True
    muted:      bool = False
    _events:    Dict[str, TimelineEvent] = field(default_factory=dict, repr=False)

    # ── CRUD événements ──────────────────────────────────────────

    def add_event(self, event: TimelineEvent) -> bool:
        """Ajoute un événement si pas de collision. Retourne succès."""
        if event.track_id != self.track_id:
            return False
        if self._has_collision(event.start_ms, event.duration_ms, exclude_id=None):
            return False
        self._events[event.event_id] = event
        return True

    def remove_event(self, event_id: str) -> bool:
        """Supprime un événement. Retourne succès."""
        if event_id not in self._events:
            return False
        del self._events[event_id]
        return True

    def update_event(self, event: TimelineEvent) -> bool:
        """Remplace un événement existant après validation collision."""
        if event.event_id not in self._events:
            return False
        if self._has_collision(event.start_ms, event.duration_ms,
                               exclude_id=event.event_id):
            return False
        self._events[event.event_id] = event
        return True

    def move_event(self, event_id: str,
                   new_start_ms: int) -> Tuple[bool, str]:
        """
        Déplace un événement vers une nouvelle position.
        Retourne (ok, message). Utilisé par le drag-drop.
        """
        evt = self._events.get(event_id)
        if evt is None:
            return False, f"Événement {event_id} introuvable"

        if new_start_ms < 0:
            new_start_ms = 0

        if self._has_collision(new_start_ms, evt.duration_ms, exclude_id=event_id):
            return False, "Collision avec un autre bloc sur cette piste"

        moved = evt.with_start(new_start_ms)
        self._events[event_id] = moved
        return True, "OK"

    # ── Lecture ──────────────────────────────────────────────────

    def get_event(self, event_id: str) -> Optional[TimelineEvent]:
        return self._events.get(event_id)

    def all_events(self) -> List[TimelineEvent]:
        """Retourne les événements triés par start_ms."""
        return sorted(self._events.values(), key=lambda e: e.start_ms)

    def events_at(self, time_ms: int) -> List[TimelineEvent]:
        """Événements actifs à un instant T."""
        return [e for e in self._events.values()
                if e.start_ms <= time_ms < e.end_ms]

    def events_pending(self) -> List[TimelineEvent]:
        """Événements non encore exécutés."""
        return [e for e in self.all_events() if e.is_pending]

    def duration_ms(self) -> int:
        """Durée totale de la piste (fin du dernier événement)."""
        if not self._events:
            return 0
        return max(e.end_ms for e in self._events.values())

    def event_count(self) -> int:
        return len(self._events)

    # ── Reset état ───────────────────────────────────────────────

    def reset_states(self) -> None:
        """Remet tous les événements en PENDING (avant lecture)."""
        for eid, evt in self._events.items():
            self._events[eid] = evt.with_start(evt.start_ms)

    # ── Sérialisation ────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "track_id":   self.track_id,
            "track_type": self.track_type,
            "label":      self.label,
            "color":      self.color,
            "robot_id":   self.robot_id,
            "visible":    self.visible,
            "muted":      self.muted,
            "events":     [e.to_dict() for e in self.all_events()],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineTrack":
        """Désérialise depuis dict JSON."""
        from xrv22.timeline.timeline_event import TimelineEvent
        track = cls(
            track_id=d["track_id"],
            track_type=d["track_type"],
            label=d["label"],
            color=d.get("color", "#f6a117"),
            robot_id=d.get("robot_id", ""),
            visible=d.get("visible", True),
            muted=d.get("muted", False),
        )
        for ed in d.get("events", []):
            evt = TimelineEvent.from_dict(ed)
            track._events[evt.event_id] = evt
        return track

    # ── Privé ────────────────────────────────────────────────────

    def _has_collision(self, start_ms: int, duration_ms: int,
                       exclude_id: Optional[str]) -> bool:
        """Vérifie si une plage temporelle entre en collision."""
        end_ms = start_ms + duration_ms
        for evt in self._events.values():
            if evt.event_id == exclude_id:
                continue
            if start_ms < evt.end_ms and end_ms > evt.start_ms:
                return True
        return False


# ── Factory ──────────────────────────────────────────────────────

def make_robot_track(robot_id: str, label: str, color: str) -> TimelineTrack:
    """Crée une piste robot."""
    return TimelineTrack(
        track_id=f"track_{robot_id}",
        track_type=TrackType.ROBOT,
        label=label,
        color=color,
        robot_id=robot_id,
    )


def make_arduino_track() -> TimelineTrack:
    """Crée la piste Arduino."""
    return TimelineTrack(
        track_id="track_arduino",
        track_type=TrackType.ARDUINO,
        label="Arduino",
        color="#38bdf8",
    )


def make_sensor_track() -> TimelineTrack:
    """Crée la piste Capteurs."""
    return TimelineTrack(
        track_id="track_sensors",
        track_type=TrackType.SENSOR,
        label="Capteurs",
        color="#4ade80",
    )
