"""
xrv22/server/port_discovery.py
──────────────────────────────
Découverte des ports série proposables pour un Arduino.
Exclut les adaptateurs U2D2 (FTDI 0x0403 = robots) et flag les cartes
Arduino (VID 0x2341).
"""
from __future__ import annotations

from typing import Any, Iterable, List, Set

FTDI_VID = 0x0403   # U2D2 / robots Dynamixel
ARDUINO_VIDS = {0x2341, 0x2A03, 0x1A86, 0x10C4}  # Arduino SA, clones CH340/CP210x


def classify_ports(comports: Iterable[Any],
                   robot_ports: Set[str] | None = None) -> List[dict]:
    """Transforme une liste de ListPortInfo en liste proposable.

    - Exclut les ports FTDI (robots) et ceux déjà tenus par un robot connecté.
    - Flag is_arduino selon le VID.
    """
    robot_ports = robot_ports or set()
    out: List[dict] = []
    for p in comports:
        if p.device in robot_ports:
            continue
        if getattr(p, "vid", None) == FTDI_VID:
            continue
        out.append({
            "device": p.device,
            "description": getattr(p, "description", "") or "",
            "vid": getattr(p, "vid", None),
            "is_arduino": getattr(p, "vid", None) in ARDUINO_VIDS,
        })
    return out


def list_available_ports(robot_ports: Set[str] | None = None) -> List[dict]:
    """Scanne les ports réels du système (vide si pyserial absent)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return classify_ports(list_ports.comports(), robot_ports)
