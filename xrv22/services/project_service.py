"""
xrv22/services/project_service.py
──────────────────────────────────
Service de projet V22 — Orchestre la sauvegarde et le chargement complet.

Responsabilites :
  - Sauvegarder l'etat complet : robots + timeline + parametres ouverture
  - Charger et restaurer : robots (homes, limites, motion), timeline
  - Gerer les projets recents via startup_params
  - Creer de nouveaux projets

Couche unique de persistance : library (LibraryManager).
Plus de ConfigManager ni de SessionStore.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

from xrv22.library.library_manager import library
from xrv22.library.models import RobotConfigModel
from xrv22.timeline.timeline_model import TimelineModel
from xrv22.core.state_store import store
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("ProjectService")

MAX_RECENT = 8


class ProjectService:
    """
    Sauvegarde / chargement projet XRV22.
    Utilise library comme unique couche de persistance.
    """

    def __init__(self) -> None:
        self._timeline_ref: Optional[TimelineModel] = None
        self._on_load_callbacks: List[Callable[[str], None]] = []
        bus.subscribe("timeline.model_replaced", self._on_model_replaced)

    def _on_model_replaced(self, payload: dict) -> None:
        """Met à jour la référence timeline après un changement de scénario."""
        model = payload.get("model")
        if isinstance(model, TimelineModel):
            self._timeline_ref = model

    # ── Configuration ────────────────────────────────────────────

    def set_timeline(self, model: TimelineModel) -> None:
        """Attache le modele timeline."""
        self._timeline_ref = model

    def on_load(self, callback: Callable[[str], None]) -> None:
        """Enregistre un callback appele apres chaque chargement."""
        self._on_load_callbacks.append(callback)

    # ── Nouveau projet ───────────────────────────────────────────

    def new_project(self, name: str) -> bool:
        """Cree un projet vide dans la librairie locale."""
        library.new_project(name)
        if self._timeline_ref:
            self._reset_timeline()
        store.set_system(project_name=name, execution_state="IDLE")
        bus.publish("project.new", {"name": name})
        _LOG.info("Nouveau projet : %s", name)
        return True

    def new_project_at(self, name: str, path: str) -> bool:
        """Cree un projet vide a un emplacement arbitraire."""
        from pathlib import Path
        library.new_project_at(name, Path(path))
        if self._timeline_ref:
            self._reset_timeline()
        store.set_system(project_name=name, execution_state="IDLE")
        bus.publish("project.new", {"name": name})
        _LOG.info("Nouveau projet externe : %s (%s)", name, path)
        return True

    def _reset_timeline(self) -> None:
        """Efface toutes les pistes et evenements du modele timeline."""
        model = self._timeline_ref
        if model is None:
            return
        for track in list(model.ordered_tracks()):
            if track.robot_id:
                model.remove_robot_track(track.robot_id)
            for evt in list(track.all_events()):
                model.remove_event(evt.event_id)

    # ── Sauvegarde ───────────────────────────────────────────────

    def save(self) -> bool:
        """Sauvegarde le projet courant via la librairie."""
        if not library.loaded:
            _LOG.warning("Aucun projet charge, impossible de sauvegarder")
            return False

        self._snapshot_robots()
        self._snapshot_timeline()
        self._snapshot_startup_params()

        ok = library.save_project()
        if ok:
            path = str(library.project_dir)
            bus.publish("project.saved", {"path": path})
            _LOG.info("Projet sauvegarde : %s", path)
        else:
            _LOG.error("Échec sauvegarde projet")
        return ok

    # ── Chargement ───────────────────────────────────────────────

    def load(self, path: str) -> bool:
        """Charge un projet depuis le disque et restaure l'etat."""
        ok = library.load_project(path)
        if not ok:
            _LOG.error("Impossible de charger : %s", path)
            return False

        self._restore_robots()
        self._restore_timeline()

        # Mettre a jour les parametres d'ouverture (projet recent)
        self._push_recent(path)

        project_name = library.project_name
        store.set_system(project_name=project_name)

        bus.publish("project.loaded", {"path": path, "name": project_name})
        _LOG.info("Projet charge : %s", project_name)

        for cb in self._on_load_callbacks:
            cb(path)
        return True

    # ── Fichiers recents ─────────────────────────────────────────

    @property
    def recent(self) -> List[str]:
        """Retourne la liste des projets recents depuis startup_params."""
        params = library.get_startup_params()
        return params.get("recent_projects", [])

    def _push_recent(self, path: str) -> None:
        """Ajoute en tete, dedoublonne, limite la liste."""
        recents = list(self.recent)
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        recents = recents[:MAX_RECENT]
        library.save_startup_params(
            recent_projects=recents,
            last_project_path=path,
        )

    # ── Snapshot (application -> librairie) ───────────────────────

    def _snapshot_robots(self) -> None:
        """Serialise l'etat des robots dans la librairie."""
        from xrv22.robots.robot_registry import registry
        for robot_id in registry.ids():
            ctrl = registry.get(robot_id)
            snap = store.get_robot(robot_id)
            if ctrl is None or snap is None:
                continue

            hm = ctrl.home_machine
            hw = ctrl.home_work
            sl = {int(mid): list(lim)
                  for mid, lim in ctrl.profile.soft_limits.items()}

            _LOG.info("[%s] Snapshot -> home_machine=%s", robot_id, hm)
            _LOG.info("[%s] Snapshot -> home_work=%s", robot_id, hw)
            _LOG.info("[%s] Snapshot -> soft_limits=%s", robot_id, sl)

            robot_model = RobotConfigModel(
                robot_id=robot_id,
                name=robot_id,
                port=snap.port or "",
                baud=ctrl.profile.baud,
                motor_ids=ctrl.profile.motor_ids,
                home_machine=hm,
                home_work=hw,
                soft_limits=sl,
                motion_params={
                    "smooth_hz": ctrl.smooth_hz,
                    "comfort_vel": ctrl.comfort_vel,
                    "comfort_acc": ctrl.comfort_acc,
                    "home_duration": ctrl.home_duration,
                },
            )
            library.save_robot(robot_model)

    def _snapshot_timeline(self) -> None:
        """Serialise la timeline dans la librairie (gère scénarios)."""
        if self._timeline_ref is None:
            return
        tl_data = self._timeline_ref.to_dict()
        name = self._timeline_ref.name
        if name and name != "default":
            # Scénario nommé → stocké dans le ScenarioModel
            for s in library.list_scenarios():
                if s.name == name:
                    s.timeline_data = tl_data
                    library.save_scenario(s)
                    return
        ok = library.save_timeline(tl_data)
        if not ok:
            _LOG.error("Échec sauvegarde timeline")

    def _snapshot_startup_params(self) -> None:
        """Sauvegarde les preferences UI dans les parametres d'ouverture."""
        sys_snap = store.get_system()
        library.save_startup_params(
            active_robot_id=sys_snap.active_robot_id,
            simulation_mode=sys_snap.simulation_mode,
        )

    # ── Restauration (librairie -> application) ──────────────────

    @staticmethod
    def _restore_one_robot(robot_data, registry, simulation: bool) -> None:
        """Restaure un robot depuis ses données library dans le registre."""
        robot_id = robot_data.robot_id
        if not robot_id:
            return
        motor_ids = robot_data.motor_ids or [1, 2, 3, 4, 5, 6, 7]
        ctrl = registry.add(robot_id, motor_ids, simulation=simulation)
        if robot_data.home_machine:
            ctrl.set_home_machine(
                {int(k): v for k, v in robot_data.home_machine.items()})
        if robot_data.home_work:
            ctrl.set_home_work(
                {int(k): v for k, v in robot_data.home_work.items()})
        # soft_limits : sinon les défauts du profil s'appliquent
        if robot_data.soft_limits:
            for mid, lim in robot_data.soft_limits.items():
                ctrl.profile.soft_limits[int(mid)] = tuple(lim)
        mp = robot_data.motion_params
        if mp:
            ctrl.set_motion_params(
                mp.get("smooth_hz", 60),
                mp.get("comfort_vel", 120),
                mp.get("comfort_acc", 40),
                home_duration=mp.get("home_duration", 3.0),
            )
        _LOG.info("Robot restaure : %s", robot_id)

    def _restore_robots(self) -> None:
        """Restaure les robots depuis la librairie dans le registre."""
        from xrv22.robots.robot_registry import registry
        simulation = store.get_system().simulation_mode
        for robot_data in library.list_robots():
            self._restore_one_robot(robot_data, registry, simulation)
        # Auto-reconnexion en arrière-plan (2s après init)
        self._auto_reconnect_robots()

    @staticmethod
    def _reconnect_blocked(registry, rid: str, port: str, ctrl) -> Optional[str]:
        """Raison de NE PAS auto-reconnecter `rid` sur `port`, ou None si OK.

        Évite les connexions fantômes : sur le Pi les ports /dev/ttyUSBn sont
        dynamiques et un port mémorisé peut être périmé (= celui d'un autre
        robot). L'autorité de connexion est le mapping U2D2 (auto_connect_all_u2d2),
        qui s'exécute avant. On bloque donc si :
        - le robot est déjà connecté (mapping l'a fait) → ne pas rouvrir ;
        - le port est déjà occupé par un autre robot connecté → port d'un autre."""
        if ctrl.is_connected:
            return "déjà connecté"
        for other_rid in registry.ids():
            if other_rid == rid:
                continue
            other = registry.get(other_rid)
            if other and other.is_connected and other.port_name == port:
                return f"port {port} déjà pris par {other_rid}"
        return None

    def _auto_reconnect_robots(self) -> None:
        """Tente de reconnecter les robots sur leurs ports memorises."""
        from xrv22.robots.robot_registry import registry

        candidates = []
        for robot_data in library.list_robots():
            rid = robot_data.robot_id
            port = robot_data.port
            baud = robot_data.baud or 1_000_000
            if rid and port:
                candidates.append((rid, port, baud))

        if not candidates:
            return

        def _task():
            time.sleep(2)  # Laisser l'UI s'initialiser + l'auto-connexion U2D2
            for rid, port, baud in candidates:
                ctrl = registry.get(rid)
                if ctrl is None:
                    continue
                blocked = self._reconnect_blocked(registry, rid, port, ctrl)
                if blocked:
                    _LOG.info("Auto-reconnexion %s ignorée : %s", rid, blocked)
                    continue
                _LOG.info("Auto-reconnexion %s sur %s...", rid, port)
                ok = ctrl.connect(port, baud)
                if ok:
                    _LOG.info("Auto-reconnexion %s : OK", rid)
                    bus.publish("robot.connected", {"robot_id": rid, "port": port})
                else:
                    _LOG.warning("Auto-reconnexion %s : echec sur %s", rid, port)

        threading.Thread(target=_task, daemon=True, name="AutoReconnect").start()

    def _restore_timeline(self) -> None:
        """Restaure la timeline depuis la librairie."""
        if self._timeline_ref is None:
            return
        tl_data = library.get_timeline()
        if not tl_data or not tl_data.get("tracks"):
            return

        restored = TimelineModel.from_dict(tl_data)
        # Copie les pistes et evenements dans le modele existant
        # (on ne remplace pas l'objet car l'UI a une reference dessus)
        self._merge_timeline(restored)
        _LOG.info("Timeline restauree : %s", restored.stats())

    def _merge_timeline(self, source: TimelineModel) -> None:
        """Fusionne les donnees source dans le modele reference (avec dedup)."""
        target = self._timeline_ref
        # Collecter les event_ids existants pour éviter les doublons
        existing_ids = set()
        for track in target.ordered_tracks():
            for evt in track.all_events():
                existing_ids.add(evt.event_id)

        for track in source.ordered_tracks():
            if track.robot_id:
                target.add_robot_track(track.robot_id, track.label, track.color)
            dest_track = target.get_track(track.track_id)
            if dest_track is None:
                continue
            for evt in track.all_events():
                if evt.event_id not in existing_ids:
                    target.add_event(evt)
                    existing_ids.add(evt.event_id)


# Singleton
project = ProjectService()
