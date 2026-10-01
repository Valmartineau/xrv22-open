"""
xrv22/ui_pi/dessin_trace.py
───────────────────────────
Logique PURE d'accumulation des traits (strokes) du flux stylet, pour l'écran
Dessin du Pi. Aucune dépendance Tkinter/matériel → testable directement.

Un trait = liste de points (x, y, p) contigus EN CONTACT (p > 0). Le contact qui
cesse rompt le trait ; le contact suivant en démarre un nouveau.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

Point = Tuple[int, int, int]   # (x, y, pression)
Stroke = List[Point]


def ajoute_tick(strokes: List[Stroke], tick: Dict) -> List[Stroke]:
    """Renvoie la nouvelle liste de traits après intégration d'un tick.

    - En contact (p>0 et coords présentes) → prolonge le dernier trait (en
      démarre un si besoin).
    - Sinon → clôt le trait courant (rupture) : un nouveau trait vide est mis en
      attente, pour que le prochain contact reparte séparément.
    """
    p = int(tick.get("p") or 0)
    x, y = tick.get("x"), tick.get("y")
    en_contact = p > 0 and x is not None and y is not None
    if not en_contact:
        if strokes and len(strokes[-1]) > 0:
            return strokes + [[]]
        return strokes
    pt: Point = (int(x), int(y), p)
    if not strokes:
        return [[pt]]
    return strokes[:-1] + [strokes[-1] + [pt]]
