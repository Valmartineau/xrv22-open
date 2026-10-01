"""Mémoire des parties de devinette (journal JSONL persistant).

En V1 : journalisation seule (pas d'adaptation de difficulté). Une ligne JSON
par partie : canal, description perçue, hypothèses, issue, nombre de tours.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


class CarnetParties:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def enregistre(self, partie: Dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(partie, ensure_ascii=False) + "\n")

    def parties(self) -> List[Dict]:
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def recap(self) -> str:
        ps = self.parties()
        gagnees = sum(1 for p in ps if p.get("issue") == "win")
        return f"{len(ps)} partie(s), dont {gagnees} en 'win'."
