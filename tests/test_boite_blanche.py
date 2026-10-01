"""La boîte blanche : un client Ollama (Mistral) NU et ISOLÉ.

Propriété centrale : on n'injecte AUCUN contexte MiCHEL (pas de vault/RAG, pas
de system prompt d'identité). Le client envoie exactement les messages qu'on lui
donne (graine + carnet + observation) — sa seule mémoire est le carnet, géré au
dessus. L'appel HTTP est injecté → testable sans Ollama.
"""
from incarne.boucle.boite_blanche import BoiteBlanche


def test_repond_envoie_le_payload_et_rend_le_contenu():
    captured = {}

    def fake_post(url, body):
        captured["url"] = url
        captured["body"] = body
        return {"message": {"role": "assistant", "content": "  salut  "}, "done": True}

    bb = BoiteBlanche(model="mistral:latest", http_post=fake_post)
    out = bb.repond([{"role": "user", "content": "qui es-tu ?"}])

    assert out == "salut"  # trim
    assert captured["url"].endswith("/api/chat")
    assert captured["body"]["model"] == "mistral:latest"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"] == [{"role": "user", "content": "qui es-tu ?"}]


def test_isolee_aucun_contexte_michel_injecte():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"message": {"content": "x"}}

    bb = BoiteBlanche(model="m", http_post=fake_post)
    msgs = [{"role": "user", "content": "graine + carnet"}]
    bb.repond(msgs)

    roles = [m["role"] for m in captured["body"]["messages"]]
    assert "system" not in roles  # aucune identité/contexte injecté
    assert captured["body"]["messages"] == msgs  # exactement ce qu'on a fourni


def test_temperature_passee_en_options_ollama():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"message": {"content": "x"}}

    bb = BoiteBlanche(model="m", temperature=2.0, http_post=fake_post)
    bb.repond([{"role": "user", "content": "go"}])
    assert captured["body"]["options"]["temperature"] == 2.0


def test_sans_temperature_pas_de_cle_temperature():
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"message": {"content": "x"}}

    bb = BoiteBlanche(model="m", http_post=fake_post)
    bb.repond([{"role": "user", "content": "go"}])
    # options existe (num_predict), mais pas de température imposée
    assert "temperature" not in captured["body"].get("options", {})


def test_genere_borne_par_num_predict():
    """La génération est bornée (num_predict) : à temp 2.0 le 24b peut partir en
    sortie interminable → recv timeout → run mort. On borne pour rester rapide."""
    captured = {}

    def fake_post(url, body):
        captured["body"] = body
        return {"message": {"content": "x"}}

    bb = BoiteBlanche(model="m", temperature=2.0, http_post=fake_post)
    bb.repond([{"role": "user", "content": "go"}])
    assert captured["body"]["options"]["num_predict"] >= 1


# ── Résilience réseau (run long : survivre aux coupures de tunnel) ──

def test_repond_retente_sur_erreur_reseau_puis_reussit():
    """Un blip réseau (tunnel SSH qui tombe une seconde) ne doit PAS tuer le run :
    on retente quelques fois (le tunnel auto-reconnectant revient) puis on réussit."""
    appels = {"n": 0}

    def flaky_post(url, body):
        appels["n"] += 1
        if appels["n"] < 3:
            raise ConnectionResetError("tunnel down")  # OSError → erreur réseau
        return {"message": {"content": "  ok  "}}

    dodos = []
    bb = BoiteBlanche(model="m", http_post=flaky_post)
    out = bb.repond([{"role": "user", "content": "x"}], _attente=0.01, _dormir=dodos.append)

    assert out == "ok"
    assert appels["n"] == 3          # 2 échecs + 1 réussite
    assert len(dodos) == 2           # une attente avant chaque nouvel essai


def test_repond_leve_apres_max_essais():
    """Si le réseau ne revient jamais, on lève après le quota d'essais (pas de
    boucle infinie), pour que l'échec soit visible."""
    import pytest

    def always_fail(url, body):
        raise ConnectionResetError("down")

    bb = BoiteBlanche(model="m", http_post=always_fail)
    with pytest.raises(OSError):
        bb.repond([{"role": "user", "content": "x"}],
                  _essais=3, _attente=0, _dormir=lambda _: None)


def test_repond_ne_retente_pas_une_erreur_non_reseau():
    """Une erreur logique (ex. réponse malformée) ne doit pas être retentée en
    boucle : seules les erreurs réseau/OSError déclenchent le retry."""
    import pytest

    def bad_shape(url, body):
        return {"pas_de_message": True}  # KeyError sur out["message"]

    bb = BoiteBlanche(model="m", http_post=bad_shape)
    with pytest.raises(KeyError):
        bb.repond([{"role": "user", "content": "x"}], _dormir=lambda _: None)
