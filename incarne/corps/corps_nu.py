"""Couche « corps nu » — manettes anonymes par-dessus l'API RXV22.

On expose au cerveau vierge des manettes SANS label (« manette 0, 1, … »), pas
des axes nommés. L'axe 7 (pince, tient le stylet) est EXCLU : jamais exposé,
jamais bougé. Voir spec §5.
"""
from __future__ import annotations

from typing import Iterable, Set

# Axe de la pince : tient le stylet → toujours figé (jamais une manette).
AXE_PINCE = 7


class CorpsNu:
    """Mappe des manettes anonymes [0..n-1] sur les axes pilotables (hors
    exclusions). `delta_cap` borne l'amplitude d'un pas (ticks)."""

    def __init__(self, axes: Iterable[int], delta_cap: int,
                 exclus: Set[int] | None = None) -> None:
        self._exclus = {AXE_PINCE} | (exclus or set())
        self._axes = [a for a in axes if a not in self._exclus]
        self.delta_cap = delta_cap

    @property
    def nb_manettes(self) -> int:
        return len(self._axes)

    def manette_axis(self, manette: int) -> int:
        """Axe réel derrière une manette anonyme."""
        return self._axes[manette]

    def borne_delta(self, delta: int) -> int:
        """Borne δ à ±delta_cap (cap de sécurité, jamais confié au cerveau)."""
        return max(-self.delta_cap, min(self.delta_cap, delta))

    def cible(self, manette: int, delta: int,
              positions: dict[int, int]) -> dict[int, int]:
        """Cible d'écriture absolue pour un pas « manette i ±δ » : position
        courante de l'axe + δ borné. Ne contient QUE l'axe visé (jamais un axe
        exclu). `manette` hors plage ⇒ IndexError."""
        axis = self.manette_axis(manette)
        return {axis: positions[axis] + self.borne_delta(delta)}
