"""
xr200/ui/status_bar.py  — V21
Corrections :
  - Segment état robot actif (READY/MOVING/ESTOP/TORQUE_OFF) avec couleurs
  - Polling 500ms fallback (comme V17)
  - Abonné à robot.state_changed pour refresh immédiat
  - flash_estop() exposé pour main_window
CC max : 5
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from xrv22.theme import theme as T
from xrv22.services.event_bus import bus
from xrv22.core.state_store import store
from xrv22.robots.robot_registry import registry
from xrv22.services.logger import get_logger

_LOG = get_logger("UI.StatusBar")

_STATE_COLOR = {
    "READY":          "#39d353",
    "MOVING":         "#00d2e6",
    "ERROR":          "#ff4757",
    "EMERGENCY_STOP": "#ff4757",
    "TORQUE_OFF":     "#ffb347",
    "CONNECTING":     "#ffb347",
    "DISCONNECTED":   "#4a5568",
    "IDLE":           "#4a5568",
}
_STATE_ICON = {
    "READY":          "●",
    "MOVING":         "◉",
    "ERROR":          "⊗",
    "EMERGENCY_STOP": "🛑",
    "TORQUE_OFF":     "◎",
    "CONNECTING":     "◌",
    "DISCONNECTED":   "⚬",
    "IDLE":           "⚬",
}


class StatusBar(tk.Frame):
    """Barre de statut bas de fenêtre — V21."""

    def __init__(self, parent: tk.Widget, on_after: Callable) -> None:
        super().__init__(parent, bg=T.SURFACE, height=T.STATUSBAR_H)
        self._after = on_after
        self.pack_propagate(False)
        self._estop_active = False
        self._estop_flashing = False

        self._build()
        self._subscribe()
        self._poll()   # démarrage polling 500ms (V17 style)

    def _build(self) -> None:
        # Accent gauche
        tk.Frame(self, bg=T.C_MAG, width=3).pack(side="left", fill="y")

        # Exécution engine
        self._exec_lbl = tk.Label(self, text="⚫ IDLE",
                                   bg=T.SURFACE, fg=T.TEXT_DIM, font=T.F_CONTROL,
                                   padx=T.PAD_SM)
        self._exec_lbl.pack(side="left")

        _sep(self)

        # FIX V21: État safety du robot actif
        self._robot_state_lbl = tk.Label(self, text="⚬ —",
                                          bg=T.SURFACE, fg=T.TEXT_DIM, font=T.F_CONTROL,
                                          padx=T.PAD_SM)
        self._robot_state_lbl.pack(side="left")

        _sep(self)

        # Robot actif
        self._robot_lbl = tk.Label(self, text="",
                                    bg=T.SURFACE, fg=T.TEXT_MED, font=T.F_CAPTION,
                                    padx=T.PAD_SM)
        self._robot_lbl.pack(side="left")

        _sep(self)

        # Message contextuel
        self._msg_var = tk.StringVar(value="Prêt")
        self._msg_lbl = tk.Label(self, textvariable=self._msg_var,
                                  bg=T.SURFACE, fg=T.TEXT_MED, font=T.F_CAPTION,
                                  padx=T.PAD_SM)
        self._msg_lbl.pack(side="left")

        # E-STOP indicator — droite
        self._estop_lbl = tk.Label(self, text="",
                                    bg=T.SURFACE, fg=T.C_ERR, font=T.F_BADGE,
                                    padx=T.PAD_SM)
        self._estop_lbl.pack(side="right")

        _sep(self)

        # Mode simulation — droite
        self._sim_lbl = tk.Label(self, text="",
                                  bg=T.SURFACE, fg=T.C_AMB, font=T.F_CAPTION,
                                  padx=T.PAD_SM)
        self._sim_lbl.pack(side="right")

    # ── API publique ─────────────────────────────────────────────────────────

    def set_message(self, msg: str, level: str = "info") -> None:
        color_map = {"info": T.TEXT_MED, "ok": T.C_OK, "warning": T.C_AMB, "error": T.C_ERR}
        self._msg_var.set(msg)
        self._msg_lbl.config(fg=color_map.get(level, T.TEXT_MED))

    def flash_estop(self) -> None:
        """Déclenche le flash E-STOP (appelé depuis main_window)."""
        if not self._estop_flashing:
            self._estop_flashing = True
            self._estop_lbl.config(text=" ⚡ E-STOP ")
            self._toggle_estop_flash()

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """CC=5 — Met à jour tous les segments."""
        try:
            sys_snap = store.get_system()
            self._update_exec_state(sys_snap.execution_state)
            self._update_robot_state_label(sys_snap.active_robot_id)
            self._update_robot_id_label(sys_snap.active_robot_id)
            self._update_estop()
            sim_text = "⚙️  Simulation" if sys_snap.simulation_mode else ""
            self._sim_lbl.config(text=sim_text)
        except Exception as exc:
            _LOG.debug("Erreur refresh status bar: %s", exc)

    def _update_exec_state(self, state: str) -> None:
        icons = {"IDLE": "⚫", "RUNNING": "🟢", "PAUSED": "🟡", "STOPPED": "🔴"}
        icon  = icons.get(state, "⚫")
        color = T.state_text_color(state) if state in T.STATE_COLORS else T.TEXT_DIM
        self._exec_lbl.config(text=f"{icon} {state}", fg=color)

    def _update_robot_state_label(self, robot_id: str) -> None:
        """FIX V21: affiche l'état safety du robot actif."""
        snap = store.get_robot(robot_id) if robot_id else None
        if snap and snap.state:
            state = snap.state
            icon  = _STATE_ICON.get(state, "⚬")
            color = _STATE_COLOR.get(state, T.TEXT_DIM)
            self._robot_state_lbl.config(text=f"{icon} {state}", fg=color)
        else:
            self._robot_state_lbl.config(text="⚬ —", fg=T.TEXT_DIM)

    def _update_robot_id_label(self, robot_id: str) -> None:
        snap = store.get_robot(robot_id) if robot_id else None
        if snap:
            icon = "🟢" if snap.connected else "🔴"
            self._robot_lbl.config(text=f"{icon} {robot_id}", fg=T.TEXT_MED)
        else:
            self._robot_lbl.config(text="", fg=T.TEXT_DIM)

    def _update_estop(self) -> None:
        try:
            robots = registry.all()
            estop_on = any(
                store.get_robot(c.robot_id) and
                store.get_robot(c.robot_id).state == "EMERGENCY_STOP"
                for c in robots)
            if estop_on and not self._estop_flashing:
                self.flash_estop()
            elif not estop_on:
                self._estop_flashing = False
                self._estop_lbl.config(text="")
        except Exception as exc:
            _LOG.debug("Erreur check E-STOP: %s", exc)

    def _toggle_estop_flash(self) -> None:
        self._estop_active = not self._estop_active
        color = T.C_ERR if self._estop_active else T.C_ERR_DEEP
        self._estop_lbl.config(fg=color)
        try:
            robots = registry.all()
            still_estop = any(
                store.get_robot(c.robot_id) and
                store.get_robot(c.robot_id).state == "EMERGENCY_STOP"
                for c in robots)
        except Exception:
            still_estop = False
        if still_estop:
            self._after(400, self._toggle_estop_flash)
        else:
            self._estop_flashing = False
            self._estop_lbl.config(text="")

    def _poll(self) -> None:
        """FIX V21: polling 500ms fallback (comme V17)."""
        self._refresh()
        self._after(500, self._poll)

    # ── Bus ──────────────────────────────────────────────────────────────────

    def _subscribe(self) -> None:
        bus.subscribe("ui.refresh",            self._on_refresh)
        bus.subscribe("robot.state_changed",   self._on_refresh)   # FIX V21
        bus.subscribe("robot.connected",       self._on_refresh)
        bus.subscribe("robot.disconnected",    self._on_refresh)
        bus.subscribe("safety.emergency_stop", self._on_refresh)
        bus.subscribe("engine.tick",           self._on_tick)

    def destroy(self) -> None:
        """Nettoyage des souscriptions bus avant destruction."""
        bus.unsubscribe_object(self)
        super().destroy()

    def _on_refresh(self, _: dict) -> None:
        if getattr(self, "_refresh_pending", False):
            return
        self._refresh_pending = True
        self._after(50, self._debounced_refresh)

    def _debounced_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh()

    def _on_tick(self, payload: dict) -> None:
        sys_snap = store.get_system()
        self._after(0, lambda: self._update_exec_state(sys_snap.execution_state))


def _sep(parent: tk.Frame) -> None:
    tk.Frame(parent, bg=T.BORDER, width=1).pack(side="left", fill="y", pady=6)
