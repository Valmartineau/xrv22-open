"""Go-to DESSIN en douceur, en 2 paliers (position de travail → pose de dessin).

`goto_dessin_doux(ctrl, depart)` calque le schéma éprouvé de `safe_home` :
`move(home_work, hd, skip_limits=True)` → attente → `move(cible, hd)`. Le profil
temporel de `move()` lisse le mouvement (pas d'à-coup, contrairement à
`write_positions_direct` qui pose le goal d'un coup). L'axe 7 (pince tenant le
stylet) est TOUJOURS exclu — règle inviolable de la boîte blanche incarnée.
Controller et sleep injectés (faux) → testable sans matériel.
"""
from incarne.goto_doux import goto_dessin_doux


class _FauxCtrl:
    """Controller minimal qui enregistre les appels move()."""

    def __init__(self, home_work, home_duration=2.0, resultats=None):
        self.home_work = dict(home_work)
        self.home_duration = home_duration
        self.moves = []                       # [(positions, duration_s, skip_limits)]
        self._resultats = list(resultats or [])

    def move(self, positions, duration_s, skip_limits=False):
        self.moves.append((dict(positions), duration_s, skip_limits))
        if self._resultats:
            return self._resultats.pop(0)
        return True, "OK"


def test_passe_par_home_work_puis_depart_avec_attentes():
    ctrl = _FauxCtrl({1: 10, 2: 20, 7: 99}, home_duration=2.0)
    dodos = []

    ok, msg = goto_dessin_doux(ctrl, {1: 100, 2: 200, 7: 88}, dormir=dodos.append)

    assert ok is True and msg == "OK"
    # Palier 1 : home_work (skip_limits) ; palier 2 : départ.
    assert len(ctrl.moves) == 2
    (hw_pos, hw_dur, hw_skip), (cible_pos, cible_dur, cible_skip) = ctrl.moves
    assert hw_pos == {1: 10, 2: 20} and hw_dur == 2.0 and hw_skip is True
    # Pose de dessin = pose calibrée de confiance → skip_limits aussi (faux-positif
    # de collision sur la posture repliée, cf. goto_doux).
    assert cible_pos == {1: 100, 2: 200} and cible_dur == 2.0 and cible_skip is True
    # On attend la fin de chaque palier avant d'enchaîner.
    assert dodos == [2.2, 2.2]


def test_exclut_toujours_l_axe_7():
    ctrl = _FauxCtrl({1: 10, 7: 99})
    goto_dessin_doux(ctrl, {1: 100, 7: 88}, dormir=lambda _: None)
    for positions, _dur, _skip in ctrl.moves:
        assert 7 not in positions


def test_stoppe_si_palier_travail_echoue():
    ctrl = _FauxCtrl({1: 10}, resultats=[(False, "hors limites")])
    dodos = []

    ok, msg = goto_dessin_doux(ctrl, {1: 100}, dormir=dodos.append)

    assert ok is False and "travail" in msg
    assert len(ctrl.moves) == 1          # le palier dessin n'est PAS lancé
    assert dodos == []                   # pas d'attente après l'échec


def test_echec_si_home_work_absent():
    ctrl = _FauxCtrl({})
    ok, msg = goto_dessin_doux(ctrl, {1: 100}, dormir=lambda _: None)
    assert ok is False and "home_work" in msg
    assert ctrl.moves == []


def test_duree_personnalisee_remplace_home_duration():
    ctrl = _FauxCtrl({1: 10}, home_duration=2.0)
    dodos = []
    goto_dessin_doux(ctrl, {1: 100}, duree=4.0, dormir=dodos.append)
    assert all(dur == 4.0 for _pos, dur, _skip in ctrl.moves)
    assert dodos == [4.2, 4.2]
