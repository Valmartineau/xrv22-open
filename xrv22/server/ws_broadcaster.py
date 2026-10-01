"""
xrv22/server/ws_broadcaster.py
──────────────────────────────
ETAPE 2 — Pont entre le bus d'evenements (sync, multi-thread) et les clients
WebSocket connectes via FastAPI (asyncio, mono-thread sur l'event loop).

Principe :
    bus.publish(topic, data)   [thread quelconque]
        -> handler sync enfile sur asyncio.Queue via call_soon_threadsafe
            -> coroutine drainer broadcast aux WebSockets enregistres

En plus du forwarding du bus, un tick periodique (200ms par defaut) lit le
StateStore et publie un message "robot.positions_tick" avec les positions
hardware live de chaque robot connecte. Cela permet aux clients web de suivre
les sliders/visu en temps reel sans devoir poller /api/robots/{rid}.

Format des messages WebSocket (JSON) :
    {"topic": "<topic>", "data": {...}, "ts": <epoch_seconds>}
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Set

from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("WS")

try:
    from fastapi import WebSocket
    from starlette.websockets import WebSocketState
    WS_OK = True
except ImportError:
    WS_OK = False


# Topics du bus a broadcaster aux clients web. Garder cette liste explicite
# (pas de wildcard) pour ne pas exposer accidentellement de canaux internes.
_BUS_TOPICS = (
    "robot.connected",
    "robot.disconnected",
    "robot.state_changed",
    "robot.comm_lost",
    "robot.master_changed",
    "robot.torque_changed",
    "robot.control_changed",
    "safety.emergency_stop",
    "safety.comm_lost",
    "sensor.triggered",
    "timeline.event_started",
    "timeline.event_done",
    "timeline.play",
    "timeline.pause",
    "timeline.stop",
    "engine.tick",        # Position de lecture timeline (elapsed_ms)
    "engine.error",
    "engine.zone_collision",
    "ui.refresh",
    "eddy.step",
    "eddy.say",
    "stylet.tick",
    "system.active_robot_changed",
    "arduino.connected",
    "arduino.disconnected",
    "arduino.identified",
    "arduino.error",
    "sensor.alert",
)

# Periode du tick positions live (secondes). 100ms = 10Hz : rafraichissement
# 3D/position plus fluide. Le payload est petit (positions de chaque robot) et
# lu depuis le cache StateStore (pas de lecture serie ici), donc sans risque de
# saturer le LAN ni l'event loop.
_POSITIONS_TICK_S = 0.1
# Période du tick capteurs Arduino (secondes). 5 Hz suffit pour la supervision.
_SENSORS_TICK_S = 0.2


class WSBroadcaster:
    """

    Cycle de vie :
        - attach_loop(loop) : appele depuis le startup hook FastAPI ; cree
          la queue, abonne les handlers du bus, lance les tasks.
        - register(ws) / unregister(ws) : appele par l'endpoint /ws.
        - shutdown() : optionnel, pour les tests.
    """

    def __init__(self) -> None:
        self._clients: Set["WebSocket"] = set()
        self._clients_lock = asyncio.Lock()
        self._queue: asyncio.Queue | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._bus_handlers: list[tuple[str, Any]] = []
        self._started = False

    # ── Cycle de vie ────────────────────────────────────────────────

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Attache l'event loop, cree la queue, branche le bus.
        Idempotent."""
        if self._started:
            return
        self._loop = loop
        self._queue = asyncio.Queue(maxsize=2000)
        for topic in _BUS_TOPICS:
            handler = self._make_bus_handler(topic)
            bus.subscribe(topic, handler)
            self._bus_handlers.append((topic, handler))
        self._tasks.append(loop.create_task(self._drain_loop()))
        self._tasks.append(loop.create_task(self._positions_tick_loop()))
        self._tasks.append(loop.create_task(self._sensors_tick_loop()))
        self._started = True
        _LOG.info("WS broadcaster pret (%d topics + tick positions %.0fms + tick capteurs %.0fms)",
                  len(_BUS_TOPICS), _POSITIONS_TICK_S * 1000, _SENSORS_TICK_S * 1000)

    def shutdown(self) -> None:
        """Desabonne du bus et annule les tasks. Utilitaire tests."""
        for topic, handler in self._bus_handlers:
            try:
                bus.unsubscribe(topic, handler)
            except Exception:
                pass
        self._bus_handlers.clear()
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self._started = False

    # ── Enregistrement clients ──────────────────────────────────────

    async def register(self, ws: "WebSocket") -> None:
        """Ajoute ws a la liste des clients."""
        async with self._clients_lock:
            self._clients.add(ws)
        _LOG.info("WS client connecte (%d total)", len(self._clients))

    async def unregister(self, ws: "WebSocket") -> None:
        """Retire ws de la liste. Si le web possedait le controle d'un
        robot, libere l'arbitrage pour eviter un deadlock (ex. rechargement
        de la page)."""
        async with self._clients_lock:
            self._clients.discard(ws)
        _LOG.info("WS client deconnecte (%d restants)", len(self._clients))
        # Liberation de l'arbitrage web -> libere le controle si personne ne
        # le tenait cote Pi, pour que la Pi puisse reprendre sans blocage.
        try:
            from xrv22.robots.robot_registry import registry
            from xrv22.core.jog_engine import jog_engine
            for rid in registry.ids():
                ctrl = registry.get(rid)
                if ctrl is not None and ctrl.control_owner == "web":
                    jog_engine.release(rid)
        except Exception as exc:
            _LOG.warning("unregister: erreur liberation arbitrage : %s", exc)

    # ── Pont bus -> queue ───────────────────────────────────────────

    def _make_bus_handler(self, topic: str):
        """Cree un callback synchrone qui enfile sur la queue async.
        Capture topic dans la closure."""
        def handler(data: dict) -> None:
            self._enqueue({"topic": topic, "data": data, "ts": time.time()})
        return handler

    def _enqueue(self, msg: Dict[str, Any]) -> None:
        """Pousse un message sur la queue depuis un thread arbitraire.
        Drop silencieux si queue saturee (mieux que bloquer le bus)."""
        if self._loop is None or self._queue is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._put_nowait_safe, msg)
        except RuntimeError:
            # Loop ferme (shutdown en cours)
            pass

    def _put_nowait_safe(self, msg: Dict[str, Any]) -> None:
        """Helper execute sur l'event loop : put non bloquant."""
        try:
            assert self._queue is not None
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            _LOG.warning("WS queue saturee, message %s drope", msg.get("topic"))

    # ── Tasks asyncio ───────────────────────────────────────────────

    async def _drain_loop(self) -> None:
        """Boucle infinie : drain la queue et broadcast."""
        assert self._queue is not None
        while True:
            try:
                msg = await self._queue.get()
            except asyncio.CancelledError:
                return
            await self._broadcast(msg)

    @staticmethod
    def _collect_robot_positions(store, registry) -> Dict[str, Any]:
        """Snapshot des positions live des robots connectés depuis le StateStore.
        PAS de read série ici : cela entrerait en contention avec le pilotage
        (jog 20 Hz). Le store est tenu à jour par write_positions_direct."""
        payload: Dict[str, Any] = {}
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl is None or not ctrl.is_connected:
                continue
            snap = store.get_robot(rid)
            if snap and snap.positions:
                payload[rid] = {str(k): v for k, v in snap.positions.items()}
        return payload

    async def _positions_tick_loop(self) -> None:
        """Tick périodique : publie les positions hardware live."""
        # Lazy import : évite import circulaire au module load
        try:
            from xrv22.core.state_store import store
            from xrv22.robots.robot_registry import registry
        except ImportError:
            return
        while True:
            try:
                await asyncio.sleep(_POSITIONS_TICK_S)
            except asyncio.CancelledError:
                return
            if not self._clients:
                continue  # personne n'écoute, on épargne le store
            payload = self._collect_robot_positions(store, registry)
            if payload:
                await self._broadcast({
                    "topic": "robot.positions_tick",
                    "data": payload,
                    "ts": time.time(),
                })

    async def _sensors_tick_loop(self) -> None:
        """Tick périodique : publie les dernières valeurs capteurs Arduino."""
        try:
            from xrv22.hardware.arduino_bridge import arduino
        except ImportError:
            return
        while True:
            try:
                await asyncio.sleep(_SENSORS_TICK_S)
            except asyncio.CancelledError:
                return
            if not self._clients:
                continue
            payload: Dict[str, Any] = {}
            for dev in list(arduino.devices.values()):
                if not dev.connected or not dev.channels:
                    continue
                payload[dev.name] = {
                    c.name: c.value for c in list(dev.channels.values())
                }
            if payload:
                await self._broadcast({
                    "topic": "arduino.sensors_tick",
                    "data": payload,
                    "ts": time.time(),
                })

    # ── Broadcast ───────────────────────────────────────────────────

    async def _broadcast(self, msg: Dict[str, Any]) -> None:
        """Envoie msg a tous les clients. Retire les clients morts."""
        async with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return
        dead: list["WebSocket"] = []
        for ws in clients:
            if ws.client_state != WebSocketState.CONNECTED:
                dead.append(ws)
                continue
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._clients_lock:
                for ws in dead:
                    self._clients.discard(ws)


# Singleton global — utilise par api.py
broadcaster = WSBroadcaster()
