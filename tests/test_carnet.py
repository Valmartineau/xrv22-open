"""Le carnet : seule mémoire de la boîte blanche. Une ligne par note, persisté,
relu à chaque pas. C'est aussi l'objet qu'on lit, nous, pour voir sa pensée se
construire (spec §7)."""
from incarne.boucle.carnet import Carnet


def test_ajoute_et_relit_dans_l_ordre(tmp_path):
    c = Carnet(tmp_path / "carnet.txt")
    c.ajoute("pas 1 : j'ai bougé une manette")
    c.ajoute("pas 2 : un nombre a changé")
    assert c.lignes() == ["pas 1 : j'ai bougé une manette",
                          "pas 2 : un nombre a changé"]


def test_persiste_entre_instances(tmp_path):
    p = tmp_path / "carnet.txt"
    Carnet(p).ajoute("souvenir")
    assert Carnet(p).lignes() == ["souvenir"]


def test_carnet_vierge_est_vide(tmp_path):
    assert Carnet(tmp_path / "neuf.txt").lignes() == []
