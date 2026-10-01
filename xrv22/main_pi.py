"""
xrv22/main_pi.py
─────────────────
Point d'entree XRV22 PRO — couche UI Raspberry Pi (7" tactile, 800x480).

Reutilise le bootstrap de la version Mac (logging, migration, watchdog,
chargement projet) mais lance MainWindowPi a la place de l'UI Mac.

Commandes :
  python -m xrv22.main_pi                 # Mode normal (plein ecran sous Linux)
  python -m xrv22.main_pi --sim           # Mode simulation
  python -m xrv22.main_pi --windowed      # Force fenetre (debug sur Mac)
  python -m xrv22.main_pi --project X     # Charge un projet au boot
  python -m xrv22.main_pi --debug

La version Mac (xrv22.main) est inchangee — ce fichier est ajoute a cote.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from xrv22 import main as main_mac
from xrv22.services.logger import get_logger
from xrv22.services.watchdog import watchdog

_LOG = get_logger("MainPi")

# VID FTDI (Robotis U2D2 = FT232H/FT232R)
_U2D2_VIDS = {0x0403}

# Mapping serial U2D2 -> robot_id (lecture seule, source de verite par cable physique)
_U2D2_MAPPING_PATH = Path.home() / "xrv22" / "XRV22_LIBRARY" / "global" / "u2d2_mapping.json"

# Extrait le serial FTDI depuis le nom de symlink /dev/serial/by-id/
# ex : usb-FTDI_USB__-__Serial_Converter_FT94THU9-if00-port0
_FTDI_SERIAL_RE = re.compile(r"FTDI_USB.*Serial_Converter_([A-Z0-9]+)-if")


def list_u2d2_ports() -> list:
    """Liste tous les ports U2D2 (FTDI) disponibles."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports() if p.vid in _U2D2_VIDS]


def list_u2d2_with_serials() -> list:
    """Liste les U2D2 detectes avec leur serial FTDI.
    Retourne [(serial, port), ...] tries par serial. Source : /dev/serial/by-id."""
    by_id_dir = "/dev/serial/by-id"
    if not os.path.isdir(by_id_dir):
        return []
    result = []
    for entry in os.listdir(by_id_dir):
        m = _FTDI_SERIAL_RE.search(entry)
        if not m:
            continue
        try:
            target = os.path.realpath(os.path.join(by_id_dir, entry))
        except OSError:
            continue
        if target.startswith("/dev/tty"):
            result.append((m.group(1), target))
    return sorted(result)


def _load_u2d2_mapping() -> dict:
    """Charge le mapping serial U2D2 -> robot_id depuis JSON.
    Retourne {} si absent, illisible ou invalide."""
    try:
        with open(_U2D2_MAPPING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


_AUTO_CONNECT_LOCK = __import__("threading").Lock()


def _try_set_torque(ctrl, rid: str, cycle: int) -> bool:
    """Active le torque, retourne True si succès effectif."""
    try:
        ok = ctrl.set_torque(True)
    except Exception as exc:
        _LOG.warning("auto-torque %s cycle %d : %s", rid, cycle, exc)
        return False
    return bool(ok) and getattr(ctrl, "torque_enabled", False)


def _restore_motion_profile(ctrl) -> None:
    """Réapplique le profile de vitesse (les reboots l'ont effacé)."""
    try:
        ctrl.apply_motion_profile()
    except Exception:
        pass


def _reboot_all_motors(ctrl, motor_ids) -> int:
    """Reboote tous les moteurs, retourne le nombre de reboots réussis."""
    rebooted = 0
    for mid in motor_ids:
        try:
            if ctrl.reboot_motor(mid):
                rebooted += 1
        except Exception:
            pass
    return rebooted


def _safe_torque_with_reboot(ctrl, rid: str) -> None:
    """Active le torque ; en cas d'échec HW partiel, reboot les moteurs
    fautifs et réessaie. Jusqu'à 2 cycles."""
    try:
        from xrv22.robots.robot_profiles import profiles
    except ImportError:
        return
    profile = profiles.get(rid)
    motor_ids = list(profile.motor_ids) if profile else []

    for cycle in (1, 2):
        if _try_set_torque(ctrl, rid, cycle):
            _LOG.info("auto-torque: %s -> ON", rid)
            _restore_motion_profile(ctrl)
            return
        _LOG.warning("auto-torque %s cycle %d : torque OFF, tentative reboot",
                     rid, cycle)
        if _reboot_all_motors(ctrl, motor_ids) == 0:
            _LOG.warning("auto-torque %s : aucun moteur reboote, abandon", rid)
            return
        # Petit délai pour laisser les moteurs revenir
        __import__("time").sleep(0.4)
    _LOG.error("auto-torque %s : echec apres reboot, torque OFF", rid)


# Ordre d'attribution USB historique (fallback si u2d2_mapping.json absent).
# robot_3 prend le 1er U2D2 detecte (USB0), robot_2 USB1, robot_1 USB2.
AUTO_CONNECT_ORDER = ("robot_3", "robot_2", "robot_1")


def _sanitize_stale_connections(registry, valid_ports: set) -> None:
    """Force-deconnecte les robots dont le port memorise n'est plus la
    ou n'est pas un chemin Linux valide (ex. ancien port Mac)."""
    for rid in AUTO_CONNECT_ORDER:
        ctrl = registry.get(rid)
        if ctrl is None:
            continue
        pname = ctrl.port_name or ""
        invalid = pname and (not pname.startswith("/dev/tty"))
        stale = pname and pname not in valid_ports
        if (ctrl.is_connected and stale) or invalid:
            _LOG.info("auto-connect: sanitize %s (port=%s)", rid, pname)
            try:
                ctrl.disconnect()
            except Exception:
                pass


def _connect_one(registry, rid: str, port: str) -> bool:
    """Connecte un robot sur un port et active le torque.
    Retourne True si connexion OK (le torque peut avoir echoue separement)."""
    ctrl = registry.get(rid)
    if ctrl is None or ctrl.is_connected:
        return False
    _LOG.info("auto-connect: %s sur %s", rid, port)
    try:
        ok = ctrl.connect(port)
    except Exception as exc:
        _LOG.warning("auto-connect: exception sur %s : %s", rid, exc)
        return False
    if not ok:
        _LOG.warning("auto-connect: echec %s sur %s", rid, port)
        return False
    _safe_torque_with_reboot(ctrl, rid)
    return True


def _safe_disconnect(ctrl) -> None:
    """Déconnecte un contrôleur, en absorbant les erreurs."""
    try:
        ctrl.disconnect()
    except Exception:
        pass


def _free_port_from_other_robots(registry, rid: str, port: str) -> None:
    """Si un autre robot occupe le port, le libère."""
    for other_rid in AUTO_CONNECT_ORDER:
        if other_rid == rid:
            continue
        other = registry.get(other_rid)
        if other and other.is_connected and other.port_name == port:
            _LOG.info("auto-connect: libere %s du port %s (revient a %s)",
                      other_rid, port, rid)
            _safe_disconnect(other)


def _connect_one_mapped(registry, rid: str, port: str, serial: str) -> None:
    """Pour un U2D2 mappé à un robot : libère les conflits puis connecte."""
    ctrl = registry.get(rid)
    if ctrl is None:
        _LOG.warning("auto-connect: mapping pointe sur %s inconnu (serial=%s)",
                     rid, serial)
        return
    # Si déjà connecté sur le bon port, rien à faire
    if ctrl.is_connected and ctrl.port_name == port:
        return
    # Si connecté sur un autre port (mauvaise affectation passée), on libère
    if ctrl.is_connected and ctrl.port_name != port:
        _LOG.info("auto-connect: %s sur mauvais port %s, reaffectation -> %s",
                  rid, ctrl.port_name, port)
        _safe_disconnect(ctrl)
    _free_port_from_other_robots(registry, rid, port)
    _connect_one(registry, rid, port)


def _connect_by_mapping(registry, mapping: dict, u2d2_list: list) -> set:
    """Attribue chaque U2D2 à son robot via le mapping serial -> robot_id.
    Retourne l'ensemble des serials non couverts par le mapping (à traiter en
    fallback ordre). u2d2_list = [(serial, port), ...]."""
    unknown_serials: set = set()
    for serial, port in u2d2_list:
        rid = mapping.get(serial)
        if not rid:
            unknown_serials.add(serial)
            continue
        _connect_one_mapped(registry, rid, port, serial)
    return unknown_serials


def _connect_mapped(registry, mapping: dict, u2d2_list: list) -> set:
    """Phase mapping : connecte chaque U2D2 via u2d2_mapping.json.
    Retourne l'ensemble des serials non couverts par le mapping."""
    if not (mapping and u2d2_list):
        return set()
    unknown = _connect_by_mapping(registry, mapping, u2d2_list)
    if unknown:
        _LOG.warning("auto-connect: U2D2 hors mapping : %s (fallback ordre)",
                     sorted(unknown))
    return unknown


def _used_mapped_ports(registry, ports) -> set:
    """Ports déjà occupés par un robot connecté, parmi les U2D2 détectés."""
    used = set()
    for rid in AUTO_CONNECT_ORDER:
        ctrl = registry.get(rid)
        if ctrl and ctrl.is_connected and ctrl.port_name in ports:
            used.add(ctrl.port_name)
    return used


def _compute_free_ports(ports: list, u2d2_list: list, mapping: dict,
                        unknown_serials: set, used_ports: set) -> list:
    """Ports à attribuer en fallback ordre (hors ceux déjà utilisés).
    Avec mapping : uniquement les ports des serials non couverts par le mapping."""
    if mapping and u2d2_list:
        return sorted(p for s, p in u2d2_list
                      if s in unknown_serials and p not in used_ports)
    return sorted(p for p in ports if p not in used_ports)


def _connect_fallback_order(registry, free_ports: list) -> None:
    """Attribue les ports libres aux robots dans l'ordre historique."""
    for rid in AUTO_CONNECT_ORDER:
        if not free_ports:
            break
        ctrl = registry.get(rid)
        if ctrl is None or ctrl.is_connected:
            continue
        port = free_ports.pop(0)
        if not _connect_one(registry, rid, port):
            free_ports.append(port)  # remet en pool si echec connexion


def resolve_port_for_robot(rid: str, mapping: dict, u2d2_list: list):
    """Port du U2D2 mappe a `rid` (serial -> robot_id), s'il est detecte.
    Retourne le chemin /dev/tty... ou None si `rid` n'est pas mappe ou si son
    U2D2 n'est pas branche. u2d2_list = [(serial, port), ...]."""
    serials_for_rid = {s for s, r in mapping.items() if r == rid}
    for serial, port in u2d2_list:
        if serial in serials_for_rid:
            return port
    return None


def auto_connect_one(rid: str) -> bool:
    """Connecte UNIQUEMENT le robot `rid` (clic "Connecter" sur une carte).
    Resout son port via le mapping U2D2 (stable au reboot) ; a defaut, prend
    un U2D2 libre non utilise par un autre robot. Ne touche jamais aux autres
    robots — contrairement a auto_connect_all_u2d2. Retourne True si connecte."""
    try:
        from xrv22.robots.robot_registry import registry
    except ImportError:
        return False

    if not _AUTO_CONNECT_LOCK.acquire(blocking=False):
        return False
    try:
        ctrl = registry.get(rid)
        if ctrl is None:
            return False
        if ctrl.is_connected:
            return True

        u2d2_list = list_u2d2_with_serials()  # [(serial, port), ...]
        ports = [p for _, p in u2d2_list] or list_u2d2_ports()
        if not ports:
            _LOG.info("auto-connect-one: aucun U2D2 detecte")
            return False

        mapping = _load_u2d2_mapping()
        port = resolve_port_for_robot(rid, mapping, u2d2_list)
        if port:
            serial = next((s for s, p in u2d2_list if p == port), "")
            _connect_one_mapped(registry, rid, port, serial)
        else:
            # Pas de mapping pour ce robot : 1er U2D2 libre (non pris par un autre)
            used = {c.port_name for r in AUTO_CONNECT_ORDER
                    for c in [registry.get(r)]
                    if c and c.is_connected and c.port_name}
            free = [p for p in ports if p not in used]
            if not free:
                _LOG.warning("auto-connect-one: aucun U2D2 libre pour %s", rid)
                return False
            _connect_one(registry, rid, free[0])
        return ctrl.is_connected
    finally:
        _AUTO_CONNECT_LOCK.release()


def auto_connect_all_u2d2() -> None:
    """Connecte automatiquement chaque U2D2 à son robot.
    Mode prioritaire : mapping serial U2D2 -> robot_id (u2d2_mapping.json),
    indépendant du port USB et du boot order.
    Fallback : ordre de détection (AUTO_CONNECT_ORDER) pour les U2D2 non
    mappés ou si le mapping est absent.
    Idempotent. Verrou global : évite que deux ticks concurrents s'entrelacent.
    """
    try:
        from xrv22.robots.robot_registry import registry
    except ImportError:
        return

    if not _AUTO_CONNECT_LOCK.acquire(blocking=False):
        return  # un autre tick est en cours
    try:
        u2d2_list = list_u2d2_with_serials()  # [(serial, port), ...]
        ports = [p for _, p in u2d2_list] or list_u2d2_ports()
        if not ports:
            _LOG.info("auto-connect: aucun U2D2 detecte")
            return

        _sanitize_stale_connections(registry, set(ports))

        # 1) Mode mapping : serial U2D2 -> robot_id (stable au reboot)
        mapping = _load_u2d2_mapping()
        unknown_serials = _connect_mapped(registry, mapping, u2d2_list)

        # 2) Fallback : ordre historique pour les ports non couverts par le mapping
        used_ports = _used_mapped_ports(registry, ports)
        free_ports = _compute_free_ports(ports, u2d2_list, mapping,
                                         unknown_serials, used_ports)
        if free_ports:
            _connect_fallback_order(registry, free_ports)
    finally:
        _AUTO_CONNECT_LOCK.release()


# Alias historique pour compatibilite
_auto_connect_unique_u2d2 = auto_connect_all_u2d2


def force_robot_1_as_master() -> None:
    """UI Pi : Robot 1 est master au boot uniquement."""
    try:
        from xrv22.robots.robot_registry import registry
        from xrv22.services.event_bus import bus
    except ImportError:
        return
    if "robot_1" in registry.ids() and registry.master_id != "robot_1":
        registry.set_master("robot_1")
        bus.publish("robot.master_changed", {"robot_id": "robot_1"})
        _LOG.info("Master force a robot_1")


def ensure_valid_master() -> None:
    """Tick hot-plug : ne touche au master que s'il est invalide
    (master_id absent ou disparu du registry). Respecte le choix de
    l'utilisateur fait dans PILOTAGE via les chevrons < / >."""
    try:
        from xrv22.robots.robot_registry import registry
        from xrv22.services.event_bus import bus
    except ImportError:
        return
    ids = registry.ids()
    current = registry.master_id
    if current and current in ids:
        return  # master valide -> on respecte le choix utilisateur
    fallback = "robot_1" if "robot_1" in ids else (ids[0] if ids else None)
    if fallback:
        registry.set_master(fallback)
        bus.publish("robot.master_changed", {"robot_id": fallback})
        _LOG.info("Master invalide -> fallback %s", fallback)


def propagate_master_to_slaves() -> None:
    """Wrapper retro-compat. La logique vit dans
    RobotRegistry.propagate_from_master (SSOT backend)."""
    try:
        from xrv22.robots.robot_registry import registry
    except ImportError:
        return
    if not registry.master_id:
        return
    registry.propagate_from_master(kind="all")


_LEGACY_TOP_LEVEL_KEYS = (
    "positions", "duration_s", "speed_pct", "robot_id",
    "position_id", "position_name", "sensor_id",
    "timeout_ms", "on_timeout", "device_id", "command",
)


def _migrate_event_top_level(ev: dict) -> dict:
    """Migre les clés top-level (anciens formats) vers ev['parameters']."""
    params = ev.get("parameters", {}) or {}
    for k in _LEGACY_TOP_LEVEL_KEYS:
        if k in ev and k not in params:
            params[k] = ev[k]
    return params


def _normalize_positions(params: dict) -> None:
    """Convertit params['positions'] str -> int en place (JSON sérialise tjs en str)."""
    pos = params.get("positions")
    if not isinstance(pos, dict):
        return
    try:
        params["positions"] = {int(k): int(v) for k, v in pos.items()}
    except (ValueError, TypeError):
        pass


def _normalize_timeline_data(td: dict) -> dict:
    """Normalise un dict timeline pour l'engine : migre les clés top-level vers
    parameters et convertit les clés de positions en int. Identique au helper
    côté API web."""
    td = dict(td)
    for t in td.get("tracks", []) or []:
        for ev in t.get("events", []) or []:
            params = _migrate_event_top_level(ev)
            _normalize_positions(params)
            ev["parameters"] = params
    return td


def _wire_ui_pi_play() -> None:
    """Connecte les events bus 'ui.request.play/pause/stop' (publies
    par screen_execution.py) a l'engine d'execution. Sans ce wiring, le bouton
    Play sur l'UI tactile Pi ne declenche rien."""
    try:
        from xrv22.services.event_bus import bus
        from xrv22.library.library_manager import library
        from xrv22.timeline.timeline_model import TimelineModel
        from xrv22.core.execution_engine import engine
    except ImportError:
        _LOG.warning("ui.request.* : import echec, wiring desactive")
        return

    def _on_play(payload: dict) -> None:
        # Si engine deja en cours -> pas de relance (evite conflits de
        # double scheduler / handlers paralleles)
        if engine.state in ("RUNNING",):
            _LOG.info("ui.request.play : engine deja RUNNING, ignore")
            return
        # Si en PAUSED : juste resume sans reload du model
        if engine.state == "PAUSED":
            engine.play(int(payload.get("from_ms", 0)))
            _LOG.info("ui.request.play : resume depuis PAUSED")
            return
        sid = payload.get("scenario_id", "")
        scenario = library.get_scenario(sid) if sid else None
        if scenario is None:
            _LOG.warning("ui.request.play : scenario %r introuvable", sid)
            bus.publish("engine.error", {
                "event_type": "PLAY",
                "message": f"Scenario inconnu : {sid}",
            })
            return
        td = scenario.timeline_data or {}
        if not td:
            _LOG.warning("ui.request.play : scenario %s sans timeline_data", sid)
            return
        try:
            td = _normalize_timeline_data(td)
            model = TimelineModel.from_dict(td)
            engine.set_model(model)
            ok = engine.play(int(payload.get("from_ms", 0)))
            _LOG.info("ui.request.play [%s] : engine.play -> %s", sid, ok)
        except Exception as exc:
            _LOG.exception("ui.request.play [%s] : %s", sid, exc)
            bus.publish("engine.error", {
                "event_type": "PLAY", "message": str(exc),
            })

    def _on_pause(_payload: dict) -> None:
        try: engine.pause()
        except Exception as exc: _LOG.warning("ui.request.pause : %s", exc)

    def _on_stop(_payload: dict) -> None:
        try: engine.stop()
        except Exception as exc: _LOG.warning("ui.request.stop : %s", exc)

    bus.subscribe("ui.request.play", _on_play)
    bus.subscribe("ui.request.pause", _on_pause)
    bus.subscribe("ui.request.stop", _on_stop)
    _LOG.info("UI Pi tactile : ui.request.play/pause/stop connectes a l'engine")


def _ensure_coupling_enabled() -> None:
    """Active le couplage axe 2-3 par defaut au boot s'il n'est pas
    deja configure. Persiste dans hardware.json. Reglage cable physique :
    le bras XRV22 a les 2 servomoteurs 2/3 reliés mecaniquement."""
    try:
        from xrv22.library.library_manager import library
    except ImportError:
        return
    try:
        hw = library.get_hardware() or {}
        cfg = hw.get("coupling", {}) or {}
        if cfg.get("enabled") is True:
            return  # deja active, on respecte la config existante
        hw["coupling"] = {
            "enabled": True,
            "invert": cfg.get("invert", False),
            "ratio": cfg.get("ratio", 1.0),
            "offset": cfg.get("offset", 0),
            "center": cfg.get("center", 2048),
        }
        library.save_hardware(hw)
        _LOG.info("Couplage 2-3 active nativement (config par defaut)")
    except Exception as exc:
        _LOG.warning("Activation couplage echouee : %s", exc)


def parse_args_pi() -> argparse.Namespace:
    """Args CLI specifiques au Pi."""
    p = argparse.ArgumentParser(description="XRV22 PRO — UI Raspberry Pi")
    p.add_argument("--sim",       action="store_true", help="Mode simulation")
    p.add_argument("--project",   type=str, default="",
                   help="Chemin vers un fichier projet .xrv22")
    p.add_argument("--debug",     action="store_true", help="Logs verbeux")
    p.add_argument("--windowed",  action="store_true",
                   help="Force le mode fenetre (par defaut plein ecran sous Linux)")
    return p.parse_args()


def _shutdown_park_robots(timeout_s: float = 15.0) -> None:
    """Sequence d'arret : pour chaque robot connecte, retour
    position travail puis machine via safe_home, puis torque OFF.
    Parallelise sur threads (sinon 3 robots * 2 * home_duration = trop long).
    Le torque OFF est fait meme si safe_home echoue, pour qu'aucun robot
    ne reste sous tension a une position arbitraire."""
    try:
        from xrv22.robots.robot_registry import registry
    except ImportError:
        return
    rids = []
    for rid in registry.ids():
        ctrl = registry.get(rid)
        if ctrl and ctrl.is_connected:
            rids.append(rid)
    if not rids:
        _LOG.info("shutdown: aucun robot connecte a parker")
        return
    _LOG.info("shutdown: parking %d robot(s) (travail -> machine -> torque OFF)",
              len(rids))
    import threading as _th

    def _park_one(rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None:
            return
        try:
            ok, msg = ctrl.safe_home()
            if not ok:
                _LOG.warning("shutdown %s: safe_home echec : %s", rid, msg)
        except Exception as exc:
            _LOG.warning("shutdown %s: safe_home exception : %s", rid, exc)
        try:
            ctrl.set_torque(False)
            _LOG.info("shutdown %s: torque OFF", rid)
        except Exception as exc:
            _LOG.warning("shutdown %s: torque OFF exception : %s", rid, exc)

    threads = [_th.Thread(target=_park_one, args=(rid,), daemon=True)
               for rid in rids]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout_s)
    _LOG.info("shutdown: parking termine")


def _boot_arduino_devices() -> None:
    """Restaure les Arduino mémorisés (hardware.json) et les reconnecte.
    Importe sensor_manager pour qu'il s'abonne au bus capteurs."""
    try:
        from xrv22.hardware.arduino_bridge import arduino
        from xrv22.hardware import sensor_manager  # noqa: F401 (abonnement bus)
        from xrv22.library.library_manager import library
    except Exception as exc:
        _LOG.warning("Arduino boot indisponible : %s", exc)
        return
    try:
        hw = library.get_hardware() or {}
    except Exception as exc:
        _LOG.debug("hardware.json illisible : %s", exc)
        hw = {}
    devices = hw.get("devices", []) or []
    if not devices:
        return
    arduino.restore_devices(devices)
    for d in devices:
        name = d.get("name", "")
        if name:
            try:
                arduino.connect(name)
                _LOG.info("Arduino auto-connect : %s", name)
            except Exception as exc:
                _LOG.warning("Arduino auto-connect %s échec : %s", name, exc)


# Cadence de lecture HW des robots en torque OFF (suivi position/3D live).
_LIVE_POLL_S = 0.1


def _live_position_poll_loop() -> None:
    """Lit en continu les positions des robots CONNECTÉS et en TORQUE OFF, pour
    que la Visu 3D (et tout client web) suive le bras déplacé à la main.

    Gaté sur torque OFF volontairement : un robot torque OFF n'est ni jogé ni
    exécuté → aucune contention sur le bus série (l'archi évite la lecture
    continue pendant le jog 20 Hz). En torque ON, le store est déjà tenu à jour
    par les commandes (write_positions_direct / exécution). read_positions met
    à jour le StateStore, que le tick WS diffuse aux clients."""
    import time as _t
    try:
        from xrv22.robots.robot_registry import registry
    except ImportError:
        return
    while True:
        try:
            for ctrl in registry.all():
                if ctrl.is_connected and not ctrl.torque_enabled:
                    try:
                        ctrl.read_positions()   # lit HW (GroupSyncRead) + maj store
                    except Exception:
                        pass
        except Exception:
            pass
        _t.sleep(_LIVE_POLL_S)


def start_live_position_poll() -> None:
    """Démarre le thread (daemon) de suivi position live."""
    import threading as _th
    _th.Thread(target=_live_position_poll_loop, daemon=True,
               name="LivePosPoll").start()
    _LOG.info("Suivi position live (torque OFF) démarré (%.0fms)", _LIVE_POLL_S * 1000)


def run() -> None:
    """Orchestre le boot + UI Pi + shutdown propre."""
    args = parse_args_pi()

    # Bootstrap partage avec la version Mac (logging, migration, store, projet)
    main_mac._install_crash_traps()
    main_mac.bootstrap(args)

    # Force Robot 1 comme master (UI Pi : convention identique au PC)
    force_robot_1_as_master()
    # Active nativement le couplage axe 2-3 si pas deja configure
    _ensure_coupling_enabled()
    # Connecte les bus ui.request.play/pause/stop (UI tactile Pi -> engine)
    _wire_ui_pi_play()
    # Propage la config du master vers les autres au demarrage
    propagate_master_to_slaves()
    # Auto-connexion U2D2 + torque ON pour tous les adaptateurs branches
    if not args.sim:
        auto_connect_all_u2d2()
        # Force re-application du profile vitesse sur TOUS les robots
        # connectes pour uniformiser la sensation entre robots (sinon vel
        # peut differer si _enable_time_based_profile a echoue partiellement).
        try:
            from xrv22.robots.robot_registry import registry
            for rid in registry.ids():
                ctrl = registry.get(rid)
                if ctrl and ctrl.is_connected:
                    try:
                        ctrl.apply_motion_profile()
                    except Exception:
                        pass
        except Exception:
            pass
        # Capteurs/actionneurs Arduino : restaure + reconnecte les appareils mémorisés
        _boot_arduino_devices()
        # Suivi position live : lit en continu les robots en torque OFF pour que
        # la Visu 3D suive le bras bougé à la main (lecture rapide GroupSyncRead).
        start_live_position_poll()

    # Serveur API REST (lecture seule en Etape 1) — accessible depuis
    # n'importe quel client navigateur sur le LAN via http://xrv22.local:8080
    try:
        from xrv22.server.api import start_server
        start_server(host="0.0.0.0", port=8080)
    except Exception as exc:
        _LOG.warning("Serveur API non demarre : %s", exc)

    # UI
    from xrv22.ui_pi.main_window import MainWindowPi
    app = MainWindowPi(fullscreen=not args.windowed)
    main_mac._install_tk_crash_trap(app)

    _LOG.info("UI Pi prete — entrée mainloop")
    try:
        app.mainloop()
    finally:
        # Sequence parking : retour travail -> machine -> torque OFF
        # avant le shutdown des services (engine/arduino/watchdog).
        if not args.sim:
            try:
                _shutdown_park_robots()
            except Exception as exc:
                _LOG.warning("shutdown park exception : %s", exc)
            try:
                from xrv22.hardware.arduino_bridge import arduino
                arduino.disconnect_all()
            except Exception as exc:
                _LOG.warning("shutdown arduino exception : %s", exc)
        main_mac.shutdown()


if __name__ == "__main__":
    run()
