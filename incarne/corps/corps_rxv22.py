"""Corps RXV22 réel : implémente l'interface corps (observe/agir) attendue par
la boucle, par-dessus le client HTTP et la couche corps nu.

- observe() : lit l'état serveur → manettes (axes mappés, axe 7 exclu) + signaux
  (injectés depuis la tablette, vides par défaut) ;
- agir()    : lit le présent, calcule la cible bornée (corps nu) et l'écrit —
  passe par l'anticollision serveur ; l'axe 7 n'est jamais commandé ;
- armer()   : torque ON puis goal = position courante (anti-sursaut au réveil,
  cf [[project_xrv22_reveil_coude]]) — à appeler une fois au démarrage.
"""
from __future__ import annotations

import time as _time
from typing import Callable, Dict, List, Optional

from incarne.corps.corps_nu import CorpsNu


class CorpsRxv22:
    def __init__(self, client, rid: str, corps_nu: CorpsNu,
                 lire_signaux: Optional[Callable[[], List[int]]] = None,
                 lire_pression: Optional[Callable[[], int]] = None,
                 plafond_pression: int = 650, dwell: float = 0.15,
                 dormir: Optional[Callable[[float], None]] = None,
                 observation: bool = False) -> None:
        self.client = client
        self.rid = rid
        self.corps = corps_nu
        self.lire_signaux = lire_signaux or (lambda: [])
        # Mode passif : torque OFF, l'humain bouge le bras → agir() n'écrit rien,
        # Eddy ne fait qu'observer son corps déplacé de l'extérieur.
        self.observation = observation
        # Garde-fou tolérant : après chaque geste, si la pression lue ≥ plafond,
        # on annule (réécriture de la position précédente). Axe-agnostique : Eddy
        # découvre ses axes, nous on ne surveille que la pression (NOTRE échafaudage).
        self.lire_pression = lire_pression
        self.plafond_pression = plafond_pression
        self.dwell = dwell
        self._dormir = dormir or _time.sleep

    def _positions(self) -> Dict[int, int]:
        etat = self.client.get_robot(self.rid)
        return {int(k): int(v) for k, v in (etat.get("positions") or {}).items()}

    def observe(self) -> dict:
        pos = self._positions()
        manettes = [pos[self.corps.manette_axis(i)]
                    for i in range(self.corps.nb_manettes)]
        return {"manettes": manettes, "signaux": list(self.lire_signaux())}

    def agir(self, manette: int, delta: int) -> dict:
        if self.observation:
            return {"ok": True, "passif": True}  # mode passif : on n'actionne pas
        # Robustesse : manette inexistante (sortie aberrante à température élevée)
        # → no-op, surtout pas d'IndexError qui ferait crasher le run.
        if not isinstance(manette, int) or not (0 <= manette < self.corps.nb_manettes):
            return {"ok": False, "raison": "manette inexistante", "manette": manette}
        positions = self._positions()
        axis = self.corps.manette_axis(manette)
        avant = positions[axis]
        cible = self.corps.cible(manette, delta, positions)
        res = self.client.write_positions(self.rid, cible)
        if self.lire_pression is None:
            return res
        self._dormir(self.dwell)                       # laisse la pression s'établir
        p = int(self.lire_pression() or 0)
        if p >= self.plafond_pression:
            self.client.write_positions(self.rid, {axis: avant})  # annulation
            return {"ok": False, "bloque": "plafond_pression",
                    "pression": p, "plafond": self.plafond_pression}
        return res

    def armer(self) -> dict:
        """Réconcilie le goal au torque-on : torque ON puis écrit les positions
        courantes (toutes, axe 7 compris) comme cible → aucun sursaut au réveil."""
        pos = self._positions()
        self.client.set_torque(self.rid, True)
        return self.client.write_positions(self.rid, pos)
