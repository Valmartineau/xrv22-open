"""
xrv22/library/models.py
────────────────────────
Modèles de données pour la librairie XRV22.
Un fichier = un objet. Chaque modèle correspond à un fichier JSON.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from xrv22.config import (
    MOTOR_IDS_DEFAULT, BAUDRATE_DXL_DEFAULT, BAUDRATE_ARDUINO_DEFAULT,
    SMOOTH_HZ_DEFAULT, COMFORT_VEL_DEFAULT, COMFORT_ACC_DEFAULT,
    HOME_DURATION_DEFAULT_S,
)


def _uuid() -> str:
    """Génère un identifiant court unique."""
    return str(uuid.uuid4())[:8]


def _now() -> str:
    """Horodatage courant ISO."""
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ══════════════════════════════════════════════════════════════════
#  Position
# ══════════════════════════════════════════════════════════════════

@dataclass
class PositionModel:
    """Une position robot (7 valeurs moteur)."""
    id: str = field(default_factory=_uuid)
    name: str = ""
    category: str = "sauvegardees"  # "machine_initiales", "travail", "sauvegardees"
    positions: Dict[int, int] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["positions"] = {str(k): v for k, v in self.positions.items()}
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "PositionModel":
        data = dict(data)
        if "positions" in data:
            try:
                data["positions"] = {int(k): int(v) for k, v in data["positions"].items()}
            except (ValueError, TypeError):
                data["positions"] = {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Suite
# ══════════════════════════════════════════════════════════════════

@dataclass
class SuiteModel:
    """Une suite = liste ordonnée de références de positions + durées."""
    id: str = field(default_factory=_uuid)
    name: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    # Chaque step : {"position_id": "xxx", "position_name": "...", "duration_s": 2.0, "pause_s": 0.0}
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SuiteModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Scénario
# ══════════════════════════════════════════════════════════════════

@dataclass
class ScenarioModel:
    """Un scénario = enchaînement de suites avec logique conditionnelle + snapshot timeline."""
    id: str = field(default_factory=_uuid)
    name: str = ""
    suite_ids: List[str] = field(default_factory=list)
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    timeline_data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScenarioModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Robot
# ══════════════════════════════════════════════════════════════════

@dataclass
class RobotConfigModel:
    """Configuration persistante d'un robot."""
    robot_id: str = ""
    name: str = ""
    port: str = ""
    baud: int = BAUDRATE_DXL_DEFAULT
    motor_ids: List[int] = field(default_factory=lambda: list(MOTOR_IDS_DEFAULT))
    home_machine: Dict[int, int] = field(default_factory=dict)
    home_work: Dict[int, int] = field(default_factory=dict)
    soft_limits: Dict[int, List[int]] = field(default_factory=dict)
    motion_params: Dict[str, Any] = field(default_factory=lambda: {
        "smooth_hz": SMOOTH_HZ_DEFAULT, "comfort_vel": COMFORT_VEL_DEFAULT,
        "comfort_acc": COMFORT_ACC_DEFAULT, "home_duration": HOME_DURATION_DEFAULT_S,
    })

    def to_dict(self) -> dict:
        d = asdict(self)
        d["home_machine"] = {str(k): v for k, v in self.home_machine.items()}
        d["home_work"] = {str(k): v for k, v in self.home_work.items()}
        d["soft_limits"] = {str(k): list(v) for k, v in self.soft_limits.items()}
        return d

    @staticmethod
    def _int_keyed(raw, value_fn=int) -> dict:
        """Convertit raw en {int(k): value_fn(v)}, ou {} si vide/invalide."""
        if not raw:
            return {}
        try:
            return {int(k): value_fn(v) for k, v in raw.items()}
        except (ValueError, TypeError):
            return {}

    @classmethod
    def from_dict(cls, data: dict) -> "RobotConfigModel":
        data = dict(data)
        data["home_machine"] = cls._int_keyed(data.get("home_machine"))
        data["home_work"] = cls._int_keyed(data.get("home_work"))
        data["soft_limits"] = cls._int_keyed(data.get("soft_limits"), value_fn=list)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Profil de mouvement
# ══════════════════════════════════════════════════════════════════

@dataclass
class MotionProfileModel:
    """Profil de mouvement réutilisable."""
    id: str = field(default_factory=_uuid)
    name: str = "standard"
    smooth_hz: int = SMOOTH_HZ_DEFAULT
    comfort_vel: int = COMFORT_VEL_DEFAULT
    comfort_acc: int = COMFORT_ACC_DEFAULT
    home_duration: float = HOME_DURATION_DEFAULT_S
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MotionProfileModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Zone de sécurité (surface 3D)
# ══════════════════════════════════════════════════════════════════

@dataclass
class ZoneModel:
    """Zone de sécurité définie par 3 ou 4 points TCP (mm)."""
    id: str = field(default_factory=_uuid)
    name: str = ""
    zone_type: str = "warning"        # "warning" | "exclusion" | "plane"
    points: List[List[float]] = field(default_factory=list)  # [[x,y,z], ...]
    color: str = "#f6a117"
    visible: bool = True
    plane_label: str = ""             # "plan bas", "plan côté", etc.
    plane_axis: str = ""              # "XY", "XZ", "YZ" ou "oblique"
    source_robot_id: str = ""         # robot ayant capturé les points
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ZoneModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Presets d'assiette (orientation outil)
# ══════════════════════════════════════════════════════════════════

@dataclass
class AssettePreset:
    """Preset d'assiette : orientation outil verrouillée.

    locked_axes : liste d'axes verrouillés (ex: [5], [4], [4,5])
      - Axe 5 (tangage) : compense a2+a3 → angle_deg = a2+a3+a5
      - Axe 4 (roulis) : figé à roll_deg
    angle_deg : angle cible tangage (a2+a3+a5) en degrés (180°=vers le bas)
    roll_deg  : angle cible roulis (axe 4) en degrés (0°=neutre)
    """
    id: str = field(default_factory=_uuid)
    name: str = ""
    angle_deg: float = 180.0   # tangage : a2+a3+a5
    roll_deg: float = 0.0      # roulis : a4
    locked_axes: List[int] = field(default_factory=lambda: [5])
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AssettePreset":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════════════
#  Infos projet
# ══════════════════════════════════════════════════════════════════

@dataclass
class ProjectInfo:
    """Métadonnées d'un projet."""
    name: str = ""
    path: str = ""
    version: int = 22
    created_at: str = field(default_factory=_now)
    modified_at: str = field(default_factory=_now)
    position_count: int = 0
    suite_count: int = 0


# ══════════════════════════════════════════════════════════════════
#  Hardware / Arduino / Capteurs
# ══════════════════════════════════════════════════════════════════

@dataclass
class SensorChannelModel:
    """Configuration persistante d'un capteur Arduino."""
    name: str = ""
    unit: str = ""
    min_val: float = 0.0
    max_val: float = 100.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SensorChannelModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ActuatorChannelModel:
    """Configuration persistante d'un actionneur Arduino."""
    name: str = ""
    kind: str = "custom"
    label: str = ""
    min_val: float = 0.0
    max_val: float = 255.0
    cmd_template: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ActuatorChannelModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ArduinoActionModel:
    """Configuration persistante d'une action Arduino."""
    name: str = ""
    label: str = ""
    description: str = ""
    params: List[str] = field(default_factory=list)
    duration_ms: int = 0
    has_ack: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArduinoActionModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ArduinoDeviceModel:
    """Configuration persistante d'un appareil Arduino."""
    name: str = ""
    port: str = ""
    baud: int = BAUDRATE_ARDUINO_DEFAULT
    firmware: str = ""
    channels: List[SensorChannelModel] = field(default_factory=list)
    actuators: List[ActuatorChannelModel] = field(default_factory=list)
    actions: List[ArduinoActionModel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "port": self.port, "baud": self.baud,
            "firmware": self.firmware,
            "channels": [c.to_dict() for c in self.channels],
            "actuators": [a.to_dict() for a in self.actuators],
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArduinoDeviceModel":
        d = dict(data)
        d["channels"] = [SensorChannelModel.from_dict(c) for c in d.get("channels", [])]
        d["actuators"] = [ActuatorChannelModel.from_dict(a) for a in d.get("actuators", [])]
        d["actions"] = [ArduinoActionModel.from_dict(a) for a in d.get("actions", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AlertRuleModel:
    """Règle de seuil persistante pour un capteur."""
    sensor_id: str = ""
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AlertRuleModel":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class HardwareConfigModel:
    """Configuration hardware complète du projet (Arduino + capteurs + couplage)."""
    version: int = 1
    axis_names: Dict[str, str] = field(default_factory=dict)
    color_rules: List[Dict[str, Any]] = field(default_factory=list)
    devices: List[ArduinoDeviceModel] = field(default_factory=list)
    alert_rules: List[AlertRuleModel] = field(default_factory=list)
    # Couplage axe 2-3 (lu par RobotController._apply_coupling).
    # Format : {enabled, invert, ratio, offset, center}
    coupling: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "axis_names": self.axis_names,
            "color_rules": self.color_rules,
            "devices": [d.to_dict() for d in self.devices],
            "alert_rules": [r.to_dict() for r in self.alert_rules],
            "coupling": self.coupling,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HardwareConfigModel":
        d = dict(data)
        d["devices"] = [ArduinoDeviceModel.from_dict(x) for x in d.get("devices", [])]
        d["alert_rules"] = [AlertRuleModel.from_dict(x) for x in d.get("alert_rules", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
