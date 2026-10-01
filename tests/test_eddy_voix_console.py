from eddy.voix.console import VoixConsole

def test_dis_ecrit_et_ecoute_lit():
    sorties = []
    reponses = iter(["non, plus petit", "oui !"])
    voix = VoixConsole(entree=lambda _prompt="": next(reponses),
                       sortie=sorties.append)
    voix.dis("Un éléphant ?")
    assert voix.ecoute() == "non, plus petit"
    assert voix.ecoute() == "oui !"
    assert any("Un éléphant ?" in s for s in sorties)
