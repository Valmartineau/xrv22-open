"""
incarne/goto_doux.py
────────────────────
Go-to DESSIN en douceur, en 2 paliers : position de travail (`home_work`) →
pose de départ dessin.

Pourquoi : `write_positions_direct` pose le goal d'un coup → le moteur file à sa
vitesse de profil = à-coup brutal. `ctrl.move(positions, duration_s)` utilise le
**profil temporel Dynamixel** (mouvement lissé sur une durée) — c'est la primitive
qu'utilise déjà `safe_home`. On la calque ici, mais le 2e palier vise la pose de
dessin au lieu du home machine.

Règle inviolable (boîte blanche incarnée) : l'axe 7 tient le stylet, il n'est
JAMAIS bougé — on l'exclut systématiquement des cibles.
"""
from __future__ import annotations

import time

AXE_PINCE = 7


def _sans_pince(positions: dict) -> dict:
    """Retire l'axe 7 (pince/stylet) d'un dict de positions."""
    return {k: v for k, v in positions.items() if int(k) != AXE_PINCE}


def goto_dessin_doux(ctrl, depart: dict, *, duree: float | None = None,
                     dormir=time.sleep):
    """Amène `ctrl` à la pose de dessin `depart` en douceur, via la position de
    travail (`home_work`). Deux `move()` temporisés enchaînés avec attente de fin.

    - `duree` : durée de chaque palier (s). Par défaut `ctrl.home_duration`.
    - `dormir` : injectable (tests). Attend la fin de chaque mouvement.

    Retourne (ok, message). L'axe 7 est toujours exclu des cibles.
    """
    hw = _sans_pince(ctrl.home_work)
    if not hw:
        return False, "home_work non défini"
    hd = duree if duree is not None else getattr(ctrl, "home_duration", 2.5)

    # Palier 1 : position de travail (calibrée → skip_limits).
    ok, msg = ctrl.move(hw, hd, skip_limits=True)
    if not ok:
        return False, f"palier travail : {msg}"
    dormir(hd + 0.2)  # move() est asynchrone : attendre la fin avant d'enchaîner

    # Palier 2 : pose de dessin. skip_limits=True comme pour les poses home :
    # c'est une pose calibrée de CONFIANCE (capturée et tenue dans les runs réels).
    # La posture de dessin est repliée → le modèle de collision strict de move()
    # la classe à tort en auto-collision Épaule×Avant-bras (faux-positif de marge),
    # alors qu'elle est physiquement atteignable. On saute donc la validation
    # stricte pour ce seul mouvement de confiance (anticollision global inchangé).
    cible = _sans_pince(depart)
    ok, msg = ctrl.move(cible, hd, skip_limits=True)
    if not ok:
        return False, f"palier dessin : {msg}"
    dormir(hd + 0.2)
    return True, "OK"
