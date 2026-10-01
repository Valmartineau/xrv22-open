"""Perception tablette → signaux bruts pour la boîte blanche.

`signaux_stylet(lecture)` transforme une lecture StyletLecteur
({"etat","x","y","p"}) en une liste d'entiers ANONYMES [x, y, p] que la boucle
injecte tels quels dans l'observation (cf corps_rxv22.lire_signaux). Aucun label,
aucune explication : la boîte blanche ne voit que des nombres qui bougent quand
elle agit. Les None (stylet hors-portée → x/y absents) deviennent 0.
"""
from incarne.corps.perception import signaux_stylet


def test_signaux_stylet_rend_x_y_pression_en_ints():
    lec = {"etat": "CONTACT", "x": 1200, "y": 3400, "p": 512}
    assert signaux_stylet(lec) == [1200, 3400, 512]


def test_signaux_stylet_remplace_none_par_zero():
    lec = {"etat": "HORS-PORTEE", "x": None, "y": None, "p": 0}
    assert signaux_stylet(lec) == [0, 0, 0]


def test_signaux_stylet_ne_contient_que_des_ints():
    lec = {"etat": "SURVOL", "x": 10, "y": 20, "p": 0}
    assert all(isinstance(v, int) for v in signaux_stylet(lec))
