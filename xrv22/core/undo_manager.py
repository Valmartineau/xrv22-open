"""
xrv22/core/undo_manager.py
===========================
Gestionnaire Undo/Redo global pour XRV22.

Principe : chaque action modifiante est encapsulée dans un UndoCommand
(un callable undo + un callable redo). Le manager empile les commandes
et permet de naviguer dans l'historique.

Capacité par défaut : 50 commandes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("XRV22.UndoManager")

MAX_HISTORY = 50


@dataclass
class UndoCommand:
    """Une action réversible."""
    description: str
    undo_fn: Callable[[], None]
    redo_fn: Callable[[], None]


class UndoManager:
    """Pile Undo/Redo avec notification bus."""

    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self._undo_stack: List[UndoCommand] = []
        self._redo_stack: List[UndoCommand] = []
        self._max = max_history

    # ── API publique ──────────────────────────────────────────────

    def push(self, cmd: UndoCommand) -> None:
        """Enregistre une commande exécutée."""
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > self._max:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        _LOG.debug("Undo push : %s (pile=%d)", cmd.description,
                   len(self._undo_stack))
        self._notify()

    def undo(self) -> Optional[str]:
        """Annule la dernière action. Retourne la description ou None."""
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        try:
            cmd.undo_fn()
        except Exception as exc:
            _LOG.error("Undo échoué [%s] : %s", cmd.description, exc)
            return None
        self._redo_stack.append(cmd)
        _LOG.info("Undo : %s", cmd.description)
        self._notify()
        return cmd.description

    def redo(self) -> Optional[str]:
        """Refait la dernière action annulée. Retourne la description ou None."""
        if not self._redo_stack:
            return None
        cmd = self._redo_stack.pop()
        try:
            cmd.redo_fn()
        except Exception as exc:
            _LOG.error("Redo échoué [%s] : %s", cmd.description, exc)
            return None
        self._undo_stack.append(cmd)
        _LOG.info("Redo : %s", cmd.description)
        self._notify()
        return cmd.description

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo_description(self) -> str:
        """Description de la prochaine action undo."""
        if self._undo_stack:
            return self._undo_stack[-1].description
        return ""

    def redo_description(self) -> str:
        """Description de la prochaine action redo."""
        if self._redo_stack:
            return self._redo_stack[-1].description
        return ""

    def clear(self) -> None:
        """Vide l'historique."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify()

    # ── Interne ───────────────────────────────────────────────────

    def _notify(self) -> None:
        bus.publish("undo.changed", {
            "can_undo": self.can_undo(),
            "can_redo": self.can_redo(),
            "undo_desc": self.undo_description(),
            "redo_desc": self.redo_description(),
        })


# Singleton global
undo_manager = UndoManager()
