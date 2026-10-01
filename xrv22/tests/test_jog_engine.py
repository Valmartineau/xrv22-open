"""Tests du JogEngine : orchestration de l'intégration jog côté serveur, sans
hardware ni asyncio. Faux contrôleur/registre/store injectés. La non-régression
de la *math* est verrouillée par test_jog_integrator (J1) ; ici on teste
l'orchestration (robots actifs, profil, écriture, miroir, thread-safety)."""
import time

from xrv22.core.jog_engine import JogEngine

DT = 0.05


class FakeCtrl:
    def __init__(self, positions):
        self._positions = dict(positions)
        self.control_owner = None
        self.comfort_vel = 120
        self.comfort_acc = 40
        self.direct_calls = []          # historique des set_direct_mode(vel, acc)
        self.written = []               # historique des write_positions_direct(targets)
        # soft-limits exposées comme dans robot_controller (self._profile.soft_limits)
        self._profile = type("P", (), {"soft_limits": {}})()

    def set_direct_mode(self, vel, acc):
        self.direct_calls.append((vel, acc))

    def read_positions(self):
        return dict(self._positions)

    def get_positions(self):
        # Source réelle utilisée par _tick_jog (cache), miroir de read_positions ici.
        return dict(self._positions)

    def write_positions_direct(self, targets, baseline=None):
        self.written.append(dict(targets))
        self.baselines = getattr(self, "baselines", [])
        self.baselines.append(dict(baseline) if baseline else None)
        return True


class FakeRegistry:
    def __init__(self, ctrls):
        self._ctrls = ctrls             # {rid: FakeCtrl}

    def get(self, rid):
        return self._ctrls.get(rid)


class FakeStore:
    def __init__(self):
        self.mirrors = []               # historique des (rid, positions)

    def set_positions(self, rid, positions):
        self.mirrors.append((rid, dict(positions)))


def _engine(ctrls):
    return JogEngine(registry=FakeRegistry(ctrls), store=FakeStore())


def test_acquire_cree_un_integrateur_actif():
    eng = _engine({"robot_1": FakeCtrl({1: 2000})})
    assert eng.active_rids() == []
    eng.acquire("robot_1", "pi")
    assert eng.active_rids() == ["robot_1"]


def test_release_retire_le_robot():
    eng = _engine({"robot_1": FakeCtrl({1: 2000})})
    eng.acquire("robot_1", "pi")
    eng.release("robot_1")
    assert eng.active_rids() == []


def test_acquire_robot_inconnu_ignore():
    eng = _engine({"robot_1": FakeCtrl({1: 2000})})
    eng.acquire("robot_42", "pi")
    assert eng.active_rids() == []


def test_acquire_reset_l_integrateur_a_chaque_prise():
    # Deux acquire successifs ne doivent pas conserver l'état du jog précédent
    # (seed propre = anti-à-coup réveil, garde-fou project_xrv22_reveil_coude).
    eng = _engine({"robot_1": FakeCtrl({1: 2000})})
    eng.acquire("robot_1", "pi")
    first = eng._integrators["robot_1"]
    eng.release("robot_1")
    eng.acquire("robot_1", "pi")
    assert eng._integrators["robot_1"] is not first


def test_tick_ecrit_les_targets_quand_velocite_non_nulle():
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {1: 1.0})
    eng._tick_once(DT)
    assert len(ctrl.written) == 1
    assert ctrl.written[0][1] > 2000          # axe 1 avance


def test_tick_robot_non_acquis_jamais_ecrit():
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    # pas d'acquire -> aucun intégrateur actif
    eng._tick_once(DT)
    assert ctrl.written == []


def test_tick_met_a_jour_le_miroir_store():
    ctrl = FakeCtrl({1: 2000, 2: 1500})
    store = FakeStore()
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=store)
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {1: 1.0})
    eng._tick_once(DT)
    assert len(store.mirrors) == 1
    rid, pos = store.mirrors[0]
    assert rid == "robot_1"
    assert set(pos) == {1, 2}                  # axes non joggés préservés (axe 2)


def test_tick_respecte_les_soft_limits_du_profil():
    ctrl = FakeCtrl({1: 2990})
    ctrl._profile.soft_limits = {1: (1070, 3000)}
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {1: 1.0})
    for _ in range(50):
        eng._tick_once(DT)
    # la cible interne sature à 3000 -> la dernière target écrite ne dépasse pas hi
    assert ctrl.written[-1][1] <= 3000


def test_acquire_ne_pose_pas_le_profil_court_mais_owner():
    # Le profil court NE doit PAS être posé à la prise de main : sinon les axes
    # lourds tenus (épaule/coude) ramollissent et s'affaissent. set_torque (appelé
    # avant par le Pi) a déjà posé le confort + Goal=Present (maintien ferme).
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    assert ctrl.direct_calls == []             # aucun changement de profil à l'acquire
    assert ctrl.control_owner == "pi"


def test_profil_court_pose_au_debut_du_jog_pas_a_l_acquire():
    # Le profil court (60,25) est posé au 1er tick ACTIF (front repos->actif),
    # pas re-posé pendant le jog, et re-posé (ré-agrippage des axes tenus) à
    # chaque nouveau mouvement après un arrêt. Reproduit l'ancien
    # _sync_direct_profile -> empêche l'affaissement de l'épaule/coude.
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    assert ctrl.direct_calls == []                     # rien à l'acquire
    eng.set_velocity("robot_1", {1: 1.0})
    eng._tick_once(DT)
    assert ctrl.direct_calls == [(60, 25)]            # posé au début du jog
    eng._tick_once(DT)                                # jog continue
    assert ctrl.direct_calls == [(60, 25)]            # pas re-posé pendant le jog
    eng.set_velocity("robot_1", {1: 0.0})            # relâche
    eng._tick_once(DT)
    eng._tick_once(DT)                               # repos confirmé
    eng.set_velocity("robot_1", {1: 1.0})           # nouveau mouvement
    eng._tick_once(DT)
    assert ctrl.direct_calls == [(60, 25), (60, 25)]  # ré-agrippé au nouveau jog


def test_release_restaure_profil_confort_et_libere():
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    eng.release("robot_1")
    assert ctrl.direct_calls[-1] == (120, 40)  # comfort_vel/comfort_acc du FakeCtrl
    assert ctrl.control_owner is None


import threading as _threading


def test_set_velocity_ignore_si_non_acquis():
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.set_velocity("robot_1", {1: 1.0})     # pas d'acquire -> ignoré
    eng._tick_once(DT)
    assert ctrl.written == []


def test_set_velocity_isole_par_robot():
    c1, c2 = FakeCtrl({1: 2000}), FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"r1": c1, "r2": c2}), store=FakeStore())
    eng.acquire("r1", "pi")
    eng.acquire("r2", "pi")
    eng.set_velocity("r1", {1: 1.0})          # r2 reste au repos
    eng._tick_once(DT)
    assert len(c1.written) == 1
    # Maintien teach-pendant : r2 (acquis -> prime_hold) TIENT sa pose à chaque
    # tick, figé sur son présent (2000) — il n'est pas piloté par la vélocité de
    # r1 (isolation par robot préservée).
    assert len(c2.written) == 1
    assert c2.written[-1] == {1: 2000}


def test_set_velocity_concurrent_ne_casse_pas_le_tick():
    # set_velocity (thread Tk) en parallèle de _tick_once (worker) : pas de
    # "dict changed size during iteration" ni de crash.
    # axes 1-5 seedés : les axes spammés 2+(i%4) (vél 0.5 constante) sont
    # inscriptibles -> ≥1 écriture par tick de façon déterministe, tout en
    # gardant la croissance de _vel qui stresse l'itération (le vrai point).
    ctrl = FakeCtrl({1: 2000, 2: 2000, 3: 2000, 4: 2000, 5: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    stop = _threading.Event()

    def spam():
        i = 0
        while not stop.is_set():
            eng.set_velocity("robot_1", {1: (i % 3) - 1, 2 + (i % 4): 0.5})
            i += 1

    t = _threading.Thread(target=spam)
    t.start()
    try:
        for _ in range(200):
            eng._tick_once(DT)
    finally:
        stop.set()
        t.join()
    assert len(ctrl.written) >= 1              # a tourné sans exception


def test_abandon_retire_l_integrateur_sans_toucher_owner_ni_profil():
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    calls_after_acquire = len(ctrl.direct_calls)
    # Un autre canal (web) prend la main : on simule l'owner web.
    ctrl.control_owner = "web"
    eng.abandon("robot_1")
    assert eng.active_rids() == []                       # plus piloté par l'engine
    assert ctrl.control_owner == "web"                   # owner NON écrasé
    assert len(ctrl.direct_calls) == calls_after_acquire  # profil NON retouché


def test_release_stoppe_le_pilotage_meme_si_velocite_active():
    # Garde-fou TORQUE OFF (cf. _toggle_torque) : après release, la boucle ne
    # doit plus écrire sur le robot, même si une vélocité était poussée.
    ctrl = FakeCtrl({1: 2000})
    eng = JogEngine(registry=FakeRegistry({"robot_1": ctrl}), store=FakeStore())
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {1: 1.0})
    eng._tick_once(DT)
    assert len(ctrl.written) == 1            # piloté tant qu'acquis
    eng.release("robot_1")
    eng._tick_once(DT)                        # plus d'intégrateur -> rien
    eng._tick_once(DT)
    assert len(ctrl.written) == 1            # aucune écriture supplémentaire


def test_start_stop_cycle_de_vie():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {5: 1.0})
    eng.start()
    time.sleep(0.2)
    eng.stop()
    assert ctrl.written, "le thread aurait du ecrire au moins une fois"
    assert eng._thread is None or not eng._thread.is_alive()


def test_dead_man_dans_le_tick():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "pi")
    eng.set_velocity("robot_1", {5: 1.0})
    eng._tick_once(0.05)                          # 1er tick : ecrit (intention fraiche)
    assert len(ctrl.written) >= 1
    eng._diag_force_now = eng._now() + 1.0        # simule l'absence de rafraichissement
    eng._tick_once(0.05)                          # axe expire -> dernier write (arret)
    eng._tick_once(0.05)
    n2 = len(ctrl.written)
    eng._tick_once(0.05)
    assert len(ctrl.written) == n2                # l'ecriture s'est arretee


# ---------------------------------------------------------------------------
# Task 4 : set_target + heartbeat (canal web cote moteur)
# ---------------------------------------------------------------------------

def test_set_target_delegue_a_l_integrateur():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "web")
    eng.set_target("robot_1", {5: 2000})
    eng._tick_once(0.05)
    assert ctrl.written, "set_target aurait du produire une ecriture"


def test_heartbeat_rafraichit_le_dead_man():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "web")
    eng.set_target("robot_1", {5: 2000})
    eng._tick_once(0.05)
    eng._diag_force_now = eng._now() + 0.30
    eng.heartbeat("robot_1")
    n = len(ctrl.written)
    eng._tick_once(0.05)
    assert len(ctrl.written) > n                  # toujours pilote (heartbeat a nourri)


def test_set_target_sans_acquire_noop():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.set_target("robot_1", {5: 2000})         # pas acquis
    eng._tick_once(0.05)
    assert not ctrl.written


# ---------------------------------------------------------------------------
# Task 5 : route_jog_message (jog.intent / jog.alive)
# ---------------------------------------------------------------------------

def test_route_jog_message_intent_et_alive():
    from xrv22.server.jog_ws import route_jog_message
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "web")
    route_jog_message(eng, {"type": "jog.intent", "rid": "robot_1", "axis": 5, "target": 2000})
    eng._tick_once(0.05)
    assert ctrl.written
    route_jog_message(eng, {"type": "jog.alive", "rid": "robot_1"})


def test_route_jog_message_robuste():
    from xrv22.server.jog_ws import route_jog_message
    eng = _engine({"robot_1": FakeCtrl({5: 1000})})
    route_jog_message(eng, {"type": "inconnu"})           # ignore
    route_jog_message(eng, {"garbage": True})             # ignore
    route_jog_message(eng, {"type": "jog.intent"})        # champs manquants -> ignore
    # aucun raise attendu


# ---------------------------------------------------------------------------
# Task 1 J4 : front profil-court declenche aussi en mode cible (has_intent)
# ---------------------------------------------------------------------------

def test_front_profil_court_en_mode_cible():
    ctrl = FakeCtrl({5: 1000})
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "web")              # acquire ne pose PAS le profil
    assert (60, 25) not in ctrl.direct_calls
    eng.set_target("robot_1", {5: 2000})
    eng._tick_once(0.05)                        # 1er tick avec cible -> front
    assert (60, 25) in ctrl.direct_calls       # set_direct_mode(60,25) pose


class BlockOnceCtrl(FakeCtrl):
    """Accepte tant que la cible reste <= seuil, rejette au-delà (simule une
    surface de collision à `seuil`)."""
    def __init__(self, positions, seuil):
        super().__init__(positions)
        self.seuil = seuil

    def write_positions_direct(self, targets, baseline=None):
        self.baselines = getattr(self, "baselines", [])
        self.baselines.append(dict(baseline) if baseline else None)
        if any(v > self.seuil for v in targets.values()):
            return False                           # bloqué (au-delà de la surface)
        self.written.append(dict(targets))
        return True


def test_write_rejete_pas_de_fuite_de_la_cible_interne():
    # Pousser CONTRE une surface (writes rejetés au-delà du seuil) : la cible
    # interne ne « fuit » pas — elle reste sous le seuil (pile au contact),
    # grâce à snapshot/restore. Le baseline est bien transmis au contrôleur.
    ctrl = BlockOnceCtrl({1: 2000}, seuil=2060)
    eng = _engine({"robot_1": ctrl})
    eng.acquire("robot_1", "pi")
    for _ in range(20):
        eng.set_velocity("robot_1", {1: 1.0})      # pousse vers le + (dead-man frais)
        eng._tick_once(DT)
    jog = eng._integrators["robot_1"]
    assert jog._jog_pos[1] <= 2060 + 1             # AUCUNE fuite au-delà de la surface
    assert ctrl.baselines[-1] is not None          # baseline transmis au garde-fou
