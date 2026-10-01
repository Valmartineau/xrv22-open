"""Extrait l'action structurée de la réponse libre de la boîte blanche.

Contrat (spec §6) : { pensee, action: {manette, delta}, note }. Tolérant : JSON
pur, ou noyé dans de la prose / un bloc ```json. Clé « pensée » accentuée admise.
Échec d'extraction ⇒ ValueError (la boucle décide quoi en faire : re-demander).
"""
from __future__ import annotations

import json
import re
from typing import Dict

_OBJ = re.compile(r"\{.*\}", re.DOTALL)  # premier '{' … dernier '}'


def parse_reponse(texte: str) -> Dict:
    m = _OBJ.search(texte)
    if not m:
        raise ValueError(f"aucun objet JSON dans la réponse : {texte!r}")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide dans la réponse : {e}") from e

    pensee = raw.get("pensee", raw.get("pensée", ""))
    action = raw.get("action") or {}
    if not isinstance(action, dict) or "manette" not in action or "delta" not in action:
        raise ValueError(f"action incomplète (manette/delta manquant) : {raw!r}")
    try:
        manette, delta = int(action["manette"]), int(action["delta"])
    except (TypeError, ValueError) as e:
        # sortie aberrante (manette/delta = liste, dict, None, texte non numérique)
        raise ValueError(f"manette/delta non entiers : {action!r}") from e
    return {
        "pensee": str(pensee),
        "action": {"manette": manette, "delta": delta},
        "note": str(raw.get("note", "")),
        # Réponse optionnelle à la personne qui dialogue (mode compagnon). Vide
        # si Eddy n'est pas adressé / ne répond pas.
        "reponse": str(raw.get("reponse", "")),
    }
