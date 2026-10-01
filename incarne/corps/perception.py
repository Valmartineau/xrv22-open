"""Perception tablette : lecture StyletLecteur → signaux bruts anonymes.

La boucle injecte ces nombres tels quels dans l'observation (corps_rxv22.
lire_signaux). On n'expose QUE des entiers, sans étiquette : position x, y et
pression. La boîte blanche découvre seule qu'un de ces nombres réagit quand elle
bouge une manette (le « signe de vie » incarné). Aucune explication. Voir
docs/recherche/journal-collaboration.md.
"""
from __future__ import annotations

from typing import Dict, List


def signaux_stylet(lecture: Dict) -> List[int]:
    """[x, y, p] en entiers ; les valeurs absentes (None, hors-portée) → 0."""
    return [int(lecture.get("x") or 0),
            int(lecture.get("y") or 0),
            int(lecture.get("p") or 0)]
