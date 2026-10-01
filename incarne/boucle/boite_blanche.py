"""La boîte blanche — client Ollama (Mistral) nu et isolé.

Aucun contexte MiCHEL : pas de vault/RAG, pas de system prompt d'identité. Le
client transmet exactement les messages reçus (graine + carnet + observation,
assemblés au-dessus) et rend le contenu de la réponse. Sa seule mémoire est le
carnet — géré par la boucle, pas ici.

Choix modèle : Mistral (souveraineté européenne). Paramétrable : `model` +
`host`. L'appel HTTP est injectable (`http_post`) pour les tests ; par défaut il
parle à l'API /api/chat d'Ollama via la lib standard (aucune dépendance tierce).
"""
from __future__ import annotations

import json
import time
from http.client import HTTPException
from typing import Callable, Dict, List, Optional
from urllib import request as _urlreq

# Timeout de l'appel Ollama : assez large pour une réponse normale du 24b, mais
# borné pour qu'un tunnel à moitié mort ne fasse pas pendre le run indéfiniment.
_TIMEOUT_S = 120

# Borne dure de génération : la réponse d'Eddy est un petit JSON (pensée + action
# + note). À haute température le 24b peut partir en sortie interminable → recv
# pend → timeout → run mort. On plafonne le nombre de tokens générés.
_NUM_PREDICT = 512

# Erreurs réseau transitoires (tunnel SSH qui tombe/revient) → on retente.
# OSError couvre ConnectionResetError, socket.timeout, URLError ; HTTPException
# couvre RemoteDisconnected/BadStatusLine.
_ERREURS_RESEAU = (OSError, HTTPException)


def _ollama_post(url: str, body: dict) -> dict:
    """POST JSON par défaut vers Ollama (urllib, pas de dépendance externe)."""
    data = json.dumps(body).encode("utf-8")
    req = _urlreq.Request(url, data=data,
                          headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 (host local)
        return json.loads(resp.read().decode("utf-8"))


class BoiteBlanche:
    """LLM vierge isolé. `repond(messages)` → texte de la réponse."""

    def __init__(self, model: str, host: str = "http://localhost:11434",
                 http_post: Optional[Callable[[str, dict], dict]] = None,
                 temperature: Optional[float] = None) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._post = http_post or _ollama_post
        # Levier de diversité d'exploration (NOTRE échafaudage, on n'explique rien
        # à la boîte blanche) : température Ollama. None = défaut du modèle.
        self.temperature = temperature

    def repond(self, messages: List[Dict[str, str]], *,
               _essais: int = 5, _attente: float = 3.0,
               _dormir: Callable[[float], None] = time.sleep) -> str:
        """Envoie les messages TELS QUELS (aucun contexte injecté) et rend le
        contenu de la réponse, espaces de bord retirés.

        Résilient aux coupures réseau (run long : le tunnel SSH peut tomber et
        revenir) : on retente `_essais` fois sur erreur réseau, avec `_attente`
        entre chaque (le temps que le tunnel auto-reconnectant revienne). Les
        erreurs NON réseau (réponse malformée…) ne sont pas retentées."""
        options: Dict[str, float] = {"num_predict": _NUM_PREDICT}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        body = {"model": self.model, "messages": messages,
                "stream": False, "options": options}
        derniere_exc: Optional[BaseException] = None
        for i in range(_essais):
            try:
                out = self._post(f"{self.host}/api/chat", body)
                return out["message"]["content"].strip()
            except _ERREURS_RESEAU as exc:
                derniere_exc = exc
                if i < _essais - 1:
                    _dormir(_attente)
        raise derniere_exc  # type: ignore[misc]
