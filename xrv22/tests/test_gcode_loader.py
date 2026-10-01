"""Tests de caracterisation du parseur G-code (xrv22/simulation/gcode_loader.py).

Ces tests figent le comportement observable de load_gcode AVANT refactor.
Ils doivent passer a l'identique apres restructuration interne.
"""
from __future__ import annotations

import pytest

from xrv22.simulation.gcode_loader import gcode_to_waypoints, load_gcode


def _write(tmp_path, text: str) -> str:
    p = tmp_path / "prog.gcode"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_lineaire_absolu(tmp_path):
    prog = load_gcode(_write(tmp_path, "G0 X10 Y20\nG1 X30 Y40 Z5 F500\n"))
    assert prog.errors == []
    assert len(prog.waypoints) == 2
    w0, w1 = prog.waypoints
    assert (w0.x, w0.y, w0.z) == (10, 20, 0)
    assert w0.is_rapid is True
    assert w0.feed_rate == 1000.0  # F par defaut
    assert (w1.x, w1.y, w1.z) == (30, 40, 5)
    assert w1.is_rapid is False
    assert w1.feed_rate == 500.0


def test_relatif_g91(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X10 Y10\nG91\nG1 X5 Y5\nG1 X5\n"))
    assert [(w.x, w.y) for w in prog.waypoints] == [(10, 10), (15, 15), (20, 15)]


def test_g90_repasse_en_absolu(tmp_path):
    prog = load_gcode(_write(tmp_path, "G91\nG1 X5\nG90\nG1 X5\n"))
    assert [w.x for w in prog.waypoints] == [5, 5]


def test_g28_home(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X50 Y50\nG28\n"))
    assert len(prog.waypoints) == 2
    last = prog.waypoints[-1]
    assert (last.x, last.y, last.z) == (0, 0, 0)
    assert last.is_rapid is True


def test_outil_m3_m5(tmp_path):
    prog = load_gcode(_write(tmp_path, "M5\nG1 X1\nM3\nG1 X2\n"))
    assert [w.tool_on for w in prog.waypoints] == [False, True]


def test_g1_implicite(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X1 Y1\nX5 Y5\n"))
    assert [(w.x, w.y) for w in prog.waypoints] == [(1, 1), (5, 5)]
    assert all(w.is_rapid is False for w in prog.waypoints)


def test_commentaires(tmp_path):
    prog = load_gcode(
        _write(tmp_path, "G1 X1 ; deplacement\nG1 X2 (rapide)\n; ligne entiere\n")
    )
    assert [w.x for w in prog.waypoints] == [1, 2]


def test_arc_g2_quart_cercle(tmp_path):
    # quart de cercle rayon 10, centre origine, depart (10,0)
    prog = load_gcode(_write(tmp_path, "G1 X10 Y0\nG2 X0 Y10 I-10 J0\n"))
    assert len(prog.waypoints) == 1 + 16  # depart + 16 segments
    end = prog.waypoints[-1]
    assert end.x == pytest.approx(0, abs=1e-6)
    assert end.y == pytest.approx(10, abs=1e-6)
    assert all(not w.is_rapid for w in prog.waypoints[1:])


def test_bornes(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X10 Y-5 Z3\nG1 X-2 Y8 Z1\n"))
    assert prog.bounds_min == (-2, -5, 1)
    assert prog.bounds_max == (10, 8, 3)


def test_feed_persiste(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X1 F250\nG1 X2\n"))
    assert [w.feed_rate for w in prog.waypoints] == [250.0, 250.0]


def test_fichier_absent(tmp_path):
    prog = load_gcode(str(tmp_path / "inexistant.gcode"))
    assert prog.errors
    assert prog.waypoints == []


def test_line_count(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X1\n\nG1 X2\n"))
    assert prog.line_count == 3


def test_gcode_to_waypoints_scale_offset(tmp_path):
    prog = load_gcode(_write(tmp_path, "G1 X10 Y20 Z0 F300\n"))
    pts = gcode_to_waypoints(prog, scale=2.0, offset=(1.0, 2.0, 3.0))
    assert pts == [(21.0, 42.0, 3.0, 300.0)]
