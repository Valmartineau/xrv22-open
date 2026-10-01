"""Cerveau du jeu de devinette : à partir de ce qui est perçu (description
VLM) et du dialogue, décide le prochain coup. La logique de devinette vit dans
le modèle ; ici on assemble le contexte et on parse le coup.
"""
from __future__ import annotations

from typing import Dict, List

from eddy.cerveau.parse_move import parse_move

SYSTEM = (
    "Tu es Eddy, un compagnon de jeu. On te montre un objet ou un dessin : "
    "ta description est donnée ci-dessous. Tu dois faire DEVINER en posant des "
    "hypothèses à voix haute et en les affinant selon les réponses du joueur. "
    "Réponds UNIQUEMENT par un objet JSON : "
    '{"pensee": "...", "action": "guess|ask_clue|win|give_up", "phrase": "..."} '
    "— 'guess' = tu proposes (« C\'est un ... ? »), 'ask_clue' = tu demandes un "
    "indice, 'win' = le joueur vient de confirmer ta proposition, 'give_up' = "
    "tu abandonnes. 'phrase' est ce que tu diras à voix haute, en français."
)


class CerveauJeu:
    def __init__(self, chat, system: str = SYSTEM) -> None:
        self.chat = chat          # objet avec .repond(messages) -> str
        self.system = system

    def prochain_coup(self, description: str,
                      historique: List[Dict[str, str]]) -> Dict:
        dialogue = "\n".join(f"{t['role']}: {t['texte']}" for t in historique) \
            or "(aucun échange pour l'instant)"
        user = (f"Ce que tu perçois : {description}\n\n"
                f"Dialogue jusqu'ici :\n{dialogue}\n\n"
                "Donne ton prochain coup en JSON.")
        msgs = [{"role": "system", "content": self.system},
                {"role": "user", "content": user}]
        return parse_move(self.chat.repond(msgs))
