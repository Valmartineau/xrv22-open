"""Orchestrateur du jeu : machine à états d'une partie de devinette.

IDLE → CAPTURE → PERCEIVE → (HYPOTHESIZE → SPEAK → LISTEN → EVALUATE)* → WIN/GIVE_UP → log.
Toutes les dépendances sont injectées (source, vision, cerveau, voix, carnet)
→ testable sans matériel ni Ollama. La perception se fait UNE fois en début de
partie (V1) ; l'affinage est verbal sur la même image.
"""
from __future__ import annotations

from typing import Dict, List


class DevinetteSession:
    def __init__(self, source, vision, cerveau, voix, carnet,
                 max_tours: int = 6) -> None:
        self.source = source        # .capture() -> bytes ; .canal -> str
        self.vision = vision        # .decris(bytes) -> str
        self.cerveau = cerveau      # .prochain_coup(description, historique) -> Move
        self.voix = voix            # .dis(texte) ; .ecoute() -> str
        self.carnet = carnet        # .enregistre(dict)
        self.max_tours = max_tours

    def jouer_une_partie(self) -> str:
        historique: List[Dict[str, str]] = []
        hypotheses: List[str] = []
        description = ""
        tours = 0
        issue = "give_up"
        erreur = None
        try:
            image = self.source.capture()                  # CAPTURE
            description = self.vision.decris(image)         # PERCEIVE
            while tours < self.max_tours:
                coup = self.cerveau.prochain_coup(description, historique)  # HYPOTHESIZE
                self.voix.dis(coup["phrase"])                              # SPEAK
                historique.append({"role": "eddy", "texte": coup["phrase"]})
                if coup["action"] == "win":
                    issue = "win"
                    break
                if coup["action"] == "give_up":
                    issue = "give_up"
                    break
                if coup["action"] == "guess":
                    hypotheses.append(coup["phrase"])
                tours += 1
                reponse = self._ecoute_non_vide()                          # LISTEN
                historique.append({"role": "joueur", "texte": reponse})    # EVALUATE
        except Exception as exc:  # noqa: BLE001 — robustesse démo : on ne plante jamais
            issue = "erreur"
            erreur = repr(exc)
            self.voix.dis("Oups, j'ai un souci technique — on réessaie ?")

        if issue == "give_up":
            self.voix.dis("Je donne ma langue au chat !")

        self.carnet.enregistre({                                           # log
            "canal": getattr(self.source, "canal", "?"),
            "description": description,
            "hypotheses": hypotheses,
            "issue": issue,
            "tours": tours,
            "erreur": erreur,
        })
        return issue

    def _ecoute_non_vide(self, max_relances: int = 2) -> str:
        for essai in range(max_relances + 1):
            reponse = self.voix.ecoute()
            if reponse.strip():
                return reponse
            if essai < max_relances:
                self.voix.dis("Je n'ai pas bien entendu, tu peux répéter ?")
        return ""
