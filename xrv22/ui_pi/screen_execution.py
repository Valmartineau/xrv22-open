"""
xrv22/ui_pi/screen_execution.py
────────────────────────────────
Ecran Execution : selection projet + scenarios + play/pause/stop/emergency.

Layout (800 x 480 - header 40 - tabbar 56 = 384 dispo) :
  Header projet 48    (nom projet actuel + bouton CHANGER)
  Scenarios 200       (liste tactile des scenarios du projet, scrollable)
  Progress + log 48   (barre + label)
  Actions 88          (PLAY / PAUSE / STOP / EMERGENCY)
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, List, Optional

from xrv22.library.library_manager import library
from xrv22.library.models import ScenarioModel, ProjectInfo
from xrv22.robots.robot_profiles import profiles
from xrv22.services.event_bus import bus
from xrv22.services.project_service import project
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.widgets_pi import (ProgressBar, TouchButton, draw_neu_rect)


class ScreenExecution(tk.Frame):
    """Selection projet + liste scenarios + execution timeline."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.BG,
                         width=P.SCREEN_W, height=P.SCREEN_H - 56)
        self.pack_propagate(False)
        self._scenarios: List[ScenarioModel] = []
        self._selected_idx = 0
        self._popup: Optional[tk.Toplevel] = None

        # ── Barre projet (48) ─────────────────────────────────────
        bar = tk.Frame(self, bg=T.SIDEBAR, height=48)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="Projet :",
                 bg=T.SIDEBAR, fg=T.TEXT_MED, font=P.F_LABEL
                 ).place(x=P.PAD_MD, y=17)
        self._lbl_project = tk.Label(
            bar, text="—", bg=T.SIDEBAR, fg=T.C_AMB, font=P.F_H1)
        self._lbl_project.place(x=80, y=10)
        TouchButton(bar, text="CHANGER", icon="\u21BB",
                    width=150, height=36,
                    accent=T.SURFACE_HI, fg=T.C_AMB, font=P.F_BTN,
                    command=self._open_project_picker
                    ).place(x=P.SCREEN_W - 160, y=6)

        # ── Liste scenarios (100) ─────────────────────────────────
        tk.Label(self, text="SCENARIOS",
                 bg=T.BG, fg=T.C_MAG_3, font=P.F_LABEL
                 ).pack(side="top", anchor="w", padx=P.PAD_LG, pady=(2, 0))
        self._scen_frame = tk.Frame(self, bg=T.BG, height=100)
        self._scen_frame.pack(side="top", fill="x",
                              padx=P.PAD_MD, pady=0)
        self._scen_frame.pack_propagate(False)

        # ── Vue timeline (prend toute la hauteur disponible) ─────
        tk.Label(self, text="TIMELINE",
                 bg=T.BG, fg=T.C_MAG_3, font=P.F_LABEL
                 ).pack(side="top", anchor="w", padx=P.PAD_LG, pady=(2, 0))
        self._timeline_view = TimelineView(self, width=P.SCREEN_W - 16, height=118)
        self._timeline_view.pack(side="top", fill="both", expand=True,
                                  padx=P.PAD_SM, pady=0)

        # ── Progress + log (30) ───────────────────────────────────
        prog_row = tk.Frame(self, bg=T.BG, height=30)
        prog_row.pack(side="top", fill="x", padx=P.PAD_MD, pady=0)
        prog_row.pack_propagate(False)
        self._progress = ProgressBar(prog_row, width=P.SCREEN_W - 260, height=18)
        self._progress.pack(side="left")
        self._log = tk.Label(prog_row, text="Pret.",
                             bg=T.BG, fg=T.TEXT_MED, font=P.F_MONO,
                             anchor="w")
        self._log.pack(side="left", fill="x", expand=True, padx=P.PAD_SM)

        # ── Actions (88) ──────────────────────────────────────────
        act = tk.Frame(self, bg=T.BG, height=88)
        act.pack(side="bottom", fill="x", padx=P.PAD_MD, pady=P.PAD_SM)
        act.pack_propagate(False)
        btn_w, btn_h = 170, 72
        gap = 10
        total = btn_w * 4 + gap * 3
        x0 = (P.SCREEN_W - total) // 2
        self._btn_play = TouchButton(
            act, text="PLAY", icon="\u25B6", width=btn_w, height=btn_h,
            accent=T.C_OK_DIM, fg=T.C_OK, font=P.F_BTN_LG,
            command=self._play)
        self._btn_play.place(x=x0, y=8)
        self._btn_pause = TouchButton(
            act, text="PAUSE", icon="\u23F8", width=btn_w, height=btn_h,
            accent=T.C_AMB_DIM, fg=T.C_AMB, font=P.F_BTN_LG,
            command=self._pause_or_resume)
        self._btn_pause.place(x=x0 + (btn_w + gap), y=8)
        self._is_paused = False
        self._btn_stop = TouchButton(
            act, text="STOP", icon="\u25A0", width=btn_w, height=btn_h,
            accent=T.C_MAG_DIM2, fg=T.C_MAG_4, font=P.F_BTN_LG,
            command=self._stop)
        self._btn_stop.place(x=x0 + (btn_w + gap) * 2, y=8)
        self._btn_emg = TouchButton(
            act, text="URGENCE", icon="\u26A0", width=btn_w, height=btn_h,
            accent=T.C_ERR_DEEP, fg="#ffffff", font=P.F_BTN_LG,
            command=self._emergency)
        self._btn_emg.place(x=x0 + (btn_w + gap) * 3, y=8)

        # Bus — subscribe_ui marshal vers le mainloop Tk via self.after(0, ...)
        bus.subscribe_ui("timeline.event_started", self._on_event_start, self)
        bus.subscribe_ui("timeline.event_done",    self._on_event_done, self)
        bus.subscribe_ui("timeline.play",          self._on_timeline_play, self)
        bus.subscribe_ui("timeline.pause",         self._on_timeline_pause, self)
        bus.subscribe_ui("timeline.stop",          self._on_timeline_stop, self)
        # engine.tick (20Hz) -> progress + curseur Timeline progressifs
        bus.subscribe_ui("engine.tick",            self._on_engine_tick, self)

        self._total_events = 0
        self._done_events = 0

    # ── API ───────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Rafraichit l'affichage (appele au changement d'onglet)."""
        name = getattr(project, "name", "")
        self._lbl_project.config(text=name or "— aucun projet —")
        self._load_scenarios()
        self._refresh_timeline()

    def _load_scenarios(self) -> None:
        """Charge la liste des scenarios du projet courant."""
        for w in self._scen_frame.winfo_children():
            w.destroy()
        try:
            self._scenarios = library.list_scenarios() or []
        except Exception:
            self._scenarios = []
        if not self._scenarios:
            tk.Label(self._scen_frame, text="Aucun scenario dans ce projet",
                     bg=T.BG, fg=T.TEXT_DIM, font=P.F_H2,
                     pady=60).pack()
            return
        # scrollable canvas
        canvas = tk.Canvas(self._scen_frame, bg=T.BG,
                           highlightthickness=0, bd=0)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=T.BG)
        canvas.create_window((0, 0), window=inner, anchor="nw",
                             width=P.SCREEN_W - 32)
        inner.bind("<Configure>", lambda e:
                   canvas.configure(scrollregion=canvas.bbox("all")))
        for i, sc in enumerate(self._scenarios):
            row = _ScenarioRow(inner, scenario=sc,
                               is_selected=(i == self._selected_idx),
                               on_tap=lambda idx=i: self._select(idx))
            row.pack(fill="x", pady=1)

    def _select(self, idx: int) -> None:
        self._selected_idx = idx
        self._load_scenarios()
        self._refresh_timeline()

    def _refresh_timeline(self) -> None:
        """Rafraichit la TimelineView avec le scenario selectionne."""
        if 0 <= self._selected_idx < len(self._scenarios):
            sc = self._scenarios[self._selected_idx]
            self._timeline_view.set_scenario(sc)
        else:
            self._timeline_view.clear()

    # ── Actions ───────────────────────────────────────────────────
    def _play(self) -> None:
        if not self._scenarios:
            return
        sc = self._scenarios[self._selected_idx]
        bus.publish("ui.request.play", {"scenario_id": sc.id})
        self._set_log(f"▶ PLAY : {sc.name}")
        self._done_events = 0
        self._total_events = len(sc.timeline_data.get("events", []))

    def _pause(self) -> None:
        """Conserve pour retro-compat ou usage externe."""
        bus.publish("ui.request.pause", {})
        self._set_log("⏸ PAUSE demande")

    def _pause_or_resume(self) -> None:
        """Bascule pause/reprendre selon l'etat engine courant."""
        if self._is_paused:
            # Reprendre : republie ui.request.play (scheduler detecte PAUSED -> resume)
            if not self._scenarios:
                return
            sc = self._scenarios[self._selected_idx]
            bus.publish("ui.request.play", {"scenario_id": sc.id})
            self._set_log(f"▶ REPRENDRE : {sc.name}")
        else:
            bus.publish("ui.request.pause", {})
            self._set_log("⏸ PAUSE demande")

    def _set_pause_button_mode(self, paused: bool) -> None:
        """Configure le bouton entre 'PAUSE' et 'REPRENDRE'."""
        self._is_paused = paused
        if paused:
            self._btn_pause.set_text("REPRENDRE")
            self._btn_pause._icon = "▶"
            self._btn_pause.set_accent(T.C_OK_DIM)
            self._btn_pause.set_fg(T.C_OK)
        else:
            self._btn_pause.set_text("PAUSE")
            self._btn_pause._icon = "⏸"
            self._btn_pause.set_accent(T.C_AMB_DIM)
            self._btn_pause.set_fg(T.C_AMB)

    def _on_timeline_play(self, _payload: dict) -> None:
        self._set_log("▶ Timeline PLAY")
        self._set_pause_button_mode(False)
        # Anti-double-clic : grise le Play tant que la timeline tourne
        self._btn_play.set_disabled(True)

    def _on_timeline_pause(self, _payload: dict) -> None:
        self._set_log("⏸ Timeline PAUSE")
        self._set_pause_button_mode(True)
        # En pause, Play reste grise (utiliser REPRENDRE pour relancer)
        self._btn_play.set_disabled(True)

    def _on_timeline_stop(self, _payload: dict) -> None:
        self._set_log("⏹ Timeline STOP")
        self._set_pause_button_mode(False)
        # Stop -> Play redevient cliquable
        self._btn_play.set_disabled(False)

    def _stop(self) -> None:
        bus.publish("ui.request.stop", {})
        self._progress.set_ratio(0.0)
        self._set_log("⏹ STOP demande")

    def _emergency(self) -> None:
        bus.publish("safety.emergency_stop", {"source": "ui_pi"})
        self._set_log("!! ARRET D'URGENCE !!")

    # ── Bus callbacks ─────────────────────────────────────────────
    def _on_event_start(self, payload: dict) -> None:
        label = payload.get("label") or payload.get("suite_name") or "event"
        t = time.strftime("%H:%M:%S")
        self._set_log(f"{t}  ▶ {label}")

    def _on_event_done(self, _payload: dict) -> None:
        self._done_events += 1
        # On laisse engine.tick gerer la progress (plus fluide) — ici juste log

    def _on_engine_tick(self, payload: dict) -> None:
        """Met a jour progress + curseur Timeline a 20Hz (engine.tick)."""
        elapsed_ms = int(payload.get("elapsed_ms", 0))
        # Progress bar : ratio elapsed / total
        total_ms = self._timeline_view._total_ms or 1
        self._progress.set_ratio(elapsed_ms / total_ms)
        # Curseur Timeline : juste deplace l'item (pas de redraw complet)
        self._timeline_view.set_cursor_ms(elapsed_ms)

    def _set_log(self, msg: str) -> None:
        self._log.config(text=msg)

    # ── Project picker ────────────────────────────────────────────
    def _open_project_picker(self) -> None:
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy()
        self._popup = _ProjectPickerPopup(self, on_pick=self._on_project_pick)

    def _on_project_pick(self, project_path: str) -> None:
        ok = project.load(project_path)
        if ok:
            self.refresh()


class _ScenarioRow(tk.Canvas):
    """Ligne scenario tactile avec selection visuelle."""

    ROW_W = P.SCREEN_W - 32
    ROW_H = 48

    def __init__(self, parent, *, scenario: ScenarioModel,
                 is_selected: bool, on_tap: Callable):
        super().__init__(parent, width=self.ROW_W, height=self.ROW_H,
                         bg=T.BG, highlightthickness=0, bd=0)
        self._sc = scenario
        self._sel = is_selected
        self._on_tap = on_tap
        self._redraw()
        self.bind("<ButtonRelease-1>", lambda _: self._on_tap())

    def _redraw(self) -> None:
        self.delete("all")
        bg = T.C_AMB_DIM2 if self._sel else T.SURFACE_HI
        fg = T.C_AMB if self._sel else T.TEXT_MED
        draw_neu_rect(self, 2, 2, self.ROW_W - 2, self.ROW_H - 2, fill=bg)
        # puce selection
        if self._sel:
            self.create_oval(14, self.ROW_H // 2 - 5,
                             24, self.ROW_H // 2 + 5,
                             fill=T.C_AMB, outline="")
        # nom
        self.create_text(40, self.ROW_H // 2, text=self._sc.name or "—",
                         fill=fg, font=P.F_H2, anchor="w")
        # nb evenements
        ev_count = len(self._sc.timeline_data.get("events", []))
        self.create_text(self.ROW_W - 16, self.ROW_H // 2,
                         text=f"{ev_count} ev.",
                         fill=T.TEXT_DIM, font=P.F_MONO, anchor="e")


class _ProjectPickerPopup(tk.Toplevel):
    """Popup de selection projet (centre 640x380)."""

    def __init__(self, parent, *, on_pick: Callable[[str], None]):
        super().__init__(parent)
        self._on_pick = on_pick
        self.overrideredirect(True)
        self.configure(bg=T.BG)
        w, h = 640, 380
        x = parent.winfo_rootx() + (P.SCREEN_W - w) // 2
        y = parent.winfo_rooty() + (P.SCREEN_H - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        head = tk.Frame(self, bg=T.SIDEBAR, height=48)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="Selection projet",
                 bg=T.SIDEBAR, fg=T.C_AMB, font=P.F_H1
                 ).pack(side="left", padx=P.PAD_LG, pady=P.PAD_SM)
        TouchButton(head, text="X", width=40, height=36,
                    accent=T.SURFACE_HI, fg=T.C_ERR, font=P.F_H2,
                    command=self.destroy
                    ).pack(side="right", padx=P.PAD_SM, pady=6)

        body = tk.Frame(self, bg=T.BG)
        body.pack(fill="both", expand=True, padx=P.PAD_MD, pady=P.PAD_SM)
        projects: List[ProjectInfo] = library.list_projects()
        if not projects:
            tk.Label(body, text="Aucun projet — copier depuis Mac",
                     bg=T.BG, fg=T.TEXT_DIM, font=P.F_H2,
                     pady=60).pack()
            return
        for info in projects:
            row = _ProjectPickerRow(body, info=info,
                                    on_tap=lambda p=info.path: self._pick(p))
            row.pack(fill="x", pady=2)

    def _pick(self, path: str) -> None:
        self._on_pick(path)
        self.destroy()


class _ProjectPickerRow(tk.Canvas):
    """Ligne projet compacte pour le picker."""

    ROW_W = 600
    ROW_H = 52

    def __init__(self, parent, *, info: ProjectInfo, on_tap: Callable):
        super().__init__(parent, width=self.ROW_W, height=self.ROW_H,
                         bg=T.BG, highlightthickness=0, bd=0)
        self._info = info
        self._on_tap = on_tap
        self._redraw()
        self.bind("<ButtonRelease-1>", lambda _: self._on_tap())

    def _redraw(self) -> None:
        self.delete("all")
        draw_neu_rect(self, 2, 2, self.ROW_W - 2, self.ROW_H - 2,
                      fill=T.SURFACE_HI)
        self.create_text(16, self.ROW_H // 2 - 6, text=self._info.name,
                         fill=T.C_AMB, font=P.F_H2, anchor="w")
        meta = f"{self._info.position_count} positions  ·  {self._info.suite_count} suites"
        self.create_text(16, self.ROW_H // 2 + 12, text=meta,
                         fill=T.TEXT_MED, font=P.F_LABEL, anchor="w")


# ═══════════════════════════════════════════════════════════════
# TimelineView — visualisation multi-pistes compacte
# ═══════════════════════════════════════════════════════════════

class TimelineView(tk.Canvas):
    """Vue multi-pistes d'un scenario (read-only).

    Affiche les evenements du scenario sous forme de blocs colores sur
    une grille temporelle. Mise a jour live pendant l'execution :
    - etat PENDING : couleur attenuee
    - etat RUNNING : bordure ambre animee
    - etat DONE    : couleur pleine + liseret vert
    - etat ERROR   : rouge

    Un curseur vertical ambre suit la position courante (cursor_ms).
    """

    LABEL_W   = 92
    TIME_AXIS = 18
    ROW_H_MIN = 20

    def __init__(self, parent, *, width: int = 784, height: int = 118):
        super().__init__(parent, width=width, height=height, bg=T.BG,
                         highlightthickness=0, bd=0)
        self._width, self._height = width, height
        self._scenario: Optional[ScenarioModel] = None
        self._cursor_ms: int = 0
        self._total_ms: int = 0
        self._events_by_track: dict = {}
        self._track_order: list = []
        self._redraw_empty()
        # ecoute l'etat des evenements (subscribe_ui = marshal Tk thread)
        bus.subscribe_ui("timeline.event_started", self._on_evt_state, self)
        bus.subscribe_ui("timeline.event_done",    self._on_evt_state, self)
        # Resize : adapte _width/_height a la taille reelle du widget
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, evt) -> None:
        """Adapte les dimensions a la taille reelle + redraw."""
        if evt.width < 50 or evt.height < 30:
            return
        if evt.width == self._width and evt.height == self._height:
            return
        self._width = evt.width
        self._height = evt.height
        if self._track_order:
            self._redraw()
        else:
            self._redraw_empty()

    # ── API ───────────────────────────────────────────────────────
    @staticmethod
    def _extract_tracks_events(td: dict):
        """Retourne (tracks_data, events_data) depuis un timeline_data.
        events_data peut venir directement de td['events'] ou être collecté
        depuis chaque track (format timeline_model)."""
        tracks_data = td.get("tracks") or []
        events_data = td.get("events") or []
        if not events_data and tracks_data:
            collected = []
            for tr in tracks_data:
                collected.extend(tr.get("events") or [])
            events_data = collected
        return tracks_data, events_data

    @staticmethod
    def _group_by_track(events_data):
        """Regroupe les events par track_id."""
        by_track: dict = {}
        for ev in events_data:
            tid = ev.get("track_id", "track_default")
            by_track.setdefault(tid, []).append(ev)
        return by_track

    @staticmethod
    def _filter_ghost_tracks(track_order, track_meta):
        """Retire les pistes ROBOT dont le robot n'existe plus dans le registry.
        Les pistes non-ROBOT et les pistes robots VIDES sont conservées."""
        try:
            from xrv22.robots.robot_registry import registry
            valid_rids = set(registry.ids())
        except Exception:
            valid_rids = set()
        return [
            t for t in track_order
            if (track_meta.get(t, {}).get("track_type") != "ROBOT"
                or track_meta.get(t, {}).get("robot_id", "") in valid_rids)
        ]

    @staticmethod
    def _compute_total_ms(events_by_track) -> int:
        """Borne max sur l'ensemble des events (au minimum 1000 ms)."""
        total = 0
        for evs in events_by_track.values():
            for ev in evs:
                end = ev.get("start_ms", 0) + ev.get("duration_ms", 0)
                total = max(total, end)
        return max(total, 1000)

    def set_scenario(self, scenario: ScenarioModel) -> None:
        """Parse le timeline_data et redessine."""
        self._scenario = scenario
        td = scenario.timeline_data or {}
        tracks_data, events_data = self._extract_tracks_events(td)
        self._events_by_track = self._group_by_track(events_data)
        track_meta = {t.get("track_id", ""): t for t in tracks_data}
        if tracks_data:
            order = [t.get("track_id", "") for t in tracks_data]
        else:
            order = list(self._events_by_track.keys())
        self._track_order = self._filter_ghost_tracks(order, track_meta)
        self._total_ms = self._compute_total_ms(self._events_by_track)
        self._cursor_ms = 0
        self._redraw()

    def set_cursor_ms(self, ms: int) -> None:
        """Met a jour la position du curseur SANS redraw complet
        (juste un coords() sur l'item line cursor pour eviter le flicker)."""
        self._cursor_ms = max(0, min(self._total_ms, int(ms)))
        x = self._ms_to_x(self._cursor_ms)
        if self.find_withtag("cursor"):
            self.coords("cursor", x, self.TIME_AXIS, x, self._height)
        else:
            # Pas encore de cursor (1er appel apres _redraw) -> on le cree
            self.create_line(x, self.TIME_AXIS, x, self._height,
                             fill=T.C_MAG, width=2, tags="cursor")

    def clear(self) -> None:
        self._scenario = None
        self._events_by_track = {}
        self._track_order = []
        self._total_ms = 0
        self._cursor_ms = 0
        self._redraw_empty()

    # ── Rendu ─────────────────────────────────────────────────────
    def _redraw_empty(self) -> None:
        self.delete("all")
        self.create_rectangle(0, 0, self._width, self._height,
                              fill=T.SURFACE, outline=T.BORDER, width=1)
        self.create_text(self._width // 2, self._height // 2,
                         text="— aucun scenario selectionne —",
                         fill=T.TEXT_DIM, font=P.F_LABEL)

    def _ms_to_x(self, ms: int) -> int:
        usable = self._width - self.LABEL_W - 8
        if self._total_ms <= 0:
            return self.LABEL_W
        return self.LABEL_W + int(usable * ms / self._total_ms)

    def _track_color(self, track_id: str) -> str:
        """Deduit la couleur robot a partir du track_id."""
        if track_id.startswith("track_robot_"):
            rid = track_id.replace("track_", "")
            p = profiles.get(rid)
            if p:
                return p.color
        if "arduino" in track_id:
            return T.C_INFO
        if "sensor" in track_id:
            return T.C_MAG_3
        return T.C_AMB

    def _redraw(self) -> None:
        if not self._track_order:
            self._redraw_empty()
            return
        self.delete("all")
        # fond
        self.create_rectangle(0, 0, self._width, self._height,
                              fill=T.SURFACE, outline=T.BORDER, width=1)
        # zone utile
        x_tracks_start = self.LABEL_W
        y_axis_end = self.TIME_AXIS
        n = len(self._track_order)
        row_h = max(self.ROW_H_MIN,
                    (self._height - self.TIME_AXIS - 4) // n)

        # Axe temporel : lignes verticales chaque seconde
        total_s = max(1, self._total_ms / 1000)
        step_s = max(1, int(total_s / 10))  # ~10 graduations
        for s in range(0, int(total_s) + 1, step_s):
            x = self._ms_to_x(s * 1000)
            self.create_line(x, y_axis_end, x, self._height,
                             fill=T.BORDER, width=1)
            self.create_text(x, y_axis_end // 2,
                             text=f"{s}s", fill=T.TEXT_DIM,
                             font=(T.FONT_MONO, 8), anchor="c")

        # separateur axe / pistes
        self.create_line(0, y_axis_end, self._width, y_axis_end,
                         fill=T.BORDER, width=1)

        # Pistes et evenements
        for i, tid in enumerate(self._track_order):
            y0 = y_axis_end + i * row_h + 2
            y1 = y0 + row_h - 4
            # fond piste
            self.create_rectangle(x_tracks_start, y0,
                                  self._width - 2, y1,
                                  fill=T.BG_DEEP, outline="")
            # label
            color = self._track_color(tid)
            label = tid.replace("track_", "")
            self.create_rectangle(2, y0, self.LABEL_W - 4, y1,
                                  fill=T.SURFACE_HI, outline="")
            self.create_rectangle(2, y0, 6, y1, fill=color, outline="")
            self.create_text(10, (y0 + y1) // 2, text=label,
                             fill=color, font=P.F_LABEL, anchor="w")
            # evenements
            for ev in self._events_by_track.get(tid, []):
                self._draw_event(ev, color, y0 + 2, y1 - 2)

        # Curseur playback
        if self._cursor_ms > 0:
            xc = self._ms_to_x(self._cursor_ms)
            self.create_line(xc, y_axis_end - 2, xc, self._height - 2,
                             fill=T.C_AMB, width=2)

    def _draw_event(self, ev: dict, color: str, y0: int, y1: int) -> None:
        """Dessine un event en fonction de son etat."""
        x0 = self._ms_to_x(ev.get("start_ms", 0))
        x1 = self._ms_to_x(ev.get("start_ms", 0) + ev.get("duration_ms", 0))
        x1 = max(x0 + 4, x1)
        state = ev.get("state", "PENDING")
        if state == "DONE":
            fill, outline = color, T.C_OK
        elif state == "RUNNING":
            fill, outline = color, T.C_AMB
        elif state == "ERROR":
            fill, outline = T.C_ERR_DIM, T.C_ERR
        else:
            fill, outline = T.SURFACE_HI, color
        self.create_rectangle(x0, y0, x1, y1,
                              fill=fill, outline=outline, width=1)
        # label tronque si assez de place
        label = ev.get("label", ev.get("event_type", ""))
        if x1 - x0 > 40 and y1 - y0 > 10:
            self.create_text(x0 + 3, (y0 + y1) // 2, text=label[:14],
                             fill=T.C_AMB, font=(T.FONT_UI, 8), anchor="w")

    # ── Bus ───────────────────────────────────────────────────────
    def _on_evt_state(self, payload: dict) -> None:
        """Met a jour l'etat d'un event specifique (live)."""
        eid = payload.get("event_id")
        if not eid or not self._events_by_track:
            return
        for evs in self._events_by_track.values():
            for ev in evs:
                if ev.get("event_id") == eid:
                    ev["state"] = payload.get("state",
                                              "DONE" if "done" in payload.get("_topic", "")
                                              else "RUNNING")
        # cursor = max start_ms des events termines
        max_ms = 0
        for evs in self._events_by_track.values():
            for ev in evs:
                if ev.get("state") in ("DONE", "RUNNING"):
                    max_ms = max(max_ms,
                                 ev.get("start_ms", 0) + ev.get("duration_ms", 0))
        self._cursor_ms = max_ms
        self._redraw()
