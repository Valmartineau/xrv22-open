"""
xr200/ui/tab_capteurs.py
─────────────────────────
Onglet Capteurs & Actionneurs.

Layout :
  ┌── Left (260px) ─────────────────────────────────────┐
  │  Liste appareils Arduino                             │
  │  Boutons : ➕ Ajouter / 🔌 Connecter / ⏏ Déco / 🗑 │
  │  Port / Baud / Protocoles info                      │
  ├── Right ─────────────────────────────────────────────┤
  │  Nom + statut appareil sélectionné                  │
  │  ┌ Sub-notebook ──────────────────────────────────┐ │
  │  │ 📥 Capteurs │ 📤 Actionneurs │ ⚡ Actions     │ │
  │  └────────────────────────────────────────────────┘ │
  └──────────────────────────────────────────────────────┘

Thread model : bus.subscribe → after(0, fn) pour tout callback
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Callable, Dict, Optional

from xrv22.theme import theme as T
from xrv22.ui.widgets import NeuFrame, SectionHeader, HSep, label
from xrv22.hardware.arduino_bridge import arduino, ArduinoDevice, ActuatorChannel
from xrv22.hardware.sensor_manager import sensor_manager
from xrv22.library.library_manager import library
from xrv22.library.models import ArduinoDeviceModel, AlertRuleModel
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("UI.Capteurs")

try:
    from serial.tools import list_ports as _lp
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False


class CapteursTab(tk.Frame):
    """
    Onglet Capteurs & Actionneurs.
    CC max par méthode : 8.
    """

    def __init__(self, parent: tk.Widget, on_after: Callable) -> None:
        super().__init__(parent, bg=T.BG)
        self._after = on_after
        self._selected_device: str = ""
        self._channel_rows: Dict[str, tk.Label] = {}   # sensor_id → value label

        self._build()
        self._subscribe()
        self._restore_from_library()

    # ── Construction ─────────────────────────────────────────────

    def _build(self) -> None:
        """CC=3 — Assemble le panneau."""
        self._build_toolbar()
        HSep(self).pack(fill="x")
        pane = tk.PanedWindow(self, orient="horizontal",
                               bg=T.BG, sashwidth=8, sashrelief="flat")
        pane.pack(fill="both", expand=True)
        left  = tk.Frame(pane, bg=T.BG, width=270)
        right = tk.Frame(pane, bg=T.BG)
        pane.add(left, minsize=220)
        pane.add(right, minsize=400)
        self._build_left(left)
        self._build_right(right)

    def _build_toolbar(self) -> None:
        """CC=3 — Barre de titre."""
        bar = tk.Frame(self, bg=T.SURFACE, pady=T.PAD_SM)
        bar.pack(fill="x")
        tk.Label(bar, text="Arduino USB — Capteurs & Actionneurs",
                  bg=T.SURFACE, fg=T.TEXT, font=T.F_SECTION).pack(side="left", padx=T.PAD_MD)
        serial_col = T.C_OK if SERIAL_OK else T.C_ERR
        serial_txt = "pyserial ✅" if SERIAL_OK else "pyserial ❌  (pip install pyserial)"
        tk.Label(bar, text=serial_txt, bg=T.SURFACE,
                  fg=serial_col, font=T.F_CAPTION).pack(side="right", padx=T.PAD_MD)

    def _build_left(self, parent: tk.Frame) -> None:
        """CC=5 — Panneau gauche : liste appareils + contrôles."""
        SectionHeader(parent, "Appareils").pack(fill="x", pady=(T.PAD_SM, T.PAD_XS))

        # Liste
        lf = tk.Frame(parent, bg=T.BG_DEEP)
        lf.pack(fill="both", expand=True, padx=T.PAD_SM)
        vsb = ttk.Scrollbar(lf, orient="vertical")
        vsb.pack(side="right", fill="y")
        self._device_list = tk.Listbox(
            lf, bg=T.SURFACE, fg=T.TEXT, font=T.F_MONO_MD,
            selectbackground=T.C_MAG_DIM2, selectforeground=T.C_AMB,
            relief="flat", borderwidth=0, height=6,
            yscrollcommand=vsb.set)
        self._device_list.pack(fill="both", expand=True)
        vsb.config(command=self._device_list.yview)
        self._device_list.bind("<<ListboxSelect>>", lambda _: self._on_device_select())

        # Boutons
        btn_row = tk.Frame(parent, bg=T.BG)
        btn_row.pack(fill="x", padx=T.PAD_SM, pady=T.PAD_XS)
        for lbl_text, cmd, w in [
            ("➕", self._add_device,         3),
            ("🔌", self._connect_selected,   3),
            ("⏏",  self._disconnect_selected,3),
            ("🗑",  self._remove_selected,    3),
            ("🔍", self._refresh_ports,       3),
        ]:
            ttk.Button(btn_row, text=lbl_text, width=w,
                        command=cmd).pack(side="left", padx=1)

        HSep(parent).pack(fill="x", pady=T.PAD_SM)

        # Port / Baud
        pf = tk.Frame(parent, bg=T.BG, padx=T.PAD_SM)
        pf.pack(fill="x")
        label(pf, "Port :").pack(anchor="w")
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(pf, textvariable=self._port_var,
                                         state="readonly", width=18)
        self._port_combo.pack(fill="x", pady=T.PAD_XS)

        label(pf, "Baud :").pack(anchor="w")
        self._baud_var = tk.IntVar(value=115200)
        ttk.Combobox(pf, textvariable=self._baud_var,
                      values=[9600, 19200, 57600, 115200, 230400],
                      state="readonly", width=10).pack(anchor="w", pady=T.PAD_XS)

        HSep(parent).pack(fill="x", pady=T.PAD_SM)

        # Info protocoles
        proto_f = tk.Frame(parent, bg=T.BG, padx=T.PAD_SM)
        proto_f.pack(fill="x")
        label(proto_f, "Protocoles (auto-détection)", style="med").pack(anchor="w")
        protos = ('📥  JSON : {"t":25.3,"d":142}\n'
                  '📥  KV   : t=25.3,d=142\n'
                  '📥  Colon: TEMP:25.3\n'
                  '📤  SET  : {"SET":"nom","v":128}')
        tk.Label(proto_f, text=protos, bg=T.BG, fg=T.TEXT_DIM,
                  font=T.F_MONO_SM, justify="left").pack(anchor="w")

    def _build_right(self, parent: tk.Frame) -> None:
        """CC=4 — Panneau droit : détail appareil + sous-onglets."""
        # Header dynamique
        self._dev_name_lbl = tk.Label(parent, text="Sélectionnez un appareil →",
                                       bg=T.BG, fg=T.TEXT, font=T.F_SECTION)
        self._dev_name_lbl.pack(anchor="w", padx=T.PAD_MD, pady=(T.PAD_SM, 0))
        self._dev_status_lbl = tk.Label(parent, text="",
                                         bg=T.BG, fg=T.TEXT_MED, font=T.F_CAPTION)
        self._dev_status_lbl.pack(anchor="w", padx=T.PAD_MD)

        # Sub-notebook
        self._sub_nb = ttk.Notebook(parent)
        self._sub_nb.pack(fill="both", expand=True, padx=T.PAD_SM, pady=T.PAD_SM)

        self._build_tab_capteurs(self._sub_nb)
        self._build_tab_actionneurs(self._sub_nb)
        self._build_tab_actions(self._sub_nb)
        self._build_tab_console(self._sub_nb)

    def _build_tab_capteurs(self, nb: ttk.Notebook) -> None:
        """CC=4 — Sous-onglet capteurs : tableau valeurs + alertes."""
        tab = tk.Frame(nb, bg=T.BG)
        nb.add(tab, text="📥 Capteurs")

        # Canvas scrollable pour les rangées de canaux
        outer = tk.Frame(tab, bg=T.BG)
        outer.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(outer, orient="vertical")
        vsb.pack(side="right", fill="y")
        ch_canvas = tk.Canvas(outer, bg=T.BG, highlightthickness=0,
                               yscrollcommand=vsb.set)
        ch_canvas.pack(fill="both", expand=True)
        vsb.config(command=ch_canvas.yview)
        self._channels_inner = tk.Frame(ch_canvas, bg=T.BG)
        self._channels_inner.bind("<Configure>",
            lambda e: ch_canvas.configure(scrollregion=ch_canvas.bbox("all")))
        ch_canvas.create_window((0, 0), window=self._channels_inner, anchor="nw")

        HSep(tab).pack(fill="x", pady=T.PAD_SM)

        # Zone alertes
        alert_f = tk.Frame(tab, bg=T.SURFACE, padx=T.PAD_SM, pady=T.PAD_XS)
        alert_f.pack(fill="x")
        label(alert_f, "⚠️  Alertes seuil :").pack(side="left")
        label(alert_f, "Canal :", style="med").pack(side="left", padx=(T.PAD_SM, T.PAD_XS))
        self._alert_ch_var = tk.StringVar()
        self._alert_ch_combo = ttk.Combobox(alert_f, textvariable=self._alert_ch_var,
                                              width=12, state="readonly")
        self._alert_ch_combo.pack(side="left")
        label(alert_f, "Min :", style="med").pack(side="left", padx=(T.PAD_SM, T.PAD_XS))
        self._alert_min_var = tk.StringVar()
        ttk.Entry(alert_f, textvariable=self._alert_min_var, width=7).pack(side="left")
        label(alert_f, "Max :", style="med").pack(side="left", padx=(T.PAD_SM, T.PAD_XS))
        self._alert_max_var = tk.StringVar()
        ttk.Entry(alert_f, textvariable=self._alert_max_var, width=7).pack(side="left")
        ttk.Button(alert_f, text="✅ Appliquer",
                    command=self._apply_alert).pack(side="left", padx=T.PAD_SM)
        ttk.Button(alert_f, text="🗑 Effacer",
                    command=self._clear_alert).pack(side="left")

    def _build_tab_actionneurs(self, nb: ttk.Notebook) -> None:
        """CC=4 — Sous-onglet actionneurs : liste + contrôle valeur."""
        tab = tk.Frame(nb, bg=T.BG)
        nb.add(tab, text="📤 Actionneurs")

        # Toolbar
        bar = tk.Frame(tab, bg=T.SURFACE)
        bar.pack(fill="x")
        ttk.Button(bar, text="➕ Ajouter",
                    command=self._add_actuator).pack(side="left", padx=T.PAD_SM, pady=T.PAD_XS)
        ttk.Button(bar, text="🗑 Supprimer",
                    command=self._remove_actuator).pack(side="left")

        # Treeview actionneurs
        cols = ("kind", "min", "max", "last")
        self._act_tree = ttk.Treeview(tab, columns=cols,
                                       show="headings tree", height=8)
        self._act_tree.heading("#0",    text="Nom")
        self._act_tree.heading("kind",  text="Type")
        self._act_tree.heading("min",   text="Min")
        self._act_tree.heading("max",   text="Max")
        self._act_tree.heading("last",  text="Dernière val.")
        self._act_tree.column("#0",    width=120)
        self._act_tree.column("kind",  width=80,  anchor="center")
        self._act_tree.column("min",   width=60,  anchor="center")
        self._act_tree.column("max",   width=60,  anchor="center")
        self._act_tree.column("last",  width=100, anchor="center")
        vsb = ttk.Scrollbar(tab, orient="vertical",
                              command=self._act_tree.yview)
        self._act_tree.configure(yscrollcommand=vsb.set)
        self._act_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        # Contrôle valeur
        ctrl_f = tk.Frame(tab, bg=T.SURFACE, padx=T.PAD_SM, pady=T.PAD_SM)
        ctrl_f.pack(fill="x", side="bottom")
        label(ctrl_f, "Valeur :").pack(side="left")
        self._act_val_var = tk.DoubleVar(value=0.0)
        ttk.Spinbox(ctrl_f, from_=0, to=255, increment=1,
                     textvariable=self._act_val_var,
                     width=8).pack(side="left", padx=T.PAD_SM)
        ttk.Button(ctrl_f, text="📤 Envoyer",
                    command=self._send_actuator).pack(side="left")

    def _build_tab_actions(self, nb: ttk.Notebook) -> None:
        """CC=4 — Sous-onglet actions RUN + ACK."""
        tab = tk.Frame(nb, bg=T.BG)
        nb.add(tab, text="⚡ Actions")

        # Treeview actions
        cols = ("label", "duration", "has_ack")
        self._act_tree2 = ttk.Treeview(tab, columns=cols,
                                        show="headings tree", height=8)
        self._act_tree2.heading("#0",       text="Nom")
        self._act_tree2.heading("label",    text="Label")
        self._act_tree2.heading("duration", text="Durée (ms)")
        self._act_tree2.heading("has_ack",  text="ACK ?")
        self._act_tree2.column("#0",       width=120)
        self._act_tree2.column("label",    width=160)
        self._act_tree2.column("duration", width=90, anchor="center")
        self._act_tree2.column("has_ack",  width=60, anchor="center")
        self._act_tree2.pack(fill="both", expand=True, padx=T.PAD_SM)

        btn_f = tk.Frame(tab, bg=T.SURFACE, padx=T.PAD_SM, pady=T.PAD_SM)
        btn_f.pack(fill="x")
        ttk.Button(btn_f, text="▶ Exécuter action",
                    command=self._run_action).pack(side="left")
        ttk.Button(btn_f, text="🔄 Recharger depuis Arduino",
                    command=self._re_identify).pack(side="left", padx=T.PAD_SM)

    def _build_tab_console(self, nb: ttk.Notebook) -> None:
        """CC=3 — Sous-onglet console série brute."""
        tab = tk.Frame(nb, bg=T.BG)
        nb.add(tab, text="🖥 Console")

        self._console_text = tk.Text(
            tab, bg=T.BG_DEEP, fg=T.TEXT_MED,
            font=T.F_MONO_SM, state="disabled",
            relief="flat", padx=T.PAD_SM)
        vsb = ttk.Scrollbar(tab, orient="vertical",
                              command=self._console_text.yview)
        self._console_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._console_text.pack(fill="both", expand=True)

        send_f = tk.Frame(tab, bg=T.SURFACE, padx=T.PAD_SM, pady=T.PAD_XS)
        send_f.pack(fill="x")
        self._raw_var = tk.StringVar()
        raw_entry = ttk.Entry(send_f, textvariable=self._raw_var,
                               width=40, font=T.F_MONO_MD)
        raw_entry.pack(side="left", fill="x", expand=True, padx=(0, T.PAD_SM))
        raw_entry.bind("<Return>", lambda _: self._send_raw())
        ttk.Button(send_f, text="Envoyer",
                    command=self._send_raw).pack(side="left")

    # ── Commandes ────────────────────────────────────────────────

    def _add_device(self) -> None:
        """CC=5 — Dialogue ajout appareil."""
        name = simpledialog.askstring("Ajouter Arduino",
            "Nom de l'appareil :", parent=self)
        if not name:
            return
        port = self._port_var.get()
        if not port:
            messagebox.showwarning("Port", "Sélectionnez un port série.", parent=self)
            return
        baud = self._baud_var.get()
        arduino.add_device(name, port, baud)
        self._refresh_device_list()
        self._save_to_library()

    def _connect_selected(self) -> None:
        """CC=4 — Connecte l'appareil sélectionné."""
        name = self._selected_device
        if not name:
            return
        ok = arduino.connect(name)
        if not ok:
            messagebox.showerror("Connexion",
                f"Impossible de connecter '{name}'.", parent=self)
        self._refresh_device_list()

    def _disconnect_selected(self) -> None:
        """CC=3 — Déconnecte l'appareil sélectionné."""
        if self._selected_device:
            arduino.disconnect(self._selected_device)
            self._refresh_device_list()

    def _remove_selected(self) -> None:
        """CC=4 — Supprime l'appareil sélectionné."""
        name = self._selected_device
        if not name:
            return
        ok = messagebox.askyesno("Supprimer",
            f"Supprimer '{name}' ?", parent=self)
        if ok:
            arduino.remove_device(name)
            self._selected_device = ""
            self._refresh_device_list()
            self._save_to_library()

    def _refresh_ports(self) -> None:
        """CC=3 — Détecte les ports série disponibles."""
        if not SERIAL_OK:
            return
        ports = [p.device for p in _lp.comports()]
        self._port_combo["values"] = ports
        if ports and not self._port_var.get():
            self._port_var.set(ports[0])

    def _on_device_select(self) -> None:
        """CC=4 — Met à jour le panneau droit pour l'appareil sélectionné."""
        sel = self._device_list.curselection()
        if not sel:
            return
        name = self._device_list.get(sel[0]).split(" ")[0]
        self._selected_device = name
        self._refresh_device_detail()

    def _refresh_device_list(self) -> None:
        """CC=4 — Recharge la liste des appareils."""
        self._device_list.delete(0, "end")
        for name, dev in arduino.devices.items():
            icon = "🟢" if dev.connected else "⚫"
            id_icon = " ✅" if dev.identified else ""
            self._device_list.insert("end", f"{name} {icon}{id_icon}")

    def _refresh_device_detail(self) -> None:
        """CC=6 — Met à jour le header + les 3 sous-onglets pour l'appareil courant."""
        dev = arduino.get_device(self._selected_device)
        if dev is None:
            return

        state = "🟢 Connecté" if dev.connected else "⚫ Déconnecté"
        fw = f"  — firmware {dev.firmware}" if dev.firmware else ""
        self._dev_name_lbl.config(text=dev.name)
        self._dev_status_lbl.config(text=f"{state}{fw}  |  {dev.port} @ {dev.baud}")

        self._refresh_channels(dev)
        self._refresh_actuators(dev)
        self._refresh_actions(dev)

    def _refresh_channels(self, dev: ArduinoDevice) -> None:
        """CC=5 — Reconstruit les rangées de canaux capteurs."""
        for w in self._channels_inner.winfo_children():
            w.destroy()
        self._channel_rows.clear()

        channels = list(dev.channels.values())
        if not channels:
            label(self._channels_inner,
                  "Aucun capteur détecté.\nConnectez et attendez IDENTIFY.", style="dim"
                  ).pack(pady=T.PAD_LG)
            return

        for i, ch in enumerate(channels):
            row_bg = T.SURFACE if i % 2 == 0 else T.SURFACE_HI
            row = tk.Frame(self._channels_inner, bg=row_bg, padx=T.PAD_SM, pady=2)
            row.pack(fill="x")
            tk.Label(row, text=ch.name, bg=row_bg, fg=T.C_AMB,
                      font=T.F_MONO_MD, width=16, anchor="w").pack(side="left")
            val_lbl = tk.Label(row, text=f"{ch.value:.2f}",
                                bg=row_bg, fg=T.TEXT, font=T.F_MONO_MD, width=10)
            val_lbl.pack(side="left")
            tk.Label(row, text=ch.unit, bg=row_bg, fg=T.TEXT_DIM,
                      font=T.F_CAPTION, width=6).pack(side="left")
            sensor_id = f"{dev.name}.{ch.name}"
            self._channel_rows[sensor_id] = val_lbl

        # Alerte combo
        ch_names = [f"{dev.name}.{c.name}" for c in channels]
        self._alert_ch_combo["values"] = ch_names

    def _refresh_actuators(self, dev: ArduinoDevice) -> None:
        """CC=4 — Recharge la treeview des actionneurs."""
        for item in self._act_tree.get_children():
            self._act_tree.delete(item)
        for name, act in dev.actuators.items():
            self._act_tree.insert("", "end", iid=name, text=name,
                                   values=(act.kind, act.min_val,
                                           act.max_val, act.last_value))

    def _refresh_actions(self, dev: ArduinoDevice) -> None:
        """CC=4 — Recharge la treeview des actions."""
        for item in self._act_tree2.get_children():
            self._act_tree2.delete(item)
        for name, ac in dev.actions.items():
            self._act_tree2.insert("", "end", iid=name, text=name,
                                    values=(ac.label, ac.duration_ms,
                                            "✅" if ac.has_ack else "—"))

    def _add_actuator(self) -> None:
        """CC=5 — Dialogue ajout actionneur manuel."""
        dev = arduino.get_device(self._selected_device)
        if dev is None:
            return
        name = simpledialog.askstring("Ajouter actionneur", "Nom :", parent=self)
        if not name:
            return
        dev.actuators[name] = ActuatorChannel(name=name)
        self._refresh_actuators(dev)

    def _remove_actuator(self) -> None:
        """CC=4 — Supprime l'actionneur sélectionné."""
        sel = self._act_tree.selection()
        if not sel:
            return
        dev = arduino.get_device(self._selected_device)
        if dev:
            dev.actuators.pop(sel[0], None)
            self._refresh_actuators(dev)

    def _send_actuator(self) -> None:
        """CC=5 — Envoie la valeur à l'actionneur sélectionné."""
        sel = self._act_tree.selection()
        if not sel:
            messagebox.showinfo("Actionneur", "Sélectionnez un actionneur.", parent=self)
            return
        val = self._act_val_var.get()
        ok = arduino.send_command(self._selected_device, sel[0], val)
        if not ok:
            messagebox.showerror("Envoi", "Impossible d'envoyer la commande.", parent=self)
        else:
            self._refresh_actuators(arduino.get_device(self._selected_device))

    def _run_action(self) -> None:
        """CC=4 — Lance l'action sélectionnée (thread séparé)."""
        sel = self._act_tree2.selection()
        if not sel:
            messagebox.showinfo("Action", "Sélectionnez une action.", parent=self)
            return
        import threading
        threading.Thread(
            target=self._run_action_bg,
            args=(self._selected_device, sel[0]),
            daemon=True).start()

    def _run_action_bg(self, device: str, action: str) -> None:
        """CC=4 — Exécute l'action en arrière-plan."""
        ok, msg = arduino.run_action(device, action)
        status = "✅ " + msg if ok else "❌ " + msg
        _LOG.info("[%s] Action %s : %s", device, action, status)
        self._after(0, lambda: self._console_append(
            f"[{device}] RUN {action} → {status}"))

    def _re_identify(self) -> None:
        """CC=3 — Relance le handshake IDENTIFY."""
        if not self._selected_device:
            return
        import threading
        threading.Thread(
            target=arduino._identify_device,
            args=(self._selected_device,),
            daemon=True).start()

    def _send_raw(self) -> None:
        """CC=4 — Envoie une commande brute."""
        cmd = self._raw_var.get().strip()
        if not cmd:
            return
        ok = arduino.send_raw(self._selected_device, cmd)
        self._raw_var.set("")
        self._console_append(f"→ {cmd}" + ("" if ok else "  [ERREUR]"))

    def _console_append(self, line: str) -> None:
        """CC=3 — Ajoute une ligne dans la console."""
        self._console_text.config(state="normal")
        self._console_text.insert("end", line + "\n")
        self._console_text.see("end")
        self._console_text.config(state="disabled")

    def _apply_alert(self) -> None:
        """CC=6 — Applique une règle d'alerte seuil."""
        ch = self._alert_ch_var.get()
        if not ch:
            return
        try:
            min_v = float(self._alert_min_var.get()) if self._alert_min_var.get() else None
            max_v = float(self._alert_max_var.get()) if self._alert_max_var.get() else None
        except ValueError:
            messagebox.showerror("Alerte", "Valeurs min/max invalides.", parent=self)
            return
        sensor_manager.add_rule(ch, min_val=min_v, max_val=max_v)
        _LOG.info("Règle alerte : %s  min=%s max=%s", ch, min_v, max_v)
        self._save_to_library()

    def _clear_alert(self) -> None:
        """CC=3 — Supprime la règle d'alerte du canal sélectionné."""
        ch = self._alert_ch_var.get()
        if ch:
            sensor_manager.remove_rule(ch)
            self._save_to_library()

    # ── Mise à jour temps réel ───────────────────────────────────

    def _update_channel_value(self, payload: dict) -> None:
        """CC=5 — Met à jour les labels de valeur capteur."""
        device = payload.get("device", "")
        values = payload.get("values", {})
        if not values:
            sid = payload.get("sensor_id", "")
            val = payload.get("value", 0.0)
            if sid and sid in self._channel_rows:
                self._channel_rows[sid].config(text=f"{float(val):.2f}")
            return
        for ch_name, ch_val in values.items():
            sid = f"{device}.{ch_name}"
            if sid in self._channel_rows:
                self._channel_rows[sid].config(text=f"{float(ch_val):.2f}")

    # ── Souscriptions bus ────────────────────────────────────────

    def _subscribe(self) -> None:
        """CC=2 — Souscrit aux événements Arduino."""
        bus.subscribe("arduino.connected",    self._on_device_event)
        bus.subscribe("arduino.disconnected", self._on_device_event)
        bus.subscribe("arduino.identified",   self._on_identified)
        bus.subscribe("arduino.error",        self._on_device_event)
        bus.subscribe("sensor.reading",       self._on_sensor_reading)
        bus.subscribe("sensor.alert",         self._on_sensor_alert)

    def destroy(self) -> None:
        bus.unsubscribe_object(self)
        super().destroy()

    def _on_device_event(self, payload: dict) -> None:
        """CC=2 — Refresh liste + détail sur changement d'état."""
        self._after(0, self._refresh_device_list)
        if payload.get("name") == self._selected_device:
            self._after(0, self._refresh_device_detail)

    def _on_identified(self, payload: dict) -> None:
        """CC=3 — Refresh complet quand IDENTIFY reçu + sauvegarde."""
        self._after(0, self._refresh_device_list)
        if payload.get("name") == self._selected_device:
            self._after(0, self._refresh_device_detail)
        self._after(100, self._save_to_library)

    def _on_sensor_reading(self, payload: dict) -> None:
        """CC=2 — Mise à jour valeurs capteurs."""
        self._after(0, lambda p=payload: self._update_channel_value(p))

    def _on_sensor_alert(self, payload: dict) -> None:
        """CC=3 — Affiche l'alerte dans la console."""
        msg = payload.get("message", "")
        self._after(0, lambda m=msg: self._console_append(f"⚠️  {m}"))

    # ── Persistance Arduino / capteurs ────────────────────────

    def _save_to_library(self) -> None:
        """CC=3 — Sauvegarde la config Arduino dans la library du projet."""
        hw = library.get_hardware_config()
        hw.devices = [
            ArduinoDeviceModel.from_dict(d)
            for d in arduino.snapshot_devices()
        ]
        hw.alert_rules = [
            AlertRuleModel.from_dict(r)
            for r in sensor_manager.snapshot_rules()
        ]
        library.save_hardware_config(hw)
        _LOG.debug("Config Arduino sauvegardée dans la library")

    def _restore_from_library(self) -> None:
        """CC=4 — Restaure les devices Arduino et règles depuis la library."""
        hw = library.get_hardware_config()
        if hw.devices:
            device_dicts = [d.to_dict() for d in hw.devices]
            arduino.restore_devices(device_dicts)
            self._refresh_device_list()
            _LOG.info("Restauré %d appareil(s) Arduino depuis la library",
                       len(hw.devices))
            # Auto-reconnexion en arrière-plan (délai pour laisser l'UI se construire)
            self._after(2000, self._auto_reconnect_devices)
        if hw.alert_rules:
            rule_dicts = [r.to_dict() for r in hw.alert_rules]
            sensor_manager.restore_rules(rule_dicts)
            _LOG.info("Restauré %d règle(s) d'alerte depuis la library",
                       len(hw.alert_rules))

    def _auto_reconnect_devices(self) -> None:
        """CC=5 — Tente de reconnecter les devices Arduino sur les ports mémorisés."""
        available = set()
        try:
            available = {p.device for p in _lp.comports()}
        except Exception:
            return
        for name, dev in arduino.devices.items():
            if dev.connected:
                continue
            if dev.port not in available:
                _LOG.debug("[%s] Port %s non disponible, skip", name, dev.port)
                continue
            _LOG.info("[%s] Auto-reconnexion sur %s...", name, dev.port)
            threading.Thread(
                target=self._try_reconnect, args=(name,),
                daemon=True, name=f"AutoReconnect-{name}").start()

    def _try_reconnect(self, name: str) -> None:
        """CC=2 — Tentative de connexion en thread (ne bloque pas l'UI)."""
        ok = arduino.connect(name)
        if ok:
            _LOG.info("[%s] Auto-reconnexion réussie", name)
        else:
            _LOG.warning("[%s] Auto-reconnexion échouée", name)
