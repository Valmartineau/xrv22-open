"""
Tests : formatage des commandes actionneurs Arduino (contrat ActuatorChannel.format_command).
Ces tests verrouillent le contrat utilisé par l'endpoint POST /api/hardware/devices/{did}/actuators/{act}.
"""
from xrv22.hardware.arduino_bridge import ActuatorChannel


def test_relay_command_format():
    act = ActuatorChannel(name="pump", kind="relay")
    assert act.format_command(1).strip() == '{"SET": "pump", "v": "1"}'
    assert act.format_command(0).strip() == '{"SET": "pump", "v": "0"}'


def test_pwm_command_format():
    act = ActuatorChannel(name="fan", kind="pwm")
    assert act.format_command(128).strip() == '{"SET": "fan", "v": 128}'


def test_template_command_format():
    act = ActuatorChannel(name="led", cmd_template="LED {v}")
    assert act.format_command(7).strip() == "LED 7"
