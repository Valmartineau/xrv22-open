"""Tests pour xrv22/robots/robot_profiles.py."""
import pytest
from xrv22.robots.robot_profiles import (
    RobotProfile, ProfileRegistry, make_default_profile,
)


@pytest.fixture
def profile():
    """Profil XRV22 standard 7 axes."""
    return make_default_profile("test_bot")


class TestRobotProfile:

    def test_motor_ids(self, profile):
        assert profile.motor_ids == [1, 2, 3, 4, 5, 6, 7]

    def test_soft_limits_populated(self, profile):
        for mid in profile.motor_ids:
            lo, hi = profile.soft_limits[mid]
            assert 0 <= lo < hi <= 4095

    def test_validate_positions_ok(self, profile):
        ok, errors = profile.validate_positions({1: 2048, 2: 2048})
        assert ok
        assert errors == []

    def test_validate_positions_out(self, profile):
        ok, errors = profile.validate_positions({7: 0})
        assert not ok
        assert len(errors) == 1

    def test_validate_duration_ok(self, profile):
        ok, msg = profile.validate_duration(1.0)
        assert ok

    def test_validate_duration_too_short(self, profile):
        ok, msg = profile.validate_duration(0.01)
        assert not ok

    def test_validate_duration_too_long(self, profile):
        ok, msg = profile.validate_duration(999.0)
        assert not ok

    def test_clamp_positions(self, profile):
        clamped = profile.clamp_positions({1: 0, 2: 9999})
        lo1, hi1 = profile.soft_limits[1]
        lo2, hi2 = profile.soft_limits[2]
        assert clamped[1] == lo1
        assert clamped[2] == hi2


class TestProfileRegistry:

    def test_register_and_get(self):
        reg = ProfileRegistry()
        p = make_default_profile("bot1")
        reg.register(p)
        assert reg.get("bot1") is p

    def test_get_missing(self):
        reg = ProfileRegistry()
        assert reg.get("nope") is None

    def test_all_ids(self):
        reg = ProfileRegistry()
        reg.register(make_default_profile("a"))
        reg.register(make_default_profile("b"))
        assert sorted(reg.all_ids()) == ["a", "b"]
