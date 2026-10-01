"""Démo : la boucle à blanc, contre le vrai Mistral, SANS robot.

Corps factice (les manettes bougent, les signaux restent inertes — pas de
tablette ici). But : voir une boîte blanche Mistral raisonner sur des manettes
anonymes et émettre des actions valides. Aucun matériel touché.

    python3 -m incarne.run_blanc [n_pas] [modele]
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from incarne.boucle.boite_blanche import BoiteBlanche
from incarne.boucle.boucle import Boucle
from incarne.boucle.carnet import Carnet
from incarne.boucle.parse_reponse import parse_reponse  # noqa: F401 (doc)


class CorpsFactice:
    """6 manettes anonymes (axe 7 déjà exclu côté corps nu) ; agir déplace la
    position de la manette visée (bornée) ; signaux inertes (pas de tablette)."""

    def __init__(self) -> None:
        self.manettes = [2048, 2048, 2048, 2048, 2048, 2048]
        self.signaux = [0, 0, 0, 0]

    def observe(self) -> dict:
        return {"manettes": list(self.manettes), "signaux": list(self.signaux)}

    def agir(self, manette: int, delta: int) -> dict:
        if not 0 <= manette < len(self.manettes):
            return {"ok": False, "raison": "manette inexistante"}
        avant = self.manettes[manette]
        self.manettes[manette] = max(1024, min(3072, avant + delta))
        return {"ok": True, "raison": "exécutée",
                "manette": manette, "avant": avant, "apres": self.manettes[manette]}


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    modele = sys.argv[2] if len(sys.argv) > 2 else "mistral:latest"

    carnet_path = Path(tempfile.gettempdir()) / "carnet_blanc.txt"
    carnet_path.unlink(missing_ok=True)

    boucle = Boucle(BoiteBlanche(model=modele), Carnet(carnet_path), CorpsFactice())
    print(f"=== Boucle à blanc — {modele}, {n} pas (corps factice, sans robot) ===\n")

    derniere = None
    for i in range(1, n + 1):
        try:
            r = boucle.pas(derniere_action=derniere)
        except ValueError as e:
            print(f"[pas {i}] réponse non exploitable : {e}\n")
            continue
        a = r["action"]
        print(f"[pas {i}] pensée : {r['pensee']}")
        print(f"         action : manette {a['manette']}, delta {a['delta']} "
              f"→ {r['resultat']}")
        print(f"         note   : {r['note']}\n")
        derniere = (f"manette {a['manette']}, delta {a['delta']} → "
                    f"{r['resultat'].get('raison')}")

    print("--- carnet final ---")
    for ligne in Carnet(carnet_path).lignes():
        print(f"  - {ligne}")


if __name__ == "__main__":
    main()
