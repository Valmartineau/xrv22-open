"""
xrv22/config.py
───────────────
Constantes centralisées du projet XRV22 PRO.

JAMAIS de valeur magique codée en dur hors de ce fichier.
Les modules importent depuis ici :
    from xrv22.config import MOTOR_CENTER, BAUDRATE_DXL_DEFAULT
"""

# ═══════════════════════════════════════════════════════════════
# MOTEURS — Dynamixel X Series (Protocol 2.0)
# ═══════════════════════════════════════════════════════════════
MOTOR_IDS_DEFAULT = [1, 2, 3, 4, 5, 6, 7]
MOTOR_COUNT = 7
PINCE_AXIS = 7
HIDDEN_AXES = frozenset({3})   # axes masqués dans l'UI détail

MOTOR_RANGE_MIN = 0
MOTOR_RANGE_MAX = 4095
MOTOR_CENTER = 2048
MOTOR_RANGE = (MOTOR_RANGE_MIN, MOTOR_RANGE_MAX)

# Limites logicielles par défaut (axe: (min, max))
SOFT_LIMITS_DEFAULTS = {
    1: (370, 3450),
    2: (1070, 3000),
    3: (0, 4095),
    4: (915, 3140),
    5: (930, 3380),
    6: (0, 4095),
    7: (1615, 2860),
}

# ═══════════════════════════════════════════════════════════════
# CALIBRATION PINCE (axe 7) — écart réel des doigts en mm
# ═══════════════════════════════════════════════════════════════
# Source de vérité unique (miroir Python de web/src/grip.ts).
# Modèle linéaire, ancres mesurées en live sur robot_1 le 2026-06-15 :
#   contact (doigts joints)      : tick 1649  → 0 mm
#   butée d'ouverture (soft-max) : tick 2860  → 46 mm
# La pente mm/tick est géométrique (quasi identique d'un robot à l'autre) ;
# seule la butée haute varie selon le soft-limit propre au robot.
GRIP_CLOSE_TICK = 1649
GRIP_OPEN_TICK = 2860
GRIP_SPAN_MM = 46.0
GRIP_MM_PER_TICK = GRIP_SPAN_MM / (GRIP_OPEN_TICK - GRIP_CLOSE_TICK)


def gripper_mm(tick: float) -> float:
    """Écart réel entre les doigts (mm) pour une position brute de l'axe 7."""
    return max(0.0, (tick - GRIP_CLOSE_TICK) * GRIP_MM_PER_TICK)


# ═══════════════════════════════════════════════════════════════
# BAUDRATES
# ═══════════════════════════════════════════════════════════════
BAUDRATE_DXL_DEFAULT = 1_000_000
BAUDRATE_DXL_OPTIONS = [57600, 115200, 1_000_000, 2_000_000]
BAUDRATE_DXL_VALID = {9600, 57600, 115200, 1_000_000,
                      2_000_000, 3_000_000, 4_000_000}

BAUDRATE_ARDUINO_DEFAULT = 115200
BAUDRATE_ARDUINO_OPTIONS = [9600, 19200, 57600, 115200, 230400]

# ═══════════════════════════════════════════════════════════════
# PARAMÈTRES MOUVEMENT (defaults)
# ═══════════════════════════════════════════════════════════════
SMOOTH_HZ_DEFAULT = 60
COMFORT_VEL_DEFAULT = 60
COMFORT_ACC_DEFAULT = 20
HOME_DURATION_DEFAULT_S = 3.0

MAX_SPEED_TICKS_PER_S = 1000
MIN_SAFE_DURATION_S = 0.1

# ═══════════════════════════════════════════════════════════════
# TIMEOUTS & FRÉQUENCES (secondes sauf mention)
# ═══════════════════════════════════════════════════════════════
TICK_MS = 50
TICK_S = TICK_MS / 1000.0

HEARTBEAT_INTERVAL_S = 0.5
COMM_TIMEOUT_S = 1.5
ESCALATE_TIMEOUT_S = 5.0

SENSOR_WAIT_DEFAULT_MS = 10_000
SENSOR_UPDATE_HZ = 5.0
SENSOR_TICK_S = 1.0 / SENSOR_UPDATE_HZ

RECONNECT_DELAY_S = 5.0
READ_TIMEOUT_S = 5.0
IDENTIFY_TIMEOUT_S = 4.0
IDENTIFY_RETRIES = 3

SNAP_MS = 250   # timeline : snap au 1/4 de seconde

# ═══════════════════════════════════════════════════════════════
# AUTO-SAVE
# ═══════════════════════════════════════════════════════════════
AUTOSAVE_INTERVAL_MS = 60_000   # 60 secondes

# ═══════════════════════════════════════════════════════════════
# ADRESSES REGISTRES DYNAMIXEL (Protocol 2.0, X Series)
# ═══════════════════════════════════════════════════════════════
ADDR_TORQUE_ENABLE = 64
ADDR_GOAL_POSITION = 108
ADDR_PROFILE_VELOCITY = 112
ADDR_PROFILE_ACCELERATION = 116
ADDR_PRESENT_POSITION = 132
ADDR_MIN_POSITION_LIMIT = 52
ADDR_MAX_POSITION_LIMIT = 48
ADDR_DRIVE_MODE = 10
