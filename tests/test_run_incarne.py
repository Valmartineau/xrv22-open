"""Câblage du premier run incarné réel : perception tablette + garde-fou stylet.

`construire_corps_incarne(client, rid, stylet, ...)` assemble un CorpsRxv22 dont
la perception (signaux) vient du StyletLecteur et dont le garde-fou de pression
lit la même tablette. Stylet et client injectés (faux) → testable sans matériel.
Voir docs/recherche/journal-collaboration.md (étape 3).
"""
import json
from incarne.run_incarne import construire_corps_incarne, ecrire_journal, payload_du_pas, rejouer
from incarne.run_incarne import charger_position_protocole


def test_payload_du_pas_assemble_les_champs():
    positions = {1: 2048, 2: 2048, 3: 2048, 4: 2050, 5: 2079, 6: 2048, 7: 1649}
    observation = {"manettes": [2048, 2048, 2048, 2050, 2079, 2048],
                   "signaux": [8412, 5310, 47]}
    decision = {"pensee": "et si je poussais ?", "note": "manette 4 -> sig 3 monte",
                "action": {"manette": 4, "delta": -2}}
    resultat = {"ok": True, "raison": "exécutée"}

    p = payload_du_pas(5, positions, observation, decision, resultat, plafond=500)

    assert p["pas"] == 5
    assert p["positions"] == {"1": 2048, "2": 2048, "3": 2048, "4": 2050,
                              "5": 2079, "6": 2048, "7": 1649}
    assert p["manettes"] == [2048, 2048, 2048, 2050, 2079, 2048]
    assert p["signaux"] == [8412, 5310, 47]
    assert p["pression"] == 47
    assert p["plafond"] == 500
    assert p["manette_active"] == 4 and p["delta"] == -2
    assert p["pensee"] == "et si je poussais ?"
    assert p["note"] == "manette 4 -> sig 3 monte"
    assert p["bloque"] is False
    assert "ts" not in p


def test_payload_du_pas_reflete_le_garde_fou_bloque():
    p = payload_du_pas(
        2, {5: 2080}, {"manettes": [2080], "signaux": [1, 2, 520]},
        {"pensee": "", "note": "", "action": {"manette": 4, "delta": -3}},
        {"ok": False, "bloque": "plafond_pression", "pression": 520}, plafond=500)
    assert p["bloque"] is True
    assert p["pression"] == 520


def test_ecrire_journal_append_une_ligne_json_par_pas(tmp_path):
    f = tmp_path / "eddy.jsonl"
    ecrire_journal({"pas": 1, "note": "é accentué"}, f)
    ecrire_journal({"pas": 2, "note": "b"}, f)
    lignes = f.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 2
    assert json.loads(lignes[0])["pas"] == 1
    assert json.loads(lignes[1])["note"] == "b"
    assert "é accentué" in lignes[0]


def test_rejouer_emet_les_pas_dans_l_ordre_au_rythme_des_ts():
    lignes = [
        '{"pas": 1, "ts": 10.0}',
        '',
        '{"pas": 2, "ts": 10.5}',
        '{"pas": 3, "ts": 11.5}',
    ]
    publies, dodos = [], []
    rejouer(lignes, publier=publies.append, dormir=dodos.append)

    assert [p["pas"] for p in publies] == [1, 2, 3]
    assert dodos == [0.5, 1.0]


def test_charger_position_protocole(tmp_path):
    import json
    f = tmp_path / "pos.json"
    f.write_text(json.dumps({"robot": "robot_1",
                             "positions": {"1": 2011, "5": 2109, "7": 2108}}))
    rid, positions = charger_position_protocole(f)
    assert rid == "robot_1"
    assert positions == {1: 2011, 5: 2109, 7: 2108}   # clés en int


class FakeClient:
    def __init__(self, positions):
        self._pos = positions
        self.writes = []

    def get_robot(self, rid):
        return {"positions": dict(self._pos), "torque_enabled": True,
                "connected": True}

    def write_positions(self, rid, cible):
        self.writes.append((rid, cible))
        return {"ok": True, "positions": cible}

    def set_torque(self, rid, enable):
        return {"ok": True}


class FakeStylet:
    def __init__(self, lecture):
        self._lec = lecture

    def lecture(self):
        return dict(self._lec)


def _corps(client, stylet):
    return construire_corps_incarne(
        client, "r", stylet, axes=[1, 2, 3, 4, 5, 6], delta_cap=30,
        plafond_pression=650, dormir=lambda _s: None)


def test_la_perception_vient_du_stylet():
    client = FakeClient({"1": 0, "2": 0, "3": 0, "4": 0, "5": 2080, "6": 0})
    stylet = FakeStylet({"etat": "CONTACT", "x": 11, "y": 22, "p": 480})
    corps = _corps(client, stylet)
    assert corps.observe()["signaux"] == [11, 22, 480]


def test_le_garde_fou_annule_si_pression_depasse():
    client = FakeClient({"1": 0, "2": 0, "3": 0, "4": 0, "5": 2080, "6": 0})
    stylet = FakeStylet({"etat": "CONTACT", "x": 11, "y": 22, "p": 700})
    corps = _corps(client, stylet)
    res = corps.agir(manette=4, delta=10)         # manette 4 → axe 5 ; 2080→2090 puis annulé
    assert client.writes == [("r", {5: 2090}), ("r", {5: 2080})]
    assert res["ok"] is False


def test_sous_le_plafond_le_geste_passe():
    client = FakeClient({"1": 0, "2": 0, "3": 0, "4": 0, "5": 2080, "6": 0})
    stylet = FakeStylet({"etat": "CONTACT", "x": 11, "y": 22, "p": 300})
    corps = _corps(client, stylet)
    corps.agir(manette=4, delta=10)
    assert client.writes == [("r", {5: 2090})]
