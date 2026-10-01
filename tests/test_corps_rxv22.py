"""Le corps RXV22 réel : observe/agir/armer par-dessus le client HTTP + corps nu.
Client injecté (faux) → testable sans robot.

- observe : positions → manettes ordonnées, axe 7 jamais exposé ;
- agir    : lit le présent, écrit la cible bornée sur le bon axe, jamais l'axe 7 ;
- armer   : torque ON + goal = position courante (anti-sursaut, cf reveil_coude).
"""
from incarne.corps.corps_nu import CorpsNu
from incarne.corps.corps_rxv22 import CorpsRxv22


class FakeClient:
    def __init__(self, positions):
        self._pos = positions
        self.writes = []
        self.torque_calls = []

    def get_robot(self, rid):
        return {"positions": dict(self._pos), "torque_enabled": True, "connected": True}

    def write_positions(self, rid, cible):
        self.writes.append((rid, cible))
        return {"ok": True, "positions": cible}

    def set_torque(self, rid, enable):
        self.torque_calls.append((rid, enable))
        return {"ok": True, "torque_enabled": enable}


def test_observe_mappe_les_manettes_sans_axe_7():
    client = FakeClient({"1": 100, "2": 200, "3": 300,
                         "4": 400, "5": 500, "6": 600, "7": 999})
    corps = CorpsRxv22(client, "robot_1", CorpsNu([1, 2, 3, 4, 5, 6, 7], delta_cap=30))
    obs = corps.observe()
    assert obs["manettes"] == [100, 200, 300, 400, 500, 600]  # axe 7 (=999) exclu


def test_observe_inclut_les_signaux_injectes():
    client = FakeClient({"1": 0, "2": 0})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 2], delta_cap=30),
                       lire_signaux=lambda: [12, 34, 0, 1])
    assert corps.observe()["signaux"] == [12, 34, 0, 1]


def test_agir_ecrit_la_cible_bornee_sur_le_bon_axe():
    client = FakeClient({"1": 1000, "2": 2000, "3": 3000})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 2, 3], delta_cap=30))
    corps.agir(manette=1, delta=50)  # manette 1 → axe 2 ; +50 borné 30 → 2030
    assert client.writes == [("r", {2: 2030})]


def test_armer_reconcilie_le_goal_au_torque_on():
    client = FakeClient({"1": 1000, "2": 2000, "7": 2500})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 2, 7], delta_cap=30))
    corps.armer()
    assert client.torque_calls == [("r", True)]
    # goal écrit = positions courantes (toutes, incl. axe 7) → anti-sursaut
    assert client.writes[-1] == ("r", {1: 1000, 2: 2000, 7: 2500})


# --- Garde-fou tolérant (post-geste + annulation, axe-agnostique) ------------
# Bras pédagogique souple : pas de relation axe↔pression fiable. On laisse Eddy
# bouger n'importe quel axe ; APRÈS le geste on lit la pression et si elle dépasse
# le plafond on RÉÉCRIT la position précédente (annulation). Tolérant à la
# souplesse ; un dépassement ±cap sur bras souple/pointe-ressort est inoffensif.

def _corps_garde(client, plafond=650):
    return CorpsRxv22(client, "r", CorpsNu([1, 2, 3, 4, 5, 6], delta_cap=30),
                      lire_pression=lambda: client.pression,
                      plafond_pression=plafond, dormir=lambda _s: None)


def test_agir_ecrit_si_pression_reste_sous_le_plafond():
    client = FakeClient({"1": 2000, "2": 0, "3": 0, "4": 0, "5": 2080, "6": 0})
    client.pression = 400
    corps = _corps_garde(client)
    res = corps.agir(manette=0, delta=10)        # manette 0 → axe 1 ; +10 → 2010
    assert client.writes == [("r", {1: 2010})]   # un seul write, pas d'annulation
    assert res["ok"] is True


def test_agir_annule_si_pression_depasse_apres_le_geste():
    client = FakeClient({"1": 2000, "2": 0, "3": 0, "4": 0, "5": 2080, "6": 0})
    client.pression = 700                         # pression post-geste ≥ plafond 650
    corps = _corps_garde(client)
    res = corps.agir(manette=0, delta=10)
    # geste exécuté PUIS annulé (réécriture de la position précédente)
    assert client.writes == [("r", {1: 2010}), ("r", {1: 2000})]
    assert res["ok"] is False
    assert res["bloque"] == "plafond_pression" and res["pression"] == 700


def test_agir_sans_capteur_ecrit_toujours():
    client = FakeClient({"1": 2000, "5": 2080})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 5], delta_cap=30))
    corps.agir(manette=0, delta=10)
    assert client.writes == [("r", {1: 2010})]


def test_agir_observation_n_ecrit_rien():
    # Mode passif : torque OFF, l'humain bouge le bras, Eddy observe seulement.
    # agir() ne doit RIEN écrire (no-op) et signaler qu'il est passif.
    client = FakeClient({"1": 2000, "5": 2080})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 5], delta_cap=30), observation=True)
    res = corps.agir(manette=0, delta=10)
    assert client.writes == []
    assert res.get("passif") is True


def test_agir_manette_hors_plage_no_op_sans_crash():
    # Robustesse : à température élevée la boîte blanche peut émettre une manette
    # inexistante → on l'ignore (no-op), on ne plante pas (IndexError).
    client = FakeClient({"1": 2000, "5": 2080})
    corps = CorpsRxv22(client, "r", CorpsNu([1, 5], delta_cap=30))  # manettes 0,1
    res = corps.agir(manette=6, delta=10)
    assert client.writes == []
    assert res["ok"] is False and "inexistante" in res.get("raison", "")
    # négatif aussi (pas d'indexation Python à rebours)
    assert corps.agir(manette=-1, delta=10)["ok"] is False
    assert client.writes == []
