# tests/test_arret_descente.py
from incarne.corps.arret_descente import EvaluateurArret


def test_cap_de_pression_arrete():
    ev = EvaluateurArret(cap_pression=700, descente_max=1000)
    assert ev.evaluer(pression=699, en_portee=True, descente_cumulee=10) == (True, None)
    cont, raison = ev.evaluer(pression=700, en_portee=True, descente_cumulee=14)
    assert cont is False
    assert "cap" in raison.lower()


def test_perte_de_signal_arrete():
    ev = EvaluateurArret(cap_pression=700, descente_max=1000)
    cont, raison = ev.evaluer(pression=200, en_portee=False, descente_cumulee=8)
    assert cont is False
    assert "signal" in raison.lower()


def test_descente_max_arrete():
    ev = EvaluateurArret(cap_pression=700, descente_max=120)
    cont, raison = ev.evaluer(pression=200, en_portee=True, descente_cumulee=120)
    assert cont is False
    assert "max" in raison.lower()


def test_plateau_arrete_quand_la_pression_cesse_de_monter():
    ev = EvaluateurArret(cap_pression=700, plateau_delta=15, plateau_fenetre=3,
                         descente_max=1000, seuil_contact=30)
    # montée franche puis plateau (~+2/pas)
    seq = [50, 150, 250, 350, 352, 354, 356]
    resultats = [ev.evaluer(p, en_portee=True, descente_cumulee=10) for p in seq]
    assert all(c for c, _ in resultats[:-1])          # tout continue avant
    cont, raison = resultats[-1]
    assert cont is False
    assert "plateau" in raison.lower() or "glissement" in raison.lower()


def test_pas_de_plateau_en_survol_sous_le_seuil_contact():
    # pression ~0 (survol) plusieurs pas : pas de faux plateau, on continue
    ev = EvaluateurArret(cap_pression=700, plateau_delta=15, plateau_fenetre=3,
                         descente_max=1000, seuil_contact=30)
    resultats = [ev.evaluer(0, en_portee=True, descente_cumulee=10) for _ in range(6)]
    assert all(c for c, _ in resultats)


def test_pression_none_ne_crashe_pas():
    # une lecture None (capteur muet) ne doit pas lever : on continue proprement
    ev = EvaluateurArret(cap_pression=700, plateau_delta=15, plateau_fenetre=3,
                         descente_max=1000, seuil_contact=30)
    cont, raison = ev.evaluer(None, en_portee=True, descente_cumulee=10)
    assert cont is True
    assert raison is None


def test_arret_si_contact_jamais_etabli():
    # 16 pas en portée mais pression toujours nulle (montage absent) → arrêt
    ev = EvaluateurArret(cap_pression=700, plateau_delta=15, plateau_fenetre=3,
                         descente_max=1000, seuil_contact=30,
                         max_pas_sans_contact=15)
    resultats = [ev.evaluer(0, en_portee=True, descente_cumulee=10 + i)
                 for i in range(16)]
    cont, raison = resultats[-1]
    assert cont is False
    assert "contact" in raison.lower()
