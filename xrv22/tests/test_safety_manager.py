"""Tests pour xrv22/core/safety_manager.py."""
import pytest
from xrv22.core.safety_manager import (
    RobotSafetyManager, RobotState, GlobalSafetyManager, SafetyViolation,
)


@pytest.fixture
def rsm():
    """RobotSafetyManager pour robot_test avec 7 moteurs."""
    return RobotSafetyManager("robot_test", [1, 2, 3, 4, 5, 6, 7])


class TestRobotState:

    def test_initial_state_idle(self, rsm):
        assert rsm.state == RobotState.IDLE

    def test_transition_to_ready(self, rsm):
        assert rsm.transition_to(RobotState.READY) is True
        assert rsm.state == RobotState.READY

    def test_transition_to_running(self, rsm):
        rsm.transition_to(RobotState.READY)
        assert rsm.transition_to(RobotState.RUNNING) is True
        assert rsm.state == RobotState.RUNNING

    def test_force_emergency_stop(self, rsm):
        rsm.transition_to(RobotState.READY)
        rsm.force_emergency_stop("test")
        assert rsm.state == RobotState.EMERGENCY_STOP

    def test_emergency_stop_from_any_state(self, rsm):
        """force_emergency_stop fonctionne depuis n'importe quel état."""
        rsm.force_emergency_stop("test")
        assert rsm.state == RobotState.EMERGENCY_STOP

    def test_soft_stop(self, rsm):
        rsm.transition_to(RobotState.READY)
        rsm.transition_to(RobotState.RUNNING)
        rsm.soft_stop()
        assert rsm.state == RobotState.SOFT_STOP

    def test_comm_lost(self, rsm):
        rsm.transition_to(RobotState.READY)
        rsm.on_comm_lost()
        assert rsm.state == RobotState.COMM_LOST

    def test_invalid_transition_refused(self, rsm):
        """IDLE → PAUSED n'est pas dans la matrice."""
        assert rsm.transition_to(RobotState.PAUSED) is False
        assert rsm.state == RobotState.IDLE

    def test_lock_unlock(self, rsm):
        assert rsm.lock() is True
        assert rsm.state == RobotState.LOCKED
        assert rsm.unlock() is True
        assert rsm.state == RobotState.IDLE


class TestSoftLimits:

    def test_set_soft_limits(self, rsm):
        rsm.set_soft_limits(1, 100, 3000)
        assert rsm.soft_limits[1] == (100, 3000)

    def test_default_limits(self, rsm):
        assert rsm.soft_limits[1] == (0, 4095)

    def test_validate_move_within_limits(self, rsm):
        rsm.set_soft_limits(1, 100, 3000)
        ok, violations = rsm.validate_move({1: 500}, 1.0, {1: 400})
        assert ok is True
        assert all(v.severity not in ("critical", "error") for v in violations)

    def test_validate_move_out_of_limits(self, rsm):
        rsm.set_soft_limits(1, 100, 3000)
        ok, violations = rsm.validate_move({1: 50}, 1.0, {1: 100})
        assert ok is False
        error_violations = [v for v in violations if v.severity == "error"]
        assert len(error_violations) > 0

    def test_validate_move_speed_too_fast(self, rsm):
        """Déplacement trop rapide génère une violation."""
        ok, violations = rsm.validate_move({1: 4000}, 0.2, {1: 0})
        assert ok is False


class TestGlobalSafety:

    def test_add_robot(self):
        gsm = GlobalSafetyManager()
        rsm = gsm.add_robot("test_global", [1, 2, 3])
        assert rsm is not None
        assert rsm.state == RobotState.IDLE

    def test_emergency_stop_all(self):
        gsm = GlobalSafetyManager()
        rsm1 = gsm.add_robot("r1", [1])
        rsm2 = gsm.add_robot("r2", [1])
        rsm1.transition_to(RobotState.READY)
        rsm2.transition_to(RobotState.READY)
        gsm.emergency_stop_all()
        assert rsm1.state == RobotState.EMERGENCY_STOP
        assert rsm2.state == RobotState.EMERGENCY_STOP

    def test_soft_stop_all(self):
        gsm = GlobalSafetyManager()
        rsm1 = gsm.add_robot("r3", [1])
        rsm1.transition_to(RobotState.READY)
        rsm1.transition_to(RobotState.RUNNING)
        gsm.soft_stop_all()
        assert rsm1.state == RobotState.SOFT_STOP
