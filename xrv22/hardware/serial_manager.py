"""
xr200/hardware/serial_manager.py
──────────────────────────────────
Gestion de la communication Dynamixel par robot.

Utilise le SDK Dynamixel (Protocol 2.0) directement — identique à V17.
  - PortHandler   : gère le port série USB (U2D2)
  - PacketHandler : encode/décode les paquets Protocol 2.0
  - GroupSyncWrite : écriture synchrone multi-moteurs

Mode simulation :
  Quand dynamixel_sdk est absent ou simulation=True, toutes les
  opérations retournent des résultats simulés sans accès hardware.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

from xrv22.config import MOTOR_CENTER, MOTOR_RANGE_MIN, MOTOR_RANGE_MAX, BAUDRATE_DXL_DEFAULT, BAUDRATE_DXL_VALID
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL

_LOG = get_logger("SerialManager")

# ── Dynamixel Protocol 2.0 — registres X series ─────────────────
PROTOCOL_VERSION = 2.0
ADDR_DRIVE_MODE         = 10
ADDR_MAX_POSITION_LIMIT = 48
ADDR_MIN_POSITION_LIMIT = 52
ADDR_TORQUE_ENABLE      = 64
ADDR_VELOCITY_I_GAIN    = 76    # 2 bytes
ADDR_VELOCITY_P_GAIN    = 78    # 2 bytes
ADDR_POSITION_D_GAIN    = 80    # 2 bytes
ADDR_POSITION_I_GAIN    = 82    # 2 bytes
ADDR_POSITION_P_GAIN    = 84    # 2 bytes
ADDR_FEEDFORWARD_2_GAIN = 88    # 2 bytes
ADDR_FEEDFORWARD_1_GAIN = 90    # 2 bytes
ADDR_PROFILE_ACCEL      = 108
ADDR_PROFILE_VELOCITY   = 112
ADDR_GOAL_POSITION      = 116
ADDR_HARDWARE_ERROR     = 70    # 1 byte, read-only — bits d'erreur hardware
ADDR_PRESENT_POSITION   = 132
LEN_2                   = 2
LEN_4                   = 4
TORQUE_ON              = 1
TORQUE_OFF             = 0
DRIVE_MODE_TIME_PROFILE = 0x04   # bit 2 : Time-based Profile

# Gains PID Robotis par défaut pour X series (XM430, XL430, etc.)
# Position : P=800 I=0 D=0 — Velocity : P=100 I=1920 — FF1=FF2=0
DEFAULT_GAINS = {
    ADDR_POSITION_P_GAIN:    800,
    ADDR_POSITION_I_GAIN:    0,
    ADDR_POSITION_D_GAIN:    0,
    ADDR_VELOCITY_P_GAIN:    100,
    ADDR_VELOCITY_I_GAIN:    1920,
    ADDR_FEEDFORWARD_1_GAIN: 0,
    ADDR_FEEDFORWARD_2_GAIN: 0,
}
GAIN_NAMES = {
    ADDR_POSITION_P_GAIN:    "PosP",
    ADDR_POSITION_I_GAIN:    "PosI",
    ADDR_POSITION_D_GAIN:    "PosD",
    ADDR_VELOCITY_P_GAIN:    "VelP",
    ADDR_VELOCITY_I_GAIN:    "VelI",
    ADDR_FEEDFORWARD_1_GAIN: "FF1",
    ADDR_FEEDFORWARD_2_GAIN: "FF2",
}

# Décodage bits du registre Hardware Error Status (adresse 70)
HW_ERROR_BITS = {
    0: "Input Voltage",
    2: "Overheating",
    3: "Motor Encoder",
    4: "Electrical Shock",
    5: "Overload",
}

# Import optionnel du SDK
try:
    from dynamixel_sdk import PortHandler, PacketHandler, GroupSyncWrite, GroupSyncRead  # type: ignore
    DXL_OK = True
except ImportError:
    DXL_OK = False
    PortHandler = PacketHandler = GroupSyncWrite = GroupSyncRead = None  # type: ignore


def _u32_to_bytes(v: int) -> list:
    """Convertit un uint32 en 4 bytes little-endian (format Dynamixel)."""
    v = int(v) & 0xFFFFFFFF
    return [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF]


# ── SerialManager ────────────────────────────────────────────────

class SerialManager:
    """
    Communication Dynamixel Protocol 2.0 via SDK.
    Thread-safe.
    """

    def __init__(self, robot_id: str, motor_ids: List[int],
                 simulation: bool = False) -> None:
        self.robot_id = robot_id
        self.motor_ids = motor_ids
        self.simulation = simulation or not DXL_OK

        self._port_handler = None       # PortHandler
        self._packet_handler = None     # PacketHandler
        self._port_name: str = ""
        self._connected = False
        self._lock = threading.Lock()

        # Positions simulées
        self._sim_positions: Dict[int, int] = {m: MOTOR_CENTER for m in motor_ids}
        self._torque_enabled = False

    # ── Connexion ────────────────────────────────────────────────

    _VALID_BAUDS = BAUDRATE_DXL_VALID

    def connect(self, port: str, baud: int = BAUDRATE_DXL_DEFAULT) -> bool:
        """Ouvre le port Dynamixel et teste la communication."""
        if baud not in self._VALID_BAUDS:
            _LOG.error("[%s] Baudrate invalide : %d (valides : %s)",
                       self.robot_id, baud, self._VALID_BAUDS)
            return False
        # Déconnexion propre si déjà connecté (évite "Port is in use")
        if self._connected:
            _LOG.info("[%s] Déconnexion préalable avant reconnexion", self.robot_id)
            self._connected = False
            self._cleanup()
        self._port_name = port
        if self.simulation:
            return self._connect_sim(port)
        try:
            self._port_handler = PortHandler(port)
            self._packet_handler = PacketHandler(PROTOCOL_VERSION)

            if not self._port_handler.openPort():
                raise RuntimeError(f"Impossible d'ouvrir le port : {port}")
            if not self._port_handler.setBaudRate(baud):
                raise RuntimeError(f"Impossible de configurer le baudrate : {baud}")

            self._connected = True

            # Test communication — lecture position du premier moteur
            if not self.motor_ids:
                _LOG.error("[%s] Aucun motor_id configuré", self.robot_id)
                self._connected = False
                return False
            mid = self.motor_ids[0]
            try:
                pos, result, error = self._packet_handler.read4ByteTxRx(
                    self._port_handler, mid, ADDR_PRESENT_POSITION)
                if result != 0:
                    msg = self._packet_handler.getTxRxResult(result)
                    _LOG.warning("[%s] Test moteur %d échoué : %s (le port est ouvert)",
                                 self.robot_id, mid, msg)
                else:
                    _LOG.info("[%s] Test moteur %d OK — position=%d",
                              self.robot_id, mid, pos)
            except Exception as exc:
                _LOG.warning("[%s] Test communication échoué : %s", self.robot_id, exc)

            # Diagnostic : lire les limites hardware de chaque moteur
            self._log_hardware_limits()

            # Activer le Time-based Profile sur tous les moteurs
            self._enable_time_based_profile()

            # Diagnostic gains PID + unification (silencieux si déjà conformes)
            self._diagnose_and_unify_gains()

            bus.publish("robot.connected", {"robot_id": self.robot_id, "port": port})
            _LOG.info("[%s] Connecté sur %s @ %d", self.robot_id, port, baud)
            return True

        except Exception as exc:
            _LOG.error("[%s] Connexion échouée sur %s : %s", self.robot_id, port, exc)
            self._connected = False
            self._cleanup()
            return False

    def _connect_sim(self, port: str) -> bool:
        """Connexion en mode simulation."""
        self._connected = True
        bus.publish("robot.connected", {"robot_id": self.robot_id, "port": f"SIM:{port}"})
        _LOG.info("[%s] Mode simulation activé", self.robot_id)
        return True

    def disconnect(self) -> None:
        """Ferme le port proprement."""
        self._connected = False
        self._cleanup()
        bus.publish("robot.disconnected", {"robot_id": self.robot_id})
        _LOG.info("[%s] Déconnecté", self.robot_id)

    def _enable_time_based_profile(self) -> int:
        """Active le Time-based Profile (bit 2 Drive Mode) sur tous les moteurs.
        Torque doit être OFF. Retourne le nombre de moteurs en échec.
        En cas d'échec sur un moteur, fait un reboot HW + retry une fois
        (corrige les erreurs Dynamixel transitoires au cold boot)."""
        if self.simulation:
            return 0
        failed_ids: List[int] = []
        for mid in self.motor_ids:
            ok = self._try_enable_time_based_for(mid)
            if not ok:
                failed_ids.append(mid)
        # Retry avec reboot pour les moteurs en échec
        if failed_ids:
            _LOG.warning("[%s] Time-based Profile : %d/%d moteurs en échec — "
                         "tentative reboot+retry sur %s",
                         self.robot_id, len(failed_ids),
                         len(self.motor_ids), failed_ids)
            import time as _time
            with self._lock:
                for mid in list(failed_ids):
                    try:
                        self._packet_handler.reboot(self._port_handler, mid)
                    except Exception:
                        pass
            _time.sleep(0.5)  # laisser les moteurs redemarrer
            still_failed: List[int] = []
            for mid in failed_ids:
                ok = self._try_enable_time_based_for(mid)
                if not ok:
                    still_failed.append(mid)
                else:
                    _LOG.info("[%s] Moteur %d — recupere apres reboot",
                              self.robot_id, mid)
            if still_failed:
                _LOG.warning("[%s] Time-based Profile : %d/%d moteurs encore "
                             "en échec après reboot : %s",
                             self.robot_id, len(still_failed),
                             len(self.motor_ids), still_failed)
            return len(still_failed)
        return 0

    def _try_enable_time_based_for(self, mid: int) -> bool:
        """Tentative d'activation Time-based Profile pour un moteur.
        Retourne True si OK (ou deja active), False si echec."""
        with self._lock:
            try:
                drive_mode, result, _ = self._packet_handler.read1ByteTxRx(
                    self._port_handler, mid, ADDR_DRIVE_MODE)
                if result != 0:
                    _LOG.error("[%s] Moteur %d — lecture Drive Mode échouée",
                               self.robot_id, mid)
                    return False
                if drive_mode & DRIVE_MODE_TIME_PROFILE:
                    return True  # déjà OK
                self._packet_handler.write1ByteTxRx(
                    self._port_handler, mid, ADDR_TORQUE_ENABLE, TORQUE_OFF)
                new_mode = drive_mode | DRIVE_MODE_TIME_PROFILE
                result, _err = self._packet_handler.write1ByteTxRx(
                    self._port_handler, mid, ADDR_DRIVE_MODE, new_mode)
                if result == 0:
                    _LOG.info("[%s] Moteur %d — Time-based Profile activé "
                              "(mode 0x%02X → 0x%02X)",
                              self.robot_id, mid, drive_mode, new_mode)
                    return True
                _LOG.error("[%s] Moteur %d — Échec activation Time-based",
                           self.robot_id, mid)
                return False
            except Exception as exc:
                _LOG.error("[%s] Moteur %d — Drive Mode échoué : %s",
                           self.robot_id, mid, exc)
                return False

    def _log_hardware_limits(self) -> None:
        """Diagnostic : lit et log les limites Min/Max Position de chaque moteur."""
        if self.simulation:
            return
        with self._lock:
            for mid in self.motor_ids:
                try:
                    min_pos, r1, _ = self._packet_handler.read4ByteTxRx(
                        self._port_handler, mid, ADDR_MIN_POSITION_LIMIT)
                    max_pos, r2, _ = self._packet_handler.read4ByteTxRx(
                        self._port_handler, mid, ADDR_MAX_POSITION_LIMIT)
                    if r1 == 0 and r2 == 0:
                        _LOG.info("[%s] Moteur %d — limites HW : min=%d  max=%d",
                                  self.robot_id, mid, min_pos, max_pos)
                        if min_pos != MOTOR_RANGE_MIN or max_pos != MOTOR_RANGE_MAX:
                            _LOG.warning(
                                "[%s] ⚠️ Moteur %d : limites HW non standard ! "
                                "min=%d max=%d (attendu 0–4095)",
                                self.robot_id, mid, min_pos, max_pos)
                except Exception as exc:
                    _LOG.debug("[%s] Lecture limites HW moteur %d échouée : %s",
                               self.robot_id, mid, exc)

    def _read_motor_gains(self, mid: int) -> Dict[int, int]:
        """Lit Drive Mode + gains d'un moteur, logge le tout, retourne {addr: gain}."""
        dm, r_dm, _ = self._packet_handler.read1ByteTxRx(
            self._port_handler, mid, ADDR_DRIVE_MODE)
        if r_dm == 0:
            _LOG.info("[%s] Moteur %d — Drive Mode = 0x%02X",
                      self.robot_id, mid, dm)

        current: Dict[int, int] = {}
        for addr in DEFAULT_GAINS:
            val, r, _ = self._packet_handler.read2ByteTxRx(
                self._port_handler, mid, addr)
            if r == 0:
                current[addr] = int(val)

        gains_str = "  ".join(
            f"{GAIN_NAMES[a]}={current.get(a, '?')}" for a in DEFAULT_GAINS)
        _LOG.info("[%s] Moteur %d — gains : %s", self.robot_id, mid, gains_str)
        return current

    def _write_gain_overrides(self, mid: int, diverging: Dict[int, int]) -> None:
        """Réécrit les gains divergents d'un moteur (Torque OFF préalable, lock détenu)."""
        if not diverging:
            return
        div_str = ", ".join(
            f"{GAIN_NAMES[a]} {v}→{DEFAULT_GAINS[a]}"
            for a, v in diverging.items())
        _LOG.warning("[%s] ⚠️ Moteur %d gains divergents : %s — réécriture",
                     self.robot_id, mid, div_str)
        # Torque OFF avant écriture (cohérent avec les autres écritures)
        self._packet_handler.write1ByteTxRx(
            self._port_handler, mid, ADDR_TORQUE_ENABLE, TORQUE_OFF)
        for addr, target in diverging.items():
            result, _ = self._packet_handler.write2ByteTxRx(
                self._port_handler, mid, addr, target)
            if result != 0:
                _LOG.error("[%s] Moteur %d — écriture %s échouée",
                           self.robot_id, mid, GAIN_NAMES[addr])

    def _diagnose_motor_gains(self, mid: int) -> None:
        """Lit et unifie les gains PID/Drive Mode d'un moteur (lock détenu)."""
        current = self._read_motor_gains(mid)
        diverging = {a: v for a, v in current.items()
                     if v != DEFAULT_GAINS[a]}
        self._write_gain_overrides(mid, diverging)

    def _diagnose_and_unify_gains(self) -> None:
        """Lit les gains PID et Drive Mode de chaque moteur, log les
        divergences vs DEFAULT_GAINS, puis réécrit les gains incorrects.
        Permet d'unifier le comportement de plusieurs robots qui auraient
        des gains divergents (causant un bruit moteur différent)."""
        if self.simulation:
            return
        with self._lock:
            for mid in self.motor_ids:
                try:
                    self._diagnose_motor_gains(mid)
                except Exception as exc:
                    _LOG.debug("[%s] Diagnostic gains moteur %d échoué : %s",
                               self.robot_id, mid, exc)

    def _sync_motor_limits(self, mid: int, lo: int, hi: int) -> bool:
        """Aligne les limites HW d'un moteur sur (lo, hi).
        Retourne True si une limite a été réécrite (lock détenu)."""
        hw_min, r1, _ = self._packet_handler.read4ByteTxRx(
            self._port_handler, mid, ADDR_MIN_POSITION_LIMIT)
        hw_max, r2, _ = self._packet_handler.read4ByteTxRx(
            self._port_handler, mid, ADDR_MAX_POSITION_LIMIT)
        if r1 != 0 or r2 != 0:
            return False
        need_min = hw_min > lo
        need_max = hw_max < hi
        if not need_min and not need_max:
            return False
        # Torque OFF obligatoire pour écrire EEPROM
        self._packet_handler.write1ByteTxRx(
            self._port_handler, mid, ADDR_TORQUE_ENABLE, TORQUE_OFF)
        if need_min:
            result, error = self._packet_handler.write4ByteTxRx(
                self._port_handler, mid, ADDR_MIN_POSITION_LIMIT, lo)
            if result != 0:
                _LOG.error("[%s] Moteur %d : écriture Min Position échouée",
                           self.robot_id, mid)
                return False
            _LOG.info("[%s] Moteur %d — Min Position : %d → %d",
                      self.robot_id, mid, hw_min, lo)
        if need_max:
            result, error = self._packet_handler.write4ByteTxRx(
                self._port_handler, mid, ADDR_MAX_POSITION_LIMIT, hi)
            if result != 0:
                _LOG.error("[%s] Moteur %d : écriture Max Position échouée",
                           self.robot_id, mid)
                return False
            _LOG.info("[%s] Moteur %d — Max Position : %d → %d",
                      self.robot_id, mid, hw_max, hi)
        return True

    def sync_hardware_limits(self, soft_limits: Dict[int, tuple]) -> bool:
        """Synchronise les limites HW des moteurs avec les soft_limits.
        Si une limite HW est plus restrictive que la soft_limit, on la réécrit.
        Torque doit être OFF pour écrire dans l'EEPROM Dynamixel."""
        if not self._connected or self.simulation:
            return True
        updated = False
        with self._lock:
            for mid in self.motor_ids:
                lo, hi = soft_limits.get(mid, (MOTOR_RANGE_MIN, MOTOR_RANGE_MAX))
                try:
                    if self._sync_motor_limits(mid, lo, hi):
                        updated = True
                except Exception as exc:
                    _LOG.error("[%s] Moteur %d : sync limites HW échouée : %s",
                               self.robot_id, mid, exc)
        if updated:
            _LOG.info("[%s] Limites HW synchronisées avec soft_limits", self.robot_id)
            self._log_hardware_limits()
        return True

    def _cleanup(self) -> None:
        """Ferme le port hardware."""
        if self._port_handler:
            try:
                self._port_handler.closePort()
            except Exception as exc:
                _LOG.debug("Erreur fermeture port: %s", exc)
            self._port_handler = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def torque_enabled(self) -> bool:
        return self._torque_enabled

    @property
    def port_name(self) -> str:
        return self._port_name

    # ── Torque ON/OFF (V17 compatible) ───────────────────────────

    def _write_motor_torque(self, mid: int, value: int) -> bool:
        """Écrit Torque Enable sur un moteur. Retourne True si OK (lock détenu)."""
        try:
            result, error = self._packet_handler.write1ByteTxRx(
                self._port_handler, mid, ADDR_TORQUE_ENABLE, value)
            if result != 0:
                _LOG.error("[%s] Torque moteur %d : %s", self.robot_id, mid,
                           self._packet_handler.getTxRxResult(result))
                return False
            if error != 0:
                _LOG.error("[%s] Torque moteur %d : %s", self.robot_id, mid,
                           self._packet_handler.getRxPacketError(error))
                return False
        except Exception as exc:
            _LOG.error("[%s] Torque moteur %d exception : %s",
                       self.robot_id, mid, exc)
            return False
        return True

    def set_torque(self, enable: bool) -> bool:
        """Active/désactive le couple sur tous les moteurs."""
        if not self._connected:
            return False
        if self.simulation:
            self._torque_enabled = enable
            _LOG.info("[%s] SIM: Torque %s", self.robot_id, "ON" if enable else "OFF")
            return True

        value = TORQUE_ON if enable else TORQUE_OFF
        failed = []
        with self._lock:
            for mid in self.motor_ids:
                if not self._write_motor_torque(mid, value):
                    failed.append(mid)

        if failed:
            _LOG.error("[%s] set_torque(%s) : %d/%d moteurs en échec %s",
                       self.robot_id, enable, len(failed),
                       len(self.motor_ids), failed)
            return False
        self._torque_enabled = enable
        _LOG.info("[%s] Torque %s", self.robot_id, "ON" if enable else "OFF")
        return True

    # ── Diagnostic erreurs hardware moteur ─────────────────────────

    def _read_motor_errors(self, mid: int):
        """Lit le Hardware Error Status d'un moteur. Retourne la liste d'erreurs,
        ou None si pas d'erreur / lecture échouée (lock détenu)."""
        try:
            status, result, _ = self._packet_handler.read1ByteTxRx(
                self._port_handler, mid, ADDR_HARDWARE_ERROR)
        except OSError:
            return None
        except Exception as exc:
            _LOG.debug("[%s] Lecture HW error moteur %d : %s",
                       self.robot_id, mid, exc)
            return None
        if result != 0 or status == 0:
            return None
        names = [name for bit, name in HW_ERROR_BITS.items()
                 if status & (1 << bit)]
        names = names or [f"Unknown (0x{status:02X})"]
        _LOG.error("[%s] Moteur %d HARDWARE ERROR : %s (reg=0x%02X)",
                   self.robot_id, mid, ", ".join(names), status)
        return names

    def read_hardware_errors(self) -> Dict[int, List[str]]:
        """Lit le registre Hardware Error Status (addr 70) de chaque moteur.
        Retourne {motor_id: [liste erreurs]} pour les moteurs en erreur uniquement."""
        if not self._connected or self.simulation:
            return {}
        errors: Dict[int, List[str]] = {}
        with self._lock:
            for mid in self.motor_ids:
                names = self._read_motor_errors(mid)
                if names:
                    errors[mid] = names
        return errors

    def reboot_motor(self, motor_id: int) -> bool:
        """Reboot un moteur Dynamixel via instruction Protocol 2.0.
        Apres reboot, le moteur perd torque et profil — il faut les reconfigurer."""
        if not self._connected or self.simulation:
            return False
        with self._lock:
            try:
                result, error = self._packet_handler.reboot(
                    self._port_handler, motor_id)
                if result != 0:
                    _LOG.error("[%s] Reboot moteur %d echoue : %s",
                               self.robot_id, motor_id,
                               self._packet_handler.getTxRxResult(result))
                    return False
                _LOG.info("[%s] Moteur %d reboot OK", self.robot_id, motor_id)
            except Exception as exc:
                _LOG.error("[%s] Reboot moteur %d exception : %s",
                           self.robot_id, motor_id, exc)
                return False
        # Attendre que le moteur redémarre (~500ms typique Dynamixel)
        time.sleep(0.6)
        # Reconfigurer Time-based Profile sur ce moteur
        self._reconfigure_motor(motor_id)
        bus.publish("motor.rebooted", {
            "robot_id": self.robot_id, "motor_id": motor_id})
        return True

    def _reconfigure_motor(self, motor_id: int) -> None:
        """Reconfigure un moteur apres reboot (Drive Mode Time-based)."""
        with self._lock:
            try:
                drive_mode, result, _ = self._packet_handler.read1ByteTxRx(
                    self._port_handler, motor_id, ADDR_DRIVE_MODE)
                if result != 0:
                    return
                if not (drive_mode & DRIVE_MODE_TIME_PROFILE):
                    new_mode = drive_mode | DRIVE_MODE_TIME_PROFILE
                    self._packet_handler.write1ByteTxRx(
                        self._port_handler, motor_id, ADDR_DRIVE_MODE, new_mode)
                    _LOG.info("[%s] Moteur %d reconfigure en Time-based Profile",
                              self.robot_id, motor_id)
            except Exception as exc:
                _LOG.error("[%s] Reconfiguration moteur %d echouee : %s",
                           self.robot_id, motor_id, exc)

    # ── Lecture positions ─────────────────────────────────────────

    def read_positions(self) -> Dict[int, int]:
        """Lit les positions courantes de tous les moteurs.

        Voie rapide : GroupSyncRead (1 transaction série pour tous les moteurs,
        ~5× plus rapide que la lecture moteur par moteur). En cas d'échec ou de
        lecture incomplète, repli sur la lecture séquentielle (qui porte la
        logique de tolérance d'erreurs + déconnexion sur port instable)."""
        if not self._connected:
            return {}
        if self.simulation:
            with self._lock:
                return dict(self._sim_positions)
        grouped = self._read_positions_group()
        if grouped is not None:
            return grouped
        return self._read_positions_sequential()

    def _read_positions_group(self) -> Optional[Dict[int, int]]:
        """Lecture groupée (GroupSyncRead) des positions. Retourne le dict
        complet, ou None si indisponible/échec/incomplet → fallback séquentiel."""
        if GroupSyncRead is None:
            return None
        try:
            with self._lock:
                gsr = GroupSyncRead(self._port_handler, self._packet_handler,
                                    ADDR_PRESENT_POSITION, 4)
                try:
                    for mid in self.motor_ids:
                        gsr.addParam(mid)
                    if gsr.txRxPacket() != 0:
                        return None
                    positions: Dict[int, int] = {}
                    for mid in self.motor_ids:
                        if not gsr.isAvailable(mid, ADDR_PRESENT_POSITION, 4):
                            return None      # un moteur n'a pas répondu → fallback
                        positions[mid] = int(gsr.getData(mid, ADDR_PRESENT_POSITION, 4))
                    return positions
                finally:
                    gsr.clearParam()
        except Exception as exc:
            _LOG.debug("[%s] GroupSyncRead échec, fallback séquentiel : %s",
                       self.robot_id, exc)
            return None

    def read_goal_positions(self) -> Dict[int, int]:
        """Lit le registre Goal Position (consigne courante) de tous les moteurs.
        Sert au maintien teach-pendant à la prise de main : on ancre le maintien
        sur le Goal commandé (pas le present affaissé) pour ne pas re-droober."""
        if not self._connected or self.simulation or GroupSyncRead is None:
            return {}
        try:
            with self._lock:
                gsr = GroupSyncRead(self._port_handler, self._packet_handler,
                                    ADDR_GOAL_POSITION, 4)
                try:
                    for mid in self.motor_ids:
                        gsr.addParam(mid)
                    if gsr.txRxPacket() != 0:
                        return {}
                    goals: Dict[int, int] = {}
                    for mid in self.motor_ids:
                        if gsr.isAvailable(mid, ADDR_GOAL_POSITION, 4):
                            goals[mid] = int(gsr.getData(mid, ADDR_GOAL_POSITION, 4))
                    return goals
                finally:
                    gsr.clearParam()
        except Exception:
            return {}

    def _read_positions_sequential(self) -> Dict[int, int]:
        """Lecture moteur par moteur (read4ByteTxRx). Tolère les erreurs par
        moteur ; déconnecte si le port est trop instable."""
        positions: Dict[int, int] = {}
        errors = 0
        with self._lock:
            for mid in self.motor_ids:
                try:
                    pos, result, error = self._packet_handler.read4ByteTxRx(
                        self._port_handler, mid, ADDR_PRESENT_POSITION)
                    if result == 0 and error == 0:
                        positions[mid] = int(pos)
                    else:
                        errors += 1
                except OSError:
                    # USB déconnecté (Errno 6 / Device not configured)
                    errors += 1
                except Exception as exc:
                    _LOG.error("[%s] Lecture position moteur %d : %s",
                               self.robot_id, mid, exc)
                    errors += 1
            # Si trop d'erreurs, le port USB est instable → marquer déconnecté.
            # max(1, ...) : pour un robot mono-moteur, len//2 == 0 ferait
            # `errors >= 0` (toujours vrai) → fausse déconnexion à chaque lecture.
            if errors >= max(1, len(self.motor_ids) // 2):
                _LOG.error("[%s] Port USB instable (%d erreurs) — déconnexion",
                           self.robot_id, errors)
                self._connected = False
                bus.publish("robot.disconnected", {"robot_id": self.robot_id})
        return positions

    # ── Écriture positions (GroupSyncWrite) ───────────────────────

    def write_positions(self, targets: Dict[int, int]) -> bool:
        """Écrit les positions cibles via GroupSyncWrite."""
        if not self._connected:
            return False
        if self.simulation:
            with self._lock:
                self._sim_positions.update(targets)
            bus.publish("serial.move_sent", {
                "robot_id": self.robot_id, "positions": targets,
                "duration_ms": 0, "cmd_id": "sim"})
            return True

        with self._lock:
            try:
                group = GroupSyncWrite(
                    self._port_handler, self._packet_handler,
                    ADDR_GOAL_POSITION, LEN_4)
                for mid, pos in targets.items():
                    if not group.addParam(mid, _u32_to_bytes(pos)):
                        raise RuntimeError(f"addParam échoué moteur {mid}")
                result = group.txPacket()
                group.clearParam()
                if result != 0:
                    raise RuntimeError(self._packet_handler.getTxRxResult(result))
            except OSError as exc:
                _LOG.error("[%s] USB déconnecté pendant écriture : %s",
                           self.robot_id, exc)
                self._connected = False
                bus.publish("robot.disconnected", {"robot_id": self.robot_id})
                return False
            except Exception as exc:
                _LOG.error("[%s] write_positions échoué : %s", self.robot_id, exc)
                return False

        bus.publish("serial.move_sent", {
            "robot_id": self.robot_id, "positions": targets,
            "duration_ms": 0, "cmd_id": ""})
        return True

    # ── Profils vitesse/accélération ─────────────────────────────

    def set_profile(self, velocity: int, acceleration: int) -> bool:
        """Configure les profils de mouvement pour tous les moteurs."""
        if not self._connected or self.simulation:
            return True
        with self._lock:
            try:
                self._sync_write_u32(ADDR_PROFILE_VELOCITY,
                                     {m: velocity for m in self.motor_ids})
                self._sync_write_u32(ADDR_PROFILE_ACCEL,
                                     {m: acceleration for m in self.motor_ids})
            except Exception as exc:
                _LOG.error("[%s] set_profile échoué : %s", self.robot_id, exc)
                return False
        return True

    def _sync_write_u32(self, addr: int, values: Dict[int, int]) -> None:
        """GroupSyncWrite générique 4 bytes."""
        group = GroupSyncWrite(
            self._port_handler, self._packet_handler, addr, LEN_4)
        for mid, val in values.items():
            if not group.addParam(mid, _u32_to_bytes(val)):
                raise RuntimeError(f"addParam échoué moteur {mid}")
        result = group.txPacket()
        group.clearParam()
        if result != 0:
            raise RuntimeError(self._packet_handler.getTxRxResult(result))

    # ── Commandes de stop ────────────────────────────────────────

    def send_estop(self) -> None:
        """Arrêt d'urgence : torque off immédiat."""
        self.set_torque(False)
        bus.publish("serial.stop_sent", {"robot_id": self.robot_id, "estop": True})
        _LOG.log(SAFETY_LEVEL, "[%s] ESTOP — torque OFF", self.robot_id)

    def send_stop(self) -> None:
        """Arrêt propre : torque off."""
        self.set_torque(False)
        bus.publish("serial.stop_sent", {"robot_id": self.robot_id, "estop": False})

    # ── Mouvement haut niveau ────────────────────────────────────

    def send_move(self, positions: Dict[int, int], duration_ms: int) -> str:
        """Configure la durée (Time-based Profile) puis écrit les positions.
        En Time-based Profile, Profile Velocity = durée totale en ms,
        Profile Acceleration = temps de rampe (10% de la durée, min 100ms).
        Tout se fait dans un seul verrou pour éviter 'Port is in use'."""
        ramp_ms = max(100, duration_ms // 10)
        if not self.simulation and self._connected:
            with self._lock:
                try:
                    self._sync_write_u32(ADDR_PROFILE_VELOCITY,
                                         {m: duration_ms for m in self.motor_ids})
                    self._sync_write_u32(ADDR_PROFILE_ACCEL,
                                         {m: ramp_ms for m in self.motor_ids})
                    # Écriture positions dans le même verrou
                    self._write_positions_unlocked(positions)
                except Exception as exc:
                    _LOG.error("[%s] send_move échoué : %s", self.robot_id, exc)
        elif self.simulation and self._connected:
            with self._lock:
                self._sim_positions.update(positions)
            bus.publish("serial.move_sent", {
                "robot_id": self.robot_id, "positions": positions,
                "duration_ms": duration_ms, "cmd_id": "sim"})
        _LOG.info("[%s] send_move : %s (durée=%dms, rampe=%dms)",
                  self.robot_id, positions, duration_ms, ramp_ms)
        return ""

    def _write_positions_unlocked(self, targets: Dict[int, int]) -> None:
        """Écriture positions sans verrou (appelé depuis send_move qui tient déjà le lock)."""
        group = GroupSyncWrite(
            self._port_handler, self._packet_handler,
            ADDR_GOAL_POSITION, LEN_4)
        for mid, pos in targets.items():
            if not group.addParam(mid, _u32_to_bytes(pos)):
                raise RuntimeError(f"addParam échoué moteur {mid}")
        result = group.txPacket()
        group.clearParam()
        if result != 0:
            raise RuntimeError(self._packet_handler.getTxRxResult(result))
        bus.publish("serial.move_sent", {
            "robot_id": self.robot_id, "positions": targets,
            "duration_ms": 0, "cmd_id": ""})
