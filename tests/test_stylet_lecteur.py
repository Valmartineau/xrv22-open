# tests/test_stylet_lecteur.py
from incarne.stylet_reader import (StyletLecteur, EV_ABS, EV_KEY, EV_SYN,
                                    ABS_PRESSURE, BTN_TOOL_PEN, BTN_TOUCH,
                                    SYN_REPORT)


def test_lecture_reflete_les_evenements_jusqu_au_syn():
    lec = StyletLecteur()
    lec.appliquer(EV_KEY, BTN_TOOL_PEN, 1)   # en portée
    lec.appliquer(EV_KEY, BTN_TOUCH, 1)      # contact
    lec.appliquer(EV_ABS, ABS_PRESSURE, 421)
    lec.appliquer(EV_SYN, SYN_REPORT, 0)     # publie l'état
    snap = lec.lecture()
    assert snap["etat"] == "CONTACT"
    assert snap["p"] == 421


def test_lecture_initiale_hors_portee():
    assert StyletLecteur().lecture()["etat"] == "HORS-PORTEE"
