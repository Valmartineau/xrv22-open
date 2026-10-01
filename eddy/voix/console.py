"""Voix de secours en mode texte (stdin/stdout).

Même interface que la vraie voix VoiceMode (dis / ecoute) → permet de jouer la
boucle complète sans audio, et de la tester avec des doublures.
"""
from __future__ import annotations

from typing import Callable


class VoixConsole:
    def __init__(self, entree: Callable[..., str] = input,
                 sortie: Callable[[str], None] = print) -> None:
        self._entree = entree
        self._sortie = sortie

    def dis(self, texte: str) -> None:
        self._sortie(f"🤖 Eddy : {texte}")

    def ecoute(self) -> str:
        return self._entree("🧑 toi : ").strip()
