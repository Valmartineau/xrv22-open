"""
xrv22/ui_pi/screen_cockpit.py
──────────────────────────────
Cockpit d'execution : un projet charge, pilotage timeline sur ecran tactile.

Layout (800 x 480) :
  ┌────────── header 52 ───────────┐
  ├────────── status robots 120 ──┤
  ├────────── scenario 78 ────────┤
  ├────────── actions 170 ────────┤
  └────────── log 60 ─────────────┘

Ecoute le bus d'evenements xrv22 pour :
  - timeline.event_started / event_done  → mise a jour progression
  - robot.state_changed                  → mise a jour tuiles
  - robot.positions                      → rafraichissement positions live
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, List, Optional

from xrv22.core.state_store import store
from xrv22.library.library_manager import library
from xrv22.library.models import ScenarioModel
from xrv22.robots.robot_profiles import profiles
from xrv22.robots.robot_registry import registry
from xrv22.services.event_bus import bus
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.widgets_pi import (HeaderBar, ProgressBar, StatusTile,
                                    TouchButton, draw_neu_rect)


class ScreenCockpit(tk.Frame):
    """Vue principale d'execution : status, scenario, actions, log."""

    def __init__(self, parent, on_back: Callable[[], None]):
        super().__init__(parent, bg=T.BG, width=P.SCREEN_W,
                         height=P.SCREEN_H - P.H_HEADER)
        self._on_back = on_back
        self._scenarios: List[ScenarioModel] = []
        self._scenario_idx = 0
        self._tiles = {}

        # ── Header ────────────────────────────────────────────────
        self.header = HeaderBar(self, title="Cockpit", on_back=on_back)
        self.header.pack(side="top", fill="x")

        # ── Status robots (zone horizontale, 2 tuiles cote a cote) ─
        self._status_frame = tk.Frame(self, bg=T.BG, height=P.H_STATUS)
        self._status_frame.pack(side="top", fill="x",
                                padx=P.PAD_MD, pady=(P.PAD_SM, 0))
        self._status_frame.pack_propagate(False)

        # ── Scenario (selecteur + progress bar) ──────────────────
        self._sc_frame = tk.Frame(self, bg=T.BG, height=P.H_SCENARIO)
        self._sc_frame.pack(side="top", fill="x",
                            padx=P.PAD_MD, pady=P.PAD_SM)
        self._sc_frame.pack_propagate(False)
        tk.Label(self._sc_frame, text="SCENARIO",
                 bg=T.BG, fg=T.C_MAG_3, font=P.F_LABEL).place(x=6, y=2)
        self._sc_name = tk.Label(self._sc_frame, text="—",
                                 bg=T.BG, fg=T.C_AMB, font=P.F_H2)
        self._sc_name.place(x=6, y=18)
        self._progress = ProgressBar(self._sc_frame,
                                     width=P.SCREEN_W - 32, height=28)
        self._progress.place(x=6, y=44)

        # Boutons prev/next scenario (visibles si plus d'un)
        self._btn_prev = TouchButton(self._sc_frame, text="\u2039",
                                     width=48, height=32, font=P.F_H2,
                                     command=self._prev_scenario)
        self._btn_next = TouchButton(self._sc_frame, text="\u203A",
                                     width=48, height=32, font=P.F_H2,
                                     command=self._next_scenario)

        # ── Actions (PLAY/PAUSE/STOP/EMERGENCY) ───────────────────
        self._act_frame = tk.Frame(self, bg=T.BG, height=P.H_ACTIONS)
        self._act_frame.pack(side="top", fill="x",
                             padx=P.PAD_MD, pady=P.PAD_SM)
        self._act_frame.pack_propagate(False)

        btn_w, btn_h = 168, 140
        x0 = (P.SCREEN_W - (btn_w * 4 + 12 * 3) - 16) // 2
        self._btn_play = TouchButton(self._act_frame, text="PLAY",
                                     icon="\u25B6", width=btn_w, height=btn_h,
                                     accent=T.C_OK_DIM, fg=T.C_OK,
                                     font=P.F_BTN_LG, command=self._play)
        self._btn_play.place(x=x0, y=10)
        self._btn_pause = TouchButton(self._act_frame, text="PAUSE",
                                      icon="\u23F8", width=btn_w, height=btn_h,
                                      accent=T.C_AMB_DIM, fg=T.C_AMB,
                                      font=P.F_BTN_LG, command=self._pause)
        self._btn_pause.place(x=x0 + (btn_w + 12), y=10)
        self._btn_stop = TouchButton(self._act_frame, text="STOP",
                                     icon="\u25A0", width=btn_w, height=btn_h,
                                     accent=T.C_MAG_DIM2, fg=T.C_MAG_4,
                                     font=P.F_BTN_LG, command=self._stop)
        self._btn_stop.place(x=x0 + (btn_w + 12) * 2, y=10)
        self._btn_emg = TouchButton(self._act_frame, text="ARRET\nURGENCE",
                                    icon="\u26A0", width=btn_w, height=btn_h,
                                    accent=T.C_ERR_DEEP, fg="#ffffff",
                                    font=P.F_BTN_LG, command=self._emergency)
        self._btn_emg.place(x=x0 + (btn_w + 12) * 3, y=10)

        # ── Log (dernier evenement) ───────────────────────────────
        self._log_frame = tk.Frame(self, bg=T.SIDEBAR, height=P.H_LOG)
        self._log_frame.pack(side="bottom", fill="x")
        self._log_frame.pack_propagate(False)
        self._log_label = tk.Label(self._log_frame, text="Pret.",
                                   bg=T.SIDEBAR, fg=T.TEXT_MED,
                                   font=P.F_MONO, anchor="w")
        self._log_label.pack(fill="x", padx=P.PAD_LG, pady=P.PAD_MD)

        # Souscriptions bus
        bus.subscribe("timeline.event_started", self._on_event_start)
        bus.subscribe("timeline.event_done",    self._on_event_done)
        bus.subscribe("timeline.play",          lambda _: self._log("Timeline PLAY"))
        bus.subscribe("timeline.pause",         lambda _: self._log("Timeline PAUSE"))
        bus.subscribe("timeline.stop",          lambda _: self._log("Timeline STOP"))
        bus.subscribe("robot.state_changed",    self._on_robot_state)

        self._total_events = 0
        self._done_events = 0

        # rafraichissement positions live
        self.after(300, self._tick_positions)

    # ── API publique ──────────────────────────────────────────────
    def load_project(self, project_name: str) -> None:
        """Rafraichit l'affichage pour le projet courant."""
        self.header.set_title(project_name)
        self._refresh_tiles()
        self._refresh_scenarios()
        self._progress.set_ratio(0.0)
        self._log("Projet charge.")

    # ── Tuiles robots ─────────────────────────────────────────────
    def _refresh_tiles(self) -> None:
        """Recree les tuiles robots a partir du registry."""
        for w in self._status_frame.winfo_children():
            w.destroy()
        self._tiles.clear()
        robots = list(registry.all())
        if not robots:
            tk.Label(self._status_frame, text="Aucun robot dans ce projet",
                     bg=T.BG, fg=T.TEXT_DIM, font=P.F_H2).pack(pady=40)
            return
        for i, ctrl in enumerate(robots[:2]):
            profile = profiles.get(ctrl.robot_id)
            accent = profile.color if profile else T.C_MAG
            name = profile.name if profile else ctrl.robot_id
            snap = store.get_robot(ctrl.robot_id)
            state = snap.state if snap else "IDLE"
            tile = StatusTile(self._status_frame,
                              robot_id=ctrl.robot_id,
                              name=name,
                              state=state,
                              accent=accent)
            tile.grid(row=0, column=i, padx=P.PAD_SM, pady=0, sticky="w")
            self._tiles[ctrl.robot_id] = tile

    # ── Scenarios ─────────────────────────────────────────────────
    def _refresh_scenarios(self) -> None:
        """Charge la liste des scenarios du projet."""
        self._scenarios = library.list_scenarios() or []
        self._scenario_idx = 0
        if len(self._scenarios) > 1:
            self._btn_prev.place(x=P.SCREEN_W - 180, y=6)
            self._btn_next.place(x=P.SCREEN_W - 80, y=6)
        else:
            self._btn_prev.place_forget()
            self._btn_next.place_forget()
        self._update_scenario_label()

    def _update_scenario_label(self) -> None:
        if not self._scenarios:
            self._sc_name.config(text="— aucun scenario —")
            return
        sc = self._scenarios[self._scenario_idx]
        suffix = f"  ({self._scenario_idx + 1}/{len(self._scenarios)})" \
            if len(self._scenarios) > 1 else ""
        self._sc_name.config(text=f"{sc.name}{suffix}")

    def _prev_scenario(self) -> None:
        if not self._scenarios:
            return
        self._scenario_idx = (self._scenario_idx - 1) % len(self._scenarios)
        self._update_scenario_label()

    def _next_scenario(self) -> None:
        if not self._scenarios:
            return
        self._scenario_idx = (self._scenario_idx + 1) % len(self._scenarios)
        self._update_scenario_label()

    # ── Actions timeline ──────────────────────────────────────────
    def _play(self) -> None:
        bus.publish("ui.request.play", {})
        self._log("Demande : PLAY")

    def _pause(self) -> None:
        bus.publish("ui.request.pause", {})
        self._log("Demande : PAUSE")

    def _stop(self) -> None:
        bus.publish("ui.request.stop", {})
        self._log("Demande : STOP")
        self._progress.set_ratio(0.0)

    def _emergency(self) -> None:
        bus.publish("safety.emergency_stop", {"source": "ui_pi"})
        self._log("!! ARRET D'URGENCE !!")

    # ── Bus callbacks ─────────────────────────────────────────────
    def _on_event_start(self, payload: dict) -> None:
        label = payload.get("label") or payload.get("suite_name") or "event"
        t = time.strftime("%H:%M:%S")
        self._log(f"{t}  ▶ {label}")
        if self._total_events:
            self._progress.set_ratio(self._done_events / self._total_events)

    def _on_event_done(self, payload: dict) -> None:
        self._done_events += 1
        if self._total_events:
            self._progress.set_ratio(self._done_events / self._total_events)

    def _on_robot_state(self, payload: dict) -> None:
        rid = payload.get("robot_id")
        state = payload.get("state")
        tile = self._tiles.get(rid) if rid else None
        if tile and state:
            tile.update_state(state)

    # ── Positions live ────────────────────────────────────────────
    def _tick_positions(self) -> None:
        """Rafraichit les positions courantes toutes les 300ms."""
        for rid, tile in self._tiles.items():
            snap = store.get_robot(rid)
            if snap and snap.positions:
                # positions est un dict {motor_id: valeur}, trier par id
                ordered = [snap.positions[k] for k in sorted(snap.positions)]
                tile.update_positions(ordered)
        self.after(300, self._tick_positions)

    def _log(self, msg: str) -> None:
        self._log_label.config(text=msg)
