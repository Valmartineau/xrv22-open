"""Tests pour xrv22/robots/robot_controller.py en mode simulation.

Cible :
  - Fonctions pures : _apply_coupling, calculate_auto_duration
  - Init : safety/serial/profile en place
  - connect/disconnect en sim
  - Torque ON/OFF transitions
  - move() validations (positions hors limites, duree, sim succes)
  - set_motion_params clamp
  - safe_home requiert home_machine + home_work
  - read/write positions en sim
"""
import pytest

from xrv22.core.safety_manager import RobotState, safety
from xrv22.core.state_store import store
from xrv22.robots.robot_controller import (
    RobotController, _apply_coupling, calculate_auto_duration,
)
from xrv22.robots.robot_profiles import profiles
from xrv22.services.event_bus import bus


MOTOR_IDS = [1, 2, 3, 4, 5, 6, 7]


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def reset_globals():
    """Reset bus + store + safety + profiles entre tests."""
    bus.clear()
    store._robots.clear()  # type: ignore[attr-defined]
    safety._managers.clear()  # type: ignore[attr-defined]
    profiles._profiles.clear()  # type: ignore[attr-defined]
    yield
    bus.clear()
    store._robots.clear()  # type: ignore[attr-defined]
    safety._managers.clear()  # type: ignore[attr-defined]
    profiles._profiles.clear()  # type: ignore[attr-defined]


@pytest.fixture
def ctrl(reset_globals):
    """RobotController en mode simulation, connecte sur 'sim_port'."""
    c = RobotController("robot_test", MOTOR_IDS, simulation=True)
    c.connect("sim_port")
    yield c
    c.disconnect()


# ── _apply_coupling (fonction pure) ──────────────────────────────────

class TestApplyCoupling:

    def test_disabled_returns_unchanged(self, reset_globals):
        positions = {1: 1000, 2: 2000, 3: 3000}
        # library.hardware.coupling absent ou enabled=False : identite
        out = _apply_coupling(positions)
        assert out == positions

    def test_no_axis_2_returns_unchanged(self, reset_globals, monkeypatch):
        """Sans axe 2 dans la commande, le couplage ne s'applique pas."""
        from xrv22.library.library_manager import library
        monkeypatch.setattr(library, "get_hardware",
                             lambda: {"coupling": {"enabled": True, "ratio": 1.0}})
        positions = {1: 1000, 5: 2500}
        out = _apply_coupling(positions)
        assert out == positions

    def test_enabled_computes_slave_from_master(self, reset_globals, monkeypatch):
        """Couplage actif : pos_3 = center + ratio*(pos_2 - center) + offset."""
        from xrv22.library.library_manager import library
        monkeypatch.setattr(library, "get_hardware", lambda: {
            "coupling": {
                "enabled": True, "ratio": 1.0, "offset": 0,
                "center": 2048, "invert": False,
            }})
        out = _apply_coupling({2: 3048})
        # ratio=1, offset=0, center=2048 : axis 3 = 2048 + (3048-2048) = 3048
        assert out[3] == 3048
        assert out[2] == 3048

    def test_invert_inverses_direction(self, reset_globals, monkeypatch):
        from xrv22.library.library_manager import library
        monkeypatch.setattr(library, "get_hardware", lambda: {
            "coupling": {
                "enabled": True, "ratio": 1.0, "offset": 0,
                "center": 2048, "invert": True,
            }})
        out = _apply_coupling({2: 3048})
        # invert=True : axis 3 = 2048 - (3048-2048) = 1048
        assert out[3] == 1048

    def test_relative_coupling_no_snap_at_reference(self, reset_globals,
                                                    monkeypatch):
        """Couplage RELATIF à la prise de main : avec une référence
        (ref2, ref3) capturée au réveil, axe3 vaut ref3 quand axe2 == ref2
        (aucun saut), puis suit le delta de l'axe2 → l'offset mécanique réel
        des servos solidaires est préservé (plus d'à-coup du coude)."""
        from xrv22.library.library_manager import library
        monkeypatch.setattr(library, "get_hardware", lambda: {
            "coupling": {"enabled": True, "ratio": 1.0, "offset": 0,
                         "center": 2048, "invert": False}})
        ref = (2000, 1500)  # coude (axe3=1500) flué sous l'épaule (axe2=2000)
        # axe2 inchangé → axe3 reste à sa position réelle, PAS de saut vers 2000
        assert _apply_coupling({2: 2000}, ref)[3] == 1500
        # axe2 +100 → axe3 suit de +100 (offset mécanique 500 préservé)
        assert _apply_coupling({2: 2100}, ref)[3] == 1600
        # axe2 -300 → axe3 = 1500 - 300 = 1200
        assert _apply_coupling({2: 1700}, ref)[3] == 1200


# ── calculate_auto_duration (fonction pure) ──────────────────────────

class TestCalculateAutoDuration:

    def test_no_delta_returns_min_floor(self, reset_globals):
        # Pas de mouvement → duree minimum 0.5s
        assert calculate_auto_duration({1: 2048}, {1: 2048}) == 0.5

    def test_clamped_minimum_0_3s(self, reset_globals):
        # Petit delta → clampe a 0.3s minimum
        d = calculate_auto_duration({1: 2050}, {1: 2048})
        assert d >= 0.3

    def test_clamped_maximum_10s(self, reset_globals):
        # Gros delta → clampe a 10s maximum
        d = calculate_auto_duration({1: 4000}, {1: 0})
        assert d <= 10.0


# ── Init ────────────────────────────────────────────────────────────

class TestInit:

    def test_initial_state_idle(self, reset_globals):
        c = RobotController("robot_test", MOTOR_IDS, simulation=True)
        assert c.state == RobotState.IDLE
        assert c.simulation is True

    def test_profile_auto_registered(self, reset_globals):
        RobotController("robot_test", MOTOR_IDS, simulation=True)
        assert profiles.get("robot_test") is not None

    def test_motor_ids_stored(self, reset_globals):
        c = RobotController("robot_test", [1, 3, 5], simulation=True)
        assert c.motor_ids == [1, 3, 5]


# ── connect / disconnect ────────────────────────────────────────────

class TestConnect:

    def test_connect_sim_succeeds(self, reset_globals):
        c = RobotController("robot_test", MOTOR_IDS, simulation=True)
        assert c.connect("sim_port") is True
        assert c.is_connected is True

    def test_connect_publishes_store_connected(self, reset_globals):
        c = RobotController("robot_test", MOTOR_IDS, simulation=True)
        c.connect("sim_port")
        snap = store.get_robot("robot_test")
        assert snap is not None
        assert snap.connected is True
        assert snap.port == "sim_port"

    def test_disconnect_clears_state(self, reset_globals):
        c = RobotController("robot_test", MOTOR_IDS, simulation=True)
        c.connect("sim_port")
        c.disconnect()
        assert c.is_connected is False


# ── Torque ──────────────────────────────────────────────────────────

class TestTorque:

    def test_set_torque_true_transitions_to_ready(self, ctrl):
        assert ctrl.set_torque(True) is True
        assert ctrl.state == RobotState.READY
        assert ctrl.torque_enabled is True

    def test_set_torque_false_transitions_to_idle(self, ctrl):
        ctrl.set_torque(True)
        assert ctrl.set_torque(False) is True
        assert ctrl.state == RobotState.IDLE

    def test_set_torque_when_disconnected_refused(self, reset_globals):
        c = RobotController("robot_test", MOTOR_IDS, simulation=True)
        # Pas de connect : non connecte
        assert c.set_torque(True) is False


# ── move() — validations ────────────────────────────────────────────

class TestMove:

    def test_move_rejects_position_out_of_soft_limits(self, ctrl):
        # Soft limit moteur 1 par defaut : varie selon defaults, mais 50000 hors bornes
        ctrl.set_motor_limit(1, 1000, 3000)
        ok, msg = ctrl.move({1: 5000}, 1.0)
        assert ok is False
        assert "hors limites" in msg.lower()

    def test_move_rejects_duration_too_short(self, ctrl):
        # min_duration_s = 0.15 dans le profil par defaut
        ok, msg = ctrl.move({1: 2048}, 0.05)
        assert ok is False
        assert "min" in msg.lower() or "duree" in msg.lower() or "durée" in msg.lower()

    def test_move_rejects_duration_too_long(self, ctrl):
        # max_duration_s = 20.0 dans le profil par defaut
        ok, msg = ctrl.move({1: 2048}, 30.0)
        assert ok is False
        assert "max" in msg.lower()

    def test_move_sim_valid_succeeds_and_transitions_running(self, ctrl):
        # Donne au safety une position courante (sinon validate_move se base sur {})
        ctrl.update_positions({mid: 2048 for mid in MOTOR_IDS})
        ok, _ = ctrl.move({1: 2100}, 1.0)
        assert ok is True
        assert ctrl.state == RobotState.RUNNING


# ── set_motion_params ──────────────────────────────────────────────

class TestMotionParams:

    def test_clamp_velocity_within_bounds(self, ctrl):
        ctrl.set_motion_params(hz=60, velocity=99999, acceleration=10)
        assert ctrl.comfort_vel == 500  # clamp max

    def test_clamp_velocity_minimum(self, ctrl):
        ctrl.set_motion_params(hz=60, velocity=0, acceleration=10)
        assert ctrl.comfort_vel == 10  # clamp min

    def test_home_duration_clamped(self, ctrl):
        ctrl.set_motion_params(hz=60, velocity=100, acceleration=20,
                                home_duration=0.1)
        assert ctrl.home_duration == 0.5  # clamp min


# ── set_motor_limit ─────────────────────────────────────────────────

class TestSetMotorLimit:

    def test_propagates_to_profile_and_safety(self, ctrl):
        ctrl.set_motor_limit(1, 500, 3500)
        assert ctrl.profile.soft_limits[1] == (500, 3500)
        # Safety doit avoir la meme valeur
        assert ctrl._safety.soft_limits[1] == (500, 3500)


# ── home / safe_home ────────────────────────────────────────────────

class TestHome:

    def test_set_home_machine_records(self, ctrl):
        positions = {mid: 2000 for mid in MOTOR_IDS}
        ctrl.set_home_machine(positions)
        assert ctrl.home_machine == positions

    def test_set_home_work_records(self, ctrl):
        positions = {mid: 1500 for mid in MOTOR_IDS}
        ctrl.set_home_work(positions)
        assert ctrl.home_work == positions

    def test_safe_home_requires_home_machine(self, ctrl):
        ok, msg = ctrl.safe_home()
        assert ok is False
        assert "machine" in msg.lower()

    def test_safe_home_requires_home_work(self, ctrl):
        ctrl.set_home_machine({mid: 2000 for mid in MOTOR_IDS})
        ok, msg = ctrl.safe_home()
        assert ok is False
        assert "work" in msg.lower()

    def test_go_home_work_requires_home_work(self, ctrl):
        ok, msg = ctrl.go_home_work()
        assert ok is False
        assert "non défini" in msg.lower() or "non defini" in msg.lower()


class TestSetDirectMode:

    def test_aligns_goal_to_present_before_profile(self, reset_globals):
        """Anti-à-coup démarrage jog : set_direct_mode lit Present, le réécrit
        en Goal (alignement) AVANT d'appliquer le profil court, pour qu'un écart
        Goal−Present ne soit pas exécuté brutalement par le profil rapide."""
        class RecSerial:
            connected = True
            torque_enabled = True

            def __init__(self):
                self.calls = []

            def read_positions(self):
                self.calls.append(("read_positions", None))
                return {1: 2048, 2: 1149, 3: 1175}

            def write_positions(self, p):
                self.calls.append(("write_positions", dict(p)))
                return True

            def set_profile(self, vel, acc):
                self.calls.append(("set_profile", (vel, acc)))

        c = RobotController("robot_test", [1, 2, 3], simulation=False)
        c._serial = RecSerial()
        c.set_direct_mode(60, 25)
        ops = [op for op, _ in c._serial.calls]
        assert "read_positions" in ops and "write_positions" in ops
        assert ops.index("read_positions") < ops.index("write_positions")
        assert ops.index("write_positions") < ops.index("set_profile")
        # Le Goal réécrit = la position physique lue (alignement exact).
        written = c._serial.calls[ops.index("write_positions")][1]
        assert written == {1: 2048, 2: 1149, 3: 1175}


# ── read/write positions ────────────────────────────────────────────

class TestReadWrite:

    def test_read_positions_after_connect_returns_defaults(self, ctrl):
        positions = ctrl.read_positions()
        # Le sim init a 2048 (centre)
        assert len(positions) == len(MOTOR_IDS)
        assert all(p == 2048 for p in positions.values())

    def test_write_positions_direct_updates_sim(self, ctrl):
        ctrl.write_positions_direct({1: 2500, 5: 1500})
        positions = ctrl.read_positions()
        assert positions[1] == 2500
        assert positions[5] == 1500

    def test_set_torque_captures_coupling_ref_from_present(self, ctrl):
        """Au réveil (OFF→ON), set_torque mémorise (present[2], present[3])
        comme référence de couplage relatif → base anti-saut du coude."""
        drooped = {1: 2048, 2: 2000, 3: 1500, 4: 2048,
                   5: 2048, 6: 2048, 7: 2048}
        ctrl._serial._sim_positions = dict(drooped)
        assert ctrl.set_torque(True) is True
        assert ctrl._coupling_ref == (2000, 1500)

    def test_jog_after_wakeup_does_not_snap_elbow(self, ctrl, monkeypatch):
        """Régression à-coup coude : couplage actif + coude affaissé. Le 1er
        write de jog qui tient l'axe 2 ne doit PAS ramener l'axe 3 sur l'axe 2
        (ancien bug formule absolue axe3=axe2)."""
        from xrv22.library.library_manager import library
        monkeypatch.setattr(library, "get_hardware", lambda: {
            "coupling": {"enabled": True, "ratio": 1.0, "offset": 0,
                         "center": 2048, "invert": False}})
        drooped = {1: 2048, 2: 2000, 3: 1500, 4: 2048,
                   5: 2048, 6: 2048, 7: 2048}
        ctrl._serial._sim_positions = dict(drooped)
        ctrl.set_torque(True)  # capture ref (2000, 1500)
        ctrl.write_positions_direct({2: 2000})  # on tient l'axe 2 sur place
        assert ctrl.read_positions()[3] == 1500  # coude reste à 1500, pas 2000

    def test_write_positions_direct_clamps_to_soft_limits(self, ctrl):
        """Défense en profondeur : le backend ne doit jamais écrire un Goal
        hors soft-limits, même si un client (jog/slider) envoie une valeur
        aberrante. C'est le chemin de pilotage le plus utilisé."""
        ctrl._profile.soft_limits[1] = (1000, 3000)
        ctrl.write_positions_direct({1: 5000})  # au-dessus du plafond
        assert ctrl.read_positions()[1] == 3000
        ctrl.write_positions_direct({1: 200})  # en-dessous du plancher
        assert ctrl.read_positions()[1] == 1000


# ── write_positions_direct met le store à jour (perception live torque ON) ──

class _RecSerial:
    """Série factice : write renvoie un OK configurable, read une pose fixe."""
    connected = True
    torque_enabled = True

    def __init__(self, write_ok=True):
        self._ok = write_ok
        self.written = []

    def write_positions(self, p):
        self.written.append(dict(p))
        return self._ok

    def read_positions(self):
        return {1: 2048, 2: 2048, 3: 2048}


class TestWritePositionsDirectUpdatesStore:
    """Sans poll (torque ON), c'est l'écriture commandée qui doit tenir le store
    à jour — sinon la perception du run incarné reste figée (le bras n'avance pas
    car sa base est périmée). On met à jour le store UNIQUEMENT si l'écriture
    série réussit (ni sur blocage collision, ni sur échec série)."""

    def _ctrl(self, reset_globals, write_ok=True):
        c = RobotController("robot_test", [1, 2, 3], simulation=False)
        c._serial = _RecSerial(write_ok)
        c.update_positions({1: 2048, 2: 2048, 3: 2048})  # base connue
        return c

    def test_succes_avance_le_store_et_preserve_les_autres_axes(
            self, reset_globals, monkeypatch):
        c = self._ctrl(reset_globals, write_ok=True)
        monkeypatch.setattr(c._safety, "check_collision_only",
                            lambda *a, **k: (True, None, None, None, None))
        ok = c.write_positions_direct({1: 2500})
        assert ok is True
        assert c.get_positions()[1] == 2500     # base avancée → accumulation possible
        assert c.get_positions()[2] == 2048     # axes non écrits préservés (merge)

    def test_collision_bloquee_ne_touche_pas_le_store(
            self, reset_globals, monkeypatch):
        c = self._ctrl(reset_globals, write_ok=True)
        monkeypatch.setattr(c._safety, "check_collision_only",
                            lambda *a, **k: (False, None, None, None, None))
        ok = c.write_positions_direct({1: 2500})
        assert ok is False
        assert c.get_positions()[1] == 2048     # rien écrit → store inchangé

    def test_echec_serie_ne_touche_pas_le_store(
            self, reset_globals, monkeypatch):
        c = self._ctrl(reset_globals, write_ok=False)
        monkeypatch.setattr(c._safety, "check_collision_only",
                            lambda *a, **k: (True, None, None, None, None))
        ok = c.write_positions_direct({1: 2500})
        assert ok is False
        assert c.get_positions()[1] == 2048     # write série KO → pas de maj
