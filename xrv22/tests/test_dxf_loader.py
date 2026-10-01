"""Tests de caracterisation du chargeur DXF (xrv22/simulation/dxf_loader.py).

Figent le comportement de load_dxf et des parseurs d'entites AVANT refactor.
"""
from __future__ import annotations

from xrv22.simulation.dxf_loader import DxfMesh, load_dxf


def _dxf(tmp_path, *pairs) -> str:
    """Ecrit un DXF (section ENTITIES) a partir de paires (code, valeur)."""
    body = [(0, "SECTION"), (2, "ENTITIES")] + list(pairs) + [(0, "ENDSEC"), (0, "EOF")]
    text = "\n".join(f"{c}\n{v}" for c, v in body) + "\n"
    p = tmp_path / "f.dxf"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_line(tmp_path):
    path = _dxf(tmp_path,
                (0, "LINE"), (10, "1"), (20, "2"), (30, "0"),
                (11, "4"), (21, "6"), (31, "0"))
    mesh = load_dxf(path)
    assert mesh.segments == [((1.0, 2.0, 0.0), (4.0, 6.0, 0.0))]
    assert mesh.faces == []


def test_lwpolyline_ouverte(tmp_path):
    path = _dxf(tmp_path,
                (0, "LWPOLYLINE"),
                (10, "0"), (20, "0"), (10, "10"), (20, "0"), (10, "10"), (20, "10"))
    mesh = load_dxf(path)
    assert mesh.polylines == [[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]]
    # convertie en 2 segments
    assert len(mesh.segments) == 2


def test_lwpolyline_fermee(tmp_path):
    path = _dxf(tmp_path,
                (0, "LWPOLYLINE"), (70, "1"),
                (10, "0"), (20, "0"), (10, "10"), (20, "0"), (10, "10"), (20, "10"))
    mesh = load_dxf(path)
    pl = mesh.polylines[0]
    assert len(pl) == 4               # 3 sommets + retour au premier
    assert pl[-1] == pl[0]


def test_lwpolyline_elevation(tmp_path):
    path = _dxf(tmp_path,
                (0, "LWPOLYLINE"), (38, "2.5"),
                (10, "0"), (20, "0"), (10, "5"), (20, "5"))
    mesh = load_dxf(path)
    assert all(v[2] == 2.5 for v in mesh.polylines[0])


def test_polyline_vertex_seqend(tmp_path):
    path = _dxf(tmp_path,
                (0, "POLYLINE"),
                (0, "VERTEX"), (10, "1"), (20, "2"), (30, "3"),
                (0, "VERTEX"), (10, "4"), (20, "5"), (30, "6"),
                (0, "SEQEND"))
    mesh = load_dxf(path)
    assert mesh.polylines == [[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]]
    assert len(mesh.segments) == 1


def test_3dface_triangle(tmp_path):
    path = _dxf(tmp_path,
                (0, "3DFACE"),
                (10, "0"), (20, "0"), (30, "0"),
                (11, "10"), (21, "0"), (31, "0"),
                (12, "10"), (22, "10"), (32, "0"))
    mesh = load_dxf(path)
    assert mesh.faces == [[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0)]]


def test_3dface_quad_dedup(tmp_path):
    # 4e point identique au 3e -> deduplique en triangle
    path = _dxf(tmp_path,
                (0, "3DFACE"),
                (10, "0"), (20, "0"), (30, "0"),
                (11, "10"), (21, "0"), (31, "0"),
                (12, "10"), (22, "10"), (32, "0"),
                (13, "10"), (23, "10"), (33, "0"))
    mesh = load_dxf(path)
    assert len(mesh.faces[0]) == 3


def test_3dface_quad(tmp_path):
    path = _dxf(tmp_path,
                (0, "3DFACE"),
                (10, "0"), (20, "0"), (30, "0"),
                (11, "10"), (21, "0"), (31, "0"),
                (12, "10"), (22, "10"), (32, "0"),
                (13, "0"), (23, "10"), (33, "0"))
    mesh = load_dxf(path)
    assert len(mesh.faces[0]) == 4


def test_entites_hors_section_ignorees(tmp_path):
    # une LINE avant ENTITIES ne doit pas etre prise en compte
    text = "\n".join(f"{c}\n{v}" for c, v in [
        (0, "SECTION"), (2, "HEADER"),
        (0, "LINE"), (10, "0"), (20, "0"), (11, "1"), (21, "1"),
        (0, "ENDSEC"),
        (0, "SECTION"), (2, "ENTITIES"),
        (0, "LINE"), (10, "0"), (20, "0"), (11, "9"), (21, "9"),
        (0, "ENDSEC"), (0, "EOF"),
    ]) + "\n"
    p = tmp_path / "h.dxf"
    p.write_text(text, encoding="utf-8")
    mesh = load_dxf(str(p))
    assert mesh.segments == [((0.0, 0.0, 0.0), (9.0, 9.0, 0.0))]


def test_mesh_bounds_et_vide():
    assert DxfMesh().is_empty is True
    m = DxfMesh()
    m.segments.append(((0.0, 0.0, 0.0), (10.0, 4.0, 2.0)))
    assert m.is_empty is False
    assert m.bounds() == ((0.0, 0.0, 0.0), (10.0, 4.0, 2.0))
    assert m.center() == (5.0, 2.0, 1.0)
    assert m.size() == 10.0
