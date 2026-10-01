"""La boucle : agir → percevoir → noter, autour de la boîte blanche.

On vérifie l'assemblage du message (graine + nombres BRUTS non étiquetés +
carnet, en UN seul message user → isolation), et qu'un pas exécute l'action
parsée sur le corps puis écrit la note au carnet. Corps et boîte injectés (faux)
→ tout testable sans robot ni Ollama.
"""
from incarne.boucle.boucle import Boucle
from incarne.boucle.carnet import Carnet


class FakeBoite:
    def __init__(self, reponse):
        self.reponse = reponse
        self.vu = None

    def repond(self, messages):
        self.vu = messages
        return self.reponse


class EchoCorps:
    def __init__(self):
        self.appels = []
        self.etat = {"manettes": [1000, 2000, 1500], "signaux": [0, 0, 0, 0]}

    def observe(self):
        return self.etat

    def agir(self, manette, delta):
        self.appels.append((manette, delta))
        return {"ok": True, "raison": "exécutée"}


def test_construire_messages_un_seul_user_sans_system(tmp_path):
    boucle = Boucle(FakeBoite(""), Carnet(tmp_path / "c.txt"), EchoCorps(),
                    graine="GRAINE-TEST")
    msgs = boucle.construire_messages(
        {"manettes": [1000, 2000], "signaux": [0, 0, 0, 0]}, derniere_action=None)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    contenu = msgs[0]["content"]
    assert "GRAINE-TEST" in contenu
    assert "1000" in contenu and "2000" in contenu
    assert "json" in contenu.lower()  # le contrat de réponse
    # Régression : un petit modèle recopie les gabarits entre chevrons comme
    # valeurs (ex. delta="->") → on montre un EXEMPLE numérique concret, pas
    # de placeholder `<...>`.
    assert "<" not in contenu


def test_construire_messages_inclut_le_carnet(tmp_path):
    carnet = Carnet(tmp_path / "c.txt")
    carnet.ajoute("note précédente")
    boucle = Boucle(FakeBoite(""), carnet, EchoCorps(), graine="g")
    msgs = boucle.construire_messages({"manettes": [0], "signaux": []}, None)
    assert "note précédente" in msgs[0]["content"]


def test_message_humain_injecte_et_propose_champ_reponse(tmp_path):
    """Dialogue-en-mouvement : si une personne parle, son message est injecté
    dans le prompt et Eddy se voit proposer un champ 'reponse'."""
    boucle = Boucle(FakeBoite(""), Carnet(tmp_path / "c.txt"), EchoCorps(), graine="g")
    contenu = boucle.construire_messages(
        {"manettes": [0], "signaux": []}, None,
        message_humain="Bonjour Eddy, tu me sens ?")[0]["content"]
    assert "Bonjour Eddy, tu me sens ?" in contenu
    assert "reponse" in contenu
    assert "<" not in contenu  # toujours pas de placeholder à recopier


def test_sans_message_humain_run_isole_inchange(tmp_path):
    """Rétro-compat : sans personne, aucun champ 'reponse' (run isolé pur)."""
    boucle = Boucle(FakeBoite(""), Carnet(tmp_path / "c.txt"), EchoCorps(), graine="g")
    contenu = boucle.construire_messages(
        {"manettes": [0], "signaux": []}, None)[0]["content"]
    assert "reponse" not in contenu


def test_pas_transmet_le_message_humain_et_rend_la_reponse(tmp_path):
    boite = FakeBoite('{"pensee":"p","action":{"manette":0,"delta":1},'
                      '"note":"n","reponse":"Oui, bonjour !"}')
    boucle = Boucle(boite, Carnet(tmp_path / "c.txt"), EchoCorps(), graine="g")
    resultat = boucle.pas(message_humain="Bonjour")
    assert "Bonjour" in boite.vu[0]["content"]      # message passé au LLM
    assert resultat["reponse"] == "Oui, bonjour !"  # réponse remontée


def test_pas_execute_l_action_et_ecrit_la_note(tmp_path):
    carnet = Carnet(tmp_path / "c.txt")
    boite = FakeBoite(
        '{"pensee":"j essaie","action":{"manette":1,"delta":40},"note":"j ai poussé"}')
    corps = EchoCorps()
    boucle = Boucle(boite, carnet, corps, graine="g")

    resultat = boucle.pas()

    assert resultat["action"] == {"manette": 1, "delta": 40}
    assert corps.appels == [(1, 40)]              # l'action a été exécutée
    assert carnet.lignes()[-1].endswith("j ai poussé")  # la note est au carnet
