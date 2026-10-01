"""
xrv22/services/logger.py
─────────────────────────
Logging structuré XRV22.

Niveaux :
  INFO     — événements normaux
  WARNING  — situations récupérables
  ERROR    — erreurs hardware/logique
  SAFETY   — tout événement safety (fichier séparé safety.log)

Format : [HH:MM:SS.mmm] [MODULE] [LEVEL] message
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

# ── Niveau custom SAFETY ─────────────────────────────────────────
SAFETY_LEVEL = 45  # Entre ERROR(40) et CRITICAL(50)
logging.addLevelName(SAFETY_LEVEL, "SAFETY")


def safety(self: logging.Logger, msg: str, *args, **kwargs) -> None:
    """Logger.safety() — niveau dédié aux événements safety."""
    if self.isEnabledFor(SAFETY_LEVEL):
        self._log(SAFETY_LEVEL, msg, args, **kwargs)


logging.Logger.safety = safety  # type: ignore[attr-defined]


# ── Formatter ────────────────────────────────────────────────────

class XRFormatter(logging.Formatter):
    """Format : [HH:MM:SS.mmm] [MODULE] [LEVEL] message"""

    _FMT = "[%(asctime)s.%(msecs)03d] [%(name)-22s] [%(levelname)-7s] %(message)s"
    _DATE = "%H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt=self._DATE)


# ── Setup ─────────────────────────────────────────────────────────

def setup_logging(log_dir: str = "", debug: bool = False) -> None:
    """Initialise le logging XRV22 (appeler une seule fois au démarrage).
    debug=True active le niveau DEBUG sur la console (sinon INFO)."""
    if not log_dir:
        log_dir = str(Path(__file__).resolve().parent.parent.parent / "XRV22_LIBRARY" / "logs")
    path = Path(log_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("XRV22")
    root.setLevel(logging.DEBUG)

    _add_console_handler(root, level=logging.DEBUG if debug else logging.INFO)
    _add_file_handler(root, path / "xrv22.log")
    _add_safety_handler(root, path / "safety.log")


def _add_console_handler(logger: logging.Logger,
                         level: int = logging.INFO) -> None:
    h = logging.StreamHandler()
    h.setLevel(level)
    h.setFormatter(XRFormatter())
    logger.addHandler(h)


def _add_file_handler(logger: logging.Logger, path: Path) -> None:
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    h.setLevel(logging.DEBUG)
    h.setFormatter(XRFormatter())
    logger.addHandler(h)


def _add_safety_handler(logger: logging.Logger, path: Path) -> None:
    h = logging.handlers.RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    h.setLevel(SAFETY_LEVEL)
    h.setFormatter(XRFormatter())
    logger.addHandler(h)


def get_logger(module: str) -> logging.Logger:
    """Retourne un logger nommé XRV22.<module>."""
    return logging.getLogger(f"XRV22.{module}")
