"""
xrv22/server/auth.py
─────────────────────
ETAPE 5 — Authentification minimale par token partage.

Modele : un seul token, persiste sur disque (XRV22_LIBRARY/auth_token.json).
Genere au premier boot, reutilise ensuite. Affiche en QR code dans les logs
(et dans l'UI tactile Pi en future iteration) pour permettre a un client
LAN de se connecter sans saisie manuelle.

Validation :
    - Routes HTTP : Authorization: Bearer <token> OU ?token=<token>
    - WebSocket   : ?token=<token> en query string (les WS n'envoient pas
                    de header Authorization de maniere standard cote browser)

Routes exemptees d'auth :
    - /api/health  (probe systemd / monitoring)
    - /             et tout le static (HTML, JS, CSS, favicon) -> sinon
                    le navigateur ne peut meme pas charger la page d'auth
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Optional

from xrv22.services.logger import get_logger

_LOG = get_logger("Auth")

# Fichier de persistance : a cote de la library, pas dans un projet
_TOKEN_PATH = Path.home() / "xrv22" / "XRV22_LIBRARY" / "auth_token.json"

# Routes qui n'exigent pas de token
PUBLIC_PREFIXES = (
    "/api/health",
    "/assets/",        # bundles JS/CSS/images Vite
    "/favicon",
    "/icons.svg",
)

# Routes exactement publiques (path complet)
PUBLIC_PATHS = {"/", "/index.html"}


_MIN_TOKEN_LEN = 8  # MP utilisateur autorise (LAN). En dessous = rejete.


def _load_or_create_token() -> str:
    """Lit le token persiste, ou en cree un nouveau et le sauvegarde."""
    try:
        with open(_TOKEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        token = data.get("token", "")
        if isinstance(token, str) and len(token) >= _MIN_TOKEN_LEN:
            if len(token) < 16:
                _LOG.warning("Token court (%d chars) — OK sur LAN, "
                             "evite si exposition internet.", len(token))
            return token
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    # Generation : 32 bytes hex = 64 caracteres, espace 256 bits
    token = secrets.token_hex(32)
    try:
        _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
            json.dump({"token": token}, f)
        # Permissions restrictives (proprietaire only)
        try:
            _TOKEN_PATH.chmod(0o600)
        except OSError:
            pass
        _LOG.info("Token genere et sauvegarde dans %s", _TOKEN_PATH)
    except OSError as exc:
        _LOG.warning("Impossible de sauvegarder le token : %s", exc)
    return token


# Singleton charge a l'import du module
_TOKEN: str = _load_or_create_token()


def get_token() -> str:
    """Retourne le token courant (pour usage UI Tk Pi, QR code, logs)."""
    return _TOKEN


def is_public_path(path: str) -> bool:
    """True si le path est exempte d'authentification."""
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIXES)


def extract_token(authorization: Optional[str],
                  query_token: Optional[str]) -> Optional[str]:
    """Recupere le token depuis le header Authorization ou ?token=."""
    if authorization:
        parts = authorization.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    return query_token


def check_token(presented: Optional[str]) -> bool:
    """Verifie le token en temps constant."""
    if not presented:
        return False
    return secrets.compare_digest(presented, _TOKEN)


def make_qr_ascii(url: str) -> str:
    """Genere un QR code en ASCII (block characters) pour les logs.
    Fallback texte si la lib `qrcode` n'est pas dispo."""
    try:
        import qrcode  # type: ignore
    except ImportError:
        return f"[qrcode lib absente — installer via 'pip install qrcode']\nURL : {url}"
    qr = qrcode.QRCode(border=1, box_size=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    # 2 lignes du matrix -> 1 ligne de sortie via half-block (chaque cellule = 1 char)
    lines: list[str] = []
    for r in range(0, len(matrix), 2):
        line_chars = []
        for c in range(len(matrix[r])):
            top = matrix[r][c]
            bot = matrix[r + 1][c] if r + 1 < len(matrix) else False
            if top and bot:
                line_chars.append("█")     # full block
            elif top:
                line_chars.append("▀")     # upper half
            elif bot:
                line_chars.append("▄")     # lower half
            else:
                line_chars.append(" ")
        lines.append("".join(line_chars))
    return "\n".join(lines)
