"""Tests de caracterisation de JogIntegrator : la math du jog extraite de
ScreenPilotage._tick_jog, portee a l'identique. Ces tests verrouillent la
non-regression de la sensation du jog. Cf. spec jog-engine, jalon J1."""
import pytest

from xrv22.core.jog_integrator import JogIntegrator

DT = 0.05  # 20 Hz, comme _jog_period_ms


def test_set_velocity_and_reset():
    jog = JogIntegrator()
    jog.set_velocity(1, 0.5, now=0.0)
    assert jog._vel == {1: 0.5}
    # seed manuel pour verifier que reset vide tout
    jog._jog_pos[1] = 2048.0
    jog.reset()
    assert jog._vel == {}
    assert jog._jog_pos == {}
    assert jog._jog_ramp == {}
    assert jog._active_axes == set()


def test_seed_sur_position_reelle_au_premier_step():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    # _jog_pos seede sur 2000 puis avance (rampe partielle au 1er tick)
    assert jog._jog_pos[1] > 2000.0


def test_pas_de_reseed_si_deja_initialise():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    pos_apres_1 = jog._jog_pos[1]
    # current different : ne doit PAS re-seeder, doit continuer d'avancer
    jog.step(DT, current={1: 9999}, soft_limits={1: (0, 4095)})
    assert jog._jog_pos[1] > pos_apres_1
    assert jog._jog_pos[1] < 3000  # n'a pas saute sur 9999


def test_seed_skip_si_axe_absent_de_current():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    targets = jog.step(DT, current={}, soft_limits={1: (0, 4095)})
    assert 1 not in jog._jog_pos
    assert targets == {}


def test_rampe_monte_puis_sature_a_1():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    assert jog._jog_ramp[1] == pytest.approx(DT / JogIntegrator.JOG_RAMP_S)
    # apres assez de ticks, la rampe sature a 1.0
    for _ in range(10):
        jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    assert jog._jog_ramp[1] == 1.0


def test_avance_regime_etabli_exact():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    # saturer la rampe (4 ticks suffisent : 4*0.05/0.18 > 1)
    for _ in range(5):
        jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    pos_avant = jog._jog_pos[1]
    jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    # a rampe=1 : avance = vel * max_speed * dt = 1.0 * 750 * 0.05 = 37.5
    assert jog._jog_pos[1] - pos_avant == pytest.approx(750 * DT)


def test_clamp_borne_haute():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    # seede pres de la borne haute, beaucoup de ticks -> doit saturer a hi
    for _ in range(50):
        jog.step(DT, current={1: 2990}, soft_limits={1: (1070, 3000)})
    assert jog._jog_pos[1] == 3000.0


def test_clamp_borne_basse():
    jog = JogIntegrator()
    jog.set_velocity(1, -1.0, now=0.0)
    for _ in range(50):
        jog.step(DT, current={1: 1080}, soft_limits={1: (1070, 3000)})
    assert jog._jog_pos[1] == 1070.0


def test_lead_ajoute_a_la_cible_ecrite_en_regime():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    for _ in range(5):  # saturer la rampe (v_eff = 1.0)
        jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    targets = jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    # lead = v_eff * max_speed * lead_s = 1.0 * 750 * 0.060 = 45
    expected = round(jog._jog_pos[1] + 750 * JogIntegrator.JOG_LEAD_S)
    assert targets[1] == expected
    assert targets[1] > round(jog._jog_pos[1])  # la cible ecrite devance _jog_pos


def test_axe_au_repos_jamais_actif_non_ecrit():
    jog = JogIntegrator()
    jog.set_velocity(1, 0.0, now=0.0)  # repos, jamais actif
    targets = jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    assert 1 not in targets


def test_axe_relache_ecrit_une_derniere_fois_a_l_arret():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    for _ in range(5):  # axe actif -> entre dans _active_axes
        jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    pos_fin = jog._jog_pos[1]
    # relache : vel 0 mais etait actif au tick precedent -> ecrit une fois
    jog.set_velocity(1, 0.0, now=0.0)
    targets = jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    assert targets[1] == round(pos_fin)        # arret pile, lead=0
    assert jog._jog_ramp[1] == 0.0             # rampe remise a zero
    # tick suivant : toujours au repos -> MAINTIEN ACTIF (on continue d'ecrire
    # Goal=_jog_pos chaque tick, comme le mode cible, pour que le servo reste
    # asservi et ne back-drive pas sous gravite). present peut avoir derive,
    # mais la cible commandee reste figee sur la derniere position joggee.
    targets2 = jog.step(DT, current={1: 2050}, soft_limits={1: (0, 4095)})
    assert targets2[1] == round(pos_fin)       # toujours ecrit, fige sur jog_pos


def test_axe_lourd_maintenu_pendant_jog_d_un_autre_axe():
    """Régression décrochage 2/3/4 : on jogge l'axe 4 (coude), on le relâche,
    puis on jogge l'axe 5 (poignet) plusieurs ticks. L'axe 4 doit RESTER écrit
    (figé sur _jog_pos) à chaque tick — sinon le servo cesse d'être asservi et
    le coude back-drive sous gravité (bug observé en trace Pi : present dérive
    de +140 ticks alors que goal n'était plus écrit)."""
    jog = JogIntegrator()
    # 1) jog du coude (axe 4) puis stabilisation de la rampe
    jog.set_velocity(4, 1.0, now=0.0)
    for _ in range(5):
        jog.step(DT, current={4: 2600, 5: 2000}, soft_limits={})
    hold4 = round(jog._jog_pos[4])
    # 2) relâche l'axe 4, commence à jogger l'axe 5 (poignet)
    jog.set_velocity(4, 0.0, now=0.0)
    jog.set_velocity(5, 1.0, now=0.0)
    # 3) plusieurs ticks de jog axe 5 : present de l'axe 4 dérive (gravité),
    #    mais la cible commandée doit rester figée et TOUJOURS écrite.
    for k in range(6):
        present4 = 2600 + 20 * (k + 1)         # simulate gravity back-drive
        targets = jog.step(DT, current={4: present4, 5: 2000},
                           soft_limits={})
        assert 4 in targets, f"axe 4 non maintenu au tick {k}"
        assert targets[4] == hold4, "cible axe 4 doit rester figee sur _jog_pos"
        assert 5 in targets                     # l'axe 5 bouge bien


def test_prime_hold_fige_tous_les_axes_malgre_derive_present():
    """Maintien teach-pendant : après prime_hold, chaque axe est réécrit figé
    sur sa position d'origine à chaque tick, même si le present dérive (gravité)
    et même sans aucune intention de jog."""
    jog = JogIntegrator()
    jog.prime_hold({2: 1100, 4: 2600, 5: 2000}, now=0.0)
    for k in range(5):
        # present dérive (back-drive simulé) mais la cible doit rester figée
        targets = jog.step(DT, current={2: 1100 - 5 * k, 4: 2600 + 5 * k,
                                        5: 2000}, soft_limits={})
        assert targets[2] == 1100
        assert targets[4] == 2600
        assert targets[5] == 2000


def test_prime_hold_puis_jog_un_axe_les_autres_restent_verrouilles():
    """Le scénario utilisateur : on prend la main (prime_hold), on bouge UN axe
    (5 = poignet) et les axes lourds 2/4 jamais touchés restent verrouillés."""
    jog = JogIntegrator()
    jog.prime_hold({2: 1100, 4: 2600, 5: 2000}, now=0.0)
    jog.set_velocity(5, 1.0, now=0.0)            # on jogge le poignet
    for k in range(6):
        targets = jog.step(DT, current={2: 1100 - 3 * k, 4: 2600 + 3 * k,
                                        5: 2000}, soft_limits={})
        assert targets[2] == 1100, f"épaule a flué au tick {k}"
        assert targets[4] == 2600, f"coude a flué au tick {k}"
        assert 5 in targets
    assert jog._jog_pos[5] > 2000                # l'axe 5 a bien avancé


def test_axe_lourd_2_avance_a_vitesse_reduite():
    jog = JogIntegrator()
    jog.set_velocity(2, 1.0, now=0.0)  # axe 2 = Epaule (lourd, plafonne a 400)
    for _ in range(5):        # saturer la rampe
        jog.step(DT, current={2: 2000}, soft_limits={2: (0, 4095)})
    pos_avant = jog._jog_pos[2]
    jog.step(DT, current={2: 2000}, soft_limits={2: (0, 4095)})
    # avance = vel * 400 * dt (pas 750)
    assert jog._jog_pos[2] - pos_avant == pytest.approx(400 * DT)


def test_axe_normal_garde_750():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    for _ in range(5):
        jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    pos_avant = jog._jog_pos[1]
    jog.step(DT, current={1: 2000}, soft_limits={1: (0, 4095)})
    assert jog._jog_pos[1] - pos_avant == pytest.approx(750 * DT)


def test_mirror_fusionne_jog_pos_sur_current():
    jog = JogIntegrator()
    jog.set_velocity(1, 1.0, now=0.0)
    jog.step(DT, current={1: 2000, 2: 1500, 3: 1500}, soft_limits={1: (0, 4095)})
    mirror = jog.mirror({1: 2000, 2: 1500, 3: 1500})
    # axe 1 jogge -> remplace par _jog_pos (sans le lead) ; les autres intacts
    assert mirror[1] == round(jog._jog_pos[1])
    assert mirror[2] == 1500
    assert mirror[3] == 1500
    assert set(mirror) == {1, 2, 3}


# ── Jalon J3 : dead-man (horodatage + expire) ─────────────────────────────────

def test_set_velocity_horodate_et_expire_remet_a_zero():
    jog = JogIntegrator()
    jog.set_velocity(5, 1.0, now=0.0)
    jog.expire(now=0.1, timeout=0.25)          # 0.1s < 0.25 -> pas d'expiration
    assert jog._vel[5] == 1.0
    jog.expire(now=0.30, timeout=0.25)         # 0.30s > 0.25 -> expire
    assert 5 not in jog._vel                    # dead-man : axe RETIRE de _vel

def test_expire_est_par_axe():
    jog = JogIntegrator()
    jog.set_velocity(5, 1.0, now=0.0)
    jog.set_velocity(6, 1.0, now=0.20)         # axe 6 plus recent
    jog.expire(now=0.30, timeout=0.25)         # 5 perime (0.30), 6 frais (0.10)
    assert 5 not in jog._vel                    # dead-man : axe RETIRE de _vel
    assert jog._vel[6] == 1.0

def test_reset_efface_les_horodatages():
    jog = JogIntegrator()
    jog.set_velocity(5, 1.0, now=0.0)
    jog.reset()
    assert jog._seen == {}


# ── Jalon J3 : mode cible (set_target + rampe dans step) ─────────────────────

def test_set_target_rampe_vers_la_cible():
    jog = JogIntegrator()
    jog.set_target(5, 2000, now=0.0)
    cur = {5: 1000}
    pos_precedent = 1000
    for _ in range(60):                          # 60 * 50ms = 3s, large
        out = jog.step(0.05, cur, {5: (0, 4095)})
        assert 5 in out
        assert out[5] >= pos_precedent           # progresse vers le haut (lead inclus)
        pos_precedent = jog._jog_pos[5]
    assert abs(jog._jog_pos[5] - 2000) < 1.0      # arrive a la cible

def test_set_target_clamp_soft_limits():
    jog = JogIntegrator()
    jog.set_target(5, 9999, now=0.0)             # au-dela de la butee
    for _ in range(200):
        jog.step(0.05, {5: 1000}, {5: (0, 3000)})
    assert jog._jog_pos[5] <= 3000

def test_expire_stoppe_la_rampe_cible():
    jog = JogIntegrator()
    jog.set_target(5, 2000, now=0.0)
    jog.step(0.05, {5: 1000}, {5: (0, 4095)})
    jog.expire(now=0.30, timeout=0.25)           # cible perime
    fige = jog._jog_pos[5]
    out = jog.step(0.05, {5: 1000}, {5: (0, 4095)})
    assert 5 not in out                          # plus ecrit (cible retiree)
    assert jog._jog_pos[5] == fige               # ne bouge plus


# ── Jalon J4 : has_intent (velocite OU cible) ────────────────────────────────

def test_has_intent():
    jog = JogIntegrator()
    assert jog.has_intent() is False
    jog.set_velocity(5, 1.0, now=0.0)
    assert jog.has_intent() is True
    jog.set_velocity(5, 0.0, now=0.0)
    assert jog.has_intent() is False
    jog.set_target(3, 2000, now=0.0)
    assert jog.has_intent() is True
    jog.expire(now=1.0, timeout=0.25)          # cible perimee -> droppee
    assert jog.has_intent() is False


def test_refresh_seen_nourrit_le_dead_man():
    jog = JogIntegrator()
    jog.set_velocity(5, 1.0, now=0.0)
    jog.set_velocity(6, 1.0, now=0.0)
    jog.refresh_seen(now=5.0)
    jog.expire(now=5.1, timeout=0.25)          # 0.1s depuis le refresh -> pas d'expiration
    assert jog._vel[5] == 1.0
    assert jog._vel[6] == 1.0


def test_expire_nettoie_seen():
    jog = JogIntegrator()
    jog.set_velocity(5, 1.0, now=0.0)
    jog.expire(now=1.0, timeout=0.25)
    assert 5 not in jog._seen                  # horodatage retire (anti-accumulation)
    assert 5 not in jog._vel                    # dead-man : axe RETIRE de _vel


def test_snapshot_restore_annule_l_avance():
    # snapshot AVANT step, restore APRÈS si l'écriture est rejetée → _jog_pos
    # revient à l'état pré-step (la dernière position acceptée).
    jog = JogIntegrator()
    jog.set_velocity(5, -1.0, now=0.0)
    snap = jog.snapshot()                        # vide (rien encore intégré)
    jog.step(DT, current={5: 1000}, soft_limits={5: (0, 4095)})
    assert jog._jog_pos[5] != 1000.0            # a bougé
    jog.restore(snap)                            # write rejeté → annule l'avance
    assert 5 not in jog._jog_pos                # revenu à l'état pré-step


def test_restore_ne_claque_pas_vers_un_depart_perime():
    # Cœur du bug « recul violent » : le present passé à step est figé à la
    # position de DÉPART (cache non rafraîchi pendant le jog). La cible interne
    # ne doit PAS y retomber sur rejet — elle reste pile au contact, et le recul
    # repart en douceur.
    jog = JogIntegrator()
    stale = {5: 2000}                            # cache figé au départ
    jog.set_velocity(5, 1.0, now=0.0)
    for _ in range(12):                          # avance librement (acceptés)
        jog.step(DT, current=stale, soft_limits={5: (0, 4095)})
    contact = jog._jog_pos[5]
    assert contact > 2060                        # loin du départ 2000
    for _ in range(12):                          # maintenant rejetés
        snap = jog.snapshot()
        jog.step(DT, current=stale, soft_limits={5: (0, 4095)})
        jog.restore(snap)                        # rejet → annule
    assert jog._jog_pos[5] == pytest.approx(contact, abs=1.0)  # PAS retombé à 2000
    jog.set_velocity(5, -1.0, now=1.0)           # inversion joystick
    targets = jog.step(DT, current=stale, soft_limits={5: (0, 4095)})
    assert targets[5] < contact                  # recule depuis le contact
    assert contact - targets[5] < 60             # en douceur, pas un claquement
