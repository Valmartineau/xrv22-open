"""
xr200/theme/theme.py
─────────────────────
Design System XR200 PRO — Source unique.
Dark Neumorphism · Console Robotique Industrielle.

Palette : #80276c (magenta) · #f6a117 (ambre)
Fond    : #1e2130 (dark industriel)

JAMAIS de couleur codée en dur hors de ce fichier.
"""

# ═══════════════════════════════════════════════════════════════
# BACKGROUNDS
# ═══════════════════════════════════════════════════════════════
BG_DEEP     = "#161820"
BG          = "#1e2130"
SURFACE     = "#252836"
SURFACE_HI  = "#2c303e"
SIDEBAR     = "#181b27"

# ── Neumorphic shadows ──────────────────────────────────────────
SH_D        = "#111318"
SH_L        = "#363a4e"
BORDER      = "#2a2e40"
BORDER_MED  = "#323648"   # Transition douce entre BORDER et BORDER_HI
BORDER_HI   = "#3a3e52"

# ═══════════════════════════════════════════════════════════════
# ACCENTS — Primary: Magenta/Prune
# ═══════════════════════════════════════════════════════════════
C_MAG       = "#80276c"
C_MAG_2     = "#934a7f"
C_MAG_3     = "#a06a8f"
C_MAG_4     = "#b48aa5"
C_MAG_DIM   = "#2e0e26"
C_MAG_DIM2  = "#4a1840"

# ── Secondary: Amber ────────────────────────────────────────────
C_AMB       = "#f6a117"
C_AMB_2     = "#e6b54a"
C_AMB_3     = "#edc57b"
C_AMB_4     = "#f3d9a4"
C_AMB_DIM   = "#3e2204"
C_AMB_DIM2  = "#5c3208"

# ═══════════════════════════════════════════════════════════════
# SEMANTIC
# ═══════════════════════════════════════════════════════════════
C_OK        = "#4ade80"
C_OK_DIM    = "#0f2d1a"
C_ERR       = "#f43f5e"
C_ERR_DEEP  = "#7f1d2e"
C_ERR_DIM   = "#3a0a14"
C_WARN      = C_AMB
C_INFO      = "#38bdf8"

# ── États robot → couleur ───────────────────────────────────────
STATE_COLORS = {
    "IDLE":            SURFACE_HI,
    "READY":           C_OK_DIM,
    "RUNNING":         C_AMB_DIM2,
    "PAUSED":          C_AMB_DIM,
    "SOFT_STOP":       C_AMB_DIM,
    "COMM_LOST":       C_ERR_DIM,
    "ERROR":           C_ERR_DIM,
    "EMERGENCY_STOP":  C_ERR_DEEP,
    "LOCKED":          C_MAG_DIM,
}

STATE_TEXT_COLORS = {
    "IDLE":            "#6a6e7e",
    "READY":           C_OK,
    "RUNNING":         C_AMB,
    "PAUSED":          C_AMB_2,
    "SOFT_STOP":       C_AMB_3,
    "COMM_LOST":       C_ERR,
    "ERROR":           C_ERR,
    "EMERGENCY_STOP":  "#ff6b6b",
    "LOCKED":          C_MAG_3,
}

# ═══════════════════════════════════════════════════════════════
# TEXT HIERARCHY
# ═══════════════════════════════════════════════════════════════
TEXT        = "#e6e6e6"
TEXT_MED    = "#8a8f98"
TEXT_DIM    = "#3e4255"
TEXT_ACCENT = C_AMB
TEXT_LABEL  = "#6a6e7e"

# ═══════════════════════════════════════════════════════════════
# TIMELINE TRACK COLORS — un par robot
# ═══════════════════════════════════════════════════════════════
TRACK_COLORS = [
    "#f6a117",   # Robot 1 — ambre
    "#e040fb",   # Robot 2 — magenta vif
    "#00e5ff",   # Robot 3 — cyan
    "#76ff03",   # Robot 4 — lime
    "#ff6e40",   # Robot 5 — corail
    "#4ade80",   # Robot 6 — vert
    "#448aff",   # Robot 7 — bleu roi
    "#f43f5e",   # Robot 8 — rouge
]

TRACK_COLOR_ARDUINO  = "#38bdf8"
TRACK_COLOR_SENSOR   = "#4ade80"
TRACK_COLOR_GLOBAL   = "#b48aa5"

# ═══════════════════════════════════════════════════════════════
# TYPOGRAPHY — Futuristic Industrial
# ═══════════════════════════════════════════════════════════════
FONT_UI     = "DIN Alternate"
FONT_MONO   = "Geist Mono"
FONT_DISPLAY = "Avenir Next Condensed"
FONT_ALT    = "Helvetica Neue"

F_DISPLAY   = (FONT_DISPLAY, 28, "bold")
F_TITLE     = (FONT_DISPLAY, 20, "bold")
F_SECTION   = (FONT_UI, 15, "bold")
F_LABEL     = (FONT_UI, 14)
F_CONTROL   = (FONT_UI, 13)
F_CAPTION   = (FONT_UI, 11)
F_BADGE     = (FONT_UI, 10, "bold")

F_MONO_XL   = (FONT_MONO, 19, "bold")
F_MONO_LG   = (FONT_MONO, 15, "bold")
F_MONO_MD   = (FONT_MONO, 13)
F_MONO_SM   = (FONT_MONO, 11)

# ═══════════════════════════════════════════════════════════════
# SPACING & GEOMETRY
# ═══════════════════════════════════════════════════════════════
PAD_XS  = 4
PAD_SM  = 8
PAD_MD  = 14
PAD_LG  = 20
PAD_XL  = 28

RADIUS_XS   = 6
RADIUS_SM   = 10
RADIUS_MD   = 14
RADIUS_LG   = 20
RADIUS_PILL = 24

SIDEBAR_W   = 272
TOPBAR_H    = 58
STATUSBAR_H = 40

# Timeline
TRACK_H         = 60
TRACK_LABEL_W   = 140
HEADER_H        = 36
BLOCK_PADDING   = 4
MIN_BLOCK_W     = 24

# ═══════════════════════════════════════════════════════════════
# NEUMORPHISM
# ═══════════════════════════════════════════════════════════════
NEU_OFFSET    = 3
NEU_OFFSET_LG = 5
NEU_BLUR      = 2

# ═══════════════════════════════════════════════════════════════
# DICT — compatibilité
# ═══════════════════════════════════════════════════════════════
THEME = {
    "base": BG, "surface": SURFACE, "surface_hi": SURFACE_HI,
    "sidebar": SIDEBAR, "border": BORDER, "border_hi": BORDER_HI,
    "accent": C_MAG, "accent_hi": C_MAG_2, "accent_dim": C_MAG_DIM2,
    "accent2": C_AMB, "accent2_hi": C_AMB_2, "accent2_dim": C_AMB_DIM2,
    "text": TEXT, "text_med": TEXT_MED, "text_dim": TEXT_DIM,
    "success": C_OK, "danger": C_ERR, "warn": C_WARN,
    "shadow_d": SH_D, "shadow_l": SH_L,
}


def state_color(state: str) -> str:
    """Retourne la couleur de fond pour un état robot."""
    return STATE_COLORS.get(state, SURFACE_HI)


def state_text_color(state: str) -> str:
    """Retourne la couleur de texte pour un état robot."""
    return STATE_TEXT_COLORS.get(state, TEXT_MED)


def track_color(index: int) -> str:
    """Retourne la couleur d'une piste robot par index."""
    return TRACK_COLORS[index % len(TRACK_COLORS)]


# ═══════════════════════════════════════════════════════════════
# ROBOT THEME — système centralisé de couleurs par robot
# ═══════════════════════════════════════════════════════════════

def dim_color(hex_color: str, factor: float) -> str:
    """Assombrit une couleur hex. factor=0.0→noir, 1.0→identique."""
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"
    except (ValueError, IndexError):
        return SURFACE


def blend_color(hex_color: str, bg: str, alpha: float) -> str:
    """Mélange hex_color sur bg avec alpha (0=bg pur, 1=couleur pure)."""
    try:
        r1, g1, b1 = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        r2, g2, b2 = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        r = int(r1 * alpha + r2 * (1 - alpha))
        g = int(g1 * alpha + g2 * (1 - alpha))
        b = int(b1 * alpha + b2 * (1 - alpha))
        return f"#{r:02x}{g:02x}{b:02x}"
    except (ValueError, IndexError):
        return SURFACE


def robot_theme(hex_color: str) -> dict:
    """Retourne un dictionnaire complet de couleurs dérivées pour un robot.

    Clés retournées :
      color    — couleur vive du robot
      bg       — fond subtil (teinte très sombre)
      bg_med   — fond moyen (pour sliders / zones actives)
      bg_vif   — fond vif (pour bandeau, accents forts)
      border   — bordure teintée
      text     — texte sur fond vif (noir ou très sombre)
      dim      — couleur atténuée (labels secondaires)
    """
    return {
        "color":   hex_color,
        "bg":      blend_color(hex_color, BG, 0.08),
        "bg_med":  blend_color(hex_color, SURFACE, 0.18),
        "bg_vif":  blend_color(hex_color, SURFACE, 0.35),
        "border":  blend_color(hex_color, BORDER_HI, 0.3),
        "text":    "#1a1a2e",
        "dim":     dim_color(hex_color, 0.5),
    }
