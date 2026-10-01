"""Tests de caracterisation de _to_jsonable (xrv22/server/api.py)."""
from __future__ import annotations

from dataclasses import dataclass

from xrv22.server.api import _to_jsonable


def test_primitives():
    assert _to_jsonable(None) is None
    assert _to_jsonable(True) is True
    assert _to_jsonable(42) == 42
    assert _to_jsonable(3.14) == 3.14
    assert _to_jsonable("foo") == "foo"


def test_dict_cles_str():
    assert _to_jsonable({1: "a", 2: "b"}) == {"1": "a", "2": "b"}


def test_list_tuple_set_to_list():
    assert _to_jsonable([1, 2]) == [1, 2]
    assert _to_jsonable((1, 2)) == [1, 2]
    out = _to_jsonable({1, 2, 3})
    assert sorted(out) == [1, 2, 3]


def test_dataclass():
    @dataclass
    class P:
        x: int = 1
        y: str = "a"
    assert _to_jsonable(P()) == {"x": 1, "y": "a"}


def test_objet_avec_model_dump():
    class Pyd:
        def model_dump(self):
            return {"v": 7}
    assert _to_jsonable(Pyd()) == {"v": 7}


def test_objet_avec_dict_callable():
    class WithDict:
        def dict(self):
            return {"k": 1}
    assert _to_jsonable(WithDict()) == {"k": 1}


def test_objet_inconnu_to_str():
    class Foo:
        def __repr__(self):
            return "<Foo>"
    assert _to_jsonable(Foo()) == "<Foo>"


def test_recursif():
    @dataclass
    class P:
        x: int = 1
    out = _to_jsonable({1: [P(), P()]})
    assert out == {"1": [{"x": 1}, {"x": 1}]}


def test_objet_dict_qui_raise():
    # Si .dict() raise -> fallback sur str()
    class Bad:
        def dict(self):
            raise RuntimeError("nope")
        def __repr__(self):
            return "<Bad>"
    assert _to_jsonable(Bad()) == "<Bad>"
