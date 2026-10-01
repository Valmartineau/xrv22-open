"""La couche anticollision boîtes dans RobotSafetyManager.check_collision_only :
- flag par robot (ON par défaut, OFF ⇒ laisse passer),
- pose de repli ⇒ rejet avec libellé,
- fail-open si le moteur est indisponible.

Tous les chemins de pilotage (Direct web/Pi, jog, suites) passent par
check_collision_only — tester ici couvre donc l'ensemble.
"""
import json
from pathlib import Path

import pytest

from xrv22.core import box_collision
from xrv22.core.box_collision import REF_UP, BoxCollisionEngine
from xrv22.core.safety_manager import RobotSafetyManager

CALIB_PATH = Path(__file__).parent.parent / "web" / "public" / "calibration.json"

REST = {1: REF_UP[1], 2: REF_UP[2], 4: REF_UP[4], 5: REF_UP[5], 6: REF_UP[6]}
# Repli du poignet à -100° : auto-collision Wrist×Forearm (cf. test_box_collision).
FOLD = {**REST, 5: REF_UP[5] - round(100 * 4096 / 360)}


@pytest.fixture()
def mgr(monkeypatch):
    # Moteur initialisé sur la calibration committée (le singleton par défaut
    # pointe sur server/static, artefact de build absent du repo).
    eng = BoxCollisionEngine(CALIB_PATH)
    eng.init()
    assert eng.available
    monkeypatch.setattr(box_collision, "engine", eng)
    return RobotSafetyManager("robot_test", [1, 2, 3, 4, 5, 6, 7])


def test_flag_on_par_defaut(mgr):
    assert mgr.anticollision_enabled is True


def test_pose_sure_passe(mgr):
    ok, reason, *_ = mgr.check_collision_only(REST, REST, broadcast=False)
    assert ok, reason


def test_repli_poignet_rejete(mgr):
    ok, reason, zone_id, zone_name, _ = mgr.check_collision_only(
        {5: FOLD[5]}, REST, broadcast=False)
    assert not ok
    assert "Wrist" in reason and "Forearm" in reason
    assert zone_id == "anticollision"


def test_flag_off_laisse_passer(mgr):
    mgr.anticollision_enabled = False
    ok, *_ = mgr.check_collision_only({5: FOLD[5]}, REST, broadcast=False)
    assert ok


# ── Garde-fou conscient du recul (le bras doit pouvoir ressortir) ─

DEEP = {**REST, 5: REF_UP[5] - round(120 * 4096 / 360)}     # repli profond
SHALLOW = {**REST, 5: REF_UP[5] - round(96 * 4096 / 360)}   # repli léger (en contact)


def test_recul_autorise_depuis_collision(mgr):
    # Pilotage interactif (retreat_aware). Bras DANS la collision (repli profond) ;
    # cible = moins replié → AUTORISÉ même si elle touche encore (sinon piégé).
    ok, *_ = mgr.check_collision_only({5: SHALLOW[5]}, DEEP, broadcast=False,
                                      retreat_aware=True)
    assert ok


def test_approfondir_depuis_collision_bloque(mgr):
    # Déjà en contact léger ; cible = plus replié → AGGRAVE → bloqué.
    ok, reason, *_ = mgr.check_collision_only({5: DEEP[5]}, SHALLOW, broadcast=False,
                                              retreat_aware=True)
    assert not ok
    assert "Forearm" in reason or "Wrist" in reason


def test_entrer_depuis_clair_bloque(mgr):
    # Pose actuelle sûre ; cible entre en collision → bloqué.
    ok, *_ = mgr.check_collision_only({5: DEEP[5]}, REST, broadcast=False,
                                      retreat_aware=True)
    assert not ok


def test_maintien_au_contact_autorise(mgr):
    # Cible = pose actuelle (en contact) : pénétration égale → autorisé (tenir).
    ok, *_ = mgr.check_collision_only({5: SHALLOW[5]}, SHALLOW, broadcast=False,
                                      retreat_aware=True)
    assert ok


def test_mode_absolu_bloque_toute_collision(mgr):
    # Sans retreat_aware (défaut : check statique / goto), une cible en collision
    # est bloquée MÊME en venant d'une pose plus profonde — pas de notion de recul.
    ok_abs, *_ = mgr.check_collision_only({5: SHALLOW[5]}, DEEP, broadcast=False)
    assert not ok_abs                                   # absolu : bloqué
    ok_ret, *_ = mgr.check_collision_only({5: SHALLOW[5]}, DEEP, broadcast=False,
                                          retreat_aware=True)
    assert ok_ret                                       # interactif : autorisé


def test_fail_open_moteur_indisponible(monkeypatch, tmp_path):
    eng = BoxCollisionEngine(tmp_path / "absent.json")
    eng.init()
    monkeypatch.setattr(box_collision, "engine", eng)
    mgr = RobotSafetyManager("robot_test2", [1, 2, 3, 4, 5, 6, 7])
    ok, *_ = mgr.check_collision_only({5: FOLD[5]}, REST, broadcast=False)
    assert ok  # fail-open : pas de calibration ⇒ pas de blocage
