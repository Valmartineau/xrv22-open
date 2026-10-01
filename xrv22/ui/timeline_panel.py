"""
xr200/ui/timeline_panel.py
───────────────────────────
Timeline Gantt multi-pistes avec drag-drop.

Règles CC ≤ 15 — 5 fonctions atomiques drag-drop :
  _on_drag_start(event)                CC ≤ 4
  _on_drag_motion(event)               CC ≤ 3
  _on_drag_snap(x_px, px_per_ms)       CC ≤ 2  (pure)
  _on_drag_collision_check(eid, start) CC ≤ 5
  _on_drag_end(event)                  CC ≤ 6

Règle canvas :
  - Tags par piste (track_<id>) et par événement (event_<id>)
  - JAMAIS delete('all')
  - Seul le curseur redessiné à chaque tick (tag: "cursor")

Performance :
  - Rendu complet uniquement sur mutation du modèle
  - Tick 50ms → redraw curseur seulement
"""
from __future__ import annotations

import json
import tkinter as tk
import uuid
from tkinter import ttk, messagebox, simpledialog, filedialog
from typing import Dict, List, Optional, Tuple

from xrv22.theme import theme as T
from xrv22.timeline.timeline_model import TimelineModel
from xrv22.timeline.timeline_event import (
    TimelineEvent, EventType, EventState,
    make_move_event, make_wait_event, make_arduino_event, make_sensor_wait_event
)
from xrv22.timeline.timeline_track import TimelineTrack
from xrv22.core.execution_engine import engine
from xrv22.core.event_scheduler import SchedulerState
from xrv22.robots.robot_registry import registry, ROBOT_COLORS
from xrv22.library.library_manager import library
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("UI.Timeline")


def _robot_display(rid: str) -> str:
    """Nom d'affichage du robot (comme la sidebar)."""
    rcfg = library.get_robot(rid)
    name = rcfg.name if rcfg and rcfg.name else rid
    master = " ★" if rid == registry.master_id else ""
    return f"{name}{master}"


class _RobotSelector(tk.Frame):
    """Sélecteur robot custom avec cartes colorées (contourne les limites macOS)."""

    def __init__(self, parent, var: tk.StringVar, choices: list,
                 colors: Dict[str, str], width: int = 20) -> None:
        super().__init__(parent, bg=T.SURFACE, highlightthickness=1,
                         highlightbackground=T.BORDER, cursor="hand2")
        self._var = var
        self._choices = choices
        self._colors = colors
        self._width = width
        self._popup = None

        # Bouton principal
        self._label = tk.Label(self, text="", bg=T.SURFACE, fg=T.TEXT,
                               anchor="w", padx=6, pady=3, cursor="hand2")
        self._label.pack(side="left", fill="x", expand=True)
        self._arrow = tk.Label(self, text="▾", bg=T.SURFACE, fg=T.TEXT_DIM,
                               padx=4, pady=3, cursor="hand2")
        self._arrow.pack(side="right")

        for w in (self, self._label, self._arrow):
            w.bind("<Button-1>", self._toggle_popup)

        var.trace_add("write", self._on_var_changed)
        self._on_var_changed()

    def _on_var_changed(self, *_args) -> None:
        val = self._var.get()
        c = self._colors.get(val, T.TEXT)
        rt = T.robot_theme(c)
        display = _robot_display(val)
        self._label.configure(text=display, fg=c, bg=rt["bg"])
        self._arrow.configure(bg=rt["bg"], fg=c)
        self.configure(bg=rt["bg"], highlightbackground=c)

    def _toggle_popup(self, event=None) -> None:
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None
            return
        self._show_popup()

    def _show_popup(self) -> None:
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.geometry(f"+{x}+{y}")
        popup.configure(bg=T.BORDER)
        self._popup = popup

        for ch in self._choices:
            c = self._colors.get(ch, T.TEXT)
            rt = T.robot_theme(c)
            display = _robot_display(ch)
            row = tk.Frame(popup, bg=rt["bg"], cursor="hand2")
            row.pack(fill="x", padx=1, pady=1)
            tk.Frame(row, bg=c, width=4).pack(side="left", fill="y")
            lbl = tk.Label(row, text=f"  {display}", bg=rt["bg"], fg=c,
                           anchor="w", padx=6, pady=4, cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            for w in (row, lbl):
                w.bind("<Enter>", lambda e, r=row, cl=c: r.configure(bg=cl))
                w.bind("<Enter>", lambda e, r=row, l=lbl, cl=c:
                       (r.configure(bg=cl), l.configure(bg=cl, fg=T.BG)), add="+")
                w.bind("<Leave>", lambda e, r=row, l=lbl, rt_=rt, cl=c:
                       (r.configure(bg=rt_["bg"]), l.configure(bg=rt_["bg"], fg=cl)))
                w.bind("<Button-1>", lambda e, v=ch: self._select(v))

        popup.bind("<FocusOut>", lambda e: self._close_popup())
        popup.focus_set()

    def _select(self, value: str) -> None:
        self._var.set(value)
        self._close_popup()

    def _close_popup(self) -> None:
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
            self._popup = None


def _styled_option_menu(parent, var: tk.StringVar, choices: list,
                        width: int = 20,
                        colors: Optional[Dict[str, str]] = None,
                        robot_style: bool = False) -> tk.Widget:
    """Crée un sélecteur stylé dark theme.
    robot_style=True : cartes colorées custom (contourne limites macOS).
    Sinon : OptionMenu standard."""
    if robot_style and colors:
        return _RobotSelector(parent, var, choices, colors, width)
    om = tk.OptionMenu(parent, var, *choices)
    om.configure(bg=T.SURFACE, fg=T.TEXT,
                 activebackground=T.SURFACE_HI, activeforeground=T.TEXT,
                 highlightthickness=0, width=width, anchor="w")
    return om

PX_PER_SEC    = T.TRACK_LABEL_W  # alias pour clarté
SNAP_MS       = 250              # snap au 1/4 de seconde
HEADER_H      = T.HEADER_H
TRACK_H       = T.TRACK_H
LABEL_W       = T.TRACK_LABEL_W
BLOCK_PAD     = T.BLOCK_PADDING
MIN_BLOCK_W   = T.MIN_BLOCK_W


class TimelinePanel(tk.Frame):
    """
    Panneau Timeline Gantt.
    CC max par méthode : 8 (sauf drag-drop documenté séparément).
    """

    def __init__(self, parent: tk.Widget,
                 model: TimelineModel,
                 on_after) -> None:
        super().__init__(parent, bg=T.BG_DEEP)
        self._model = model
        self._after = on_after
        self._px_per_ms: float = 0.06    # 60px/s = 0.06px/ms

        # Drag-drop state — JAMAIS modifié pendant _on_drag_motion
        self._drag: Dict = {
            "active": False,
            "event_id": "",
            "track_id": "",
            "origin_ms": 0,
            "anchor_x": 0,
            "ghost_ids": [],    # items canvas temporaires
        }

        # Drag-drop pistes (réordonnement vertical)
        self._track_drag: Dict = {
            "active": False,
            "track_id": "",
            "origin_index": 0,
            "anchor_y": 0,
            "ghost_id": None,
        }

        self._playhead_ms: int = 0
        self._selected_id: str = ""

        self._build()
        self._subscribe()
        self._sync_robot_tracks()
        self._restore_scenario()

    # ── Construction ─────────────────────────────────────────────

    def _build(self) -> None:
        """CC=4 — Assemble le panneau."""
        self._build_scenario_bar()
        self._build_toolbar()
        self._build_zoom_bar()
        self._build_canvas_area()

    def _build_scenario_bar(self) -> None:
        """Sélecteur de scénario + boutons — identique V17."""
        bar = tk.Frame(self, bg=T.SURFACE_HI, pady=T.PAD_XS)
        bar.pack(fill="x")

        tk.Label(bar, text="Scénario :", bg=T.SURFACE_HI,
                 fg=T.TEXT_MED, font=T.F_CONTROL).pack(side="left", padx=(T.PAD_MD, T.PAD_XS))

        self._scenario_var = tk.StringVar(value="default")
        self._scenario_combo = ttk.Combobox(bar, textvariable=self._scenario_var,
                                             width=16, state="readonly",
                                             values=["default"])
        self._scenario_combo.pack(side="left", padx=(0, T.PAD_XS))
        self._scenario_combo.bind("<<ComboboxSelected>>", self._on_scenario_selected)

        ttk.Button(bar, text="➕", width=3,
                   command=self._new_scenario).pack(side="left", padx=1)
        ttk.Button(bar, text="🗑", width=3,
                   command=self._del_scenario).pack(side="left", padx=1)

        # Contrôle lecture (côté droit de la barre scénario)
        self._status_var = tk.StringVar(value="Prête")
        tk.Label(bar, textvariable=self._status_var,
                 bg=T.SURFACE_HI, fg=T.TEXT_MED, font=T.F_CAPTION).pack(
                 side="right", padx=T.PAD_MD)
        ttk.Button(bar, text="⏹️ Stop",
                   command=self._cmd_stop).pack(side="right", padx=2)
        ttk.Button(bar, text="▶️ Lecture",
                   command=self._cmd_play).pack(side="right", padx=2)

    def _build_toolbar(self) -> None:
        """CC=5 — Barre d'outils V17 complète."""
        bar = tk.Frame(self, bg=T.SURFACE, pady=T.PAD_XS)
        bar.pack(fill="x")

        # Ajout d'étapes
        ttk.Button(bar, text="➕ Ajouter Pose",
                   command=lambda: self._add_event_dialog(EventType.MOVE)).pack(side="left", padx=2, pady=4)
        ttk.Button(bar, text="⏱️ Ajouter Pause",
                   command=lambda: self._add_event_dialog(EventType.WAIT)).pack(side="left", padx=2)
        ttk.Button(bar, text="📡 Capteur Arduino",
                   command=lambda: self._add_event_dialog(EventType.SENSOR_WAIT)).pack(side="left", padx=2)
        ttk.Button(bar, text="🔧 Action Arduino",
                   command=lambda: self._add_event_dialog(EventType.ARDUINO_ACTION)).pack(side="left", padx=2)
        ttk.Button(bar, text="📁 Importer Suite",
                   command=self._import_suite).pack(side="left", padx=2)

        tk.Frame(bar, bg=T.BORDER, width=1).pack(side="left", fill="y", padx=8, pady=4)

        ttk.Button(bar, text="✏️ Modifier",
                   command=self._edit_selected_event).pack(side="left", padx=2)
        ttk.Button(bar, text="🗑️ Supprimer",
                   command=self._del_selected_event).pack(side="left", padx=2)

        tk.Frame(bar, bg=T.BORDER, width=1).pack(side="left", fill="y", padx=8, pady=4)

        ttk.Button(bar, text="📄 Exporter",
                   command=self._export).pack(side="left", padx=2)

        # Timer
        self._timer_var = tk.StringVar(value="00:00.000")
        tk.Label(bar, textvariable=self._timer_var,
                 bg=T.SURFACE, fg=T.C_AMB, font=T.F_MONO_LG).pack(
                 side="right", padx=T.PAD_MD)

    def _build_zoom_bar(self) -> None:
        """CC=1 — Barre de zoom en bas du panneau timeline."""
        bar = tk.Frame(self, bg=T.SURFACE, pady=2)
        bar.pack(side="bottom", fill="x")
        for lbl, cmd in [("🔍−", self._zoom_out), ("🔍+", self._zoom_in)]:
            ttk.Button(bar, text=lbl, width=4, command=cmd).pack(side="left", padx=2)
        self._zoom_lbl = tk.Label(bar, text="Zoom: 100%",
                                  bg=T.SURFACE, fg=T.TEXT_MED, font=T.F_CAPTION)
        self._zoom_lbl.pack(side="left", padx=T.PAD_XS)

    def _build_canvas_area(self) -> None:
        """CC=4 — Construit la zone canvas avec scrollbars + panneau éditeur inline."""
        # Wrapper principal (grid : éditeur au-dessus, canvas en dessous)
        self._main_wrapper = tk.Frame(self, bg=T.BG_DEEP)
        self._main_wrapper.pack(fill="both", expand=True)
        self._main_wrapper.columnconfigure(0, weight=1)
        self._main_wrapper.rowconfigure(0, weight=0)  # éditeur (hauteur fixe)
        self._main_wrapper.rowconfigure(1, weight=1)  # canvas (expand)

        # Zone canvas
        canvas_frame = tk.Frame(self._main_wrapper, bg=T.BG_DEEP)
        canvas_frame.grid(row=1, column=0, sticky="nsew")

        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal")
        h_scroll.pack(side="bottom", fill="x")
        v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical")
        v_scroll.pack(side="right", fill="y")

        self._canvas = tk.Canvas(
            canvas_frame,
            bg=T.BG_DEEP,
            highlightthickness=0,
            xscrollcommand=h_scroll.set,
            yscrollcommand=v_scroll.set,
        )
        self._canvas.pack(fill="both", expand=True)

        h_scroll.config(command=self._canvas.xview)
        v_scroll.config(command=self._canvas.yview)

        # Panneau éditeur de suite inline (droite, masqué par défaut)
        self._editor_panel: Optional[_SuiteEditorPanel] = None

        self._canvas.bind("<Button-1>",      self._on_drag_start)
        self._canvas.bind("<B1-Motion>",     self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)
        self._canvas.bind("<Button-3>",      self._on_right_click)
        # Scroll horizontal molette (Shift+molette ou trackpad H)
        self._canvas.bind("<Shift-MouseWheel>", self._on_h_scroll)
        # Zoom molette (Cmd/Ctrl + molette) — comme logiciel de montage
        self._canvas.bind("<Command-MouseWheel>", self._on_zoom_scroll)
        self._canvas.bind("<Control-MouseWheel>", self._on_zoom_scroll)
        # Scroll vertical normal
        self._canvas.bind("<MouseWheel>", self._on_v_scroll)
        # Navigation clavier
        self._canvas.config(takefocus=True)
        self._canvas.bind("<Delete>",        lambda e: self._del_selected_event())
        self._canvas.bind("<BackSpace>",     lambda e: self._del_selected_event())
        self._canvas.bind("<Return>",        lambda e: self._edit_selected_event())
        self._canvas.bind("<F2>",            lambda e: self._edit_selected_event())
        # Raccourcis zoom clavier (+ / -)
        self._canvas.bind("<plus>",          lambda e: self._zoom_in())
        self._canvas.bind("<minus>",         lambda e: self._zoom_out())
        self._canvas.bind("<equal>",         lambda e: self._zoom_in())   # = sans shift = +

    # ── Rendu canvas ─────────────────────────────────────────────

    def redraw(self) -> None:
        """CC=4 — Rendu complet. Appelé uniquement sur mutation modèle."""
        self._canvas.delete("all")
        tracks = self._model.ordered_tracks()
        n = len(tracks)
        total_ms = max(self._model.duration_ms(), 30_000)
        canvas_w = LABEL_W + int(total_ms * self._px_per_ms) + 200
        canvas_h = HEADER_H + n * TRACK_H + 40

        self._canvas.config(scrollregion=(0, 0, canvas_w, canvas_h))

        self._draw_header(canvas_w)
        self._draw_grid(total_ms, canvas_w, n)
        self._draw_track_backgrounds(tracks, canvas_w)
        self._draw_blocks(tracks)
        self._draw_playhead(canvas_h)

    def _draw_header(self, canvas_w: int) -> None:
        """CC=2 — Entête horizontale (temps)."""
        self._canvas.create_rectangle(
            0, 0, canvas_w, HEADER_H,
            fill=T.SURFACE, outline=T.BORDER, tags="header")
        self._canvas.create_text(
            LABEL_W // 2, HEADER_H // 2,
            text="Piste", fill=T.TEXT_DIM, font=T.F_CAPTION, tags="header")

    def _draw_grid(self, total_ms: int, canvas_w: int, n_tracks: int) -> None:
        """CC=5 — Grille temporelle verticale."""
        grid_step_ms = 5_000  # 5s entre colonnes
        canvas_h = HEADER_H + n_tracks * TRACK_H + 40
        t = 0
        while t <= total_ms:
            x = LABEL_W + int(t * self._px_per_ms)
            major = (t % 20_000 == 0)
            color = T.BORDER_HI if major else T.BORDER
            self._canvas.create_line(x, HEADER_H, x, canvas_h,
                                      fill=color, tags="grid")
            secs = t // 1000
            mins = secs // 60
            lbl = f"{mins}:{secs % 60:02d}"
            self._canvas.create_text(x + 3, HEADER_H // 2,
                                      text=lbl, fill=T.TEXT_DIM,
                                      font=T.F_CAPTION, anchor="w", tags="grid")
            t += grid_step_ms

    def _draw_track_backgrounds(self, tracks, canvas_w: int) -> None:
        """CC=5 — Fond et labels des pistes."""
        for i, track in enumerate(tracks):
            y1 = HEADER_H + i * TRACK_H
            y2 = y1 + TRACK_H
            bg = T.SURFACE if i % 2 == 0 else T.BG_DEEP
            self._canvas.create_rectangle(
                0, y1, canvas_w, y2,
                fill=bg, outline=T.BORDER,
                tags=f"track_bg_{track.track_id}")

            # Label piste (draggable)
            indicator = tk.Frame(self._canvas, bg=track.color, width=4, height=TRACK_H - 8)
            self._canvas.create_window(4, y1 + 4, anchor="nw", window=indicator)
            # Icône grip (≡) pour indiquer le drag
            self._canvas.create_text(
                LABEL_W - 10, y1 + TRACK_H // 2,
                text="≡", fill=T.TEXT_DIM, font=(T.FONT_MONO, 12),
                anchor="e", tags=f"track_label_{track.track_id}")
            self._canvas.create_text(
                14, y1 + TRACK_H // 2,
                text=track.label, fill=track.color,
                font=T.F_CONTROL, anchor="w",
                tags=f"track_label_{track.track_id}")

    def _draw_blocks(self, tracks) -> None:
        """CC=6 — Dessine les blocs : suites en bloc global, autres individuels."""
        for i, track in enumerate(tracks):
            y1 = HEADER_H + i * TRACK_H + BLOCK_PAD
            y2 = HEADER_H + (i + 1) * TRACK_H - BLOCK_PAD
            events = track.all_events()

            # Grouper par suite_group_id
            groups: Dict[str, List[TimelineEvent]] = {}
            standalone: List[TimelineEvent] = []
            for evt in events:
                gid = evt.get_param("suite_group_id", "")
                if gid:
                    groups.setdefault(gid, []).append(evt)
                else:
                    standalone.append(evt)

            # Dessiner les blocs suite (global + positions en surcouche)
            for gid, grp in groups.items():
                self._draw_suite_block(grp, y1, y2, track.color)

            # Dessiner les événements individuels
            for evt in standalone:
                self._draw_block(evt, y1, y2, track.color)

    def _draw_suite_block(self, events: List[TimelineEvent],
                          y1: int, y2: int, color: str) -> None:
        """CC=7 — Dessine une suite : bande pleine colorée + positions en surcouche."""
        if not events:
            return
        events = sorted(events, key=lambda e: e.start_ms)
        suite_name = events[0].get_param("suite_name", "Suite")
        track_id = events[0].track_id

        # Coordonnées globales de la bande
        x_start = LABEL_W + int(events[0].start_ms * self._px_per_ms)
        x_end = LABEL_W + int(events[-1].end_ms * self._px_per_ms)
        x_end = max(x_end, x_start + MIN_BLOCK_W)

        selected = any(e.event_id == self._selected_id for e in events)
        group_tag = f"suite_{events[0].get_param('suite_group_id', '')}"

        # Couleur pleine de la bande selon état
        fill = self._suite_block_color(events, color)
        outline = T.C_AMB if selected else color

        # ── Bande pleine arrondie (fond coloré sur toute la hauteur) ──
        # Tag bg_ pour chaque événement du groupe (rafraîchissement état live)
        bg_tags = tuple(f"bg_{e.event_id}" for e in events)
        self._round_rect(
            x_start, y1, x_end, y2, r=8,
            fill=fill, outline=outline, width=2 if selected else 0,
            tags=(group_tag, f"track_{track_id}") + bg_tags)

        # ── Label suite (en haut à gauche, texte clair) ──
        self._canvas.create_text(
            x_start + 6, y1 + 9,
            text=f"📁 {suite_name}", fill=T.TEXT,
            font=T.F_CAPTION, anchor="w",
            tags=(group_tag, f"track_{track_id}"))

        # ── Sous-blocs positions + délais matérialisés ──
        inner_y1 = y1 + 16
        inner_y2 = y2 - 1
        # Overlay sombre sur bande vive (positions = assombrissement léger)
        pos_fill = self._dim_color(color, 0.45)

        for i, evt in enumerate(events):
            ex1 = LABEL_W + int(evt.start_ms * self._px_per_ms)
            ew = max(MIN_BLOCK_W, int(evt.duration_ms * self._px_per_ms))
            ex2 = ex1 + ew
            tag = f"event_{evt.event_id}"

            # ── Délai entre positions (zone hachurée) ──
            if i > 0:
                prev = events[i - 1]
                gap_x1 = LABEL_W + int(prev.end_ms * self._px_per_ms)
                gap_x2 = ex1
                if gap_x2 > gap_x1 + 2:
                    # Fond du délai (plus sombre)
                    self._canvas.create_rectangle(
                        gap_x1, inner_y1, gap_x2, inner_y2,
                        fill=self._dim_color(color, 0.15), outline="",
                        tags=(group_tag, f"track_{track_id}"))
                    # Hachures diagonales pour signifier le délai
                    for hx in range(int(gap_x1) + 4, int(gap_x2), 6):
                        self._canvas.create_line(
                            hx, inner_y2, min(hx + 8, gap_x2), inner_y1,
                            fill=self._dim_color(color, 0.4), width=1,
                            tags=(group_tag, f"track_{track_id}"))

            # ── Fond position arrondi (léger rehaut sur la bande) ──
            self._round_rect(
                ex1, inner_y1, ex2, inner_y2, r=5,
                fill=pos_fill, outline="",
                tags=(tag, group_tag, f"track_{track_id}"))

            # Séparateur vertical
            if i > 0:
                self._canvas.create_line(
                    ex1, y1 + 2, ex1, inner_y2,
                    fill=outline, width=1,
                    tags=(group_tag, f"track_{track_id}"))

            # Surbrillance si sélectionné
            if evt.event_id == self._selected_id:
                self._round_rect(
                    ex1 + 1, inner_y1, ex2 - 1, inner_y2, r=5,
                    fill="", outline=T.C_AMB, width=2,
                    tags=(tag, group_tag, f"track_{track_id}"))

            # Label position
            pos_mid_y = (inner_y1 + inner_y2) // 2
            self._canvas.create_text(
                ex1 + 4, pos_mid_y,
                text=evt.label, fill=T.TEXT,
                font=T.F_CAPTION, anchor="w",
                width=max(ew - 8, 8),
                tags=(tag, group_tag, f"track_{track_id}"))

    def _draw_block(self, evt: TimelineEvent, y1: int, y2: int,
                    color: str) -> None:
        """CC=6 — Dessine un seul bloc événement (standalone)."""
        x1 = LABEL_W + int(evt.start_ms * self._px_per_ms)
        w = max(MIN_BLOCK_W, int(evt.duration_ms * self._px_per_ms))
        x2 = x1 + w
        mid_y = (y1 + y2) // 2
        tag = f"event_{evt.event_id}"

        alpha_bg = self._block_color(evt, color)
        border = T.C_AMB if evt.event_id == self._selected_id else color

        # Icône selon type
        icon = self._event_icon(evt.event_type)
        label = f"{icon} {evt.label}" if icon else evt.label

        self._round_rect(x1, y1, x2, y2, r=7,
                         fill=alpha_bg, outline=border,
                         width=2 if evt.event_id == self._selected_id else 1,
                         tags=(tag, f"bg_{evt.event_id}", f"track_{evt.track_id}"))
        self._canvas.create_text(x1 + 6, mid_y,
                                  text=label, fill=T.TEXT,
                                  font=T.F_CONTROL, anchor="w",
                                  width=max(w - 12, 10),
                                  tags=(tag, f"track_{evt.track_id}"))

    @staticmethod
    def _event_icon(event_type: str) -> str:
        """Retourne l'icône associée au type d'événement."""
        return {
            EventType.WAIT: "⏱",
            EventType.SENSOR_WAIT: "📡",
            EventType.ARDUINO_ACTION: "⚡",
            EventType.SYNC_MARKER: "🔗",
            EventType.PAUSE: "⏸",
        }.get(event_type, "")

    def _block_color(self, evt: TimelineEvent, default: str) -> str:
        """CC=5 — Couleur de fond du bloc selon l'état."""
        state_map = {
            EventState.RUNNING: T.C_AMB_DIM2,
            EventState.DONE:    T.C_OK_DIM,
            EventState.ERROR:   T.C_ERR_DIM,
            EventState.SKIPPED: T.SURFACE,
        }
        return state_map.get(evt.state, T.SURFACE_HI)

    def _round_rect(self, x1: int, y1: int, x2: int, y2: int,
                    r: int = 6, **kw) -> int:
        """CC=1 — Dessine un rectangle arrondi sur le canvas."""
        points = [
            x1 + r, y1, x2 - r, y1,
            x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2,
            x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1,
        ]
        return self._canvas.create_polygon(points, smooth=True, **kw)

    def _suite_block_color(self, events: List[TimelineEvent],
                           track_color: str) -> str:
        """CC=4 — Couleur pleine de la bande suite selon l'état global."""
        if any(e.state == EventState.ERROR for e in events):
            return T.C_ERR_DIM
        if any(e.state == EventState.RUNNING for e in events):
            return T.C_AMB_DIM2
        if all(e.state == EventState.DONE for e in events):
            return T.C_OK_DIM
        # Idle → couleur vive du track (bande pleine colorée)
        return self._dim_color(track_color, 0.7)

    @staticmethod
    def _dim_color(hex_color: str, factor: float) -> str:
        """Retourne une version assombrie d'une couleur hex."""
        try:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"
        except (ValueError, IndexError):
            return T.BG_DEEP

    def _draw_playhead(self, canvas_h: int) -> None:
        """CC=2 — Dessine le curseur de lecture."""
        self._canvas.delete("cursor")
        x = LABEL_W + int(self._playhead_ms * self._px_per_ms)
        self._canvas.create_line(x, 0, x, canvas_h,
                                  fill=T.C_ERR, width=2, tags="cursor")
        self._canvas.create_polygon(
            x - 6, 0, x + 6, 0, x, 10,
            fill=T.C_ERR, outline="", tags="cursor")

    # ── Drag-drop (5 fonctions atomiques CC ≤ 15) ────────────────

    def _on_drag_start(self, event: tk.Event) -> None:
        """
        CC=5 — Identifie le bloc sous le curseur ou un label de piste.
        Zone gauche (< LABEL_W) = drag de piste. Zone droite = drag d'événement.
        NE modifie PAS le modèle.
        """
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)

        # ── Drag de piste (clic dans la zone labels) ──
        if cx < LABEL_W and cy > HEADER_H:
            track_index = int((cy - HEADER_H) // TRACK_H)
            tracks = self._model.ordered_tracks()
            if 0 <= track_index < len(tracks):
                self._track_drag = {
                    "active": True,
                    "track_id": tracks[track_index].track_id,
                    "origin_index": track_index,
                    "anchor_y": cy,
                    "ghost_id": None,
                }
                self._canvas.config(cursor="fleur")
                self._track_drag_draw_ghost(track_index)
            return

        # ── Drag d'événement (clic dans la zone timeline) ──
        item = self._canvas.find_closest(cx, cy)
        if not item:
            return
        tags = self._canvas.gettags(item[0])
        event_id = self._extract_event_tag(tags)
        if not event_id:
            return

        evt = self._model.get_event(event_id)
        if evt is None:
            return

        # Si l'événement fait partie d'une suite, on draggue tout le groupe
        gid = evt.get_param("suite_group_id", "")
        if gid:
            siblings = self._find_suite_events(gid)
            group_ids = [(e.event_id, e.start_ms) for e in siblings]
        else:
            group_ids = [(event_id, evt.start_ms)]

        self._drag = {
            "active":    True,
            "event_id":  event_id,
            "track_id":  evt.track_id,
            "origin_ms": evt.start_ms,
            "anchor_x":  cx,
            "ghost_ids": [],
            "group":     group_ids,  # [(eid, origin_ms), ...]
        }
        self._selected_id = event_id
        self._show_suite_editor_if_needed(evt)

    def _on_drag_motion(self, event: tk.Event) -> None:
        """
        CC=4 — Déplace le fantôme visuel uniquement.
        NE JAMAIS modifier le modèle ici.
        """
        # ── Drag de piste (vertical) ──
        if self._track_drag["active"]:
            cy = self._canvas.canvasy(event.y)
            target_index = int((cy - HEADER_H) // TRACK_H)
            target_index = max(0, min(target_index,
                               len(self._model.ordered_tracks()) - 1))
            self._track_drag_draw_ghost(target_index)
            return

        if not self._drag["active"]:
            return
        cx = self._canvas.canvasx(event.x)
        delta_px = cx - self._drag["anchor_x"]
        delta_ms = int(delta_px / self._px_per_ms)

        # Déplace visuellement tous les événements du groupe
        for eid, origin_ms in self._drag["group"]:
            new_start = max(0, origin_ms + delta_ms)
            tag = f"event_{eid}"
            items = self._canvas.find_withtag(tag)
            if not items:
                continue
            cur_x = self._canvas.coords(items[0])[0]
            target_x = LABEL_W + int(new_start * self._px_per_ms)
            self._canvas.move(tag, target_x - cur_x, 0)

    def _on_drag_snap(self, x_px: float, px_per_ms: float) -> int:
        """
        CC=2 — Calcule la position snappée. Fonction pure, sans effet de bord.
        """
        raw_ms = max(0, x_px / px_per_ms)
        return int(round(raw_ms / SNAP_MS) * SNAP_MS)

    def _on_drag_collision_check(self, event_id: str,
                                  new_start_ms: int) -> bool:
        """
        CC=5 — Vérifie si le déplacement est valide (pas de collision).
        Retourne True si le move est autorisé.
        """
        evt = self._model.get_event(event_id)
        if evt is None:
            return False
        track = self._model.get_track(evt.track_id)
        if track is None:
            return False
        end_ms = new_start_ms + evt.duration_ms
        for other in track.all_events():
            if other.event_id == event_id:
                continue
            if new_start_ms < other.end_ms and end_ms > other.start_ms:
                return False
        return True

    def _on_drag_collision_check_group(self, event_id: str,
                                          new_start_ms: int,
                                          group: list) -> bool:
        """CC=5 — Collision check ignorant les autres membres du groupe."""
        evt = self._model.get_event(event_id)
        if evt is None:
            return False
        track = self._model.get_track(evt.track_id)
        if track is None:
            return False
        group_ids = {eid for eid, _ in group}
        end_ms = new_start_ms + evt.duration_ms
        for other in track.all_events():
            if other.event_id in group_ids:
                continue
            if new_start_ms < other.end_ms and end_ms > other.start_ms:
                return False
        return True

    def _on_drag_end(self, event: tk.Event) -> None:
        """
        CC=7 — Valide et commit le déplacement dans le modèle, ou rollback.
        C'est le SEUL endroit où le modèle est modifié pour le drag-drop.
        """
        # ── Commit drag de piste ──
        if self._track_drag["active"]:
            cy = self._canvas.canvasy(event.y)
            target_index = int((cy - HEADER_H) // TRACK_H)
            target_index = max(0, min(target_index,
                               len(self._model.ordered_tracks()) - 1))
            self._model.move_track(self._track_drag["track_id"], target_index)
            self._track_drag["active"] = False
            self._canvas.config(cursor="")
            self.redraw()
            return

        if not self._drag["active"]:
            return

        cx = self._canvas.canvasx(event.x)
        delta_px = cx - self._drag["anchor_x"]
        delta_ms_raw = delta_px / self._px_per_ms

        # Snap le delta sur la grille
        anchor_origin = self._drag["origin_ms"]
        raw_start = anchor_origin + delta_ms_raw
        snapped_ms = self._on_drag_snap(
            LABEL_W + int(raw_start * self._px_per_ms) - LABEL_W,
            self._px_per_ms,
        )
        delta_snapped = snapped_ms - anchor_origin

        # Vérifier la validité pour tous les événements du groupe
        group = self._drag["group"]
        can_move = True
        for eid, origin_ms in group:
            new_ms = max(0, origin_ms + delta_snapped)
            if not self._on_drag_collision_check_group(eid, new_ms, group):
                can_move = False
                break

        if can_move and delta_snapped != 0:
            for eid, origin_ms in group:
                new_ms = max(0, origin_ms + delta_snapped)
                ok, msg = self._model.move_event(eid, new_ms)
                if not ok:
                    _LOG.warning("Drag suite commit échoué pour %s : %s", eid, msg)
        elif not can_move:
            _LOG.debug("Drag suite annulé : collision")

        # Reset drag state et redraw
        self._drag["active"] = False
        self.redraw()

    # ── Drag piste — feedback visuel ────────────────────────────

    def _track_drag_draw_ghost(self, target_index: int) -> None:
        """CC=2 — Dessine l'indicateur d'insertion entre les pistes."""
        self._canvas.delete("track_ghost")
        canvas_w = self._canvas.winfo_width()
        y = HEADER_H + target_index * TRACK_H
        # Ligne d'insertion horizontale vive
        self._canvas.create_line(
            0, y, canvas_w, y,
            fill=T.C_AMB, width=3, tags="track_ghost")
        # Flèche indicatrice à gauche
        self._canvas.create_polygon(
            0, y - 6, 10, y, 0, y + 6,
            fill=T.C_AMB, outline="", tags="track_ghost")

    # ── Interactions ─────────────────────────────────────────────

    def _on_double_click(self, event: tk.Event) -> None:
        """CC=4 — Ouvre un dialog d'édition sur double-clic."""
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        item = self._canvas.find_closest(cx, cy)
        if not item:
            return
        tags = self._canvas.gettags(item[0])
        event_id = self._extract_event_tag(tags)
        if event_id:
            self._edit_event_dialog(event_id)

    def _on_right_click(self, event: tk.Event) -> None:
        """CC=5 — Menu contextuel sur clic droit."""
        cx = self._canvas.canvasx(event.x)
        cy = self._canvas.canvasy(event.y)
        item = self._canvas.find_closest(cx, cy)
        if not item:
            return
        tags = self._canvas.gettags(item[0])
        event_id = self._extract_event_tag(tags)
        if not event_id:
            return

        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT)
        menu.add_command(label="✏️  Éditer",
                         command=lambda: self._edit_event_dialog(event_id))
        menu.add_command(label="🗑  Supprimer",
                         command=lambda: self._delete_event(event_id))
        menu.tk_popup(event.x_root, event.y_root)

    # ── Commandes transport ──────────────────────────────────────

    def _cmd_play(self) -> None:
        """CC=3 — Démarre l'exécution."""
        engine.set_model(self._model)
        ok = engine.play()
        if not ok:
            messagebox.showwarning("Timeline", "Impossible de démarrer.\n"
                "Vérifiez l'état des robots.", parent=self)

    def _cmd_pause(self) -> None:
        engine.pause()

    def _cmd_stop(self) -> None:
        engine.stop()

    def _zoom_in(self) -> None:
        """CC=2 — Augmente le zoom."""
        self._zoom_at_cursor(1.3)

    def _zoom_out(self) -> None:
        """CC=2 — Réduit le zoom."""
        self._zoom_at_cursor(1 / 1.3)

    def _zoom_at_cursor(self, factor: float, anchor_x: int | None = None) -> None:
        """CC=4 — Zoom centré sur la position du curseur (comme un logiciel de montage)."""
        old_px = self._px_per_ms
        new_px = max(0.005, min(old_px * factor, 1.0))
        if new_px == old_px:
            return

        # Point d'ancrage : position visible actuelle (centre ou curseur souris)
        if anchor_x is None:
            # Centre de la vue visible
            x_frac = self._canvas.xview()
            anchor_frac = (x_frac[0] + x_frac[1]) / 2
        else:
            # Position souris en fraction du scrollregion
            sr = self._canvas.cget("scrollregion")
            if sr:
                parts = sr.split()
                total_w = float(parts[2]) if len(parts) >= 3 else 1
                anchor_frac = anchor_x / total_w if total_w > 0 else 0.5
            else:
                anchor_frac = 0.5

        # Calculer la position temporelle sous le curseur
        x_frac_view = self._canvas.xview()
        view_frac = anchor_frac
        time_at_anchor = (view_frac * self._total_canvas_w() - LABEL_W) / old_px

        self._px_per_ms = new_px
        self.redraw()
        pct = int(new_px / 0.06 * 100)
        self._zoom_lbl.config(text=f"Zoom: {pct}%")

        # Recaler pour que le même temps reste sous le curseur
        new_total_w = self._total_canvas_w()
        if new_total_w > 0:
            new_x = (LABEL_W + time_at_anchor * new_px) / new_total_w
            visible = x_frac_view[1] - x_frac_view[0]
            target = max(0.0, new_x - visible / 2)
            self._canvas.xview_moveto(target)

    def _total_canvas_w(self) -> float:
        """Largeur totale du scrollregion."""
        sr = self._canvas.cget("scrollregion")
        if sr:
            parts = sr.split()
            return float(parts[2]) if len(parts) >= 3 else 1
        return 1

    # ── Scroll & zoom molette ─────────────────────────────────────

    def _on_h_scroll(self, event: tk.Event) -> str:
        """Scroll horizontal : Shift + molette ou trackpad horizontal."""
        delta = -1 if event.delta > 0 else 1
        self._canvas.xview_scroll(delta * 3, "units")
        return "break"

    def _on_v_scroll(self, event: tk.Event) -> str:
        """Scroll vertical normal (molette sans modifier)."""
        # Sur macOS le trackpad envoie aussi des événements horizontaux
        # On scroll horizontalement par défaut sur la timeline (plus utile)
        delta = -1 if event.delta > 0 else 1
        self._canvas.xview_scroll(delta * 3, "units")
        return "break"

    def _on_zoom_scroll(self, event: tk.Event) -> str:
        """Zoom : Cmd/Ctrl + molette, centré sur la position de la souris."""
        # Position souris dans le canvas (coordonnées scrollées)
        cx = self._canvas.canvasx(event.x)
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom_at_cursor(factor, anchor_x=cx)
        return "break"

    def _on_scenario_selected(self, _event=None) -> None:
        """CC=2 — Handler sélection combo scénario."""
        name = self._scenario_var.get()
        if name == self._model.name:
            return
        self._save_current_scenario()
        self._load_scenario(name)

    def _new_scenario(self) -> None:
        """CC=4 — Crée un nouveau scénario (sauvegarde l'actuel + vide la timeline)."""
        name = simpledialog.askstring("Nouveau scénario", "Nom du scénario :", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        # Vérifie unicité
        existing = [s.name for s in library.list_scenarios()]
        if name in existing or name == "default":
            messagebox.showwarning("Nouveau scénario",
                                   f"Le scénario '{name}' existe déjà.", parent=self)
            return
        # Sauvegarder le scénario actuel avant de passer au nouveau
        self._save_current_scenario()
        # Créer le nouveau scénario vide (timeline_data vide = pistes sans événements)
        from xrv22.library.models import ScenarioModel
        scenario = ScenarioModel(name=name)
        library.save_scenario(scenario)
        # Charger le scénario vide (reconstruit les pistes robots sans événements)
        self._load_scenario(name)
        _LOG.info("Scénario '%s' créé", name)

    def _del_scenario(self) -> None:
        """CC=4 — Supprime le scénario sélectionné."""
        name = self._scenario_var.get()
        if name == "default":
            messagebox.showinfo("Supprimer scénario",
                                "Le scénario par défaut ne peut pas être supprimé.",
                                parent=self)
            return
        if not messagebox.askyesno("Supprimer scénario",
                                   f"Supprimer le scénario '{name}' ?",
                                   parent=self):
            return
        for s in library.list_scenarios():
            if s.name == name:
                library.delete_scenario(s.id)
                break
        # Repasser au default
        self._load_scenario("default")
        _LOG.info("Scénario '%s' supprimé", name)

    def _save_current_scenario(self) -> None:
        """CC=3 — Sauvegarde la timeline courante dans le scénario actif."""
        name = self._model.name
        tl_data = self._model.to_dict()
        if name == "default":
            # Le scénario default = fichier timeline.json classique
            library.save_timeline(tl_data)
        else:
            # Scénario nommé = stocké dans le ScenarioModel
            for s in library.list_scenarios():
                if s.name == name:
                    s.timeline_data = tl_data
                    library.save_scenario(s)
                    break

    def _load_scenario(self, name: str) -> None:
        """CC=5 — Charge un scénario depuis la library et remplace le modèle."""
        if name == "default":
            tl_data = library.get_timeline()
        else:
            tl_data = {}
            for s in library.list_scenarios():
                if s.name == name:
                    tl_data = s.timeline_data or {}
                    break
        # Reconstruire le modèle
        if tl_data and tl_data.get("tracks"):
            new_model = TimelineModel.from_dict(tl_data)
        else:
            new_model = TimelineModel(name=name)
        new_model.name = name
        # Synchroniser les pistes robots existantes
        existing_tracks = {t.track_id for t in new_model.ordered_tracks()}
        for i, rid in enumerate(registry.ids()):
            if rid not in existing_tracks:
                color = ROBOT_COLORS[i % len(ROBOT_COLORS)]
                new_model.add_robot_track(rid, f"Robot {rid}", color)
        # Remplacer le modèle dans le panel ET le moteur d'exécution
        self._model = new_model
        engine.set_model(new_model)
        bus.publish("timeline.model_replaced", {"model": new_model})
        # Mettre à jour le combo et redessiner
        self._scenario_var.set(name)
        self._refresh_scenario_combo()
        self.redraw()

    def _refresh_scenario_combo(self) -> None:
        """Met à jour la liste des scénarios dans le combo."""
        names = ["default"] + [s.name for s in library.list_scenarios() if s.name != "default"]
        self._scenario_combo.config(values=names)

    def _restore_scenario(self) -> None:
        """CC=3 — Restaure la timeline default depuis la library au démarrage."""
        self._refresh_scenario_combo()
        tl_data = library.get_timeline()
        if tl_data and tl_data.get("tracks"):
            restored = TimelineModel.from_dict(tl_data)
            restored.name = tl_data.get("name", "default")
            # Synchroniser pistes robots manquantes
            existing = {t.track_id for t in restored.ordered_tracks()}
            for i, rid in enumerate(registry.ids()):
                if rid not in existing:
                    color = ROBOT_COLORS[i % len(ROBOT_COLORS)]
                    restored.add_robot_track(rid, f"Robot {rid}", color)
            self._model = restored
            engine.set_model(restored)
            self._scenario_var.set(restored.name)
            self._after(100, self.redraw)

    def _import_suite(self) -> None:
        """CC=3 — Ouvre le dialog d'import de suite dans la timeline."""
        groups = {s.name: [st.get("position_name", "") for st in s.steps] for s in library.list_suites()}
        suite_names = [k for k in groups if k != "__ungrouped__" and groups[k]]
        if not suite_names:
            messagebox.showinfo("Importer Suite",
                                "Aucune suite disponible.\n"
                                "Créez d'abord une suite dans l'onglet Positions.",
                                parent=self)
            return
        dlg = _ImportSuiteDialog(self, suite_names, self._model)
        if dlg.imported:
            self.redraw()

    def _edit_selected_event(self) -> None:
        if self._selected_id:
            self._edit_event_dialog(self._selected_id)

    def _del_selected_event(self) -> None:
        if self._selected_id:
            self._delete_event(self._selected_id)

    def _export(self) -> None:
        """CC=3 — Exporte la timeline courante en fichier JSON."""
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Exporter la timeline",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
            initialfile=f"timeline_{self._model.name}.json",
        )
        if not path:
            return
        data = self._model.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _LOG.info("Timeline exportée vers %s", path)
        messagebox.showinfo("Export", f"Timeline exportée :\n{path}", parent=self)

    # ── Dialogs événements ───────────────────────────────────────

    def _add_event_dialog(self, event_type: str) -> None:
        """CC=7 — Dialog générique d'ajout d'événement."""
        track_ids = [t.track_id for t in self._model.ordered_tracks()
                     if t.track_id not in ("track_sensors",)]
        if not track_ids:
            messagebox.showinfo("Ajouter", "Aucune piste disponible.", parent=self)
            return

        dlg = _EventDialog(self, title=f"Ajouter — {event_type}",
                           event_type=event_type, track_ids=track_ids,
                           model=self._model)
        if dlg.result:
            ok, msg = self._model.add_event(dlg.result)
            if ok:
                self.redraw()
            else:
                messagebox.showerror("Collision", msg, parent=self)

    def _show_suite_editor_if_needed(self, evt: TimelineEvent) -> None:
        """CC=4 — Affiche le panneau éditeur inline si l'événement est dans une suite."""
        suite_name = self._find_suite_for_event(evt)
        if suite_name:
            # Vérifier si le panneau affiche déjà cette suite
            gid = evt.get_param("suite_group_id", "")
            if (self._editor_panel and self._editor_panel.winfo_ismapped()
                    and self._editor_panel.group_id == gid):
                return
            self._hide_suite_editor()
            self._editor_panel = _SuiteEditorPanel(
                self._main_wrapper, self._model, evt, suite_name,
                on_save=self._on_suite_editor_save,
                on_close=self._hide_suite_editor)
            self._editor_panel.grid(row=0, column=0, sticky="ew")
        else:
            self._hide_suite_editor()

    def _hide_suite_editor(self) -> None:
        """CC=1 — Cache et détruit le panneau éditeur inline."""
        if self._editor_panel:
            self._editor_panel.grid_forget()
            self._editor_panel.destroy()
            self._editor_panel = None

    def _on_suite_editor_save(self) -> None:
        """CC=1 — Callback après sauvegarde du panneau éditeur inline."""
        self._hide_suite_editor()
        self.redraw()

    def _edit_event_dialog(self, event_id: str) -> None:
        """CC=5 — Ouvre l'éditeur adapté au type d'événement."""
        evt = self._model.get_event(event_id)
        if evt is None:
            return
        # Détecte si l'événement fait partie d'une suite importée
        suite_name = self._find_suite_for_event(evt)
        if suite_name:
            # Utiliser le panneau inline
            self._show_suite_editor_if_needed(evt)
        else:
            dlg = _SingleEventEditor(self, self._model, evt)
            if dlg.changed:
                self.redraw()

    def _find_suite_for_event(self, evt: TimelineEvent) -> str:
        """CC=3 — Cherche si l'événement fait partie d'une suite importée."""
        suite_name = evt.get_param("suite_name", "")
        if suite_name:
            return suite_name
        # Fallback : recherche par nom de label dans les suites existantes
        if evt.event_type != EventType.MOVE:
            return ""
        groups = {s.name: [st.get("position_name", "") for st in s.steps] for s in library.list_suites()}
        for grp, poses in groups.items():
            if grp == "__sans_suite__":
                continue
            if evt.label in poses:
                return grp
        return ""

    def _delete_event(self, event_id: str) -> None:
        """CC=6 — Supprime un événement ou une suite entière avec confirmation."""
        evt = self._model.get_event(event_id)
        if evt is None:
            return
        gid = evt.get_param("suite_group_id", "")
        if gid:
            # L'événement fait partie d'une suite — proposer le choix
            suite_name = evt.get_param("suite_name", "Suite")
            siblings = self._find_suite_events(gid)
            msg = (f"Cet événement fait partie de la suite « {suite_name} » "
                   f"({len(siblings)} poses).\n\n"
                   f"• Oui = Supprimer toute la suite\n"
                   f"• Non = Supprimer seulement cette pose")
            choice = messagebox.askyesnocancel("Supprimer", msg, parent=self)
            if choice is None:
                return  # Annuler
            if choice:
                # Supprimer toute la suite
                for e in siblings:
                    self._model.remove_event(e.event_id)
                if self._selected_id in {e.event_id for e in siblings}:
                    self._selected_id = ""
            else:
                # Supprimer seulement cet événement
                self._model.remove_event(event_id)
                if self._selected_id == event_id:
                    self._selected_id = ""
        else:
            ok = messagebox.askyesno("Supprimer", "Supprimer cet événement ?", parent=self)
            if not ok:
                return
            self._model.remove_event(event_id)
            if self._selected_id == event_id:
                self._selected_id = ""
        self.redraw()

    def _find_suite_events(self, suite_group_id: str) -> list:
        """CC=3 — Retrouve tous les événements d'une même suite."""
        result = []
        for track in self._model.ordered_tracks():
            for evt in track.all_events():
                if evt.get_param("suite_group_id", "") == suite_group_id:
                    result.append(evt)
        return sorted(result, key=lambda e: e.start_ms)

    # ── Souscriptions bus ────────────────────────────────────────

    def _sync_robot_tracks(self) -> None:
        """Crée une piste timeline par robot enregistré."""
        for i, rid in enumerate(registry.ids()):
            color = ROBOT_COLORS[i % len(ROBOT_COLORS)]
            self._model.add_robot_track(rid, f"Robot {rid}", color)
        self._after(50, self.redraw)

    def _on_robot_added(self, payload: dict) -> None:
        rid = payload.get("robot_id", "")
        color = payload.get("color", ROBOT_COLORS[0])
        if rid:
            self._model.add_robot_track(rid, f"Robot {rid}", color)
            self._after(0, self.redraw)

    def _on_robot_removed(self, payload: dict) -> None:
        rid = payload.get("robot_id", "")
        if rid:
            self._model.remove_robot_track(rid)
            self._after(0, self.redraw)

    def _subscribe(self) -> None:
        """CC=2 — Souscrit aux événements timeline (marshales vers mainloop Tk)."""
        bus.subscribe_ui("timeline.event_added",   self._on_model_changed,      self)
        bus.subscribe_ui("timeline.event_removed", self._on_model_changed,      self)
        bus.subscribe_ui("timeline.event_moved",   self._on_model_changed,      self)
        bus.subscribe_ui("timeline.event_updated", self._on_model_changed,      self)
        bus.subscribe_ui("timeline.track_added",   self._on_model_changed,      self)
        bus.subscribe_ui("timeline.track_removed", self._on_model_changed,      self)
        bus.subscribe_ui("engine.tick",            self._on_engine_tick,        self)
        bus.subscribe_ui("timeline.event_started", self._on_event_state_changed, self)
        bus.subscribe_ui("timeline.event_done",    self._on_event_state_changed, self)
        bus.subscribe_ui("robot.added",            self._on_robot_added,        self)
        bus.subscribe_ui("robot.removed",          self._on_robot_removed,      self)

    def destroy(self) -> None:
        bus.unsubscribe_object(self)
        super().destroy()

    def _on_model_changed(self, _: dict) -> None:
        """CC=2 — Redraw complet sur mutation du modèle."""
        self._after(0, self.redraw)

    def _on_event_state_changed(self, payload: dict) -> None:
        """CC=5 — Rafraîchit la couleur d'un bloc quand son état change."""
        eid = payload.get("event_id", "")
        if not eid:
            return
        evt = self._model.get_event(eid)
        if evt is None:
            return
        gid = evt.get_param("suite_group_id", "")
        if gid:
            # Suite : recalculer la couleur globale du groupe
            siblings = self._find_suite_events(gid)
            track = self._model.get_track(evt.track_id)
            tc = track.color if track else T.SURFACE_HI
            color = self._suite_block_color(siblings, tc)
        else:
            color = self._block_color(evt, T.SURFACE_HI)
        tag = f"bg_{eid}"
        self._after(0, lambda: self._canvas.itemconfigure(tag, fill=color))

    def _on_engine_tick(self, payload: dict) -> None:
        """CC=3 — Mise à jour curseur + timer seulement (pas de redraw complet)."""
        ms = payload.get("elapsed_ms", 0)
        self._playhead_ms = ms
        self._after(0, lambda: self._update_cursor_only(ms))

    def _update_cursor_only(self, ms: int) -> None:
        """CC=3 — Redessine uniquement le curseur (tag 'cursor')."""
        tracks = self._model.ordered_tracks()
        canvas_h = HEADER_H + len(tracks) * TRACK_H + 40
        self._draw_playhead(canvas_h)
        mins = ms // 60000
        secs = (ms % 60000) // 1000
        millis = ms % 1000
        self._timer_var.set(f"{mins:02d}:{secs:02d}.{millis:03d}")

    # ── Utilitaires ──────────────────────────────────────────────

    def _extract_event_tag(self, tags: tuple) -> str:
        """CC=5 — Extrait l'event_id depuis les tags canvas.

        Fallback : si seul un tag suite_<gid> est present (clic sur la bande
        exterieure, le label ou un gap entre poses), retourne l'event_id du
        premier evenement de la suite afin que la selection (et donc les
        boutons Supprimer/Modifier) fonctionnent.
        """
        for tag in tags:
            if tag.startswith("event_"):
                return tag[len("event_"):]
        for tag in tags:
            if tag.startswith("suite_"):
                gid = tag[len("suite_"):]
                if gid:
                    siblings = self._find_suite_events(gid)
                    if siblings:
                        return siblings[0].event_id
        return ""


# ── Dialog import suite ──────────────────────────────────────────

class _ImportSuiteDialog(tk.Toplevel):
    """CC max : 10 — Dialog d'import d'une suite de poses dans la timeline."""

    def __init__(self, parent, suite_names: list,
                 model: TimelineModel) -> None:
        super().__init__(parent)
        self.title("Importer une suite")
        self.geometry("420x480")
        self.configure(bg=T.BG)
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(200, lambda: self.attributes('-topmost', False))
        self.imported = False
        self._model = model

        f = tk.Frame(self, bg=T.BG, padx=T.PAD_LG, pady=T.PAD_LG)
        f.pack(fill="both", expand=True)

        # Suite (OptionMenu natif — fiable sur macOS)
        tk.Label(f, text="Suite :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=0, column=0, sticky="w", pady=4)
        self._suite_var = tk.StringVar(value=suite_names[0])
        self._suite_var.trace_add("write", lambda *_: self._update_preview())
        _styled_option_menu(f, self._suite_var, suite_names, 24
                            ).grid(row=0, column=1, sticky="w", pady=4)

        # Robot cible (couleurs par robot)
        tk.Label(f, text="Robot :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=1, column=0, sticky="w", pady=4)
        robot_ids = sorted(registry.ids()) or ["robot_1"]
        robot_colors = {rid: registry.color_for(rid) for rid in robot_ids}
        self._robot_var = tk.StringVar(value=robot_ids[0])
        _styled_option_menu(f, self._robot_var, robot_ids, 24,
                            colors=robot_colors, robot_style=True
                            ).grid(row=1, column=1, sticky="w", pady=4)

        # Début (secondes)
        tk.Label(f, text="Début (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=2, column=0, sticky="w", pady=4)
        default_start = model.duration_ms() / 1000.0
        self._start_var = tk.DoubleVar(value=default_start)
        ttk.Spinbox(f, from_=0, to=3600, increment=0.5,
                    textvariable=self._start_var, width=10
                    ).grid(row=2, column=1, sticky="w", pady=4)

        # Durée par mouvement
        tk.Label(f, text="Durée/pose (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=3, column=0, sticky="w", pady=4)
        self._dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(f, from_=0.2, to=30, increment=0.5,
                    textvariable=self._dur_var, width=10
                    ).grid(row=3, column=1, sticky="w", pady=4)

        # Délai inter-poses
        tk.Label(f, text="Délai inter (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=4, column=0, sticky="w", pady=4)
        self._delay_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(f, from_=0, to=10, increment=0.25,
                    textvariable=self._delay_var, width=10
                    ).grid(row=4, column=1, sticky="w", pady=4)

        # Aperçu
        tk.Label(f, text="Aperçu :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=5, column=0, sticky="nw", pady=4)
        self._preview = tk.Listbox(f, height=6, width=30, font=T.F_MONO_SM,
                                   bg=T.SURFACE, fg=T.TEXT, selectmode="none")
        self._preview.grid(row=5, column=1, sticky="w", pady=4)
        self._update_preview()

        # Boutons
        btn_f = tk.Frame(f, bg=T.BG)
        btn_f.grid(row=6, column=0, columnspan=2, pady=(T.PAD_MD, 0))
        ttk.Button(btn_f, text="Annuler",
                   command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btn_f, text="✓ Importer",
                   command=self._on_ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._on_ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _update_preview(self) -> None:
        """CC=3 — Met à jour la liste d'aperçu."""
        self._preview.delete(0, tk.END)
        groups = {s.name: [st.get("position_name", "") for st in s.steps] for s in library.list_suites()}
        poses = groups.get(self._suite_var.get(), [])
        for pname in poses:
            self._preview.insert(tk.END, f"  {pname}")

    def _on_ok(self) -> None:
        """CC=8 — Convertit les poses en événements MOVE et les insère."""
        suite_name = self._suite_var.get()
        robot_id = self._robot_var.get()
        track_id = f"track_{robot_id}"
        start_ms = int(self._start_var.get() * 1000)
        dur_s = self._dur_var.get()
        delay_ms = int(self._delay_var.get() * 1000)

        # Vérifier que la piste existe
        track = self._model.get_track(track_id)
        if track is None:
            messagebox.showerror("Erreur",
                                 f"Piste '{robot_id}' introuvable.\n"
                                 "Ajoutez d'abord ce robot.", parent=self)
            return

        groups = {s.name: [st.get("position_name", "") for st in s.steps] for s in library.list_suites()}
        pose_names = groups.get(suite_name, [])
        all_poses = {p.name: {str(k): v for k, v in p.positions.items()} for p in library.list_positions()}

        # ID unique pour grouper cette import en bloc visuel
        group_id = uuid.uuid4().hex[:12]

        current_ms = start_ms
        added = 0
        for pname in pose_names:
            pdata = all_poses.get(pname)
            if not pdata:
                continue
            positions = {int(k): int(v) for k, v in pdata.items()}
            evt = make_move_event(
                track_id=track_id,
                start_ms=current_ms,
                positions=positions,
                duration_s=dur_s,
                label=pname,
            )
            # Ajouter les métadonnées de suite pour le rendu en bloc
            evt.parameters["suite_name"] = suite_name
            evt.parameters["suite_group_id"] = group_id
            ok, msg = self._model.add_event(evt)
            if not ok:
                messagebox.showerror("Collision",
                                     f"Pose '{pname}' à {current_ms}ms : {msg}",
                                     parent=self)
                break
            added += 1
            current_ms += int(dur_s * 1000) + delay_ms

        if added > 0:
            self.imported = True
            _LOG.info("Suite '%s' importée : %d événement(s) sur %s",
                      suite_name, added, robot_id)
        self.destroy()


# ── Dialog ajout événement ────────────────────────────────────────

class _EventDialog(tk.Toplevel):
    """Dialog modal pour créer un événement. CC max : 8."""

    def __init__(self, parent, title: str, event_type: str,
                 track_ids: list, model: TimelineModel) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("400x320")
        self.configure(bg=T.BG)
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(200, lambda: self.attributes('-topmost', False))
        self.result: Optional[TimelineEvent] = None

        # Bandeau couleur robot
        self._accent_bar = tk.Frame(self, height=4, bg=T.C_AMB)
        self._accent_bar.pack(fill="x")

        f = tk.Frame(self, bg=T.BG, padx=T.PAD_LG, pady=T.PAD_LG)
        f.pack(fill="both", expand=True)

        # Piste (OptionMenu natif — fiable sur macOS)
        tk.Label(f, text="Piste :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=0, column=0, sticky="w", pady=4)
        # Noms lisibles + couleurs pour les pistes
        self._track_labels = {}
        self._track_colors = {}
        for tid in track_ids:
            name = tid.replace("track_", "") if tid.startswith("track_") else tid
            self._track_labels[name] = tid
            track = model.get_track(tid)
            if track:
                self._track_colors[name] = track.color
        display_names = list(self._track_labels.keys())
        self._track_display_var = tk.StringVar(value=display_names[0])
        _styled_option_menu(f, self._track_display_var, display_names, 24,
                            colors=self._track_colors, robot_style=True
                            ).grid(row=0, column=1, sticky="w", pady=4)
        # Synchroniser la couleur du bandeau
        def _sync_accent(*_):
            c = self._track_colors.get(self._track_display_var.get(), T.C_AMB)
            self._accent_bar.configure(bg=c)
        self._track_display_var.trace_add("write", _sync_accent)
        _sync_accent()

        # Début
        tk.Label(f, text="Début (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=1, column=0, sticky="w", pady=4)
        self._start_var = tk.DoubleVar(value=0.0)
        ttk.Spinbox(f, from_=0, to=3600, increment=0.5,
                    textvariable=self._start_var,
                    width=10).grid(row=1, column=1, sticky="w", pady=4)

        # Durée
        tk.Label(f, text="Durée (s) :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=2, column=0, sticky="w", pady=4)
        self._dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(f, from_=0.1, to=300, increment=0.5,
                    textvariable=self._dur_var,
                    width=10).grid(row=2, column=1, sticky="w", pady=4)

        # Label
        tk.Label(f, text="Libellé :", bg=T.BG, fg=T.TEXT,
                 font=T.F_LABEL).grid(row=3, column=0, sticky="w", pady=4)
        self._label_var = tk.StringVar(value=event_type)
        ttk.Entry(f, textvariable=self._label_var,
                  width=28).grid(row=3, column=1, sticky="w", pady=4)

        # Boutons
        btn_f = tk.Frame(f, bg=T.BG)
        btn_f.grid(row=4, column=0, columnspan=2, pady=(T.PAD_MD, 0))
        ttk.Button(btn_f, text="Annuler",
                   command=self.destroy).pack(side="left", padx=6)
        ttk.Button(btn_f, text="✓ Ajouter",
                   command=self._on_ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _: self._on_ok())
        self.wait_window()

    def _on_ok(self) -> None:
        """CC=5 — Construit l'événement et ferme."""
        display = self._track_display_var.get()
        track_id = self._track_labels.get(display, display)
        start_ms = int(self._start_var.get() * 1000)
        dur_ms   = int(self._dur_var.get() * 1000)
        lbl      = self._label_var.get().strip() or "Événement"

        self.result = TimelineEvent.make(
            track_id=track_id,
            event_type=EventType.WAIT,  # Type générique — à étendre par sous-dialogs
            start_ms=start_ms,
            duration_ms=dur_ms,
            label=lbl,
        )
        self.destroy()


# ── Dialog édition événement simple ────────────────────────────────

class _SingleEventEditor(tk.Toplevel):
    """CC max : 5 — Dialog d'édition d'un événement simple."""

    def __init__(self, parent, model: TimelineModel,
                 evt: TimelineEvent) -> None:
        super().__init__(parent)
        self.title(f"✏️  Éditer — {evt.event_type}")
        self.geometry("440x340")
        self.configure(bg=T.BG)
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(200, lambda: self.attributes('-topmost', False))
        self.changed = False
        self._model = model
        self._evt = evt
        self._build()
        self.wait_window()

    def _build(self) -> None:
        """CC=2 — Construction du formulaire."""
        f = tk.Frame(self, bg=T.BG, padx=16, pady=16)
        f.pack(fill="both", expand=True)

        tk.Label(f, text=f"Type : {self._evt.event_type}", bg=T.BG,
                 fg=T.TEXT_MED, font=T.F_CONTROL).pack(anchor="w", pady=(0, 8))

        # Label
        r1 = ttk.Frame(f)
        r1.pack(fill="x", pady=4)
        ttk.Label(r1, text="Libellé :", width=12).pack(side="left")
        self._label_var = tk.StringVar(value=self._evt.label)
        ttk.Entry(r1, textvariable=self._label_var, width=28).pack(side="left")

        # Début
        r2 = ttk.Frame(f)
        r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="Début (s) :", width=12).pack(side="left")
        self._start_var = tk.DoubleVar(value=self._evt.start_ms / 1000.0)
        ttk.Spinbox(r2, from_=0, to=9999, increment=0.25,
                    textvariable=self._start_var, width=10).pack(side="left")

        # Durée
        r3 = ttk.Frame(f)
        r3.pack(fill="x", pady=4)
        ttk.Label(r3, text="Durée (s) :", width=12).pack(side="left")
        self._dur_var = tk.DoubleVar(value=self._evt.duration_ms / 1000.0)
        ttk.Spinbox(r3, from_=0.1, to=300, increment=0.5,
                    textvariable=self._dur_var, width=10).pack(side="left")

        # Boutons
        btn_f = ttk.Frame(f)
        btn_f.pack(fill="x", pady=(16, 0))
        ttk.Button(btn_f, text="Annuler", command=self.destroy).pack(side="left")
        ttk.Button(btn_f, text="✅ Enregistrer", command=self._save).pack(side="right")
        self.bind("<Return>", lambda _: self._save())
        self.bind("<Escape>", lambda _: self.destroy())

    def _save(self) -> None:
        """CC=3 — Applique les modifications."""
        import dataclasses
        new_start = int(self._start_var.get() * 1000)
        new_dur = int(self._dur_var.get() * 1000)
        new_label = self._label_var.get().strip() or self._evt.label
        updated = dataclasses.replace(
            self._evt,
            start_ms=new_start,
            duration_ms=new_dur,
            label=new_label,
        )
        ok, msg = self._model.update_event(updated)
        if ok:
            self.changed = True
            self.destroy()
        else:
            from tkinter import messagebox
            messagebox.showerror("Erreur", msg, parent=self)


# ── Dialog éditeur de suite complet (V17) ──────────────────────────

_STEP_TAGS = {
    "pose":     ("pose_row",   "#a9cce3"),
    "wait":     ("wait_row",   "#f9e79f"),
    "sensor":   ("sensor_row", "#a9dfbf"),
    "arduino":  ("action_row", "#f0b27a"),
}


# ── Panneau éditeur de suite inline (intégré dans TimelinePanel) ────

class _SuiteEditorPanel(tk.Frame):
    """CC max : 8 — Panneau d'édition de suite embarqué dans la timeline."""

    def __init__(self, parent, model: TimelineModel,
                 clicked_evt: TimelineEvent, suite_name: str,
                 on_save=None, on_close=None) -> None:
        super().__init__(parent, bg="#0d1117", height=360)
        self.grid_propagate(False)
        self.configure(height=360)

        self._model = model
        self._suite_name = suite_name
        self._track_id = clicked_evt.track_id
        self._group_id = clicked_evt.get_param("suite_group_id", "") or uuid.uuid4().hex[:12]
        self._on_save_cb = on_save
        self._on_close_cb = on_close

        # Résoudre la couleur de la piste pour cohérence visuelle
        track = model.get_track(self._track_id)
        self._track_color = track.color if track else T.C_AMB

        self._steps = self._collect_steps()
        self._build()
        self._refresh_tree()

    @property
    def group_id(self) -> str:
        return self._group_id

    def _collect_steps(self) -> list:
        """CC=6 — Collecte les étapes de la suite depuis le modèle."""
        track = self._model.get_track(self._track_id)
        if not track:
            return []
        events = sorted(track.all_events(), key=lambda e: e.start_ms)
        steps = []
        for evt in events:
            if self._group_id and evt.get_param("suite_group_id", "") == self._group_id:
                steps.append(self._evt_to_step(evt))
            elif not self._group_id:
                groups = {s.name: [st.get("position_name", "") for st in s.steps]
                          for s in library.list_suites()}
                pose_names = set(groups.get(self._suite_name, []))
                if evt.event_type == EventType.MOVE and evt.label in pose_names:
                    steps.append(self._evt_to_step(evt))
        for i in range(len(steps) - 1):
            gap = steps[i + 1]["start_ms"] - (
                steps[i]["start_ms"] + int(steps[i]["duration"] * 1000))
            steps[i]["pause"] = max(0, gap / 1000.0)
        return steps

    @staticmethod
    def _evt_to_step(evt: TimelineEvent) -> dict:
        """CC=5 — Convertit un TimelineEvent en dict step."""
        if evt.event_type == EventType.MOVE:
            return {"type": "pose", "event_id": evt.event_id,
                    "pose_name": evt.label, "duration": evt.duration_ms / 1000.0,
                    "start_ms": evt.start_ms, "pause": 0.0,
                    "positions": evt.get_param("positions", {})}
        elif evt.event_type == EventType.WAIT:
            return {"type": "wait", "event_id": evt.event_id,
                    "duration": evt.duration_ms / 1000.0, "start_ms": evt.start_ms,
                    "pause": 0.0, "description": evt.label}
        elif evt.event_type == EventType.SENSOR_WAIT:
            return {"type": "sensor", "event_id": evt.event_id,
                    "sensor_id": evt.get_param("sensor_id", ""),
                    "duration": evt.duration_ms / 1000.0, "start_ms": evt.start_ms,
                    "timeout_ms": evt.get_param("timeout_ms", evt.duration_ms),
                    "on_timeout": evt.get_param("on_timeout", "erreur"), "pause": 0.0,
                    "description": evt.label}
        elif evt.event_type == EventType.ARDUINO_ACTION:
            return {"type": "arduino", "event_id": evt.event_id,
                    "device_name": evt.get_param("device_name", ""),
                    "action_name": evt.get_param("action_name", ""),
                    "duration": evt.duration_ms / 1000.0, "start_ms": evt.start_ms,
                    "pause": 0.0, "description": evt.label}
        return {"type": evt.event_type.lower(), "event_id": evt.event_id,
                "duration": evt.duration_ms / 1000.0, "start_ms": evt.start_ms,
                "pause": 0.0, "description": evt.label}

    def _build(self) -> None:
        """CC=2 — Construit le panneau inline horizontal (au-dessus du canvas)."""
        # ── Barre d'en-tête : titre + robot + début + toolbar + save + close ──
        hdr = tk.Frame(self, bg="#161b22", pady=4)
        hdr.pack(fill="x", side="top")

        # Accent coloré de la piste sur le bord gauche
        tk.Frame(hdr, bg=self._track_color, width=4).pack(
            side="left", fill="y", padx=(0, 6))
        tk.Label(hdr, text=f"📁 {self._suite_name}",
                 bg="#161b22", fg=self._track_color,
                 font=(T.FONT_UI, 11, "bold")).pack(side="left", padx=(0, 12))

        # Robot
        tk.Label(hdr, text="Robot :", bg="#161b22", fg=T.TEXT_MED,
                 font=T.F_CAPTION).pack(side="left", padx=(0, 2))
        robot_ids = sorted(registry.ids()) or ["robot_1"]
        robot_colors = {rid: registry.color_for(rid) for rid in robot_ids}
        current_rid = self._track_id.replace("track_", "")
        self._robot_var = tk.StringVar(value=current_rid)
        _styled_option_menu(hdr, self._robot_var, robot_ids, 12,
                            colors=robot_colors, robot_style=True
                            ).pack(side="left", padx=2)

        # Début
        tk.Label(hdr, text="Début :", bg="#161b22", fg=T.TEXT_MED,
                 font=T.F_CAPTION).pack(side="left", padx=(10, 2))
        first_ms = self._steps[0]["start_ms"] if self._steps else 0
        self._tstart_var = tk.DoubleVar(value=first_ms / 1000.0)
        ttk.Spinbox(hdr, from_=0, to=9999, increment=0.25,
                    textvariable=self._tstart_var, width=6
                    ).pack(side="left", padx=2)

        # Séparateur
        tk.Frame(hdr, bg=T.BORDER, width=1).pack(
            side="left", fill="y", padx=8, pady=2)

        # Toolbar compacte
        for txt, cmd in [
            ("➕ Pose", self._add_pose), ("⏱ Pause", self._add_pause),
            ("📡", self._add_sensor), ("⚡", self._add_arduino),
            ("🗑", self._delete_step),
            ("⬆", lambda: self._move_step(-1)),
            ("⬇", lambda: self._move_step(1)),
            ("✏️", self._edit_step),
        ]:
            ttk.Button(hdr, text=txt, width=max(3, len(txt)),
                       command=cmd).pack(side="left", padx=1)

        # Fermer (droite)
        ttk.Button(hdr, text="✕", width=3,
                   command=self._close).pack(side="right", padx=4)
        # Enregistrer (droite)
        ttk.Button(hdr, text="✅ Enregistrer",
                   command=self._save).pack(side="right", padx=4)
        # Info (droite)
        self._info_lbl = tk.Label(hdr, text="", bg="#161b22",
                                   fg="#8b949e", font=T.F_CAPTION)
        self._info_lbl.pack(side="right", padx=8)

        # ── Treeview horizontal (en dessous) ──
        tree_frame = tk.Frame(self, bg="#0d1117")
        tree_frame.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        cols = ("type", "temps", "pause", "detail")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="tree headings",
                                   selectmode="browse", height=6)
        self._tree.heading("#0",     text="Étape",   anchor="w")
        self._tree.heading("type",   text="Type")
        self._tree.heading("temps",  text="Temps")
        self._tree.heading("pause",  text="Pause")
        self._tree.heading("detail", text="Détail")
        self._tree.column("#0",     width=140, minwidth=80)
        self._tree.column("type",   width=60,  minwidth=40)
        self._tree.column("temps",  width=50,  minwidth=40)
        self._tree.column("pause",  width=50,  minwidth=40)
        self._tree.column("detail", width=200, minwidth=100)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Tags couleur cohérents avec les pistes timeline
        self._tree.tag_configure("pose_row",    foreground=self._track_color)
        self._tree.tag_configure("wait_row",    foreground=T.C_AMB_2)
        self._tree.tag_configure("sensor_row",  foreground=T.TRACK_COLOR_SENSOR)
        self._tree.tag_configure("action_row",  foreground=T.TRACK_COLOR_ARDUINO)
        self._tree.bind("<Double-1>", lambda _: self._edit_step())

    def _refresh_tree(self) -> None:
        """CC=4 — Reconstruit le treeview."""
        self._tree.delete(*self._tree.get_children())
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, step in enumerate(self._steps):
            stype = step.get("type", "pose")
            tag_name = _STEP_TAGS.get(stype, ("pose_row", "#a9cce3"))[0]
            letter = letters[i % 26] if i < 26 else f"#{i+1}"
            if stype == "pose":
                label = f"{letter}. {step.get('pose_name', '?')}"
                temps = f"{step.get('duration', 2.0):.1f}"
                detail = step.get("pose_name", "")
            elif stype == "wait":
                label = f"{letter}. ⏱ Pause"
                temps = f"{step.get('duration', 1.0):.1f}"
                detail = step.get("description", "")
            elif stype == "sensor":
                label = f"{letter}. 📡 Capteur"
                temps = f"{step.get('duration', 10.0):.1f}"
                detail = f"{step.get('sensor_id', '?')} ({step.get('on_timeout', 'error')})"
            elif stype == "arduino":
                label = f"{letter}. ⚡ Arduino"
                temps = f"{step.get('duration', 0.5):.1f}"
                detail = f"{step.get('device_name', '?')} → {step.get('action_name', '?')}"
            else:
                label = f"{letter}. {stype}"
                temps = "—"
                detail = ""
            pause = f"{step.get('pause', 0.0):.2f}" if step.get("pause", 0) > 0 else "—"
            self._tree.insert("", "end", iid=str(i), text=label,
                              values=(stype.capitalize(), temps, pause, detail),
                              tags=(tag_name,))
        self._update_info()

    def _update_info(self) -> None:
        n = len(self._steps)
        n_poses = sum(1 for s in self._steps if s.get("type") == "pose")
        total = sum(s.get("duration", 0) + s.get("pause", 0) for s in self._steps)
        self._info_lbl.config(text=f"{n} étapes · {n_poses} poses · {total:.1f}s")

    def _selected_idx(self) -> int:
        sel = self._tree.selection()
        return int(sel[0]) if sel else -1

    def _close(self) -> None:
        if self._on_close_cb:
            self._on_close_cb()

    # ── Actions (identiques au dialog, mais parent=self) ──

    def _add_pose(self) -> None:
        """CC=5 — Ajoute une pose."""
        all_poses = {p.name: {str(k): v for k, v in p.positions.items()}
                     for p in library.list_positions()}
        available = list(all_poses.keys())
        if not available:
            messagebox.showinfo("Ajouter", "Aucune pose enregistrée.", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter une pose")
        dlg.geometry("360x440")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        tk.Label(dlg, text="Sélectionner une pose :", bg=T.BG, fg=T.TEXT,
                 font=T.F_CONTROL).pack(anchor="w", padx=12, pady=(10, 4))
        lb = tk.Listbox(dlg, height=10, font=T.F_MONO_SM,
                        bg=T.SURFACE, fg=T.TEXT, selectmode="browse")
        lb.pack(fill="both", expand=True, padx=12)
        for pn in available:
            lb.insert(tk.END, pn)
        r = ttk.Frame(dlg)
        r.pack(fill="x", padx=12, pady=4)
        ttk.Label(r, text="Durée :").pack(side="left")
        dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(r, from_=0.1, to=30, increment=0.5,
                    textvariable=dur_var, width=8).pack(side="left", padx=4)
        ttk.Label(r, text="Pause :").pack(side="left", padx=(8, 0))
        pause_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(r, from_=0, to=10, increment=0.25,
                    textvariable=pause_var, width=8).pack(side="left", padx=4)

        def _ok():
            sel = lb.curselection()
            if not sel:
                return
            pname = available[sel[0]]
            pdata = all_poses.get(pname, {})
            self._steps.append({
                "type": "pose", "event_id": "", "pose_name": pname,
                "duration": dur_var.get(), "pause": pause_var.get(),
                "start_ms": 0,
                "positions": {int(k): int(v) for k, v in pdata.items()},
            })
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=8)
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ Ajouter", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _add_pause(self) -> None:
        """CC=3 — Ajoute une pause."""
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter une pause")
        dlg.geometry("320x200")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value="Pause")
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({"type": "wait", "event_id": "",
                                "duration": dur_var.get(), "pause": 0,
                                "description": desc_var.get()})
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _add_sensor(self) -> None:
        """CC=4 — Ajoute une attente capteur."""
        dlg = tk.Toplevel(self)
        dlg.title("Attente capteur")
        dlg.geometry("380x300")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="ID capteur :").pack(anchor="w")
        sensor_var = tk.StringVar(value="sensor_1")
        ttk.Entry(f, textvariable=sensor_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Délai max (s) :").pack(anchor="w")
        timeout_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(f, from_=1, to=120, increment=1,
                    textvariable=timeout_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Si délai dépassé :").pack(anchor="w")
        action_var = tk.StringVar(value="erreur")
        _styled_option_menu(f, action_var, ["erreur", "ignorer", "continuer"], 12
                            ).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({
                "type": "sensor", "event_id": "",
                "sensor_id": sensor_var.get().strip() or "sensor_1",
                "duration": timeout_var.get(),
                "timeout_ms": int(timeout_var.get() * 1000),
                "on_timeout": action_var.get(), "pause": 0,
                "description": f"Attente {sensor_var.get()}"})
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _add_arduino(self) -> None:
        """CC=4 — Ajoute une action Arduino."""
        dlg = tk.Toplevel(self)
        dlg.title("Action Arduino")
        dlg.geometry("380x320")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Appareil :").pack(anchor="w")
        device_var = tk.StringVar(value="arduino_1")
        ttk.Entry(f, textvariable=device_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Action :").pack(anchor="w")
        action_var = tk.StringVar(value="trigger")
        ttk.Entry(f, textvariable=action_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({
                "type": "arduino", "event_id": "",
                "device_name": device_var.get().strip() or "arduino_1",
                "action_name": action_var.get().strip() or "trigger",
                "duration": dur_var.get(), "pause": 0,
                "description": f"{device_var.get()} → {action_var.get()}"})
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _delete_step(self) -> None:
        idx = self._selected_idx()
        if 0 <= idx < len(self._steps):
            self._steps.pop(idx)
            self._refresh_tree()

    def _move_step(self, direction: int) -> None:
        idx = self._selected_idx()
        new_idx = idx + direction
        if not (0 <= idx < len(self._steps) and 0 <= new_idx < len(self._steps)):
            return
        self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
        self._refresh_tree()
        self._tree.selection_set(str(new_idx))

    def _edit_step(self) -> None:
        """CC=6 — Édite l'étape sélectionnée."""
        idx = self._selected_idx()
        if idx < 0 or idx >= len(self._steps):
            return
        step = self._steps[idx]
        stype = step.get("type", "pose")
        if stype == "pose":
            self._edit_pose_step(idx, step)
        elif stype == "wait":
            self._edit_wait_step(idx, step)
        elif stype == "sensor":
            self._edit_sensor_step(idx, step)
        elif stype == "arduino":
            self._edit_arduino_step(idx, step)

    def _edit_pose_step(self, idx: int, step: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(f"Éditer — {step.get('pose_name', '?')}")
        dlg.geometry("340x260")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Pose :").pack(anchor="w")
        all_names = [p.name for p in library.list_positions()]
        pose_var = tk.StringVar(value=step.get("pose_name", ""))
        if all_names:
            _styled_option_menu(f, pose_var, all_names, 22
                                ).pack(anchor="w", pady=2)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 2.0))
        ttk.Spinbox(f, from_=0.1, to=30, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=2)
        ttk.Label(f, text="Pause après (s) :").pack(anchor="w")
        pause_var = tk.DoubleVar(value=step.get("pause", 0.0))
        ttk.Spinbox(f, from_=0, to=10, increment=0.25,
                    textvariable=pause_var, width=10).pack(anchor="w", pady=2)

        def _ok():
            new_name = pose_var.get()
            pdata = {p.name: {str(k): v for k, v in p.positions.items()}
                     for p in library.list_positions()}.get(new_name, step.get("positions", {}))
            self._steps[idx]["pose_name"] = new_name
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["pause"] = pause_var.get()
            self._steps[idx]["positions"] = {int(k): int(v) for k, v in pdata.items()}
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _edit_wait_step(self, idx: int, step: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Pause")
        dlg.geometry("320x200")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 1.0))
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value=step.get("description", ""))
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["description"] = desc_var.get()
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _edit_sensor_step(self, idx: int, step: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Capteur")
        dlg.geometry("380x300")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="ID capteur :").pack(anchor="w")
        sensor_var = tk.StringVar(value=step.get("sensor_id", "sensor_1"))
        ttk.Entry(f, textvariable=sensor_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Délai max (s) :").pack(anchor="w")
        timeout_var = tk.DoubleVar(value=step.get("duration", 10.0))
        ttk.Spinbox(f, from_=1, to=120, increment=1,
                    textvariable=timeout_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Si délai dépassé :").pack(anchor="w")
        action_var = tk.StringVar(value=step.get("on_timeout", "erreur"))
        _styled_option_menu(f, action_var, ["erreur", "ignorer", "continuer"], 12
                            ).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["sensor_id"] = sensor_var.get().strip()
            self._steps[idx]["duration"] = timeout_var.get()
            self._steps[idx]["timeout_ms"] = int(timeout_var.get() * 1000)
            self._steps[idx]["on_timeout"] = action_var.get()
            self._steps[idx]["description"] = f"Attente {sensor_var.get()}"
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _edit_arduino_step(self, idx: int, step: dict) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Arduino")
        dlg.geometry("380x320")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Appareil :").pack(anchor="w")
        device_var = tk.StringVar(value=step.get("device_name", "arduino_1"))
        ttk.Entry(f, textvariable=device_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Action :").pack(anchor="w")
        action_var = tk.StringVar(value=step.get("action_name", "trigger"))
        ttk.Entry(f, textvariable=action_var, width=24).pack(anchor="w", pady=4)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 0.5))
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["device_name"] = device_var.get().strip()
            self._steps[idx]["action_name"] = action_var.get().strip()
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["description"] = f"{device_var.get()} → {action_var.get()}"
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    # ── Sauvegarde ─────────────────────────────────────────────────

    def _save(self) -> None:
        """CC=7 — Enregistre les modifications dans le modèle timeline."""
        robot_id = self._robot_var.get()
        track_id = f"track_{robot_id}"
        track = self._model.get_track(track_id)
        if not track:
            messagebox.showerror("Erreur", f"Piste '{robot_id}' introuvable.",
                                 parent=self)
            return
        # Supprimer les anciens événements de cette suite
        for step in self._collect_steps():
            eid = step.get("event_id", "")
            if eid:
                self._model.remove_event(eid)
        # Recréer les événements
        t_start_ms = int(self._tstart_var.get() * 1000)
        current_ms = t_start_ms
        added = 0
        for step in self._steps:
            stype = step.get("type", "pose")
            dur_ms = int(step.get("duration", 2.0) * 1000)
            pause_ms = int(step.get("pause", 0.0) * 1000)
            if stype == "pose":
                evt = make_move_event(
                    track_id=track_id, start_ms=current_ms,
                    positions=step.get("positions", {}),
                    duration_s=step.get("duration", 2.0),
                    label=step.get("pose_name", "Move"))
                evt.parameters["suite_name"] = self._suite_name
                evt.parameters["suite_group_id"] = self._group_id
            elif stype == "wait":
                evt = make_wait_event(
                    track_id=track_id, start_ms=current_ms, duration_ms=dur_ms)
            elif stype == "sensor":
                evt = make_sensor_wait_event(
                    track_id=track_id, start_ms=current_ms,
                    sensor_id=step.get("sensor_id", "sensor_1"),
                    timeout_ms=step.get("timeout_ms", dur_ms),
                    on_timeout=step.get("on_timeout", "erreur"))
            elif stype == "arduino":
                evt = make_arduino_event(
                    track_id=track_id, start_ms=current_ms,
                    device_name=step.get("device_name", "arduino_1"),
                    action_name=step.get("action_name", "trigger"),
                    duration_ms=dur_ms)
            else:
                current_ms += dur_ms + pause_ms
                continue
            ok, msg = self._model.add_event(evt)
            if not ok:
                messagebox.showerror("Collision",
                                     f"Étape {added+1} à {current_ms}ms : {msg}",
                                     parent=self)
                break
            added += 1
            current_ms += dur_ms + pause_ms
        _LOG.info("Suite '%s' mise à jour : %d étapes sur %s",
                  self._suite_name, added, robot_id)
        if self._on_save_cb:
            self._on_save_cb()


class _SuiteEditorDialog(tk.Toplevel):
    """CC max : 8 — Dialog d'édition complet d'une suite sur la timeline (V17)."""

    def __init__(self, parent, model: TimelineModel,
                 clicked_evt: TimelineEvent, suite_name: str) -> None:
        super().__init__(parent)
        self.title(f"✏️  Édition suite : {suite_name}")
        self.geometry("900x680")
        self.configure(bg="#0d1117")
        self.focus_force()
        self.attributes('-topmost', True)
        self.after(200, lambda: self.attributes('-topmost', False))
        self.changed = False

        self._model = model
        self._suite_name = suite_name
        self._track_id = clicked_evt.track_id
        # Préserver ou créer un group_id pour le rendu en bloc
        self._group_id = clicked_evt.get_param("suite_group_id", "") or uuid.uuid4().hex[:12]

        # Couleur de piste pour cohérence visuelle
        track = model.get_track(self._track_id)
        self._track_color = track.color if track else T.C_AMB

        # Collecter tous les événements MOVE de cette suite sur cette piste
        self._steps = self._collect_steps()
        self._build()
        self._refresh_tree()
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _collect_steps(self) -> list:
        """CC=6 — Collecte les étapes de la suite depuis le modèle."""
        track = self._model.get_track(self._track_id)
        if not track:
            return []
        events = sorted(track.all_events(), key=lambda e: e.start_ms)
        steps = []
        for evt in events:
            # Filtrer par suite_group_id si disponible
            if self._group_id and evt.get_param("suite_group_id", "") == self._group_id:
                steps.append(self._evt_to_step(evt))
            elif not self._group_id:
                # Fallback : par nom de label dans la suite
                groups = {s.name: [st.get("position_name", "") for st in s.steps]
                          for s in library.list_suites()}
                pose_names = set(groups.get(self._suite_name, []))
                if evt.event_type == EventType.MOVE and evt.label in pose_names:
                    steps.append(self._evt_to_step(evt))
        # Calculer les pauses inter-étapes
        for i in range(len(steps) - 1):
            gap = steps[i + 1]["start_ms"] - (
                steps[i]["start_ms"] + int(steps[i]["duration"] * 1000))
            steps[i]["pause"] = max(0, gap / 1000.0)
        return steps

    @staticmethod
    def _evt_to_step(evt: TimelineEvent) -> dict:
        """CC=5 — Convertit un TimelineEvent en dict step pour l'éditeur."""
        if evt.event_type == EventType.MOVE:
            return {
                "type": "pose",
                "event_id": evt.event_id,
                "pose_name": evt.label,
                "duration": evt.duration_ms / 1000.0,
                "start_ms": evt.start_ms,
                "pause": 0.0,
                "positions": evt.get_param("positions", {}),
            }
        elif evt.event_type == EventType.WAIT:
            return {
                "type": "wait",
                "event_id": evt.event_id,
                "duration": evt.duration_ms / 1000.0,
                "start_ms": evt.start_ms,
                "pause": 0.0,
                "description": evt.label,
            }
        elif evt.event_type == EventType.SENSOR_WAIT:
            return {
                "type": "sensor",
                "event_id": evt.event_id,
                "sensor_id": evt.get_param("sensor_id", ""),
                "duration": evt.duration_ms / 1000.0,
                "start_ms": evt.start_ms,
                "timeout_ms": evt.get_param("timeout_ms", evt.duration_ms),
                "on_timeout": evt.get_param("on_timeout", "erreur"),
                "pause": 0.0,
                "description": evt.label,
            }
        elif evt.event_type == EventType.ARDUINO_ACTION:
            return {
                "type": "arduino",
                "event_id": evt.event_id,
                "device_name": evt.get_param("device_name", ""),
                "action_name": evt.get_param("action_name", ""),
                "duration": evt.duration_ms / 1000.0,
                "start_ms": evt.start_ms,
                "pause": 0.0,
                "description": evt.label,
            }
        else:
            return {
                "type": evt.event_type.lower(),
                "event_id": evt.event_id,
                "duration": evt.duration_ms / 1000.0,
                "start_ms": evt.start_ms,
                "pause": 0.0,
                "description": evt.label,
            }

    def _build(self) -> None:
        """CC=3 — Construit le dialog."""
        self._build_header()
        self._build_toolbar()
        self._build_tree_panel()
        self._build_footer()

    def _build_header(self) -> None:
        """CC=3 — En-tête : nom suite, robot, t_start."""
        hdr = tk.Frame(self, bg="#161b22", pady=8)
        hdr.pack(fill="x")

        tk.Label(hdr, text=f"  📁  {self._suite_name}",
                 bg="#161b22", fg="#f6a117", font=(T.FONT_UI, 14, "bold")
                 ).pack(side="left", padx=8)

        # Robot
        tk.Label(hdr, text="Robot :", bg="#161b22", fg="#e8edf7",
                 font=T.F_CONTROL).pack(side="left", padx=(20, 4))
        robot_ids = sorted(registry.ids()) or ["robot_1"]
        robot_colors = {rid: registry.color_for(rid) for rid in robot_ids}
        current_rid = self._track_id.replace("track_", "")
        self._robot_var = tk.StringVar(value=current_rid)
        _styled_option_menu(hdr, self._robot_var, robot_ids, 12,
                            colors=robot_colors, robot_style=True
                            ).pack(side="left", padx=2)

        # t_start
        tk.Label(hdr, text="Début (s) :", bg="#161b22", fg="#e8edf7",
                 font=T.F_CONTROL).pack(side="left", padx=(20, 4))
        first_ms = self._steps[0]["start_ms"] if self._steps else 0
        self._tstart_var = tk.DoubleVar(value=first_ms / 1000.0)
        ttk.Spinbox(hdr, from_=0, to=9999, increment=0.25,
                    textvariable=self._tstart_var, width=8
                    ).pack(side="left", padx=2)

    def _build_toolbar(self) -> None:
        """CC=2 — Barre d'outils."""
        bar = tk.Frame(self, bg="#21262d", pady=4)
        bar.pack(fill="x")
        for txt, cmd in [
            ("➕ Pose",       self._add_pose),
            ("⏱ Pause",      self._add_pause),
            ("📡 Capteur",    self._add_sensor),
            ("⚡ Arduino",    self._add_arduino),
            ("🗑 Supprimer",   self._delete_step),
            ("⬆",            lambda: self._move_step(-1)),
            ("⬇",            lambda: self._move_step(1)),
            ("✏️ Éditer",     self._edit_step),
        ]:
            ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=2)
        tk.Label(bar, text="  Double-clic pour éditer une ligne",
                 bg="#21262d", fg="#8b949e", font=T.F_CAPTION
                 ).pack(side="left", padx=12)

    def _build_tree_panel(self) -> None:
        """CC=2 — Treeview des étapes de la suite."""
        frame = tk.Frame(self, bg="#0d1117")
        frame.pack(fill="both", expand=True, padx=12, pady=6)

        cols = ("type", "robot", "temps", "pause", "detail")
        self._tree = ttk.Treeview(frame, columns=cols, show="tree headings",
                                   selectmode="browse", height=16)
        self._tree.heading("#0",     text="Étape",   anchor="w")
        self._tree.heading("type",   text="Type")
        self._tree.heading("robot",  text="Robot")
        self._tree.heading("temps",  text="Temps (s)")
        self._tree.heading("pause",  text="Pause après")
        self._tree.heading("detail", text="Détail")
        self._tree.column("#0",     width=160, minwidth=100)
        self._tree.column("type",   width=80,  minwidth=60)
        self._tree.column("robot",  width=100, minwidth=70)
        self._tree.column("temps",  width=80,  minwidth=60)
        self._tree.column("pause",  width=90,  minwidth=60)
        self._tree.column("detail", width=260, minwidth=140)

        vsb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Tags couleur cohérents avec les pistes timeline
        self._tree.tag_configure("pose_row",    foreground=self._track_color)
        self._tree.tag_configure("wait_row",    foreground=T.C_AMB_2)
        self._tree.tag_configure("sensor_row",  foreground=T.TRACK_COLOR_SENSOR)
        self._tree.tag_configure("action_row",  foreground=T.TRACK_COLOR_ARDUINO)

        self._tree.bind("<Double-1>", lambda _: self._edit_step())

    def _build_footer(self) -> None:
        """CC=2 — Compteur + boutons."""
        foot = tk.Frame(self, bg="#161b22", pady=8)
        foot.pack(fill="x", side="bottom")

        self._info_lbl = tk.Label(foot, text="", bg="#161b22",
                                   fg="#8b949e", font=T.F_CONTROL)
        self._info_lbl.pack(side="left", padx=12)
        self._update_info()

        ttk.Button(foot, text="Annuler",
                   command=self.destroy).pack(side="left", padx=6)
        ttk.Button(foot, text="✅ Enregistrer",
                   command=self._save).pack(side="right", padx=12)

    # ── Rafraîchissement ───────────────────────────────────────────

    def _refresh_tree(self) -> None:
        """CC=4 — Reconstruit le treeview des étapes."""
        self._tree.delete(*self._tree.get_children())
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, step in enumerate(self._steps):
            stype = step.get("type", "pose")
            tag_name = _STEP_TAGS.get(stype, ("pose_row", "#a9cce3"))[0]
            letter = letters[i % 26] if i < 26 else f"#{i+1}"
            robot = self._robot_var.get()

            if stype == "pose":
                label = f"{letter}. {step.get('pose_name', '?')}"
                detail = step.get("pose_name", "")
                temps = f"{step.get('duration', 2.0):.1f}"
            elif stype == "wait":
                label = f"{letter}. ⏱ Pause"
                detail = step.get("description", "")
                temps = f"{step.get('duration', 1.0):.1f}"
                robot = "—"
            elif stype == "sensor":
                label = f"{letter}. 📡 Capteur"
                detail = f"{step.get('sensor_id', '?')} (timeout: {step.get('on_timeout', 'error')})"
                temps = f"{step.get('duration', 10.0):.1f}"
                robot = "—"
            elif stype == "arduino":
                label = f"{letter}. ⚡ Arduino"
                detail = f"{step.get('device_name', '?')} → {step.get('action_name', '?')}"
                temps = f"{step.get('duration', 0.5):.1f}"
                robot = "—"
            else:
                label = f"{letter}. {stype}"
                detail = ""
                temps = "—"

            pause = f"{step.get('pause', 0.0):.2f}" if step.get("pause", 0) > 0 else "—"
            self._tree.insert("", "end", iid=str(i), text=label,
                              values=(stype.capitalize(), robot, temps, pause, detail),
                              tags=(tag_name,))
        self._update_info()

    def _update_info(self) -> None:
        """CC=3 — Met à jour le compteur en bas."""
        n = len(self._steps)
        n_poses = sum(1 for s in self._steps if s.get("type") == "pose")
        total = sum(s.get("duration", 0) + s.get("pause", 0) for s in self._steps)
        self._info_lbl.config(
            text=f"{n} étapes  ·  {n_poses} poses  ·  durée ≈ {total:.1f}s")

    # ── Actions ───────────────────────────────────────────────────

    def _selected_idx(self) -> int:
        sel = self._tree.selection()
        return int(sel[0]) if sel else -1

    def _add_pose(self) -> None:
        """CC=5 — Ajoute une pose depuis les poses existantes."""
        all_poses = {p.name: {str(k): v for k, v in p.positions.items()} for p in library.list_positions()}
        groups = {s.name: [st.get("position_name", "") for st in s.steps] for s in library.list_suites()}
        suite_poses = groups.get(self._suite_name, [])
        available = list(all_poses.keys())
        if not available:
            messagebox.showinfo("Ajouter", "Aucune pose enregistrée.", parent=self)
            return
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter une pose")
        dlg.geometry("360x440")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))

        tk.Label(dlg, text="Sélectionner une pose :", bg=T.BG, fg=T.TEXT,
                 font=T.F_CONTROL).pack(anchor="w", padx=12, pady=(10, 4))
        lb = tk.Listbox(dlg, height=10, font=T.F_MONO_SM,
                        bg=T.SURFACE, fg=T.TEXT, selectmode="browse")
        lb.pack(fill="both", expand=True, padx=12)
        for pn in available:
            marker = " ★" if pn in suite_poses else ""
            lb.insert(tk.END, f"{pn}{marker}")

        r = ttk.Frame(dlg)
        r.pack(fill="x", padx=12, pady=4)
        ttk.Label(r, text="Durée (s) :").pack(side="left")
        dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(r, from_=0.1, to=30, increment=0.5,
                    textvariable=dur_var, width=8).pack(side="left", padx=4)
        ttk.Label(r, text="Pause (s) :").pack(side="left", padx=(8, 0))
        pause_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(r, from_=0, to=10, increment=0.25,
                    textvariable=pause_var, width=8).pack(side="left", padx=4)

        def _ok():
            sel = lb.curselection()
            if not sel:
                return
            pname = available[sel[0]]
            pdata = all_poses.get(pname, {})
            self._steps.append({
                "type": "pose",
                "event_id": "",
                "pose_name": pname,
                "duration": dur_var.get(),
                "pause": pause_var.get(),
                "start_ms": 0,
                "positions": {int(k): int(v) for k, v in pdata.items()},
            })
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=8)
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ Ajouter", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _add_pause(self) -> None:
        """CC=3 — Ajoute une pause."""
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter une pause")
        dlg.geometry("320x200")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=1.0)
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value="Pause")
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({
                "type": "wait",
                "event_id": "",
                "duration": dur_var.get(),
                "pause": 0,
                "description": desc_var.get(),
            })
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.wait_window()

    def _add_sensor(self) -> None:
        """CC=4 — Ajoute une attente capteur."""
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter — Attente capteur")
        dlg.geometry("380x300")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="ID capteur :").pack(anchor="w")
        sensor_var = tk.StringVar(value="sensor_1")
        ttk.Entry(f, textvariable=sensor_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Délai max (s) :").pack(anchor="w")
        timeout_var = tk.DoubleVar(value=10.0)
        ttk.Spinbox(f, from_=1, to=120, increment=1,
                    textvariable=timeout_var, width=10).pack(anchor="w", pady=4)

        ttk.Label(f, text="Si délai dépassé :").pack(anchor="w")
        action_var = tk.StringVar(value="erreur")
        _styled_option_menu(f, action_var, ["erreur", "ignorer", "continuer"], 12
                            ).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({
                "type": "sensor",
                "event_id": "",
                "sensor_id": sensor_var.get().strip() or "sensor_1",
                "duration": timeout_var.get(),
                "timeout_ms": int(timeout_var.get() * 1000),
                "on_timeout": action_var.get(),
                "pause": 0,
                "description": f"Attente {sensor_var.get()}",
            })
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _add_arduino(self) -> None:
        """CC=4 — Ajoute une action Arduino."""
        dlg = tk.Toplevel(self)
        dlg.title("Ajouter — Action Arduino")
        dlg.geometry("380x320")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Appareil :").pack(anchor="w")
        device_var = tk.StringVar(value="arduino_1")
        ttk.Entry(f, textvariable=device_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Action :").pack(anchor="w")
        action_var = tk.StringVar(value="trigger")
        ttk.Entry(f, textvariable=action_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=0.5)
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)

        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value="")
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps.append({
                "type": "arduino",
                "event_id": "",
                "device_name": device_var.get().strip() or "arduino_1",
                "action_name": action_var.get().strip() or "trigger",
                "duration": dur_var.get(),
                "pause": 0,
                "description": desc_var.get().strip(),
            })
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _delete_step(self) -> None:
        """CC=2 — Supprime l'étape sélectionnée."""
        idx = self._selected_idx()
        if 0 <= idx < len(self._steps):
            self._steps.pop(idx)
            self._refresh_tree()

    def _move_step(self, direction: int) -> None:
        """CC=3 — Monte/descend l'étape."""
        idx = self._selected_idx()
        new_idx = idx + direction
        if not (0 <= idx < len(self._steps) and 0 <= new_idx < len(self._steps)):
            return
        self._steps[idx], self._steps[new_idx] = self._steps[new_idx], self._steps[idx]
        self._refresh_tree()
        self._tree.selection_set(str(new_idx))

    def _edit_step(self) -> None:
        """CC=6 — Édite l'étape sélectionnée selon son type."""
        idx = self._selected_idx()
        if idx < 0 or idx >= len(self._steps):
            return
        step = self._steps[idx]
        stype = step.get("type", "pose")
        if stype == "pose":
            self._edit_pose_step(idx, step)
        elif stype == "wait":
            self._edit_wait_step(idx, step)
        elif stype == "sensor":
            self._edit_sensor_step(idx, step)
        elif stype == "arduino":
            self._edit_arduino_step(idx, step)

    def _edit_pose_step(self, idx: int, step: dict) -> None:
        """CC=3 — Dialog d'édition d'une étape pose."""
        dlg = tk.Toplevel(self)
        dlg.title(f"Éditer — {step.get('pose_name', '?')}")
        dlg.geometry("340x260")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)

        # Pose (combobox avec toutes les poses)
        ttk.Label(f, text="Pose :").pack(anchor="w")
        all_names = list({p.name: {str(k): v for k, v in p.positions.items()} for p in library.list_positions()}.keys())
        pose_var = tk.StringVar(value=step.get("pose_name", ""))
        if all_names:
            _styled_option_menu(f, pose_var, all_names, 22
                                ).pack(anchor="w", pady=2)

        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 2.0))
        ttk.Spinbox(f, from_=0.1, to=30, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=2)

        ttk.Label(f, text="Pause après (s) :").pack(anchor="w")
        pause_var = tk.DoubleVar(value=step.get("pause", 0.0))
        ttk.Spinbox(f, from_=0, to=10, increment=0.25,
                    textvariable=pause_var, width=10).pack(anchor="w", pady=2)

        def _ok():
            new_name = pose_var.get()
            pdata = {p.name: {str(k): v for k, v in p.positions.items()} for p in library.list_positions()}.get(new_name, step.get("positions", {}))
            self._steps[idx]["pose_name"] = new_name
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["pause"] = pause_var.get()
            self._steps[idx]["positions"] = {int(k): int(v) for k, v in pdata.items()}
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _edit_wait_step(self, idx: int, step: dict) -> None:
        """CC=2 — Dialog d'édition d'une pause."""
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Pause")
        dlg.geometry("320x200")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 1.0))
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)
        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value=step.get("description", ""))
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["description"] = desc_var.get()
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _edit_sensor_step(self, idx: int, step: dict) -> None:
        """CC=3 — Dialog d'édition d'une étape capteur."""
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Attente capteur")
        dlg.geometry("380x300")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="ID capteur :").pack(anchor="w")
        sensor_var = tk.StringVar(value=step.get("sensor_id", "sensor_1"))
        ttk.Entry(f, textvariable=sensor_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Délai max (s) :").pack(anchor="w")
        timeout_var = tk.DoubleVar(value=step.get("duration", 10.0))
        ttk.Spinbox(f, from_=1, to=120, increment=1,
                    textvariable=timeout_var, width=10).pack(anchor="w", pady=4)

        ttk.Label(f, text="Si délai dépassé :").pack(anchor="w")
        action_var = tk.StringVar(value=step.get("on_timeout", "erreur"))
        _styled_option_menu(f, action_var, ["erreur", "ignorer", "continuer"], 12
                            ).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["sensor_id"] = sensor_var.get().strip()
            self._steps[idx]["duration"] = timeout_var.get()
            self._steps[idx]["timeout_ms"] = int(timeout_var.get() * 1000)
            self._steps[idx]["on_timeout"] = action_var.get()
            self._steps[idx]["description"] = f"Attente {sensor_var.get()}"
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    def _edit_arduino_step(self, idx: int, step: dict) -> None:
        """CC=3 — Dialog d'édition d'une étape Arduino."""
        dlg = tk.Toplevel(self)
        dlg.title("Éditer — Action Arduino")
        dlg.geometry("380x320")
        dlg.configure(bg=T.BG)
        dlg.focus_force()
        dlg.attributes('-topmost', True)
        dlg.after(200, lambda: dlg.attributes('-topmost', False))
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Appareil :").pack(anchor="w")
        device_var = tk.StringVar(value=step.get("device_name", "arduino_1"))
        ttk.Entry(f, textvariable=device_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Action :").pack(anchor="w")
        action_var = tk.StringVar(value=step.get("action_name", "trigger"))
        ttk.Entry(f, textvariable=action_var, width=24).pack(anchor="w", pady=4)

        ttk.Label(f, text="Durée (s) :").pack(anchor="w")
        dur_var = tk.DoubleVar(value=step.get("duration", 0.5))
        ttk.Spinbox(f, from_=0.1, to=60, increment=0.5,
                    textvariable=dur_var, width=10).pack(anchor="w", pady=4)

        ttk.Label(f, text="Description :").pack(anchor="w")
        desc_var = tk.StringVar(value=step.get("description", ""))
        ttk.Entry(f, textvariable=desc_var, width=24).pack(anchor="w", pady=4)

        def _ok():
            self._steps[idx]["device_name"] = device_var.get().strip()
            self._steps[idx]["action_name"] = action_var.get().strip()
            self._steps[idx]["duration"] = dur_var.get()
            self._steps[idx]["description"] = desc_var.get().strip()
            dlg.destroy()
            self._refresh_tree()

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")
        ttk.Button(bf, text="✅ OK", command=_ok).pack(side="right")
        dlg.bind("<Return>", lambda _: _ok())
        dlg.wait_window()

    # ── Sauvegarde ─────────────────────────────────────────────────

    def _save(self) -> None:
        """CC=7 — Enregistre les modifications dans le modèle timeline."""
        import dataclasses

        robot_id = self._robot_var.get()
        track_id = f"track_{robot_id}"
        track = self._model.get_track(track_id)
        if not track:
            messagebox.showerror("Erreur", f"Piste '{robot_id}' introuvable.",
                                 parent=self)
            return

        # Supprimer les anciens événements de cette suite
        for step in self._collect_steps():
            eid = step.get("event_id", "")
            if eid:
                self._model.remove_event(eid)

        # Recréer les événements dans le bon ordre
        t_start_ms = int(self._tstart_var.get() * 1000)
        current_ms = t_start_ms
        added = 0
        for step in self._steps:
            stype = step.get("type", "pose")
            dur_ms = int(step.get("duration", 2.0) * 1000)
            pause_ms = int(step.get("pause", 0.0) * 1000)

            if stype == "pose":
                evt = make_move_event(
                    track_id=track_id,
                    start_ms=current_ms,
                    positions=step.get("positions", {}),
                    duration_s=step.get("duration", 2.0),
                    label=step.get("pose_name", "Move"),
                )
                # Préserver les métadonnées de suite pour le rendu en bloc
                evt.parameters["suite_name"] = self._suite_name
                evt.parameters["suite_group_id"] = self._group_id
            elif stype == "wait":
                evt = make_wait_event(
                    track_id=track_id,
                    start_ms=current_ms,
                    duration_ms=dur_ms,
                )
            elif stype == "sensor":
                evt = make_sensor_wait_event(
                    track_id=track_id,
                    start_ms=current_ms,
                    sensor_id=step.get("sensor_id", "sensor_1"),
                    timeout_ms=step.get("timeout_ms", dur_ms),
                    on_timeout=step.get("on_timeout", "erreur"),
                )
            elif stype == "arduino":
                evt = make_arduino_event(
                    track_id=track_id,
                    start_ms=current_ms,
                    device_name=step.get("device_name", "arduino_1"),
                    action_name=step.get("action_name", "trigger"),
                    duration_ms=dur_ms,
                )
            else:
                current_ms += dur_ms + pause_ms
                continue

            ok, msg = self._model.add_event(evt)
            if not ok:
                messagebox.showerror("Collision",
                                     f"Étape {added+1} à {current_ms}ms : {msg}",
                                     parent=self)
                break
            added += 1
            current_ms += dur_ms + pause_ms

        self.changed = True
        _LOG.info("Suite '%s' mise à jour : %d étapes sur %s",
                  self._suite_name, added, robot_id)
        self.destroy()
