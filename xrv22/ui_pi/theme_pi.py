"""
xrv22/ui_pi/theme_pi.py
────────────────────────
Overrides du design system pour l'ecran tactile 7" 800x480.

Garde la charte Dark Neumorphic (magenta/ambre) mais :
  - Tailles tactiles minimum 48px (recommandation Apple/Material 44-48dp)
  - Boutons principaux 80px (cibles primaires)
  - Polices reduites pour gagner de la place (800x480 oblige)
  - Paddings compactes

Les couleurs sont importees telles quelles depuis xrv22.theme.theme.
"""
from __future__ import annotations

from xrv22.theme import theme as T

# ═══════════════════════════════════════════════════════════════
# VIEWPORT FIXE (7" officiel RPi = 800 x 480)
# ═══════════════════════════════════════════════════════════════
SCREEN_W = 800
SCREEN_H = 480

# ═══════════════════════════════════════════════════════════════
# TAILLES TACTILES
# ═══════════════════════════════════════════════════════════════
TOUCH_MIN      = 48   # Cible tactile minimale (WCAG 2.5.5)
TOUCH_MD       = 64   # Boutons secondaires
TOUCH_LG       = 80   # Boutons primaires (PLAY/PAUSE/STOP)
TOUCH_XL       = 96   # Emergency / action critique

# ═══════════════════════════════════════════════════════════════
# TYPOGRAPHIE COMPACTE
# ═══════════════════════════════════════════════════════════════
F_H1       = (T.FONT_DISPLAY, 14, "bold")   # titre ecran
F_H2       = (T.FONT_DISPLAY, 11, "bold")   # sous-titre
F_BODY     = (T.FONT_UI, 9)                 # texte standard
F_LABEL    = (T.FONT_UI, 8)                 # label secondaire
F_BTN      = (T.FONT_UI, 9, "bold")         # bouton
F_BTN_LG   = (T.FONT_DISPLAY, 11, "bold")   # bouton primaire
F_MONO     = (T.FONT_MONO, 9)               # mono standard
F_MONO_LG  = (T.FONT_MONO, 10, "bold")      # mono titre
F_BADGE    = (T.FONT_UI, 8, "bold")         # badge etat

# ═══════════════════════════════════════════════════════════════
# ESPACEMENTS COMPACTS
# ═══════════════════════════════════════════════════════════════
PAD_XS = 2
PAD_SM = 4
PAD_MD = 8
PAD_LG = 12

RADIUS = 10

# ═══════════════════════════════════════════════════════════════
# HAUTEURS DE SECTIONS (cockpit 800 x 480)
# ═══════════════════════════════════════════════════════════════
H_HEADER   = 52
H_STATUS   = 120
H_SCENARIO = 78
H_ACTIONS  = 170
H_LOG      = 60
# Total = 480
