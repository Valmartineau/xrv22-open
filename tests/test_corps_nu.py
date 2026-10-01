"""La couche « corps nu » : des manettes anonymes par-dessus l'API RXV22.

Règles dures (spec §5) :
- l'axe 7 (pince, tient le stylet) est EXCLU — jamais exposé ni bougé ;
- δ borné par un cap de sécurité ;
- une cible = position courante de l'axe + δ borné (écriture absolue).

Logique pure (pas de réseau) : la lecture/écriture est injectée → testable seule.
"""
import pytest

from incarne.corps.corps_nu import CorpsNu


def test_axe_7_jamais_expose_comme_manette():
    corps = CorpsNu(axes=[1, 2, 3, 4, 5, 6, 7], delta_cap=30)
    axes_exposes = [corps.manette_axis(i) for i in range(corps.nb_manettes)]
    assert 7 not in axes_exposes
    assert axes_exposes == [1, 2, 3, 4, 5, 6]


def test_delta_borne_au_cap_dans_les_deux_sens():
    corps = CorpsNu(axes=[1, 2], delta_cap=30)
    assert corps.borne_delta(100) == 30
    assert corps.borne_delta(-100) == -30
    assert corps.borne_delta(12) == 12
    assert corps.borne_delta(-12) == -12


def test_cible_ajoute_le_delta_borne_a_la_position_courante():
    corps = CorpsNu(axes=[1, 2, 3], delta_cap=30)
    # manette 1 → axe 2 ; position courante 2000 ; delta +50 borné à +30.
    cible = corps.cible(manette=1, delta=50, positions={1: 1000, 2: 2000, 3: 1500})
    assert cible == {2: 2030}


def test_cible_manette_inconnue_rejetee():
    corps = CorpsNu(axes=[1, 2, 3], delta_cap=30)
    with pytest.raises(IndexError):
        corps.cible(manette=9, delta=10, positions={1: 0, 2: 0, 3: 0})
