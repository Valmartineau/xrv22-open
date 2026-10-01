"""Parser tolérant de la réponse de la boîte blanche.

Le contrat (spec §6) : pensée libre + action {manette, delta} + note. Un LLM
emballe souvent ce JSON dans de la prose ou un bloc ```json → on l'extrait. Clés
sans accent (robuste) mais on tolère « pensée ».
"""
import pytest

from incarne.boucle.parse_reponse import parse_reponse


def test_json_pur():
    txt = '{"pensee":"je tente un geste","action":{"manette":2,"delta":-15},"note":"rien"}'
    r = parse_reponse(txt)
    assert r["pensee"] == "je tente un geste"
    assert r["action"] == {"manette": 2, "delta": -15}
    assert r["note"] == "rien"
    assert r["reponse"] == ""  # pas d'humain → pas de réponse


def test_extrait_reponse_a_l_humain_quand_presente():
    """Dialogue-en-mouvement : Eddy peut répondre à la personne via un champ
    optionnel 'reponse' (en plus de son action). Absent = chaîne vide."""
    txt = ('{"pensee":"x","action":{"manette":1,"delta":2},"note":"n",'
           '"reponse":"Bonjour, oui je sens quelque chose ici."}')
    r = parse_reponse(txt)
    assert r["reponse"] == "Bonjour, oui je sens quelque chose ici."
    assert r["action"] == {"manette": 1, "delta": 2}  # l'action reste extraite


def test_json_dans_la_prose_et_un_bloc_fence():
    txt = (
        "D'accord, je réfléchis.\n"
        "```json\n"
        '{"pensée": "et si je poussais ?", "action": {"manette": 0, "delta": 10}, '
        '"note": "tentative 1"}\n'
        "```\n"
        "Voilà ma décision."
    )
    r = parse_reponse(txt)
    assert r["pensee"] == "et si je poussais ?"  # accent toléré
    assert r["action"] == {"manette": 0, "delta": 10}


def test_sans_json_leve_une_erreur():
    with pytest.raises(ValueError):
        parse_reponse("Je ne sais pas quoi faire, je n'ai pas de corps.")


# Robustesse aux sorties aberrantes (température élevée) : manette/delta non
# entiers, ou action mal formée → ValueError (rattrapé par la boucle), JAMAIS
# de TypeError qui ferait crasher le run.

def test_manette_liste_leve_valueerror():
    with pytest.raises(ValueError):
        parse_reponse('{"action": {"manette": [4, 5], "delta": 1}, "note": ""}')


def test_delta_non_numerique_leve_valueerror():
    with pytest.raises(ValueError):
        parse_reponse('{"action": {"manette": 0, "delta": "abc"}, "note": ""}')


def test_action_pas_un_dict_leve_valueerror():
    with pytest.raises(ValueError):
        parse_reponse('{"action": [1, 2], "note": ""}')
