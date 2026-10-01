"""Tests pour xrv22/config.py — vérification cohérence des constantes."""
import pytest
from xrv22.config import (
    MOTOR_IDS_DEFAULT, MOTOR_COUNT, PINCE_AXIS, HIDDEN_AXES,
    MOTOR_RANGE_MIN, MOTOR_RANGE_MAX, MOTOR_CENTER, MOTOR_RANGE,
    SOFT_LIMITS_DEFAULTS,
    BAUDRATE_DXL_DEFAULT, BAUDRATE_DXL_VALID, BAUDRATE_DXL_OPTIONS,
    BAUDRATE_ARDUINO_DEFAULT, BAUDRATE_ARDUINO_OPTIONS,
    SMOOTH_HZ_DEFAULT, COMFORT_VEL_DEFAULT, COMFORT_ACC_DEFAULT,
    HOME_DURATION_DEFAULT_S, TICK_MS, TICK_S,
)


def test_motor_ids_coherent():
    assert len(MOTOR_IDS_DEFAULT) == MOTOR_COUNT
    assert PINCE_AXIS in MOTOR_IDS_DEFAULT


def test_motor_range():
    assert MOTOR_RANGE_MIN == 0
    assert MOTOR_RANGE_MAX == 4095
    assert MOTOR_CENTER == 2048
    assert MOTOR_RANGE == (0, 4095)


def test_soft_limits_within_range():
    for mid, (lo, hi) in SOFT_LIMITS_DEFAULTS.items():
        assert MOTOR_RANGE_MIN <= lo <= MOTOR_RANGE_MAX, f"Axe {mid} lo hors range"
        assert MOTOR_RANGE_MIN <= hi <= MOTOR_RANGE_MAX, f"Axe {mid} hi hors range"
        assert lo < hi, f"Axe {mid} limites inversées"


def test_baudrate_default_in_valid():
    assert BAUDRATE_DXL_DEFAULT in BAUDRATE_DXL_VALID
    for b in BAUDRATE_DXL_OPTIONS:
        assert b in BAUDRATE_DXL_VALID


def test_tick_coherence():
    assert abs(TICK_S - TICK_MS / 1000.0) < 1e-9


def test_motion_defaults_sane():
    assert 30 <= SMOOTH_HZ_DEFAULT <= 120
    assert 10 <= COMFORT_VEL_DEFAULT <= 500
    assert 5 <= COMFORT_ACC_DEFAULT <= 200
    assert 0.5 <= HOME_DURATION_DEFAULT_S <= 10.0
