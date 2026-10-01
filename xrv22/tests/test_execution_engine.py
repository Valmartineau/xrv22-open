"""Tests pour xrv22/core/execution_engine.py.

Cible les chemins critiques en mode simulation (aucun materiel requis) :
  - Filtrage des robots utilises par la timeline (_robots_used_in_timeline)
  - Verification readiness ciblee (_robots_not_ready_for_timeline)
  - play() : refus si robot utilise non pret + publish engine.error
  - _handle_move : robot_id manquant, registry absent, zone collision
  - _run_handler_safe : exception handler → engine.error + state ERROR
  - _handle_wait : pause temporelle
  - _dispatch : type inconnu → SKIPPED
"""
import threading
import time

import pytest

from xrv22.core.execution_engine import ExecutionEngine, EngineState
from xrv22.core.safety_manager import RobotState
from xrv22.core.state_store import store
from xrv22.library.library_manager import library
from xrv22.robots.robot_registry import RobotRegistry
from xrv22.services.event_bus import bus
from xrv22.timeline.timeline_event import (
    EventState, EventType, TimelineEvent, make_move_event, make_wait_event,
)
from xrv22.timeline.timeline_model import TimelineModel


MOTOR_IDS = [1, 2, 3, 4, 5, 6, 7]


# ── Helpers ──────────────────────────────────────────────────────────

def _capture_topic(topic: str) -> list:
    """Subscribe au topic, renvoie une liste qui se remplit a chaque publish."""
    received = []
    bus.subscribe(topic, lambda payload: received.append(payload))
    return received


def _new_model_with_robot(robot_id: str = "robot_1") -> TimelineModel:
    """TimelineModel avec une piste robot et un MOVE valide (positions home)."""
    model = TimelineModel(name="test")
    track = model.add_robot_track(robot_id, robot_id, "#f6a117")
    evt = make_move_event(
        track_id=track.track_id,
        start_ms=0,
        positions={mid: 2048 for mid in MOTOR_IDS},
        duration_s=0.5,
        label="home",
    )
    model.add_event(evt)
    return model


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def reset_globals():
    """Reset bus + store entre chaque test pour isoler."""
    bus.clear()
    # Vider les snapshots robots du store
    store._robots.clear()  # type: ignore[attr-defined]
    yield
    bus.clear()
    store._robots.clear()  # type: ignore[attr-defined]


@pytest.fixture
def registry(reset_globals, monkeypatch):
    """Registry isole pour le test : remplace le singleton dans les modules."""
    reg = RobotRegistry()
    monkeypatch.setattr("xrv22.core.execution_engine.registry",
                        reg, raising=False)
    monkeypatch.setattr("xrv22.robots.robot_registry.registry", reg)
    yield reg
    # Nettoyage : disconnect les controleurs
    for rid in list(reg.ids()):
        try:
            reg.remove(rid)
        except Exception:
            pass


@pytest.fixture
def engine(reset_globals):
    """ExecutionEngine fresh par test (evite l'etat residuel du singleton)."""
    eng = ExecutionEngine()
    yield eng


# ── _robots_used_in_timeline ─────────────────────────────────────────

class TestRobotsUsedInTimeline:

    def test_empty_model_returns_empty(self, engine):
        engine._model = None
        assert engine._robots_used_in_timeline() == []

    def test_returns_robots_with_move_events(self, engine, registry):
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        assert engine._robots_used_in_timeline() == ["robot_1"]

    def test_ignores_robots_without_move_events(self, engine, registry):
        """Une piste robot sans event MOVE n'est pas utilisee."""
        model = TimelineModel(name="test")
        model.add_robot_track("robot_1", "robot_1", "#f6a117")
        # Robot present mais aucun event
        engine.set_model(model)
        assert engine._robots_used_in_timeline() == []

    def test_multiple_robots(self, engine, registry):
        model = TimelineModel(name="test")
        for rid in ("robot_1", "robot_2"):
            track = model.add_robot_track(rid, rid, "#f6a117")
            evt = make_move_event(
                track_id=track.track_id, start_ms=0,
                positions={1: 2048}, duration_s=0.5)
            model.add_event(evt)
        engine.set_model(model)
        assert engine._robots_used_in_timeline() == ["robot_1", "robot_2"]


# ── _robots_not_ready_for_timeline ───────────────────────────────────

class TestRobotsNotReadyForTimeline:

    def test_all_used_ready_returns_empty(self, engine, registry):
        registry.add("robot_1", MOTOR_IDS, simulation=True)
        # En sim, le controleur demarre IDLE (donc pret)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        assert engine._robots_not_ready_for_timeline() == []

    def test_unused_robot_disconnected_does_not_block(self, engine, registry):
        """Robot 2 dans le registry mais non utilise par la timeline → pas bloquant."""
        registry.add("robot_1", MOTOR_IDS, simulation=True)
        ctrl2 = registry.add("robot_2", MOTOR_IDS, simulation=True)
        # Forcer robot_2 en COMM_LOST (deconnecte) — non utilise par la timeline
        ctrl2._safety.transition_to(RobotState.COMM_LOST)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        # robot_2 hors timeline → ne doit pas apparaitre
        assert engine._robots_not_ready_for_timeline() == []

    def test_used_robot_not_ready_returned(self, engine, registry):
        ctrl = registry.add("robot_1", MOTOR_IDS, simulation=True)
        ctrl._safety.transition_to(RobotState.COMM_LOST)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        assert engine._robots_not_ready_for_timeline() == [
            ("robot_1", RobotState.COMM_LOST),
        ]

    def test_used_robot_absent_from_registry(self, engine, registry):
        """Timeline reference robot_1 mais il n'est pas dans le registry."""
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        assert engine._robots_not_ready_for_timeline() == [("robot_1", "ABSENT")]


# ── play() ──────────────────────────────────────────────────────────

class TestPlay:

    def test_play_refused_if_no_model(self, engine):
        engine._model = None
        assert engine.play() is False

    def test_play_publishes_engine_error_on_not_ready(self, engine, registry):
        ctrl = registry.add("robot_1", MOTOR_IDS, simulation=True)
        ctrl._safety.transition_to(RobotState.COMM_LOST)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        events = _capture_topic("engine.error")

        ok = engine.play()

        assert ok is False
        assert len(events) == 1
        assert events[0]["event_type"] == "PLAY"
        assert "robot_1" in events[0]["message"]


# ── _handle_move ────────────────────────────────────────────────────

class TestHandleMove:

    def test_raises_when_robot_id_unresolvable(self, engine, registry):
        """Track sans robot_id et evt sans param robot_id → RuntimeError."""
        model = TimelineModel(name="test")
        # Piste arduino : track_id="track_arduino", robot_id=""
        evt = TimelineEvent.make(
            track_id="track_arduino",
            event_type=EventType.MOVE,
            start_ms=0, duration_ms=500,
            positions={1: 2048}, duration_s=0.5,
        )
        engine.set_model(model)
        with pytest.raises(RuntimeError, match="robot_id introuvable"):
            engine._handle_move(evt)

    def test_raises_when_robot_not_in_registry(self, engine, registry):
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        evt = next(iter(model.get_track("track_robot_1").all_events()))
        with pytest.raises(RuntimeError, match="non enregistré"):
            engine._handle_move(evt)

    def test_zone_collision_raises_and_publishes(self, engine, registry, monkeypatch):
        """Zone d'exclusion declenchee → engine.zone_collision + RuntimeError."""
        registry.add("robot_1", MOTOR_IDS, simulation=True)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        evt = next(iter(model.get_track("track_robot_1").all_events()))
        events = _capture_topic("engine.zone_collision")
        # Forcer la detection en stubant check_zone_collision
        monkeypatch.setattr(
            "xrv22.core.execution_engine.check_zone_collision",
            lambda positions, zones: "zone_test")

        with pytest.raises(RuntimeError, match="zone_test"):
            engine._handle_move(evt)
        assert len(events) == 1
        assert events[0]["zone_name"] == "zone_test"
        assert events[0]["robot_id"] == "robot_1"


# ── _run_handler_safe ────────────────────────────────────────────────

class TestRunHandlerSafe:

    def test_exception_publishes_engine_error_and_marks_state_error(
            self, engine, registry):
        registry.add("robot_1", MOTOR_IDS, simulation=True)
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        evt = next(iter(model.get_track("track_robot_1").all_events()))
        events = _capture_topic("engine.error")

        def boom(_evt):
            raise RuntimeError("BOOM")

        engine._run_handler_safe(boom, evt)

        assert engine.state == EngineState.ERROR
        assert model.get_event(evt.event_id).state == EventState.ERROR
        assert len(events) == 1
        assert events[0]["message"] == "BOOM"
        assert events[0]["event_type"] == EventType.MOVE


# ── _handle_wait ────────────────────────────────────────────────────

class TestHandleWait:

    def test_wait_sleeps_for_event_duration(self, engine):
        evt = make_wait_event("track_arduino", 0, 80)
        t0 = time.time()
        engine._handle_wait(evt)
        elapsed = time.time() - t0
        # 80ms d'attente, marge large pour eviter flakiness CI
        assert 0.06 <= elapsed < 0.5


# ── _dispatch ────────────────────────────────────────────────────────

class TestDispatch:

    def test_unknown_event_type_marked_skipped(self, engine, registry):
        model = _new_model_with_robot("robot_1")
        engine.set_model(model)
        # Forger un evt avec un type inconnu
        evt = TimelineEvent.make(
            track_id="track_robot_1",
            event_type="UNKNOWN_TYPE",
            start_ms=0, duration_ms=100,
        )
        # add_event valide collision uniquement, accepte le type
        model._tracks["track_robot_1"]._events[evt.event_id] = evt

        engine._dispatch(evt)

        assert model.get_event(evt.event_id).state == EventState.SKIPPED


# ── _handle_sync_marker ──────────────────────────────────────────────

class TestHandleSyncMarker:

    def test_sync_marker_timeout_raises(self, engine):
        evt = TimelineEvent.make(
            track_id="track_arduino",
            event_type=EventType.SYNC_MARKER,
            start_ms=0, duration_ms=10,
            group_id="grp_test",
            robot_count=2,
            timeout_s=0.05,
        )
        with pytest.raises(RuntimeError, match="barrier cassée"):
            engine._handle_sync_marker(evt)
        # Apres timeout, la barrier doit etre nettoyee pour permettre un retry
        assert "grp_test" not in engine._sync_barriers

    def test_sync_marker_two_threads_synchronized(self, engine):
        """Deux appels concurrents au meme groupe se synchronisent."""
        evt = TimelineEvent.make(
            track_id="track_arduino",
            event_type=EventType.SYNC_MARKER,
            start_ms=0, duration_ms=10,
            group_id="grp_sync",
            robot_count=2,
            timeout_s=2.0,
        )
        results = []

        def runner():
            try:
                engine._handle_sync_marker(evt)
                results.append("ok")
            except Exception as exc:
                results.append(repr(exc))

        threads = [threading.Thread(target=runner) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
        assert results == ["ok", "ok"]
