from xrv22.hardware.arduino_bridge import ArduinoDevice, SensorChannel, ActuatorChannel, ArduinoAction
from xrv22.server.arduino_serializer import device_to_dict


def test_device_to_dict_full():
    dev = ArduinoDevice(name="Arduino_1", port="/dev/ttyACM0", baud=115200)
    dev.connected = True
    dev.identified = True
    dev.firmware = "v1.2"
    dev.channels["temp"] = SensorChannel(name="temp", unit="°C", min_val=0, max_val=50)
    dev.channels["temp"].update(23.5)
    dev.actuators["pump"] = ActuatorChannel(name="pump", kind="relay", label="Pompe")
    dev.actions["purge"] = ArduinoAction(name="purge", label="Purge", duration_ms=2000)

    d = device_to_dict(dev)

    assert d["name"] == "Arduino_1"
    assert d["connected"] is True
    assert d["identified"] is True
    assert d["firmware"] == "v1.2"
    assert d["channels"][0]["name"] == "temp"
    assert d["channels"][0]["value"] == 23.5
    assert d["channels"][0]["unit"] == "°C"
    assert d["actuators"][0]["kind"] == "relay"
    assert d["actions"][0]["name"] == "purge"


def test_device_to_dict_none_stub_same_keys():
    dev = ArduinoDevice(name="Arduino_1", port="/dev/ttyACM0", baud=115200)
    full = device_to_dict(dev)
    stub = device_to_dict(None, name="Arduino_1", port="/dev/ttyACM0", baud=115200)
    assert set(stub.keys()) == set(full.keys())
    assert stub["connected"] is False
    assert stub["port"] == "/dev/ttyACM0"
    assert stub["baud"] == 115200
    assert stub["channels"] == []
