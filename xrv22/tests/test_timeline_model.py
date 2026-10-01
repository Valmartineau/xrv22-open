"""Tests pour xrv22/timeline/timeline_model.py."""
import pytest
from xrv22.timeline.timeline_model import TimelineModel
from xrv22.timeline.timeline_event import TimelineEvent, EventType


@pytest.fixture
def model():
    """TimelineModel vierge."""
    return TimelineModel("test")


class TestSystemTracks:

    def test_has_arduino_and_sensor_tracks(self, model):
        ids = [t.track_id for t in model.ordered_tracks()]
        assert "track_arduino" in ids
        assert "track_sensors" in ids

    def test_initial_duration_zero(self, model):
        assert model.duration_ms() == 0


class TestRobotTrack:

    def test_add_robot_track(self, model):
        track = model.add_robot_track("r1", "Robot 1", "#ff0000")
        assert track.track_id == "track_r1"

    def test_add_duplicate_returns_same(self, model):
        t1 = model.add_robot_track("r1", "Robot 1", "#ff0000")
        t2 = model.add_robot_track("r1", "Robot 1", "#ff0000")
        assert t1 is t2

    def test_robot_track_before_system(self, model):
        model.add_robot_track("r1", "Robot 1", "#ff0000")
        order = [t.track_id for t in model.ordered_tracks()]
        assert order.index("track_r1") < order.index("track_arduino")

    def test_remove_robot_track(self, model):
        model.add_robot_track("r1", "Robot 1", "#ff0000")
        assert model.remove_robot_track("r1") is True
        assert model.get_track("track_r1") is None

    def test_remove_nonexistent(self, model):
        assert model.remove_robot_track("nope") is False


class TestMoveTrack:

    def test_move_track(self, model):
        model.add_robot_track("r1", "Robot 1", "#ff0000")
        model.add_robot_track("r2", "Robot 2", "#00ff00")
        order_before = [t.track_id for t in model.ordered_tracks()]
        assert order_before[0] == "track_r1"
        assert model.move_track("track_r2", 0) is True
        order_after = [t.track_id for t in model.ordered_tracks()]
        assert order_after[0] == "track_r2"

    def test_move_same_index(self, model):
        model.add_robot_track("r1", "Robot 1", "#ff0000")
        assert model.move_track("track_r1", 0) is False

    def test_move_nonexistent(self, model):
        assert model.move_track("nope", 0) is False


class TestCursor:

    def test_default_cursor(self, model):
        assert model.cursor_ms == 0

    def test_set_cursor(self, model):
        model.set_cursor(1500)
        assert model.cursor_ms == 1500

    def test_cursor_no_negative(self, model):
        model.set_cursor(-100)
        assert model.cursor_ms == 0


class TestSerialization:

    def test_round_trip(self, model):
        model.add_robot_track("r1", "Robot 1", "#ff0000")
        d = model.to_dict()
        restored = TimelineModel.from_dict(d)
        assert restored.name == "test"
        ids = [t.track_id for t in restored.ordered_tracks()]
        assert "track_r1" in ids

    def test_stats(self, model):
        s = model.stats()
        assert s["name"] == "test"
        assert s["track_count"] >= 2
        assert s["event_count"] == 0
