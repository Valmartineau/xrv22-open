"""Tests pour xrv22/core/event_scheduler.py.

Cible :
  - Transitions d'etat (IDLE, PLAYING, PAUSED, STOPPED)
  - Idempotence (play() depuis PLAYING refuse, pause() depuis IDLE refuse)
  - Regression : stop() NE DOIT PAS reset les states (bug corrige 2026-05-07)
  - Reset des states au play() (chaque lecture repart fraiche)
  - Callbacks on_events / on_tick / on_done
  - Drain du thread a stop()
"""
import threading
import time

import pytest

from xrv22.core.event_scheduler import EventScheduler, SchedulerState
from xrv22.services.event_bus import bus
from xrv22.timeline.timeline_event import (
    EventState, make_move_event, make_wait_event,
)
from xrv22.timeline.timeline_model import TimelineModel


# ── Helpers ──────────────────────────────────────────────────────────

def _model_with_one_event(start_ms: int = 0,
                           duration_ms: int = 100) -> TimelineModel:
    """Modele minimal : une piste robot + un MOVE."""
    m = TimelineModel(name="test")
    track = m.add_robot_track("robot_1", "robot_1", "#f6a117")
    evt = make_move_event(
        track_id=track.track_id, start_ms=start_ms,
        positions={1: 2048}, duration_s=duration_ms / 1000.0,
    )
    m.add_event(evt)
    return m


@pytest.fixture
def reset_bus():
    bus.clear()
    yield
    bus.clear()


# ── Etat initial ────────────────────────────────────────────────────

class TestInitialState:

    def test_initial_state_idle(self, reset_bus):
        sch = EventScheduler(_model_with_one_event())
        assert sch.state == SchedulerState.IDLE
        assert sch.elapsed_ms == 0


# ── play() ──────────────────────────────────────────────────────────

class TestPlay:

    def test_play_transitions_to_playing(self, reset_bus):
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        assert sch.play() is True
        assert sch.state == SchedulerState.PLAYING
        sch.stop()

    def test_play_when_already_playing_refused(self, reset_bus):
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        sch.play()
        assert sch.play() is False
        sch.stop()

    def test_play_resets_states(self, reset_bus):
        """Un nouveau play() doit remettre les events en PENDING."""
        m = _model_with_one_event(duration_ms=10_000)
        evt_id = next(iter(m.get_track("track_robot_1").all_events())).event_id
        m.mark_event_state(evt_id, EventState.ERROR)
        sch = EventScheduler(m)
        sch.play()
        try:
            assert m.get_event(evt_id).state == EventState.PENDING
        finally:
            sch.stop()

    def test_play_publishes_timeline_play_topic(self, reset_bus):
        events = []
        bus.subscribe("timeline.play", lambda p: events.append(p))
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        sch.play(from_ms=200)
        try:
            assert len(events) == 1
            assert events[0]["from_ms"] == 200
        finally:
            sch.stop()


# ── pause() ────────────────────────────────────────────────────────

class TestPause:

    def test_pause_when_not_playing_refused(self, reset_bus):
        sch = EventScheduler(_model_with_one_event())
        assert sch.pause() is False

    def test_pause_transitions_to_paused(self, reset_bus):
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        sch.play()
        time.sleep(0.05)
        assert sch.pause() is True
        assert sch.state == SchedulerState.PAUSED
        sch.stop()


# ── stop() — REGRESSION ─────────────────────────────────────────────

class TestStop:

    def test_stop_does_not_reset_event_states(self, reset_bus):
        """REGRESSION 2026-05-07 : stop() ecrasait ERROR en PENDING.

        Si un handler crashe, _run_handler_safe set ERROR puis appelle stop().
        La visualisation timeline DOIT garder le bloc rouge.
        """
        m = _model_with_one_event(duration_ms=10_000)
        evt_id = next(iter(m.get_track("track_robot_1").all_events())).event_id
        sch = EventScheduler(m)
        sch.play()
        time.sleep(0.05)
        m.mark_event_state(evt_id, EventState.ERROR)
        sch.stop()
        # Apres stop, l'etat ERROR doit etre preserve pour debug visuel
        assert m.get_event(evt_id).state == EventState.ERROR

    def test_stop_resets_cursor_to_zero(self, reset_bus):
        m = _model_with_one_event(duration_ms=10_000)
        sch = EventScheduler(m)
        sch.play()
        time.sleep(0.1)
        assert sch.elapsed_ms > 0
        sch.stop()
        assert sch.elapsed_ms == 0
        assert m.cursor_ms == 0

    def test_stop_drains_thread_within_timeout(self, reset_bus):
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        sch.play()
        time.sleep(0.05)
        t0 = time.time()
        sch.stop()
        elapsed = time.time() - t0
        # stop() doit rendre la main rapidement (timeout interne 3s, en pratique <0.2s)
        assert elapsed < 1.0
        assert sch._thread is None


# ── Callbacks ───────────────────────────────────────────────────────

class TestCallbacks:

    def test_on_events_called_when_event_due(self, reset_bus):
        m = _model_with_one_event(start_ms=0, duration_ms=200)
        sch = EventScheduler(m)
        received = []
        sch.set_callbacks(on_events=lambda evts: received.extend(evts))
        sch.play()
        try:
            # Laisser au moins un tick passer (TICK_MS=50)
            time.sleep(0.15)
        finally:
            sch.stop()
        assert len(received) == 1

    def test_on_done_called_when_timeline_finished(self, reset_bus):
        m = _model_with_one_event(start_ms=0, duration_ms=80)
        sch = EventScheduler(m)
        done_flag = threading.Event()
        sch.set_callbacks(
            on_events=lambda evts: None,
            on_done=done_flag.set,
        )
        sch.play()
        try:
            assert done_flag.wait(timeout=2.0)
        finally:
            sch.stop()

    def test_on_tick_called_periodically(self, reset_bus):
        m = _model_with_one_event(duration_ms=10_000)
        sch = EventScheduler(m)
        ticks = []
        sch.set_callbacks(
            on_events=lambda evts: None,
            on_tick=lambda ms: ticks.append(ms),
        )
        sch.play()
        try:
            time.sleep(0.2)
        finally:
            sch.stop()
        # ~4 ticks attendus en 200ms (TICK_MS=50). Marge generouse.
        assert len(ticks) >= 2


# ── seek() ──────────────────────────────────────────────────────────

class TestSeek:

    def test_seek_updates_elapsed(self, reset_bus):
        sch = EventScheduler(_model_with_one_event(duration_ms=10_000))
        sch.seek(2500)
        assert sch.elapsed_ms == 2500

    def test_seek_negative_clamped_to_zero(self, reset_bus):
        sch = EventScheduler(_model_with_one_event())
        sch.seek(-500)
        assert sch.elapsed_ms == 0
