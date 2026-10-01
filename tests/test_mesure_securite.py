# tests/test_mesure_securite.py
from incarne.corps.arret_descente import EvaluateurArret
from incarne.corps.mesure_securite import mesurer, robot_pret


class FakeClient:
    def __init__(self, positions):
        self._pos = positions
        self.writes = []

    def get_robot(self, rid):
        return {"positions": dict(self._pos), "torque_enabled": True}

    def write_positions(self, rid, cible):
        self.writes.append((rid, dict(cible)))
        return {"ok": True}


class FakeStylet:
    """Rend une séquence scriptée de pressions (état CONTACT)."""
    def __init__(self, pressions):
        self._seq = list(pressions)
        self._i = -1

    def lecture(self):
        self._i = min(self._i + 1, len(self._seq) - 1)
        return {"etat": "CONTACT", "p": self._seq[self._i], "x": 0, "y": 0}


def test_descend_jusqu_au_plateau_et_journalise():
    client = FakeClient({"5": 2000})
    # pressions vues APRÈS chaque pas : montée puis plateau
    stylet = FakeStylet([100, 200, 300, 400, 402, 404, 406])
    ev = EvaluateurArret(cap_pression=700, plateau_delta=15, plateau_fenetre=3,
                         descente_max=1000, seuil_contact=30)

    res = mesurer(client, stylet, ev, rid="robot_1", axe=5, sens=-1, pas=4,
                  dwell=0.0, dormir=lambda s: None)

    assert "plateau" in res["arret"].lower()
    # chaque pas a bougé l'axe 5 de -4 ticks, en écriture absolue
    assert client.writes[0] == ("robot_1", {5: 1996})
    assert client.writes[1] == ("robot_1", {5: 1992})
    # le journal a une entrée par pas effectué
    assert len(res["journal"]) == len(client.writes)
    assert res["journal"][0]["pression"] == 100


def test_abort_clavier_remonte_le_stylet_au_depart():
    client = FakeClient({"5": 2000})

    class StyletQuiCoupe:
        def __init__(self):
            self.n = 0

        def lecture(self):
            self.n += 1
            if self.n >= 3:
                raise KeyboardInterrupt
            return {"etat": "CONTACT", "p": 100 * self.n, "x": 0, "y": 0}

    ev = EvaluateurArret(descente_max=1000)
    res = mesurer(client, StyletQuiCoupe(), ev, rid="robot_1", axe=5, sens=-1,
                  pas=4, dwell=0.0, dormir=lambda s: None)

    assert "abort" in res["arret"].lower() or "remont" in res["arret"].lower()
    # dernière écriture = retour à la position de départ (2000)
    assert client.writes[-1] == ("robot_1", {5: 2000})


def test_axe_absent_abort_sans_mouvement():
    client = FakeClient({"5": 2000})
    stylet = FakeStylet([100, 200, 300])
    ev = EvaluateurArret(descente_max=1000)
    res = mesurer(client, stylet, ev, rid="robot_1", axe=3, sens=-1, pas=4,
                  dwell=0.0, dormir=lambda s: None)
    assert "absent" in res["arret"].lower()
    assert client.writes == []  # aucun mouvement


def test_robot_pret_refuse_torque_off():
    pret, raison = robot_pret({"connected": True, "torque_enabled": False})
    assert pret is False
    assert "torque" in raison.lower()


def test_robot_pret_ok():
    pret, raison = robot_pret({"connected": True, "torque_enabled": True})
    assert pret is True
    assert raison is None


def test_abort_si_stylet_hors_portee_au_depart():
    from incarne.corps.mesure_securite import verifier_depart

    class StyletHorsPortee:
        def lecture(self):
            return {"etat": "HORS-PORTEE", "p": 0, "x": None, "y": None}

    ok, raison = verifier_depart(StyletHorsPortee())
    assert ok is False
    assert "portée" in raison.lower() or "portee" in raison.lower()
