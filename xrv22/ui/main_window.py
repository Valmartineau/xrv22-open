"""
xrv22/ui/main_window.py — UI Tk Mac (DEPRECIE 2026-05-11)

Cette UI n'est plus l'interface principale d'XRV22. L'usage quotidien
passe par http://raspberrypi.local:8080/ (UI web servie par le Pi).

Code conserve comme :
  - Reference visuelle pour reproduire fidelement les ecrans web
  - Backup fonctionnel en cas de probleme navigateur
  - Mode dev offline (`python3 -m xrv22.main --sim` sans Pi)

Ne plus ajouter de nouvelles features ici — tout passe par `web/src/pages/`.
"""
from __future__ import annotations
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from typing import Optional

from xrv22.theme import theme as T
from xrv22.ui.style_setup import setup_styles
from xrv22.ui.status_bar import StatusBar
from xrv22.ui.sidebar import Sidebar
from xrv22.ui.tab_connexion import ConnexionTab
from xrv22.ui.tab_positions import PositionsTab
from xrv22.ui.tab_capteurs import CapteursTab
from xrv22.ui.tab_library import LibraryTab
from xrv22.ui.timeline_panel import TimelinePanel
from xrv22.ui.diagnostics_panel import DiagnosticsPanel
from xrv22.ui.tab_visu import VisuTab
from xrv22.ui.i18n import (TAB_CONNEXION, TAB_TIMELINE, TAB_LIBRARY,
                            TAB_POSITIONS, TAB_CAPTEURS, TAB_LOGS,
                            TOPBAR_TITRE, TOPBAR_SOUS, APP_VERSION)
from xrv22.ui.keyboard import (shortcuts, setup_focus_style,
                                setup_tab_navigation, show_shortcuts_dialog)
from xrv22.timeline.timeline_model import TimelineModel
from xrv22.robots.robot_registry import registry
from xrv22.core.execution_engine import engine
from xrv22.core.safety_manager import safety
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger
from xrv22.library.library_manager import library
from xrv22.services.project_service import project
from xrv22.config import AUTOSAVE_INTERVAL_MS

_LOG = get_logger("XRV22.MainWindow")


class MainWindow(tk.Tk):
    """Fenêtre principale XRV22 PRO V22."""

    def __init__(self, simulation: bool = False) -> None:
        super().__init__()
        self._simulation = simulation
        self._timeline_model = TimelineModel()
        self._configure_window()
        self._setup_styles()
        self._setup_robots()   # avant _build : registry doit avoir des IDs
        self._build()
        self._setup_bindings()
        engine.set_model(self._timeline_model)
        # Connecte la timeline au service de projet pour la persistence
        from xrv22.services.project_service import project
        project.set_timeline(self._timeline_model)
        if simulation:
            self._start_sim_scene()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Auto-save toutes les 60 secondes
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_loop)
        # Auto-reconnexion différée (après que l'UI soit visible)
        self.after(1500, self._auto_reconnect)
        # Ecoute erreurs hardware moteur pour popup
        bus.subscribe("motor.hardware_error", self._on_motor_hardware_error)
        # Ecoute erreurs handler timeline (sinon arret silencieux en cours d'execution)
        bus.subscribe("engine.error", self._on_engine_error)
        bus.subscribe("engine.zone_collision", self._on_engine_zone_collision)

    def _configure_window(self) -> None:
        self.title("XRV22 PRO — Robot Control Station")
        self.geometry("1380x820")
        self.minsize(1000, 640)
        self.configure(bg=T.BG)

    def _setup_styles(self) -> None:
        setup_styles(self)
        setup_focus_style(self)

    def _build(self) -> None:
        root = tk.Frame(self, bg=T.BG)
        root.pack(fill="both", expand=True)

        self._sidebar = Sidebar(root,
            on_stop_soft=self._stop_soft,
            on_estop=self._emergency_stop)
        self._sidebar.pack(side="left", fill="y")

        main = tk.Frame(root, bg=T.BG)
        main.pack(side="left", fill="both", expand=True)

        self._build_topbar(main)
        self._build_notebook(main)
        # FIX: on_after obligatoire dans StatusBar
        self._status_bar = StatusBar(main, on_after=self.after)
        self._status_bar.pack(side="bottom", fill="x")

    def _build_topbar(self, parent: tk.Frame) -> None:
        tb_bg = T.SURFACE_HI
        topbar = tk.Frame(parent, bg=tb_bg,
                          highlightbackground=T.BORDER,
                          highlightthickness=0, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Frame(topbar, bg=T.C_MAG, height=1).pack(fill="x", side="bottom")
        inner = tk.Frame(topbar, bg=tb_bg)
        inner.pack(fill="both", expand=True, padx=20)
        dot = tk.Canvas(inner, width=10, height=10, bg=tb_bg, highlightthickness=0)
        dot.pack(side="left", padx=(0, 8))
        dot.create_oval(1, 1, 9, 9, fill=T.C_MAG_2, outline="")
        tk.Label(inner, text=TOPBAR_TITRE, bg=tb_bg, fg=T.TEXT, font=T.F_TITLE).pack(side="left")
        tk.Label(inner, text=TOPBAR_SOUS, bg=tb_bg, fg=T.TEXT_MED, font=T.F_LABEL).pack(side="left")
        tk.Label(inner, text=f" {APP_VERSION} ", bg=T.C_MAG_DIM2, fg=T.C_MAG_2,
                 font=T.F_MONO_SM, padx=4, pady=2).pack(side="left", padx=8)
        if self._simulation:
            tk.Label(inner, text=" SIM ", bg=T.C_AMB_DIM2, fg=T.C_AMB,
                     font=T.F_MONO_SM, padx=4, pady=2).pack(side="left", padx=4)
        clk_pill = tk.Frame(inner, bg=T.SURFACE, highlightbackground=T.C_AMB, highlightthickness=1)
        clk_pill.pack(side="right", pady=12)
        self._clock_lbl = tk.Label(clk_pill, text="", bg=T.SURFACE, fg=T.C_AMB,
                                    font=T.F_MONO_SM, padx=14, pady=3)
        self._clock_lbl.pack()

        # ── Boutons projet ──
        proj_btns = tk.Frame(inner, bg=tb_bg)
        proj_btns.pack(side="right", padx=(0, 10))
        for txt, cmd in [
            ("📤", self._export_project),
            ("💾", self._save_project),
            ("➕", self._new_project),
            ("📂", self._load_project),
        ]:
            b = tk.Label(proj_btns, text=txt, bg=T.SURFACE, fg=T.TEXT,
                         font=T.F_CONTROL, padx=6, pady=2, cursor="hand2",
                         relief="flat",
                         highlightbackground=T.BORDER, highlightthickness=1)
            b.pack(side="right", padx=2)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.config(bg=T.C_MAG_DIM2))
            b.bind("<Leave>", lambda e, w=b: w.config(bg=T.SURFACE))

        # ── Info projet ──
        proj_f = tk.Frame(inner, bg=tb_bg)
        proj_f.pack(side="right", padx=(0, 8))
        self._proj_name_lbl = tk.Label(
            proj_f, text="", bg=tb_bg, fg=T.C_AMB,
            font=T.F_CONTROL, anchor="e")
        self._proj_name_lbl.pack(anchor="e")
        self._proj_name_lbl.bind("<Double-1>", self._rename_project)
        self._proj_name_lbl.config(cursor="hand2")
        self._proj_info_lbl = tk.Label(
            proj_f, text="", bg=tb_bg, fg=T.TEXT_DIM,
            font=T.F_MONO_SM, anchor="e")
        self._proj_info_lbl.pack(anchor="e")

        self._update_clock()
        self._update_project_info()
        bus.subscribe("project.loaded", lambda _: self.after(100, self._update_project_info))
        bus.subscribe("project.saved", lambda _: self.after(100, self._update_project_info))
        bus.subscribe("project.new", lambda _: self.after(100, self._update_project_info))

    def _update_clock(self) -> None:
        now = datetime.datetime.now().strftime("%H:%M:%S  ·  %d/%m/%Y")
        if hasattr(self, "_clock_lbl"):
            self._clock_lbl.config(text=now)
        self.after(1000, self._update_clock)

    def _update_project_info(self) -> None:
        """CC=4 — Met à jour le nom, la taille et la date du projet dans la topbar."""
        if not hasattr(self, "_proj_name_lbl"):
            return
        name = library.project_name or "—"
        self._proj_name_lbl.config(text=f"📁 {name}")
        proj_dir = library.project_dir
        if proj_dir and proj_dir.exists():
            # Taille du dossier
            total = sum(f.stat().st_size for f in proj_dir.rglob("*") if f.is_file())
            if total < 1024:
                size_str = f"{total} o"
            elif total < 1024 * 1024:
                size_str = f"{total / 1024:.1f} Ko"
            else:
                size_str = f"{total / (1024 * 1024):.1f} Mo"
            # Date dernière modification
            meta_path = library.project_path
            if meta_path and meta_path.exists():
                mtime = meta_path.stat().st_mtime
                date_str = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
            else:
                date_str = "—"
            self._proj_info_lbl.config(text=f"{size_str}  ·  {date_str}")
        else:
            self._proj_info_lbl.config(text="")

    # ── Renommer projet (double-clic) ──────────────────────────────────────────

    def _rename_project(self, _event=None) -> None:
        """CC=3 — Double-clic sur le nom du projet → renommer."""
        current = library.project_name or ""
        new_name = simpledialog.askstring(
            "Renommer projet",
            "Nouveau nom du projet :",
            initialvalue=current,
            parent=self)
        if not new_name or new_name.strip() == current:
            return
        library.set_project_name(new_name)
        library.save_project()
        self._update_project_info()

    # ── Menu projet (topbar) ──────────────────────────────────────────────────

    def _load_project(self) -> None:
        """CC=6 — Dialogue FR pour charger un projet existant."""
        dlg = tk.Toplevel(self)
        dlg.title("Charger un projet")
        dlg.geometry("420x400")
        dlg.configure(bg=T.BG)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Charger un projet", bg=T.BG, fg=T.TEXT,
                 font=T.F_SECTION).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(dlg, text="Sélectionnez un projet existant ou parcourez le disque.",
                 bg=T.BG, fg=T.TEXT_DIM, font=T.F_CAPTION
                 ).pack(anchor="w", padx=20, pady=(0, 10))

        tk.Label(dlg, text="Projets disponibles :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).pack(anchor="w", padx=20, pady=(0, 4))

        list_f = tk.Frame(dlg, bg=T.BORDER_HI, bd=2, relief="flat")
        list_f.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        lb = tk.Listbox(list_f, font=T.F_CONTROL, height=8,
                         bg=T.SURFACE, fg=T.TEXT,
                         selectbackground=T.C_MAG_DIM2,
                         selectforeground=T.C_AMB,
                         activestyle="none", borderwidth=0,
                         highlightthickness=0, relief="flat")
        lb.pack(fill="both", expand=True, padx=2, pady=2)

        projects = library.list_projects()
        project_paths = {}
        current_name = library.project_name
        for i, pinfo in enumerate(projects):
            marker = "  ◄ actuel" if pinfo.name == current_name else ""
            detail = f"  {pinfo.position_count} pos. · {pinfo.suite_count} suites"
            lb.insert(tk.END, f"  📁  {pinfo.name}{detail}{marker}")
            project_paths[i] = pinfo.path
            if pinfo.name == current_name:
                lb.itemconfig(i, fg=T.C_AMB)

        result = {"path": None}

        def _on_select():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning("Charger",
                                       "Sélectionnez un projet dans la liste.",
                                       parent=dlg)
                return
            result["path"] = project_paths[sel[0]]
            dlg.destroy()

        def _on_browse():
            initial = str(library.root / "projects")
            path = filedialog.askdirectory(
                title="Sélectionner un dossier projet",
                initialdir=initial, parent=dlg)
            if not path:
                return
            p = Path(path)
            xrv_files = list(p.glob("*.xrv22"))
            if not xrv_files:
                messagebox.showwarning("Charger",
                                       "Aucun fichier projet (.xrv22) trouvé\n"
                                       "dans ce dossier.", parent=dlg)
                return
            result["path"] = str(xrv_files[0])
            dlg.destroy()

        lb.bind("<Double-1>", lambda e: _on_select())

        btn_f = tk.Frame(dlg, bg=T.BG)
        btn_f.pack(fill="x", padx=20, pady=(0, 16))
        ttk.Button(btn_f, text="📂 Parcourir le disque…",
                   command=_on_browse).pack(side="left")
        ttk.Button(btn_f, text="Annuler",
                   command=dlg.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(btn_f, text="✅ Ouvrir",
                   command=_on_select).pack(side="right")

        self._center_dialog(dlg)
        dlg.wait_window()

        if result["path"]:
            project.save()
            ok = project.load(result["path"])
            if ok:
                self._update_project_info()
                self._sidebar._refresh_list()
                _LOG.info("Projet chargé : %s", library.project_name)
            else:
                messagebox.showerror("Erreur",
                                     "Impossible de charger ce projet.")

    def _new_project(self) -> None:
        """CC=7 — Dialogue FR pour créer un nouveau projet."""
        dlg = tk.Toplevel(self)
        dlg.title("Nouveau projet")
        dlg.geometry("440x320")
        dlg.configure(bg=T.BG)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Créer un nouveau projet", bg=T.BG, fg=T.TEXT,
                 font=T.F_SECTION).pack(anchor="w", padx=20, pady=(16, 4))
        tk.Label(dlg, text="Choisissez un nom et un emplacement pour votre projet.",
                 bg=T.BG, fg=T.TEXT_DIM, font=T.F_CAPTION
                 ).pack(anchor="w", padx=20, pady=(0, 12))

        tk.Label(dlg, text="Nom du projet :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).pack(anchor="w", padx=20, pady=(0, 4))
        name_entry = tk.Entry(dlg, font=T.F_CONTROL, bg=T.SURFACE,
                               fg=T.TEXT, insertbackground=T.C_AMB, width=30)
        name_entry.pack(fill="x", padx=20, pady=(0, 10))
        name_entry.focus_set()

        tk.Label(dlg, text="Emplacement :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).pack(anchor="w", padx=20, pady=(0, 4))

        location_var = tk.StringVar(value="local")
        loc_f = tk.Frame(dlg, bg=T.BG)
        loc_f.pack(fill="x", padx=20, pady=(0, 4))

        local_path = str(library.root / "projects")
        tk.Radiobutton(loc_f, text="Librairie locale",
                        variable=location_var, value="local",
                        bg=T.BG, fg=T.TEXT, selectcolor=T.SURFACE,
                        activebackground=T.BG, activeforeground=T.C_AMB,
                        font=T.F_CONTROL).pack(anchor="w")
        tk.Label(loc_f, text=f"  {local_path}", bg=T.BG, fg=T.TEXT_DIM,
                 font=T.F_MONO_SM).pack(anchor="w", pady=(0, 4))

        tk.Radiobutton(loc_f, text="Emplacement personnalisé",
                        variable=location_var, value="custom",
                        bg=T.BG, fg=T.TEXT, selectcolor=T.SURFACE,
                        activebackground=T.BG, activeforeground=T.C_AMB,
                        font=T.F_CONTROL).pack(anchor="w")

        custom_f = tk.Frame(dlg, bg=T.BG)
        custom_f.pack(fill="x", padx=20, pady=(0, 4))
        custom_path_var = tk.StringVar(value="")
        custom_entry = tk.Entry(custom_f, textvariable=custom_path_var,
                                 font=T.F_MONO_SM, bg=T.SURFACE,
                                 fg=T.TEXT, insertbackground=T.C_AMB,
                                 state="disabled")
        custom_entry.pack(side="left", fill="x", expand=True, padx=(16, 4))
        ttk.Button(custom_f, text="📂",
                   command=lambda: self._browse_custom_path(
                       custom_path_var, custom_entry, dlg)).pack(side="left")

        def _on_location_change(*_):
            custom_entry.config(
                state="normal" if location_var.get() == "custom" else "disabled")
        location_var.trace_add("write", _on_location_change)

        error_lbl = tk.Label(dlg, text="", bg=T.BG, fg=T.C_ERR,
                              font=T.F_CAPTION)
        error_lbl.pack(anchor="w", padx=20, pady=(2, 4))

        result = {"name": None, "path": None}

        def _validate():
            name = name_entry.get().strip()
            if not name:
                error_lbl.config(text="⚠ Le nom ne peut pas être vide.")
                return
            if location_var.get() == "local":
                existing = [p.name for p in library.list_projects()]
                if name in existing:
                    error_lbl.config(text=f"⚠ Le projet « {name} » existe déjà.")
                    return
                result["name"] = name
                result["path"] = None
            else:
                cpath = custom_path_var.get().strip()
                if not cpath:
                    error_lbl.config(text="⚠ Choisissez un dossier d'emplacement.")
                    return
                target = Path(cpath) / name
                if target.exists() and list(target.glob("*.xrv22")):
                    error_lbl.config(text="⚠ Un projet existe déjà à cet emplacement.")
                    return
                result["name"] = name
                result["path"] = str(target)
            dlg.destroy()

        name_entry.bind("<Return>", lambda e: _validate())
        btn_f = tk.Frame(dlg, bg=T.BG)
        btn_f.pack(fill="x", padx=20, pady=(0, 16))
        ttk.Button(btn_f, text="Annuler",
                   command=dlg.destroy).pack(side="right", padx=(4, 0))
        ttk.Button(btn_f, text="✅ Créer le projet",
                   command=_validate).pack(side="right")

        self._center_dialog(dlg, 440, 320)
        dlg.wait_window()

        if result["name"]:
            project.save()
            if result["path"]:
                project.new_project_at(result["name"], result["path"])
            else:
                project.new_project(result["name"])
            self._update_project_info()
            self._sidebar._refresh_list()
            _LOG.info("Nouveau projet créé : %s", result["name"])

    def _save_project(self) -> None:
        """CC=3 — Enregistre le projet courant."""
        ok = project.save()
        if ok:
            self._update_project_info()
            _LOG.info("Projet enregistré : %s", library.project_name)
        else:
            messagebox.showwarning("Enregistrer",
                                   "Aucun projet chargé à enregistrer.")

    def _export_project(self) -> None:
        """CC=4 — Exporte le projet courant vers un emplacement choisi."""
        if not library.loaded:
            messagebox.showwarning("Exporter",
                                   "Aucun projet chargé à exporter.")
            return
        project.save()
        dest = filedialog.askdirectory(
            title="Choisir le dossier de destination", parent=self)
        if not dest:
            return
        ok = library.export_project(Path(dest))
        if ok:
            messagebox.showinfo(
                "Exporter",
                f"Projet « {library.project_name} » exporté\n"
                f"vers : {dest}/{library.project_dir.name}")
            _LOG.info("Projet exporté vers %s", dest)
        else:
            messagebox.showerror("Exporter",
                                 "Erreur lors de l'export du projet.")

    @staticmethod
    def _browse_custom_path(path_var: tk.StringVar,
                            entry: tk.Entry, parent: tk.Widget) -> None:
        chosen = filedialog.askdirectory(
            title="Choisir le dossier parent du projet", parent=parent)
        if chosen:
            path_var.set(chosen)
            entry.config(state="normal")

    def _center_dialog(self, dlg: tk.Toplevel,
                       w: int = 0, h: int = 0) -> None:
        """Centre un dialogue par rapport à la fenêtre principale."""
        dlg.update_idletasks()
        if not w:
            w = dlg.winfo_reqwidth()
        if not h:
            h = dlg.winfo_reqheight()
        x = self.winfo_x() + (self.winfo_width() - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        dlg.geometry(f"+{x}+{y}")

    # ── Notebook ───────────────────────────────────────────────────────────────

    def _build_notebook(self, parent: tk.Frame) -> None:
        nb_frame = tk.Frame(parent, bg=T.BG)
        nb_frame.pack(fill="both", expand=True)
        self._notebook = ttk.Notebook(nb_frame)
        self._notebook.pack(fill="both", expand=True)
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self._build_tab_connexion()    # "📡 Connexion"
        self._build_tab_positions()    # "📁 Positions & Suites"
        self._build_tab_timeline()     # "⏱️  Timeline"
        self._build_tab_capteurs()     # "📊 Capteurs & Actionneurs"
        self._build_tab_library()      # "📚 Librairie"
        self._build_tab_visu()         # "🤖 Visualisation 3D"
        self._build_tab_regles()       # "⚙️  Règles"
        self._build_tab_logs()         # "📝 Logs"

    def _build_tab_connexion(self) -> None:
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text=TAB_CONNEXION)
        self._connexion_tab = ConnexionTab(tab, on_after=self.after)
        self._connexion_tab.pack(fill="both", expand=True)

    def _build_tab_positions(self) -> None:
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text=TAB_POSITIONS)
        # FIX: active_robot_fn appelle la méthode avec ()
        # FIX: pack() appelé une seule fois
        self._positions_tab = PositionsTab(
            tab,
            on_after=self.after,
            active_robot_fn=lambda: self._sidebar.active_robot_id())
        self._positions_tab.pack(fill="both", expand=True)

    def _build_tab_timeline(self) -> None:
        tab = ttk.Frame(self._notebook, padding=0)
        self._notebook.add(tab, text=TAB_TIMELINE)
        self._timeline_panel = TimelinePanel(
            tab, model=self._timeline_model, on_after=self.after)
        # FIX: était 'panel.pack' (NameError) — corrigé en self._timeline_panel.pack
        self._timeline_panel.pack(fill="both", expand=True)

    def _build_tab_capteurs(self) -> None:
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text=TAB_CAPTEURS)
        self._capteurs_tab = CapteursTab(tab, on_after=self.after)
        self._capteurs_tab.pack(fill="both", expand=True)

    def _build_tab_library(self) -> None:
        """Onglet Librairie — gestion centralisée des données du projet."""
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text=TAB_LIBRARY)
        self._library_tab = LibraryTab(
            tab, on_after=self.after,
            active_robot_fn=lambda: self._sidebar.active_robot_id())
        self._library_tab.pack(fill="both", expand=True)

    def _build_tab_visu(self) -> None:
        """Onglet Visualisation 3D — wireframe Canvas temps réel."""
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text="🤖 Visualisation 3D")
        self._visu_tab = VisuTab(
            tab, on_after=self.after,
            active_robot_fn=lambda: self._sidebar.active_robot_id(),
            timeline_model=self._timeline_model)
        self._visu_tab.pack(fill="both", expand=True)

    def _build_tab_logs(self) -> None:
        tab = ttk.Frame(self._notebook)
        self._notebook.add(tab, text=TAB_LOGS)
        self._diag_panel = DiagnosticsPanel(tab, on_after=self.after)
        self._diag_panel.pack(fill="both", expand=True)

    def _build_tab_regles(self) -> None:
        """Onglet Règles — placeholder."""
        tab = ttk.Frame(self._notebook, padding=20)
        self._notebook.add(tab, text="⚙️  Règles")
        ttk.Label(tab, text="⚙️  Règles — Fonctionnalité à venir",
                  font=(T.FONT_UI, 14)).pack(pady=50)

    def _setup_robots(self) -> None:
        """S'assure que les robots du projet existent dans le registre.
        Les homes/params sont déjà restaurés par project.load() → _restore_robots().
        Ici on ne fait que créer les robots manquants (cas new_project sans load)."""
        from xrv22.library.library_manager import library
        robots_cfg = library.list_robots()
        if robots_cfg:
            for rcfg in robots_cfg:
                rid = rcfg.robot_id
                if not rid:
                    continue
                if rid not in registry.ids():
                    ids = rcfg.motor_ids or list(range(1, 8))
                    ctrl = registry.add(rid, ids, simulation=self._simulation)
                    hm = rcfg.home_machine
                    hw = rcfg.home_work
                    if hm:
                        ctrl.set_home_machine({int(k): v for k, v in hm.items()})
                    if hw:
                        ctrl.set_home_work({int(k): v for k, v in hw.items()})
                    sl = rcfg.soft_limits
                    if sl:
                        for mid, lim in sl.items():
                            ctrl.profile.soft_limits[int(mid)] = tuple(lim)
                    mp = rcfg.motion_params
                    if mp:
                        ctrl.set_motion_params(
                            mp.get("smooth_hz", 60),
                            mp.get("comfort_vel", 120),
                            mp.get("comfort_acc", 40),
                            home_duration=mp.get("home_duration", 3.0))
                    _LOG.info("Robot '%s' créé depuis config projet", rid)
                else:
                    _LOG.info("Robot '%s' déjà dans le registre (restauré par project.load)", rid)
        if not registry.ids():
            for rid in ("robot_1", "robot_2", "robot_3"):
                registry.add(rid, list(range(1, 8)), simulation=self._simulation)
                _LOG.info("Robot par défaut '%s' enregistré", rid)

        # Cleanup : retirer du registry les robots absents de la library
        # (evite que l'autosave ressuscite des robots supprimes manuellement)
        allowed_ids = {rcfg.robot_id for rcfg in robots_cfg if rcfg.robot_id}
        if allowed_ids:
            for rid in list(registry.ids()):
                if rid not in allowed_ids:
                    ctrl = registry.get(rid)
                    if ctrl:
                        try:
                            ctrl.disconnect()
                        except Exception:
                            pass
                    registry.remove(rid)
                    _LOG.info("Robot '%s' retire (absent de library)", rid)

    def _auto_reconnect(self) -> None:
        """Reconnexion auto — un seul robot par port."""
        if self._simulation:
            return
        from xrv22.library.library_manager import library
        available = self._scan_ports()
        if not available:
            return
        reconnected = []
        used_ports: set = set()
        # Reconnecte chaque robot sur son port, mais pas deux sur le même
        for rcfg in library.list_robots():
            rid = self._try_reconnect_robot(rcfg, available, used_ports)
            if rid:
                reconnected.append(rid)
        if reconnected and hasattr(self, "_status_bar"):
            self._status_bar.set_message(f"Reconnecté : {', '.join(reconnected)}")

    def _try_reconnect_robot(self, rcfg, available: list,
                             used_ports: set) -> str:
        """Tente de reconnecter un robot. Un seul robot par port."""
        rid = rcfg.robot_id
        port = rcfg.port or ""
        baud = rcfg.baud
        if not rid or not port or port not in available:
            return ""
        if port in used_ports:
            _LOG.info("Port %s déjà utilisé, %s ignoré", port, rid)
            return ""
        ctrl = registry.get(rid)
        if ctrl is None or ctrl.is_connected:
            return ""
        if ctrl.connect(port, baud):
            used_ports.add(port)
            _LOG.info("Auto-reconnexion : %s sur %s", rid, port)
            return rid
        return ""

    def _scan_ports(self) -> list:
        """Retourne les ports série disponibles."""
        try:
            from serial.tools import list_ports
            return [p.device for p in list_ports.comports()]
        except ImportError:
            return []

    def _start_sim_scene(self) -> None:
        try:
            from xrv22.simulation.sim_scene import get_scene
            self._sim_scene = get_scene()
            self._sim_scene.start()
        except Exception as exc:
            _LOG.warning("SimScene non disponible : %s", exc)

    def _setup_bindings(self) -> None:
        """Raccourcis globaux via registre centralisé."""
        # Transport
        shortcuts.register("<space>", "Lecture / Pause", "Transport",
                           self._toggle_play)
        shortcuts.register("<Escape>", "STOP URGENCE", "Transport",
                           self._emergency_stop)
        # Projet
        shortcuts.register("<Control-s>", "Sauvegarder projet", "Projet",
                           self._save_project)
        shortcuts.register("<Control-q>", "Quitter", "Projet",
                           self._on_close)
        # Navigation
        shortcuts.register("<F1>", "Raccourcis clavier", "Aide",
                           lambda: show_shortcuts_dialog(self))
        # Onglets directs (Alt+1..8)
        shortcuts.register("<Alt-Key-1>", "Onglet Connexion", "Navigation",
                           lambda: self._notebook.select(0))
        shortcuts.register("<Alt-Key-2>", "Onglet Positions", "Navigation",
                           lambda: self._notebook.select(1))
        shortcuts.register("<Alt-Key-3>", "Onglet Timeline", "Navigation",
                           lambda: self._notebook.select(2))
        shortcuts.register("<Alt-Key-4>", "Onglet Capteurs", "Navigation",
                           lambda: self._notebook.select(3))
        shortcuts.register("<Alt-Key-5>", "Onglet Librairie", "Navigation",
                           lambda: self._notebook.select(4))
        shortcuts.register("<Alt-Key-6>", "Onglet Visu 3D", "Navigation",
                           lambda: self._notebook.select(5))
        # Undo / Redo
        shortcuts.register("<Control-z>", "Annuler", "Édition",
                           self._undo)
        shortcuts.register("<Control-Shift-z>", "Rétablir", "Édition",
                           self._redo)
        shortcuts.bind_all(self)

        # Navigation onglets Ctrl+Tab
        setup_tab_navigation(self, self._notebook)

    def _undo(self) -> None:
        from xrv22.core.undo_manager import undo_manager
        desc = undo_manager.undo()
        if desc:
            _LOG.info("Undo : %s", desc)

    def _redo(self) -> None:
        from xrv22.core.undo_manager import undo_manager
        desc = undo_manager.redo()
        if desc:
            _LOG.info("Redo : %s", desc)

    def _toggle_play(self) -> None:
        try:
            from xrv22.core.event_scheduler import SchedulerState
            if engine.state == SchedulerState.RUNNING:
                engine.pause()
            else:
                engine.play()
        except Exception as exc:
            _LOG.warning("Toggle play : %s", exc)

    def _emergency_stop(self) -> None:
        safety.emergency_stop()
        registry.emergency_stop_all()
        if hasattr(self, "_status_bar"):
            self._status_bar.flash_estop()
        _LOG.warning("STOP URGENCE déclenché")

    def _stop_soft(self) -> None:
        engine.stop()
        registry.soft_stop_all()

    def _save_project(self) -> None:
        try:
            from xrv22.services.project_service import project
            ok = project.save()
            if hasattr(self, "_status_bar"):
                self._status_bar.set_message("Projet sauvegardé" if ok else "Échec sauvegarde")
        except Exception as exc:
            _LOG.error("Sauvegarde : %s", exc)

    def _on_tab_changed(self, _event: Optional[tk.Event] = None) -> None:
        try:
            idx  = self._notebook.index("current")
            text = self._notebook.tab(idx, "text")
            if "Positions" in text and hasattr(self, "_positions_tab"):
                self._positions_tab.refresh()
        except Exception as exc:
            _LOG.debug("Tab changed : %s", exc)

    # ── Popup erreur hardware moteur ───────────────────────────────────────

    def _on_motor_hardware_error(self, payload: dict) -> None:
        """CC=2 — Recoit l'evenement motor.hardware_error et affiche le popup dans le thread UI."""
        self.after(0, lambda p=payload: self._show_motor_error_dialog(p))

    def _show_motor_error_dialog(self, payload: dict) -> None:
        """CC=7 — Popup indiquant quel moteur est en securite avec option reboot."""
        robot_id = payload.get("robot_id", "?")
        errors = payload.get("errors", {})
        if not errors:
            return
        # Eviter les popups en doublon
        if hasattr(self, "_hw_error_dialog_open") and self._hw_error_dialog_open:
            return
        self._hw_error_dialog_open = True

        dlg = tk.Toplevel(self)
        dlg.title("Moteur en securite")
        dlg.configure(bg=T.BG)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        # Icone alerte
        tk.Label(dlg, text="ALERTE MOTEUR", bg=T.BG, fg=T.C_ERR,
                 font=T.F_SECTION).pack(padx=30, pady=(20, 5))
        tk.Label(dlg, text=f"Robot : {robot_id}", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_LABEL).pack(padx=30, pady=(0, 10))

        # Detail par moteur
        detail_f = tk.Frame(dlg, bg=T.SURFACE, bd=1, relief="solid",
                            highlightbackground=T.C_ERR)
        detail_f.pack(fill="x", padx=20, pady=(0, 10))
        for mid, errs in errors.items():
            err_text = ", ".join(errs)
            row = tk.Frame(detail_f, bg=T.SURFACE)
            row.pack(fill="x", padx=10, pady=4)
            tk.Label(row, text=f"Moteur {mid} :", bg=T.SURFACE, fg=T.C_ERR,
                     font=T.F_CONTROL).pack(side="left")
            tk.Label(row, text=err_text, bg=T.SURFACE, fg=T.C_AMB,
                     font=T.F_MONO_SM).pack(side="left", padx=(8, 0))

        # Boutons
        btn_f = tk.Frame(dlg, bg=T.BG)
        btn_f.pack(fill="x", padx=20, pady=(5, 20))

        result_var = tk.StringVar(value="")

        def _reboot_all():
            result_var.set("reboot")
            dlg.destroy()

        def _dismiss():
            result_var.set("dismiss")
            dlg.destroy()

        tk.Button(btn_f, text="Reboot moteur(s) en erreur",
                  bg=T.C_ERR_DIM if hasattr(T, 'C_ERR_DIM') else T.SURFACE,
                  fg=T.C_ERR,
                  activebackground=T.SURFACE_HI, activeforeground=T.C_ERR,
                  font=T.F_LABEL, relief="flat", padx=12, pady=8,
                  command=_reboot_all).pack(side="left", padx=(0, 8))
        tk.Button(btn_f, text="Fermer",
                  bg=T.SURFACE, fg=T.TEXT_DIM,
                  activebackground=T.SURFACE_HI, activeforeground=T.TEXT_MED,
                  font=T.F_LABEL, relief="flat", padx=12, pady=8,
                  command=_dismiss).pack(side="right")

        self._center_dialog(dlg)
        dlg.wait_window()
        self._hw_error_dialog_open = False

    # ── Popup arret execution timeline ─────────────────────────────────────

    def _on_engine_error(self, payload: dict) -> None:
        """CC=2 — Marshal vers thread UI : un handler MOVE/WAIT a leve une exception."""
        self.after(0, lambda p=payload: self._show_engine_error_dialog(p))

    def _on_engine_zone_collision(self, payload: dict) -> None:
        """CC=2 — Marshal vers thread UI : MOVE bloque par zone exclusion."""
        self.after(0, lambda p=payload: self._show_engine_error_dialog({
            "event_type": "MOVE",
            "message": f"Collision zone exclusion '{payload.get('zone_name', '?')}' "
                       f"(robot {payload.get('robot_id', '?')})",
        }))

    def _show_engine_error_dialog(self, payload: dict) -> None:
        """CC=3 — Popup explicite sur arret de timeline en cours d'execution."""
        if getattr(self, "_engine_error_dialog_open", False):
            return
        self._engine_error_dialog_open = True
        evt_type = payload.get("event_type", "?")
        msg = payload.get("message", "Erreur inconnue")
        try:
            from tkinter import messagebox
            messagebox.showerror(
                "Execution interrompue",
                f"L'execution de la timeline a ete arretee.\n\n"
                f"Type d'evenement : {evt_type}\n"
                f"Cause : {msg}",
                parent=self)
        finally:
            self._engine_error_dialog_open = False

        if result_var.get() == "reboot":
            self._reboot_faulty_motors(robot_id, list(errors.keys()))

    def _reboot_faulty_motors(self, robot_id: str, motor_ids: list) -> None:
        """CC=4 — Reboot les moteurs en erreur et reactive le torque."""
        import threading

        def _bg_reboot():
            ctrl = registry.get(robot_id)
            if ctrl is None:
                return
            success = []
            for mid in motor_ids:
                if ctrl.reboot_motor(mid):
                    success.append(mid)
                    _LOG.info("Moteur %d reboot OK sur %s", mid, robot_id)
                else:
                    _LOG.error("Echec reboot moteur %d sur %s", mid, robot_id)
            if success:
                # Reactiver torque apres reboot
                ctrl.set_torque(True)
                _LOG.info("[%s] Torque reactive apres reboot de %s", robot_id, success)
                # Verifier qu'il n'y a plus d'erreurs
                remaining = ctrl.read_hardware_errors()
                if remaining:
                    _LOG.warning("[%s] Erreurs persistantes apres reboot : %s",
                                 robot_id, remaining)
                    bus.publish("motor.hardware_error", {
                        "robot_id": robot_id, "errors": remaining})

        threading.Thread(target=_bg_reboot, daemon=True).start()

    def _autosave_loop(self) -> None:
        """CC=2 — Sauvegarde automatique périodique du projet."""
        try:
            project.save()
            _LOG.debug("Auto-save effectué")
        except Exception as exc:
            _LOG.warning("Auto-save échoué : %s", exc)
        self.after(AUTOSAVE_INTERVAL_MS, self._autosave_loop)

    def _on_close(self) -> None:
        """Fermeture avec 3 choix : protocole, sans protocole, annuler."""
        self._save_project()
        connected = [c for c in registry.all() if c.is_connected]
        if connected:
            import tkinter as tk

            dlg = tk.Toplevel(self)
            dlg.title("Fermeture")
            dlg.transient(self)
            dlg.grab_set()
            dlg.resizable(False, False)
            dlg.configure(bg=T.BG)

            tk.Label(dlg, text="Des robots sont connectés.",
                     bg=T.BG, fg=T.TEXT, font=T.F_LABEL).pack(padx=30, pady=(20, 15))

            choice = tk.StringVar(value="cancel")

            def _pick(val: str) -> None:
                choice.set(val)
                dlg.destroy()

            btn_cfg = dict(font=T.F_LABEL, relief="flat", bd=0,
                           padx=15, pady=10, cursor="hand2", width=30,
                           bg=T.SURFACE, fg=T.TEXT_DIM,
                           activebackground=T.SURFACE_HI, activeforeground=T.TEXT_MED)

            tk.Button(dlg, text="OUI — Fermer + protocole",
                      command=lambda: _pick("protocol"), **btn_cfg).pack(
                      fill="x", padx=20, pady=4)
            tk.Button(dlg, text="Fermer sans protocole",
                      command=lambda: _pick("quick"), **btn_cfg).pack(
                      fill="x", padx=20, pady=4)
            tk.Button(dlg, text="Annuler",
                      command=lambda: _pick("cancel"), **btn_cfg).pack(
                      fill="x", padx=20, pady=(4, 20))

            dlg.update_idletasks()
            w, h = dlg.winfo_reqwidth(), dlg.winfo_reqheight()
            x = self.winfo_x() + (self.winfo_width() - w) // 2
            y = self.winfo_y() + (self.winfo_height() - h) // 2
            dlg.geometry(f"+{x}+{y}")

            dlg.wait_window()
            result = choice.get()

            if result == "protocol":
                self._shutdown_robots(connected)
            elif result == "quick":
                self._finalize_shutdown(connected)
            # else: cancel → ne rien faire
        else:
            self._finalize_close()

    def _shutdown_robots(self, controllers: list) -> None:
        """Séquence : safe_home → attente → lock → disconnect → close."""
        _LOG.info("Shutdown : retour home pour %d robot(s)", len(controllers))
        if hasattr(self, "_status_bar"):
            self._status_bar.set_message("Retour position initiale...")

        import threading
        def _bg_safe_home() -> None:
            for ctrl in controllers:
                ok, msg = ctrl.safe_home(duration_s=4.0)
                if not ok:
                    _LOG.warning("safe_home %s : %s", ctrl.robot_id, msg)
            self.after(500, lambda: self._finalize_shutdown(controllers))

        threading.Thread(target=_bg_safe_home, daemon=True).start()

    def _finalize_shutdown(self, controllers: list) -> None:
        """Torque off + disconnect tous les robots, puis ferme."""
        for ctrl in controllers:
            ctrl.set_torque(False)
        _LOG.info("Shutdown : torque off appliqué")

        for ctrl in controllers:
            ctrl.disconnect()
        _LOG.info("Shutdown : robots déconnectés")

        self._finalize_close()

    def _finalize_close(self) -> None:
        """Fermeture finale (Arduino, SimScene, destroy)."""
        try:
            from xrv22.hardware.arduino_bridge import arduino
            arduino.disconnect_all()
        except Exception as exc:
            _LOG.debug("Arduino disconnect : %s", exc)
        try:
            if hasattr(self, "_sim_scene"):
                self._sim_scene.stop()
        except Exception as exc:
            _LOG.debug("SimScene stop : %s", exc)
        _LOG.info("Fermeture de l'application")
        self.destroy()
