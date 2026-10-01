"""
xr200/ui/diagnostics_panel.py
───────────────────────────────
Panneau Diagnostics — onglet Logs.

Contenu :
  - Tableau état robots (connexion, état safety, positions)
  - Log live avec niveaux colorés
  - Boutons filtres (ALL / SAFETY / ERROR / INFO)
  - Copie diagnostic JSON dans le presse-papiers

Handler logging intégré : les messages Python logger apparaissent
en temps réel dans le Text widget.

Thread model :
  Le TextHandler.emit() est appelé depuis n'importe quel thread.
  Il utilise after(0) pour marshaler l'insert vers le thread UI.
"""
from __future__ import annotations

import json
import logging
import platform
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from xrv22.theme import theme as T
from xrv22.ui.widgets import SectionHeader, HSep, StatusBadge
from xrv22.core.state_store import store
from xrv22.robots.robot_registry import registry
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL

_LOG = get_logger("UI.Diagnostics")

MAX_LOG_LINES = 2000   # Évite une fuite mémoire UI

# Couleurs par niveau de log
LOG_COLORS = {
    "DEBUG":   T.TEXT_DIM,
    "INFO":    T.TEXT_MED,
    "WARNING": T.C_AMB,
    "ERROR":   T.C_ERR,
    "SAFETY":  "#ff6b6b",
    "CRITICAL":"#ff6b6b",
}


class DiagnosticsPanel(tk.Frame):
    """
    Panneau Diagnostics + Logs.
    CC max par méthode : 7.
    """

    def __init__(self, parent: tk.Widget, on_after: Callable) -> None:
        super().__init__(parent, bg=T.BG)
        self._after = on_after
        self._log_filter = "ALL"

        self._build()
        self._install_log_handler()
        self._subscribe()
        self._refresh_robots()

    # ── Construction ─────────────────────────────────────────────

    def _build(self) -> None:
        """CC=4 — Assemble le panneau."""
        # Pane horizontal : gauche=robots, droite=logs
        pane = tk.PanedWindow(self, orient="horizontal",
                               bg=T.BG, sashwidth=6, sashrelief="flat")
        pane.pack(fill="both", expand=True)

        left = tk.Frame(pane, bg=T.BG, width=320)
        right = tk.Frame(pane, bg=T.BG)
        pane.add(left, minsize=240)
        pane.add(right, minsize=400)

        self._build_robot_panel(left)
        self._build_log_panel(right)

    def _build_robot_panel(self, parent: tk.Frame) -> None:
        """CC=4 — Tableau état robots."""
        SectionHeader(parent, "État des robots").pack(
            fill="x", padx=T.PAD_SM, pady=(T.PAD_SM, 0))

        # Treeview robots
        cols = ("state", "port", "home_m", "home_w")
        self._tree = ttk.Treeview(parent, columns=cols, show="headings tree",
                                   selectmode="browse", height=8)
        self._tree.heading("#0",      text="Robot")
        self._tree.heading("state",   text="État")
        self._tree.heading("port",    text="Port")
        self._tree.heading("home_m",  text="🏠 Mach.")
        self._tree.heading("home_w",  text="🔧 Trav.")

        self._tree.column("#0",      width=100, minwidth=80)
        self._tree.column("state",   width=100, anchor="center")
        self._tree.column("port",    width=110)
        self._tree.column("home_m",  width=60, anchor="center")
        self._tree.column("home_w",  width=60, anchor="center")

        vsb = ttk.Scrollbar(parent, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side="left", fill="both", expand=True,
                        padx=(T.PAD_SM, 0), pady=T.PAD_SM)
        vsb.pack(side="left", fill="y", pady=T.PAD_SM)

        # E-STOP global
        HSep(parent).pack(fill="x", pady=T.PAD_XS)
        tk.Button(parent, text="⚡ EMERGENCY STOP ALL",
                   bg=T.C_ERR_DIM, fg=T.C_ERR,
                   activebackground=T.C_ERR_DEEP, activeforeground="#ff6b6b",
                   font=T.F_SECTION, relief="flat", padx=8, pady=6,
                   command=self._emergency_stop_all
                   ).pack(fill="x", padx=T.PAD_SM, pady=T.PAD_SM)

        # Bouton reset
        ttk.Button(parent, text="↺ Reset ERROR / E-STOP sélectionné",
                   command=self._reset_selected
                   ).pack(fill="x", padx=T.PAD_SM, pady=(0, T.PAD_SM))

        # Infos système
        HSep(parent).pack(fill="x")
        self._sys_info = tk.Label(parent, text="",
                                   bg=T.BG, fg=T.TEXT_DIM, font=T.F_CAPTION,
                                   justify="left", padx=T.PAD_SM)
        self._sys_info.pack(anchor="w", pady=T.PAD_XS)
        self._update_sys_info()

    def _build_log_panel(self, parent: tk.Frame) -> None:
        """CC=4 — Panneau log texte avec filtres."""
        # Barre filtres
        bar = tk.Frame(parent, bg=T.SURFACE)
        bar.pack(fill="x")

        tk.Label(bar, text="Logs :", bg=T.SURFACE,
                  fg=T.TEXT_MED, font=T.F_LABEL).pack(side="left", padx=T.PAD_SM)
        for level in ("ALL", "INFO", "WARNING", "ERROR", "SAFETY"):
            col = LOG_COLORS.get(level, T.TEXT_MED)
            b = tk.Button(bar, text=level,
                           bg=T.SURFACE, fg=col,
                           activebackground=T.C_MAG_DIM2, activeforeground=col,
                           relief="flat", padx=6, pady=3, font=T.F_CAPTION,
                           command=lambda l=level: self._set_filter(l))
            b.pack(side="left", padx=2, pady=2)

        ttk.Button(bar, text="🗑 Effacer",
                   command=self._clear_logs).pack(side="right", padx=T.PAD_SM)
        ttk.Button(bar, text="📋 Copier diag.",
                   command=self._copy_diagnostic).pack(side="right", padx=3)

        # Text widget
        txt_frame = tk.Frame(parent, bg=T.BG_DEEP)
        txt_frame.pack(fill="both", expand=True)

        vsb = ttk.Scrollbar(txt_frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        self._log_text = tk.Text(
            txt_frame,
            bg=T.BG_DEEP, fg=T.TEXT_MED,
            font=T.F_MONO_SM,
            wrap="none",
            state="disabled",
            insertbackground=T.C_AMB,
            yscrollcommand=vsb.set,
            padx=T.PAD_SM,
        )
        self._log_text.pack(fill="both", expand=True)
        vsb.config(command=self._log_text.yview)

        # Tags couleur par niveau
        for level, color in LOG_COLORS.items():
            self._log_text.tag_config(level, foreground=color)

    # ── État robots ──────────────────────────────────────────────

    def _refresh_robots(self) -> None:
        """CC=6 — Met à jour le tableau état robots."""
        for item in self._tree.get_children():
            self._tree.delete(item)

        for robot_id in registry.ids():
            snap = store.get_robot(robot_id)
            if snap is None:
                continue
            hm = "✅" if snap.home_machine_set else "❌"
            hw = "✅" if snap.home_work_set else "❌"
            self._tree.insert("", "end", iid=robot_id,
                               text=robot_id,
                               values=(snap.state, snap.port or "—", hm, hw),
                               tags=(snap.state,))
            self._tree.tag_configure(snap.state,
                                      foreground=T.state_text_color(snap.state))

    def _emergency_stop_all(self) -> None:
        """CC=2 — E-STOP global."""
        registry.emergency_stop_all()

    def _reset_selected(self) -> None:
        """CC=5 — Reset le robot sélectionné dans le treeview."""
        sel = self._tree.selection()
        if not sel:
            return
        robot_id = sel[0]
        ctrl = registry.get(robot_id)
        if ctrl is None:
            return
        if ctrl.state == "EMERGENCY_STOP":
            ctrl.reset_emergency()
        elif ctrl.state == "ERROR":
            ctrl.reset_error()
        self._refresh_robots()

    def _update_sys_info(self) -> None:
        """CC=2 — Affiche les infos système en bas du panneau robots."""
        sys_snap = store.get_system()
        sim = "⚙️ Simulation" if sys_snap.simulation_mode else "🔌 Hardware"
        info = (f"Projet : {sys_snap.project_name}\n"
                f"Mode : {sim}\n"
                f"Exec : {sys_snap.execution_state}\n"
                f"OS : {platform.system()} {platform.release()}")
        self._sys_info.config(text=info)

    # ── Log handler ──────────────────────────────────────────────

    def _install_log_handler(self) -> None:
        """CC=3 — Installe un handler logging vers le Text widget."""
        handler = _UILogHandler(self._append_log, self._after)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s.%(msecs)03d] [%(name)-18s] [%(levelname)-7s] %(message)s",
            datefmt="%H:%M:%S"
        ))
        handler.setLevel(logging.DEBUG)
        logging.getLogger("XR200").addHandler(handler)

    def _append_log(self, msg: str, level: str) -> None:
        """CC=5 — Insère une ligne dans le Text widget (thread UI uniquement)."""
        if self._log_filter != "ALL" and level != self._log_filter:
            return

        self._log_text.config(state="normal")
        self._log_text.insert("end", msg + "\n", level)

        # Limite le nombre de lignes
        lines = int(self._log_text.index("end-1c").split(".")[0])
        if lines > MAX_LOG_LINES:
            self._log_text.delete("1.0", f"{lines - MAX_LOG_LINES}.0")

        self._log_text.config(state="disabled")
        self._log_text.see("end")

    def _set_filter(self, level: str) -> None:
        """CC=2 — Change le filtre de log."""
        self._log_filter = level

    def _clear_logs(self) -> None:
        """CC=2 — Efface tous les logs."""
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ── Diagnostic JSON ──────────────────────────────────────────

    def _copy_diagnostic(self) -> None:
        """CC=4 — Copie un rapport diagnostic JSON dans le presse-papiers."""
        sys_snap = store.get_system()
        robots_data = {}
        for robot_id in registry.ids():
            snap = store.get_robot(robot_id)
            if snap:
                robots_data[robot_id] = {
                    "state":   snap.state,
                    "port":    snap.port,
                    "error":   snap.last_error,
                }

        report = {
            "version":    "XR200 V21",
            "system":     {
                "simulation": sys_snap.simulation_mode,
                "project":    sys_snap.project_name,
                "execution":  sys_snap.execution_state,
            },
            "robots": robots_data,
        }
        try:
            self.clipboard_clear()
            self.clipboard_append(json.dumps(report, indent=2, ensure_ascii=False))
            _LOG.info("Diagnostic copié dans le presse-papiers")
        except tk.TclError:
            _LOG.warning("Impossible d'accéder au presse-papiers")

    # ── Souscriptions bus ────────────────────────────────────────

    def _subscribe(self) -> None:
        """CC=2 — Souscriptions."""
        bus.subscribe("ui.refresh",          self._on_refresh)
        bus.subscribe("robot.state_changed", self._on_refresh)
        bus.subscribe("robot.connected",     self._on_refresh)
        bus.subscribe("robot.disconnected",  self._on_refresh)

    def destroy(self) -> None:
        bus.unsubscribe_object(self)
        super().destroy()

    def _on_refresh(self, _: dict) -> None:
        """CC=3 — Debounce refresh vers thread UI."""
        if getattr(self, "_refresh_pending", False):
            return
        self._refresh_pending = True
        self._after(50, self._debounced_refresh)

    def _debounced_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh_robots()
        self._update_sys_info()


# ── Handler logging → Tkinter ─────────────────────────────────────

class _UILogHandler(logging.Handler):
    """Handler logging thread-safe vers Text widget."""

    def __init__(self, append_fn: Callable, after_fn: Callable) -> None:
        super().__init__()
        self._append = append_fn
        self._after  = after_fn

    def emit(self, record: logging.LogRecord) -> None:
        """CC=4 — Formate et envoie la ligne vers le thread UI."""
        try:
            msg = self.format(record)
            level = record.levelname
            self._after(0, lambda m=msg, l=level: self._append(m, l))
        except Exception:
            self.handleError(record)
