"""Boîte aux lettres personne→run (dialogue-en-mouvement)."""
from incarne.messagerie import deposer, vider


def test_deposer_puis_vider_rend_dans_l_ordre_et_vide(tmp_path):
    f = tmp_path / "inbox.txt"
    deposer("Bonjour", f)
    deposer("tu me sens ?", f)
    assert vider(f) == ["Bonjour", "tu me sens ?"]
    assert vider(f) == []  # vidé après lecture


def test_vider_boite_absente_rend_liste_vide(tmp_path):
    assert vider(tmp_path / "rien.txt") == []


def test_deposer_aplatit_les_sauts_de_ligne_et_ignore_le_vide(tmp_path):
    f = tmp_path / "inbox.txt"
    deposer("ligne1\nligne2", f)
    deposer("   ", f)  # vide → ignoré
    assert vider(f) == ["ligne1 ligne2"]
