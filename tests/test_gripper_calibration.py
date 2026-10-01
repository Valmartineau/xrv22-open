"""La calibration de la pince existe en DEUX exemplaires — `xrv22/config.py`
(Pi, Tkinter) et `web/src/grip.ts` (front). Deux copies d'un même nombre
divergent toujours un jour, et ici la divergence est muette : l'écran du Pi
afficherait 40 mm là où le navigateur en affiche 46, sans qu'aucun test ne
tombe. Ce fichier est le seul endroit qui force les deux à dire la même chose.
"""
import re
from pathlib import Path

from xrv22.config import (
    GRIP_CLOSE_TICK,
    GRIP_OPEN_TICK,
    GRIP_SPAN_MM,
    gripper_mm,
)

GRIP_TS = Path(__file__).resolve().parents[1] / "web" / "src" / "grip.ts"


def _const_ts(nom: str) -> float:
    """La valeur d'une constante exportée de grip.ts (`export const X = 42;`)."""
    m = re.search(r"export const %s\s*=\s*([0-9.]+)" % nom, GRIP_TS.read_text(encoding="utf-8"))
    assert m, "constante %s introuvable dans %s" % (nom, GRIP_TS)
    return float(m.group(1))


def test_ancres_mesurees_en_live():
    """Les deux ancres du 2026-06-15 sur robot_1, telles que mesurees."""
    assert GRIP_CLOSE_TICK == 1649
    assert GRIP_OPEN_TICK == 2860
    assert GRIP_SPAN_MM == 46.0


def test_python_et_typescript_disent_la_meme_chose():
    assert _const_ts("GRIP_CLOSE_TICK") == GRIP_CLOSE_TICK
    assert _const_ts("GRIP_OPEN_TICK") == GRIP_OPEN_TICK
    assert _const_ts("GRIP_SPAN_MM") == GRIP_SPAN_MM


def test_contact_et_butee():
    assert gripper_mm(GRIP_CLOSE_TICK) == 0.0
    assert abs(gripper_mm(GRIP_OPEN_TICK) - GRIP_SPAN_MM) < 1e-9


def test_jamais_d_ecart_negatif():
    """Sous le tick de contact les doigts se touchent : l'ecart reste 0."""
    assert gripper_mm(GRIP_CLOSE_TICK - 200) == 0.0
    assert gripper_mm(0) == 0.0
