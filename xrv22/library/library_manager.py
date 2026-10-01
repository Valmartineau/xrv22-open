"""
xrv22/library/library_manager.py
─────────────────────────────────
Gestionnaire centralisé de la librairie XRV22.

PRINCIPE : Une seule source de vérité.
Toutes les données persistantes passent par ce module.
Remplace ConfigManager + SessionStore de la V21.

Architecture :
  XRV22_LIBRARY/  (à la racine du projet)
  ├── parametres_ouverture.json
  ├── logs/
  ├── global/
  │   └── robot_profiles.json
  └── projects/
      └── <nom>/
          ├── projet.xrv22
          ├── positions/        (un .pos.json par position)
          ├── suites/           (un .suite.json par suite)
          ├── scenarios/        (un .scenario.json par scénario)
          ├── timeline/         (timeline.json)
          ├── robots/           (un .robot.json par robot)
          ├── hardware/         (hardware.json)
          └── motion_profiles/  (un .profile.json par profil)
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xrv22.library.models import (
    PositionModel, SuiteModel, ScenarioModel,
    RobotConfigModel, MotionProfileModel, ProjectInfo,
    HardwareConfigModel, ZoneModel, AssettePreset,
    _now,
)

import logging
_LOG = logging.getLogger("LibraryManager")

# Limites de sécurité par défaut (valeurs calibrées XR200)
_DEFAULT_LIMITS: Dict[int, Tuple[int, int]] = {
    1: (370, 3450),
    2: (1070, 3000),
    3: (0, 4095),
    4: (915, 3140),
    5: (930, 3380),
    6: (0, 4095),
    7: (1615, 2860),
}

_DEFAULT_HOME: Dict[int, int] = {
    1: 2050, 2: 900, 3: 900, 4: 3140, 5: 900, 6: 2040, 7: 2100,
}

_VERSION = 22
_DEFAULT_LIBRARY = Path(__file__).resolve().parent.parent.parent / "XRV22_LIBRARY"


class LibraryManager:
    """
    Singleton — unique couche de persistance XRV22.
    Thread-safe.
    """

    _instance: Optional["LibraryManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, library_root: Optional[Path] = None) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._root = library_root or _DEFAULT_LIBRARY
        self._lock = threading.Lock()

        # Projet courant
        self._project_path: Optional[Path] = None
        self._project_name: str = ""

        # Caches mémoire
        self._positions: Dict[str, PositionModel] = {}
        self._suites: Dict[str, SuiteModel] = {}
        self._scenarios: Dict[str, ScenarioModel] = {}
        self._robots: Dict[str, RobotConfigModel] = {}
        self._profiles: Dict[str, MotionProfileModel] = {}
        self._zones: Dict[str, ZoneModel] = {}
        self._assiettes: Dict[str, AssettePreset] = {}
        self._timeline: dict = {"tracks": [], "events": []}
        self._hardware = HardwareConfigModel()

        # Créer la structure de base
        self._ensure_library_structure()

    # ══════════════════════════════════════════════════════════════
    #  Propriétés
    # ══════════════════════════════════════════════════════════════

    @property
    def root(self) -> Path:
        return self._root

    @property
    def logs_dir(self) -> Path:
        return self._root / "logs"

    @property
    def project_name(self) -> str:
        return self._project_name

    @property
    def project_dir(self) -> Optional[Path]:
        if self._project_path:
            return self._project_path.parent
        return None

    @property
    def loaded(self) -> bool:
        return self._project_path is not None

    @property
    def project_path(self) -> Optional[Path]:
        """Chemin complet du fichier projet (.xrv22)."""
        return self._project_path

    def set_project_name(self, name: str) -> None:
        """Renomme le projet (avec validation)."""
        clean = name.strip()
        if clean:
            self._project_name = clean

    # ══════════════════════════════════════════════════════════════
    #  Structure librairie
    # ══════════════════════════════════════════════════════════════

    def _ensure_library_structure(self) -> None:
        """Crée l'arborescence de base si absente."""
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "logs").mkdir(exist_ok=True)
        (self._root / "global").mkdir(exist_ok=True)
        (self._root / "projects").mkdir(exist_ok=True)

        # Profils globaux par défaut
        gp = self._root / "global" / "robot_profiles.json"
        if not gp.exists():
            self._write_json(gp, {
                "default_limits": {str(k): list(v) for k, v in _DEFAULT_LIMITS.items()},
                "default_home": {str(k): v for k, v in _DEFAULT_HOME.items()},
            })

        # Paramètres d'ouverture par défaut
        po = self._root / "parametres_ouverture.json"
        if not po.exists():
            self._write_json(po, {
                "last_project_path": "",
                "simulation_mode": False,
                "active_robot_id": "robot_1",
                "window_geometry": "",
                "recent_projects": [],
                "auto_connect": True,
            })

    def _ensure_project_dirs(self, proj_dir: Path) -> None:
        """Crée les sous-dossiers d'un projet."""
        for sub in ("positions", "suites", "scenarios", "timeline",
                    "robots", "hardware", "motion_profiles"):
            (proj_dir / sub).mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════════
    #  Paramètres d'ouverture
    # ══════════════════════════════════════════════════════════════

    def get_startup_params(self) -> dict:
        """Lit parametres_ouverture.json."""
        return self._read_json(self._root / "parametres_ouverture.json") or {}

    def save_startup_params(self, **kwargs) -> bool:
        """Met à jour parametres_ouverture.json (merge)."""
        params = self.get_startup_params()
        params.update(kwargs)
        return self._write_json(self._root / "parametres_ouverture.json", params)

    # ══════════════════════════════════════════════════════════════
    #  Profils globaux
    # ══════════════════════════════════════════════════════════════

    def get_default_limits(self) -> Dict[int, Tuple[int, int]]:
        """Retourne les limites par défaut depuis la librairie."""
        data = self._read_json(self._root / "global" / "robot_profiles.json") or {}
        limits = data.get("default_limits", {})
        if limits:
            return {int(k): tuple(v) for k, v in limits.items()}
        return dict(_DEFAULT_LIMITS)

    def get_default_home(self) -> Dict[int, int]:
        """Retourne les positions home par défaut."""
        data = self._read_json(self._root / "global" / "robot_profiles.json") or {}
        home = data.get("default_home", {})
        if home:
            return {int(k): int(v) for k, v in home.items()}
        return dict(_DEFAULT_HOME)

    def save_global_profiles(self, limits: Dict[int, Tuple[int, int]],
                              home: Dict[int, int]) -> bool:
        """Sauvegarde les profils globaux."""
        return self._write_json(self._root / "global" / "robot_profiles.json", {
            "default_limits": {str(k): list(v) for k, v in limits.items()},
            "default_home": {str(k): v for k, v in home.items()},
        })

    # ══════════════════════════════════════════════════════════════
    #  Projet — CRUD
    # ══════════════════════════════════════════════════════════════

    def new_project(self, name: str) -> bool:
        """Crée un nouveau projet vide dans la librairie locale."""
        proj_dir = self._root / "projects" / name
        return self.new_project_at(name, proj_dir)

    def new_project_at(self, name: str, proj_dir: Path) -> bool:
        """Crée un nouveau projet vide à un emplacement arbitraire."""
        self._ensure_project_dirs(proj_dir)
        meta = {
            "version": _VERSION,
            "project_name": name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        proj_file = proj_dir / "projet.xrv22"
        self._write_json(proj_file, meta)
        self._project_path = proj_file
        self._project_name = name
        self._clear_caches()
        self.save_startup_params(last_project_path=str(proj_file))
        return True

    def load_project(self, path: str) -> bool:
        """Charge un projet depuis son chemin (.xrv22 ou dossier)."""
        p = Path(path)
        if p.is_dir():
            xrv = list(p.glob("*.xrv22"))
            if xrv:
                p = xrv[0]
            else:
                return False
        if not p.exists():
            return False

        proj_dir = p.parent
        meta = self._read_json(p) or {}
        self._project_path = p
        self._project_name = meta.get("project_name", proj_dir.name)
        self._clear_caches()
        self._load_all_caches(proj_dir)
        self.save_startup_params(last_project_path=str(p))
        return True

    def save_project(self) -> bool:
        """Sauvegarde les métadonnées du projet courant."""
        if not self._project_path:
            return False
        meta = self._read_json(self._project_path) or {}
        meta["modified_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta["version"] = _VERSION
        meta["project_name"] = self._project_name
        return self._write_json(self._project_path, meta)

    def get_project_settings(self) -> dict:
        """Retourne le dict settings du projet courant (ou {} si absent)."""
        if not self._project_path:
            return {}
        if not self._project_path.exists():
            return {}
        try:
            data = self._read_json(self._project_path)
            if isinstance(data, dict):
                return data.get("settings", {}) or {}
            return {}
        except Exception:
            return {}

    def set_project_settings(self, settings: dict) -> bool:
        """Persiste les settings dans projet.xrv22 (merge non destructif)."""
        if not self._project_path:
            return False
        if not self._project_path.exists():
            return False
        try:
            data = self._read_json(self._project_path)
            if not isinstance(data, dict):
                return False
            data["settings"] = settings
            return self._write_json(self._project_path, data)
        except Exception as e:
            _LOG.warning("set_project_settings failed: %s", e)
            return False

    def export_project(self, dest_dir: Path) -> bool:
        """Exporte le projet courant vers un dossier arbitraire."""
        src = self.project_dir
        if src is None or not src.exists():
            return False
        dest = dest_dir / src.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return True

    def list_projects(self) -> List[ProjectInfo]:
        """Liste tous les projets de la librairie."""
        projects_dir = self._root / "projects"
        result = []
        if not projects_dir.exists():
            return result
        for d in sorted(projects_dir.iterdir()):
            if not d.is_dir():
                continue
            xrv = list(d.glob("*.xrv22"))
            meta_path = xrv[0] if xrv else d / "projet.xrv22"
            meta = self._read_json(meta_path) if meta_path.exists() else {}
            pos_dir = d / "positions"
            suite_dir = d / "suites"
            pos_count = len(list(pos_dir.glob("*.pos.json"))) if pos_dir.exists() else 0
            suite_count = len(list(suite_dir.glob("*.suite.json"))) if suite_dir.exists() else 0
            result.append(ProjectInfo(
                name=meta.get("project_name", d.name),
                path=str(meta_path),
                version=meta.get("version", 0),
                created_at=meta.get("created_at", ""),
                modified_at=meta.get("modified_at", ""),
                position_count=pos_count,
                suite_count=suite_count,
            ))
        return result

    # ══════════════════════════════════════════════════════════════
    #  Positions — CRUD (un fichier par position)
    # ══════════════════════════════════════════════════════════════

    def save_position(self, pos: PositionModel) -> bool:
        """Sauvegarde une position (création ou mise à jour)."""
        if not self._project_path:
            return False
        pos.modified_at = _now()
        with self._lock:
            path = self.project_dir / "positions" / f"{pos.id}.pos.json"
            ok = self._write_json(path, pos.to_dict())
            if ok:
                self._positions[pos.id] = pos
        return ok

    def get_position(self, pos_id: str) -> Optional[PositionModel]:
        """Retourne une position par ID."""
        with self._lock:
            return self._positions.get(pos_id)

    def get_position_by_name(self, name: str) -> Optional[PositionModel]:
        """Retourne une position par nom."""
        with self._lock:
            for p in self._positions.values():
                if p.name == name:
                    return p
        return None

    def list_positions(self, category: Optional[str] = None) -> List[PositionModel]:
        """Liste les positions, optionnellement par catégorie."""
        with self._lock:
            if category:
                return [p for p in self._positions.values() if p.category == category]
            return list(self._positions.values())

    def delete_position(self, pos_id: str) -> Tuple[bool, str]:
        """Supprime une position. Refuse si référencée dans une suite."""
        with self._lock:
            for suite in self._suites.values():
                for step in suite.steps:
                    if step.get("position_id") == pos_id:
                        return False, f"Position utilisée dans la suite '{suite.name}'"
            if not self._project_path:
                return False, "Aucun projet chargé"
            path = self.project_dir / "positions" / f"{pos_id}.pos.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                import logging
                logging.getLogger("LibraryManager").error(
                    "Suppression échouée : %s — %s", path, exc)
                return False, f"Erreur suppression fichier : {exc}"
            self._positions.pop(pos_id, None)
        return True, "OK"

    def rename_position(self, pos_id: str, new_name: str) -> bool:
        """Renomme une position."""
        pos = self.get_position(pos_id)
        if pos is None:
            return False
        pos.name = new_name
        return self.save_position(pos)

    # ══════════════════════════════════════════════════════════════
    #  Suites — CRUD
    # ══════════════════════════════════════════════════════════════

    def save_suite(self, suite: SuiteModel) -> bool:
        """Sauvegarde une suite."""
        if not self._project_path:
            return False
        suite.modified_at = _now()
        with self._lock:
            path = self.project_dir / "suites" / f"{suite.id}.suite.json"
            ok = self._write_json(path, suite.to_dict())
            if ok:
                self._suites[suite.id] = suite
        return ok

    def get_suite(self, suite_id: str) -> Optional[SuiteModel]:
        """Retourne une suite par ID."""
        with self._lock:
            return self._suites.get(suite_id)

    def list_suites(self) -> List[SuiteModel]:
        """Liste toutes les suites."""
        with self._lock:
            return list(self._suites.values())

    def delete_suite(self, suite_id: str) -> bool:
        """Supprime une suite (safe unlink)."""
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "suites" / f"{suite_id}.suite.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression suite échouée : %s — %s", path, exc)
                return False
            self._suites.pop(suite_id, None)
        return True

    # ══════════════════════════════════════════════════════════════
    #  Scénarios — CRUD
    # ══════════════════════════════════════════════════════════════

    def save_scenario(self, scenario: ScenarioModel) -> bool:
        """Sauvegarde un scénario."""
        if not self._project_path:
            return False
        scenario.modified_at = _now()
        with self._lock:
            path = self.project_dir / "scenarios" / f"{scenario.id}.scenario.json"
            ok = self._write_json(path, scenario.to_dict())
            if ok:
                self._scenarios[scenario.id] = scenario
        return ok

    def get_scenario(self, scenario_id: str) -> Optional[ScenarioModel]:
        with self._lock:
            return self._scenarios.get(scenario_id)

    def list_scenarios(self) -> List[ScenarioModel]:
        with self._lock:
            return list(self._scenarios.values())

    def delete_scenario(self, scenario_id: str) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "scenarios" / f"{scenario_id}.scenario.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression scénario échouée : %s — %s", path, exc)
                return False
            self._scenarios.pop(scenario_id, None)
        return True

    # ══════════════════════════════════════════════════════════════
    #  Zones de sécurité — CRUD
    # ══════════════════════════════════════════════════════════════

    def save_zone(self, zone: ZoneModel) -> bool:
        """Sauvegarde une zone de sécurité."""
        if not self._project_path:
            return False
        zone.modified_at = _now()
        with self._lock:
            path = self.project_dir / "zones" / f"{zone.id}.zone.json"
            ok = self._write_json(path, zone.to_dict())
            if ok:
                self._zones[zone.id] = zone
        return ok

    def list_zones(self) -> List[ZoneModel]:
        """Liste toutes les zones."""
        with self._lock:
            return list(self._zones.values())

    def get_zone(self, zone_id: str) -> Optional[ZoneModel]:
        with self._lock:
            return self._zones.get(zone_id)

    def delete_zone(self, zone_id: str) -> bool:
        """Supprime une zone (safe unlink)."""
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "zones" / f"{zone_id}.zone.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression zone échouée : %s — %s", path, exc)
                return False
            self._zones.pop(zone_id, None)
        return True

    # ══════════════════════════════════════════════════════════════
    #  Assiettes — presets d'orientation outil
    # ══════════════════════════════════════════════════════════════

    def save_assiette(self, preset: AssettePreset) -> bool:
        """Sauvegarde un preset d'assiette."""
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "assiettes" / f"{preset.id}.assiette.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            ok = self._write_json(path, preset.to_dict())
            if ok:
                self._assiettes[preset.id] = preset
        return ok

    def list_assiettes(self) -> List[AssettePreset]:
        with self._lock:
            return list(self._assiettes.values())

    def delete_assiette(self, preset_id: str) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "assiettes" / f"{preset_id}.assiette.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression assiette échouée : %s — %s", path, exc)
                return False
            self._assiettes.pop(preset_id, None)
        return True

    def _load_assiettes(self, assiette_dir: Path) -> None:
        if not assiette_dir.is_dir():
            return
        for fp in assiette_dir.glob("*.assiette.json"):
            data = self._read_json(fp)
            if data:
                preset = AssettePreset.from_dict(data)
                self._assiettes[preset.id] = preset

    # ══════════════════════════════════════════════════════════════
    #  Robots — CRUD (un fichier par robot)
    # ══════════════════════════════════════════════════════════════

    def save_robot(self, robot: RobotConfigModel) -> bool:
        """Sauvegarde la config d'un robot."""
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "robots" / f"{robot.robot_id}.robot.json"
            ok = self._write_json(path, robot.to_dict())
            if ok:
                self._robots[robot.robot_id] = robot
        return ok

    def get_robot(self, robot_id: str) -> Optional[RobotConfigModel]:
        with self._lock:
            return self._robots.get(robot_id)

    def list_robots(self) -> List[RobotConfigModel]:
        with self._lock:
            return list(self._robots.values())

    def delete_robot(self, robot_id: str) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "robots" / f"{robot_id}.robot.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression robot échouée : %s — %s", path, exc)
                return False
            self._robots.pop(robot_id, None)
        return True

    # ══════════════════════════════════════════════════════════════
    #  Profils de mouvement — CRUD
    # ══════════════════════════════════════════════════════════════

    def save_motion_profile(self, profile: MotionProfileModel) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "motion_profiles" / f"{profile.id}.profile.json"
            ok = self._write_json(path, profile.to_dict())
            if ok:
                self._profiles[profile.id] = profile
        return ok

    def get_motion_profile(self, profile_id: str) -> Optional[MotionProfileModel]:
        with self._lock:
            return self._profiles.get(profile_id)

    def list_motion_profiles(self) -> List[MotionProfileModel]:
        with self._lock:
            return list(self._profiles.values())

    def delete_motion_profile(self, profile_id: str) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            path = self.project_dir / "motion_profiles" / f"{profile_id}.profile.json"
            try:
                if path.exists():
                    path.unlink()
            except OSError as exc:
                _LOG.error("Suppression profil échouée : %s — %s", path, exc)
                return False
            self._profiles.pop(profile_id, None)
        return True

    # ══════════════════════════════════════════════════════════════
    #  Timeline — fichier unique
    # ══════════════════════════════════════════════════════════════

    def save_timeline(self, data: dict) -> bool:
        if not self._project_path:
            return False
        with self._lock:
            self._timeline = data
            return self._write_json(self.project_dir / "timeline" / "timeline.json", data)

    def get_timeline(self) -> dict:
        with self._lock:
            return dict(self._timeline)

    # ══════════════════════════════════════════════════════════════
    #  Hardware — fichier unique (Arduino + capteurs + règles)
    # ══════════════════════════════════════════════════════════════

    def save_hardware(self, data: dict) -> bool:
        """Sauvegarde via dict brut (rétrocompat)."""
        if not self._project_path:
            return False
        with self._lock:
            self._hardware = HardwareConfigModel.from_dict(data)
            return self._write_json(
                self.project_dir / "hardware" / "hardware.json",
                self._hardware.to_dict())

    def save_hardware_config(self, hw: HardwareConfigModel) -> bool:
        """Sauvegarde via modèle typé."""
        if not self._project_path:
            return False
        with self._lock:
            self._hardware = hw
            return self._write_json(
                self.project_dir / "hardware" / "hardware.json",
                hw.to_dict())

    def get_hardware(self) -> dict:
        """Retourne le hardware en dict brut (rétrocompat)."""
        return self._hardware.to_dict()

    def get_hardware_config(self) -> HardwareConfigModel:
        """Retourne le modèle hardware typé."""
        return self._hardware

    # ══════════════════════════════════════════════════════════════
    #  Chargement caches
    # ══════════════════════════════════════════════════════════════

    def _clear_caches(self) -> None:
        """Vide tous les caches mémoire (sous lock pour atomicité)."""
        with self._lock:
            self._positions.clear()
            self._suites.clear()
            self._scenarios.clear()
            self._robots.clear()
            self._profiles.clear()
            self._zones.clear()
            self._assiettes.clear()
            self._timeline = {"tracks": [], "events": []}
            self._hardware = HardwareConfigModel()

    def _load_all_caches(self, proj_dir: Path) -> None:
        """Charge tous les fichiers du projet en cache mémoire (sous lock)."""
        with self._lock:
            self._load_positions(proj_dir / "positions")
            self._load_suites(proj_dir / "suites")
            self._load_scenarios(proj_dir / "scenarios")
            self._load_robots(proj_dir / "robots")
            self._load_motion_profiles(proj_dir / "motion_profiles")
            self._load_zones(proj_dir / "zones")
            self._load_assiettes(proj_dir / "assiettes")

            tl = self._read_json(proj_dir / "timeline" / "timeline.json")
            if tl:
                self._timeline = tl

            hw = self._read_json(proj_dir / "hardware" / "hardware.json")
            if hw:
                self._hardware = HardwareConfigModel.from_dict(hw)

    def _load_positions(self, pos_dir: Path) -> None:
        if not pos_dir.exists():
            return
        for f in pos_dir.glob("*.pos.json"):
            data = self._read_json(f)
            if data:
                pos = PositionModel.from_dict(data)
                self._positions[pos.id] = pos

    def _load_suites(self, suite_dir: Path) -> None:
        if not suite_dir.exists():
            return
        for f in suite_dir.glob("*.suite.json"):
            data = self._read_json(f)
            if data:
                suite = SuiteModel.from_dict(data)
                self._suites[suite.id] = suite

    def _load_scenarios(self, scen_dir: Path) -> None:
        if not scen_dir.exists():
            return
        for f in scen_dir.glob("*.scenario.json"):
            data = self._read_json(f)
            if data:
                scen = ScenarioModel.from_dict(data)
                self._scenarios[scen.id] = scen

    def _load_robots(self, robot_dir: Path) -> None:
        if not robot_dir.exists():
            return
        for f in robot_dir.glob("*.robot.json"):
            data = self._read_json(f)
            if data:
                robot = RobotConfigModel.from_dict(data)
                self._robots[robot.robot_id] = robot

    def _load_motion_profiles(self, prof_dir: Path) -> None:
        if not prof_dir.exists():
            return
        for f in prof_dir.glob("*.profile.json"):
            data = self._read_json(f)
            if data:
                prof = MotionProfileModel.from_dict(data)
                self._profiles[prof.id] = prof

    def _load_zones(self, zone_dir: Path) -> None:
        if not zone_dir.exists():
            return
        for f in zone_dir.glob("*.zone.json"):
            data = self._read_json(f)
            if data:
                zone = ZoneModel.from_dict(data)
                self._zones[zone.id] = zone

    # ══════════════════════════════════════════════════════════════
    #  I/O JSON — atomique
    # ══════════════════════════════════════════════════════════════

    def _read_json(self, path: Path) -> Optional[Any]:
        """Lecture JSON sécurisée avec log d'erreur."""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            import logging
            logging.getLogger("LibraryManager").error(
                "JSON corrompu : %s — %s", path, exc)
            return None
        except OSError as exc:
            import logging
            logging.getLogger("LibraryManager").error(
                "Lecture échouée : %s — %s", path, exc)
            return None

    def _write_json(self, path: Path, data: Any) -> bool:
        """Écriture JSON atomique (tmp → fsync → bak → rename)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(path) + ".tmp")
        bak = Path(str(path) + ".bak")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():
                shutil.copy2(path, bak)
            os.replace(tmp, path)
            return True
        except OSError:
            # Nettoyage du .tmp orphelin
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False


# ── Singleton global ──
library = LibraryManager()
