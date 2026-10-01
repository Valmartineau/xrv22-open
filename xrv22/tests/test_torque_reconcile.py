"""Anti-à-coup au réveil moteur : à l'activation du couple (OFF→ON), le
contrôleur doit réconcilier Goal Position = position physique réelle, sinon le
servo fonce vers le Goal résiduel (cause de l'à-coup, surtout le coude qui
s'affaisse sous gravité). Cf. project_xrv22_reveil_coude.

Test au niveau RobotController avec un faux _serial qui enregistre l'ordre
exact des appels — on ne dépend pas du vrai HW ni de _tick_jog (rang D)."""

import pytest

from xrv22.robots.robot_controller import RobotController

MOTOR_IDS = [1, 2, 3, 4, 5, 6, 7]
# Position "affaissée" : le coude (axe 3) a chuté pendant que le couple était coupé.
DROOPED = {1: 2048, 2: 1400, 3: 1100, 4: 2048, 5: 2048, 6: 2048, 7: 2048}


class FakeSerial:
    """Faux SerialManager : enregistre l'ordre des opérations."""

    def __init__(self, present, goal=None):
        self.connected = True
        self._torque = False
        self._present = dict(present)
        self._goal = dict(goal) if goal else dict(present)
        self.calls = []  # journal ordonné : (op, arg)

    @property
    def torque_enabled(self):
        return self._torque

    def set_torque(self, enable):
        self.calls.append(("set_torque", enable))
        self._torque = enable
        return True

    def read_positions(self):
        self.calls.append(("read_positions", None))
        return dict(self._present)

    def read_goal_positions(self):
        self.calls.append(("read_goal_positions", None))
        return dict(self._goal)

    def write_positions(self, pos):
        self.calls.append(("write_positions", dict(pos)))
        return True

    def set_profile(self, vel, acc):
        self.calls.append(("set_profile", (vel, acc)))


def _make_ctrl(present, torque_on=False, goal=None):
    c = RobotController("robot_test", MOTOR_IDS, simulation=False)
    fake = FakeSerial(present, goal=goal)
    fake._torque = torque_on
    c._serial = fake
    return c, fake


def test_arm_hold_reference_ancre_sur_goal_pas_present():
    """Maintien teach-pendant : à la prise de main on s'ancre sur le registre
    GOAL (consigne courante), PAS sur le present affaissé sous le goal — sinon
    le servo re-droobe d'un cran à chaque prise (ratchet). Cf. décrochage jog."""
    # present (affaissé) sous le goal sur le coude/épaule
    present = {1: 2048, 2: 1117, 3: 1142, 4: 2570, 5: 2048, 6: 2048, 7: 2048}
    goal = {1: 2048, 2: 1141, 3: 1165, 4: 2497, 5: 2048, 6: 2048, 7: 2048}
    c, fake = _make_ctrl(present, torque_on=True, goal=goal)
    seed = c.arm_hold_reference()
    assert seed == goal                       # on tient le GOAL, pas le present
    assert c._coupling_ref == (goal[2], goal[3])   # réf couplage = pose du goal


def _ops(fake):
    return [op for op, _ in fake.calls]


def test_torque_on_writes_goal_equal_to_present_after_enabling():
    c, fake = _make_ctrl(DROOPED)
    assert c.set_torque(True) is True
    ops = _ops(fake)
    assert ("set_torque", True) in fake.calls
    assert "write_positions" in ops, "le Goal doit être réécrit au réveil"
    # Anti-affaissement : le Goal=present doit être écrit AVANT d'armer le couple
    # (sinon le servo fonce vers son Goal résiduel à l'instant du torque-enable).
    assert ops.index("write_positions") < ops.index("set_torque")
    # Et il doit valoir la position physique réelle (affaissée), pas autre chose.
    written = fake.calls[ops.index("write_positions")][1]
    assert written == DROOPED


def test_torque_on_reconciles_goal_after_enabling_too():
    """Rempart : un write Goal=present subsiste APRÈS l'enable (au cas où un
    micro-fluage surviendrait dans la fenêtre pré-arm)."""
    c, fake = _make_ctrl(DROOPED)
    assert c.set_torque(True) is True
    ops = _ops(fake)
    # au moins un write_positions après set_torque
    last_write = len(ops) - 1 - ops[::-1].index("write_positions")
    assert last_write > ops.index("set_torque")


def test_torque_on_reads_present_before_enabling():
    """La position réelle est lue AVANT d'armer (lisible couple coupé) et un
    profil confort est posé — jamais le profil jog court — pour que tout rush
    résiduel reste lent."""
    c, fake = _make_ctrl(DROOPED)
    c.set_torque(True)
    ops = _ops(fake)
    assert "set_profile" in ops, "profil confort posé au réveil"
    assert ops.index("read_positions") < ops.index("set_torque")


def test_torque_off_does_not_reconcile():
    c, fake = _make_ctrl(DROOPED, torque_on=True)
    c.set_torque(False)
    assert "write_positions" not in _ops(fake)


def test_torque_on_when_already_on_does_not_reconcile():
    c, fake = _make_ctrl(DROOPED, torque_on=True)
    c.set_torque(True)
    # Pas de transition OFF→ON : aucune réconciliation parasite.
    assert "write_positions" not in _ops(fake)


def test_read_failure_falls_back_gracefully():
    """Si la lecture HW échoue, on n'écrit pas de Goal bidon : on retombe sur
    le comportement actuel (torque activé quand même)."""
    c, fake = _make_ctrl(DROOPED)
    fake.read_positions = lambda: {}
    assert c.set_torque(True) is True
    assert "write_positions" not in _ops(fake)
