import base64
from eddy.vision.vlm import VisionModel

def test_decris_envoie_image_en_base64_et_rend_le_texte():
    capture = {}
    def fake_post(url, body):
        capture["url"] = url
        capture["body"] = body
        return {"message": {"content": "  un ballon de football  "}}
    vm = VisionModel(model="qwen2.5vl:7b", host="http://localhost:11434",
                     http_post=fake_post)

    desc = vm.decris(b"\xff\xd8\xff_des_octets_jpeg")

    assert desc == "un ballon de football"                  # strip appliqué
    assert capture["url"].endswith("/api/chat")
    msg = capture["body"]["messages"][0]
    assert msg["images"] == [base64.b64encode(b"\xff\xd8\xff_des_octets_jpeg").decode()]
    assert capture["body"]["stream"] is False
    assert capture["body"]["model"] == "qwen2.5vl:7b"
