"""POST JSON local vers Ollama (urllib, aucune dépendance externe).

Partagé par eddy/vision et eddy/cerveau. Hôte local maîtrisé (localhost ou
lien Tailscale) — jamais d'appel cloud.
"""
from __future__ import annotations

import json
from urllib import request as _urlreq


def ollama_post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = _urlreq.Request(url, data=data,
                          headers={"Content-Type": "application/json"})
    with _urlreq.urlopen(req) as resp:  # noqa: S310 (host local maîtrisé)
        return json.loads(resp.read().decode("utf-8"))
