from xrv22.server.port_discovery import classify_ports


class _FakePort:
    def __init__(self, device, vid, description="", serial_number=""):
        self.device = device
        self.vid = vid
        self.description = description
        self.serial_number = serial_number


def test_arduino_flagged_robots_excluded():
    ports = [
        _FakePort("/dev/ttyACM0", 0x2341, "Arduino Mega 2560"),
        _FakePort("/dev/ttyUSB0", 0x0403, "FT232H"),   # U2D2 robot
        _FakePort("/dev/ttyUSB1", 0x0403, "FT232H"),
        _FakePort("/dev/ttyS0", None, "generic"),
    ]
    result = classify_ports(ports, robot_ports={"/dev/ttyUSB1"})

    devices = {p["device"]: p for p in result}
    assert "/dev/ttyUSB0" not in devices
    assert "/dev/ttyUSB1" not in devices
    assert devices["/dev/ttyACM0"]["is_arduino"] is True
    assert devices["/dev/ttyS0"]["is_arduino"] is False
