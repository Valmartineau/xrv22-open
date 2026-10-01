"""
xr200/timeline/timeline_event.py
──────────────────────────────────
Types d'événements timeline.

Chaque TimelineEvent est immutable en lecture (dataclass),
modifiable uniquement via les méthodes du TimelineModel.

Types :
  MOVE           — mouvement robot vers positions
  WAIT           — pause temporelle pure
  SENSOR_WAIT    — attente signal capteur (avec timeout)
  ARDUINO_ACTION — commande vers Arduino
  CALL_SEQUENCE  — exécute une suite définie
  SYNC_MARKER    — synchronise plusieurs robots
  PAUSE          — pause opérateur (interactive)

Sérialisation : to_dict() / from_dict() pour JSON projet.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Constantes ────────────────────────────────────────────────────

class EventType:
    MOVE           = "MOVE"
    WAIT           = "WAIT"
    SENSOR_WAIT    = "SENSOR_WAIT"
    ARDUINO_ACTION = "ARDUINO_ACTION"
    CALL_SEQUENCE  = "CALL_SEQUENCE"
    SYNC_MARKER    = "SYNC_MARKER"
    PAUSE          = "PAUSE"

    ALL = [MOVE, WAIT, SENSOR_WAIT, ARDUINO_ACTION,
           CALL_SEQUENCE, SYNC_MARKER, PAUSE]


class EventState:
    PENDING   = "PENDING"
    RUNNING   = "RUNNING"
    DONE      = "DONE"
    SKIPPED   = "SKIPPED"
    ERROR     = "ERROR"


# ── Dataclass principal ──────────────────────────────────────────

@dataclass
class TimelineEvent:
    """
    Un événement sur une piste de la timeline.
    start_ms et duration_ms sont en millisecondes.
    """
    event_id:    str
    track_id:    str
    event_type:  str
    start_ms:    int                         # Position temporelle
    duration_ms: int                         # Durée
    label:       str           = ""
    parameters:  Dict[str, Any] = field(default_factory=dict)
    state:       str           = EventState.PENDING
    color:       str           = ""          # Override couleur (optionnel)

    # ── Factory ──────────────────────────────────────────────────

    @classmethod
    def make(cls, track_id: str, event_type: str,
             start_ms: int, duration_ms: int,
             label: str = "", **params: Any) -> "TimelineEvent":
        """Crée un événement avec un ID unique."""
        return cls(
            event_id=uuid.uuid4().hex[:12],
            track_id=track_id,
            event_type=event_type,
            start_ms=max(0, start_ms),
            duration_ms=max(1, duration_ms),
            label=label or event_type,
            parameters=params,
        )

    # ── Propriétés calculées ─────────────────────────────────────

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000.0

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def is_pending(self) -> bool:
        return self.state == EventState.PENDING

    @property
    def is_done(self) -> bool:
        return self.state in (EventState.DONE, EventState.SKIPPED, EventState.ERROR)

    # ── Sérialisation ─────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "event_id":    self.event_id,
            "track_id":    self.track_id,
            "event_type":  self.event_type,
            "start_ms":    self.start_ms,
            "duration_ms": self.duration_ms,
            "label":       self.label,
            "parameters":  self.parameters,
            "color":       self.color,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TimelineEvent":
        """Désérialise depuis un dict JSON."""
        return cls(
            event_id=d.get("event_id", uuid.uuid4().hex[:12]),
            track_id=d["track_id"],
            event_type=d["event_type"],
            start_ms=max(0, int(d["start_ms"])),
            duration_ms=max(1, int(d["duration_ms"])),
            label=d.get("label", ""),
            parameters=d.get("parameters", {}),
            state=EventState.PENDING,
            color=d.get("color", ""),
        )

    # ── Helpers accès paramètres ─────────────────────────────────

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.parameters.get(key, default)

    def with_start(self, new_start_ms: int) -> "TimelineEvent":
        """Retourne une copie avec une nouvelle position temporelle."""
        import dataclasses
        return dataclasses.replace(self, start_ms=new_start_ms, state=EventState.PENDING)

    def with_duration(self, new_duration_ms: int) -> "TimelineEvent":
        """Retourne une copie avec une nouvelle durée."""
        import dataclasses
        return dataclasses.replace(self, duration_ms=max(1, new_duration_ms))


# ── Factories par type ────────────────────────────────────────────

def make_move_event(track_id: str, start_ms: int,
                    positions: Dict[int, int], duration_s: float,
                    label: str = "",
                    speed_pct: int = 100) -> TimelineEvent:
    """Crée un événement MOVE. speed_pct : 100=normal, 200=2× plus rapide."""
    return TimelineEvent.make(
        track_id=track_id,
        event_type=EventType.MOVE,
        start_ms=start_ms,
        duration_ms=int(duration_s * 1000),
        label=label or "Move",
        positions=positions,
        duration_s=duration_s,
        speed_pct=speed_pct,
    )


def make_wait_event(track_id: str, start_ms: int,
                    duration_ms: int) -> TimelineEvent:
    """Crée un événement WAIT."""
    return TimelineEvent.make(
        track_id=track_id,
        event_type=EventType.WAIT,
        start_ms=start_ms,
        duration_ms=duration_ms,
        label="Wait",
    )


def make_sensor_wait_event(track_id: str, start_ms: int,
                           sensor_id: str, timeout_ms: int = 10000,
                           on_timeout: str = "error") -> TimelineEvent:
    """Crée un événement SENSOR_WAIT."""
    return TimelineEvent.make(
        track_id=track_id,
        event_type=EventType.SENSOR_WAIT,
        start_ms=start_ms,
        duration_ms=timeout_ms,
        label=f"Wait {sensor_id}",
        sensor_id=sensor_id,
        timeout_ms=timeout_ms,
        on_timeout=on_timeout,
    )


def make_arduino_event(track_id: str, start_ms: int,
                       device_name: str, action_name: str,
                       params: Optional[Dict] = None,
                       duration_ms: int = 500) -> TimelineEvent:
    """Crée un événement ARDUINO_ACTION."""
    return TimelineEvent.make(
        track_id=track_id,
        event_type=EventType.ARDUINO_ACTION,
        start_ms=start_ms,
        duration_ms=duration_ms,
        label=f"⚡ {action_name}",
        device_name=device_name,
        action_name=action_name,
        params=params or {},
    )


def make_sync_marker(track_id: str, start_ms: int,
                     group_id: str) -> TimelineEvent:
    """Crée un marqueur de synchronisation."""
    return TimelineEvent.make(
        track_id=track_id,
        event_type=EventType.SYNC_MARKER,
        start_ms=start_ms,
        duration_ms=100,
        label=f"Sync:{group_id}",
        group_id=group_id,
    )
