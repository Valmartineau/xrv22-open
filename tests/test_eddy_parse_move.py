import pytest
from eddy.cerveau.parse_move import parse_move, ACTIONS

def test_parse_guess_pur():
    m = parse_move('{"pensee":"rond","action":"guess","phrase":"C\'est une balle ?"}')
    assert m == {"pensee": "rond", "action": "guess", "phrase": "C'est une balle ?"}

def test_parse_dans_de_la_prose():
    txt = "Voici mon coup :\n```json\n{\"pensee\":\"\",\"action\":\"win\",\"phrase\":\"Gagné !\"}\n```"
    m = parse_move(txt)
    assert m["action"] == "win"
    assert m["phrase"] == "Gagné !"

def test_action_inconnue_rejetee():
    with pytest.raises(ValueError):
        parse_move('{"pensee":"x","action":"danser","phrase":"y"}')

def test_pas_de_json_leve():
    with pytest.raises(ValueError):
        parse_move("aucune structure ici")

def test_phrase_manquante_leve():
    with pytest.raises(ValueError):
        parse_move('{"pensee":"x","action":"guess"}')

def test_actions_exposees():
    assert ACTIONS == {"guess", "ask_clue", "win", "give_up"}
