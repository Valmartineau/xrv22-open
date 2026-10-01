"""Garde-fou souveraineté (spec §6) : les clients réseau pointent en local par
défaut, et une partie jouée avec des doublures ne déclenche AUCUN appel réseau.
"""
from eddy.vision.vlm import VisionModel
from eddy.session import DevinetteSession
from eddy.carnet_parties import CarnetParties

def test_vision_par_defaut_en_local():
    assert VisionModel("m").host.startswith("http://localhost")

def test_partie_avec_doublures_ne_fait_aucun_appel_reseau(tmp_path, monkeypatch):
    import urllib.request as u
    def interdit(*a, **k):
        raise AssertionError("appel réseau interdit pendant une partie en doublures")
    monkeypatch.setattr(u, "urlopen", interdit)

    class Src:
        canal = "webcam"
        def capture(self): return b"img"
    class Vis:
        def decris(self, b, prompt=None): return "un objet"
    class Cer:
        def prochain_coup(self, d, h): return {"pensee":"","action":"win","phrase":"Gagné"}
    class Voi:
        def __init__(self): self.dit=[]
        def dis(self, t): self.dit.append(t)
        def ecoute(self): return "oui"

    sess = DevinetteSession(Src(), Vis(), Cer(), Voi(), CarnetParties(tmp_path/"p.jsonl"))
    assert sess.jouer_une_partie() == "win"   # aucun urlopen déclenché
