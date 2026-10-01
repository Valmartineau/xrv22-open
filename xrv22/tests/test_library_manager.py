"""Tests pour xrv22/library/library_manager.py."""
import pytest
from pathlib import Path
from xrv22.library.library_manager import LibraryManager
from xrv22.library.models import PositionModel, SuiteModel


@pytest.fixture
def lib(tmp_path):
    """LibraryManager isolé dans un dossier temporaire."""
    # Reset singleton pour isolation
    LibraryManager._instance = None
    lm = LibraryManager(library_root=tmp_path / "XRV22_LIBRARY")
    yield lm
    LibraryManager._instance = None


class TestStructure:

    def test_library_dirs_created(self, lib):
        assert (lib.root / "logs").is_dir()
        assert (lib.root / "global").is_dir()
        assert (lib.root / "projects").is_dir()

    def test_startup_params_exist(self, lib):
        params = lib.get_startup_params()
        assert "simulation_mode" in params


class TestProject:

    def test_new_project(self, lib):
        assert lib.new_project("mon_projet") is True
        assert lib.project_name == "mon_projet"
        assert lib.loaded is True

    def test_load_project(self, lib):
        lib.new_project("p1")
        path = str(lib.project_path)
        # Reset et recharge
        lib._project_path = None
        lib._project_name = ""
        assert lib.load_project(path) is True
        assert lib.project_name == "p1"

    def test_save_project(self, lib):
        lib.new_project("p1")
        assert lib.save_project() is True

    def test_list_projects(self, lib):
        lib.new_project("a")
        lib.new_project("b")
        projects = lib.list_projects()
        names = [p.name for p in projects]
        assert "a" in names
        assert "b" in names

    def test_set_project_name(self, lib):
        lib.new_project("old")
        lib.set_project_name("  new  ")
        assert lib.project_name == "new"

    def test_set_project_name_empty_ignored(self, lib):
        lib.new_project("keep")
        lib.set_project_name("   ")
        assert lib.project_name == "keep"


class TestPositions:

    def test_save_and_get(self, lib):
        lib.new_project("test_pos")
        pos = PositionModel(id="p1", name="Home", positions={1: 2048})
        assert lib.save_position(pos) is True
        got = lib.get_position("p1")
        assert got is not None
        assert got.name == "Home"

    def test_list_positions(self, lib):
        lib.new_project("test_pos")
        lib.save_position(PositionModel(id="p1", name="A", positions={}))
        lib.save_position(PositionModel(id="p2", name="B", positions={}))
        assert len(lib.list_positions()) == 2

    def test_delete_position(self, lib):
        lib.new_project("test_pos")
        lib.save_position(PositionModel(id="p1", name="A", positions={}))
        ok, msg = lib.delete_position("p1")
        assert ok
        assert lib.get_position("p1") is None

    def test_rename_position(self, lib):
        lib.new_project("test_pos")
        lib.save_position(PositionModel(id="p1", name="Old", positions={}))
        assert lib.rename_position("p1", "New") is True
        assert lib.get_position("p1").name == "New"

    def test_get_position_by_name(self, lib):
        lib.new_project("test_pos")
        lib.save_position(PositionModel(id="p1", name="Target", positions={}))
        found = lib.get_position_by_name("Target")
        assert found is not None
        assert found.id == "p1"


class TestGlobalProfiles:

    def test_default_limits(self, lib):
        limits = lib.get_default_limits()
        assert 1 in limits
        assert len(limits[1]) == 2

    def test_default_home(self, lib):
        home = lib.get_default_home()
        assert 1 in home

    def test_save_and_reload_profiles(self, lib):
        new_limits = {1: (100, 3000)}
        new_home = {1: 1500}
        lib.save_global_profiles(new_limits, new_home)
        got = lib.get_default_limits()
        assert got[1] == (100, 3000)


class TestAtomicWrite:

    def test_write_json_creates_file(self, lib):
        path = lib.root / "test_file.json"
        assert lib._write_json(path, {"key": "value"}) is True
        assert path.exists()

    def test_read_json_missing(self, lib):
        assert lib._read_json(lib.root / "nope.json") is None
