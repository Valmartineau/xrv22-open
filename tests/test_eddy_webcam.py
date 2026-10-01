from eddy.perception.webcam import SourceWebcam

class FakeCap:
    def read(self):
        return True, "FRAME"
    def release(self):
        pass

def test_capture_lit_une_frame_et_encode():
    vu = {}
    def fake_encode(frame):
        vu["frame"] = frame
        return b"\xff\xd8\xff_jpeg"
    src = SourceWebcam(ouvre=lambda index: FakeCap(), encode=fake_encode, index=0)
    data = src.capture()
    assert data == b"\xff\xd8\xff_jpeg"
    assert vu["frame"] == "FRAME"
    assert src.canal == "webcam"

def test_echec_lecture_leve():
    class CapKO:
        def read(self): return False, None
        def release(self): pass
    import pytest
    src = SourceWebcam(ouvre=lambda index: CapKO(), encode=lambda f: b"x")
    with pytest.raises(RuntimeError):
        src.capture()
