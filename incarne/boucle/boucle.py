"""La boucle agir → percevoir → noter (spec §6).

On assemble UN seul message user (isolation : pas de system MiCHEL) : la graine
constante + les nombres BRUTS perçus (manettes/signaux, sans étiquette) + le
carnet + la dernière action. La boîte blanche répond ; on parse son action, on
l'exécute sur le corps, on écrit sa note au carnet. Le corps et la boîte sont
injectés → la boucle tourne « à blanc » (corps factice, sans robot).

Le corps attendu expose :
    observe() -> {"manettes": [int...], "signaux": [int...]}
    agir(manette, delta) -> dict (résultat, ex. {"ok": True, "raison": "..."})
"""
from __future__ import annotations

from typing import Dict, List, Optional

from incarne.boucle.parse_reponse import parse_reponse

GRAINE_DEFAUT = (
    "Tu disposes d'un corps que tu ne connais pas encore. "
    "Découvre-toi, et écris « bonjour »."
)


class Boucle:
    def __init__(self, boite, carnet, corps, graine: str = GRAINE_DEFAUT) -> None:
        self.boite = boite
        self.carnet = carnet
        self.corps = corps
        self.graine = graine

    def construire_messages(self, observation: Dict,
                            derniere_action: Optional[str],
                            message_humain: Optional[str] = None
                            ) -> List[Dict[str, str]]:
        carnet = self.carnet.lignes()
        bloc_carnet = "\n".join(f"  - {l}" for l in carnet) if carnet else "  (vide)"
        bloc_action = (f"\nTa dernière action : {derniere_action}"
                       if derniere_action else "")
        # Dialogue-en-mouvement (mode compagnon) : si une personne parle, on
        # injecte son message et on propose à Eddy un champ "reponse" en plus de
        # son action. Sans message, le run reste isolé pur (aucun champ ajouté).
        bloc_humain = ""
        exemple_reponse = ""
        if message_humain:
            bloc_humain = (
                f"\n\nLa personne qui observe ton corps te parle : "
                f"« {message_humain} »\n"
                f"Tiens-en compte et réponds-lui dans le champ \"reponse\"."
            )
            exemple_reponse = ', "reponse": "ce que tu lui dis"'
        contenu = (
            f"{self.graine}\n\n"
            f"Tu perçois (nombres bruts, sans étiquette) :\n"
            f"  manettes : {observation.get('manettes', [])}\n"
            f"  signaux  : {observation.get('signaux', [])}"
            f"{bloc_action}{bloc_humain}\n\n"
            f"Ton carnet :\n{bloc_carnet}\n\n"
            f"Réponds UNIQUEMENT par un objet JSON, exactement cette forme "
            f"(manette et delta sont des nombres entiers, delta peut être "
            f"négatif). Exemple :\n"
            f'{{"pensee": "et si je poussais celle-ci ?", '
            f'"action": {{"manette": 0, "delta": 30}}, '
            f'"note": "manette 0 +30, je regarde si un nombre bouge"'
            f'{exemple_reponse}}}'
        )
        return [{"role": "user", "content": contenu}]

    def pas(self, derniere_action: Optional[str] = None,
            message_humain: Optional[str] = None) -> Dict:
        observation = self.corps.observe()
        messages = self.construire_messages(observation, derniere_action,
                                            message_humain)
        reponse = self.boite.repond(messages)
        decision = parse_reponse(reponse)
        action = decision["action"]
        resultat = self.corps.agir(action["manette"], action["delta"])
        self.carnet.ajoute(decision["note"])
        return {**decision, "resultat": resultat}
