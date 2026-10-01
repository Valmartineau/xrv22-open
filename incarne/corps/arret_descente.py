# incarne/corps/arret_descente.py
"""Logique d'arrêt PURE de la descente de mesure (pas de matériel ici).

Après chaque micro-pas, `evaluer(pression, en_portee, descente_cumulee)` rend
(continuer, raison). Ordre des contrôles : sécurité d'abord (perte de signal,
cap, descente max), puis détection de plateau/glissement (le but de la mesure).
Voir docs/recherche/2026-06-16-protocole-mesure-securite.md §6.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional, Tuple


class EvaluateurArret:
    def __init__(self, cap_pression: int = 700, plateau_delta: int = 15,
                 plateau_fenetre: int = 3, descente_max: int = 120,
                 seuil_contact: int = 30, max_pas_sans_contact: int = 15) -> None:
        self.cap = cap_pression
        self.plateau_delta = plateau_delta
        self.fenetre = plateau_fenetre
        self.descente_max = descente_max
        self.seuil_contact = seuil_contact
        self.max_pas_sans_contact = max_pas_sans_contact
        self._pressions: Deque[int] = deque(maxlen=plateau_fenetre + 1)
        self._pas_sans_contact = 0

    def evaluer(self, pression: int, en_portee: bool,
                descente_cumulee: int) -> Tuple[bool, Optional[str]]:
        if not en_portee:
            return False, "signal perdu (stylet hors-portée)"
        pression = int(pression or 0)
        if pression >= self.cap:
            return False, f"cap de pression atteint ({pression} ≥ {self.cap})"
        if descente_cumulee >= self.descente_max:
            return False, (f"descente max atteinte "
                           f"({descente_cumulee} ≥ {self.descente_max} ticks)")
        # contact jamais établi : on est en portée mais la pression reste sous
        # le seuil de contact pas après pas → montage probablement absent
        if pression < self.seuil_contact:
            self._pas_sans_contact += 1
        else:
            self._pas_sans_contact = 0
        if self._pas_sans_contact >= self.max_pas_sans_contact:
            return False, (f"contact jamais établi (pression < seuil sur "
                           f"{self.max_pas_sans_contact} pas) — vérifier le montage")
        self._pressions.append(pression)
        if (pression >= self.seuil_contact
                and len(self._pressions) >= self.fenetre + 1):
            hausse = self._pressions[-1] - self._pressions[-(self.fenetre + 1)]
            if hausse < self.plateau_delta:
                return False, (f"plateau/glissement détecté "
                               f"(hausse {hausse} < {self.plateau_delta} "
                               f"sur {self.fenetre} pas)")
        return True, None
