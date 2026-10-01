"""
xr200/services/event_bus.py
────────────────────────────
Bus d'événements thread-safe.
Canal unique de communication entre les couches.
Aucune couche ne s'appelle directement — tout passe ici.

Topics standards :
  robot.state_changed     {robot_id, state, prev_state}
  robot.comm_lost         {robot_id, last_seen_ms}
  robot.connected         {robot_id, port}
  robot.disconnected      {robot_id}
  safety.emergency_stop   {robot_id, source}
  safety.comm_lost        {robot_id}
  serial.ack              {robot_id, cmd_id}
  serial.nack             {robot_id, cmd_id, reason}
  serial.timeout          {robot_id, cmd_id}
  sensor.triggered        {sensor_id, value}
  timeline.event_started  {event_id, track_id}
  timeline.event_done     {event_id}
  ui.refresh              {}
"""
from __future__ import annotations

import threading
import logging
from typing import Callable, Dict, List

_LOG = logging.getLogger("XR200.EventBus")

Subscriber = Callable[[dict], None]


class EventBus:
    """Publish-subscribe thread-safe.
    Utilise RLock pour permettre unsubscribe pendant publish."""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Subscriber]] = {}
        self._lock = threading.RLock()

    # ── Public API ──────────────────────────────────────────────────

    def subscribe(self, topic: str, fn: Subscriber) -> None:
        """Abonne fn au topic."""
        with self._lock:
            self._subs.setdefault(topic, []).append(fn)

    def subscribe_ui(self, topic: str, fn: Subscriber, widget) -> None:
        """Abonne un callback UI marshale vers le mainloop Tk.

        Indispensable quand le topic peut etre publie depuis un thread de fond
        (scheduler, serial, sim, arduino) : appeler Tk hors du thread principal
        declenche un Tkapp_ThreadSend bloquant → deadlock si le main thread
        attend ensuite un lock detenu par le thread publieur.

        Le widget sert d'ancrage pour `widget.after(0, ...)`. Si le widget est
        detruit, la callback est silencieusement ignoree.
        """
        def _marshalled(data: dict) -> None:
            try:
                widget.after(0, lambda d=data: fn(d))
            except Exception:
                # Widget detruit ou mainloop arrete — on laisse tomber
                pass
        # Conserve la reference a fn pour que unsubscribe_object() fonctionne
        # via __self__ = objet qui porte la methode fn
        _marshalled.__self__ = getattr(fn, "__self__", None)
        _marshalled.__qualname__ = getattr(fn, "__qualname__", repr(fn))
        self.subscribe(topic, _marshalled)

    def unsubscribe(self, topic: str, fn: Subscriber) -> None:
        """Désabonne fn du topic."""
        with self._lock:
            subs = self._subs.get(topic, [])
            if fn in subs:
                subs.remove(fn)

    def publish(self, topic: str, payload: dict | None = None) -> None:
        """Publie un événement. Les erreurs subscriber sont loguées, jamais avalées."""
        data = payload or {}
        with self._lock:
            subs = list(self._subs.get(topic, []))
        for fn in subs:
            self._call_safe(topic, fn, data)

    def unsubscribe_object(self, obj: object) -> None:
        """Retire toutes les souscriptions dont le callback est lié à obj."""
        with self._lock:
            for topic in self._subs:
                self._subs[topic] = [
                    fn for fn in self._subs[topic]
                    if getattr(fn, "__self__", None) is not obj
                ]

    def clear(self) -> None:
        """Supprime toutes les souscriptions (utile pour les tests)."""
        with self._lock:
            self._subs.clear()

    # ── Privé ────────────────────────────────────────────────────────

    def _call_safe(self, topic: str, fn: Subscriber, data: dict) -> None:
        """Appel sécurisé d'un subscriber."""
        try:
            fn(data)
        except Exception as exc:
            name = getattr(fn, "__qualname__", repr(fn))
            _LOG.error("EventBus [%s] subscriber '%s' error: %s", topic, name, exc,
                       exc_info=True)


# Singleton global — importé par tous les modules
bus = EventBus()
