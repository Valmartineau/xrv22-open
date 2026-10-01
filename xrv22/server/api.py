"""
xrv22/server/api.py
────────────────────
Serveur FastAPI embarque dans le process Pi (lance dans un thread Uvicorn
depuis main_pi.run). ETAPE 1 : endpoints GET en lecture seule.

Routes :
    GET /api/health            -> ping + version
    GET /api/projects          -> liste des projets
    GET /api/projects/active   -> info projet actuellement charge
    GET /api/robots            -> liste des robots avec etats live
    GET /api/robots/{rid}      -> details robot
    GET /api/positions         -> liste des positions du projet actif
    GET /api/suites            -> liste des suites
    GET /api/scenarios         -> liste des scenarios
    GET /api/hardware          -> config hardware (couplage, etc.)

Note : les ecritures (POST/PUT/DELETE) seront ajoutees en Etape 4.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List

from xrv22.services.logger import get_logger

_LOG = get_logger("API")

try:
    import asyncio
    import tempfile
    from pathlib import Path as _Path
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from pydantic import BaseModel, Field
    import uvicorn
    FASTAPI_OK = True
except ImportError:
    FASTAPI_OK = False
    _LOG.warning("fastapi/uvicorn absents -> API web desactivee. "
                 "Installer : pip install fastapi 'uvicorn[standard]'")


# ── Bodies Pydantic (Etape 4) ─────────────────────────────────────
# IMPORTANT : ces classes DOIVENT etre au top-level du module et pas
# dans create_app(). Sinon FastAPI les voit comme query params (issue
# d'introspection sur les classes locales), et toutes les routes POST
# avec body retournent HTTP 422 "Field required" sur loc=["query","body"].

if FASTAPI_OK:

    class ConnectBody(BaseModel):
        port: str | None = None  # si absent : auto_connect_all_u2d2

    class TorqueBody(BaseModel):
        enable: bool

    class HomeBody(BaseModel):
        kind: str = Field(default="machine", pattern="^(machine|work)$")

    class CaptureBody(BaseModel):
        robot_id: str
        name: str
        category: str = "sauvegardees"
        # Snapshot explicite pris cote UI (ex. wizard de suite : chaque pose
        # figee au 📸). Si vide, on lit la position COURANTE du robot (capture
        # "live", ex. bouton Enregistrer de la page Positions).
        positions: dict[str, int] = {}

    class PlayBody(BaseModel):
        from_ms: int = 0

    class DirectPositionsBody(BaseModel):
        # {axis_str: ticks 0-4095}, ex. {"1": 2048, "2": 1500}
        positions: dict[str, int]

    class DirectModeBody(BaseModel):
        enable: bool

    class AnticollisionBody(BaseModel):
        enable: bool

    class SuiteBody(BaseModel):
        name: str
        steps: list[dict] = []
        meta: dict = {}

    class SuiteUpdateBody(BaseModel):
        name: str | None = None
        steps: list[dict] | None = None
        meta: dict | None = None

    class GotoBody(BaseModel):
        robot_id: str
        duration_s: float = 3.0

    class MotorLimitBody(BaseModel):
        motor_id: int
        lo: int
        hi: int

    class CouplingBody(BaseModel):
        enabled: bool = True
        invert: bool = False
        ratio: float = 1.0
        offset: int = 0
        center: int = 2048

    class TimelineDataBody(BaseModel):
        timeline_data: dict

    class NewProjectBody(BaseModel):
        name: str

    class LoadProjectBody(BaseModel):
        path: str

    class AddRobotBody(BaseModel):
        robot_id: str
        motor_ids: list[int] = [1, 2, 3, 4, 5, 6, 7]

    class CapturePointBody(BaseModel):
        robot_id: str

    class ZoneBody(BaseModel):
        name: str
        zone_type: str = "warning"   # warning | exclusion | plane
        points: list[list[float]] = []
        color: str = "#f6a117"
        visible: bool = True
        source_robot_id: str = ""

    class ZoneUpdateBody(BaseModel):
        name: str | None = None
        zone_type: str | None = None
        visible: bool | None = None
        color: str | None = None

    class DxfImportParams(BaseModel):
        scenario_id: str
        robot_id: str
        duration_s: float = 2.0
        z_surface: float = 100.0   # mm depuis sol
        tool_angle: float = 3.14159  # pi = tool-down

    class DeviceBody(BaseModel):
        name: str
        port: str
        baud: int = 115200
        device_type: str = "arduino"

    class SafetySettingsBody(BaseModel):
        collision_check_enabled: bool | None = None

    class ActiveRobotBody(BaseModel):
        robot_id: str

    class PositionUpdateBody(BaseModel):
        positions: dict[str, int]

    class ActuatorBody(BaseModel):
        value: float

    class ActionBody(BaseModel):
        params: dict[str, Any] = {}

    class RawBody(BaseModel):
        raw: str

    class RuleBody(BaseModel):
        min_val: float | None = None
        max_val: float | None = None

    class EddyStepBody(BaseModel):
        pas: int
        positions: dict[str, int]
        manettes: list[int]
        signaux: list[int]
        pression: int
        plafond: int
        manette_active: int
        delta: int
        pensee: str = ""
        note: str = ""
        bloque: bool = False
        ts: float | None = None
        # Dialogue-en-mouvement (mode compagnon) : ce que la personne a dit à ce
        # pas, et la réponse d'Eddy. Vides en run isolé.
        message_humain: str = ""
        reponse: str = ""

    class StyletTickBody(BaseModel):
        x: int | None = None
        y: int | None = None
        p: int = 0
        etat: str = "HORS-PORTEE"

    class EddySayBody(BaseModel):
        message: str


# ── Helpers de serialisation ─────────────────────────────────────

def _to_jsonable_via_method(obj: Any):
    """Tente la sérialisation par méthode (model_dump Pydantic, .dict()).
    Retourne (résultat, True) si une méthode a fonctionné, sinon (None, False)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(), True
    dict_method = getattr(obj, "dict", None)
    if callable(dict_method):
        try:
            return dict_method(), True
        except Exception:
            pass
    return None, False


def _to_jsonable(obj: Any) -> Any:
    """Convertit un objet (dataclass, dict, list, primitives) en JSON-safe."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if is_dataclass(obj):
        return _to_jsonable(asdict(obj))
    result, ok = _to_jsonable_via_method(obj)
    if ok:
        return result
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_jsonable(v) for v in obj]
    return str(obj)


# ── App factory ──────────────────────────────────────────────────

def create_app() -> "FastAPI":
    """Construit l'instance FastAPI avec toutes les routes GET."""
    app = FastAPI(title="XRV22 API", version="0.1.0")

    # ── Etape 5 : CORS restreint au LAN (avec mode dev permissif) ────
    # Origins acceptees : Pi en LAN (mDNS + IP), serveur Vite dev local.
    # Override possible via env XRV22_ALLOWED_ORIGINS=url1,url2 si besoin.
    import os as _os
    _env_origins = _os.environ.get("XRV22_ALLOWED_ORIGINS", "").strip()
    if _env_origins:
        cors_origins = [o.strip() for o in _env_origins.split(",") if o.strip()]
    else:
        cors_origins = [
            "http://localhost:5173", "http://127.0.0.1:5173",  # Vite dev
            "http://raspberrypi.local:8080", "http://xrv22.local:8080",
            "http://192.168.1.95:8080", "http://192.168.2.12:8080",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── Etape 5 : middleware d'authentification ─────────────────────
    from xrv22.server.auth import (check_token, extract_token,
                                   is_public_path, get_token, make_qr_ascii)

    @app.middleware("http")
    async def _auth_middleware(request, call_next):
        """Valide le token sur toutes les routes /api/* sauf
        celles listees comme publiques. Le static (HTML/JS/CSS) reste
        accessible sans token : sinon le navigateur ne peut pas charger
        l'app pour soumettre le token."""
        path = request.url.path
        if request.method == "OPTIONS" or is_public_path(path):
            return await call_next(request)
        # On protege /api/* (sauf /api/health) et c'est tout
        if not path.startswith("/api/"):
            return await call_next(request)
        presented = extract_token(request.headers.get("authorization"),
                                  request.query_params.get("token"))
        if not check_token(presented):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "token invalide ou manquant"},
                                status_code=401)
        return await call_next(request)

    # ── Etape 2 : broadcaster WebSocket — attache l'event loop au boot ───
    @app.on_event("startup")
    async def _ws_startup() -> None:
        from xrv22.server.ws_broadcaster import broadcaster
        broadcaster.attach_loop(asyncio.get_running_loop())

        from xrv22.core.jog_engine import jog_engine
        jog_engine.start()

        # Préchauffe le moteur anticollision boîtes (~1 s) en tâche de fond dès
        # le boot → prêt avant tout pilotage, ferme la fenêtre fail-open à froid.
        from xrv22.core.box_collision import engine as box_engine
        box_engine._kick_init()

        # Persistance auto des canaux découverts après IDENTIFY
        from xrv22.services.event_bus import bus

        def _persist_arduino(_payload: dict) -> None:
            try:
                lib = _library()
                hw = lib.get_hardware() or {}
                snap = {d["name"]: d for d in _arduino().snapshot_devices()}
                merged = []
                for rec in hw.get("devices", []) or []:
                    s = snap.get(rec.get("name"))
                    if s:
                        rec = {**rec, "firmware": s.get("firmware", ""),
                               "channels": s.get("channels", []),
                               "actuators": s.get("actuators", []),
                               "actions": s.get("actions", [])}
                    merged.append(rec)
                hw["devices"] = merged
                lib.save_hardware(hw)
            except Exception as exc:
                _LOG.warning("persist arduino échec : %s", exc)

        bus.subscribe("arduino.identified", _persist_arduino)

    @app.on_event("shutdown")
    async def _jog_shutdown() -> None:
        from xrv22.core.jog_engine import jog_engine
        jog_engine.stop()

    # ── Lazy imports : eviter l'import circulaire au boot ────────
    def _library():
        from xrv22.library.library_manager import library
        return library

    def _registry():
        from xrv22.robots.robot_registry import registry
        return registry

    def _store():
        from xrv22.core.state_store import store
        return store

    # ── Routes ───────────────────────────────────────────────────

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": app.version,
            "robots": list(_registry().ids()),
            "master": _registry().master_id,
        }

    @app.get("/api/projects")
    def list_projects() -> List[Dict[str, Any]]:
        return [_to_jsonable(p) for p in _library().list_projects()]

    @app.get("/api/projects/active")
    def active_project() -> Dict[str, Any]:
        lib = _library()
        if not lib.loaded:
            raise HTTPException(404, "Aucun projet charge")
        return {
            "name": lib.project_name,
            "path": str(lib.project_path) if lib.project_path else None,
            "loaded": True,
        }

    @app.get("/api/robots")
    def list_robots() -> List[Dict[str, Any]]:
        reg = _registry()
        out = []
        for rid in reg.ids():
            ctrl = reg.get(rid)
            if ctrl is None:
                continue
            soft_limits = (_to_jsonable(ctrl.profile.soft_limits)
                           if ctrl.profile else {})
            out.append({
                "id": rid,
                "is_master": rid == reg.master_id,
                "connected": bool(ctrl.is_connected),
                "port": ctrl.port_name or "",
                "torque_enabled": bool(getattr(ctrl, "torque_enabled", False)),
                "state": str(ctrl.state),
                "smooth_hz": ctrl.smooth_hz,
                "comfort_vel": ctrl.comfort_vel,
                "comfort_acc": ctrl.comfort_acc,
                "soft_limits": soft_limits,
                "home_machine": dict(ctrl.home_machine) if ctrl.home_machine else {},
                "home_work": dict(ctrl.home_work) if ctrl.home_work else {},
            })
        return out

    @app.get("/api/robots/{rid}")
    def robot_detail(rid: str) -> Dict[str, Any]:
        ctrl = _registry().get(rid)
        if ctrl is None:
            raise HTTPException(404, f"Robot inconnu : {rid}")
        snap = _store().get_robot(rid)
        return {
            "id": rid,
            "is_master": rid == _registry().master_id,
            "connected": bool(ctrl.is_connected),
            "port": ctrl.port_name or "",
            "torque_enabled": bool(getattr(ctrl, "torque_enabled", False)),
            "state": str(ctrl.state),
            "smooth_hz": ctrl.smooth_hz,
            "comfort_vel": ctrl.comfort_vel,
            "comfort_acc": ctrl.comfort_acc,
            "home_machine": dict(ctrl.home_machine) if ctrl.home_machine else {},
            "home_work": dict(ctrl.home_work) if ctrl.home_work else {},
            "soft_limits": _to_jsonable(ctrl.profile.soft_limits)
                           if ctrl.profile else {},
            "positions": dict(snap.positions) if snap and snap.positions else {},
        }

    @app.get("/api/positions")
    def list_positions(category: str | None = None) -> List[Dict[str, Any]]:
        return [_to_jsonable(p) for p in _library().list_positions(category)]

    @app.get("/api/suites")
    def list_suites() -> List[Dict[str, Any]]:
        return [_to_jsonable(s) for s in _library().list_suites()]

    @app.get("/api/scenarios")
    def list_scenarios() -> List[Dict[str, Any]]:
        lib = _library()
        if hasattr(lib, "list_scenarios"):
            return [_to_jsonable(s) for s in lib.list_scenarios()]
        return []

    @app.get("/api/hardware")
    def hardware() -> Dict[str, Any]:
        return _to_jsonable(_library().get_hardware())

    @app.get("/api/hardware/ports")
    def hardware_ports() -> Dict[str, Any]:
        """Ports série proposables pour un Arduino (robots exclus)."""
        from xrv22.server.port_discovery import list_available_ports
        robot_ports = set()
        for rid in _registry().ids():
            ctrl = _registry().get(rid)
            if ctrl is not None and getattr(ctrl, "port_name", None):
                robot_ports.add(ctrl.port_name)
        return {"ports": list_available_ports(robot_ports)}

    def _arduino():
        from xrv22.hardware.arduino_bridge import arduino
        return arduino

    def _dev_name(did: str) -> str:
        """Résout l'id hardware.json -> name du device. 404 si inconnu."""
        hw = _library().get_hardware() or {}
        for d in hw.get("devices", []) or []:
            if d.get("id") == did:
                name = d.get("name", "")
                if not name:
                    raise HTTPException(500, f"Device {did} sans nom dans hardware.json")
                return name
        raise HTTPException(404, f"Device inconnu : {did}")

    @app.get("/api/hardware/devices/{did}")
    def get_device(did: str) -> Dict[str, Any]:
        from xrv22.server.arduino_serializer import device_to_dict
        name = _dev_name(did)
        dev = _arduino().get_device(name)
        if dev is None:
            hw = _library().get_hardware() or {}
            rec = next((d for d in hw.get("devices", []) or [] if d.get("id") == did), {})
            return device_to_dict(None, name=name,
                                  port=rec.get("port", ""), baud=rec.get("baud", 0))
        return device_to_dict(dev)

    @app.post("/api/hardware/devices/{did}/connect")
    async def connect_device(did: str) -> Dict[str, Any]:
        """Enregistre le device dans le bridge si besoin, ouvre le port + IDENTIFY."""
        name = _dev_name(did)
        hw = _library().get_hardware() or {}
        rec = next((d for d in hw.get("devices", []) or [] if d.get("id") == did), {})
        arduino = _arduino()
        if arduino.get_device(name) is None:
            arduino.add_device(name, rec.get("port", ""), rec.get("baud", 115200))
        ok = await asyncio.to_thread(arduino.connect, name)
        if not ok:
            dev = arduino.get_device(name)
            raise HTTPException(502, f"Connexion échouée : {dev.error if dev else 'inconnu'}")
        return {"ok": True, "id": did, "connected": True}

    @app.post("/api/hardware/devices/{did}/disconnect")
    async def disconnect_device(did: str) -> Dict[str, Any]:
        name = _dev_name(did)
        await asyncio.to_thread(_arduino().disconnect, name)
        return {"ok": True, "id": did, "connected": False}

    @app.post("/api/hardware/devices/{did}/actuators/{act}")
    async def set_actuator(did: str, act: str, body: ActuatorBody) -> Dict[str, Any]:
        name = _dev_name(did)
        ok = await asyncio.to_thread(_arduino().send_command, name, act, body.value)
        if not ok:
            raise HTTPException(502, f"Échec commande actionneur '{act}'")
        return {"ok": True, "actuator": act, "value": body.value}

    @app.post("/api/hardware/devices/{did}/actions/{action}")
    async def run_action(did: str, action: str, body: ActionBody) -> Dict[str, Any]:
        name = _dev_name(did)
        ok, msg = await asyncio.to_thread(
            _arduino().run_action, name, action, body.params, 10.0)
        if not ok:
            raise HTTPException(502, msg)
        return {"ok": True, "action": action, "message": msg}

    @app.post("/api/hardware/devices/{did}/raw")
    async def send_raw(did: str, body: RawBody) -> Dict[str, Any]:
        name = _dev_name(did)
        ok = await asyncio.to_thread(_arduino().send_raw, name, body.raw)
        if not ok:
            raise HTTPException(502, "Échec envoi commande brute")
        return {"ok": True, "raw": body.raw}

    @app.post("/api/hardware/devices/{did}/sensors/{sensor}/rule")
    def set_sensor_rule(did: str, sensor: str, body: RuleBody) -> Dict[str, Any]:
        from xrv22.hardware.sensor_manager import sensor_manager
        name = _dev_name(did)
        sensor_id = f"{name}.{sensor}"
        if body.min_val is None and body.max_val is None:
            sensor_manager.remove_rule(sensor_id)
            return {"ok": True, "sensor_id": sensor_id, "rule": None}
        sensor_manager.add_rule(sensor_id, min_val=body.min_val, max_val=body.max_val)
        return {"ok": True, "sensor_id": sensor_id,
                "rule": {"min_val": body.min_val, "max_val": body.max_val}}

    # ── ETAPE 4 : commandes (POST) ───────────────────────────────────
    # Toutes les actions potentiellement bloquantes passent par
    # asyncio.to_thread pour ne pas geler l'event loop FastAPI.

    def _bus():
        from xrv22.services.event_bus import bus
        return bus

    def _get_ctrl(rid: str):
        """Recupere le RobotController ou leve 404."""
        ctrl = _registry().get(rid)
        if ctrl is None:
            raise HTTPException(404, f"Robot inconnu : {rid}")
        return ctrl

    def _refresh_now() -> None:
        """Publie ui.refresh -> push aux WS clients pour refetch."""
        _bus().publish("ui.refresh", {})

    @app.post("/api/robots/{rid}/connect")
    async def cmd_connect(rid: str, body: ConnectBody | None = None):
        """Connecte un robot. Si body.port absent : auto_connect_all_u2d2."""
        ctrl = _get_ctrl(rid)
        if body and body.port:
            from xrv22.main_pi import _safe_torque_with_reboot
            ok = await asyncio.to_thread(ctrl.connect, body.port)
            if ok:
                await asyncio.to_thread(_safe_torque_with_reboot, ctrl, rid)
        else:
            # Sans port explicite : connecte UNIQUEMENT ce robot (via son U2D2
            # mappe). auto_connect_all_u2d2 connecterait les 3 robots d'un coup.
            from xrv22.main_pi import auto_connect_one
            ok = await asyncio.to_thread(auto_connect_one, rid)
        _refresh_now()
        return {"ok": bool(ok), "connected": ctrl.is_connected,
                "port": ctrl.port_name or ""}

    @app.post("/api/robots/{rid}/disconnect")
    async def cmd_disconnect(rid: str):
        """Deconnecte un robot."""
        ctrl = _get_ctrl(rid)
        await asyncio.to_thread(ctrl.disconnect)
        _refresh_now()
        return {"ok": True, "connected": ctrl.is_connected}

    @app.post("/api/robots/{rid}/torque")
    async def cmd_torque(rid: str, body: TorqueBody):
        """Active ou coupe le torque."""
        ctrl = _get_ctrl(rid)
        ok = await asyncio.to_thread(ctrl.set_torque, body.enable)
        _bus().publish("robot.torque_changed",
                       {"robot_id": rid, "enabled": ctrl.torque_enabled})
        _refresh_now()
        return {"ok": bool(ok), "torque_enabled": ctrl.torque_enabled}

    @app.post("/api/robots/{rid}/master")
    async def cmd_master(rid: str):
        """Definit le robot master + propage la config aux esclaves."""
        reg = _registry()
        if rid not in reg.ids():
            raise HTTPException(404, f"Robot inconnu : {rid}")
        ok = reg.set_master(rid)
        if ok:
            await asyncio.to_thread(reg.propagate_from_master, kind="all")
            _bus().publish("robot.master_changed", {"robot_id": rid})
        _refresh_now()
        return {"ok": bool(ok), "master": reg.master_id}

    @app.post("/api/robots/{rid}/reboot")
    async def cmd_reboot(rid: str):
        """Reboot tous les moteurs du robot + retry torque + reapplique
        profile + reset des etats safety bloquants (ERROR / EMERGENCY_STOP /
        LOCKED / COMM_LOST) pour ne pas avoir besoin de disconnect/reconnect."""
        ctrl = _get_ctrl(rid)
        from xrv22.main_pi import _safe_torque_with_reboot
        from xrv22.robots.robot_profiles import profiles
        profile = profiles.get(rid)
        motor_ids = list(profile.motor_ids) if profile else []

        def _do():
            for mid in motor_ids:
                try:
                    ctrl.reboot_motor(mid)
                except Exception:
                    pass
            _safe_torque_with_reboot(ctrl, rid)
            # Reset des states bloquants (sinon, apres reboot, le state reste
            # ERROR/EMERGENCY_STOP/LOCKED et le robot refuse les move).
            for resetter in ("reset_error", "reset_emergency", "unlock"):
                fn = getattr(ctrl, resetter, None)
                if fn:
                    try: fn()
                    except Exception: pass

        await asyncio.to_thread(_do)
        _refresh_now()
        return {"ok": True, "torque_enabled": ctrl.torque_enabled,
                "state": str(ctrl.state)}

    @app.post("/api/robots/{rid}/home")
    async def cmd_home(rid: str, body: HomeBody):
        """Retour position machine (safe_home) ou travail."""
        ctrl = _get_ctrl(rid)
        if body.kind == "machine":
            ok, msg = await asyncio.to_thread(ctrl.safe_home)
        else:
            ok, msg = await asyncio.to_thread(ctrl.go_home_work)
        _refresh_now()
        return {"ok": bool(ok), "message": msg, "kind": body.kind}

    @app.post("/api/robots/{rid}/calib")
    async def cmd_calib(rid: str, body: HomeBody):
        """Definit la position courante du robot comme home_machine
        ou home_work (selon body.kind). Lecture HW + set_home_* + persist
        dans la library.robots.json."""
        ctrl = _get_ctrl(rid)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {rid} non connecte")
        positions = await asyncio.to_thread(ctrl.read_positions)
        pos_dict = dict(positions)
        if body.kind == "machine":
            await asyncio.to_thread(ctrl.set_home_machine, pos_dict)
        else:
            await asyncio.to_thread(ctrl.set_home_work, pos_dict)
        # Persist dans la library (chaque robot a un .robot.json)
        try:
            from xrv22.services.project_service import project as _proj
            await asyncio.to_thread(_proj.save)
        except Exception as exc:
            _LOG.warning("calib %s/%s : sauvegarde projet echec : %s",
                         rid, body.kind, exc)
        _refresh_now()
        return {"ok": True, "kind": body.kind, "robot_id": rid,
                "positions": {str(k): int(v) for k, v in pos_dict.items()}}

    @app.post("/api/robots/{rid}/stop")
    async def cmd_stop(rid: str):
        """Arret d'urgence (torque off + estop hardware)."""
        ctrl = _get_ctrl(rid)
        await asyncio.to_thread(ctrl.emergency_stop)
        _refresh_now()
        return {"ok": True, "state": str(ctrl.state)}

    @app.post("/api/robots/{rid}/positions")
    async def cmd_write_positions_direct(rid: str, body: DirectPositionsBody):
        """Ecriture directe des positions (mode pilotage manuel /
        sliders web). Le couplage configure dans la library est applique
        automatiquement par RobotController._apply_coupling."""
        ctrl = _get_ctrl(rid)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {rid} non connecte")
        if not ctrl.torque_enabled:
            raise HTTPException(409, f"Robot {rid} : torque OFF (active-le d'abord)")
        try:
            targets = {int(k): int(v) for k, v in body.positions.items()}
        except (TypeError, ValueError):
            raise HTTPException(422, "positions doit etre {axis_int: ticks_int}")
        ok = await asyncio.to_thread(ctrl.write_positions_direct, targets)
        return {"ok": bool(ok),
                "positions": {str(k): v for k, v in targets.items()}}

    @app.post("/api/eddy/step")
    def cmd_eddy_step(body: EddyStepBody) -> Dict[str, Any]:
        """Moniteur incarné : republie un pas d'Eddy sur le bus (relayé en WS).
        Notre échafaudage — ce payload n'est jamais renvoyé dans la boucle."""
        _bus().publish("eddy.step", body.model_dump())
        return {"ok": True}

    @app.post("/api/stylet/tick")
    def cmd_stylet_tick(body: StyletTickBody) -> Dict[str, Any]:
        """Flux dessin : republie un tick stylet sur le bus (relayé WS)."""
        _bus().publish("stylet.tick", body.model_dump())
        return {"ok": True}

    @app.post("/api/eddy/say")
    def cmd_eddy_say(body: EddySayBody) -> Dict[str, Any]:
        """Dialogue-en-mouvement : dépose un message de la personne dans la boîte
        aux lettres ; le run en cours la vide au pas suivant et l'injecte dans le
        prompt d'Eddy. Republie aussi le message sur le bus (echo immédiat /eddy)."""
        from incarne.messagerie import deposer
        from pathlib import Path
        inbox = Path.home() / "xrv22" / "XRV22_LIBRARY" / "eddy_inbox.txt"
        deposer(body.message, inbox)
        _bus().publish("eddy.say", {"message": body.message})
        return {"ok": True}

    @app.post("/api/eddy/position_depart")
    async def cmd_eddy_position_depart() -> Dict[str, Any]:
        """Envoie le robot à la position initiale de dessin (position_protocole.json)."""
        from incarne.run_incarne import charger_position_protocole
        from pathlib import Path
        fichier = Path.home() / "xrv22" / "incarne" / "position_protocole.json"
        rid, targets = charger_position_protocole(fichier)
        ctrl = _get_ctrl(rid)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {rid} non connecté")
        if not ctrl.torque_enabled:
            raise HTTPException(409, f"Robot {rid} : torque OFF (active-le d'abord)")
        ok = await asyncio.to_thread(ctrl.write_positions_direct, targets)
        return {"ok": bool(ok), "positions": {str(k): v for k, v in targets.items()}}

    @app.post("/api/robots/{rid}/direct_mode")
    async def cmd_direct_mode(rid: str, body: DirectModeBody):
        """Mode pilotage direct web : prise de main explicite via le JogEngine
        (acquire a l'activation, release a la desactivation si le web possede
        encore la main). Le profil court est pose au 1er mouvement (front)."""
        ctrl = _get_ctrl(rid)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {rid} non connecte")
        from xrv22.core.jog_engine import jog_engine
        if body.enable:
            # Prise de main web : acquire pose owner=web + integrateur (seed
            # lazy) + publie control_changed. Le profil court est pose au 1er
            # target par le front (cf has_intent), pas ici (lecon J2 : ne pas
            # ramollir le maintien tant qu'on tient juste la position).
            await asyncio.to_thread(jog_engine.acquire, rid, "web")
        elif ctrl.control_owner == "web":
            # GARDE arbitrage : on ne release QUE si le web possede encore la
            # main. Sinon (le Pi a repris -> store.tsx repasse le web en
            # non-Direct -> cmdDirectMode(false)), un release ecraserait le
            # controle que le Pi vient de prendre.
            await asyncio.to_thread(jog_engine.release, rid)
        return {"ok": True, "direct": body.enable}

    @app.get("/api/robots/{rid}/anticollision")
    async def get_anticollision(rid: str):
        """État de la couche anticollision boîtes STL pour ce robot.
        `available` = moteur prêt (calibration.json avec boxes chargée)."""
        from xrv22.core.safety_manager import safety
        from xrv22.core.box_collision import engine as box_engine
        mgr = safety.get(rid)
        if mgr is None:
            raise HTTPException(404, f"Robot inconnu : {rid}")
        # Init SYNCHRONE (idempotente) : `available` reflète la réalité dès le
        # 1er appel, sans course avec le thread d'init paresseux (sinon `false`
        # transitoire au démarrage à froid, cf. faux diagnostic 2026-06-15).
        box_engine.init()
        return {"enabled": mgr.anticollision_enabled,
                "available": box_engine.available}

    @app.post("/api/robots/{rid}/anticollision")
    async def set_anticollision(rid: str, body: AnticollisionBody):
        """Active/désactive la couche anticollision pour ce robot (tous les
        chemins de pilotage : Direct web/Pi, jog, suites). ON par défaut à
        chaque démarrage — le réglage n'est volontairement pas persisté."""
        from xrv22.core.safety_manager import safety
        mgr = safety.get(rid)
        if mgr is None:
            raise HTTPException(404, f"Robot inconnu : {rid}")
        mgr.anticollision_enabled = bool(body.enable)
        try:
            from xrv22.services.event_bus import bus
            bus.publish("safety.anticollision_changed", {
                "robot_id": rid, "enabled": mgr.anticollision_enabled,
            })
        except Exception:
            pass
        return {"ok": True, "enabled": mgr.anticollision_enabled}

    @app.post("/api/positions")
    async def cmd_capture_position(body: CaptureBody):
        """Enregistre une position. Utilise body.positions si fourni (snapshot
        UI, ex. wizard de suite) ; sinon lit la position courante du robot."""
        ctrl = _get_ctrl(body.robot_id)
        if body.positions:
            positions = {int(k): int(v) for k, v in body.positions.items()}
        else:
            if not ctrl.is_connected:
                raise HTTPException(409, f"Robot {body.robot_id} non connecte")
            positions = await asyncio.to_thread(ctrl.read_positions)
        from xrv22.library.models import PositionModel
        pos = PositionModel(name=body.name, category=body.category,
                            positions=dict(positions),
                            meta={"robot_id": body.robot_id})
        ok = await asyncio.to_thread(_library().save_position, pos)
        _refresh_now()
        return {"ok": bool(ok), "id": pos.id, "name": pos.name,
                "positions": {str(k): v for k, v in pos.positions.items()}}

    @app.put("/api/positions/{pid}")
    async def cmd_update_position(pid: str, body: PositionUpdateBody):
        """Met à jour les ticks d'une position librairie existante."""
        lib = _library()
        pos = lib.get_position(pid)
        if pos is None:
            raise HTTPException(404, f"Position inconnue : {pid}")
        try:
            pos.positions = {int(k): int(v) for k, v in body.positions.items()}
        except (ValueError, TypeError):
            raise HTTPException(422, "positions doit etre {axis_int: ticks_int}")
        ok = await asyncio.to_thread(lib.save_position, pos)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde position")
        _refresh_now()
        return {"ok": True, "id": pid}

    # ── Soft limits + couplage ───────────────────────────────────────

    @app.post("/api/robots/{rid}/motor_limit")
    async def cmd_motor_limit(rid: str, body: MotorLimitBody):
        """Modifie les soft_limits [lo, hi] d'un axe.
        Si robot master + couplage ON pour axe 2 : propage aussi a l'axe 3."""
        ctrl = _get_ctrl(rid)
        if body.lo < 0 or body.hi > 4095 or body.lo >= body.hi:
            raise HTTPException(422, "lo/hi invalides (0 <= lo < hi <= 4095)")
        await asyncio.to_thread(ctrl.set_motor_limit, body.motor_id, body.lo, body.hi)
        _refresh_now()
        return {"ok": True, "robot_id": rid, "motor_id": body.motor_id,
                "lo": body.lo, "hi": body.hi}

    @app.post("/api/hardware/coupling")
    async def cmd_set_coupling(body: CouplingBody):
        """Active/configure le couplage 2-3 dans library.hardware.
        Persiste dans XRV22_LIBRARY/projects/<active>/hardware/hardware.json."""
        lib = _library()
        hw = lib.get_hardware() or {}
        hw["coupling"] = {
            "enabled": body.enabled,
            "invert": body.invert,
            "ratio": body.ratio,
            "offset": body.offset,
            "center": body.center,
        }
        ok = await asyncio.to_thread(lib.save_hardware, hw)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde hardware.json")
        _refresh_now()
        return {"ok": True, "coupling": hw["coupling"]}

    @app.get("/api/hardware/coupling")
    def get_coupling() -> Dict[str, Any]:
        """Retourne la config couplage courante (defauts si absente)."""
        cfg = _library().get_hardware().get("coupling", {}) or {}
        return {
            "enabled": cfg.get("enabled", False),
            "invert":  cfg.get("invert", False),
            "ratio":   cfg.get("ratio", 1.0),
            "offset":  cfg.get("offset", 0),
            "center":  cfg.get("center", 2048),
        }

    # ── Library : delete + create suite + goto position ──────────────

    @app.delete("/api/positions/{pid}")
    async def cmd_delete_position(pid: str):
        """Supprime une position. 409 si referencee dans une suite."""
        ok, msg = await asyncio.to_thread(_library().delete_position, pid)
        if not ok:
            raise HTTPException(409, msg)
        _refresh_now()
        return {"ok": True, "id": pid}

    @app.put("/api/suites/{sid}")
    async def cmd_update_suite(sid: str, body: SuiteUpdateBody):
        """Met a jour name/steps/meta d'une suite (utilise par drag-drop dossier)."""
        lib = _library()
        suite = lib.get_suite(sid)
        if suite is None:
            raise HTTPException(404, f"Suite inconnue : {sid}")
        if body.name is not None: suite.name = body.name
        if body.steps is not None: suite.steps = body.steps
        if body.meta is not None: suite.meta = body.meta
        ok = await asyncio.to_thread(lib.save_suite, suite)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde suite")
        _refresh_now()
        return {"ok": True, "id": sid}

    @app.delete("/api/suites/{sid}")
    async def cmd_delete_suite(sid: str):
        """Supprime une suite (sans toucher aux positions referencees)."""
        ok = await asyncio.to_thread(_library().delete_suite, sid)
        if not ok:
            raise HTTPException(404, f"Suite inconnue ou suppression refusee : {sid}")
        _refresh_now()
        return {"ok": True, "id": sid}

    @app.post("/api/suites")
    async def cmd_create_suite(body: SuiteBody):
        """Cree une nouvelle suite avec name + steps optionnels."""
        from xrv22.library.models import SuiteModel
        suite = SuiteModel(name=body.name, steps=body.steps, meta=body.meta)
        ok = await asyncio.to_thread(_library().save_suite, suite)
        if not ok:
            raise HTTPException(500, "Echec de la sauvegarde (projet charge ?)")
        _refresh_now()
        return {"ok": True, "id": suite.id, "name": suite.name}

    @app.post("/api/positions/{pid}/goto")
    async def cmd_goto_position(pid: str, body: GotoBody):
        """Envoie le robot a la position sauvegardee. Bloquant."""
        pos = _library().get_position(pid)
        if pos is None:
            raise HTTPException(404, f"Position inconnue : {pid}")
        ctrl = _get_ctrl(body.robot_id)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {body.robot_id} non connecte")
        if not ctrl.torque_enabled:
            raise HTTPException(409, f"Robot {body.robot_id} : torque OFF")
        ok = await asyncio.to_thread(ctrl.move, dict(pos.positions), body.duration_s)
        return {"ok": bool(ok), "position_id": pid, "name": pos.name}

    # ── Zones (Chantier 1) ───────────────────────────────────────────

    @app.get("/api/zones")
    def list_zones() -> List[Dict[str, Any]]:
        lib = _library()
        if not hasattr(lib, "list_zones"): return []
        return [_to_jsonable(z) for z in lib.list_zones()]

    @app.post("/api/zones")
    async def cmd_create_zone(body: ZoneBody):
        from xrv22.library.models import ZoneModel
        from xrv22.library.zone_geometry import compute_plane_axis, ColinearPointsError

        if len(body.points) < 3:
            raise HTTPException(422, "Au moins 3 points requis")
        try:
            axis = compute_plane_axis(body.points)
        except ColinearPointsError as e:
            raise HTTPException(422, f"Points colineaires : {e}")

        z = ZoneModel(
            name=body.name, zone_type=body.zone_type,
            points=body.points, color=body.color, visible=body.visible,
            plane_axis=axis, source_robot_id=body.source_robot_id,
        )
        ok = await asyncio.to_thread(_library().save_zone, z)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde zone (projet charge ?)")
        _refresh_now()
        return {"ok": True, "id": z.id, "name": z.name}

    @app.delete("/api/zones/{zid}")
    async def cmd_delete_zone(zid: str):
        ok = await asyncio.to_thread(_library().delete_zone, zid)
        if not ok:
            raise HTTPException(404, f"Zone inconnue : {zid}")
        _refresh_now()
        return {"ok": True, "id": zid}

    @app.put("/api/zones/{zid}")
    async def cmd_update_zone(zid: str, body: ZoneUpdateBody):
        lib = _library()
        z = lib.get_zone(zid)
        if z is None:
            raise HTTPException(404, f"Zone inconnue : {zid}")
        if body.name is not None:      z.name = body.name
        if body.zone_type is not None: z.zone_type = body.zone_type
        if body.visible is not None:   z.visible = body.visible
        if body.color is not None:     z.color = body.color
        ok = await asyncio.to_thread(lib.save_zone, z)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde zone")
        _refresh_now()
        return {"ok": True, "id": z.id}

    @app.post("/api/robots/{rid}/tcp")
    async def cmd_get_tcp(rid: str):
        """Calcule la position TCP (x,y,z mm) du robot via FK
        sur ses positions HW courantes."""
        ctrl = _get_ctrl(rid)
        if not ctrl.is_connected:
            raise HTTPException(409, f"Robot {rid} non connecte")
        try:
            from xrv22.simulation.kinematics import fk_tcp
        except ImportError:
            raise HTTPException(500, "Module kinematics absent")
        positions = await asyncio.to_thread(ctrl.read_positions)
        x, y, z = fk_tcp(dict(positions))
        return {"ok": True, "robot_id": rid, "x": round(x, 1),
                "y": round(y, 1), "z": round(z, 1),
                "positions": {str(k): v for k, v in positions.items()}}

    @app.post("/api/robots/{rid}/check_position")
    async def cmd_check_position(rid: str, body: DirectPositionsBody):
        """Vérifie une position (limites soft + collision zones) sans bouger
        le robot. Retourne {ok, conflicts:[{type,severity,message}]}."""
        ctrl = _get_ctrl(rid)
        try:
            targets = {int(k): int(v) for k, v in body.positions.items()}
        except (ValueError, TypeError):
            raise HTTPException(422, "positions doit etre {axis_int: ticks_int}")
        conflicts = await asyncio.to_thread(ctrl._safety.check_position, targets)
        return {"ok": not conflicts, "conflicts": conflicts}

    # ── Safety Settings (Chantier 2 — Phase 2 Task 3) ──────────────

    @app.get("/api/settings/safety")
    def get_safety_settings():
        lib = _library()
        settings = lib.get_project_settings() if hasattr(lib, "get_project_settings") else {}
        safety = settings.get("safety", {}) if isinstance(settings, dict) else {}
        return {
            "collision_check_enabled": bool(safety.get("collision_check_enabled", True)),
        }

    @app.put("/api/settings/safety")
    async def set_safety_settings(body: SafetySettingsBody):
        lib = _library()
        settings = lib.get_project_settings() if hasattr(lib, "get_project_settings") else {}
        if not isinstance(settings, dict):
            settings = {}
        safety = settings.get("safety", {}) if isinstance(settings.get("safety"), dict) else {}
        if body.collision_check_enabled is not None:
            safety["collision_check_enabled"] = body.collision_check_enabled
        settings["safety"] = safety
        ok = await asyncio.to_thread(lib.set_project_settings, settings)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde settings safety")
        _refresh_now()
        return {"ok": True, "collision_check_enabled": safety["collision_check_enabled"]}

    # ── Robot actif (sync Web <-> Pi tactile) ────────────────────────

    @app.get("/api/ui/active_robot")
    def get_active_robot():
        from xrv22.core.state_store import store
        rid = store.get_system().active_robot_id
        return {"active_robot_id": rid}

    @app.put("/api/ui/active_robot")
    async def set_active_robot(body: ActiveRobotBody):
        from xrv22.core.state_store import store
        from xrv22.robots.robot_registry import registry
        if body.robot_id not in registry.ids():
            raise HTTPException(404, f"Robot inconnu : {body.robot_id}")
        changed = await asyncio.to_thread(store.set_active_robot, body.robot_id)
        return {"ok": True, "active_robot_id": body.robot_id, "changed": changed}

    # ── DXF + G-code Import (Chantiers 2 + 3) ────────────────────────

    @app.post("/api/dxf")
    async def cmd_dxf_to_timeline(
        file: UploadFile = File(...),
        scenario_id: str = Form(...),
        robot_id: str = Form(...),
        duration_s: float = Form(2.0),
        z_surface: float = Form(100.0),
        tool_angle: float = Form(3.14159),
    ):
        """Upload DXF + parser + IK + ajout events MOVE dans timeline scenario."""
        try:
            from xrv22.simulation.dxf_loader import load_dxf
            from xrv22.simulation.kinematics import dxf_to_waypoints
        except ImportError:
            raise HTTPException(500, "Modules DXF/IK absents")
        lib = _library()
        scenario = lib.get_scenario(scenario_id) if hasattr(lib, "get_scenario") else None
        if scenario is None:
            raise HTTPException(404, f"Scenario inconnu : {scenario_id}")
        if robot_id not in _registry().ids():
            raise HTTPException(404, f"Robot inconnu : {robot_id}")

        # Sauvegarde temporaire du fichier
        with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            mesh = await asyncio.to_thread(load_dxf, tmp_path)
            if mesh.is_empty:
                raise HTTPException(422, "DXF vide ou non parsable")
            # Calcul waypoints via IK (scale=1.0 par defaut, offset centre)
            cx, cy, _ = mesh.center()
            waypoints = await asyncio.to_thread(
                dxf_to_waypoints, mesh.segments,
                1.0, (-cx, -cy), z_surface, tool_angle,
            )
            if not waypoints:
                raise HTTPException(422, "Aucun waypoint calculable (hors portee robot)")
        finally:
            try: _Path(tmp_path).unlink()
            except OSError: pass

        # Insertion des events MOVE dans la timeline du scenario
        from xrv22.theme.theme import track_color  # type: ignore  # noqa
        td = scenario.timeline_data or {}
        tracks = td.get("tracks", []) or []
        track_id = f"track_{robot_id}"
        track = next((t for t in tracks if t.get("track_id") == track_id), None)
        if track is None:
            # Cree la piste si absente
            from xrv22.theme import theme as T
            try:
                idx = int(robot_id.rsplit("_", 1)[-1]) - 1
            except ValueError:
                idx = 0
            track = {
                "track_id": track_id, "track_type": "ROBOT",
                "label": f"Robot {robot_id}", "color": T.track_color(idx),
                "robot_id": robot_id, "events": [],
            }
            tracks.append(track)
            order = list(td.get("track_order", []) or [])
            if track_id not in order: order.append(track_id)
            td["track_order"] = order

        # Trouve le dernier instant occupe sur la piste
        t_ms = 0
        for ev in track["events"]:
            end = ev.get("start_ms", 0) + ev.get("duration_ms", 0)
            if end > t_ms: t_ms = end
        dur_ms = int(duration_s * 1000)
        added = 0
        import time as _t
        for i, positions in enumerate(waypoints):
            track["events"].append({
                "event_id": f"evt_{int(_t.time() * 1000)}_{i}",
                "event_type": "MOVE",
                "track_id": track_id,
                "start_ms": t_ms, "duration_ms": dur_ms,
                "label": f"DXF {i+1}/{len(waypoints)}",
                "parameters": {
                    "positions": {str(k): int(v) for k, v in positions.items()},
                    "duration_s": float(duration_s),
                    "speed_pct": 100,
                    "robot_id": robot_id,
                },
            })
            t_ms += dur_ms
            added += 1
        td["tracks"] = tracks
        scenario.timeline_data = td
        await asyncio.to_thread(lib.save_scenario, scenario)
        _refresh_now()
        return {"ok": True, "scenario_id": scenario_id, "waypoints": added,
                "duration_total_s": added * duration_s}

    @app.post("/api/gcode")
    async def cmd_gcode_to_timeline(
        file: UploadFile = File(...),
        scenario_id: str = Form(...),
        robot_id: str = Form(...),
        duration_s: float = Form(2.0),
        z_surface: float = Form(100.0),
        tool_angle: float = Form(3.14159),
    ):
        """Upload G-code + parser + IK + events MOVE timeline."""
        try:
            from xrv22.simulation.gcode_loader import load_gcode, gcode_to_waypoints
            from xrv22.simulation.kinematics import ik_tool_angle
        except ImportError:
            raise HTTPException(500, "Modules G-code/IK absents")
        lib = _library()
        scenario = lib.get_scenario(scenario_id) if hasattr(lib, "get_scenario") else None
        if scenario is None:
            raise HTTPException(404, f"Scenario inconnu : {scenario_id}")
        if robot_id not in _registry().ids():
            raise HTTPException(404, f"Robot inconnu : {robot_id}")

        with tempfile.NamedTemporaryFile(suffix=".gcode", delete=False) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        try:
            program = await asyncio.to_thread(load_gcode, tmp_path)
            xyzf = await asyncio.to_thread(gcode_to_waypoints, program, 1.0,
                                            (0.0, 0.0, z_surface))
            if not xyzf:
                raise HTTPException(422, "G-code vide ou non parsable")
            # IK pour chaque point cartesien
            waypoints: list = []
            for x, y, z, _f in xyzf:
                try:
                    pos = ik_tool_angle(x, y, z, tool_angle)
                    if pos:
                        waypoints.append(pos)
                except Exception:
                    pass
            if not waypoints:
                raise HTTPException(422, "Aucun point G-code atteignable par le robot")
        finally:
            try: _Path(tmp_path).unlink()
            except OSError: pass

        # Insertion identique a DXF
        td = scenario.timeline_data or {}
        tracks = td.get("tracks", []) or []
        track_id = f"track_{robot_id}"
        track = next((t for t in tracks if t.get("track_id") == track_id), None)
        if track is None:
            from xrv22.theme import theme as T
            try: idx = int(robot_id.rsplit("_", 1)[-1]) - 1
            except ValueError: idx = 0
            track = {
                "track_id": track_id, "track_type": "ROBOT",
                "label": f"Robot {robot_id}", "color": T.track_color(idx),
                "robot_id": robot_id, "events": [],
            }
            tracks.append(track)
            order = list(td.get("track_order", []) or [])
            if track_id not in order: order.append(track_id)
            td["track_order"] = order

        t_ms = 0
        for ev in track["events"]:
            end = ev.get("start_ms", 0) + ev.get("duration_ms", 0)
            if end > t_ms: t_ms = end
        dur_ms = int(duration_s * 1000)
        added = 0
        import time as _t
        for i, positions in enumerate(waypoints):
            track["events"].append({
                "event_id": f"evt_{int(_t.time() * 1000)}_{i}",
                "event_type": "MOVE",
                "track_id": track_id,
                "start_ms": t_ms, "duration_ms": dur_ms,
                "label": f"G-code {i+1}/{len(waypoints)}",
                "parameters": {
                    "positions": {str(k): int(v) for k, v in positions.items()},
                    "duration_s": float(duration_s),
                    "speed_pct": 100,
                    "robot_id": robot_id,
                },
            })
            t_ms += dur_ms
            added += 1
        td["tracks"] = tracks
        scenario.timeline_data = td
        await asyncio.to_thread(lib.save_scenario, scenario)
        _refresh_now()
        return {"ok": True, "scenario_id": scenario_id, "waypoints": added,
                "duration_total_s": added * duration_s}

    @app.post("/api/hardware/devices")
    async def cmd_add_device(body: DeviceBody):
        """Ajoute un device Arduino dans hardware.json."""
        lib = _library()
        hw = lib.get_hardware() or {}
        devices = list(hw.get("devices", []) or [])
        # Genere un id si pas fourni, evite doublons par port
        for d in devices:
            if d.get("port") == body.port:
                raise HTTPException(409, f"Device deja existant sur port {body.port}")
        new_dev = {
            "id": f"dev_{len(devices) + 1}",
            "name": body.name,
            "port": body.port,
            "baud": body.baud,
            "device_type": body.device_type,
            "channels": [],
        }
        devices.append(new_dev)
        hw["devices"] = devices
        ok = await asyncio.to_thread(lib.save_hardware, hw)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde device")
        _refresh_now()
        return {"ok": True, "device": new_dev}

    @app.delete("/api/hardware/devices/{did}")
    async def cmd_delete_device(did: str):
        """Supprime un device Arduino par id."""
        lib = _library()
        hw = lib.get_hardware() or {}
        devices = list(hw.get("devices", []) or [])
        before = len(devices)
        devices = [d for d in devices if d.get("id") != did]
        if len(devices) == before:
            raise HTTPException(404, f"Device inconnu : {did}")
        hw["devices"] = devices
        await asyncio.to_thread(lib.save_hardware, hw)
        _refresh_now()
        return {"ok": True, "id": did}

    # ── Robots CRUD (PRIO 3) ─────────────────────────────────────────

    @app.post("/api/robots")
    async def cmd_add_robot(body: AddRobotBody):
        """Ajoute un robot au registry (defaut motor_ids 1-7)."""
        reg = _registry()
        if body.robot_id in reg.ids():
            raise HTTPException(409, f"Robot deja existant : {body.robot_id}")
        await asyncio.to_thread(reg.add, body.robot_id, body.motor_ids)
        _refresh_now()
        return {"ok": True, "robot_id": body.robot_id}

    @app.delete("/api/robots/{rid}")
    async def cmd_remove_robot(rid: str):
        """Retire un robot du registry."""
        reg = _registry()
        if rid not in reg.ids():
            raise HTTPException(404, f"Robot inconnu : {rid}")
        if len(reg.ids()) <= 1:
            raise HTTPException(409, "Impossible de supprimer le dernier robot")
        await asyncio.to_thread(reg.remove, rid)
        _refresh_now()
        return {"ok": True, "robot_id": rid}

    # ── Projects (PRIO 1) ────────────────────────────────────────────

    @app.post("/api/projects/new")
    async def cmd_project_new(body: NewProjectBody):
        """Cree un nouveau projet (echec si nom existe deja)."""
        from xrv22.services.project_service import project
        ok = await asyncio.to_thread(project.new_project, body.name)
        if not ok:
            raise HTTPException(409, f"Nom de projet deja utilise : {body.name}")
        _refresh_now()
        return {"ok": True, "name": body.name}

    @app.post("/api/projects/load")
    async def cmd_project_load(body: LoadProjectBody):
        """Charge un projet existant a partir du chemin .xrv22 ou dossier."""
        from xrv22.services.project_service import project
        ok = await asyncio.to_thread(project.load, body.path)
        if not ok:
            raise HTTPException(404, f"Impossible de charger : {body.path}")
        _refresh_now()
        return {"ok": True, "path": body.path}

    @app.post("/api/projects/save")
    async def cmd_project_save():
        """Sauvegarde le projet actif."""
        from xrv22.services.project_service import project
        ok = await asyncio.to_thread(project.save)
        return {"ok": bool(ok)}

    @app.post("/api/projects/export")
    async def cmd_project_export(body: LoadProjectBody):
        """Exporte le projet actif vers un dossier arbitraire (path)."""
        ok = await asyncio.to_thread(_library().export_project, _Path(body.path))
        if not ok:
            raise HTTPException(500, "Echec export (projet vide ou destination invalide)")
        return {"ok": True, "destination": body.path}

    # Cles "metier" qui peuvent etre au top-level d'un event mais doivent
    # etre dans `parameters` pour que TimelineEvent.get_param() les trouve.
    _MIGRATABLE_PARAM_KEYS = (
        "positions", "duration_s", "speed_pct", "robot_id",
        "position_id", "position_name",
        "sensor_id", "timeout_ms", "on_timeout",
        "device_id", "command",
    )

    def _migrate_event(ev: dict) -> dict:
        """Migre les params top-level vers `parameters` + convertit
        les cles int (positions, soft_limits) qui ont ete serialisees en str
        par JSON. Le safety_manager s'attend a des int comme motor_id."""
        params = dict(ev.get("parameters", {}) or {})
        for k in _MIGRATABLE_PARAM_KEYS:
            if k in ev and k not in params:
                params[k] = ev[k]
        # Convertit les cles de positions {str -> int} -> {int -> int}
        pos = params.get("positions")
        if isinstance(pos, dict):
            try:
                params["positions"] = {int(k): int(v) for k, v in pos.items()}
            except (ValueError, TypeError):
                pass  # garde tel quel si conversion impossible
        ev["parameters"] = params
        return ev

    @app.post("/api/scenarios/{sid}/timeline_data")
    async def cmd_scenario_set_timeline(sid: str, body: TimelineDataBody):
        """Remplace timeline_data du scenario.
        - Auto-purge des pistes ROBOT dont robot_id n'existe plus (anti-ghost)
        - Auto-migration des events : positions/duration_s/etc top-level -> parameters
          (pour que _handle_move retrouve evt.get_param("positions"))"""
        lib = _library()
        scenario = lib.get_scenario(sid) if hasattr(lib, "get_scenario") else None
        if scenario is None:
            raise HTTPException(404, f"Scenario inconnu : {sid}")
        td = dict(body.timeline_data)
        valid_rids = set(_registry().ids())
        tracks = td.get("tracks", []) or []
        keep, dropped = [], []
        for t in tracks:
            if t.get("track_type") == "ROBOT" and t.get("robot_id") not in valid_rids:
                dropped.append(t.get("track_id"))
                continue
            t["events"] = [_migrate_event(dict(ev)) for ev in (t.get("events") or [])]
            keep.append(t)
        td["tracks"] = keep
        td["track_order"] = [tid for tid in (td.get("track_order") or []) if tid not in dropped]
        scenario.timeline_data = td
        ok = await asyncio.to_thread(lib.save_scenario, scenario)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde scenario")
        _refresh_now()
        return {"ok": True, "scenario_id": sid,
                "tracks": len(keep), "dropped_ghosts": dropped}

    @app.post("/api/scenarios/{sid}/purge_ghost_tracks")
    async def cmd_scenario_purge_ghosts(sid: str):
        """Supprime du timeline_data les pistes ROBOT dont le robot_id
        n'existe plus dans le registry (pistes fantomes du scenario)."""
        lib = _library()
        scenario = lib.get_scenario(sid) if hasattr(lib, "get_scenario") else None
        if scenario is None:
            raise HTTPException(404, f"Scenario inconnu : {sid}")
        td = scenario.timeline_data or {}
        valid_rids = set(_registry().ids())
        tracks = td.get("tracks", []) or []
        keep, dropped = [], []
        for t in tracks:
            if t.get("track_type") == "ROBOT" and t.get("robot_id") not in valid_rids:
                dropped.append(t.get("track_id"))
            else:
                keep.append(t)
        td["tracks"] = keep
        td["track_order"] = [tid for tid in (td.get("track_order") or []) if tid not in dropped]
        scenario.timeline_data = td
        ok = await asyncio.to_thread(lib.save_scenario, scenario)
        if not ok:
            raise HTTPException(500, "Echec sauvegarde scenario")
        _refresh_now()
        return {"ok": True, "scenario_id": sid, "removed_tracks": dropped}

    def _normalize_timeline_data(td: dict) -> dict:
        """Convertit les cles 'positions' str->int dans tous les events
        MOVE (JSON serialise tjs les cles en str, mais le safety attend int)."""
        td = dict(td)
        for t in td.get("tracks", []) or []:
            for ev in t.get("events", []) or []:
                params = ev.get("parameters", {}) or {}
                pos = params.get("positions")
                if isinstance(pos, dict):
                    try:
                        params["positions"] = {int(k): int(v) for k, v in pos.items()}
                    except (ValueError, TypeError):
                        pass
                ev["parameters"] = params
        return td

    @app.post("/api/scenarios/{sid}/play")
    async def cmd_scenario_play(sid: str, body: PlayBody | None = None):
        """Charge le scenario dans l'engine et lance la lecture timeline."""
        lib = _library()
        scenario = lib.get_scenario(sid) if hasattr(lib, "get_scenario") else None
        if scenario is None:
            raise HTTPException(404, f"Scenario inconnu : {sid}")
        if not scenario.timeline_data:
            raise HTTPException(409, "Scenario sans timeline_data")
        from xrv22.timeline.timeline_model import TimelineModel
        from xrv22.core.execution_engine import engine
        td = _normalize_timeline_data(scenario.timeline_data or {})
        model = TimelineModel.from_dict(td)
        engine.set_model(model)

        # Garde-fou anti-conflit : avant de lancer la timeline, on retire la
        # main a tout pilotage Direct (web ou autre) sur les robots utilises par
        # la suite. Sinon la boucle useDirectRamp du web continuerait d'ecrire
        # sur les memes servos pendant les MOVE de la timeline = deux pilotes en
        # conflit. Pour chaque robot utilise et connecte :
        #   1) restaure le profil moteur confort (le Direct l'avait mis en court
        #      ~60ms) ;
        #   2) prend la main au nom de l'engine (control_owner = "engine") ;
        #   3) publie robot.control_changed -> le web coupe alors son Direct
        #      automatiquement (arbitrage owner != "web", cf. store.tsx).
        reg = _registry()
        for rid in engine._robots_used_in_timeline():
            ctrl = reg.get(rid)
            if ctrl is None:
                continue
            ctrl.control_owner = "engine"
            await asyncio.to_thread(ctrl.set_direct_mode,
                                    ctrl.comfort_vel, ctrl.comfort_acc)
            _bus().publish("robot.control_changed",
                           {"robot_id": rid, "owner": ctrl.control_owner})

        from_ms = body.from_ms if body else 0
        ok = await asyncio.to_thread(engine.play, from_ms)
        return {"ok": bool(ok), "scenario_id": sid, "state": engine.state}

    @app.post("/api/scenarios/{sid}/stop")
    async def cmd_scenario_stop(sid: str):
        """Arret de l'execution timeline en cours."""
        from xrv22.core.execution_engine import engine
        await asyncio.to_thread(engine.stop)
        return {"ok": True, "state": engine.state}

    # ── WebSocket : broadcast des events du bus + tick positions live ─
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        """Client se connecte, recoit les events broadcastes
        jusqu'a deconnexion. Auth via ?token=<token> en query (les WS
        cote browser n'envoient pas de header Authorization standard)."""
        from xrv22.server.ws_broadcaster import broadcaster
        from xrv22.server.jog_ws import route_jog_message
        from xrv22.core.jog_engine import jog_engine
        import json
        token = ws.query_params.get("token")
        if not check_token(token):
            await ws.close(code=4401)  # 4401 = unauthorized (custom range)
            return
        await ws.accept()
        await broadcaster.register(ws)
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    route_jog_message(jog_engine, json.loads(raw))
                except Exception:
                    pass            # message non-jog ou JSON invalide -> ignore
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            _LOG.warning("WS endpoint exception : %s", exc)
        finally:
            await broadcaster.unregister(ws)

    # ── Etape 3 : sert le frontend React build (xrv22/server/static) ──
    # Monte en dernier (catch-all) : les routes /api/* et /ws sont resolues
    # avant ce mount. Pour le SPA routing client-side (react-router), il faut
    # un fallback explicite qui sert index.html pour toute URL inconnue
    # (sinon /timeline, /positions, etc. retournent 404 a Cmd+R).
    static_dir = _Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/assets",
                  StaticFiles(directory=str(static_dir / "assets")),
                  name="web_assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """Fallback SPA : sert index.html pour toute URL non-API.
            Les routes /api/* et /ws sont prioritaires, /assets/* est servi
            par StaticFiles. Tout le reste -> index.html (react-router prend
            la suite cote client)."""
            # Fichiers static a la racine (favicon, icons.svg, etc.)
            if full_path:
                fp = static_dir / full_path
                if fp.is_file():
                    return FileResponse(fp)
            # Sinon : index.html (SPA routing client-side).
            # no-cache : index.html pointe vers le bundle JS hashe courant ;
            # sans ca le navigateur reste bloque sur un ancien build apres
            # un deploiement (d'ou les "idem" persistants cote client).
            return FileResponse(
                static_dir / "index.html",
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )
    else:
        _LOG.info("Pas de build web a servir (dossier %s absent)", static_dir)

    return app


# ── Lancement Uvicorn dans un thread ────────────────────────────

_server_thread: threading.Thread | None = None
_uvicorn_server = None


def start_server(host: str = "0.0.0.0", port: int = 8080) -> bool:
    """Demarre le serveur Uvicorn dans un thread daemon.

    Retourne True si le serveur est demarre, False si fastapi/uvicorn
    ne sont pas installes (lib disponible cote Pi via apt ou pip).
    Idempotent : ne demarre qu'une fois.
    """
    global _server_thread, _uvicorn_server
    if not FASTAPI_OK:
        return False
    if _server_thread is not None:
        return True
    app = create_app()
    config = uvicorn.Config(app, host=host, port=port,
                            log_level="warning", access_log=False)
    _uvicorn_server = uvicorn.Server(config)

    def _run() -> None:
        try:
            _uvicorn_server.run()
        except Exception as exc:
            _LOG.error("API : crash Uvicorn : %s", exc)

    _server_thread = threading.Thread(
        target=_run, name="xrv22-api", daemon=True)
    _server_thread.start()
    _LOG.info("API XRV22 demarree sur http://%s:%d", host, port)
    _print_access_qr(host, port)
    return True


def _print_access_qr(host: str, port: int) -> None:
    """Affiche dans les logs un QR code avec l'URL + token pour
    qu'un client (mobile, autre poste) se connecte sans saisie."""
    try:
        from xrv22.server.auth import get_token, make_qr_ascii
    except ImportError:
        return
    # Si on bind sur 0.0.0.0, on choisit raspberrypi.local comme URL
    # affichable (le QR contient un nom resoluble en LAN).
    display_host = "raspberrypi.local" if host in ("0.0.0.0", "::") else host
    url = f"http://{display_host}:{port}/?token={get_token()}"
    _LOG.info("Acces UI Web (scanner pour connexion sans saisie) :\n%s\n%s",
              url, make_qr_ascii(url))


def stop_server() -> None:
    """Arret propre (utile en tests). Le thread daemon se ferme
    avec le process si on n'appelle pas explicitement."""
    global _uvicorn_server, _server_thread
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
        _uvicorn_server = None
    _server_thread = None
