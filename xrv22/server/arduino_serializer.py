"""
xrv22/server/arduino_serializer.py
──────────────────────────────────
Sérialise un ArduinoDevice (état runtime + valeurs live) pour l'API web.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from xrv22.hardware.arduino_bridge import ArduinoDevice


def device_to_dict(dev: Optional[ArduinoDevice], *, name: str = "",
                   port: str = "", baud: int = 0) -> Dict[str, Any]:
    """Sérialise un ArduinoDevice. Si dev est None (pas encore enregistré
    dans le bridge), renvoie un stub aux MÊMES clés (listes vides)."""
    if dev is None:
        return {
            "name": name, "port": port, "baud": baud,
            "connected": False, "identified": False, "firmware": "", "error": "",
            "channels": [], "actuators": [], "actions": [],
        }
    return {
        "name": dev.name,
        "port": dev.port,
        "baud": dev.baud,
        "connected": dev.connected,
        "identified": dev.identified,
        "firmware": dev.firmware,
        "error": dev.error,
        "channels": [
            {"name": c.name, "unit": c.unit, "value": c.value,
             "min_val": c.min_val, "max_val": c.max_val, "updated": c.updated}
            for c in dev.channels.values()
        ],
        "actuators": [
            {"name": a.name, "kind": a.kind, "label": a.label,
             "min_val": a.min_val, "max_val": a.max_val,
             "last_value": a.last_value, "state_on": a.state_on}
            for a in dev.actuators.values()
        ],
        "actions": [
            {"name": a.name, "label": a.label, "description": a.description,
             "params": a.params, "duration_ms": a.duration_ms, "has_ack": a.has_ack}
            for a in dev.actions.values()
        ],
    }
