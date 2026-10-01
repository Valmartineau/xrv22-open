from eddy.cerveau.cerveau_jeu import CerveauJeu

class FakeChat:
    def __init__(self, reponse):
        self.reponse = reponse
        self.vu = None
    def repond(self, messages):
        self.vu = messages
        return self.reponse

def test_prochain_coup_parse_le_json():
    chat = FakeChat('{"pensee":"rond","action":"guess","phrase":"Une orange ?"}')
    cerveau = CerveauJeu(chat)
    coup = cerveau.prochain_coup("un objet rond et orange", historique=[])
    assert coup["action"] == "guess"
    assert coup["phrase"] == "Une orange ?"

def test_message_contient_system_description_et_historique():
    chat = FakeChat('{"pensee":"","action":"ask_clue","phrase":"Plus grand ?"}')
    cerveau = CerveauJeu(chat)
    cerveau.prochain_coup("un fruit orange",
                          historique=[{"role": "eddy", "texte": "Une balle ?"},
                                      {"role": "joueur", "texte": "non, ça se mange"}])
    msgs = chat.vu
    assert msgs[0]["role"] == "system"
    joint = " ".join(m["content"] for m in msgs)
    assert "un fruit orange" in joint           # la description perçue
    assert "Une balle ?" in joint               # l'historique
    assert "ça se mange" in joint
    assert "json" in joint.lower()              # le contrat de réponse rappelé
