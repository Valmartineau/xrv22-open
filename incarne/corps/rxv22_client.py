"""Client HTTP fin vers le serveur RXV22 (token Bearer).

Trois appels suffisent au corps nu : lire l'état (positions), écrire des
positions directes, (dés)activer le torque. L'appel réseau est injectable
(`http_request`) pour les tests ; par défaut urllib (aucune dépendance tierce).
"""
from __future__ import annotations

import json
from typing import Callable, Dict, Optional
from urllib import request as _urlreq

# Signature de l'appel injecté : (method, url, headers, body|None) -> dict
HttpRequest = Callable[[str, str, Dict[str, str], Optional[dict]], dict]


def _default_request(method: str, url: str, headers: Dict[str, str],
                     body: Optional[dict]) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = _urlreq.Request(url, data=data, headers=headers, method=method)
    with _urlreq.urlopen(req) as resp:  # noqa: S310 (hôte LAN maîtrisé)
        return json.loads(resp.read().decode("utf-8"))


class RxV22Client:
    def __init__(self, base_url: str, token: str,
                 http_request: Optional[HttpRequest] = None) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self._req = http_request or _default_request

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}",
                   "Content-Type": "application/json"}
        return self._req(method, f"{self.base}{path}", headers, body)

    def get_robot(self, rid: str) -> dict:
        return self._call("GET", f"/api/robots/{rid}")

    def write_positions(self, rid: str, cible: Dict[int, int]) -> dict:
        body = {"positions": {str(k): int(v) for k, v in cible.items()}}
        return self._call("POST", f"/api/robots/{rid}/positions", body)

    def set_torque(self, rid: str, enable: bool) -> dict:
        return self._call("POST", f"/api/robots/{rid}/torque", {"enable": bool(enable)})

    def set_direct_mode(self, rid: str, enable: bool) -> dict:
        """Prend (True) / lâche (False) la main sur le robot. NÉCESSAIRE pour que
        les écritures de position pilotent réellement le servo (sinon no-op)."""
        return self._call("POST", f"/api/robots/{rid}/direct_mode", {"enable": bool(enable)})

    def publier_eddy(self, payload: Dict) -> dict:
        """Publie un pas au moniteur Eddy (POST /api/eddy/step → bus → WS)."""
        return self._call("POST", "/api/eddy/step", payload)

    def publier_stylet(self, payload: Dict) -> dict:
        """Publie un tick stylet (flux dessin) → POST /api/stylet/tick → bus → WS."""
        return self._call("POST", "/api/stylet/tick", payload)
