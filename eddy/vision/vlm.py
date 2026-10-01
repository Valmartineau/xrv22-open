"""Vision locale : décrit une image via un modèle multimodal Ollama.

Reçoit des OCTETS d'image (JPEG/PNG), les encode en base64 pour /api/chat.
http_post injectable pour les tests. Aucun appel cloud.
"""
from __future__ import annotations

import base64
from typing import Callable, Optional

from eddy._ollama import ollama_post

PROMPT = (
    "Décris en français, en une à deux phrases, ce que tu vois sur cette image. "
    "Si c'est un objet ou un dessin reconnaissable, nomme tes 1 à 3 hypothèses, "
    "de la plus probable à la moins probable."
)


class VisionModel:
    def __init__(self, model: str, host: str = "http://localhost:11434",
                 http_post: Optional[Callable[[str, dict], dict]] = None) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self._post = http_post or ollama_post

    def decris(self, image_bytes: bytes, prompt: str = PROMPT) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "user", "content": prompt, "images": [b64]}]}
        out = self._post(f"{self.host}/api/chat", body)
        return out["message"]["content"].strip()
