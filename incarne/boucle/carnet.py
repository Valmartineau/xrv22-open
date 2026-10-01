"""Le carnet — seule mémoire de la boîte blanche (spec §7).

Une ligne par note, persisté sur disque, relu à chaque pas. Substrat de
l'apprentissage ET fenêtre d'observation pour nous.
"""
from __future__ import annotations

from pathlib import Path
from typing import List


class Carnet:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def ajoute(self, ligne: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(ligne.rstrip("\n") + "\n")

    def lignes(self) -> List[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()
