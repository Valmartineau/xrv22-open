"""
xr200/hardware/arduino_bridge.py
──────────────────────────────────
Bridge Arduino USB — V20.

Gère plusieurs Arduino connectés en USB.
Chaque Arduino peut exposer :
  - des capteurs (canaux float publiés en continu)
  - des actionneurs (SET val → envoi immédiat)
  - des actions (RUN + params → ACK attendu)

Protocole série (auto-détection) :
  JSON  : {"temp": 25.3, "dist": 142}
  KV    : temp=25.3,dist=142
  Colon : TEMP:25.3

Handshake IDENTIFY :
  → {"CMD":"IDENTIFY"}
  ← {"IDENTIFY":{"firmware":"v1.2","sensors":[…],"actuators":[…],"actions":[…]}}

Commande RUN :
  → {"CMD":"RUN","action":"pump_on","params":{"power":128}}
  ← {"STATUS":"OK","action":"pump_on"}

Toutes les mutations publient sur l'EventBus.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from xrv22.config import BAUDRATE_ARDUINO_DEFAULT
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("ArduinoBridge")

try:
    import serial as _serial   # type: ignore
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False

RECONNECT_DELAY_S = 5.0
READ_TIMEOUT_S    = 5.0
IDENTIFY_TIMEOUT_S = 4.0
IDENTIFY_RETRIES  = 3


# ── Dataclasses ──────────────────────────────────────────────────

@dataclass
class SensorChannel:
    name:    str
    unit:    str   = ""
    min_val: float = 0.0
    max_val: float = 100.0
    value:   float = 0.0
    updated: float = 0.0

    def update(self, val: float) -> None:
        self.value   = float(val)
        self.updated = time.time()


@dataclass
class ActuatorChannel:
    name:         str
    kind:         str  = "custom"   # relay, pwm, servo, custom
    label:        str  = ""
    min_val:      float = 0.0
    max_val:      float = 255.0
    cmd_template: str  = ""
    last_value:   float = 0.0
    state_on:     bool = False

    def format_command(self, value: float) -> str:
        """Formate la commande selon le template ou le kind."""
        if self.cmd_template:
            return self.cmd_template.replace("{v}", str(value)) + "\n"
        if self.kind == "relay":
            v = "1" if value else "0"
            return json.dumps({"SET": self.name, "v": v}) + "\n"
        return json.dumps({"SET": self.name, "v": value}) + "\n"


@dataclass
class ArduinoAction:
    name:        str
    label:       str  = ""
    description: str  = ""
    params:      list = field(default_factory=list)
    duration_ms: int  = 0
    has_ack:     bool = True


@dataclass
class ArduinoDevice:
    name:       str
    port:       str
    baud:       int  = BAUDRATE_ARDUINO_DEFAULT
    channels:   Dict[str, SensorChannel]   = field(default_factory=dict)
    actuators:  Dict[str, ActuatorChannel] = field(default_factory=dict)
    actions:    Dict[str, ArduinoAction]   = field(default_factory=dict)
    connected:  bool  = False
    identified: bool  = False
    firmware:   str   = ""
    error:      str   = ""
    last_rx:    float = 0.0


# ── ArduinoBridge ────────────────────────────────────────────────

class ArduinoBridge:
    """
    Gestionnaire multi-Arduino.
    """

    def __init__(self) -> None:
        self.devices: Dict[str, ArduinoDevice] = {}
        self._serials: Dict[str, Any]          = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._identify_threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, threading.Event] = {}
        self._ack_events: Dict[str, threading.Event] = {}
        self._ack_lock = threading.Lock()
        self._lock = threading.Lock()

    # ── Device CRUD ──────────────────────────────────────────────

    def add_device(self, name: str, port: str, baud: int = BAUDRATE_ARDUINO_DEFAULT) -> ArduinoDevice:
        """Enregistre un appareil (sans connecter)."""
        with self._lock:
            dev = ArduinoDevice(name=name, port=port, baud=baud)
            self.devices[name] = dev
        _LOG.info("[%s] Appareil enregistré sur %s", name, port)
        bus.publish("arduino.device_added", {"name": name, "port": port})
        return dev

    def remove_device(self, name: str) -> None:
        """Déconnecte et supprime un appareil."""
        self.disconnect(name)
        with self._lock:
            self.devices.pop(name, None)
        bus.publish("arduino.device_removed", {"name": name})

    def get_device(self, name: str) -> Optional[ArduinoDevice]:
        return self.devices.get(name)

    # ── Connexion ────────────────────────────────────────────────

    def connect(self, name: str) -> bool:
        """Ouvre le port, démarre la lecture, lance IDENTIFY."""
        if not SERIAL_OK:
            _LOG.error("pyserial non disponible — impossible de connecter %s", name)
            return False
        dev = self.devices.get(name)
        if dev is None:
            return False
        if dev.connected:
            _LOG.info("[%s] Déconnexion préalable avant reconnexion", name)
            self.disconnect(name)

        try:
            ser = _serial.Serial(dev.port, dev.baud, timeout=1.0)
            time.sleep(1.5)     # Reset Arduino
            ser.reset_input_buffer()

            self._serials[name] = ser
            dev.connected = True
            dev.error = ""

            stop_evt = threading.Event()
            self._stop_flags[name] = stop_evt
            t = threading.Thread(
                target=self._reader_thread,
                args=(name, ser, stop_evt),
                daemon=True, name=f"Arduino-{name}")
            self._threads[name] = t
            t.start()

            _LOG.info("[%s] Connecté sur %s @ %d", name, dev.port, dev.baud)
            bus.publish("arduino.connected", {"name": name, "port": dev.port})

            # IDENTIFY en arrière-plan (thread tracké pour cleanup)
            id_thread = threading.Thread(
                target=self._identify_device, args=(name,),
                daemon=True, name=f"Arduino-ID-{name}")
            self._identify_threads[name] = id_thread
            id_thread.start()
            return True

        except Exception as exc:
            dev.error = str(exc)
            dev.connected = False
            _LOG.error("[%s] Connexion échouée : %s", name, exc)
            bus.publish("arduino.error", {"name": name, "error": str(exc)})
            return False

    def disconnect(self, name: str) -> None:
        """Déconnexion propre (reader + identify threads)."""
        if name in self._stop_flags:
            self._stop_flags[name].set()
        # Attendre le thread reader
        if name in self._threads:
            self._threads[name].join(timeout=5.0)
            del self._threads[name]
        # Attendre le thread identify
        if name in self._identify_threads:
            self._identify_threads[name].join(timeout=2.0)
            del self._identify_threads[name]
        self._stop_flags.pop(name, None)
        # Nettoyer les ack_events orphelins pour ce device
        with self._ack_lock:
            keys_to_remove = [k for k in self._ack_events if k.startswith(f"{name}.")]
            for k in keys_to_remove:
                self._ack_events.pop(k, None)
        if name in self._serials:
            try:
                self._serials[name].close()
            except Exception as exc:
                _LOG.debug("[%s] Erreur fermeture port: %s", name, exc)
            del self._serials[name]
        dev = self.devices.get(name)
        if dev:
            dev.connected = False
        _LOG.info("[%s] Déconnecté", name)
        bus.publish("arduino.disconnected", {"name": name})

    def disconnect_all(self) -> None:
        """Déconnecte tous les appareils."""
        for name in list(self.devices.keys()):
            self.disconnect(name)

    # ── Commandes ────────────────────────────────────────────────

    def send_command(self, device_name: str, act_name: str,
                      value: float) -> bool:
        """Envoie une commande actionneur."""
        dev = self.devices.get(device_name)
        if dev is None or not dev.connected:
            _LOG.warning("[%s] send_command : non connecté", device_name)
            return False
        act = dev.actuators.get(act_name)
        if act is None:
            _LOG.warning("[%s] Actionneur inconnu : %s", device_name, act_name)
            return False
        ser = self._serials.get(device_name)
        if ser is None:
            return False
        cmd = act.format_command(value)
        try:
            with self._lock:
                ser.write(cmd.encode("utf-8"))
                ser.flush()
            act.last_value = value
            if act.kind == "relay":
                act.state_on = bool(value)
            _LOG.debug("[%s] ← %s", device_name, cmd.strip())
            bus.publish("arduino.command_sent", {
                "device": device_name, "actuator": act_name,
                "value": value, "cmd": cmd.strip()})
            return True
        except Exception as exc:
            _LOG.error("[%s] send_command error : %s", device_name, exc)
            return False

    def run_action(self, device_name: str, action_name: str,
                    params: Optional[Dict[str, Any]] = None,
                    timeout: float = 10.0) -> Tuple[bool, str]:
        """Lance une action + attend ACK."""
        dev = self.devices.get(device_name)
        if dev is None or not dev.connected:
            return False, f"'{device_name}' non connecté"
        act = dev.actions.get(action_name)
        if act is None:
            return False, f"Action '{action_name}' inconnue sur '{device_name}'"

        ok, err = self._action_send_cmd(device_name, action_name, params)
        if not ok:
            return False, err
        if not act.has_ack:
            return True, "Envoyé (pas d'ACK attendu)"
        return self._action_wait_ack(device_name, action_name, timeout)

    def send_raw(self, device_name: str, raw: str) -> bool:
        """Envoie une commande brute (debug/console)."""
        ser  = self._serials.get(device_name)
        dev  = self.devices.get(device_name)
        if ser is None or dev is None or not dev.connected:
            return False
        try:
            with self._lock:
                line = raw if raw.endswith("\n") else raw + "\n"
                ser.write(line.encode("utf-8"))
                ser.flush()
            _LOG.debug("[%s] ← RAW: %s", device_name, raw.strip())
            return True
        except Exception as exc:
            _LOG.error("[%s] send_raw : %s", device_name, exc)
            return False

    # ── Privé : commande action ──────────────────────────────────

    def _action_send_cmd(self, device_name: str, action_name: str,
                          params: Optional[Dict]) -> Tuple[bool, str]:
        """Envoie la commande RUN série."""
        ser = self._serials.get(device_name)
        if ser is None:
            return False, "Port série non disponible"
        cmd = json.dumps({"CMD": "RUN", "action": action_name,
                           "params": params or {}}) + "\n"
        try:
            with self._lock:
                ser.write(cmd.encode("utf-8"))
                ser.flush()
            _LOG.info("[%s] RUN %s params=%s", device_name, action_name, params)
            bus.publish("arduino.action_sent", {
                "device": device_name, "action": action_name, "params": params})
            return True, ""
        except Exception as exc:
            return False, f"Erreur envoi : {exc}"

    def _action_wait_ack(self, device_name: str, action_name: str,
                          timeout: float) -> Tuple[bool, str]:
        """Attend l'ACK de l'action (thread-safe)."""
        ack_key = f"{device_name}.{action_name}"
        with self._ack_lock:
            ack_evt = self._ack_events.setdefault(ack_key, threading.Event())
        triggered = ack_evt.wait(timeout=timeout)
        with self._ack_lock:
            self._ack_events.pop(ack_key, None)
        if triggered:
            return True, "ACK reçu"
        return False, f"Timeout ({timeout}s) — pas d'ACK pour '{action_name}'"

    # ── IDENTIFY handshake ───────────────────────────────────────

    def _identify_device(self, name: str) -> None:
        """Envoie IDENTIFY et attend la réponse."""
        ser = self._serials.get(name)
        dev = self.devices.get(name)
        if ser is None or dev is None:
            return
        _LOG.info("[%s] IDENTIFY handshake…", name)
        for attempt in range(IDENTIFY_RETRIES):
            try:
                with self._lock:
                    ser.reset_input_buffer()
                    ser.write(b'{"CMD":"IDENTIFY"}\n')
                    ser.flush()
            except Exception as exc:
                _LOG.error("[%s] IDENTIFY envoi échoué : %s", name, exc)
                return
            if self._identify_wait_response(name, ser, dev):
                return
            _LOG.warning("[%s] IDENTIFY timeout (essai %d/%d)",
                          name, attempt + 1, IDENTIFY_RETRIES)
        _LOG.warning("[%s] IDENTIFY non supporté — découverte passive", name)
        bus.publish("arduino.identify_failed", {"name": name})

    def _identify_wait_response(self, name: str, ser: Any,
                                  dev: ArduinoDevice) -> bool:
        """Attend une ligne IDENTIFY. Retourne True si reçu."""
        deadline = time.time() + IDENTIFY_TIMEOUT_S
        while time.time() < deadline:
            if self._stop_flags.get(name, threading.Event()).is_set():
                return False
            try:
                if ser.in_waiting > 0:
                    raw = ser.readline().decode("utf-8", errors="replace").strip()
                    if raw and "IDENTIFY" in raw:
                        self._parse_identify(dev, raw)
                        return True
            except Exception as exc:
                _LOG.debug("[%s] Erreur IDENTIFY: %s", dev.name, exc)
            time.sleep(0.05)
        return False

    def _parse_identify(self, dev: ArduinoDevice, raw: str) -> None:
        """Parse le manifest IDENTIFY et crée les canaux/actions."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _LOG.error("[%s] IDENTIFY parse error : %s", dev.name, raw[:80])
            return
        manifest   = data.get("IDENTIFY", data)
        dev.firmware   = manifest.get("firmware", "")
        dev.identified = True

        for s in manifest.get("sensors", []):
            ch = s.get("name", "")
            if ch and ch not in dev.channels:
                dev.channels[ch] = SensorChannel(
                    name=ch, unit=s.get("unit", ""),
                    min_val=float(s.get("min", 0)),
                    max_val=float(s.get("max", 100)))

        for a in manifest.get("actuators", []):
            an = a.get("name", "")
            if an and an not in dev.actuators:
                dev.actuators[an] = ActuatorChannel(
                    name=an, kind=a.get("kind", "custom"),
                    label=a.get("label", an),
                    min_val=float(a.get("min", 0)),
                    max_val=float(a.get("max", 255)),
                    cmd_template=a.get("cmd_template", ""))

        for ac in manifest.get("actions", []):
            acn = ac.get("name", "")
            if acn:
                dev.actions[acn] = ArduinoAction(
                    name=acn, label=ac.get("label", acn),
                    description=ac.get("description", ""),
                    params=ac.get("params", []),
                    duration_ms=int(ac.get("duration_ms", 0)),
                    has_ack=bool(ac.get("has_ack", True)))

        ns = len(manifest.get("sensors", []))
        na = len(manifest.get("actuators", []))
        nac = len(manifest.get("actions", []))
        _LOG.info("[%s] Identifié : fw=%s  %d capteurs, %d act., %d actions",
                   dev.name, dev.firmware, ns, na, nac)
        bus.publish("arduino.identified", {
            "name": dev.name, "firmware": dev.firmware,
            "n_sensors": ns, "n_actuators": na, "n_actions": nac})

    # ── Reader thread ────────────────────────────────────────────

    def _reader_thread(self, name: str, ser: Any,
                        stop_evt: threading.Event) -> None:
        """Thread de lecture continue avec reconnexion auto."""
        dev = self.devices.get(name)
        if dev is None:
            return
        while not stop_evt.is_set():
            try:
                if ser.in_waiting > 0:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if line:
                        self._parse_line(dev, line)
                else:
                    time.sleep(0.01)
                timeout = (dev.last_rx > 0 and
                            (time.time() - dev.last_rx) > READ_TIMEOUT_S)
                if timeout and not stop_evt.is_set():
                    dev.error = "Timeout (pas de données)"
                    self._reconnect(name, ser, dev)
            except Exception as exc:
                if not stop_evt.is_set():
                    dev.error = str(exc)
                    _LOG.error("[%s] Reader : %s", name, exc)
                    time.sleep(1.0)

    def _reconnect(self, name: str, ser: Any, dev: ArduinoDevice) -> None:
        """Tentative de reconnexion série."""
        _LOG.warning("[%s] Timeout — tentative reconnexion", name)
        try:
            ser.close()
        except Exception as exc:
            _LOG.debug("[%s] Erreur fermeture port reconnexion: %s", name, exc)
        time.sleep(RECONNECT_DELAY_S)
        try:
            ser.open()
            ser.reset_input_buffer()
            dev.error   = ""
            dev.last_rx = 0.0
            _LOG.info("[%s] Reconnecté", name)
        except Exception as exc:
            dev.error = f"Reconnexion échouée : {exc}"
            _LOG.error("[%s] Reconnexion échouée : %s", name, exc)
            time.sleep(RECONNECT_DELAY_S)

    # ── Parsers ──────────────────────────────────────────────────

    def _parse_line(self, dev: ArduinoDevice, line: str) -> None:
        """Dispatch vers le bon parser selon le format."""
        if line.startswith("{"):
            self._parse_json(dev, line)
        elif self._parse_colon(dev, line):
            pass
        else:
            self._parse_kv(dev, line)

    def _parse_json(self, dev: ArduinoDevice, line: str) -> None:
        """Parse une ligne JSON."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return
        # Manifest IDENTIFY
        if "IDENTIFY" in data or data.get("CMD") == "IDENTIFY_RESP":
            self._parse_identify(dev, line)
            return
        # ACK action
        if "STATUS" in data and "action" in data:
            ok  = data.get("STATUS", "").upper() in ("OK", "DONE")
            key = f"{dev.name}.{data['action']}"
            with self._ack_lock:
                evt = self._ack_events.get(key)
            if evt:
                evt.set()
            bus.publish("arduino.action_ack", {
                "device": dev.name, "action": data["action"],
                "ok": ok, "data": data})
            return
        # Valeurs capteurs
        values = {}
        for k, v in data.items():
            try:
                values[str(k)] = float(v)
            except (ValueError, TypeError):
                pass
        if values:
            self._publish_sensor(dev, values)

    def _parse_colon(self, dev: ArduinoDevice, line: str) -> bool:
        """Parse KEY:val. Retourne True si géré."""
        if ":" not in line or "," in line:
            return False
        try:
            k, v = line.split(":", 1)
            self._publish_sensor(dev, {k.strip(): float(v.strip())})
        except ValueError:
            pass
        return True

    def _parse_kv(self, dev: ArduinoDevice, line: str) -> None:
        """Parse key=val,key2=val2."""
        if "=" not in line:
            return
        values = {}
        for pair in line.split(","):
            if "=" in pair:
                try:
                    k, v = pair.split("=", 1)
                    values[k.strip()] = float(v.strip())
                except ValueError:
                    pass
        if values:
            self._publish_sensor(dev, values)

    def _publish_sensor(self, dev: ArduinoDevice,
                         values: Dict[str, float]) -> None:
        """Met à jour les canaux et publie sur le bus."""
        dev.last_rx = time.time()
        for ch_name, ch_val in values.items():
            if ch_name not in dev.channels:
                dev.channels[ch_name] = SensorChannel(name=ch_name)
            dev.channels[ch_name].update(ch_val)
        bus.publish("sensor.reading", {
            "device":    dev.name,
            "values":    values,
            "timestamp": dev.last_rx,
        })


    # ── Persistance ─────────────────────────────────────────────

    def snapshot_devices(self) -> list:
        """Exporte les devices pour persistance (sans état runtime)."""
        result = []
        for dev in self.devices.values():
            result.append({
                "name": dev.name,
                "port": dev.port,
                "baud": dev.baud,
                "firmware": dev.firmware,
                "channels": [
                    {"name": ch.name, "unit": ch.unit,
                     "min_val": ch.min_val, "max_val": ch.max_val}
                    for ch in dev.channels.values()
                ],
                "actuators": [
                    {"name": a.name, "kind": a.kind, "label": a.label,
                     "min_val": a.min_val, "max_val": a.max_val,
                     "cmd_template": a.cmd_template}
                    for a in dev.actuators.values()
                ],
                "actions": [
                    {"name": a.name, "label": a.label,
                     "description": a.description, "params": a.params,
                     "duration_ms": a.duration_ms, "has_ack": a.has_ack}
                    for a in dev.actions.values()
                ],
            })
        return result

    def restore_devices(self, device_list: list) -> None:
        """Restaure les devices depuis la persistance (sans connecter)."""
        for d in device_list:
            name = d.get("name", "")
            port = d.get("port", "")
            baud = d.get("baud", BAUDRATE_ARDUINO_DEFAULT)
            if not name or not port:
                continue
            dev = ArduinoDevice(name=name, port=port, baud=baud,
                                firmware=d.get("firmware", ""))
            for ch in d.get("channels", []):
                cn = ch.get("name", "")
                if cn:
                    dev.channels[cn] = SensorChannel(
                        name=cn, unit=ch.get("unit", ""),
                        min_val=float(ch.get("min_val", 0)),
                        max_val=float(ch.get("max_val", 100)))
            for a in d.get("actuators", []):
                an = a.get("name", "")
                if an:
                    dev.actuators[an] = ActuatorChannel(
                        name=an, kind=a.get("kind", "custom"),
                        label=a.get("label", an),
                        min_val=float(a.get("min_val", 0)),
                        max_val=float(a.get("max_val", 255)),
                        cmd_template=a.get("cmd_template", ""))
            for ac in d.get("actions", []):
                acn = ac.get("name", "")
                if acn:
                    dev.actions[acn] = ArduinoAction(
                        name=acn, label=ac.get("label", acn),
                        description=ac.get("description", ""),
                        params=ac.get("params", []),
                        duration_ms=int(ac.get("duration_ms", 0)),
                        has_ack=bool(ac.get("has_ack", True)))
            with self._lock:
                self.devices[name] = dev
            _LOG.info("[%s] Restauré depuis library (port=%s, %d capteurs, %d act.)",
                       name, port, len(dev.channels), len(dev.actuators))
            bus.publish("arduino.device_added", {"name": name, "port": port})


# Singleton
arduino = ArduinoBridge()
