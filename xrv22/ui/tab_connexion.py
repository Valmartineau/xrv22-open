"""
xrv22/ui/tab_connexion.py  — V22
Layout V17 : 3 colonnes (Formulaire | Actions rapides | Statut)
+ Pilotage intégré en bas.
CC max : 10
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Callable, Dict, Optional

from xrv22.theme import theme as T
from xrv22.ui.widgets import NeuFrame, NeuButton, StatusBadge, SectionHeader, HSep, label
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger
from xrv22.core.state_store import store
from xrv22.robots.robot_registry import registry
from xrv22.robots.robot_controller import calculate_auto_duration
from xrv22.ui.keyboard import tooltip
from xrv22.library.library_manager import library
from xrv22.library.models import RobotConfigModel, PositionModel

_LOG = get_logger("UI.Connexion")


def apply_couplings(positions: Dict[int, int],
                    enabled: bool, invert: bool,
                    ratio: float, offset: int, center: int) -> Dict[int, int]:
    """Couplage axe 2 → axe 3 (formule V17).

    pos_slave = center + sign × ratio × (pos_master - center) + offset
    """
    if not enabled or 2 not in positions:
        return positions
    out = dict(positions)
    sign = -1.0 if invert else 1.0
    mpos = positions[2]
    spos = int(round(center + sign * ratio * (mpos - center) + offset))
    spos = max(0, min(4095, spos))
    out[3] = spos
    return out

try:
    from serial.tools import list_ports
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False

try:
    import dynamixel_sdk  # noqa: F401
    DXL_OK = True
except ImportError:
    DXL_OK = False


class ConnexionTab(tk.Frame):
    """Onglet Connexion & Pilotage — V22 (layout V17)."""

    def __init__(self, parent: tk.Widget, on_after: Callable) -> None:
        super().__init__(parent, bg=T.BG)
        self._after = on_after
        self._slider_vars: Dict[int, tk.IntVar] = {}
        self._slider_updating = False

        # Mode direct + throttle
        self._direct_var = tk.BooleanVar(value=False)
        self._direct_throttle_id: Optional[str] = None
        self._direct_pending = False

        # Paramètres mouvement (V17)
        self._hz_var  = tk.IntVar(value=60)
        self._vel_var = tk.IntVar(value=120)
        self._acc_var = tk.IntVar(value=40)
        self._home_dur_var = tk.DoubleVar(value=3.0)

        # Couplage axes 2-3
        self._c_enabled = tk.BooleanVar(value=True)
        self._c_invert = tk.BooleanVar(value=False)
        self._c_ratio = tk.DoubleVar(value=1.0)
        self._c_offset = tk.IntVar(value=0)
        self._c_center = tk.IntVar(value=2048)

        self._robot_color = T.C_AMB  # couleur du robot actif

        self._restore_coupling_from_config()
        self._build()
        self._subscribe()
        self._after(100, self._refresh)
        self._after(200, self._sync_port_from_config)
        self._after(300, self._update_robot_colors)
        self._after(1000, self._poll_positions)

    # ── Construction ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        pane = ttk.PanedWindow(self, orient="vertical")
        pane.pack(fill="both", expand=True)

        # Panneau haut : config robot
        top_frame = tk.Frame(pane, bg=T.BG)
        pane.add(top_frame, weight=0)
        self._build_top_section(top_frame)

        # Panneau bas : sliders
        bot_frame = tk.Frame(pane, bg=T.BG)
        pane.add(bot_frame, weight=1)
        self._build_sliders_area(bot_frame)

    def _build_top_section(self, container: tk.Widget = None) -> None:
        """CC=3 — Section haute : robot + 3 colonnes (form | actions | statut)."""
        parent = container or self
        top = tk.Frame(parent, bg=T.BG, padx=T.PAD_MD, pady=T.PAD_SM)
        top.pack(fill="both", expand=True)

        # ── Ligne robot actif (Button + popup Menu — compatible macOS) ──
        robot_row = tk.Frame(top, bg=T.BG)
        robot_row.pack(fill="x", pady=(0, 6))
        tk.Label(robot_row, text="Robot actif :", bg=T.BG, fg=T.TEXT,
                 font=(T.FONT_UI, 12, "bold")).pack(side="left", padx=(0, 6))
        self._robot_var = tk.StringVar()
        ids = sorted(registry.ids()) or ["—"]
        self._robot_var.set(ids[0])

        self._robot_btn = tk.Label(
            robot_row, textvariable=self._robot_var,
            bg=T.SURFACE, fg=T.C_AMB, font=(T.FONT_UI, 12, "bold"),
            highlightthickness=1, highlightbackground=T.TEXT_DIM,
            relief="flat", width=22, anchor="w", cursor="hand2",
            padx=6, pady=2)
        self._robot_btn.pack(side="left")
        self._robot_btn.bind("<Button-1>", lambda _: self._show_robot_popup())
        # Indicateur ▾
        self._arrow_lbl = tk.Label(robot_row, text="▾", bg=T.SURFACE, fg=T.C_AMB,
                                   font=(T.FONT_UI, 10), cursor="hand2")
        self._arrow_lbl.pack(side="left")
        self._arrow_lbl.bind("<Button-1>", lambda _: self._show_robot_popup())

        # ── 3 colonnes : Connexion | Actions rapides | Statut ───────
        cols = tk.Frame(top, bg=T.BG)
        cols.pack(fill="x")

        self._build_form_column(cols)
        self._build_actions_column(cols)
        self._build_status_column(cols)

        # ── Paramètres mouvement (sous Connexion robot) ──────────
        self._build_motion_params(top)

    def _build_motion_params(self, parent: tk.Frame) -> None:
        """CC=3 — Bloc Paramètres mouvement (Hz, Vélocité, Accélération) — V17."""
        mp = tk.LabelFrame(parent, text="Paramètres mouvement",
                           bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                           padx=10, pady=6)
        mp.pack(fill="x", pady=(8, 0))
        self._motion_lf = mp

        inner = tk.Frame(mp, bg=T.SURFACE)
        inner.pack(fill="x")

        # Durée Home (temps de déplacement par défaut) — EN PREMIER
        tk.Label(inner, text="Durée (s) :", bg=T.SURFACE, fg=T.TEXT,
                 font=T.F_CONTROL).pack(side="left")
        dur_spin = tk.Spinbox(inner, from_=0.5, to=10.0, increment=0.5,
                              textvariable=self._home_dur_var, width=5,
                              font=T.F_MONO_MD, bg=T.SURFACE, fg=T.TEXT,
                              buttonbackground=T.SURFACE,
                              insertbackground=T.TEXT,
                              command=self._on_motion_params_changed)
        dur_spin.pack(side="left", padx=(2, 16))
        tooltip(dur_spin, "Durée par défaut des mouvements (0.5–10 s)")

        # Hertz (fréquence de la boucle d'interpolation) — grisé
        tk.Label(inner, text="Hertz :", bg=T.SURFACE, fg=T.TEXT_DIM,
                 font=T.F_CONTROL).pack(side="left")
        hz_spin = tk.Spinbox(inner, from_=30, to=120, increment=5,
                             textvariable=self._hz_var, width=5,
                             font=T.F_MONO_MD, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                             buttonbackground=T.SURFACE,
                             insertbackground=T.TEXT_DIM,
                             command=self._on_motion_params_changed)
        hz_spin.pack(side="left", padx=(2, 16))
        tooltip(hz_spin, "Fréquence d'interpolation (30–120 Hz)")

        # Vélocité (Profile Velocity — registre 112) — grisé
        tk.Label(inner, text="Vélocité :", bg=T.SURFACE, fg=T.TEXT_DIM,
                 font=T.F_CONTROL).pack(side="left")
        vel_spin = tk.Spinbox(inner, from_=10, to=500, increment=10,
                              textvariable=self._vel_var, width=5,
                              font=T.F_MONO_MD, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                              buttonbackground=T.SURFACE,
                              insertbackground=T.TEXT_DIM,
                              command=self._on_motion_params_changed)
        vel_spin.pack(side="left", padx=(2, 16))
        tooltip(vel_spin, "Vitesse max moteurs (10–500 rev/min)")

        # Accélération (Profile Acceleration — registre 108) — grisé
        tk.Label(inner, text="Accélération :", bg=T.SURFACE, fg=T.TEXT_DIM,
                 font=T.F_CONTROL).pack(side="left")
        acc_spin = tk.Spinbox(inner, from_=5, to=200, increment=5,
                              textvariable=self._acc_var, width=5,
                              font=T.F_MONO_MD, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                              buttonbackground=T.SURFACE,
                              insertbackground=T.TEXT_DIM,
                              command=self._on_motion_params_changed)
        acc_spin.pack(side="left", padx=(2, 0))
        tooltip(acc_spin, "Accélération moteurs (5–200 rev/min²)")

    def _on_motion_params_changed(self) -> None:
        """Applique les paramètres mouvement au robot actif."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        vel = self._vel_var.get()
        acc = self._acc_var.get()
        dur = self._home_dur_var.get()
        ctrl.set_motion_params(self._hz_var.get(), vel, acc, home_duration=dur)
        _LOG.info("[%s] Paramètres mouvement : Hz=%d  Vel=%d  Acc=%d  Durée=%.1fs",
                  self._robot_var.get(), self._hz_var.get(), vel, acc, dur)

    def _sync_motion_params_from_ctrl(self) -> None:
        """Restaure les spinboxes depuis les paramètres du controller actif."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        self._hz_var.set(ctrl.smooth_hz)
        self._vel_var.set(ctrl.comfort_vel)
        self._acc_var.set(ctrl.comfort_acc)
        self._home_dur_var.set(ctrl.home_duration)

    def _build_form_column(self, parent: tk.Frame) -> None:
        """CC=4 — Colonne formulaire connexion (LabelFrame V17)."""
        form = tk.LabelFrame(parent, text="Connexion robot",
                             bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                             padx=8, pady=8)
        form.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._form_lf = form

        # Port série
        port_row = tk.Frame(form, bg=T.SURFACE)
        port_row.pack(fill="x", pady=3)
        tk.Label(port_row, text="Port série :", bg=T.SURFACE, fg=T.TEXT,
                 font=T.F_CONTROL, width=12, anchor="w").pack(side="left")
        self._port_var = tk.StringVar()
        self._port_entry = ttk.Entry(port_row, textvariable=self._port_var,
                                      width=28, font=T.F_MONO_MD)
        self._port_entry.pack(side="left", padx=5)
        if SERIAL_OK:
            ttk.Button(port_row, text="🔍", width=3,
                       command=self._detect_ports).pack(side="left")

        # Baudrate
        baud_row = tk.Frame(form, bg=T.SURFACE)
        baud_row.pack(fill="x", pady=3)
        tk.Label(baud_row, text="Baudrate :", bg=T.SURFACE, fg=T.TEXT,
                 font=T.F_CONTROL, width=12, anchor="w").pack(side="left")
        self._baud_var = tk.IntVar(value=1000000)
        baud_combo = ttk.Combobox(baud_row, textvariable=self._baud_var,
                                   values=[57600, 115200, 1000000, 2000000],
                                   width=12, state="readonly")
        baud_combo.pack(side="left", padx=5)

        # Boutons connecter / déconnecter
        btn_row = tk.Frame(form, bg=T.SURFACE)
        btn_row.pack(fill="x", pady=(6, 0))
        btn_conn = ttk.Button(btn_row, text="🔌 Connecter", command=self._connect)
        btn_conn.pack(side="left", padx=4)
        tooltip(btn_conn, "Connecter le robot au port série")
        btn_disc = ttk.Button(btn_row, text="❌ Déconnecter", command=self._disconnect)
        btn_disc.pack(side="left", padx=4)
        tooltip(btn_disc, "Déconnecter le robot")
        btn_reboot = ttk.Button(btn_row, text="🔄 Reboot", command=self._reboot)
        btn_reboot.pack(side="left", padx=4)
        tooltip(btn_reboot, "Reboot des moteurs en sécurité (sans débrancher)")

    def _build_actions_column(self, parent: tk.Frame) -> None:
        """CC=2 — Colonne actions rapides (V17 style)."""
        quick = tk.LabelFrame(parent, text="Actions rapides",
                              bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                              padx=8, pady=8)
        quick.pack(side="left", fill="y", padx=(0, 8))
        self._quick_lf = quick

        actions = [
            ("📍 Calib. Machine", self._calibrate_home_machine, True),
            ("🏠 Pos. Machine",   self._goto_home_machine,      False),
            ("📍 Calib. Travail", self._calibrate_home_work,    True),
            ("🔧 Pos. Travail",   self._goto_home_work,         False),
        ]
        self._master_only_btns: list = []
        for item in actions:
            if item is None:
                ttk.Separator(quick, orient="horizontal").pack(fill="x", pady=3)
            else:
                lbl, cmd, master_only = item
                btn = ttk.Button(quick, text=lbl, command=cmd)
                btn.pack(fill="x", pady=2)
                if master_only:
                    self._master_only_btns.append(btn)

    def _build_status_column(self, parent: tk.Frame) -> None:
        """CC=3 — Colonne statut + environnement (V17 style)."""
        right = tk.Frame(parent, bg=T.BG)
        right.pack(side="left", fill="y")

        # Statut connexion
        st_frame = tk.LabelFrame(right, text="Statut",
                                  bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                                  padx=8, pady=8)
        st_frame.pack(fill="x", pady=(0, 6))
        self._status_lf = st_frame
        self._conn_status_lbl = tk.Label(st_frame, text="🔴 Déconnecté",
                                          bg=T.SURFACE, fg=T.TEXT_DIM,
                                          font=(T.FONT_UI, 13))
        self._conn_status_lbl.pack()

        # Badge simulation
        self._sim_badge = tk.Label(st_frame, text="", bg=T.SURFACE,
                                    fg=T.C_AMB, font=T.F_CAPTION)
        self._sim_badge.pack()

        # Environnement
        env_frame = tk.LabelFrame(right, text="Environnement",
                                   bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                                   padx=8, pady=5)
        env_frame.pack(fill="x")

        sdk_color = T.C_OK if DXL_OK else T.C_AMB
        sdk_text  = "✅ Dynamixel SDK" if DXL_OK else "⚠ Simulation (pas de SDK)"
        tk.Label(env_frame, text=sdk_text, bg=T.SURFACE, fg=sdk_color,
                 font=T.F_CAPTION).pack(anchor="w")

        ser_color = T.C_OK if SERIAL_OK else T.C_ERR
        ser_text  = "✅ pyserial" if SERIAL_OK else "❌ pyserial manquant"
        tk.Label(env_frame, text=ser_text, bg=T.SURFACE, fg=ser_color,
                 font=T.F_CAPTION).pack(anchor="w")

    def _build_sliders_area(self, container: tk.Widget = None) -> None:
        """CC=3 — Section pilotage (sliders + couplage). Compacte pour voir les 7 axes."""
        parent = container or self
        # Barre compacte : mode direct + test rapide + sauvegarder (une seule ligne)
        bar = tk.Frame(parent, bg=T.BG)
        bar.pack(fill="x", padx=T.PAD_MD, pady=(T.PAD_XS, 0))

        tk.Checkbutton(bar, text="🎮 Direct",
                       variable=self._direct_var, bg=T.BG, fg=T.C_AMB,
                       selectcolor=T.SURFACE, activebackground=T.BG,
                       activeforeground=T.C_AMB, font=T.F_CONTROL,
                       command=self._on_direct_toggled).pack(side="left")
        self._direct_warn = tk.Label(bar, text="", bg=T.BG, fg=T.C_ERR, font=T.F_CAPTION)
        self._direct_warn.pack(side="left", padx=(T.PAD_XS, T.PAD_SM))

        ttk.Button(bar, text="📍 Lire",
                   command=self._read_positions).pack(side="left", padx=2)
        ttk.Button(bar, text="🎯 Go sliders",
                   command=self._goto_sliders).pack(side="left", padx=2)
        ttk.Button(bar, text="⏹ Stop",
                   command=self._stop_motion).pack(side="left", padx=2)

        ttk.Button(bar, text="💾 Enregistrer position",
                   command=self._save_position).pack(side="right")

        # Zone sliders (pas de LabelFrame pour gagner de la place)
        self._sliders_frame = tk.Frame(parent, bg=T.SURFACE)
        self._sliders_frame.pack(fill="both", expand=True,
                                  padx=T.PAD_MD, pady=(T.PAD_XS, 0))

        # Couplage en bas (compact)
        self._build_coupling_ui(parent)
        self._rebuild_sliders()
        self._update_master_only_buttons()

    def _build_coupling_ui(self, parent: tk.Widget) -> None:
        """Panneau couplage axes 2-3 avec persistance et statut (V17)."""
        lf = tk.LabelFrame(parent, text="⚙️  Couplage axes 2-3",
                           bg=T.SURFACE, fg=T.C_MAG, font=T.F_CAPTION,
                           padx=T.PAD_SM, pady=T.PAD_XS)
        lf.pack(fill="x", pady=(T.PAD_XS, 0))
        self._coupling_lf = lf

        row1 = tk.Frame(lf, bg=T.SURFACE)
        row1.pack(fill="x")
        tk.Checkbutton(row1, text="Activer", variable=self._c_enabled,
                       bg=T.SURFACE, fg=T.TEXT, selectcolor=T.BG,
                       activebackground=T.SURFACE, font=T.F_CONTROL,
                       command=self._on_coupling_change
                       ).pack(side="left", padx=(0, T.PAD_MD))
        tk.Checkbutton(row1, text="Inverser", variable=self._c_invert,
                       bg=T.SURFACE, fg=T.TEXT, selectcolor=T.BG,
                       activebackground=T.SURFACE, font=T.F_CONTROL,
                       command=self._on_coupling_change
                       ).pack(side="left", padx=(0, T.PAD_MD))

        for lbl, var, lo, hi, inc in [
            ("Ratio", self._c_ratio, 0.1, 2.0, 0.05),
            ("Offset", self._c_offset, -500, 500, 10),
            ("Centre", self._c_center, 0, 4095, 50),
        ]:
            tk.Label(row1, text=f"{lbl}:", bg=T.SURFACE, fg=T.TEXT_MED,
                     font=T.F_CONTROL).pack(side="left", padx=(T.PAD_SM, 2))
            tk.Spinbox(row1, textvariable=var, from_=lo, to=hi,
                       increment=inc, width=6, bg=T.BG, fg=T.TEXT,
                       font=T.F_MONO_SM, buttonbackground=T.SURFACE,
                       command=self._on_coupling_change
                       ).pack(side="left", padx=(0, T.PAD_XS))

        # Label statut couplage (V17)
        self._coupling_status_lbl = tk.Label(lf, text="", bg=T.SURFACE,
                                              fg=T.TEXT_DIM, font=T.F_CAPTION)
        self._coupling_status_lbl.pack(pady=(T.PAD_XS, 0))
        self._update_coupling_status()

    def _show_robot_popup(self) -> None:
        """Affiche un menu popup coloré pour choisir le robot actif."""
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg=T.SURFACE, fg=T.TEXT,
                       activebackground=T.C_MAG_DIM2, activeforeground=T.C_AMB,
                       font=(T.FONT_UI, 11))
        for rid in sorted(registry.ids()):
            color = registry.color_for(rid)
            rcfg = library.get_robot(rid)
            lbl = f"{rcfg.name}  ({rid})" if rcfg and rcfg.name else rid
            menu.add_command(
                label=lbl, foreground=color,
                command=lambda r=rid: (self._robot_var.set(r),
                                       self._on_robot_selected()))
        # Positionne le popup sous le bouton
        x = self._robot_btn.winfo_rootx()
        y = self._robot_btn.winfo_rooty() + self._robot_btn.winfo_height()
        menu.tk_popup(x, y)

    # ── Couplage : persistance + statut (V17) ────────────────────────────

    def _restore_coupling_from_config(self) -> None:
        """Restaure l'état du couplage depuis la config hardware (library)."""
        hw = library.get_hardware()
        coupling = hw.get("coupling", {})
        if coupling:
            self._c_enabled.set(coupling.get("enabled", False))
            self._c_invert.set(coupling.get("invert", False))
            self._c_ratio.set(coupling.get("ratio", 1.0))
            self._c_offset.set(coupling.get("offset", 0))
            self._c_center.set(coupling.get("center", 2048))

    def _save_coupling_to_config(self) -> None:
        """Sauvegarde l'état du couplage dans la config hardware (library)."""
        hw = library.get_hardware()
        hw["coupling"] = {
            "enabled": bool(self._c_enabled.get()),
            "invert": bool(self._c_invert.get()),
            "ratio": float(self._c_ratio.get()),
            "offset": int(self._c_offset.get()),
            "center": int(self._c_center.get()),
        }
        library.save_hardware(hw)
        _LOG.info("Couplage %s", "activé" if self._c_enabled.get() else "désactivé")

    def _on_coupling_change(self) -> None:
        """Callback changement couplage : sauvegarde + met à jour le label (V17)."""
        self._save_coupling_to_config()
        self._update_coupling_status()
        self._update_axis3_state()

    def _update_axis3_state(self) -> None:
        """Grise ou dégrise l'axe 3 selon l'état du couplage.

        Grisé = limites + label axe grisés, interactions désactivées.
        Mais le curseur de position et le label valeur restent visibles
        pour refléter le couplage avec l'axe 2.
        """
        cdata = self._limit_canvases.get(3)
        if cdata is None:
            return
        disabled = self._c_enabled.get()
        cvs = cdata["canvas"]
        # Label axe : grisé ou ambre
        row = cdata["row"]
        children = row.winfo_children()
        if children and isinstance(children[0], tk.Label):
            children[0].config(fg=T.TEXT_DIM if disabled else T.C_AMB)
        # Label limites : grisé
        lim_lbl = cdata.get("lim_lbl")
        if lim_lbl:
            lim_lbl.config(fg="#444" if disabled else T.TEXT_DIM)
        # Label valeur : toujours visible (suivi couplage)
        val_lbl = cdata.get("val_lbl")
        if val_lbl:
            val_lbl.config(fg=T.TEXT)
        # Désactiver/réactiver les interactions sur le canvas
        if disabled:
            cvs.unbind("<Button-1>")
            cvs.unbind("<B1-Motion>")
            cvs.unbind("<ButtonRelease-1>")
            # Copier les limites de l'axe 2 vers l'axe 3
            self._sync_limits_2_to_3()
        else:
            cvs.bind("<Button-1>", lambda e, d=cdata: self._on_cvs_press(e, d))
            cvs.bind("<B1-Motion>", lambda e, d=cdata: self._on_cvs_drag(e, d))
            cvs.bind("<ButtonRelease-1>", lambda e, d=cdata: self._on_cvs_release(e, d))
        # Redessiner avec les bonnes couleurs
        self._draw_slider(cdata)

    def _sync_limits_2_to_3(self) -> None:
        """Copie les limites de sécurité de l'axe 2 vers l'axe 3 (couplage)."""
        cdata2 = self._limit_canvases.get(2)
        cdata3 = self._limit_canvases.get(3)
        if cdata2 is None or cdata3 is None:
            return
        cdata3["lo"] = cdata2["lo"]
        cdata3["hi"] = cdata2["hi"]
        cdata3["lim_var"].set(f"{cdata3['lo']}–{cdata3['hi']}")
        # Appliquer au profil
        rid = self._robot_var.get()
        ctrl = registry.get(rid)
        if ctrl:
            ctrl.profile.soft_limits[3] = (cdata3["lo"], cdata3["hi"])
        self._draw_slider(cdata3)

    def _update_coupling_status(self) -> None:
        """Met à jour le label statut couplage (V17)."""
        if not hasattr(self, "_coupling_status_lbl"):
            return
        if self._c_enabled.get():
            ratio = self._c_ratio.get()
            arrow = "↕️" if self._c_invert.get() else "↔️"
            self._coupling_status_lbl.config(
                text=f"✅ Couplage actif {arrow} Ratio: {ratio:.1f}",
                fg=T.C_OK)
        else:
            self._coupling_status_lbl.config(
                text="❌ Couplage désactivé", fg=T.TEXT_DIM)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _on_direct_toggled(self) -> None:
        """CC=6 — Toggle mode direct avec confirmation V17."""
        if self._direct_var.get():
            ctrl = self._active_ctrl()
            if ctrl is None or not ctrl.serial_connected:
                self._direct_var.set(False)
                messagebox.showwarning(
                    "Contrôle Direct",
                    "Connectez le robot avant d'activer le contrôle direct",
                    parent=self)
                return
            if not messagebox.askyesno(
                    "Contrôle Direct",
                    "⚠️ ATTENTION ⚠️\n\n"
                    "Le mode contrôle direct envoie IMMÉDIATEMENT\n"
                    "chaque mouvement de slider au robot.\n\n"
                    "• Pas de validation safety\n"
                    "• Pas de mouvement smooth\n"
                    "• Risque de mouvements brusques\n\n"
                    "Continuer ?",
                    icon="warning", parent=self):
                self._direct_var.set(False)
                self._direct_warn.config(text="")
                return
            self._direct_warn.config(text="⚠️ Mode actif — mouvement direct")
            # Profil rapide pour le mode direct (annule le profil lent du dernier move)
            # Profil direct : vitesse limitée pour mouvements sûrs
            # velocity=200 (~55°/s), acceleration=50 (rampe douce)
            ctrl.set_direct_mode(200, 50)
            # Sync sliders depuis le hardware (V17)
            self._sync_sliders_from_hardware()
            _LOG.warning("Mode contrôle direct ACTIVÉ (velocity=200, acc=50)")
        else:
            self._direct_warn.config(text="")
            # Restaurer le profil comfort pour les mouvements normaux
            ctrl = self._active_ctrl()
            if ctrl and ctrl.serial_connected:
                ctrl.apply_motion_profile()
            _LOG.info("Mode contrôle direct désactivé (profil comfort restauré)")

    def _rebuild_sliders(self) -> None:
        # H4 : nettoyer les traces Tcl avant de détruire les vars
        for var in self._slider_vars.values():
            for tid in var.trace_info():
                try:
                    var.trace_remove(tid[0], tid[1])
                except Exception:
                    _LOG.debug("trace_remove échoué pour variable slider: %s", tid)
        for w in self._sliders_frame.winfo_children():
            w.destroy()
        self._slider_vars.clear()
        self._limit_canvases: Dict[int, dict] = {}

        rid = self._robot_var.get()
        if not rid:
            ids = sorted(registry.ids())
            if ids:
                rid = ids[0]
                self._robot_var.set(rid)

        robot = registry.get(rid)
        if robot is None:
            label(self._sliders_frame, "Aucun robot enregistré.", style="dim").pack(pady=T.PAD_XL)
            return

        profile = robot.profile
        for mid in sorted(profile.motor_ids):
            self._build_slider_row(self._sliders_frame, mid, profile)
        # Griser axe 3 si couplage actif
        self._update_axis3_state()

    # ── Slider avec curseurs de limites draggables ────────────────

    _TRACK_H = 28          # hauteur du canvas slider
    _TRACK_PAD = 8         # marge gauche/droite dans le canvas
    _LIMIT_W = 6           # largeur du curseur limite
    _SLIDER_R = 7          # rayon du curseur position

    # Noms des curseurs de limites par axe
    _LIMIT_LABELS = {
        7: ("Pince fermée", "Pince ouverte"),
    }

    def _build_slider_row(self, parent: tk.Widget, motor_id: int, profile) -> None:
        lo, hi = profile.soft_limits.get(motor_id, (0, 4095))
        rt = T.robot_theme(self._robot_color)
        block_bg = rt["bg_med"]
        row = tk.Frame(parent, bg=block_bg, padx=T.PAD_SM, pady=1)
        row.pack(fill="x", pady=1)

        # Label axe (couleur du robot actif)
        tk.Label(row, text=f"Axe {motor_id}", bg=block_bg, fg=self._robot_color,
                 font=T.F_MONO_MD, width=5).pack(side="left")

        # Variable position
        var = tk.IntVar(value=2048)
        self._slider_vars[motor_id] = var

        # Canvas slider custom avec curseurs de limites
        cvs = tk.Canvas(row, height=self._TRACK_H, bg=block_bg,
                        highlightthickness=0, bd=0)
        cvs.pack(side="left", fill="x", expand=True, padx=4)

        # Stocker les données du canvas
        cdata = {
            "canvas": cvs, "motor_id": motor_id,
            "row": row,              # frame conteneur pour griser
            "lo": lo, "hi": hi,      # limites courantes
            "abs_lo": 0, "abs_hi": 4095,  # limites physiques absolues
            "pos": 2048,
            "dragging": None,         # "lo", "hi", "pos" ou None
        }
        self._limit_canvases[motor_id] = cdata

        # Dessiner après que le canvas ait sa taille
        cvs.bind("<Configure>", lambda e, d=cdata: self._draw_slider(d))
        cvs.bind("<Button-1>", lambda e, d=cdata: self._on_cvs_press(e, d))
        cvs.bind("<B1-Motion>", lambda e, d=cdata: self._on_cvs_drag(e, d))
        cvs.bind("<ButtonRelease-1>", lambda e, d=cdata: self._on_cvs_release(e, d))

        # Callback quand var change (polling externe)
        var.trace_add("write", lambda *_, d=cdata, v=var: self._on_var_changed(d, v))

        # Label valeur
        val_lbl = tk.Label(row, textvariable=var, bg=block_bg, fg=T.TEXT,
                           font=T.F_MONO_MD, width=5)
        val_lbl.pack(side="left", padx=2)
        cdata["val_lbl"] = val_lbl

        # Label limites
        lo_name, hi_name = self._LIMIT_LABELS.get(motor_id, ("", ""))
        if lo_name:
            lim_text = f"{lo_name} ◄► {hi_name}"
        else:
            lim_text = f"{lo}–{hi}"
        lim_var = tk.StringVar(value=lim_text)
        cdata["lim_var"] = lim_var
        cdata["lo_name"] = lo_name
        cdata["hi_name"] = hi_name
        lim_lbl = tk.Label(row, textvariable=lim_var, bg=block_bg, fg=T.TEXT_DIM,
                           font=T.F_CAPTION, width=14)
        lim_lbl.pack(side="left")
        cdata["lim_lbl"] = lim_lbl

    def _pos_to_x(self, cdata: dict, pos: int) -> int:
        """Convertit une position moteur en coordonnée X canvas."""
        w = cdata["canvas"].winfo_width()
        pad = self._TRACK_PAD
        usable = w - 2 * pad
        if usable <= 0:
            return pad
        ratio = (pos - cdata["abs_lo"]) / max(1, cdata["abs_hi"] - cdata["abs_lo"])
        return int(pad + ratio * usable)

    def _x_to_pos(self, cdata: dict, x: int) -> int:
        """Convertit une coordonnée X canvas en position moteur."""
        w = cdata["canvas"].winfo_width()
        pad = self._TRACK_PAD
        usable = w - 2 * pad
        if usable <= 0:
            return cdata["abs_lo"]
        ratio = max(0.0, min(1.0, (x - pad) / usable))
        return int(cdata["abs_lo"] + ratio * (cdata["abs_hi"] - cdata["abs_lo"]))

    def _draw_slider(self, cdata: dict, pos_only: bool = False) -> None:
        """Redessine le canvas slider.

        Si pos_only=True, ne déplace que le curseur de position (rapide).
        """
        cvs = cdata["canvas"]
        w = cvs.winfo_width()
        h = self._TRACK_H
        pad = self._TRACK_PAD
        if w < 20:
            return

        mid_y = h // 2
        r = self._SLIDER_R
        x_lo = self._pos_to_x(cdata, cdata["lo"])
        x_hi = self._pos_to_x(cdata, cdata["hi"])
        x_pos = self._pos_to_x(cdata, cdata["pos"])

        # Détecte si la position est hors limites
        pos_val = cdata["pos"]
        out_of_limits = pos_val < cdata["lo"] or pos_val > cdata["hi"]

        # Torque off → on peut afficher hors limites (grisé)
        # Torque on  → on clamp dans les limites
        ctrl = self._active_ctrl()
        torque_off = ctrl is not None and not ctrl.torque_enabled
        if not torque_off:
            x_pos = max(x_lo, min(x_hi, x_pos))
            out_of_limits = False

        # Mise à jour rapide : déplacer uniquement le curseur position
        if pos_only and cvs.find_withtag("pos"):
            cvs.coords("pos", x_pos - r, mid_y - r, x_pos + r, mid_y + r)
            fill = "#888" if out_of_limits else "#1a1a2e"
            outline = "#666" if out_of_limits else self._robot_color
            cvs.itemconfigure("pos", fill=fill, outline=outline)
            return

        # Redraw complet
        cvs.delete("all")

        greyed = (cdata["motor_id"] == 3 and self._c_enabled.get())
        rt = T.robot_theme(self._robot_color)
        col_zone = "#3a3a4a" if greyed else rt["bg_vif"]
        col_lim = "#555" if greyed else "#e74c3c"
        col_lim_border = "#444" if greyed else "#c0392b"

        # Piste (zone hors limites)
        cvs.create_rectangle(pad, mid_y - 3, w - pad, mid_y + 3,
                             fill=T.BG_DEEP, outline="")
        # Zone dans les limites (bande colorée robot)
        cvs.create_rectangle(x_lo, mid_y - 3, x_hi, mid_y + 3,
                             fill=col_zone, outline="")
        # Curseur limite gauche
        lw = self._LIMIT_W
        cvs.create_rectangle(x_lo - lw // 2, 2, x_lo + lw // 2, h - 2,
                             fill=col_lim, outline=col_lim_border, tags="lim_lo")
        # Curseur limite droite
        cvs.create_rectangle(x_hi - lw // 2, 2, x_hi + lw // 2, h - 2,
                             fill=col_lim, outline=col_lim_border, tags="lim_hi")
        # Curseur position (sombre avec contour robot — comme Position & Suite)
        if out_of_limits:
            col_pos, col_pos_border = "#888", "#666"
        elif greyed:
            col_pos, col_pos_border = "#888", "#666"
        else:
            col_pos, col_pos_border = "#1a1a2e", self._robot_color
        cvs.create_oval(x_pos - r, mid_y - r, x_pos + r, mid_y + r,
                        fill=col_pos, outline=col_pos_border, width=2, tags="pos")

    def _hit_test(self, cdata: dict, x: int) -> Optional[str]:
        """Détermine quel élément est sous le curseur.

        Priorité au curseur de position pour éviter d'attraper
        accidentellement une limite quand le curseur est en butée.
        """
        tol = 10
        x_lo = self._pos_to_x(cdata, cdata["lo"])
        x_hi = self._pos_to_x(cdata, cdata["hi"])
        x_pos = self._pos_to_x(cdata, cdata["pos"])
        x_pos = max(x_lo, min(x_hi, x_pos))
        # Position d'abord (priorité)
        if abs(x - x_pos) < tol + 2:
            return "pos"
        # Puis limites
        if abs(x - x_lo) < tol:
            return "lo"
        if abs(x - x_hi) < tol:
            return "hi"
        return None

    def _on_cvs_press(self, event: tk.Event, cdata: dict) -> None:
        hit = self._hit_test(cdata, event.x)
        if hit:
            cdata["dragging"] = hit
        else:
            # Clic sur la piste → déplacer la position
            cdata["dragging"] = "pos"
            self._move_pos_to(cdata, event.x)

    def _on_cvs_drag(self, event: tk.Event, cdata: dict) -> None:
        drag = cdata.get("dragging")
        if not drag:
            return
        pos = self._x_to_pos(cdata, event.x)
        pos = max(cdata["abs_lo"], min(cdata["abs_hi"], pos))

        if drag == "lo":
            # Limite min ne peut pas dépasser la limite max - 50
            pos = min(pos, cdata["hi"] - 50)
            pos = max(cdata["abs_lo"], pos)
            cdata["lo"] = pos
        elif drag == "hi":
            # Limite max ne peut pas descendre sous la limite min + 50
            pos = max(pos, cdata["lo"] + 50)
            pos = min(cdata["abs_hi"], pos)
            cdata["hi"] = pos
        elif drag == "pos":
            self._move_pos_to(cdata, event.x)
            return  # _move_pos_to fait déjà le redraw

        lo_name = cdata.get("lo_name", "")
        if lo_name:
            cdata["lim_var"].set(f"{lo_name} ◄► {cdata.get('hi_name', '')}")
        else:
            cdata["lim_var"].set(f"{cdata['lo']}–{cdata['hi']}")
        self._draw_slider(cdata)

    def _on_cvs_release(self, event: tk.Event, cdata: dict) -> None:
        drag = cdata.get("dragging")
        cdata["dragging"] = None
        if drag in ("lo", "hi"):
            self._apply_limits(cdata)

    def _move_pos_to(self, cdata: dict, x: int) -> None:
        """Déplace le curseur position (clampé dans les limites) + couplage visuel."""
        pos = self._x_to_pos(cdata, x)
        pos = max(cdata["lo"], min(cdata["hi"], pos))
        cdata["pos"] = pos
        mid = cdata["motor_id"]
        if not self._slider_updating:
            self._slider_updating = True
            self._slider_vars[mid].set(pos)
            self._slider_updating = False
        self._draw_slider(cdata, pos_only=True)
        # Couplage visuel axe 2 → axe 3
        if mid == 2 and self._c_enabled.get():
            coupled = apply_couplings(
                {2: pos}, True, self._c_invert.get(),
                self._c_ratio.get(), self._c_offset.get(), self._c_center.get())
            if 3 in coupled and 3 in self._slider_vars:
                self._slider_updating = True
                self._slider_vars[3].set(coupled[3])
                cdata3 = self._limit_canvases.get(3)
                if cdata3:
                    cdata3["pos"] = coupled[3]
                    self._draw_slider(cdata3, pos_only=True)
                self._slider_updating = False
        if self._direct_var.get():
            self._direct_write_single(mid, pos)

    def _on_var_changed(self, cdata: dict, var: tk.IntVar) -> None:
        """Callback quand la variable position change (polling externe)."""
        if self._slider_updating:
            return
        try:
            cdata["pos"] = var.get()
            self._draw_slider(cdata, pos_only=True)
        except tk.TclError:
            _LOG.debug("TclError lors de la mise à jour du slider position")

    def _apply_limits(self, cdata: dict) -> None:
        """Applique les nouvelles limites au profil + propage si maître."""
        mid = cdata["motor_id"]
        lo, hi = cdata["lo"], cdata["hi"]
        rid = self._robot_var.get()
        ctrl = registry.get(rid)
        if ctrl is None:
            return

        # Appliquer au profil du robot actif + safety_manager
        ctrl.profile.soft_limits[mid] = (lo, hi)
        ctrl.set_motor_limit(mid, lo, hi)
        # Synchroniser les limites HW du moteur si connecté
        if ctrl.serial_connected:
            ctrl.sync_hardware_limits()
        _LOG.info("[%s] Limites axe %d : %d–%d (profil + safety + HW sync)", rid, mid, lo, hi)

        # Clamper la position courante si hors limites
        cur = cdata["pos"]
        if cur < lo or cur > hi:
            cdata["pos"] = max(lo, min(hi, cur))
            self._slider_updating = True
            self._slider_vars[mid].set(cdata["pos"])
            self._slider_updating = False

        # Propagation maître → autres robots
        if rid == registry.master_id:
            for other_rid in registry.ids():
                if other_rid == rid:
                    continue
                other = registry.get(other_rid)
                if other:
                    other.profile.soft_limits[mid] = (lo, hi)
                    other.set_motor_limit(mid, lo, hi)
                    if other.serial_connected:
                        other.sync_hardware_limits()
            _LOG.info("Limites axe %d propagées depuis %s (profil + safety + HW)", mid, rid)

        # Synchroniser axe 3 si couplage actif et limites axe 2 modifiées
        if mid == 2 and self._c_enabled.get():
            self._sync_limits_2_to_3()

        # Sauvegarde dans la library
        self._save_limits_to_config()
        self._draw_slider(cdata)

    def _save_limits_to_config(self) -> None:
        """Sauvegarde les soft_limits dans la library (un fichier par robot)."""
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl is None:
                continue
            # Récupérer la config existante ou en créer une nouvelle
            existing = library.get_robot(rid)
            if existing:
                existing.soft_limits = {
                    mid: list(lim)
                    for mid, lim in ctrl.profile.soft_limits.items()
                }
                library.save_robot(existing)
            else:
                robot_cfg = RobotConfigModel(
                    robot_id=rid,
                    soft_limits={
                        mid: list(lim)
                        for mid, lim in ctrl.profile.soft_limits.items()
                    },
                )
                library.save_robot(robot_cfg)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        """CC=7 — Connexion asynchrone avec feedback (V17 style)."""
        robot_id = self._robot_var.get()
        port     = self._port_var.get().strip()
        baud     = self._baud_var.get()
        if not robot_id:
            messagebox.showwarning("Connexion", "Sélectionnez un robot.", parent=self)
            return
        if not port:
            messagebox.showwarning("Connexion", "Entrez un port série.", parent=self)
            return
        ctrl = registry.get(robot_id)
        if ctrl is None:
            return
        self._conn_status_lbl.config(text="🔄 Connexion...", fg=T.C_AMB)

        def _task() -> None:
            ok = ctrl.connect(port, baud)
            self._after(0, lambda: self._on_connect_result(robot_id, port, baud, ok))

        threading.Thread(target=_task, daemon=True).start()

    def _on_connect_result(self, robot_id: str, port: str,
                           baud: int, ok: bool) -> None:
        """CC=5 — Callback résultat connexion (thread principal)."""
        if ok:
            sim = "(SIM)" if registry.get(robot_id).simulation else ""
            self._conn_status_lbl.config(text=f"🟢 Connecté {sim}", fg=T.C_OK)
            _LOG.info("Connexion réussie : %s sur %s", robot_id, port)
            # Mémorise port+baud dans la library
            existing = library.get_robot(robot_id)
            if existing:
                existing.port = port
                existing.baud = baud
                library.save_robot(existing)
            else:
                library.save_robot(RobotConfigModel(
                    robot_id=robot_id, port=port, baud=baud,
                ))
        else:
            self._conn_status_lbl.config(text="🔴 Erreur connexion", fg=T.C_ERR)
            messagebox.showerror(
                "Connexion échouée",
                f"Impossible de se connecter sur {port}\n\n"
                "Vérifiez :\n"
                "  1. Le robot est sous tension\n"
                "  2. Le câble USB est branché\n"
                "  3. Le port est correct (🔍)",
                parent=self)
        self._refresh()

    def _disconnect(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl:
            ctrl.disconnect()
            self._conn_status_lbl.config(text="🔴 Déconnecté", fg=T.TEXT_DIM)

    def _reboot(self) -> None:
        """CC=5 — Reboot moteurs en securite sans debrancher.
        Lit les erreurs HW, reboot les moteurs concernes (ou tous si aucun ciblé),
        puis reactive le torque."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if not ctrl.serial_connected:
            messagebox.showwarning("Reboot", "Connectez le robot d'abord.",
                                   parent=self)
            return
        rid = ctrl.robot_id

        def _bg():
            try:
                errors = ctrl.read_hardware_errors() or {}
            except Exception as exc:
                _LOG.warning("[%s] read_hardware_errors KO : %s", rid, exc)
                errors = {}
            targets = list(errors.keys()) or list(ctrl.profile.motor_ids)
            success = []
            for mid in targets:
                if ctrl.reboot_motor(mid):
                    success.append(mid)
                    _LOG.info("[%s] Moteur %d reboot OK", rid, mid)
                else:
                    _LOG.error("[%s] Echec reboot moteur %d", rid, mid)
            if success:
                ctrl.set_torque(True)
                _LOG.info("[%s] Torque reactive apres reboot %s", rid, success)
            self._after(0, lambda: self._reboot_done(rid, success, errors))

        threading.Thread(target=_bg, daemon=True).start()

    def _reboot_done(self, rid: str, success: list, errors: dict) -> None:
        """CC=2 — Feedback UI apres reboot."""
        if success:
            msg = f"Reboot OK : moteur(s) {success}"
            if errors:
                msg += f"\nErreurs initiales : {list(errors.keys())}"
            messagebox.showinfo("Reboot", msg, parent=self)
        else:
            messagebox.showerror("Reboot",
                                 f"Aucun moteur n'a pu être rebooté sur {rid}.",
                                 parent=self)

    def _torque_on(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl:
            ok = ctrl.set_torque(True)
            if not ok:
                messagebox.showerror("Torque", "Impossible d'activer le torque.")

    def _torque_off(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl:
            ok = ctrl.set_torque(False)
            if not ok:
                messagebox.showerror("Torque", "Impossible de désactiver le torque.")

    def _calibrate_home_machine(self) -> None:
        """CC=6 — Calibration position machine.
        Lit les positions brutes sans aucune limite."""
        rid = self._robot_var.get()
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if not ctrl.serial_connected:
            messagebox.showwarning("Calibration", "Connectez le robot d'abord.",
                                   parent=self)
            return
        if not messagebox.askyesno(
                "Position initiale machine",
                f"Définir la position actuelle de {rid}\n"
                "comme position initiale machine ?\n\n"
                "Les valeurs brutes seront enregistrées\n"
                "(aucune limite de sécurité appliquée).",
                parent=self):
            return
        # Lecture brute — pas de clamp, pas de limite
        positions = ctrl.read_positions()
        if not positions:
            messagebox.showerror("Calibration", "Lecture positions échouée.",
                                 parent=self)
            return
        ctrl.set_home_machine(positions)
        # Propagation maître (V17)
        self._propagate_home("machine", rid, positions)
        self._save_project()
        messagebox.showinfo("Calibration",
                            f"Position initiale machine enregistrée\n{positions}",
                            parent=self)

    def _calibrate_home_work(self) -> None:
        """CC=7 — Calibration position travail (V17 : confirmation + lecture + save)."""
        rid = self._robot_var.get()
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if not ctrl.serial_connected:
            messagebox.showwarning("Calibration", "Connectez le robot d'abord.",
                                   parent=self)
            return
        if not messagebox.askyesno(
                "Position initiale de travail",
                f"Définir la position actuelle de {rid}\n"
                "comme position initiale de travail ?\n\n"
                "(bras dégagé, posture prête à agir)",
                parent=self):
            return
        positions = ctrl.read_positions()
        if not positions:
            messagebox.showerror("Calibration", "Lecture positions échouée.",
                                 parent=self)
            return
        ctrl.set_home_work(positions)
        self._propagate_home("work", rid, positions)
        self._save_project()
        messagebox.showinfo("Calibration",
                            f"Position initiale de travail enregistrée\n{positions}",
                            parent=self)

    def _propagate_home(self, kind: str, master_rid: str,
                        positions: Dict[int, int]) -> None:
        """CC=4 — Propage la calibration du maître aux autres robots (V17)."""
        if master_rid != registry.master_id:
            return
        for rid in registry.ids():
            if rid == master_rid:
                continue
            ctrl = registry.get(rid)
            if ctrl is None:
                continue
            if kind == "machine":
                ctrl.set_home_machine(positions)
            else:
                ctrl.set_home_work(positions)
        _LOG.info("Position %s propagée depuis %s", kind, master_rid)

    def _save_project(self) -> None:
        """CC=2 — Sauvegarde le projet après calibration (via ProjectService pour snapshot)."""
        from xrv22.services.project_service import project
        project.save()

    def _goto_home_machine(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if not ctrl.serial_connected:
            messagebox.showwarning("Position machine", "Robot non connecté.",
                                   parent=self)
            return
        import threading
        def _bg() -> None:
            ok, msg = ctrl.safe_home()
            if not ok:
                self._after(0, lambda: messagebox.showerror("Home Machine", msg, parent=self))
        threading.Thread(target=_bg, daemon=True).start()

    def _goto_home_work(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if not ctrl.serial_connected:
            messagebox.showwarning("Position travail", "Robot non connecté.",
                                   parent=self)
            return
        ok, msg = ctrl.go_home_work()
        if not ok:
            messagebox.showerror("Home Travail", msg, parent=self)

    def _detect_ports(self) -> None:
        """CC=4 — Ouvre la fenêtre de sélection des ports (V17 style)."""
        if not SERIAL_OK:
            messagebox.showwarning("Détection", "Module serial non disponible", parent=self)
            return
        ports = list(list_ports.comports())
        if not ports:
            messagebox.showinfo("Détection", "Aucun port série détecté", parent=self)
            return
        self._show_port_picker(ports)

    def _show_port_picker(self, ports: list) -> None:
        """CC=4 — Fenêtre de sélection de port (V17 style Listbox)."""
        dlg = tk.Toplevel(self)
        dlg.title("Ports disponibles")
        dlg.configure(bg=T.BG)
        dlg.geometry("500x300")
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        tk.Label(dlg, text="Sélectionnez un port :", bg=T.BG, fg=T.TEXT,
                 font=T.F_SECTION).pack(padx=10, pady=10)

        listbox = tk.Listbox(dlg, height=10, bg=T.SURFACE, fg=T.TEXT,
                             selectbackground=T.C_MAG_DIM2, selectforeground=T.C_AMB,
                             font=T.F_MONO_MD, relief="flat", highlightthickness=0)
        listbox.pack(fill="both", expand=True, padx=10, pady=5)

        for p in ports:
            listbox.insert(tk.END, f"{p.device}  —  {p.description}")

        # Pré-sélection du port actuel
        current = self._port_var.get()
        for i, p in enumerate(ports):
            if p.device == current:
                listbox.selection_set(i)
                listbox.see(i)
                break

        def _select() -> None:
            sel = listbox.curselection()
            if sel:
                self._port_var.set(ports[sel[0]].device)
            dlg.destroy()

        def _refresh() -> None:
            listbox.delete(0, tk.END)
            new_ports = list(list_ports.comports())
            ports.clear()
            ports.extend(new_ports)
            for p in ports:
                listbox.insert(tk.END, f"{p.device}  —  {p.description}")

        btn_frame = tk.Frame(dlg, bg=T.BG)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Rafraîchir", command=_refresh).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Sélectionner", command=_select).pack(side="left", padx=5)
        listbox.bind("<Double-1>", lambda _: _select())

    # ── Sliders callbacks ─────────────────────────────────────────────────────

    def _on_slider_change(self, motor_id: int, _val: str) -> None:
        """CC=4 — Slider changé : mode direct = écriture throttlée (150ms min)."""
        if self._slider_updating or not self._direct_var.get():
            return
        self._direct_pending = True
        if self._direct_throttle_id is None:
            self._direct_do_flush()

    def _direct_do_flush(self) -> None:
        """Envoie les positions pendantes et programme le prochain flush."""
        self._direct_throttle_id = None
        if not self._direct_pending:
            return
        self._direct_pending = False
        self._direct_write_all()
        # Re-programmer si un nouveau changement arrive pendant l'envoi
        self._direct_throttle_id = self.after(150, self._direct_do_flush)

    def _on_slider_release(self, motor_id: int) -> None:
        """CC=2 — Slider relâché : rien en mode non-direct (seul 'Go sliders' envoie)."""
        pass

    def _direct_write_all(self) -> None:
        """CC=5 — Écriture directe de TOUS les sliders (V17 : write_positions)."""
        ctrl = self._active_ctrl()
        if ctrl is None or not ctrl.serial_connected:
            return
        targets = self._get_slider_positions()
        if self._c_enabled.get():
            targets = apply_couplings(
                targets, True, self._c_invert.get(),
                self._c_ratio.get(), self._c_offset.get(), self._c_center.get())
            if 3 in targets and 3 in self._slider_vars:
                self._slider_updating = True
                self._slider_vars[3].set(targets[3])
                self._slider_updating = False
        try:
            ctrl.write_positions_direct(targets)
        except Exception as exc:
            _LOG.error("Direct control write error: %s", exc)

    def _direct_write_single(self, motor_id: int, pos: int) -> None:
        """Écriture directe d'UN seul axe (+ couplage si axe 2)."""
        ctrl = self._active_ctrl()
        if ctrl is None or not ctrl.serial_connected:
            return
        targets = {motor_id: pos}
        # Couplage axe 2 → axe 3
        if motor_id == 2 and self._c_enabled.get():
            targets = apply_couplings(
                targets, True, self._c_invert.get(),
                self._c_ratio.get(), self._c_offset.get(), self._c_center.get())
            if 3 in targets and 3 in self._slider_vars:
                self._slider_updating = True
                self._slider_vars[3].set(targets[3])
                cdata3 = self._limit_canvases.get(3)
                if cdata3:
                    cdata3["pos"] = targets[3]
                    self._draw_slider(cdata3, pos_only=True)
                self._slider_updating = False
        try:
            ctrl.write_positions_direct(targets)
        except Exception as exc:
            _LOG.error("Direct single write error: %s", exc)

    def _send_with_coupling(self, motor_id: int) -> None:
        """CC=5 — Mouvement smooth d'un axe avec couplage + durée auto (V17)."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        positions = {motor_id: self._slider_vars[motor_id].get()}
        if motor_id == 2 and self._c_enabled.get():
            positions = apply_couplings(
                positions, True, self._c_invert.get(),
                self._c_ratio.get(), self._c_offset.get(), self._c_center.get())
            if 3 in positions and 3 in self._slider_vars:
                self._slider_updating = True
                self._slider_vars[3].set(positions[3])
                self._slider_updating = False
        current = ctrl.get_positions()
        duration_s = calculate_auto_duration(positions, current, speed_ratio=1.0)
        ok, msg = ctrl.move(positions, duration_s=duration_s)
        if not ok:
            _LOG.warning("Move rejeté : %s", msg)

    def _on_robot_selected(self) -> None:
        """CC=6 — Changement de robot : sync port/baud/sliders + boutons maître (V17)."""
        rid = self._robot_var.get()
        if rid:
            bus.publish("ui.active_robot_changed", {"robot_id": rid})
        self._sync_port_from_config()
        self._rebuild_sliders()
        self._update_master_only_buttons()
        self._update_robot_colors()
        self._refresh()
        # V17 : désactive le mode direct au changement de robot
        if self._direct_var.get():
            self._direct_var.set(False)
            self._direct_warn.config(text="")
        # Sync sliders depuis le hardware si connecté
        self._sync_sliders_from_hardware()
        # Sync paramètres mouvement depuis le controller
        self._sync_motion_params_from_ctrl()

    def _update_master_only_buttons(self) -> None:
        """Active les boutons calibration seulement pour le robot maître."""
        rid = self._robot_var.get()
        is_master = (rid == registry.master_id)
        state = "normal" if is_master else "disabled"
        for btn in self._master_only_btns:
            btn.configure(state=state)

    def _sync_port_from_config(self) -> None:
        """CC=4 — Restaure port+baud depuis le controller connecté ou la library."""
        rid = self._robot_var.get()
        # Priorité : port réel du controller connecté
        ctrl = registry.get(rid)
        if ctrl and ctrl.is_connected and ctrl.port_name:
            self._port_var.set(ctrl.port_name)
            return
        # Sinon : config sauvegardée dans la library
        robot_cfg = library.get_robot(rid)
        if robot_cfg:
            self._port_var.set(robot_cfg.port or "")
            self._baud_var.set(robot_cfg.baud or 1000000)
            return
        # Robot non trouvé — vider le champ
        self._port_var.set("")
        self._baud_var.set(1000000)

    def _on_active_robot_changed(self, payload: dict) -> None:
        rid = payload.get("robot_id", "")
        if not rid or rid == self._robot_var.get():
            return
        ids = sorted(registry.ids())
        if rid in ids:
            self._robot_var.set(rid)
        self._after(0, self._sync_port_from_config)
        self._after(0, self._rebuild_sliders)
        self._after(0, self._update_robot_colors)
        self._after(0, self._refresh)

    # ── Refresh ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """CC=6 — Rafraîchit depuis StateStore + met à jour statut."""
        ids = sorted(registry.ids())
        if ids and (not self._robot_var.get() or self._robot_var.get() not in ids):
            self._robot_var.set(ids[0])

        robot_id = self._robot_var.get()
        snap     = store.get_robot(robot_id) if robot_id else None
        system   = store.get_system()

        if snap:
            self._update_conn_status(snap)
            # Ne PAS écraser le port saisi par l'utilisateur — sync port
            # uniquement depuis la config au changement de robot (_on_robot_selected)
            self._update_sliders_from_positions(snap.positions)

        sim_text = "⚙️  Simulation" if system.simulation_mode else ""
        self._sim_badge.config(text=sim_text)

    def _update_conn_status(self, snap) -> None:
        """CC=5 — Met à jour le label statut connexion."""
        state = snap.state
        if snap.connected:
            self._conn_status_lbl.config(text=f"🟢 Connecté ({state})", fg=T.C_OK)
        elif state == "EMERGENCY_STOP":
            self._conn_status_lbl.config(text="🛑 E-STOP", fg=T.C_ERR)
        elif state == "ERROR":
            self._conn_status_lbl.config(text="⊗ Erreur", fg=T.C_ERR)
        else:
            self._conn_status_lbl.config(text="🔴 Déconnecté", fg=T.TEXT_DIM)

    def _update_sliders_from_positions(self, positions: Dict[int, int]) -> None:
        self._slider_updating = True
        for mid, pos in positions.items():
            # Ne pas écraser un slider en cours de drag
            cdata = self._limit_canvases.get(mid)
            if cdata is not None and cdata.get("dragging"):
                continue
            if mid in self._slider_vars:
                self._slider_vars[mid].set(pos)
            # Mettre à jour le canvas seulement si la position a changé
            if cdata is not None and cdata["pos"] != pos:
                cdata["pos"] = pos
                self._draw_slider(cdata, pos_only=True)
        self._slider_updating = False

    def _save_position(self) -> None:
        """CC=7 — Sauvegarde position courante avec nom (V17 : askstring + read + save)."""
        ctrl = self._active_ctrl()
        if ctrl is None or not ctrl.serial_connected:
            messagebox.showwarning("Enregistrer", "Connectez le robot d'abord",
                                   parent=self)
            return
        name = simpledialog.askstring("Enregistrer position", "Nom de la position :",
                                      parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        positions = ctrl.read_positions()
        if not positions:
            messagebox.showerror("Enregistrer", "Lecture positions échouée",
                                 parent=self)
            return
        # Sauvegarder via la library
        pos_model = PositionModel(name=name, positions=positions)
        library.save_position(pos_model)
        _LOG.info("Position '%s' sauvegardée : %s", name, positions)
        messagebox.showinfo("Enregistrer", f"Position '{name}' enregistrée",
                            parent=self)
        bus.publish("position.capture_request", {"name": name, "positions": positions})

    def _poll_positions(self) -> None:
        """CC=6 — Polling 500ms : lit les positions hardware (V17 : seulement si READY)."""
        ctrl = self._active_ctrl()
        if ctrl and ctrl.serial_connected:
            state = ctrl.state
            # V17 : on ne lit que si READY (pas en RUNNING ni E-STOP)
            if state in ("READY", "IDLE"):
                def _bg_read() -> None:
                    try:
                        positions = ctrl.read_positions()
                        if positions:
                            self._after(0, lambda: self._update_sliders_from_positions(positions))
                    except Exception as exc:
                        _LOG.debug("_poll_positions read error: %s", exc)
                threading.Thread(target=_bg_read, daemon=True).start()
        self._after(500, self._poll_positions)

    def _sync_sliders_from_hardware(self) -> None:
        """CC=3 — Lit les positions hardware et met à jour les sliders (V17)."""
        ctrl = self._active_ctrl()
        if ctrl is None or not ctrl.serial_connected:
            return
        def _bg() -> None:
            positions = ctrl.read_positions()
            if positions:
                self._after(0, lambda: self._update_sliders_from_positions(positions))
        threading.Thread(target=_bg, daemon=True).start()

    def _read_positions(self) -> None:
        """CC=3 — Lecture manuelle depuis le hardware."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        positions = ctrl.read_positions()
        if positions:
            self._update_sliders_from_positions(positions)

    def _goto_sliders(self) -> None:
        """Mouvement vers les positions des sliders avec durée auto (V17)."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        positions = self._get_slider_positions()
        if self._c_enabled.get():
            positions = apply_couplings(
                positions, True, self._c_invert.get(),
                self._c_ratio.get(), self._c_offset.get(), self._c_center.get())
        current = ctrl.get_positions()
        duration_s = calculate_auto_duration(positions, current, speed_ratio=1.0)
        ok, msg = ctrl.move(positions, duration_s=duration_s)
        if not ok:
            _LOG.warning("Goto sliders rejeté : %s", msg)

    def _stop_motion(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl:
            ctrl.soft_stop()

    def _goto_axis(self, motor_id: int, pos: int) -> None:
        """Mouvement d'un axe vers une position avec durée auto (V17)."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        if motor_id in self._slider_vars:
            self._slider_vars[motor_id].set(pos)
        targets = {motor_id: pos}
        current = ctrl.get_positions()
        duration_s = calculate_auto_duration(targets, current, speed_ratio=1.0)
        ctrl.move(targets, duration_s=duration_s)

    # ── Multi-robot (V17) ──────────────────────────────────────────────────

    def _all_connect(self) -> None:
        """Connecte tous les robots configurés avec un port défini (V17: async + feedback)."""
        candidates = []
        used_ports: set = set()
        for robot_cfg in library.list_robots():
            rid = robot_cfg.robot_id
            port = robot_cfg.port or ""
            baud = robot_cfg.baud or 1000000
            if not port or port in used_ports:
                continue
            ctrl = registry.get(rid)
            if ctrl is None:
                continue
            if ctrl.is_connected:
                used_ports.add(port)
                continue
            candidates.append((rid, port, baud))
            used_ports.add(port)

        if not candidates:
            messagebox.showwarning(
                "Connexion",
                "Aucun port mémorisé.\nConnectez d'abord chaque robot individuellement.",
                parent=self)
            return

        self._conn_status_lbl.config(
            text=f"🔄 Connexion de {len(candidates)} robot(s)…", fg=T.C_AMB)
        _LOG.info("All connect : %d candidat(s)", len(candidates))

        def _worker() -> None:
            results = []
            for rid, port, baud in candidates:
                ctrl = registry.get(rid)
                ok = ctrl.connect(port, baud) if ctrl else False
                results.append((rid, port, ok))
            self._after(0, lambda: self._all_connect_done(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _all_connect_done(self, results: list) -> None:
        """Callback résultat all_connect (V17: feedback détaillé)."""
        ok_robots = [n for n, p, r in results if r]
        fail_robots = [f"{n} ({p})" for n, p, r in results if not r]
        self._refresh()
        if ok_robots:
            _LOG.info("All connect OK : %s", ", ".join(ok_robots))
            bus.publish("ui.toast", {
                "text": f"✅ Connecté(s) : {', '.join(ok_robots)}", "level": "success"})
        if fail_robots:
            _LOG.warning("All connect FAIL : %s", ", ".join(fail_robots))
            bus.publish("ui.toast", {
                "text": f"⚠️ Échec : {', '.join(fail_robots)}", "level": "warning"})

    def _all_torque_on(self) -> None:
        """Active le torque sur tous les robots connectés (V17: feedback)."""
        done = []
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl and ctrl.is_connected:
                try:
                    ctrl.set_torque(True)
                    done.append(rid)
                except Exception as e:
                    _LOG.warning("Torque ON échoué pour %s: %s", rid, e)
        if not done:
            messagebox.showwarning("Torque ON", "Aucun robot connecté", parent=self)
        else:
            bus.publish("ui.toast", {
                "text": f"🔓 Torque ON : {', '.join(done)}", "level": "success"})

    def _all_torque_off(self) -> None:
        """Désactive le torque sur tous les robots connectés (V17: feedback)."""
        done = []
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl and ctrl.is_connected:
                try:
                    ctrl.set_torque(False)
                    done.append(rid)
                except Exception as e:
                    _LOG.warning("Torque OFF échoué pour %s: %s", rid, e)
        if not done:
            messagebox.showwarning("Torque OFF", "Aucun robot connecté", parent=self)
        else:
            bus.publish("ui.toast", {
                "text": f"🔒 Torque OFF : {', '.join(done)}", "level": "success"})

    def _all_goto_machine(self) -> None:
        """Envoie tous les robots connectés en position machine (V17: vérification calibration)."""
        connected = []
        missing = []
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl and ctrl.is_connected:
                if ctrl.home_machine is None or ctrl.home_work is None:
                    missing.append(rid)
                else:
                    connected.append(rid)
        if missing and not connected:
            messagebox.showwarning(
                "Tous → Machine",
                f"Position machine non calibrée pour :\n{', '.join(missing)}",
                parent=self)
            return
        if missing:
            if not messagebox.askyesno(
                    "Position machine",
                    f"Position machine non calibrée pour :\n{', '.join(missing)}\n\n"
                    "Continuer pour les autres ?",
                    parent=self):
                return
        import threading
        def _bg() -> None:
            errors = []
            for rid in connected:
                ctrl = registry.get(rid)
                ok, msg = ctrl.safe_home()
                if not ok:
                    errors.append(f"{rid}: {msg}")
            if errors:
                self._after(0, lambda: messagebox.showerror(
                    "Tous → Machine", "\n".join(errors), parent=self))
            else:
                self._after(0, lambda: bus.publish("ui.toast", {
                    "text": f"🏠 Tous → machine : {', '.join(connected)}", "level": "info"}))
        threading.Thread(target=_bg, daemon=True).start()

    def _all_goto_work(self) -> None:
        """Envoie tous les robots connectés en position de travail (V17: feedback)."""
        connected = []
        errors = []
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl and ctrl.is_connected:
                ok, msg = ctrl.go_home_work()
                if not ok:
                    errors.append(f"{rid}: {msg}")
                else:
                    connected.append(rid)
        if errors:
            messagebox.showerror("Tous → Travail",
                                 "Erreurs :\n" + "\n".join(errors), parent=self)
        elif connected:
            bus.publish("ui.toast", {
                "text": f"🔧 Tous → travail : {', '.join(connected)}", "level": "info"})
        elif not connected and not errors:
            messagebox.showwarning("Tous → Travail", "Aucun robot connecté",
                                   parent=self)

    # ── Bus ──────────────────────────────────────────────────────────────────

    def _subscribe(self) -> None:
        bus.subscribe("ui.refresh",             self._on_bus_refresh)
        bus.subscribe("robot.state_changed",    self._on_bus_refresh)
        bus.subscribe("robot.connected",        self._on_bus_refresh)
        bus.subscribe("robot.disconnected",     self._on_bus_refresh)
        bus.subscribe("robot.added",            self._on_bus_refresh)
        bus.subscribe("robot.removed",          self._on_bus_refresh)
        bus.subscribe("ui.active_robot_changed", self._on_active_robot_changed_bus)

    def destroy(self) -> None:
        bus.unsubscribe_object(self)
        super().destroy()

    def _on_bus_refresh(self, _: dict) -> None:
        if getattr(self, "_refresh_pending", False):
            return
        self._refresh_pending = True
        self._after(50, self._debounced_refresh)

    def _debounced_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh()

    def _on_active_robot_changed_bus(self, payload: dict) -> None:
        self._after(0, lambda: self._on_active_robot_changed(payload))

    # ── Privé ─────────────────────────────────────────────────────────────────

    def _active_ctrl(self):
        rid = self._robot_var.get()
        return registry.get(rid) if rid else None

    def _get_slider_positions(self) -> Dict[int, int]:
        return {mid: var.get() for mid, var in self._slider_vars.items()}

    # ── Couleur robot ─────────────────────────────────────────────────────────

    def _update_robot_colors(self) -> None:
        """CC=3 — Met à jour les couleurs de l'onglet selon le robot actif."""
        rid = self._robot_var.get()
        color = registry.color_for(rid) if rid else T.C_AMB
        self._robot_color = color
        rt = T.robot_theme(color)

        # Fond de l'onglet entier teinté robot
        self.config(bg=rt["bg"])

        # Bouton sélecteur robot
        if hasattr(self, "_robot_btn"):
            self._robot_btn.config(fg=color, bg=rt["bg_med"],
                                    highlightbackground=rt["border"])
        if hasattr(self, "_arrow_lbl"):
            self._arrow_lbl.config(fg=color)

        # Fonds et labels d'axe dans les sliders
        block_bg = rt["bg_med"]
        if hasattr(self, "_sliders_frame"):
            self._sliders_frame.config(bg=block_bg)
        for mid, cdata in self._limit_canvases.items():
            row = cdata["row"]
            row.config(bg=block_bg)
            cdata["canvas"].config(bg=block_bg)
            for child in row.winfo_children():
                if isinstance(child, tk.Label):
                    child.config(bg=block_bg)
            children = row.winfo_children()
            if children and isinstance(children[0], tk.Label):
                greyed = (mid == 3 and self._c_enabled.get())
                children[0].config(fg=T.TEXT_DIM if greyed else color)
            self._draw_slider(cdata)

        # LabelFrames : titre en couleur robot
        for lf_name in ("_form_lf", "_quick_lf", "_status_lf", "_motion_lf", "_coupling_lf"):
            lf = getattr(self, lf_name, None)
            if lf:
                lf.config(fg=color)
