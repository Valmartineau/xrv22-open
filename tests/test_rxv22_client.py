"""Client HTTP fin vers le serveur RXV22 (token Bearer). L'appel réseau est
injecté → on teste URL, en-têtes et payload sans serveur."""
from incarne.corps.rxv22_client import RxV22Client


def _client_capteur():
    captured = {}

    def fake_request(method, url, headers, body):
        captured.update(method=method, url=url, headers=headers, body=body)
        return {"ok": True}

    return RxV22Client("http://pi:8080", token="TT", http_request=fake_request), captured


def test_write_positions_url_token_et_payload_str():
    client, captured = _client_capteur()
    client.write_positions("robot_1", {2: 2030})
    assert captured["method"] == "POST"
    assert captured["url"] == "http://pi:8080/api/robots/robot_1/positions"
    assert captured["headers"]["Authorization"] == "Bearer TT"
    assert captured["body"] == {"positions": {"2": 2030}}  # clés en str


def test_get_robot_url_et_token():
    client, captured = _client_capteur()
    client.get_robot("robot_1")
    assert captured["method"] == "GET"
    assert captured["url"] == "http://pi:8080/api/robots/robot_1"
    assert captured["headers"]["Authorization"] == "Bearer TT"


def test_set_torque_payload():
    client, captured = _client_capteur()
    client.set_torque("robot_1", True)
    assert captured["url"].endswith("/api/robots/robot_1/torque")
    assert captured["body"] == {"enable": True}


def test_publier_eddy_poste_le_payload_sur_la_bonne_route():
    appels = []

    def fake_req(method, url, headers, body):
        appels.append((method, url, body))
        return {"ok": True}

    from incarne.corps.rxv22_client import RxV22Client
    client = RxV22Client("http://h:8080", token="tok", http_request=fake_req)
    client.publier_eddy({"pas": 3, "bloque": False})

    assert appels == [("POST", "http://h:8080/api/eddy/step",
                       {"pas": 3, "bloque": False})]


def test_set_direct_mode_prend_et_lache_la_main():
    appels = []

    def fake_req(method, url, headers, body):
        appels.append((method, url, body)); return {"ok": True}

    from incarne.corps.rxv22_client import RxV22Client
    client = RxV22Client("http://h:8080", token="t", http_request=fake_req)
    client.set_direct_mode("robot_1", True)
    client.set_direct_mode("robot_1", False)
    assert appels == [
        ("POST", "http://h:8080/api/robots/robot_1/direct_mode", {"enable": True}),
        ("POST", "http://h:8080/api/robots/robot_1/direct_mode", {"enable": False}),
    ]


def test_publier_stylet_poste_le_tick():
    appels = []
    def fake_req(method, url, headers, body):
        appels.append((method, url, body)); return {"ok": True}
    from incarne.corps.rxv22_client import RxV22Client
    client = RxV22Client("http://h:8080", token="t", http_request=fake_req)
    client.publier_stylet({"x": 10, "y": 20, "p": 300, "etat": "CONTACT"})
    assert appels == [("POST", "http://h:8080/api/stylet/tick",
                       {"x": 10, "y": 20, "p": 300, "etat": "CONTACT"})]
