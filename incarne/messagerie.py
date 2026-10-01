"""
incarne/messagerie.py
─────────────────────
Boîte aux lettres simple entre la personne (UI /eddy → API) et le run en cours.

L'API y DÉPOSE les messages de Valentin ; la boucle de run la VIDE à chaque pas
et injecte les messages en attente dans le prompt d'Eddy (dialogue-en-mouvement).
Fichier-texte, une ligne par message. Process distincts (API vs run) → on accepte
une micro-fenêtre de course (un seul humain qui tape) au profit de la simplicité.
"""
from __future__ import annotations

from pathlib import Path
from typing import List


def deposer(message: str, path) -> None:
    """Ajoute un message à la boîte (une ligne ; sauts de ligne aplatis)."""
    msg = " ".join(str(message).split()).strip()
    if not msg:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def vider(path) -> List[str]:
    """Retourne tous les messages en attente ET vide la boîte."""
    p = Path(path)
    if not p.exists():
        return []
    lignes = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()
              if l.strip()]
    p.write_text("", encoding="utf-8")
    return lignes
