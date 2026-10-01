"""Accumulation des traits du flux stylet pour l'écran Dessin (Pi, Tkinter).

Fonction pure : à partir des ticks `stylet.tick`, construit la liste des traits
(strokes). Un trait = suite de points contigus en contact (p>0). Le contact qui
cesse (p=0 ou coords absentes) ROMPT le trait ; le contact suivant en démarre un
nouveau. Testable sans écran ni matériel.
"""
from xrv22.ui_pi.dessin_trace import ajoute_tick


def _t(x, y, p):
    return {"x": x, "y": y, "p": p, "etat": "CONTACT" if p > 0 else "SURVOL"}


def test_accumule_les_points_en_contact_dans_un_meme_trait():
    s = []
    s = ajoute_tick(s, _t(10, 20, 300))
    s = ajoute_tick(s, _t(12, 22, 320))
    assert len(s) == 1
    assert s[0] == [(10, 20, 300), (12, 22, 320)]


def test_rompt_le_trait_quand_le_contact_cesse_puis_repart():
    s = []
    s = ajoute_tick(s, _t(10, 20, 300))
    s = ajoute_tick(s, _t(11, 21, 0))     # plus de contact → rupture
    s = ajoute_tick(s, _t(40, 50, 300))   # nouveau trait
    assert len(s) == 2
    assert s[0] == [(10, 20, 300)]
    assert s[1] == [(40, 50, 300)]


def test_ignore_les_ticks_hors_contact_au_debut():
    s = ajoute_tick([], _t(None, None, 0))
    assert s == []
