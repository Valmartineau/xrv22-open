from eddy.session import DevinetteSession
from eddy.carnet_parties import CarnetParties

class FakeSource:
    canal = "webcam"
    def capture(self):
        return b"image"

class FakeVision:
    def decris(self, image_bytes, prompt=None):
        return "un objet rond et orange"

class FakeCerveau:
    """Rend les coups d'une liste, dans l'ordre."""
    def __init__(self, coups):
        self.coups = list(coups)
        self.vu = []
    def prochain_coup(self, description, historique):
        self.vu.append((description, list(historique)))
        return self.coups.pop(0)

class FakeVoix:
    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.dit = []
    def dis(self, texte):
        self.dit.append(texte)
    def ecoute(self):
        return self.reponses.pop(0)

def _coup(action, phrase):
    return {"pensee": "", "action": action, "phrase": phrase}

def test_partie_gagnee_journalise_et_termine(tmp_path):
    cerveau = FakeCerveau([_coup("guess", "Une orange ?"),
                           _coup("win", "Gagné, une orange !")])
    voix = FakeVoix(["oui c'est ça"])
    carnet = CarnetParties(tmp_path / "p.jsonl")
    sess = DevinetteSession(FakeSource(), FakeVision(), cerveau, voix, carnet,
                            max_tours=6)

    issue = sess.jouer_une_partie()

    assert issue == "win"
    assert "Une orange ?" in voix.dit and "Gagné, une orange !" in voix.dit
    p = carnet.parties()[0]
    assert p["canal"] == "webcam"
    assert p["issue"] == "win"
    assert p["tours"] == 1                       # 1 guess avant le win
    assert p["description"] == "un objet rond et orange"

def test_abandon_au_max_de_tours(tmp_path):
    # Le cerveau propose sans cesse ; la garde MAX doit forcer give_up.
    cerveau = FakeCerveau([_coup("guess", f"Essai {i} ?") for i in range(10)])
    voix = FakeVoix(["non"] * 10)
    carnet = CarnetParties(tmp_path / "p.jsonl")
    sess = DevinetteSession(FakeSource(), FakeVision(), cerveau, voix, carnet,
                            max_tours=3)

    issue = sess.jouer_une_partie()

    assert issue == "give_up"
    assert carnet.parties()[0]["issue"] == "give_up"
    assert carnet.parties()[0]["tours"] == 3     # stoppé à la garde

def test_ask_clue_puis_guess_puis_win(tmp_path):
    cerveau = FakeCerveau([_coup("ask_clue", "C'est vivant ?"),
                           _coup("guess", "Un chat ?"),
                           _coup("win", "Bravo !")])
    voix = FakeVoix(["non", "oui un chat"])
    carnet = CarnetParties(tmp_path / "p.jsonl")
    sess = DevinetteSession(FakeSource(), FakeVision(), cerveau, voix, carnet,
                            max_tours=6)

    assert sess.jouer_une_partie() == "win"
    # L'historique transmis au 2e coup contient le 1er échange.
    _desc, hist = cerveau.vu[1]
    assert any("C'est vivant ?" in t["texte"] for t in hist)
    assert any(t["texte"] == "non" for t in hist)


def test_exception_de_perception_est_journalisee_sans_planter(tmp_path):
    class VisionKO:
        def decris(self, image_bytes, prompt=None):
            raise RuntimeError("VLM injoignable")
    voix = FakeVoix([])
    carnet = CarnetParties(tmp_path / "p.jsonl")
    sess = DevinetteSession(FakeSource(), VisionKO(),
                            FakeCerveau([]), voix, carnet)
    assert sess.jouer_une_partie() == "erreur"
    p = carnet.parties()[0]
    assert p["issue"] == "erreur"
    assert "VLM injoignable" in p["erreur"]
    assert any("souci technique" in t for t in voix.dit)


def test_reponse_vide_declenche_une_relance_puis_recoit(tmp_path):
    cerveau = FakeCerveau([_coup("guess", "Un chat ?"), _coup("win", "Bravo !")])
    voix = FakeVoix(["", "oui un chat"])   # 1re écoute vide -> relance -> 2e ok
    carnet = CarnetParties(tmp_path / "p.jsonl")
    sess = DevinetteSession(FakeSource(), FakeVision(), cerveau, voix, carnet)
    assert sess.jouer_une_partie() == "win"
    assert any("répéter" in t for t in voix.dit)
    _desc, hist = cerveau.vu[1]
    assert any(t["texte"] == "oui un chat" for t in hist)
