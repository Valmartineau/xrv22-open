"""
xrv22/ui_pi/widgets_pi.py
──────────────────────────
Widgets neumorphiques tactiles pour RPi 7".

Principes :
  - Tout est dessine sur Canvas (coherence visuelle avec la version Mac)
  - Zones tactiles >= 48px, cibles primaires 80px
  - Pas de survol (pas de <Enter>/<Leave>), seulement press/release
  - Feedback visuel immediat au touch (inversion ombres)

Widgets :
  TouchButton     — bouton neumorphic tactile (multi-tailles)
  StatusTile      — tuile robot (nom + badge etat + positions live)
  ProgressBar     — barre de progression timeline
  ScenarioCombo   — selecteur scenario (popup liste)
  HeaderBar       — barre de titre (titre + retour + horloge)
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Iterable, Optional

from xrv22.config import GRIP_CLOSE_TICK, GRIP_MM_PER_TICK, GRIP_SPAN_MM
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P


# ═══════════════════════════════════════════════════════════════
# Helper neumorphic
# ═══════════════════════════════════════════════════════════════

def _round_rect(c: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                r: int = 10, **kw) -> int:
    """Rectangle arrondi via polygone lisse."""
    pts = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_neu_rect(c: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                  radius: int = P.RADIUS, pressed: bool = False,
                  fill: str = T.SURFACE_HI) -> None:
    """Rectangle neumorphic (ombre inversee si pressed)."""
    sh_d = T.SH_L if pressed else T.SH_D
    sh_l = T.SH_D if pressed else T.SH_L
    off = 2 if pressed else 3
    r = min(radius, 10)
    _round_rect(c, x1 + off, y1 + off, x2 + off, y2 + off, r=r,
                outline=sh_d, fill="", width=2)
    _round_rect(c, x1 - off + 1, y1 - off + 1, x2 - off + 1, y2 - off + 1,
                r=r, outline=sh_l, fill="", width=1)
    _round_rect(c, x1, y1, x2, y2, r=r, fill=fill, outline=T.BORDER, width=1)


# ═══════════════════════════════════════════════════════════════
# TouchButton — bouton tactile
# ═══════════════════════════════════════════════════════════════

class TouchButton(tk.Canvas):
    """Bouton neumorphique tactile a taille configurable.

    Parametres :
        parent     : widget Tk parent
        text       : libelle (peut contenir \\n)
        command    : callback clic
        width      : largeur en px
        height     : hauteur en px (>= P.TOUCH_MIN recommande)
        accent     : couleur de fond (T.SURFACE_HI, T.C_MAG, T.C_ERR...)
        fg         : couleur du texte
        font       : police (defaut P.F_BTN)
        icon       : caractere unicode optionnel au-dessus du texte
    """

    def __init__(self, parent, *, text: str = "", command: Optional[Callable] = None,
                 width: int = 120, height: int = P.TOUCH_LG,
                 accent: str = T.SURFACE_HI, fg: str = T.C_AMB,
                 font=P.F_BTN, icon: str = "", disabled: bool = False):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._text = text
        self._cmd = command
        self._accent = accent
        self._fg = fg
        self._font = font
        self._icon = icon
        self._pressed = False
        self._disabled = disabled
        self._redraw()
        self.bind("<Button-1>",        self._on_down)
        self.bind("<ButtonRelease-1>", self._on_up)

    def _redraw(self) -> None:
        self.delete("all")
        fill = T.SURFACE if self._disabled else self._accent
        fg = T.TEXT_DIM if self._disabled else self._fg
        draw_neu_rect(self, 2, 2, self._width - 2, self._height - 2,
                      pressed=self._pressed, fill=fill)
        cx, cy = self._width // 2, self._height // 2
        # Icon et texte alignes horizontalement sur la meme ligne
        label = f"{self._icon}  {self._text}" if self._icon else self._text
        self.create_text(cx, cy, text=label, fill=fg, font=self._font)

    def _on_down(self, _evt) -> None:
        if self._disabled:
            return
        self._pressed = True
        self._redraw()

    def _on_up(self, evt) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if self._disabled or not was_pressed:
            return
        if 0 <= evt.x <= self._width and 0 <= evt.y <= self._height and self._cmd:
            self._cmd()

    def set_disabled(self, disabled: bool) -> None:
        self._disabled = disabled
        self._redraw()

    def set_text(self, text: str) -> None:
        self._text = text
        self._redraw()

    def set_accent(self, color: str) -> None:
        self._accent = color
        self._redraw()

    def set_fg(self, color: str) -> None:
        self._fg = color
        self._redraw()


# ═══════════════════════════════════════════════════════════════
# StatusTile — tuile etat robot
# ═══════════════════════════════════════════════════════════════

class StatusTile(tk.Canvas):
    """Affichage compact d'un robot : nom, etat, positions live."""

    TILE_W = 380
    TILE_H = 108

    def __init__(self, parent, *, robot_id: str = "—", name: str = "ROBOT",
                 state: str = "IDLE", positions: Optional[Iterable[int]] = None,
                 accent: str = T.C_MAG):
        super().__init__(parent, width=self.TILE_W, height=self.TILE_H,
                         bg=T.BG, highlightthickness=0, bd=0)
        self._rid = robot_id
        self._name = name
        self._state = state
        self._positions = list(positions) if positions else []
        self._accent = accent
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        # fond
        draw_neu_rect(self, 2, 2, self.TILE_W - 2, self.TILE_H - 2,
                      fill=T.SURFACE)
        # bande accent a gauche
        self.create_rectangle(2, 2, 10, self.TILE_H - 2,
                              fill=self._accent, outline="")
        # nom
        self.create_text(22, 20, text=self._name, fill=T.C_AMB,
                         font=P.F_H2, anchor="w")
        # badge etat
        bg_state = T.STATE_COLORS.get(self._state, T.SURFACE_HI)
        fg_state = T.STATE_TEXT_COLORS.get(self._state, T.TEXT_MED)
        x_badge = self.TILE_W - 100
        self.create_rectangle(x_badge, 10, self.TILE_W - 16, 32,
                              fill=bg_state, outline="")
        self.create_text((x_badge + self.TILE_W - 16) // 2, 21,
                         text=self._state, fill=fg_state, font=P.F_BADGE)
        # positions
        if self._positions:
            txt = "  ".join(f"{p:>4}" for p in self._positions[:7])
            self.create_text(22, 54, text=txt, fill=T.TEXT_MED,
                             font=P.F_MONO, anchor="w")
        else:
            self.create_text(22, 54, text="— deconnecte —",
                             fill=T.TEXT_DIM, font=P.F_LABEL, anchor="w")
        # id en bas
        self.create_text(22, self.TILE_H - 14, text=self._rid,
                         fill=T.C_MAG_3, font=P.F_LABEL, anchor="w")

    def update_state(self, state: str) -> None:
        self._state = state
        self._redraw()

    def update_positions(self, positions: Iterable[int]) -> None:
        self._positions = list(positions)
        self._redraw()


# ═══════════════════════════════════════════════════════════════
# ProgressBar — barre progression timeline
# ═══════════════════════════════════════════════════════════════

class ProgressBar(tk.Canvas):
    """Barre de progression neumorphic.
    Items persistants + update via coords/itemconfig (pas de delete) pour
    eviter le flicker quand set_ratio est appele a 20Hz (engine.tick)."""

    def __init__(self, parent, *, width: int = 400, height: int = 28,
                 accent: str = T.C_AMB):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._accent = accent
        self._ratio = 0.0
        # Fond statique (1 fois)
        _round_rect(self, 2, 2, self._width - 2, self._height - 2,
                    r=self._height // 2,
                    fill=T.BG_DEEP, outline=T.BORDER, width=1)
        # Item remplissage : rectangle simple (pas arrondi car coords() ne peut
        # pas redimensionner un polygon arrondi).
        self._fill_item = self.create_rectangle(
            4, 4, 4, self._height - 4,
            fill=self._accent, outline="")
        # Texte contraste : noir/sombre pour rester lisible meme quand le fill
        # ambre passe derriere. Cree EN DERNIER pour etre au-dessus + tag_raise
        # apres chaque update pour s'assurer qu'il reste au-dessus.
        self._text_item = self.create_text(
            self._width // 2, self._height // 2,
            text="0 %", fill="#1a1a2e", font=P.F_MONO_LG)
        self.tag_raise(self._text_item)

    def set_ratio(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        if abs(ratio - self._ratio) < 0.001:
            return  # rien a redessiner
        self._ratio = ratio
        filled = int((self._width - 8) * ratio)
        # Update coords du remplissage (pas de delete)
        if filled > 4:
            self.coords(self._fill_item, 4, 4, 4 + filled, self._height - 4)
            self.itemconfigure(self._fill_item, state="normal")
        else:
            self.itemconfigure(self._fill_item, state="hidden")
        self.itemconfigure(self._text_item, text=f"{int(ratio * 100)} %")
        # Garantit que le texte reste au-dessus du fill (Tk peut reordonner)
        self.tag_raise(self._text_item)


# ═══════════════════════════════════════════════════════════════
# HeaderBar — barre titre
# ═══════════════════════════════════════════════════════════════

class HeaderBar(tk.Canvas):
    """Barre superieure : bouton retour + titre + horloge."""

    def __init__(self, parent, *, title: str = "", show_back: bool = True,
                 on_back: Optional[Callable] = None):
        super().__init__(parent, width=P.SCREEN_W, height=P.H_HEADER,
                         bg=T.SIDEBAR, highlightthickness=0, bd=0)
        self._title = title
        self._show_back = show_back
        self._on_back = on_back
        self._clock = ""
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        # fond
        self.create_rectangle(0, 0, P.SCREEN_W, P.H_HEADER,
                              fill=T.SIDEBAR, outline="")
        # separateur bas
        self.create_line(0, P.H_HEADER - 1, P.SCREEN_W, P.H_HEADER - 1,
                         fill=T.BORDER, width=1)
        # bouton retour
        if self._show_back:
            self.create_text(30, P.H_HEADER // 2, text="\u2190",
                             fill=T.C_AMB, font=(T.FONT_MONO, 24, "bold"),
                             tags="back")
        # titre
        self.create_text(P.SCREEN_W // 2, P.H_HEADER // 2,
                         text=self._title, fill=T.C_AMB, font=P.F_H1)
        # horloge
        self.create_text(P.SCREEN_W - 24, P.H_HEADER // 2,
                         text=self._clock, fill=T.C_MAG_3,
                         font=P.F_MONO_LG, anchor="e")

    def _on_click(self, evt) -> None:
        if self._show_back and evt.x < 60 and self._on_back:
            self._on_back()

    def set_title(self, title: str) -> None:
        self._title = title
        self._redraw()

    def set_clock(self, clock: str) -> None:
        self._clock = clock
        self._redraw()


# ═══════════════════════════════════════════════════════════════
# BottomTabBar — barre onglets fixe en bas (telecommande style)
# ═══════════════════════════════════════════════════════════════

class BottomTabBar(tk.Canvas):
    """Barre d'onglets permanente en bas de l'ecran.

    Parametres :
        tabs  : liste de (id, label, icon) — id est la cle renvoyee
        on_tab_change : callback(tab_id) au tap
    """

    BAR_H = 40

    def __init__(self, parent, *, tabs: list, on_tab_change: Callable[[str], None]):
        super().__init__(parent, width=P.SCREEN_W, height=self.BAR_H,
                         bg=T.SIDEBAR, highlightthickness=0, bd=0)
        self._tabs = tabs  # [(id, label, icon)]
        self._on_change = on_tab_change
        self._active = tabs[0][0] if tabs else ""
        self._redraw()
        self.bind("<ButtonRelease-1>", self._on_click)

    def _redraw(self) -> None:
        self.delete("all")
        n = len(self._tabs)
        if n == 0:
            return
        tab_w = P.SCREEN_W // n
        self.create_rectangle(0, 0, P.SCREEN_W, self.BAR_H,
                              fill=T.SIDEBAR, outline="")
        self.create_line(0, 0, P.SCREEN_W, 0, fill=T.BORDER, width=1)
        for i, (tid, label, icon) in enumerate(self._tabs):
            x0 = i * tab_w
            x1 = x0 + tab_w
            is_active = (tid == self._active)
            bg = T.SURFACE_HI if is_active else T.SIDEBAR
            fg = T.C_AMB if is_active else T.TEXT_MED
            # fond onglet
            self.create_rectangle(x0 + 2, 4, x1 - 2, self.BAR_H - 4,
                                  fill=bg, outline="")
            # bande accent bas si actif
            if is_active:
                self.create_rectangle(x0 + 2, self.BAR_H - 4,
                                      x1 - 2, self.BAR_H - 1,
                                      fill=T.C_AMB, outline="")
            # icone + label
            cx = (x0 + x1) // 2
            self.create_text(cx - 60, self.BAR_H // 2, text=icon,
                             fill=fg, font=(T.FONT_MONO, 20, "bold"),
                             anchor="w")
            self.create_text(cx - 30, self.BAR_H // 2, text=label,
                             fill=fg, font=P.F_BTN_LG, anchor="w")
        # separateurs verticaux
        for i in range(1, n):
            x = i * tab_w
            self.create_line(x, 8, x, self.BAR_H - 8,
                             fill=T.BORDER, width=1)

    def _on_click(self, evt) -> None:
        n = len(self._tabs)
        if n == 0:
            return
        tab_w = P.SCREEN_W // n
        idx = min(n - 1, max(0, evt.x // tab_w))
        new_id = self._tabs[idx][0]
        if new_id != self._active:
            self._active = new_id
            self._redraw()
            self._on_change(new_id)

    def set_active(self, tab_id: str) -> None:
        self._active = tab_id
        self._redraw()


# ═══════════════════════════════════════════════════════════════
# HoldButton — bouton modal "tant que je presse"
# ═══════════════════════════════════════════════════════════════

class HoldButton(tk.Canvas):
    """Bouton qui maintient un etat haut tant qu'il est presse.

    Utilise comme touche modificatrice (L1/R1 sur manette) :
    on_state_change(True) au press, on_state_change(False) au release.
    Compatible avec le MultiTouchDispatcher (methodes _on_press/_on_release).
    """

    def __init__(self, parent, *, text: str = "",
                 accent: str = T.C_AMB,
                 on_state_change: Optional[Callable[[bool], None]] = None,
                 width: int = 200, height: int = 44):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        # NB: Tkinter reserve self._w pour le chemin Tcl du widget. Ne PAS
        # ecrire dessus (ca casse self.delete, self.bind, etc.).
        self._width = width
        self._height = height
        self._text = text
        self._accent = accent
        self._on_state_change = on_state_change
        self._held = False
        self._redraw()
        # Bindings Tk fallback (le dispatcher multi-touch les bypasse)
        self.bind("<Button-1>",        self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Leave>",           self._on_release)

    def _redraw(self) -> None:
        self.delete("all")
        bg = self._accent if self._held else T.SURFACE_HI
        fg = "#ffffff" if self._held else self._accent
        draw_neu_rect(self, 2, 2, self._width - 2, self._height - 2,
                      pressed=self._held, fill=bg)
        self.create_text(self._width // 2, self._height // 2,
                         text=self._text, fill=fg, font=P.F_BTN)

    def _on_press(self, _evt) -> None:
        if self._held:
            return
        self._held = True
        self._redraw()
        if self._on_state_change:
            self._on_state_change(True)

    def _on_drag(self, _evt) -> None:
        # On ignore le drag : tant qu'un doigt reste sur le bouton, c'est tenu
        pass

    def _on_release(self, _evt) -> None:
        if not self._held:
            return
        self._held = False
        self._redraw()
        if self._on_state_change:
            self._on_state_change(False)


# ═══════════════════════════════════════════════════════════════
# Joystick2D — joystick analogique omnidirectionnel (X + Y)
# ═══════════════════════════════════════════════════════════════

class Joystick2D(tk.Canvas):
    """Joystick analogique 2D type manette de jeu.

    - Surface ronde (cercle de pilotage)
    - Press n'importe ou -> handle apparait sous le doigt, vel_x = vel_y = 0
    - Drag -> vel_x = dx / R, vel_y = -dy / R (Y inverse pour 'haut = +')
    - Release -> handle revient au centre (ressort), velocites = 0
    - Mapping configurable : axis_x = motor_x, axis_y = motor_y
    """

    DEADBAND = 0.10  # zone morte centrale (10 % du rayon)

    def __init__(self, parent, *,
                 label_x: str = "X", motor_id_x: int = 1,
                 label_y: str = "Y", motor_id_y: int = 2,
                 accent: str = T.C_AMB,
                 on_velocity: Optional[Callable[[float, float], None]] = None,
                 size: int = 150):
        super().__init__(parent, width=size, height=size, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._size = size
        self._cx = size // 2
        self._cy = size // 2
        self._radius = size // 2 - 8     # rayon de la surface
        self._handle_r = 22              # rayon du handle
        self._label_x = label_x
        self._motor_id_x = motor_id_x
        self._label_y = label_y
        self._motor_id_y = motor_id_y
        self._accent = accent
        self._on_velocity = on_velocity
        self._rel_x = 0.0
        self._rel_y = 0.0
        self._dragging = False
        self._press_x = 0
        self._press_y = 0
        self._redraw()
        self.bind("<Button-1>",        self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Leave>",           self._on_release)

    # ── Rendu ────────────────────────────────────────────────────
    def _redraw(self) -> None:
        self.delete("all")
        cx, cy, R = self._cx, self._cy, self._radius

        # Fond circulaire (zone de pilotage)
        self.create_oval(cx - R, cy - R, cx + R, cy + R,
                         fill=T.SURFACE_HI, outline=T.BORDER, width=1)

        # Zone morte centrale (un peu plus claire)
        dr = int(R * self.DEADBAND)
        self.create_oval(cx - dr, cy - dr, cx + dr, cy + dr,
                         fill=T.BORDER, outline="")

        # Croix de reference (axes)
        self.create_line(cx - R + 4, cy, cx + R - 4, cy,
                         fill=T.TEXT_DIM, width=1)
        self.create_line(cx, cy - R + 4, cx, cy + R - 4,
                         fill=T.TEXT_DIM, width=1)

        # Labels axes (X aux extremites horizontales, Y aux verticales)
        self.create_text(cx - R + 6, cy - 8, text=self._label_x,
                         fill=self._accent, font=P.F_LABEL, anchor="w")
        self.create_text(cx, cy - R + 12, text=self._label_y,
                         fill=self._accent, font=P.F_LABEL)

        # Handle (sous le doigt si drag, sinon au centre = ressort)
        hx = cx + int(self._rel_x * R)
        hy = cy - int(self._rel_y * R)  # Y inverse : rel_y > 0 = haut
        r = self._handle_r
        outline_w = 4 if self._dragging else 2
        fill = self._accent if self._dragging else "#1a1a2e"
        self.create_oval(hx - r, hy - r, hx + r, hy + r,
                         fill=fill, outline=self._accent, width=outline_w)
        # Point central blanc
        self.create_oval(hx - 3, hy - 3, hx + 3, hy + 3,
                         fill="#ffffff", outline="")

    # ── Calcul rel ───────────────────────────────────────────────
    def _delta_to_rel(self, dx: int, dy: int) -> tuple[float, float]:
        """(dx, dy en px) -> (rel_x, rel_y in [-1..+1]). Clamp dans
        un cercle (pas dans un carre) pour la sensation joystick rond."""
        R = max(1, self._radius)
        rx = dx / R
        ry = -dy / R    # Y inverse : haut = +
        # Clamp dans le disque unite
        norm = (rx * rx + ry * ry) ** 0.5
        if norm > 1.0:
            rx /= norm
            ry /= norm
        return max(-1.0, min(1.0, rx)), max(-1.0, min(1.0, ry))

    # ── Interactions ─────────────────────────────────────────────
    def _on_press(self, evt) -> None:
        # Presse acceptable n'importe ou dans le carre du widget
        self._dragging = True
        self._press_x = evt.x
        self._press_y = evt.y
        self._rel_x = 0.0
        self._rel_y = 0.0
        self._redraw()
        if self._on_velocity:
            self._on_velocity(0.0, 0.0)

    def _on_drag(self, evt) -> None:
        if not self._dragging:
            return
        dx = evt.x - self._press_x
        dy = evt.y - self._press_y
        self._rel_x, self._rel_y = self._delta_to_rel(dx, dy)
        self._redraw()
        if self._on_velocity:
            self._on_velocity(self._rel_x, self._rel_y)

    def _on_release(self, _evt) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self._rel_x = 0.0
        self._rel_y = 0.0
        self._redraw()
        if self._on_velocity:
            self._on_velocity(0.0, 0.0)

    # ── API publique ─────────────────────────────────────────────
    def stop(self) -> None:
        """Force l'arret + retour au centre."""
        if self._dragging or self._rel_x != 0 or self._rel_y != 0:
            self._dragging = False
            self._rel_x = 0.0
            self._rel_y = 0.0
            self._redraw()
            if self._on_velocity:
                self._on_velocity(0.0, 0.0)

    def set_value(self, _value: int) -> None:
        """Compat tick_ghost (les valeurs reelles ne sont pas
        affichees sur ce widget, seul le handle compte)."""
        return


# ═══════════════════════════════════════════════════════════════
# JoystickStick — stick analogique horizontal pour piloter un axe
# ═══════════════════════════════════════════════════════════════

class JoystickStick(tk.Canvas):
    """Stick horizontal type manette de jeu.

    Layout : [LABEL]  ━━━━━━●━━━━━━  [VALUE]
                              ↑
                       handle deplacable

    - Tap + drag du handle -> on_velocity(rel) avec rel in [-1..+1]
    - Plus on s'eloigne du centre, plus la vitesse est rapide (easing
      quadratique pour precision proche du centre).
    - Au release : retour ressort instantane au centre + on_velocity(0).
    """

    # Stick rasse a droite pour pilotage au pouce droit (main qui tient l'ecran).
    # Course ~160 px ≈ 3 cm sur ecran 7" officiel — sensation manette Xbox.
    STICK_W = 160
    HANDLE_R = 16
    RIGHT_MARGIN = 16
    DEADBAND = 0.08  # zone morte un peu plus large pour un stick court

    def __init__(self, parent, *, label: str = "", motor_id: int = 1,
                 value: int = 2048, accent: str = T.C_AMB,
                 on_velocity: Optional[Callable[[float], None]] = None,
                 value_fmt: Optional[Callable[[int], str]] = None,
                 width: int = 784, height: int = 56):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._label = label
        self._motor_id = motor_id
        self._value = int(value)
        self._accent = accent
        self._on_velocity = on_velocity
        self._value_fmt = value_fmt or (lambda v: str(v))
        self._rel = 0.0          # position du handle, -1..+1 (persistante)
        self._dragging = False
        self._press_x = 0        # x du press initial
        self._press_rel = 0.0    # rel au moment du press (origine du drag)
        self._redraw()
        self.bind("<Button-1>",        self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Leave>",           self._on_release)

    # ── Geometrie ────────────────────────────────────────────────
    def _is_compact(self) -> bool:
        """Mode compact (2 lignes) si la largeur ne permet pas
        d'afficher label + valeur + stick sur une seule ligne."""
        return self._width < 500

    def _track_bounds(self) -> tuple[int, int, int]:
        """(x0, x1, y_centre) du track horizontal."""
        if self._is_compact():
            # Layout 2 lignes : stick centre dans la moitie basse
            x_pad = 16
            x0 = x_pad
            x1 = self._width - x_pad
            yc = int(self._height * 0.72)
        else:
            # Layout 1 ligne : stick colle a droite
            x1 = self._width - self.RIGHT_MARGIN
            x0 = x1 - self.STICK_W
            yc = self._height // 2
        return x0, x1, yc

    def _rel_to_x(self, rel: float) -> int:
        x0, x1, _ = self._track_bounds()
        cx = (x0 + x1) // 2
        half = (x1 - x0) // 2
        return int(cx + rel * half)

    def _delta_to_rel(self, dx: int) -> float:
        """Convertit un deplacement (px) depuis le press en rel -1..+1.

        On utilise la demi-course du stick comme reference. Au press, rel=0
        peu importe ou on touche -> sensation 'saisir' un vrai joystick.
        """
        _x0, _x1, _ = self._track_bounds()
        half = max(1, (_x1 - _x0) // 2)
        return max(-1.0, min(1.0, dx / half))

    # ── Rendu ────────────────────────────────────────────────────
    def _redraw(self) -> None:
        self.delete("all")
        x0, x1, yc = self._track_bounds()
        cx = (x0 + x1) // 2

        if self._is_compact():
            # Mode compact : top = label gauche + valeur droite, gros et lisibles
            top_y = max(8, int(self._height * 0.22))
            self.create_text(12, top_y, text=self._label,
                             fill=self._accent, font=P.F_H1, anchor="w")
            self.create_text(self._width - 12, top_y,
                             text=self._value_fmt(self._value),
                             fill=T.C_AMB, font=P.F_MONO_LG, anchor="e")
        else:
            # Layout 1 ligne : label gauche + valeur juste avant le stick
            self.create_text(12, yc - 8, text=self._label,
                             fill=self._accent, font=P.F_H1, anchor="w")
            self.create_text(12, yc + 12, text=f"axe {self._motor_id}",
                             fill=T.TEXT_MED, font=P.F_LABEL, anchor="w")
            self.create_text(x0 - 16, yc, text=self._value_fmt(self._value),
                             fill=T.C_AMB, font=P.F_MONO_LG, anchor="e")

        # Track : rail sombre + zone morte centrale plus claire
        rail_h = 8
        self.create_rectangle(x0, yc - rail_h // 2, x1, yc + rail_h // 2,
                              fill=T.SURFACE_HI, outline=T.BORDER, width=1)
        # Zone morte (deadband) coloree en clair pour visibilite
        dead_w = int((x1 - x0) // 2 * self.DEADBAND)
        self.create_rectangle(cx - dead_w, yc - rail_h // 2,
                              cx + dead_w, yc + rail_h // 2,
                              fill=T.BORDER, outline="")

        # Marqueurs des extremes (- gauche / + droite, plus discrets)
        self.create_text(x0 - 8, yc, text="−",
                         fill=T.TEXT_DIM, font=(T.FONT_DISPLAY, 14, "bold"),
                         anchor="e")
        self.create_text(x1 + 8, yc, text="+",
                         fill=T.TEXT_DIM, font=(T.FONT_DISPLAY, 14, "bold"),
                         anchor="w")

        # Le handle reste a la position courante _rel (persistante au release).
        xh = self._rel_to_x(self._rel)

        # Trail entre centre et handle (visu de la deviation)
        if abs(self._rel) > self.DEADBAND:
            tx0 = min(cx, xh)
            tx1 = max(cx, xh)
            self.create_rectangle(tx0, yc - rail_h // 2,
                                  tx1, yc + rail_h // 2,
                                  fill=self._accent, outline="")

        # Handle (rond) — plus epais quand actif
        r = self.HANDLE_R
        outline_w = 4 if self._dragging else 2
        fill = self._accent if self._dragging else "#1a1a2e"
        self.create_oval(xh - r, yc - r, xh + r, yc + r,
                         fill=fill, outline=self._accent, width=outline_w)
        # Point central blanc (visu nette)
        self.create_oval(xh - 3, yc - 3, xh + 3, yc + 3,
                         fill="#ffffff", outline="")

    # ── Interactions ─────────────────────────────────────────────
    def _on_press(self, evt) -> None:
        x0, x1, _ = self._track_bounds()
        # Press accepte dans la zone stick + marge confortable pour le pouce
        if not (x0 - 24 <= evt.x <= x1 + 24):
            return
        # Press 'saisit' le stick : rel=0 au point de contact, peu importe
        # ou. Le drag calcule la velocite comme un delta depuis ce point.
        self._dragging = True
        self._press_x = evt.x
        self._press_rel = 0.0
        self._rel = 0.0
        self._redraw()
        if self._on_velocity:
            self._on_velocity(0.0)

    def _on_drag(self, evt) -> None:
        if not self._dragging:
            return
        dx = evt.x - self._press_x
        half = max(1, (self._track_bounds()[1]
                       - self._track_bounds()[0]) // 2)
        self._rel = max(-1.0, min(1.0, dx / half))
        self._redraw()
        if self._on_velocity:
            self._on_velocity(self._rel)

    def _on_release(self, _evt) -> None:
        if not self._dragging:
            return
        self._dragging = False
        # Effet ressort : handle revient au centre, robot s'arrete.
        # Le robot garde sa position physique (cible accumulee dans pilotage).
        self._rel = 0.0
        self._press_rel = 0.0
        self._redraw()
        if self._on_velocity:
            self._on_velocity(0.0)

    # ── API publique ─────────────────────────────────────────────
    def set_value(self, value: int) -> None:
        self._value = int(value)
        if not self._dragging:
            self._redraw()

    def stop(self) -> None:
        """Force l'arret + retour au centre (utilise au switch de robot)."""
        if self._dragging or self._rel != 0.0:
            self._dragging = False
            self._rel = 0.0
            self._press_rel = 0.0
            self._redraw()
            if self._on_velocity:
                self._on_velocity(0.0)


# ═══════════════════════════════════════════════════════════════
# JoystickPair — controle d'axe type manette : boutons − et +
# ═══════════════════════════════════════════════════════════════

class JoystickPair(tk.Canvas):
    """Paire de boutons − / + pour piloter un axe en vitesse.

    Tant que le doigt maintient un bouton -> on_velocity(-1.0) ou (+1.0).
    Au relachement -> on_velocity(0.0). Style "manette" (gros boutons
    tactiles), avec label axe + valeur courante au centre.
    """

    def __init__(self, parent, *, label: str = "", motor_id: int = 1,
                 value: int = 2048, accent: str = T.C_AMB,
                 on_velocity: Optional[Callable[[float], None]] = None,
                 value_fmt: Optional[Callable[[int], str]] = None,
                 width: int = 760, height: int = 56):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._label = label
        self._motor_id = motor_id
        self._value = int(value)
        self._accent = accent
        self._on_velocity = on_velocity
        self._value_fmt = value_fmt or (lambda v: str(v))
        self._active_dir = 0  # -1 / 0 / +1
        self._redraw()
        self.bind("<Button-1>",        self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Leave>",           self._on_release)

    # ── Geometrie : 2 zones cliquables (gauche = −, droite = +) ─
    def _hit(self, x: int) -> int:
        """Renvoie -1 si tap dans zone −, +1 zone +, 0 sinon (label)."""
        margin = 4
        gap = 8
        btn_w = (self._width - 2 * margin - gap - 200) // 2
        # Layout : [ −  btn_w ] [ label/valeur 200 ] [ +  btn_w ]
        x_minus_end = margin + btn_w
        x_plus_start = self._width - margin - btn_w
        if margin <= x <= x_minus_end:
            return -1
        if x_plus_start <= x <= self._width - margin:
            return +1
        return 0

    def _redraw(self) -> None:
        self.delete("all")
        margin = 4
        gap = 8
        btn_w = (self._width - 2 * margin - gap - 200) // 2
        h = self._height - 2 * margin
        y0 = margin
        y1 = self._height - margin

        # Bouton − (gauche)
        x0_m = margin
        x1_m = margin + btn_w
        bg_m = self._accent if self._active_dir == -1 else T.SURFACE_HI
        fg_m = "#ffffff" if self._active_dir == -1 else self._accent
        draw_neu_rect(self, x0_m, y0, x1_m, y1,
                      pressed=(self._active_dir == -1), fill=bg_m)
        self.create_text((x0_m + x1_m) // 2, (y0 + y1) // 2,
                         text="−", fill=fg_m,
                         font=(T.FONT_DISPLAY, 28, "bold"))

        # Bouton + (droite)
        x0_p = self._width - margin - btn_w
        x1_p = self._width - margin
        bg_p = self._accent if self._active_dir == +1 else T.SURFACE_HI
        fg_p = "#ffffff" if self._active_dir == +1 else self._accent
        draw_neu_rect(self, x0_p, y0, x1_p, y1,
                      pressed=(self._active_dir == +1), fill=bg_p)
        self.create_text((x0_p + x1_p) // 2, (y0 + y1) // 2,
                         text="+", fill=fg_p,
                         font=(T.FONT_DISPLAY, 28, "bold"))

        # Zone centrale : label + valeur
        cx = self._width // 2
        cy = self._height // 2
        self.create_text(cx, cy - 8, text=self._label,
                         fill=self._accent, font=P.F_H2)
        self.create_text(cx, cy + 10,
                         text=self._value_fmt(self._value),
                         fill=T.TEXT_MED, font=P.F_MONO_LG)

    # ── Interactions ──────────────────────────────────────────────
    def _on_press(self, evt) -> None:
        d = self._hit(evt.x)
        if d == 0:
            return
        self._active_dir = d
        self._redraw()
        if self._on_velocity:
            self._on_velocity(float(d))

    def _on_release(self, _evt) -> None:
        if self._active_dir == 0:
            return
        self._active_dir = 0
        self._redraw()
        if self._on_velocity:
            self._on_velocity(0.0)

    # ── API publique ─────────────────────────────────────────────
    def set_value(self, value: int) -> None:
        self._value = int(value)
        self._redraw()

    def stop(self) -> None:
        """Force l'arret (utilise au switch de robot)."""
        if self._active_dir != 0:
            self._active_dir = 0
            self._redraw()
            if self._on_velocity:
                self._on_velocity(0.0)


# ═══════════════════════════════════════════════════════════════
# TouchSlider — slider tactile (drag large) avec limites + ghost
# ═══════════════════════════════════════════════════════════════

class TouchSlider(tk.Canvas):
    """Slider tactile — rendu identique a l'onglet Position & Suite Mac.

    - Piste : bande robot_theme(accent).bg_vif sur toute la largeur (4px)
    - Marqueur centre : petit trait vertical TEXT_DIM
    - Pince (motor_id=7) : graduations en mm reels (calibration partagee)
    - Ghost : petit cercle gris (TEXT_DIM / BORDER_HI) = position hardware live
    - Handle : cercle #1a1a2e avec contour couleur robot 2px
    - Label a gauche, valeur a droite
    """

    HANDLE_R = 22

    def __init__(self, parent, *, label: str = "", motor_id: int = 1,
                 lo: int = 0, hi: int = 4095,
                 pos_min: int = 0, pos_max: int = 4095,
                 value: int = 2048, accent: str = T.C_AMB,
                 on_change: Optional[Callable[[int], None]] = None,
                 on_commit: Optional[Callable[[int], None]] = None,
                 on_velocity: Optional[Callable[[float], None]] = None,
                 value_fmt: Optional[Callable[[int], str]] = None,
                 joystick: bool = False,
                 width: int = 760, height: int = 44):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._label = label
        self._motor_id = motor_id
        self._lo, self._hi = lo, hi
        self._pmin, self._pmax = pos_min, pos_max
        self._value = int(value)
        self._ghost = int(value)
        self._accent = accent
        self._on_change = on_change
        self._on_commit = on_commit
        self._on_velocity = on_velocity
        self._value_fmt = value_fmt or (lambda v: str(v))
        self._joystick = joystick
        self._joystick_v = 0.0  # -1..+1 quand drag, 0 au repos
        self._dragging = False
        self._redraw()
        self.bind("<Button-1>",        self._on_down)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_up)

    # ── Geometrie ─────────────────────────────────────────────────
    def _track_bounds(self) -> tuple[int, int, int]:
        """(x_start, x_end, y_center) de la piste."""
        label_w = 120
        value_w = 96
        pad = P.PAD_MD
        x_start = label_w + pad
        x_end = self._width - value_w - pad
        y_center = self._height // 2 + 2
        return x_start, x_end, y_center

    def _value_to_x(self, value: int) -> int:
        x0, x1, _ = self._track_bounds()
        span = max(1, self._pmax - self._pmin)
        return int(x0 + (x1 - x0) * (value - self._pmin) / span)

    def _x_to_value(self, x: int) -> int:
        x0, x1, _ = self._track_bounds()
        span = max(1, self._pmax - self._pmin)
        ratio = max(0.0, min(1.0, (x - x0) / max(1, x1 - x0)))
        return int(self._pmin + span * ratio)

    # ── Rendu (rigoureusement aligne sur tab_positions Mac) ───────
    def _redraw(self) -> None:
        self.delete("all")
        x0, x1, yc = self._track_bounds()
        rt = T.robot_theme(self._accent)

        # label (gauche) — couleur du robot actif pour forte identite visuelle
        self.create_text(P.PAD_SM, yc - 8, text=self._label,
                         fill=self._accent, font=P.F_H2, anchor="w")
        self.create_text(P.PAD_SM, yc + 10, text=f"axe {self._motor_id}",
                         fill=T.TEXT_MED, font=P.F_LABEL, anchor="w")

        # Piste : bande coloree robot — fond sombre + remplissage bg_vif 6px
        self.create_rectangle(x0, yc - 3, x1, yc + 3,
                              fill=rt["bg_vif"], outline="")
        # Surlignage fin (plus sature) au dessus et en dessous pour visibilite
        self.create_line(x0, yc - 3, x1, yc - 3, fill=self._accent, width=1)
        self.create_line(x0, yc + 3, x1, yc + 3, fill=self._accent, width=1)
        # Marqueur centre
        x_mid = (x0 + x1) // 2
        self.create_line(x_mid, yc - 5, x_mid, yc + 5,
                         fill=T.TEXT_DIM, width=1)

        # Graduations pince (axe 7) — mm reels positionnes via la calibration
        # partagee : chaque mm est place au tick correspondant (aligne au handle).
        if self._motor_id == 7:
            total_mm = int(GRIP_SPAN_MM)
            for mm in range(1, total_mm + 1):
                gx = self._value_to_x(round(GRIP_CLOSE_TICK + mm / GRIP_MM_PER_TICK))
                if mm % 10 == 0:
                    tick_h, tick_w, color = 10, 2, "#ffffff"
                elif mm % 5 == 0:
                    tick_h, tick_w, color = 6, 1, T.TEXT_MED
                else:
                    tick_h, tick_w, color = 3, 1, T.TEXT_DIM
                self.create_line(gx, yc + 3, gx, yc + 3 + tick_h,
                                 fill=color, width=tick_w)
                if mm % 10 == 0:
                    self.create_text(gx, yc + 16, text=str(mm),
                                     fill="#ffffff",
                                     font=(T.FONT_MONO, 9, "bold"),
                                     anchor="center")
            self.create_text(x1 + 4, yc + 16, text="mm",
                             fill=T.TEXT_MED, font=(T.FONT_MONO, 8),
                             anchor="w")

        # Ghost (position hardware live) — dessine sous le handle
        r = self.HANDLE_R
        if self._ghost is not None:
            xg = self._value_to_x(self._ghost)
            gr = r - 2
            self.create_oval(xg - gr, yc - gr, xg + gr, yc + gr,
                             fill=T.TEXT_DIM, outline=T.BORDER_HI,
                             width=1, tags="ghost")

        # Handle (position commandee) — fond plein accent + contour clair, +
        # marqueur central pour reperer le centre du rond au pouce
        xp = self._value_to_x(self._value)
        outline_w = 3 if self._dragging else 2
        self.create_oval(xp - r, yc - r, xp + r, yc + r,
                         fill=self._accent, outline="#ffffff",
                         width=outline_w, tags="pos")
        # Point central pour rendre le rond plus net visuellement
        self.create_oval(xp - 3, yc - 3, xp + 3, yc + 3,
                         fill="#ffffff", outline="", tags="pos")

        # Valeur (droite)
        txt = self._value_fmt(self._value)
        self.create_text(self._width - P.PAD_MD, yc,
                         text=txt, fill=T.C_AMB, font=P.F_MONO_LG, anchor="e")

    # ── Interactions ──────────────────────────────────────────────
    def _joystick_norm(self, x: int) -> float:
        """Convertit une position pixel en valeur normalisee -1..+1."""
        x0, x1, _ = self._track_bounds()
        center = (x0 + x1) // 2
        half = max(1, (x1 - x0) // 2)
        return max(-1.0, min(1.0, (x - center) / half))

    def _center_value(self) -> int:
        return (self._pmin + self._pmax) // 2

    def _on_down(self, evt) -> None:
        self._dragging = True
        if self._joystick:
            rel = self._joystick_norm(evt.x)
            self._joystick_v = rel
            # Le handle suit le doigt visuellement (sur la course pmin..pmax)
            self._value = int(self._pmin
                              + (self._pmax - self._pmin) * (rel + 1.0) / 2.0)
            self._redraw()
            if self._on_velocity:
                self._on_velocity(rel)
        else:
            v = self._x_to_value(evt.x)
            self._value = max(self._lo, min(self._hi, v))
            self._redraw()
            if self._on_change:
                self._on_change(self._value)

    def _on_drag(self, evt) -> None:
        if not self._dragging:
            return
        if self._joystick:
            rel = self._joystick_norm(evt.x)
            self._joystick_v = rel
            self._value = int(self._pmin
                              + (self._pmax - self._pmin) * (rel + 1.0) / 2.0)
            self._redraw()
            if self._on_velocity:
                self._on_velocity(rel)
        else:
            v = self._x_to_value(evt.x)
            self._value = max(self._lo, min(self._hi, v))
            self._redraw()
            if self._on_change:
                self._on_change(self._value)

    def _on_up(self, _evt) -> None:
        was = self._dragging
        self._dragging = False
        if not was:
            return
        if self._joystick:
            # Retour au centre + arret immediat
            self._joystick_v = 0.0
            self._value = self._center_value()
            self._redraw()
            if self._on_velocity:
                self._on_velocity(0.0)
        elif self._on_commit:
            self._on_commit(self._value)

    # ── API ───────────────────────────────────────────────────────
    def set_value(self, value: int) -> None:
        self._value = int(value)
        self._redraw()

    def set_ghost(self, value: int) -> None:
        self._ghost = int(value)
        if not self._dragging:
            self._redraw()

    def set_limits(self, lo: int, hi: int) -> None:
        self._lo, self._hi = lo, hi
        self._redraw()

    def get_value(self) -> int:
        return self._value
