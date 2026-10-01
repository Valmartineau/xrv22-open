"""Tests pour xrv22/hardware/serial_manager.py — sim path uniquement.

Cible :
  - Init et etats de connexion
  - connect/disconnect en sim (pas de hardware)
  - Validation baudrate
  - set_torque sim
  - read/write positions sim (round-trip)
  - send_move sim met a jour les positions et publie sur le bus
  - read_hardware_errors retourne {} en sim
  - reboot_motor refuse en sim
  - set_profile no-op en sim
"""
import pytest

from xrv22.hardware.serial_manager import SerialManager
from xrv22.services.event_bus import bus


MOTOR_IDS = [1, 2, 3, 4, 5, 6, 7]
MOTOR_CENTER = 2048


@pytest.fixture
def reset_bus():
    bus.clear()
    yield
    bus.clear()


@pytest.fixture
def sm(reset_bus):
    """SerialManager en mode simulation."""
    s = SerialManager("robot_test", MOTOR_IDS, simulation=True)
    yield s
    if s.connected:
        s.disconnect()


# ── Init ────────────────────────────────────────────────────────────

class TestInit:

    def test_initial_not_connected(self, sm):
        assert sm.connected is False
        assert sm.torque_enabled is False
        assert sm.port_name == ""

    def test_sim_positions_initialized_at_center(self, sm):
        # Avant connect : sim_positions est deja initialise au centre 2048
        sm._connected = True  # forcer pour read_positions
        positions = sm.read_positions()
        assert all(p == MOTOR_CENTER for p in positions.values())
        assert set(positions.keys()) == set(MOTOR_IDS)


# ── connect / disconnect ────────────────────────────────────────────

class TestConnect:

    def test_connect_sim_succeeds(self, sm):
        assert sm.connect("sim_port") is True
        assert sm.connected is True
        assert sm.port_name == "sim_port"

    def test_connect_invalid_baudrate_refused(self, sm):
        # Baudrate hors BAUDRATE_DXL_VALID
        assert sm.connect("sim_port", baud=12345) is False
        assert sm.connected is False

    def test_connect_publishes_robot_connected(self, reset_bus):
        events = []
        bus.subscribe("robot.connected", lambda p: events.append(p))
        sm = SerialManager("robot_test", MOTOR_IDS, simulation=True)
        sm.connect("sim_port")
        assert len(events) == 1
        assert events[0]["robot_id"] == "robot_test"
        # Sim port prefixed with SIM:
        assert events[0]["port"].startswith("SIM:")

    def test_disconnect_publishes_event(self, sm):
        sm.connect("sim_port")
        events = []
        bus.subscribe("robot.disconnected", lambda p: events.append(p))
        sm.disconnect()
        assert sm.connected is False
        assert len(events) == 1

    def test_reconnect_disconnects_first(self, sm):
        """Une connexion sur un port deja ouvert doit faire un cleanup."""
        sm.connect("port_A")
        assert sm.connect("port_B") is True
        assert sm.port_name == "port_B"


# ── Torque ──────────────────────────────────────────────────────────

class TestTorque:

    def test_torque_when_disconnected_refused(self, sm):
        assert sm.set_torque(True) is False

    def test_torque_on_sim(self, sm):
        sm.connect("sim_port")
        assert sm.set_torque(True) is True
        assert sm.torque_enabled is True

    def test_torque_off_sim(self, sm):
        sm.connect("sim_port")
        sm.set_torque(True)
        assert sm.set_torque(False) is True
        assert sm.torque_enabled is False


# ── Positions sim (round-trip) ──────────────────────────────────────

class TestPositions:

    def test_write_then_read_returns_written(self, sm):
        sm.connect("sim_port")
        sm.write_positions({1: 1500, 5: 3000})
        positions = sm.read_positions()
        assert positions[1] == 1500
        assert positions[5] == 3000
        # Les autres restent au centre
        assert positions[2] == MOTOR_CENTER

    def test_write_publishes_serial_move_sent(self, sm):
        sm.connect("sim_port")
        events = []
        bus.subscribe("serial.move_sent", lambda p: events.append(p))
        sm.write_positions({1: 2500})
        assert len(events) == 1
        assert events[0]["robot_id"] == "robot_test"
        assert events[0]["positions"] == {1: 2500}

    def test_write_when_disconnected_refused(self, sm):
        # Pas de connect : doit retourner False
        assert sm.write_positions({1: 2500}) is False

    def test_read_when_disconnected_returns_empty(self, sm):
        assert sm.read_positions() == {}


# ── send_move ───────────────────────────────────────────────────────

class TestSendMove:

    def test_send_move_sim_updates_positions(self, sm):
        sm.connect("sim_port")
        sm.send_move({1: 3000, 7: 2200}, duration_ms=1000)
        positions = sm.read_positions()
        assert positions[1] == 3000
        assert positions[7] == 2200

    def test_send_move_sim_publishes_with_duration(self, sm):
        sm.connect("sim_port")
        events = []
        bus.subscribe("serial.move_sent", lambda p: events.append(p))
        sm.send_move({1: 2500}, duration_ms=2000)
        assert len(events) == 1
        assert events[0]["duration_ms"] == 2000

    def test_send_move_when_disconnected_no_op(self, sm):
        """send_move silencieux mais sans crash si non connecte."""
        events = []
        bus.subscribe("serial.move_sent", lambda p: events.append(p))
        sm.send_move({1: 2500}, duration_ms=1000)
        # Ni publish ni mise a jour : silencieux mais pas d'exception
        assert events == []


# ── Diagnostic / hardware features (sim no-op) ──────────────────────

class TestDiagnostic:

    def test_read_hardware_errors_empty_in_sim(self, sm):
        sm.connect("sim_port")
        assert sm.read_hardware_errors() == {}

    def test_reboot_motor_refused_in_sim(self, sm):
        sm.connect("sim_port")
        assert sm.reboot_motor(1) is False

    def test_set_profile_no_op_in_sim_returns_true(self, sm):
        sm.connect("sim_port")
        # En sim, set_profile retourne True sans rien ecrire
        assert sm.set_profile(velocity=100, acceleration=20) is True


# ── send_estop / send_stop ──────────────────────────────────────────

class TestStop:

    def test_send_estop_disables_torque(self, sm):
        sm.connect("sim_port")
        sm.set_torque(True)
        sm.send_estop()
        assert sm.torque_enabled is False

    def test_send_stop_disables_torque(self, sm):
        sm.connect("sim_port")
        sm.set_torque(True)
        sm.send_stop()
        assert sm.torque_enabled is False


# ── connect() : contrat de type (bug tuple/bool) ────────────────────

class TestConnectReturnType:
    """connect() est typée -> bool. Le chemin 'aucun moteur configuré'
    doit retourner False (bool) et non un tuple (truthy → fausse connexion
    chez l'appelant qui fait `if ok:`)."""

    def test_connect_no_motors_returns_bool_false(self, reset_bus, monkeypatch):
        import xrv22.hardware.serial_manager as sm_mod

        class FakePort:
            def __init__(self, port):
                pass

            def openPort(self):
                return True

            def setBaudRate(self, baud):
                return True

        class FakePacket:
            def __init__(self, proto):
                pass

        monkeypatch.setattr(sm_mod, "PortHandler", FakePort)
        monkeypatch.setattr(sm_mod, "PacketHandler", FakePacket)

        s = SerialManager("robot_empty", [], simulation=False)
        result = s.connect("/dev/ttyUSB0")
        assert result is False  # bool, surtout pas un tuple truthy
        assert s.connected is False


# ── Seuil de déconnexion (off-by-one mono-moteur) ───────────────────

class TestDisconnectThreshold:
    """`_read_positions_sequential` ne doit déconnecter que si le port est
    réellement instable. Pour un robot mono-moteur, une lecture RÉUSSIE ne
    doit pas déclencher une fausse déconnexion (bug `errors >= len//2` qui
    vaut `errors >= 0` → toujours vrai à 1 moteur)."""

    def _attach_fake_ph(self, s, result_code):
        class FakePH:
            def read4ByteTxRx(self, ph, mid, addr):
                return (2048, result_code, 0)

        s._packet_handler = FakePH()
        s._port_handler = object()

    def test_mono_motor_successful_read_keeps_connected(self, reset_bus):
        s = SerialManager("robot_mono", [1], simulation=False)
        s._connected = True
        self._attach_fake_ph(s, result_code=0)  # lecture OK
        events = []
        bus.subscribe("robot.disconnected", lambda p: events.append(p))
        pos = s._read_positions_sequential()
        assert pos == {1: 2048}
        assert s.connected is True
        assert events == []

    def test_mono_motor_failing_read_disconnects(self, reset_bus):
        s = SerialManager("robot_mono", [1], simulation=False)
        s._connected = True
        self._attach_fake_ph(s, result_code=-1)  # erreur de comm
        s._read_positions_sequential()
        assert s.connected is False

    def test_multi_motor_all_failing_disconnects(self, reset_bus):
        s = SerialManager("robot_multi", [1, 2, 3, 4], simulation=False)
        s._connected = True
        self._attach_fake_ph(s, result_code=-1)  # toutes les lectures KO
        events = []
        bus.subscribe("robot.disconnected", lambda p: events.append(p))
        s._read_positions_sequential()
        assert s.connected is False
        assert len(events) == 1
