"""
xrv22/server/jog_ws.py
──────────────────────
Routage des messages WebSocket entrants du jog vers le JogEngine.
Isolé de la route FastAPI pour être testable sans vrai WebSocket.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

_LOG = logging.getLogger(__name__)


def route_jog_message(engine, msg: Dict[str, Any]) -> None:
    """Route un message client. Tolérant : tout message mal formé est ignoré."""
    if not isinstance(msg, dict):
        return
    mtype = msg.get("type")
    rid = msg.get("rid")
    try:
        if mtype == "jog.intent":
            axis = msg.get("axis")
            target = msg.get("target")
            if rid is None or axis is None or target is None:
                return
            if rid not in engine.active_rids():
                # Garde : n'acquiert (ne RECREE l'integrateur) que si aucune
                # session n'est active. NB : si le Pi possede deja ce rid, on
                # n'acquiert pas, mais set_target ci-dessous ecrit quand meme sur
                # SON integrateur (interference inter-canal a granularite axe).
                # L'arbitrage propre Pi<->web (takeover) est traite en J4 ; pas de
                # client web envoyant ces messages en J3.
                engine.acquire(rid, "web")
            engine.set_target(rid, {int(axis): int(target)})
        elif mtype == "jog.alive":
            if rid is None:
                return
            engine.heartbeat(rid)
    except Exception:
        _LOG.exception("[jog-ws] message ignore : %s", msg)
