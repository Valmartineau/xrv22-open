"""
xrv22/robots/robot_profiles.py
────────────────────────────────
Profils robot — Limites physiques par axe.

V22 : les valeurs par défaut sont lues depuis la librairie
      (XRV22_LIBRARY/global/robot_profiles.json).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from xrv22.services.logger import get_logger

_LOG = get_logger("RobotProfiles")


_defaults_cache: Tuple[Dict[int, Tuple[int, int]], Dict[int, int]] | None = None


def _get_defaults() -> Tuple[Dict[int, Tuple[int, int]], Dict[int, int]]:
    """Charge les limites et home par défaut depuis la librairie (cache apres 1er appel)."""
    global _defaults_cache
    if _defaults_cache is not None:
        return _defaults_cache
    try:
        from xrv22.library.library_manager import library
        result = library.get_default_limits(), library.get_default_home()
        _defaults_cache = result
        return result
    except Exception as exc:
        # Fallback si la librairie n'est pas encore initialisée
        _LOG.debug("Library non prête, fallback limites: %s", exc)
        return _FALLBACK_LIMITS, _FALLBACK_HOME


# Fallback (utilisé uniquement si la librairie est inaccessible)
_FALLBACK_LIMITS: Dict[int, Tuple[int, int]] = {
    1: (370, 3450),
    2: (1070, 3000),
    3: (0, 4095),
    4: (915, 3140),
    5: (930, 3380),
    6: (0, 4095),
    7: (1615, 2860),
}

_FALLBACK_HOME: Dict[int, int] = {
    1: 2050, 2: 900, 3: 900, 4: 3140, 5: 900, 6: 2040, 7: 2100,
}


@dataclass
class RobotProfile:
    """Profil physique d'un robot XRV22."""
    robot_id: str
    name: str
    motor_ids: List[int]
    soft_limits: Dict[int, Tuple[int, int]] = field(default_factory=dict)
    max_speed_ticks_per_s: int = 1000
    min_duration_s: float = 0.15
    max_duration_s: float = 20.0
    color: str = "#f6a117"
    baud: int = 1_000_000

    def __post_init__(self) -> None:
        """Initialise les soft_limits par défaut depuis la librairie."""
        defaults, _ = _get_defaults()
        for mid in self.motor_ids:
            if mid not in self.soft_limits:
                self.soft_limits[mid] = defaults.get(mid, (0, 4095))

    # ── Validation ──────────────────────────────────────────────

    def validate_positions(self, positions: Dict[int, int]) -> Tuple[bool, List[str]]:
        """Vérifie que toutes les positions sont dans les limites."""
        errors = []
        for mid, pos in positions.items():
            lo, hi = self.soft_limits.get(mid, (0, 4095))
            if not (lo <= pos <= hi):
                errors.append(
                    f"Motor {mid}: {pos} hors limites [{lo}, {hi}]")
        return len(errors) == 0, errors

    def validate_duration(self, duration_s: float) -> Tuple[bool, str]:
        """Vérifie que la durée est dans les bornes."""
        if duration_s < self.min_duration_s:
            return False, f"Durée {duration_s:.2f}s < min {self.min_duration_s}s"
        if duration_s > self.max_duration_s:
            return False, f"Durée {duration_s:.1f}s > max {self.max_duration_s}s"
        return True, ""

    def clamp_positions(self, positions: Dict[int, int]) -> Dict[int, int]:
        """Retourne les positions clampées aux limites."""
        out = {}
        for mid, pos in positions.items():
            lo, hi = self.soft_limits.get(mid, (0, 4095))
            out[mid] = max(lo, min(hi, pos))
        return out


# ── Registre des profils ──────────────────────────────────────────

class ProfileRegistry:
    """Registre des profils robot."""

    def __init__(self) -> None:
        self._profiles: Dict[str, RobotProfile] = {}

    def register(self, profile: RobotProfile) -> None:
        self._profiles[profile.robot_id] = profile
        _LOG.info("Profil enregistré : %s (%s)", profile.robot_id, profile.name)

    def get(self, robot_id: str) -> Optional[RobotProfile]:
        return self._profiles.get(robot_id)

    def all_ids(self) -> List[str]:
        return list(self._profiles.keys())


# ── Profil par défaut ──────────────────────────────────────────

def make_default_profile(robot_id: str, color: str = "#f6a117") -> RobotProfile:
    """Crée un profil XRV22 standard (7 axes)."""
    defaults, _ = _get_defaults()
    return RobotProfile(
        robot_id=robot_id,
        name=f"XRV22 {robot_id}",
        motor_ids=[1, 2, 3, 4, 5, 6, 7],
        soft_limits=dict(defaults),
        max_speed_ticks_per_s=1000,
        min_duration_s=0.15,
        max_duration_s=20.0,
        color=color,
        baud=1_000_000,
    )


# Singleton global
profiles = ProfileRegistry()
