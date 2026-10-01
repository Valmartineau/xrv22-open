"""
xr200/ui/widgets.py
────────────────────
Widgets réutilisables Dark Neumorphic.

NeuFrame        — surface raised/inset avec ombres
NeuButton       — bouton neumorphic
NeuLabel        — label stylé
StatusBadge     — badge état robot (couleur dynamique)
SectionHeader   — entête de section
Separator       — séparateur horizontal stylé
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from xrv22.theme import theme as T


# ── Helpers canvas neumorphique ───────────────────────────────────

def _canvas_round_rect(canvas: tk.Canvas, x1: int, y1: int,
                       x2: int, y2: int, r: int = 8, **kw) -> int:
    """CC=1 — Dessine un polygone arrondi sur un canvas."""
    points = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


def draw_neu_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                  radius: int = T.RADIUS_MD, raised: bool = True,
                  fill: str = T.SURFACE_HI) -> None:
    """CC=4 — Dessine un rectangle neumorphic arrondi sur un canvas."""
    sh_d = T.SH_D if raised else T.SH_L
    sh_l = T.SH_L if raised else T.SH_D

    offset = T.NEU_OFFSET
    r = min(radius, 10)
    # Ombre sombre (bas-droite)
    _canvas_round_rect(canvas, x1 + offset, y1 + offset,
                       x2 + offset, y2 + offset, r=r,
                       outline=sh_d, fill="", width=T.NEU_BLUR)
    # Ombre lumineuse (haut-gauche)
    _canvas_round_rect(canvas, x1 - offset + 1, y1 - offset + 1,
                       x2 - offset + 1, y2 - offset + 1, r=r,
                       outline=sh_l, fill="", width=1)
    # Surface
    _canvas_round_rect(canvas, x1, y1, x2, y2, r=r,
                       fill=fill, outline=T.BORDER, width=1)


# ── NeuFrame ─────────────────────────────────────────────────────

class NeuFrame(tk.Frame):
    """Surface neumorphic avec relief visuel subtil."""

    def __init__(self, parent: tk.Widget, raised: bool = True,
                 padding: int = T.PAD_MD, **kw) -> None:
        bg = T.SURFACE_HI if raised else T.SURFACE
        hl = T.BORDER_HI if raised else T.BORDER
        super().__init__(parent,
            bg=bg,
            highlightbackground=hl,
            highlightthickness=1,
            padx=padding, pady=padding,
            **kw
        )
        self._bg = bg


# ── NeuButton ────────────────────────────────────────────────────

class NeuButton(tk.Canvas):
    """
    Bouton neumorphic custom avec coins arrondis.
    Utilise tk.Canvas pour le rendu arrondi.
    """

    def __init__(self, parent: tk.Widget, text: str,
                 command: Optional[Callable] = None,
                 accent: bool = False,
                 danger: bool = False,
                 width: int = 0,
                 **kw) -> None:
        self._bg_val = T.C_MAG_DIM2 if accent else (T.C_ERR_DIM if danger else T.SURFACE_HI)
        self._fg = T.C_AMB if accent else (T.C_ERR if danger else T.TEXT)
        self._bg_hover = T.C_MAG if accent else (T.C_ERR_DEEP if danger else T.C_MAG_DIM2)
        self._command = command
        self._text = text

        h = 32
        w_px = max((width or len(text)) * 9 + 24, 60)
        super().__init__(parent, bg=parent.cget("bg"),
                         width=w_px, height=h,
                         highlightthickness=0, bd=0,
                         cursor="hand2", **kw)
        self._w = w_px
        self._h = h
        self._draw(self._bg_val)

        self.bind("<Enter>",    self._on_enter)
        self.bind("<Leave>",    self._on_leave)
        self.bind("<Button-1>", self._on_click)

        self.bind("<Enter>",        self._on_enter)
        self.bind("<Leave>",        self._on_leave)
        self.bind("<Button-1>",     self._on_click)
        self._lbl.bind("<Enter>",   self._on_enter)
        self._lbl.bind("<Leave>",   self._on_leave)
        self._lbl.bind("<Button-1>",self._on_click)

    def _draw(self, bg: str) -> None:
        """Redessine le bouton avec la couleur donnée."""
        self.delete("all")
        r = 8
        w, h = self._w, self._h
        pts = [
            r, 0, w - r, 0,
            w, 0, w, r,
            w, h - r, w, h,
            w - r, h, r, h,
            0, h, 0, h - r,
            0, r, 0, 0,
        ]
        self.create_polygon(pts, smooth=True,
                            fill=bg, outline=T.BORDER_HI, width=1)
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=self._fg, font=T.F_CONTROL)

    def config_text(self, text: str) -> None:
        self._text = text
        self._draw(self._bg_val)

    def _on_enter(self, _=None) -> None:
        self._draw(self._bg_hover)

    def _on_leave(self, _=None) -> None:
        self._draw(self._bg_val)

    def _on_click(self, _=None) -> None:
        if self._command:
            self._command()


# ── StatusBadge ──────────────────────────────────────────────────

class StatusBadge(tk.Label):
    """Badge d'état robot avec couleur dynamique selon l'état."""

    def __init__(self, parent: tk.Widget, state: str = "IDLE", **kw) -> None:
        super().__init__(parent,
            font=T.F_BADGE,
            padx=8, pady=3,
            **kw
        )
        self.set_state(state)

    def set_state(self, state: str) -> None:
        """Met à jour l'affichage selon l'état."""
        self.config(
            text=f" {state} ",
            bg=T.state_color(state),
            fg=T.state_text_color(state),
        )


# ── SectionHeader ────────────────────────────────────────────────

class SectionHeader(tk.Frame):
    """Entête de section avec accent coloré."""

    def __init__(self, parent: tk.Widget, title: str,
                 subtitle: str = "", **kw) -> None:
        super().__init__(parent, bg=T.BG, **kw)
        accent = tk.Frame(self, bg=T.C_MAG, width=3)
        accent.pack(side="left", fill="y", padx=(0, 10))
        text_frame = tk.Frame(self, bg=T.BG)
        text_frame.pack(side="left", fill="both", expand=True, pady=T.PAD_SM)
        tk.Label(text_frame, text=title,
                 bg=T.BG, fg=T.TEXT, font=T.F_SECTION).pack(anchor="w")
        if subtitle:
            tk.Label(text_frame, text=subtitle,
                     bg=T.BG, fg=T.TEXT_MED, font=T.F_CAPTION).pack(anchor="w")


# ── Separator ─────────────────────────────────────────────────────

class HSep(tk.Frame):
    """Séparateur horizontal stylé."""

    def __init__(self, parent: tk.Widget, **kw) -> None:
        super().__init__(parent, bg=T.BORDER, height=1, **kw)


# ── RoundedFrame ──────────────────────────────────────────────────

class RoundedFrame(tk.Canvas):
    """CC=4 — Frame avec coins arrondis dessinés sur Canvas.

    Utiliser `inner` comme parent pour placer les widgets enfants.
    """

    def __init__(self, parent: tk.Widget, bg: str = T.SURFACE,
                 border_color: str = T.BORDER, radius: int = 14,
                 padding: int = 8, **kw) -> None:
        super().__init__(parent, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0, **kw)
        self._rf_bg = bg
        self._rf_border = border_color
        self._rf_radius = radius

        self.inner = tk.Frame(self, bg=bg, padx=padding, pady=padding)
        self._window_id = self.create_window(0, 0, window=self.inner,
                                              anchor="nw")
        self.bind("<Configure>", self._on_configure)

    def _on_configure(self, event=None) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return
        self.delete("bg")
        r = self._rf_radius
        # Rectangle arrondi via arcs + rectangles
        self.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                        fill=self._rf_bg, outline=self._rf_border,
                        tags="bg")
        self.create_arc(w - 2 * r, 0, w, 2 * r, start=0, extent=90,
                        fill=self._rf_bg, outline=self._rf_border,
                        tags="bg")
        self.create_arc(0, h - 2 * r, 2 * r, h, start=180, extent=90,
                        fill=self._rf_bg, outline=self._rf_border,
                        tags="bg")
        self.create_arc(w - 2 * r, h - 2 * r, w, h, start=270, extent=90,
                        fill=self._rf_bg, outline=self._rf_border,
                        tags="bg")
        # Bords horizontaux
        self.create_rectangle(r, 0, w - r, h, fill=self._rf_bg,
                              outline="", tags="bg")
        # Bords verticaux
        self.create_rectangle(0, r, w, h - r, fill=self._rf_bg,
                              outline="", tags="bg")
        # Trait de bordure haut/bas
        self.create_line(r, 0, w - r, 0, fill=self._rf_border, tags="bg")
        self.create_line(r, h - 1, w - r, h - 1, fill=self._rf_border,
                        tags="bg")
        # Trait de bordure gauche/droite
        self.create_line(0, r, 0, h - r, fill=self._rf_border, tags="bg")
        self.create_line(w - 1, r, w - 1, h - r, fill=self._rf_border,
                        tags="bg")
        # Remonter le inner au-dessus du fond
        self.tag_lower("bg")
        # Ajuster la taille du inner
        self.itemconfigure(self._window_id, width=w - 2, height=h - 2)
        self.coords(self._window_id, 1, 1)


# ── Utility ──────────────────────────────────────────────────────

def label(parent: tk.Widget, text: str, style: str = "normal",
          **kw) -> tk.Label:
    """CC=4 — Factory label stylé. style: normal|med|dim|accent|mono."""
    styles = {
        "normal": (T.TEXT,     T.F_LABEL),
        "med":    (T.TEXT_MED, T.F_CAPTION),
        "dim":    (T.TEXT_DIM, T.F_CAPTION),
        "accent": (T.C_AMB,    T.F_LABEL),
        "mono":   (T.TEXT,     T.F_MONO_MD),
    }
    fg, font = styles.get(style, styles["normal"])
    return tk.Label(parent, text=text, bg=parent.cget("bg"),
                    fg=fg, font=font, **kw)
