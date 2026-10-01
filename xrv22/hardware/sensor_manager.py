"""
xr200/hardware/sensor_manager.py
──────────────────────────────────
Gestionnaire d'état des capteurs.

Rôle :
  - Agréger les lectures capteurs depuis l'ArduinoBridge
  - Maintenir l'état courant de chaque capteur dans le StateStore
  - Évaluer les règles de seuil (alert si > max ou < min)
  - Publier sensor.alert si un seuil est dépassé

Sources :
  - sensor.reading  : lectures Arduino (via bus)
  - sensor.reading  : lectures simulées (SimScene)

Architecture :
  SensorManager n'écrit jamais directement dans l'UI.
  Il publie sur le bus et l'UI lit le StateStore.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("SensorManager")


# ── Dataclasses ──────────────────────────────────────────────────

@dataclass
class SensorReading:
    """Dernière valeur connue d'un capteur."""
    sensor_id: str
    device:    str
    value:     float
    unit:      str   = ""
    min_alert: Optional[float] = None
    max_alert: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    in_alert:  bool  = False

    @property
    def age_s(self) -> float:
        return time.time() - self.timestamp

    @property
    def is_fresh(self) -> bool:
        return self.age_s < 5.0


@dataclass
class AlertRule:
    """Règle de seuil pour un capteur."""
    sensor_id: str
    min_val:   Optional[float] = None
    max_val:   Optional[float] = None
    message:   str             = ""


# ── SensorManager ────────────────────────────────────────────────

class SensorManager:
    """
    Agrège les lectures capteurs et évalue les seuils.
    """

    def __init__(self) -> None:
        self._readings: Dict[str, SensorReading] = {}
        self._rules:    Dict[str, AlertRule]     = {}
        self._lock = threading.Lock()
        self._subscribe()

    # ── Règles ───────────────────────────────────────────────────

    def add_rule(self, sensor_id: str, min_val: Optional[float] = None,
                  max_val: Optional[float] = None, message: str = "") -> None:
        """Ajoute une règle de seuil."""
        with self._lock:
            self._rules[sensor_id] = AlertRule(
                sensor_id=sensor_id, min_val=min_val,
                max_val=max_val, message=message or f"Seuil dépassé : {sensor_id}")
        _LOG.debug("Règle ajoutée : %s  min=%s max=%s", sensor_id, min_val, max_val)

    def remove_rule(self, sensor_id: str) -> None:
        """Supprime une règle."""
        with self._lock:
            self._rules.pop(sensor_id, None)

    def snapshot_rules(self) -> list:
        """Exporte les règles pour persistance."""
        with self._lock:
            return [
                {"sensor_id": r.sensor_id, "min_val": r.min_val,
                 "max_val": r.max_val, "message": r.message}
                for r in self._rules.values()
            ]

    def restore_rules(self, rules_list: list) -> None:
        """Restaure les règles depuis la persistance."""
        with self._lock:
            self._rules.clear()
            for r in rules_list:
                sid = r.get("sensor_id", "")
                if sid:
                    self._rules[sid] = AlertRule(
                        sensor_id=sid,
                        min_val=r.get("min_val"),
                        max_val=r.get("max_val"),
                        message=r.get("message", ""))

    # ── Lectures ─────────────────────────────────────────────────

    def get_reading(self, sensor_id: str) -> Optional[SensorReading]:
        with self._lock:
            return self._readings.get(sensor_id)

    def all_readings(self) -> List[SensorReading]:
        with self._lock:
            return list(self._readings.values())

    def fresh_readings(self) -> List[SensorReading]:
        """Retourne les capteurs ayant reçu une valeur récente."""
        with self._lock:
            return [r for r in self._readings.values() if r.is_fresh]

    def alerts(self) -> List[SensorReading]:
        """Retourne les capteurs en état d'alerte."""
        with self._lock:
            return [r for r in self._readings.values() if r.in_alert]

    def stats(self) -> dict:
        """Statistiques globales."""
        with self._lock:
            total   = len(self._readings)
            fresh   = sum(1 for r in self._readings.values() if r.is_fresh)
            alerted = sum(1 for r in self._readings.values() if r.in_alert)
        return {"total": total, "fresh": fresh, "alerts": alerted}

    # ── Souscriptions bus ────────────────────────────────────────

    def _subscribe(self) -> None:
        """Écoute les événements de lecture capteur."""
        bus.subscribe("sensor.reading", self._on_reading)

    def _on_reading(self, payload: dict) -> None:
        """Traite une lecture capteur (JSON multi-valeurs ou single)."""
        device = payload.get("device", "sim")
        values = payload.get("values")

        if values:
            for ch_name, ch_val in values.items():
                sensor_id = f"{device}.{ch_name}"
                self._record(sensor_id, device, float(ch_val))
        else:
            sensor_id = payload.get("sensor_id", "")
            value     = payload.get("value", 0.0)
            if sensor_id:
                self._record(sensor_id, device, float(value))

    def _record(self, sensor_id: str, device: str, value: float) -> None:
        """Enregistre une valeur et évalue les seuils."""
        with self._lock:
            reading = self._readings.get(sensor_id)
            if reading is None:
                reading = SensorReading(sensor_id=sensor_id, device=device,
                                         value=value)
                self._readings[sensor_id] = reading
            else:
                reading.value     = value
                reading.timestamp = time.time()

            was_alert = reading.in_alert
            rule = self._rules.get(sensor_id)
            reading.in_alert = self._eval_rule(rule, value) if rule else False

        if reading.in_alert and not was_alert:
            self._fire_alert(reading, rule)
        elif was_alert and not reading.in_alert:
            bus.publish("sensor.alert_cleared", {"sensor_id": sensor_id})

    def _eval_rule(self, rule: AlertRule, value: float) -> bool:
        """Évalue si la valeur déclenche l'alerte."""
        if rule.min_val is not None and value < rule.min_val:
            return True
        if rule.max_val is not None and value > rule.max_val:
            return True
        return False

    def _fire_alert(self, reading: SensorReading,
                     rule: Optional[AlertRule]) -> None:
        """Publie une alerte capteur."""
        msg = rule.message if rule else f"Seuil dépassé : {reading.sensor_id}"
        _LOG.warning("⚠️  SENSOR ALERT [%s] = %.2f  → %s",
                      reading.sensor_id, reading.value, msg)
        bus.publish("sensor.alert", {
            "sensor_id": reading.sensor_id,
            "device":    reading.device,
            "value":     reading.value,
            "message":   msg,
        })


# Singleton
sensor_manager = SensorManager()
