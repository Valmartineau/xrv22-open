"""Tests de validation de la cinematique backend XRV22.

Aligne la FK / IK sur la calibration physique du robot (REF_UP du 2026-05-19,
mapping d'axes 1=base, 2&3=epaule couples, 4=coude, 5=poignet, 6=rot poignet,
7=pince ; echelle Dynamixel X-series 360 deg / 4096 pas).
"""
from __future__ import annotations

import math

import pytest

from xrv22.simulation.kinematics import (
    BASE_H, SHOULDER_H, L_FARM, L_TOOL, L_WRIST, REF_UP, UA_X, UA_Z,
    fk, fk_tcp, ik_tool_angle, ik_tool_down,
    rad_to_tick, tick_to_rad,
)


# ── Conversion ticks ↔ rad ────────────────────────────────────────

def test_scale_360_sur_4096():
    """Echelle Dynamixel : 1024 ticks = 90 deg = pi/2 rad."""
    assert tick_to_rad(2048 + 1024) == pytest.approx(math.pi / 2)
    assert tick_to_rad(2048 - 1024) == pytest.approx(-math.pi / 2)


def test_axis_ref_calibre_sur_ref_up():
    # A REF_UP, l'angle du joint = 0
    for axis, ref in REF_UP.items():
        assert tick_to_rad(ref, axis=axis) == 0.0


def test_rad_to_tick_round_trip_par_axe():
    for axis, ref in REF_UP.items():
        # Round-trip a 0
        assert rad_to_tick(0, axis=axis) == ref
        # Round-trip a +1024 ticks (90 deg)
        t = rad_to_tick(math.pi / 2, axis=axis)
        assert t == ref + 1024


def test_rad_to_tick_clamp():
    assert rad_to_tick(math.radians(360), axis=1) == 4095
    assert rad_to_tick(-math.radians(360), axis=1) == 0


# ── Forward Kinematics ────────────────────────────────────────────

REF_POSE = {1: REF_UP[1], 2: REF_UP[2], 4: REF_UP[4], 5: REF_UP[5]}


def test_fk_a_la_pose_ref_up():
    """A REF_UP, tous les joints a 0 → bras "vers le haut"."""
    j0, j1, j2, j3, j4, j5, j6 = fk(REF_POSE)
    assert j0 == (0.0, 0.0, 0.0)
    assert j1 == (0.0, 0.0, BASE_H)
    assert j2 == (0.0, 0.0, BASE_H + SHOULDER_H)
    # Upper arm a a2=0 : kink horizontal UA_X, vertical UA_Z
    assert j3 == pytest.approx((0.0, UA_X, BASE_H + SHOULDER_H + UA_Z))
    # Avant-bras vertical (Z+) depuis j3
    assert j4 == pytest.approx((0.0, UA_X, BASE_H + SHOULDER_H + UA_Z + L_FARM))
    # Poignet + outil : meme direction
    assert j5 == pytest.approx((0.0, UA_X, BASE_H + SHOULDER_H + UA_Z + L_FARM + L_WRIST))
    assert j6 == pytest.approx(
        (0.0, UA_X, BASE_H + SHOULDER_H + UA_Z + L_FARM + L_WRIST + L_TOOL))


def test_fk_rotation_base_a1():
    """Faire tourner l'axe 1 de pi/2 : l'offset UA_X passe de Y a X."""
    pose = dict(REF_POSE)
    pose[1] = REF_UP[1] + 1024            # +90 deg
    tcp = fk_tcp(pose)
    expected_z = BASE_H + SHOULDER_H + UA_Z + L_FARM + L_WRIST + L_TOOL
    assert tcp[0] == pytest.approx(UA_X)
    assert tcp[1] == pytest.approx(0, abs=1e-9)
    assert tcp[2] == pytest.approx(expected_z)


def test_fk_tcp_alias():
    assert fk_tcp(REF_POSE) == fk(REF_POSE)[-1]


def test_fk_axe_3_ignore():
    """L'axe 3 (slave couple) ne doit pas affecter la FK."""
    pose_a = dict(REF_POSE)
    pose_b = dict(REF_POSE)
    pose_b[3] = 1000   # n'importe quelle valeur
    assert fk(pose_a) == fk(pose_b)


def test_fk_coude_axe_4():
    """Bouger l'axe 4 (coude) plie l'avant-bras, pas l'axe 3."""
    pose_neutral = dict(REF_POSE)
    pose_via_4 = dict(REF_POSE); pose_via_4[4] = REF_UP[4] + 512   # +45 deg
    pose_via_3 = dict(REF_POSE); pose_via_3[3] = 2048 + 512        # ne change rien
    assert fk_tcp(pose_via_4) != pytest.approx(fk_tcp(pose_neutral))
    assert fk_tcp(pose_via_3) == fk_tcp(pose_neutral)


# ── Inverse Kinematics ────────────────────────────────────────────

def test_ik_hors_portee_retourne_none():
    # Tres loin du robot
    assert ik_tool_angle(2000.0, 0.0, 100.0) is None


def test_ik_round_trip_tool_down():
    """IK(target) → ticks ; FK(ticks) ≈ target."""
    target = (200.0, 0.0, 100.0)
    ticks = ik_tool_down(*target)
    assert ticks is not None
    tcp = fk_tcp(ticks)
    assert tcp[0] == pytest.approx(target[0], abs=0.5)
    assert tcp[1] == pytest.approx(target[1], abs=0.5)
    assert tcp[2] == pytest.approx(target[2], abs=0.5)


def test_ik_round_trip_tool_horizontal():
    """Outil horizontal (tool_angle=pi/2) : round-trip."""
    target = (250.0, 50.0, 200.0)
    ticks = ik_tool_angle(*target, tool_angle_rad=math.pi / 2)
    assert ticks is not None
    tcp = fk_tcp(ticks)
    assert tcp[0] == pytest.approx(target[0], abs=0.5)
    assert tcp[1] == pytest.approx(target[1], abs=0.5)
    assert tcp[2] == pytest.approx(target[2], abs=0.5)


def test_ik_axe_3_copie_de_l_axe_2():
    """L'IK met l'axe 3 = axe 2 (placeholder ; sera ecrase par le couplage)."""
    ticks = ik_tool_down(200.0, 0.0, 100.0)
    assert ticks is not None
    assert ticks[3] == ticks[2]


def test_ik_axes_6_et_7():
    """L'IK fixe l'axe 6 sur REF_UP (rot. poignet neutre) et l'axe 7 sur l'argument."""
    ticks = ik_tool_down(200.0, 0.0, 100.0, gripper_tick=1500)
    assert ticks is not None
    assert ticks[6] == REF_UP.get(6, 2048)
    assert ticks[7] == 1500
