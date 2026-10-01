"""Extrait le coup structuré de la réponse libre du cerveau de jeu.

Contrat : { pensee, action ∈ ACTIONS, phrase }. Tolérant : JSON pur ou noyé
dans de la prose / un bloc ```json. Échec ⇒ ValueError (la session re-demande).
"""
from __future__ import annotations

import json
import re
from typing import Dict

ACTIONS = {"guess", "ask_clue", "win", "give_up"}
_OBJ = re.compile(r"\{.*\}", re.DOTALL)


def parse_move(texte: str) -> Dict:
    m = _OBJ.search(texte)
    if not m:
        raise ValueError(f"aucun objet JSON dans la réponse : {texte!r}")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON invalide : {e}") from e

    action = raw.get("action")
    if action not in ACTIONS:
        raise ValueError(f"action invalide {action!r} (attendu {ACTIONS})")
    if "phrase" not in raw:
        raise ValueError(f"phrase manquante : {raw!r}")
    return {
        "pensee": str(raw.get("pensee", raw.get("pensée", ""))),
        "action": action,
        "phrase": str(raw["phrase"]),
    }
