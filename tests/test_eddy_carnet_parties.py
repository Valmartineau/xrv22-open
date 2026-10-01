from eddy.carnet_parties import CarnetParties

def test_enregistre_et_relit(tmp_path):
    c = CarnetParties(tmp_path / "parties.jsonl")
    c.enregistre({"canal": "webcam", "issue": "win", "tours": 3})
    c.enregistre({"canal": "tablette", "issue": "give_up", "tours": 6})
    parties = c.parties()
    assert len(parties) == 2
    assert parties[0]["canal"] == "webcam"
    assert parties[1]["issue"] == "give_up"

def test_recap_resume_le_nombre_de_parties(tmp_path):
    c = CarnetParties(tmp_path / "parties.jsonl")
    c.enregistre({"canal": "webcam", "issue": "win", "tours": 2})
    r = c.recap()
    assert "1" in r and "win" in r

def test_parties_vide_si_fichier_absent(tmp_path):
    assert CarnetParties(tmp_path / "rien.jsonl").parties() == []
