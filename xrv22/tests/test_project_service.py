"""Tests pour xrv22/services/project_service.py.

Cible :
  - new_project / new_project_at — creation via library
  - save() — snapshot complet (robots + timeline + startup params)
  - load() — restauration robots + timeline depuis disque
  - Round-trip : sauvegarde puis recharge → meme contenu
  - Recents : push_recent dedoublonne et limite a MAX_RECENT
  - Reproduire l'erreur "Échec sauvegarde timeline" qui apparaissait dans les logs
"""
import pytest
from pathlib import Path

from xrv22.library.library_manager import LibraryManager
from xrv22.library.models import RobotConfigModel
from xrv22.services.event_bus import bus
from xrv22.services.project_service import ProjectService, MAX_RECENT
from xrv22.timeline.timeline_event import make_move_event
from xrv22.timeline.timeline_model import TimelineModel


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def lib(tmp_path, monkeypatch):
    """LibraryManager isole dans tmp_path + bus reset.

    Patche aussi la reference dans project_service pour que le service
    utilise la library temporaire.
    """
    bus.clear()
    LibraryManager._instance = None  # type: ignore[attr-defined]
    lm = LibraryManager(library_root=tmp_path / "XRV22_LIBRARY")
    monkeypatch.setattr("xrv22.services.project_service.library", lm)
    yield lm
    LibraryManager._instance = None  # type: ignore[attr-defined]
    bus.clear()


@pytest.fixture
def service(lib):
    """ProjectService avec un TimelineModel attache."""
    svc = ProjectService()
    model = TimelineModel(name="default")
    svc.set_timeline(model)
    return svc


# ── new_project ─────────────────────────────────────────────────────

class TestNewProject:

    def test_new_project_creates_files(self, service, lib):
        assert service.new_project("test_proj") is True
        assert lib.loaded is True
        assert lib.project_name == "test_proj"
        # Verifier que le fichier projet.xrv22 existe
        assert (lib.project_dir / "projet.xrv22").exists()
        # Sous-dossiers crees
        for sub in ("positions", "suites", "scenarios", "timeline",
                     "robots", "hardware"):
            assert (lib.project_dir / sub).is_dir()

    def test_new_project_publishes_event(self, service, lib):
        events = []
        bus.subscribe("project.new", lambda p: events.append(p))
        service.new_project("p1")
        assert len(events) == 1
        assert events[0]["name"] == "p1"

    def test_new_project_resets_timeline(self, service, lib):
        # Ajouter un evenement, puis nouveau projet → timeline vide
        model = service._timeline_ref
        track = model.add_robot_track("robot_1", "robot_1", "#f6a117")
        evt = make_move_event(track.track_id, 0, {1: 2048}, 1.0)
        model.add_event(evt)
        service.new_project("fresh")
        # La piste robot_1 a ete retiree par _reset_timeline
        assert model.get_track("track_robot_1") is None

    def test_new_project_at_uses_arbitrary_path(self, service, lib, tmp_path):
        # new_project_at attend le repertoire DU projet (pas son parent)
        external = tmp_path / "external_dir" / "ext_proj"
        assert service.new_project_at("ext_proj", str(external)) is True
        assert lib.loaded is True
        assert (external / "projet.xrv22").exists()


# ── save() ──────────────────────────────────────────────────────────

class TestSave:

    def test_save_when_no_project_loaded_returns_false(self, lib):
        # ProjectService cree mais pas de projet charge
        svc = ProjectService()
        svc.set_timeline(TimelineModel(name="default"))
        assert svc.save() is False

    def test_save_after_new_project_succeeds(self, service, lib):
        service.new_project("save_test")
        assert service.save() is True

    def test_save_publishes_project_saved(self, service, lib):
        service.new_project("save_test")
        events = []
        bus.subscribe("project.saved", lambda p: events.append(p))
        service.save()
        assert len(events) == 1

    def test_save_writes_timeline_json(self, service, lib):
        service.new_project("save_test")
        # Ajouter un event
        model = service._timeline_ref
        track = model.add_robot_track("robot_1", "robot_1", "#f6a117")
        evt = make_move_event(track.track_id, 0, {1: 2048}, 1.0)
        model.add_event(evt)
        service.save()
        # timeline.json doit exister et contenir l'event
        tl_path = lib.project_dir / "timeline" / "timeline.json"
        assert tl_path.exists()
        import json
        data = json.loads(tl_path.read_text())
        assert data["name"] == "default"
        # L'event est dans une track
        assert len(data["tracks"]) >= 1


# ── load() ──────────────────────────────────────────────────────────

class TestLoad:

    def test_load_nonexistent_path_returns_false(self, service):
        assert service.load("/path/that/does/not/exist") is False

    def test_round_trip_preserves_timeline(self, service, lib):
        """Save puis load doivent restituer la meme timeline."""
        service.new_project("rt_test")
        model = service._timeline_ref
        track = model.add_robot_track("robot_1", "robot_1", "#f6a117")
        evt = make_move_event(track.track_id, 100, {1: 2048, 2: 1500}, 1.5,
                                label="pose_test")
        model.add_event(evt)
        path = str(lib.project_path)
        service.save()

        # Reset timeline et reload
        new_model = TimelineModel(name="default")
        service.set_timeline(new_model)
        assert service.load(path) is True
        # La piste et l'event doivent etre restaures
        track2 = new_model.get_track("track_robot_1")
        assert track2 is not None
        events = list(track2.all_events())
        assert len(events) == 1
        assert events[0].label == "pose_test"
        assert events[0].start_ms == 100

    def test_load_publishes_project_loaded(self, service, lib):
        service.new_project("rt_test")
        path = str(lib.project_path)
        events = []
        bus.subscribe("project.loaded", lambda p: events.append(p))
        service.load(path)
        assert len(events) == 1
        assert events[0]["name"] == "rt_test"


# ── Recents ─────────────────────────────────────────────────────────

class TestRecents:

    def test_push_recent_adds_to_front(self, service, lib):
        service.new_project("p1")
        service._push_recent("/tmp/p1")
        assert service.recent[0] == "/tmp/p1"

    def test_push_recent_dedups(self, service, lib):
        service.new_project("p1")
        service._push_recent("/tmp/p1")
        service._push_recent("/tmp/p2")
        service._push_recent("/tmp/p1")
        # /tmp/p1 doit etre en tete, et n'apparaitre qu'une fois
        assert service.recent[0] == "/tmp/p1"
        assert service.recent.count("/tmp/p1") == 1

    def test_push_recent_clamped_to_max(self, service, lib):
        service.new_project("p1")
        for i in range(MAX_RECENT + 5):
            service._push_recent(f"/tmp/p{i}")
        assert len(service.recent) == MAX_RECENT


# ── Snapshot timeline (regression "Échec sauvegarde timeline") ──────

class TestTimelineSnapshot:

    def test_snapshot_default_writes_timeline_json(self, service, lib):
        """Le scenario 'default' ecrit dans timeline/timeline.json."""
        service.new_project("snap_default")
        model = service._timeline_ref
        track = model.add_robot_track("robot_1", "robot_1", "#f6a117")
        evt = make_move_event(track.track_id, 0, {1: 2048}, 1.0)
        model.add_event(evt)
        # Appel direct au snapshot (interne)
        service._snapshot_timeline()
        assert (lib.project_dir / "timeline" / "timeline.json").exists()

    def test_snapshot_named_scenario_writes_to_scenario_file(self, service, lib):
        """Un scenario nomme doit etre stocke dans son ScenarioModel."""
        from xrv22.library.models import ScenarioModel
        service.new_project("snap_named")
        # Creer un scenario avec ce nom dans la library
        scenario = ScenarioModel(id="sc1", name="mon_scenario", timeline_data={})
        lib.save_scenario(scenario)
        # Renommer le timeline avec ce nom
        service._timeline_ref.name = "mon_scenario"
        track = service._timeline_ref.add_robot_track(
            "robot_1", "robot_1", "#f6a117")
        evt = make_move_event(track.track_id, 0, {1: 2048}, 1.0)
        service._timeline_ref.add_event(evt)
        service._snapshot_timeline()
        # Le scenario en library doit avoir le timeline_data rempli
        updated = next(s for s in lib.list_scenarios() if s.name == "mon_scenario")
        assert updated.timeline_data
        assert "tracks" in updated.timeline_data

    def test_snapshot_when_no_timeline_ref_no_op(self, lib):
        """Si _timeline_ref est None, _snapshot_timeline ne crash pas."""
        svc = ProjectService()
        svc.set_timeline(TimelineModel("default"))
        # Detacher la reference
        svc._timeline_ref = None
        # Doit etre un no-op silencieux
        svc._snapshot_timeline()


# ── Snapshot robots ─────────────────────────────────────────────────

class TestSnapshotRobots:

    def test_snapshot_robots_writes_per_robot_files(self, service, lib, monkeypatch):
        """_snapshot_robots ecrit un fichier par robot enregistre."""
        from xrv22.robots.robot_registry import RobotRegistry
        from xrv22.core.state_store import store

        reg = RobotRegistry()
        monkeypatch.setattr("xrv22.services.project_service.registry",
                             reg, raising=False)
        # Patcher l'import lazy aussi
        import xrv22.services.project_service as ps
        # _snapshot_robots fait un import lazy depuis robot_registry
        monkeypatch.setattr("xrv22.robots.robot_registry.registry", reg)

        service.new_project("robots_snap")
        # Ajouter un robot sim au registry
        ctrl = reg.add("robot_1", [1, 2, 3, 4, 5, 6, 7], simulation=True)
        ctrl.connect("sim_port")
        ctrl.update_positions({1: 2048, 2: 1500})

        service._snapshot_robots()
        robot_file = lib.project_dir / "robots" / "robot_1.robot.json"
        assert robot_file.exists()
