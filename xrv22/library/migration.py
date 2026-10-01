"""
xrv22/library/migration.py
────────────────────────────
Migration des données V21 (XR200) vers V22 (XRV22).

Convertit :
  - poses dict → fichiers individuels .pos.json
  - suites/pose_groups → fichiers .suite.json
  - robots list → fichiers individuels .robot.json
  - sequences → fichiers .scenario.json
  - timeline → timeline.json
  - hardware → hardware.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from xrv22.library.models import (
    PositionModel, SuiteModel, ScenarioModel, RobotConfigModel,
)
from xrv22.library.library_manager import LibraryManager


def _load_v21_sources(source_dir: Path) -> Dict[str, Any]:
    """Charge les données V21, avec repli sur un project.json plat (V20)."""
    sources: Dict[str, Any] = {
        "poses": _load_json(source_dir / "positions" / "poses.json") or {},
        "groups": _load_json(source_dir / "suites" / "suites.json") or {},
        "robots": _load_json(source_dir / "robots" / "robots.json") or [],
        "sequences": _load_json(source_dir / "scenarios" / "sequences.json") or [],
        "timeline": _load_json(source_dir / "timeline" / "timeline.json"),
        "hardware": _load_json(source_dir / "hardware" / "hardware.json"),
    }
    # Repli : fichier plat project.json (V20)
    if not sources["poses"] and not sources["robots"]:
        flat = _load_json(source_dir / "project.json")
        if flat:
            sources["poses"] = flat.get("poses", {})
            sources["groups"] = flat.get("pose_groups", {})
            sources["robots"] = flat.get("robots", [])
            sources["sequences"] = flat.get("sequences", [])
            sources["timeline"] = flat.get("timeline")
            sources["hardware"] = flat.get("hardware")
    return sources


def _migrate_positions(lib: LibraryManager, poses_data: dict,
                       report: dict) -> Dict[str, str]:
    """Migre les poses en PositionModel. Retourne le mapping ancien nom → nouvel id."""
    pose_id_map: Dict[str, str] = {}
    for pose_name, pose_values in poses_data.items():
        positions = {int(k): int(v) for k, v in pose_values.items()}
        pos = PositionModel(name=pose_name, category="sauvegardees",
                            positions=positions)
        lib.save_position(pos)
        pose_id_map[pose_name] = pos.id
        report["positions_migrated"] += 1
    return pose_id_map


def _migrate_suites(lib: LibraryManager, groups_data: dict,
                    pose_id_map: Dict[str, str], report: dict) -> None:
    """Migre les anciens pose_groups en SuiteModel."""
    for group_name, pose_names in groups_data.items():
        if group_name == "Non groupées":
            continue
        steps = []
        for pname in pose_names:
            pid = pose_id_map.get(pname)
            if pid:
                steps.append({
                    "position_id": pid,
                    "position_name": pname,
                    "duration_s": 2.0,
                    "pause_s": 0.0,
                })
            else:
                report["warnings"].append(
                    f"Suite '{group_name}' : position '{pname}' introuvable")
        lib.save_suite(SuiteModel(name=group_name, steps=steps))
        report["suites_migrated"] += 1


def _build_robot_config(rdata: dict) -> Optional[RobotConfigModel]:
    """Construit un RobotConfigModel depuis un dict robot V21 (None si sans identifiant)."""
    robot_id = rdata.get("robot_id") or rdata.get("id", "")
    if not robot_id:
        return None
    hm = rdata.get("home_machine", {})
    hw = rdata.get("home_work", {})
    sl = rdata.get("soft_limits", {})
    mp = rdata.get("motion_params", {})
    return RobotConfigModel(
        robot_id=robot_id,
        name=rdata.get("name", robot_id),
        port=rdata.get("port", ""),
        baud=rdata.get("baud", 1_000_000),
        motor_ids=rdata.get("motor_ids", [1, 2, 3, 4, 5, 6, 7]),
        home_machine={int(k): int(v) for k, v in hm.items()} if hm else {},
        home_work={int(k): int(v) for k, v in hw.items()} if hw else {},
        soft_limits={int(k): list(v) for k, v in sl.items()} if sl else {},
        motion_params=mp or {
            "smooth_hz": 60, "comfort_vel": 120,
            "comfort_acc": 40, "home_duration": 3.0,
        },
    )


def _migrate_robots(lib: LibraryManager, robots_data: list, report: dict) -> None:
    """Migre la liste de robots V21 en fichiers .robot.json."""
    for rdata in robots_data:
        robot = _build_robot_config(rdata)
        if robot is None:
            continue
        lib.save_robot(robot)
        report["robots_migrated"] += 1


def _migrate_scenarios(lib: LibraryManager, sequences_data: list,
                       report: dict) -> None:
    """Migre les séquences V21 en ScenarioModel."""
    for seq in sequences_data:
        seq_id = seq.get("id", seq.get("name", ""))
        scen = ScenarioModel(name=seq.get("name", seq_id), suite_ids=[])
        if seq.get("steps"):
            scen.triggers = [{"legacy_steps": seq["steps"]}]
        lib.save_scenario(scen)
        report["scenarios_migrated"] += 1


def migrate_v21_to_v22(lib: LibraryManager,
                       source_dir: Path,
                       project_name: str = "migrated") -> dict:
    """
    Migre un projet V21 vers V22.

    source_dir : chemin du dossier projet V21
                 (ex: ~/XR200_LIBRARY/projects/default/)

    Retourne un rapport de migration.
    """
    report = {
        "positions_migrated": 0,
        "suites_migrated": 0,
        "scenarios_migrated": 0,
        "robots_migrated": 0,
        "warnings": [],
    }

    lib.new_project(project_name)
    src = _load_v21_sources(source_dir)

    pose_id_map = _migrate_positions(lib, src["poses"], report)
    _migrate_suites(lib, src["groups"], pose_id_map, report)
    _migrate_robots(lib, src["robots"], report)
    _migrate_scenarios(lib, src["sequences"], report)

    if src["timeline"]:
        lib.save_timeline(src["timeline"])
    if src["hardware"]:
        lib.save_hardware(src["hardware"])

    lib.save_project()
    return report


def auto_migrate_if_needed(lib: LibraryManager) -> Optional[dict]:
    """
    Vérifie si une migration V21 est nécessaire et l'exécute.
    Appelé au premier lancement si aucun projet V22 n'existe.
    """
    v21_dir = Path("~/XR200_LIBRARY/projects/default").expanduser()
    if not v21_dir.exists():
        return None

    # Vérifier qu'on n'a pas déjà migré
    v22_default = lib.root / "projects" / "default"
    if v22_default.exists() and list(v22_default.glob("*.xrv22")):
        return None

    return migrate_v21_to_v22(lib, v21_dir, "default")


def _load_json(path: Path) -> Optional[Any]:
    """Lecture JSON sécurisée."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
