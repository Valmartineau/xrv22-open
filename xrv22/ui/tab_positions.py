"""
xrv22/ui/tab_positions.py
=========================
Onglet Positions & Suites — refactorisé pour XRV22.

Fonctionnalités :
  - Arbre Suites / Positions avec drag & drop
  - Enregistrement / édition / suppression de positions
  - Wizard de création de suite pas à pas
  - Panneau détail avec barres d'axes et couleurs
  - Règles couleur conditionnelles (stockées localement, pas migrées en V22)

Branchages V22 :
  - registry.get(rid)           → RobotController
  - ctrl.is_connected           → bool
  - ctrl.move(positions, dur)   → envoi commande
  - ctrl.lock() / unlock()
  - store.get_robot(rid)        → RobotSnapshot (positions)
  - library.list_positions()    → List[PositionModel]
  - library.save_position(pos)  → bool
  - library.delete_position(id) → (bool, str)
  - library.list_suites()       → List[SuiteModel]
  - library.save_suite(suite)   → bool
  - library.delete_suite(id)    → bool

CC max : 12
"""
from __future__ import annotations

import math
import threading
import time
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from typing import Optional, List, Dict, Any

from xrv22.theme import theme as T
from xrv22.ui.i18n import (
    POS_ENREGISTRER, POS_ALLER, POS_EDITER, POS_DUPLIQUER, POS_DEPLACER,
    POS_SUPPRIMER, POS_RAFRAICHIR, POS_NOUVELLE_SUITE, POS_NOUVEAU_DOSSIER,
    POS_WIZARD,
    POS_RENOMMER_SUITE, POS_DUPLIQUER_SUITE, POS_SUPPRIMER_SUITE,
    POS_RETIRER_ETAPE,
    POS_SANS_SUITE, POS_SUITE_PREFIX, POS_DETAIL_AUCUNE,
    WIZ_CAPTURER, WIZ_ANNULER_LAST, WIZ_ANNULER_TOUT, WIZ_ENREGISTRER,
    DLG_ANNULER, DLG_APPLIQUER, DLG_SAUVEGARDER, DLG_SUIVANT, DLG_DEPLACER,
    MSG_ROBOT_NON_CONNECTE, MSG_SUITE_EXISTE, MSG_NOM_EXISTE,
)
from xrv22.robots.robot_registry import registry
from xrv22.robots.robot_controller import calculate_auto_duration
from xrv22.core.state_store import store
from xrv22.library.library_manager import library
from xrv22.library.models import PositionModel, SuiteModel
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("XRV22.TabPositions")

from xrv22.config import MOTOR_IDS_DEFAULT as MOTOR_IDS, PINCE_AXIS, MOTOR_RANGE_MAX, MOTOR_CENTER

UNGROUPED_KEY = "__sans_suite__"
_DEFAULT_AXIS_NAMES = {
    1: "Base", 2: "Épaule", 3: "Coude",
    4: "Coude", 5: "Poignet", 6: "Rot. tête", 7: "Pince",
}

_DEFAULT_AXIS_HINTS = {
    1: ("Gauche", "Droite"),
    2: ("Lever", "Baisser"),
    3: ("Fermer", "Ouvrir"),
    4: ("Fermer", "Ouvrir"),
    5: ("Baisser", "Lever"),
    6: ("Horaire", "Anti-H"),
    7: ("Fermée", "Ouverte"),
}


def _get_axis_names() -> Dict[int, str]:
    """Retourne les noms d'axes (depuis hardware.json ou défaut)."""
    hw = library.get_hardware()
    custom = hw.get("axis_names", {})
    names = dict(_DEFAULT_AXIS_NAMES)
    for k, v in custom.items():
        names[int(k)] = v
    return names


def _get_axis_hints() -> Dict[int, tuple]:
    """Retourne les hints gauche/droite par axe (depuis hardware.json ou défaut)."""
    hw = library.get_hardware()
    custom = hw.get("axis_hints", {})
    hints = dict(_DEFAULT_AXIS_HINTS)
    for k, v in custom.items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            hints[int(k)] = (v[0], v[1])
    return hints


def _save_axis_name(mid: int, name: str) -> None:
    """Persiste un nom d'axe custom dans hardware.json."""
    hw = library.get_hardware()
    if "axis_names" not in hw:
        hw["axis_names"] = {}
    hw["axis_names"][str(mid)] = name
    library.save_hardware(hw)


def _save_axis_hint(mid: int, side: str, text: str) -> None:
    """Persiste un hint custom (side='left'|'right') dans hardware.json."""
    hw = library.get_hardware()
    if "axis_hints" not in hw:
        hw["axis_hints"] = {}
    current = hw["axis_hints"].get(str(mid), list(_DEFAULT_AXIS_HINTS.get(mid, ("", ""))))
    if side == "left":
        current[0] = text
    else:
        current[1] = text
    hw["axis_hints"][str(mid)] = current
    library.save_hardware(hw)


def _ticks_to_deg(ticks: int) -> float:
    """Convertit des ticks Dynamixel (0-4095) en degrés (0.0-360.0)."""
    return round(ticks * 360.0 / 4095.0, 1)


def _deg_to_ticks(deg: float) -> int:
    """Convertit des degrés (0.0-360.0) en ticks Dynamixel (0-4095)."""
    return max(0, min(4095, int(deg * 4095.0 / 360.0)))


# ── Pince : conversion ticks → cm (0 cm = fermée, 5 cm = ouverte) ──
_PINCE_CM_MAX = 5.0  # ouverture max en cm

def _ticks_to_cm(ticks: int, lo: int, hi: int) -> float:
    """Convertit des ticks pince en cm (lo=fermée=0cm, hi=ouverte=5cm)."""
    if hi <= lo:
        return 0.0
    ratio = max(0.0, min(1.0, (ticks - lo) / (hi - lo)))
    return round(ratio * _PINCE_CM_MAX, 1)


def _cm_to_ticks(cm: float, lo: int, hi: int) -> int:
    """Convertit des cm pince en ticks."""
    ratio = max(0.0, min(1.0, cm / _PINCE_CM_MAX))
    return max(lo, min(hi, int(lo + ratio * (hi - lo))))
_RULE_COLORS = [
    ("Vert",    "#2ecc71"), ("Rouge",  "#e74c3c"), ("Orange", "#e67e22"),
    ("Bleu",    "#3498db"), ("Violet", "#9b59b6"), ("Cyan",   "#1abc9c"),
    ("Rose",    "#e91e63"), ("Ambre",  "#f6a117"),
]

POSE_COLORS   = [
    ("Rouge",   "#e74c3c"), ("Orange", "#e67e22"), ("Jaune", "#f1c40f"),
    ("Vert",    "#2ecc71"), ("Bleu",   "#3498db"), ("Violet","#9b59b6"),
    ("Rose",    "#e91e63"), ("Cyan",   "#1abc9c"), ("Gris",  "#95a5a6"),
    ("Aucune",  ""),
]

# ── Helpers accès projet ──────────────────────────────────────────────────────

def _positions_dict() -> Dict[str, PositionModel]:
    """Retourne un dict {name: PositionModel} depuis la library."""
    return {p.name: p for p in library.list_positions()}


def _suites_dict() -> Dict[str, SuiteModel]:
    """Retourne un dict {name: SuiteModel} depuis la library."""
    return {s.name: s for s in library.list_suites()}


def _build_groups() -> Dict[str, list]:
    """Construit un dict {suite_name: [position_names]} depuis les suites.

    Les positions non référencées dans une suite vont dans UNGROUPED_KEY.
    """
    all_positions = _positions_dict()
    suites = library.list_suites()
    groups: Dict[str, list] = {}

    for suite in suites:
        pose_names = []
        for step in suite.steps:
            pname = step.get("position_name", "")
            if pname and pname in all_positions:
                pose_names.append(pname)
        groups[suite.name] = pose_names

    # Positions sans suite
    all_grouped = {p for lst in groups.values() for p in lst}
    ungrouped = [p for p in all_positions if p not in all_grouped]
    groups[UNGROUPED_KEY] = ungrouped

    return groups


def _get_suite_by_name(name: str) -> Optional[SuiteModel]:
    """Retourne une suite par nom."""
    for s in library.list_suites():
        if s.name == name:
            return s
    return None


def _rules() -> List[Dict[str, Any]]:
    """Retourne les règles conditionnelles de couleur (persistées dans la library)."""
    hw = library.get_hardware()
    return hw.get("color_rules", [])


def _save_rules(rules: list) -> None:
    """Sauvegarde les règles conditionnelles dans la library du projet."""
    hw = library.get_hardware()
    hw["color_rules"] = list(rules)
    library.save_hardware(hw)


def eval_first_rule(pose: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """CC=5 — Retourne la première règle satisfaite {label, color} ou None."""
    for rule in _rules():
        if not rule.get("enabled", True):
            continue
        axis = str(rule.get("axis", ""))
        val = pose.get(axis, pose.get(int(axis) if axis.isdigit() else 0, None))
        if val is None:
            continue
        try:
            val = int(val)
        except (ValueError, TypeError):
            continue
        if _rule_matches(rule, val):
            return {"label": rule.get("label", ""), "color": rule.get("color", "")}
    return None


def evaluate_rules(pose: Dict[str, Any]) -> List[Dict[str, str]]:
    """CC=4 — Retourne toutes les règles satisfaites."""
    results = []
    for rule in _rules():
        if not rule.get("enabled", True):
            continue
        axis = str(rule.get("axis", ""))
        val = pose.get(axis, pose.get(int(axis) if axis.isdigit() else 0, None))
        if val is None:
            continue
        try:
            val = int(val)
        except (ValueError, TypeError):
            continue
        if _rule_matches(rule, val):
            results.append({"label": rule.get("label", ""), "color": rule.get("color", "")})
    return results


def _rule_matches(rule: dict, val: int) -> bool:
    """CC=5 — Teste si une valeur satisfait une règle."""
    op = rule.get("op", ">=")
    threshold = int(rule.get("threshold", rule.get("value", 0)))
    if op == ">=":
        return val >= threshold
    if op == "<=":
        return val <= threshold
    if op == ">":
        return val > threshold
    if op == "<":
        return val < threshold
    if op == "==":
        return val == threshold
    return False


def _eval_pince(pose: Dict[str, Any]) -> tuple:
    """CC=4 — Évalue l'état de la pince (axe 7) via les règles conditionnelles.

    Retourne (label, color) de la première règle matchée sur l'axe 7,
    ou un label par défaut basé sur la valeur brute.
    """
    val = pose.get(str(PINCE_AXIS), pose.get(PINCE_AXIS))
    if val is None:
        return ("—", "")
    try:
        val = int(val)
    except (ValueError, TypeError):
        return ("—", "")
    # Chercher la première règle active portant sur l'axe 7
    for rule in _rules():
        if not rule.get("enabled", True):
            continue
        if str(rule.get("axis", "")) != str(PINCE_AXIS):
            continue
        if _rule_matches(rule, val):
            return (rule.get("label", f"{val}"), rule.get("color", ""))
    # Aucune règle : afficher la valeur brute
    return (str(val), "")


def _active_ctrl():
    """CC=2 — Retourne le contrôleur du robot actif (sélectionné)."""
    return registry.get(store.get_system().active_robot_id)


def _active_rid() -> str:
    return store.get_system().active_robot_id


# ── Classe principale ─────────────────────────────────────────────────────────

class PositionsTab(ttk.Frame):
    """CC=5 — Onglet Positions & Suites."""

    def __init__(self, parent: tk.Widget, on_after=None, active_robot_fn=None) -> None:  # noqa: ARG002
        super().__init__(parent, padding=10)
        self._dnd_item: Optional[str]  = None
        self._dnd_canvas: Optional[tk.Canvas] = None
        self._pos_axis_labels: Dict[int, tk.Label] = {}
        self._pos_axis_bars:   Dict[int, tk.Canvas] = {}
        self._ghost_live = True
        self._ghost_busy = False
        self._build()
        self._subscribe()
        self.after(300, self.refresh)
        self.after(500, self._ghost_live_loop)

    # ── Construction ─────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_toolbar()
        pane = ttk.PanedWindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(pane, width=340)
        pane.add(left, weight=1)
        right = ttk.Frame(pane)
        pane.add(right, weight=2)
        self._build_tree(left)
        self._build_detail(right)

    def _build_toolbar(self) -> None:
        """CC=2."""
        tb = ttk.Frame(self)
        tb.pack(fill="x", pady=(0, 6))
        btns = [
            (POS_ENREGISTRER,    self._save_current_pose),
            (POS_NOUVEAU_DOSSIER, self._add_folder),
            (POS_NOUVELLE_SUITE, self._add_suite),
            (POS_WIZARD,         self._suite_wizard),
            (POS_RAFRAICHIR,     self.refresh),
        ]
        for txt, cmd in btns:
            ttk.Button(tb, text=txt, command=cmd).pack(
                side="right", padx=3)

    def _build_tree(self, parent: tk.Widget) -> None:
        """CC=3 — Treeview + boutons action."""
        ttk.Label(parent, text="Suites et Positions",
                  font=T.F_SECTION).pack(anchor="w", pady=(0, 4))

        tree_f = ttk.Frame(parent)
        tree_f.pack(fill="both", expand=True)
        vsb = ttk.Scrollbar(tree_f, orient="vertical")
        vsb.pack(side="right", fill="y")

        # Treeview principal (arbre positions/suites)
        self._tree = ttk.Treeview(tree_f, show="tree headings",
                                   selectmode="extended")
        self._tree.heading("#0", text="Position")
        self._tree.column("#0", width=220, minwidth=140)
        self._tree.pack(side="left", fill="both", expand=True)

        # Treeview pince (colonne état pince — alignée avec l'arbre principal)
        self._pince_tree = ttk.Treeview(tree_f, columns=("pince",),
                                         show="tree headings",
                                         selectmode="none")
        self._pince_tree.heading("pince", text="Pince")
        self._pince_tree.column("pince", width=90, minwidth=60,
                                anchor="center", stretch=False)
        self._pince_tree.column("#0", width=0, minwidth=0, stretch=False)
        self._pince_tree.pack(side="left", fill="y")

        # Scrollbar synchronisée sur les deux arbres
        def _sync_scroll(*args):
            self._tree.yview(*args)
            self._pince_tree.yview(*args)
        vsb.config(command=_sync_scroll)

        def _on_tree_scroll(*args):
            vsb.set(*args)
            self._pince_tree.yview_moveto(args[0])
        def _on_pince_scroll(*args):
            vsb.set(*args)
            self._tree.yview_moveto(args[0])
        self._tree.config(yscrollcommand=_on_tree_scroll)
        self._pince_tree.config(yscrollcommand=_on_pince_scroll)

        # Sync molette souris
        def _on_mousewheel(event):
            delta = -1 if event.delta > 0 else 1
            self._tree.yview_scroll(delta, "units")
            self._pince_tree.yview_scroll(delta, "units")
            return "break"
        self._tree.bind("<MouseWheel>", _on_mousewheel)
        self._pince_tree.bind("<MouseWheel>", _on_mousewheel)

        # Sync open/close groupes entre les deux arbres
        def _on_tree_open(event):
            iid = self._tree.focus()
            if iid and iid.startswith("grp:"):
                pince_iid = "p" + iid  # pgrp:xxx
                try:
                    self._pince_tree.item(pince_iid, open=True)
                except tk.TclError:
                    pass

        def _on_tree_close(event):
            iid = self._tree.focus()
            if iid and iid.startswith("grp:"):
                pince_iid = "p" + iid
                try:
                    self._pince_tree.item(pince_iid, open=False)
                except tk.TclError:
                    pass

        self._tree.bind("<<TreeviewOpen>>",  _on_tree_open)
        self._tree.bind("<<TreeviewClose>>", _on_tree_close)

        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Double-1>",         self._on_double_click)
        self._tree.bind("<ButtonPress-1>",    self._dnd_start)
        self._tree.bind("<B1-Motion>",        self._dnd_motion)
        self._tree.bind("<ButtonRelease-1>",  self._dnd_drop)
        # Navigation clavier
        self._tree.bind("<Delete>",           lambda e: self._delete_selected())
        self._tree.bind("<BackSpace>",        lambda e: self._delete_selected())
        self._tree.bind("<Return>",           lambda e: self._goto_selected())

        # Boutons position
        pos_f = ttk.Frame(parent)
        pos_f.pack(fill="x", pady=(5, 0))
        for txt, cmd in [
            (POS_DUPLIQUER,      self._duplicate_selected),
            (POS_SUPPRIMER,      self._delete_selected),
        ]:
            ttk.Button(pos_f, text=txt, command=cmd).pack(
                side="left", padx=2)

        # Boutons suite
        suite_f = ttk.Frame(parent)
        suite_f.pack(fill="x", pady=(3, 0))
        for txt, cmd in [
            (POS_DUPLIQUER_SUITE, self._duplicate_suite),
            (POS_SUPPRIMER_SUITE, self._delete_suite),
        ]:
            ttk.Button(suite_f, text=txt, command=cmd).pack(
                side="left", padx=2)

    def _build_detail(self, parent: tk.Widget) -> None:
        """CC=3 — Panneau détail position — layout : bandeau → nom → manette → actions."""
        self._detail_parent = parent

        # ═══ 1. BANDEAU ROBOT (pleine largeur, couleur vive) ═══
        self._robot_bar = tk.Frame(parent, bg=T.SURFACE_HI, pady=8)
        self._robot_bar.pack(fill="x", padx=0, pady=(0, 0))
        self._robot_color_accent = tk.Frame(self._robot_bar, width=6, bg=T.C_AMB)
        self._robot_color_accent.pack(side="left", fill="y")
        bar_inner = tk.Frame(self._robot_bar, bg=T.SURFACE_HI, padx=12)
        bar_inner.pack(side="left", fill="x", expand=True)
        self._robot_bar_inner = bar_inner

        self._robot_selector_var = tk.StringVar(value=_active_rid() or "—")
        self._robot_btn = tk.Label(
            bar_inner, textvariable=self._robot_selector_var,
            bg=T.SURFACE, fg=T.C_AMB, font=(T.FONT_UI, 13, "bold"),
            highlightthickness=1, highlightbackground=T.TEXT_DIM,
            relief="flat", width=16, anchor="w", cursor="hand2",
            padx=6, pady=2)
        self._robot_btn.pack(side="left")
        self._robot_btn.bind("<Button-1>", lambda _: self._show_robot_popup())
        self._robot_arrow = tk.Label(bar_inner, text="▾", bg=T.SURFACE_HI,
                                      fg=T.C_AMB, font=(T.FONT_UI, 10),
                                      cursor="hand2")
        self._robot_arrow.pack(side="left", padx=(0, 10))
        self._robot_arrow.bind("<Button-1>", lambda _: self._show_robot_popup())
        self._robot_name_display = tk.Label(
            bar_inner, text="", bg=T.SURFACE_HI, fg=T.C_AMB,
            font=T.F_TITLE)
        self._robot_name_display.pack(side="left", padx=(0, 16))

        # Bouton Direct dans le bandeau robot
        self._detail_direct_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bar_inner, text="🎮 Direct", bg=T.SURFACE_HI,
                       fg=T.C_AMB, variable=self._detail_direct_var,
                       selectcolor=T.SURFACE, activebackground=T.SURFACE_HI,
                       activeforeground=T.C_AMB, font=T.F_CONTROL,
                       command=self._detail_toggle_direct).pack(side="left")
        self._detail_direct_warn = tk.Label(bar_inner, text="",
                                             bg=T.SURFACE_HI,
                                             fg=T.C_ERR, font=T.F_CAPTION)
        self._detail_direct_warn.pack(side="left", padx=4)

        # Bouton verrouillage assiette (compensation axes)
        self._assiette_var = tk.BooleanVar(value=False)
        self._assiette_target: float | None = None   # tangage cible (a2+a3+a5) rad
        self._assiette_roll: float | None = None      # roulis cible (a4) rad
        self._assiette_locked: List[int] = []          # axes verrouillés [4], [5], [4,5]
        self._assiette_btn = tk.Label(bar_inner, text="🔒 Assiette",
                                       bg=T.SURFACE, fg=T.C_INFO,
                                       font=T.F_CONTROL, padx=6, pady=1,
                                       cursor="hand2")
        self._assiette_btn.pack(side="left", padx=(8, 0))
        self._assiette_btn.bind("<Button-1>", lambda _: self._show_assiette_menu())
        self._assiette_lbl = tk.Label(bar_inner, text="",
                                       bg=T.SURFACE_HI, fg=T.C_INFO,
                                       font=T.F_CAPTION)
        self._assiette_lbl.pack(side="left", padx=4)

        self._update_robot_bar_color()

        # ═══ 2. NOM POSITION + CHEMIN ═══
        hdr = tk.Frame(parent, bg=T.BG)
        hdr.pack(fill="x", padx=12, pady=(8, 2))
        self._detail_name = tk.Label(hdr, text=POS_DETAIL_AUCUNE,
                                      bg=T.BG, fg=T.TEXT,
                                      font=T.F_SECTION)
        self._detail_name.pack(side="left")
        self._path_label = tk.Label(parent, text="—", bg=T.BG,
                                     fg=T.TEXT_DIM, font=T.F_CAPTION)
        self._path_label.pack(anchor="w", padx=14, pady=(0, 4))

        # Badges règles (résultat évaluation)
        self._rules_badges_frame = ttk.Frame(parent)
        self._rules_badges_frame.pack(fill="x", padx=10, pady=(0, 2))

        # ═══ 3. SLIDERS / MANETTE (zone principale) ═══
        self._detail_slider_data: Dict[int, dict] = {}
        self._detail_slider_vars: Dict[int, tk.IntVar] = {}
        self._detail_slider_updating = False
        self._detail_selected_pose: Optional[str] = None
        # Throttle mode direct : max 1 commande / 150ms, delta max 80 ticks/cmd
        self._direct_throttle_id: Optional[str] = None
        self._direct_pending: Optional[tuple] = None  # (motor_id, pos)
        self._direct_last_sent: Dict[int, int] = {}   # dernière pos envoyée par axe
        _DIRECT_INTERVAL_MS = 150
        _DIRECT_MAX_DELTA = 80
        self._DIRECT_INTERVAL_MS = _DIRECT_INTERVAL_MS
        self._DIRECT_MAX_DELTA = _DIRECT_MAX_DELTA

        self._detail_sliders_outer = tk.Frame(parent, bg=T.BG)
        self._detail_sliders_outer.pack(fill="both", expand=True,
                                         padx=8, pady=(0, 2))
        self._detail_sliders_frame = tk.Frame(self._detail_sliders_outer,
                                               bg=T.SURFACE)
        self._detail_sliders_frame.pack(fill="both", expand=True,
                                         padx=4, pady=2)
        self._build_detail_sliders()

        # ═══ 4. BARRE ACTIONS (Lire / Go / Enregistrer) ═══
        action_bar = tk.Frame(parent, bg=T.BG)
        action_bar.pack(fill="x", padx=10, pady=(2, 4))
        ttk.Button(action_bar, text="📍 Lire",
                   command=self._detail_read_hw).pack(side="left", padx=2)
        ttk.Button(action_bar, text="🎯 Go",
                   command=self._detail_goto_sliders).pack(side="left", padx=2)
        save_btn = tk.Label(action_bar, text="  💾  Enregistrer  ", bg=T.C_MAG,
                            fg=T.TEXT, font=T.F_CONTROL, cursor="hand2",
                            padx=10, pady=4)
        save_btn.pack(side="right", padx=(8, 0))
        save_btn.bind("<Button-1>", lambda e: self._detail_save_pose())
        save_btn.bind("<Enter>", lambda e: save_btn.config(bg=T.C_MAG_2))
        save_btn.bind("<Leave>", lambda e: save_btn.config(bg=T.C_MAG))

        # ═══ 5. RÈGLES CONDITIONNELLES (collapsible, en bas) ═══
        self._rules_collapsed = True
        self._rules_header = tk.Frame(parent, bg=T.BORDER_MED, cursor="hand2")
        self._rules_header.pack(fill="x", padx=10, pady=(2, 2))
        self._rules_toggle_lbl = tk.Label(
            self._rules_header,
            text="▶  Règles couleurs",
            bg=T.BORDER_MED, fg=T.TEXT_MED, font=T.F_CAPTION,
            anchor="w", padx=8, pady=4)
        self._rules_toggle_lbl.pack(fill="x")
        self._rules_header.bind("<Button-1>", self._on_rules_click)
        self._rules_toggle_lbl.bind("<Button-1>", self._on_rules_click)

        self._rules_body = ttk.Frame(parent)
        self._build_rules_panel(self._rules_body)

    # ── Arbre : refresh ───────────────────────────────────────────────────────

    def refresh(self) -> None:
        """CC=7 — Reconstruit l'arbre principal + arbre pince synchronisé."""
        if not hasattr(self, "_tree"):
            return
        positions = _positions_dict()
        groups = _build_groups()

        # Vider les deux arbres
        for item in self._tree.get_children():
            self._tree.delete(item)
        for item in self._pince_tree.get_children():
            self._pince_tree.delete(item)

        # Tags visuels pour dossiers et suites
        self._tree.tag_configure("folder", foreground=T.C_AMB_2)
        self._tree.tag_configure("group", foreground=T.TEXT_MED)

        # Séparer dossiers, suites rattachées, suites libres
        all_suites = library.list_suites()
        folders = {s.name: s for s in all_suites if s.meta.get("is_folder")}
        child_of = {}  # suite_name → folder_name
        for s in all_suites:
            pf = s.meta.get("parent_folder", "")
            if pf and pf in folders:
                child_of[s.name] = pf

        # Ordre d'affichage : dossiers (avec leurs suites enfants), suites libres, sans suite
        def _insert_grp(grp: str, parent_iid: str = "",
                        pparent: str = "") -> None:
            suite = _get_suite_by_name(grp)
            is_folder = suite and suite.meta.get("is_folder", False)
            if grp == UNGROUPED_KEY:
                disp, grp_tag = POS_SANS_SUITE, "group"
            elif is_folder:
                disp, grp_tag = f"📁 {grp}", "folder"
            else:
                disp, grp_tag = f"▶ {grp}", "group"
            self._tree.insert(parent_iid, "end", iid=f"grp:{grp}",
                              text=disp, open=True, tags=(grp_tag,))
            self._pince_tree.insert(pparent, "end", iid=f"pgrp:{grp}",
                                     text="", open=True)

        sorted_keys = sorted(groups.keys(), key=lambda x: (x == UNGROUPED_KEY, x))

        def _insert_positions(grp: str) -> None:
            """Insère les positions d'un groupe sous grp:{grp}."""
            for pname in groups.get(grp, []):
                color = self._get_color(pname)
                tag   = f"pc_{color.lstrip('#')}" if color else "nocolor"
                dot   = "⬤ " if color else "  ● "
                pos_model = positions.get(pname)
                pose_dict = self._pos_model_to_str_dict(pos_model) if pos_model else {}
                rule_suffix = self._rule_suffix(pose_dict)

                # Arbre principal (nom position avec sa couleur)
                self._tree.insert(f"grp:{grp}", "end",
                                  iid=f"pose:{pname}",
                                  text=f"{dot}{pname}{rule_suffix}",
                                  tags=(tag,))
                if color:
                    try:
                        self._tree.tag_configure(tag, foreground=color)
                    except Exception:
                        pass

                # Arbre pince (état pince avec sa propre couleur)
                pince_label, pince_color = _eval_pince(pose_dict)
                pince_display = f"● {pince_label}" if pince_color else pince_label
                pince_tag = f"pnc_{pince_color.lstrip('#')}" if pince_color else "pnc_def"
                self._pince_tree.insert(
                    f"pgrp:{grp}", "end", iid=f"pp:{pname}",
                    values=(pince_display,), tags=(pince_tag,))
                if pince_color:
                    try:
                        self._pince_tree.tag_configure(
                            pince_tag, foreground=pince_color)
                    except Exception:
                        pass

        # ── Boucle principale : insertion groupes + positions ──
        for grp in sorted_keys:
            if grp in child_of:
                continue  # sera inséré sous son dossier parent
            if grp in folders:
                _insert_grp(grp)
                _insert_positions(grp)
                for child_name in sorted_keys:
                    if child_of.get(child_name) == grp:
                        _insert_grp(child_name, f"grp:{grp}", f"pgrp:{grp}")
                        _insert_positions(child_name)
            else:
                _insert_grp(grp)
                _insert_positions(grp)

    @staticmethod
    def _pos_model_to_str_dict(pos: PositionModel) -> Dict[str, int]:
        """Convertit les positions d'un PositionModel en dict {str(motor_id): value}."""
        return {str(k): v for k, v in pos.positions.items()}

    # ── Sélection / détail ───────────────────────────────────────────────────

    def _on_select(self, _event: Optional[tk.Event] = None) -> None:
        """CC=5 — Sélection tree → affiche détail de la pose."""
        sel = self._tree.selection()
        if not sel:
            return
        iid = self._resolve_pose_iid(sel)
        if not iid:
            return
        pname = iid[5:]
        n_poses = sum(1 for i in sel if i.startswith("pose:"))
        if n_poses > 1:
            self._detail_name.config(
                text=f"{pname}  (+{n_poses-1} sélectionnée(s))")
        self._show_detail(pname)

    def _resolve_pose_iid(self, sel: tuple) -> Optional[str]:
        """CC=5 — Résout l'iid de pose prioritaire dans la sélection."""
        focused = self._tree.focus()
        iid = focused if (focused and focused in sel) else sel[-1]
        if iid.startswith("pose:"):
            return iid
        poses_in_sel = [i for i in sel if i.startswith("pose:")]
        return poses_in_sel[-1] if poses_in_sel else None

    def _on_double_click(self, event: Optional[tk.Event] = None) -> None:
        """CC=4 — Double-clic : édition in-place du nom (position ou suite)."""
        if event is None:
            return
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        if iid.startswith("pose:"):
            self._inline_rename_position(iid)
        elif iid.startswith("grp:"):
            grp = iid[4:]
            if grp != UNGROUPED_KEY:
                self._inline_rename_suite(iid)

    def _inline_rename_position(self, iid: str) -> None:
        """CC=7 — Édition in-place du nom d'une position dans le Treeview."""
        pname = iid[5:]
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return

        bbox = self._tree.bbox(iid, "#0")
        if not bbox:
            return
        x, y, w, h = bbox

        entry = tk.Entry(self._tree, font=T.F_CONTROL, bg=T.BG,
                         fg=T.C_AMB, insertbackground=T.C_AMB,
                         highlightbackground=T.C_AMB, highlightthickness=1)
        # Retirer le préfixe d'icône éventuel
        current_text = self._tree.item(iid, "text")
        # Extraire le nom brut (après les icônes/espaces)
        entry.insert(0, pname)
        entry.select_range(0, tk.END)
        entry.place(x=x + 20, y=y, width=w - 20, height=h)
        entry.focus_set()

        def _commit(_e=None):
            new_name = entry.get().strip()
            entry.destroy()
            if not new_name or new_name == pname:
                return
            if library.get_position_by_name(new_name):
                messagebox.showwarning("Renommer", MSG_NOM_EXISTE)
                return
            old_id = pos_model.id
            pos_model.name = new_name
            library.save_position(pos_model)
            # Mettre à jour les références dans les suites
            for suite in library.list_suites():
                changed = False
                for step in suite.steps:
                    if step.get("position_id") == old_id or step.get("position_name") == pname:
                        step["position_name"] = new_name
                        changed = True
                if changed:
                    library.save_suite(suite)
            self.refresh()
            try:
                self._tree.selection_set(f"pose:{new_name}")
                self._tree.see(f"pose:{new_name}")
            except tk.TclError:
                pass
            self._show_detail(new_name)
            _LOG.info("Position renommée : '%s' → '%s'", pname, new_name)

        def _cancel(_e=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<Tab>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", _cancel)

    def _inline_rename_suite(self, iid: str) -> None:
        """CC=6 — Édition in-place du nom d'une suite dans le Treeview."""
        grp = iid[4:]
        suite = _get_suite_by_name(grp)
        if not suite:
            return

        bbox = self._tree.bbox(iid, "#0")
        if not bbox:
            return
        x, y, w, h = bbox

        entry = tk.Entry(self._tree, font=T.F_CONTROL, bg=T.BG,
                         fg=T.C_AMB, insertbackground=T.C_AMB,
                         highlightbackground=T.C_AMB, highlightthickness=1)
        entry.insert(0, grp)
        entry.select_range(0, tk.END)
        entry.place(x=x + 20, y=y, width=w - 20, height=h)
        entry.focus_set()

        def _commit(_e=None):
            new_name = entry.get().strip()
            entry.destroy()
            if not new_name or new_name == grp:
                return
            if _get_suite_by_name(new_name):
                messagebox.showwarning("Renommer", MSG_NOM_EXISTE)
                return
            suite.name = new_name
            library.save_suite(suite)
            self.refresh()
            try:
                self._tree.selection_set(f"grp:{new_name}")
                self._tree.see(f"grp:{new_name}")
            except tk.TclError:
                pass
            _LOG.info("Suite renommée : '%s' → '%s'", grp, new_name)

        def _cancel(_e=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<Tab>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", _cancel)

    # ── Sliders détail — construction & helpers ────────────────────────────

    _DT_TRACK_H  = 32
    _DT_TRACK_PAD = 8
    _DT_SLIDER_R = 10

    _HIDDEN_AXES = {3}  # axes masqués dans le panneau détail

    def _update_robot_bar_color(self) -> None:
        """CC=2 — Met à jour la couleur du bandeau robot (vif, identifiable)."""
        rid = self._robot_selector_var.get()
        if rid and rid != "—":
            color = registry.color_for(rid)
        else:
            color = T.C_AMB
        rt = T.robot_theme(color)
        # Bandeau : fond teinté vif, accent plein, texte couleur robot
        self._robot_color_accent.config(bg=color)
        bar_bg = rt["bg_vif"]
        self._robot_bar.config(bg=bar_bg)
        if hasattr(self, "_robot_bar_inner"):
            self._robot_bar_inner.config(bg=bar_bg)
        self._robot_name_display.config(fg=color, bg=bar_bg)
        # Bouton sélecteur + flèche
        if hasattr(self, "_robot_btn"):
            self._robot_btn.config(fg=color, bg=rt["bg_med"],
                                    highlightbackground=rt["border"])
        if hasattr(self, "_robot_arrow"):
            self._robot_arrow.config(fg=color, bg=bar_bg)
        if hasattr(self, "_detail_direct_warn"):
            self._detail_direct_warn.config(bg=bar_bg)
        # Teinter le fond du frame sliders
        if hasattr(self, "_detail_sliders_frame"):
            self._detail_sliders_frame.config(bg=rt["bg"])
        # Nom du robot
        from xrv22.library.library_manager import library as lib
        rcfg = lib.get_robot(rid)
        name = rcfg.name if rcfg and rcfg.name else rid
        self._robot_name_display.config(text=name)

    def _show_robot_popup(self) -> None:
        """Affiche un menu popup coloré pour choisir le robot actif."""
        menu = tk.Menu(self.winfo_toplevel(), tearoff=0,
                       bg=T.SURFACE, fg=T.TEXT,
                       activebackground=T.C_MAG_DIM2, activeforeground=T.C_AMB,
                       font=(T.FONT_UI, 11))
        for rid in sorted(registry.ids()):
            color = registry.color_for(rid)
            from xrv22.library.library_manager import library as lib
            rcfg = lib.get_robot(rid)
            lbl = f"{rcfg.name}  ({rid})" if rcfg and rcfg.name else rid
            menu.add_command(
                label=lbl, foreground=color,
                command=lambda r=rid: self._on_robot_selector_changed(r))
        x = self._robot_btn.winfo_rootx()
        y = self._robot_btn.winfo_rooty() + self._robot_btn.winfo_height()
        menu.tk_popup(x, y)

    def _on_robot_selector_changed(self, rid: str = None) -> None:
        """CC=2 — Change le robot actif depuis le sélecteur popup."""
        if rid is None:
            rid = self._robot_selector_var.get()
        if rid and rid != "—" and registry.get(rid):
            self._robot_selector_var.set(rid)
            registry.set_master(rid)
            self._update_robot_bar_color()
            self._build_detail_sliders()
            bus.publish("ui.active_robot_changed", {"robot_id": rid})

    def _build_detail_sliders(self) -> None:
        """CC=4 — Construit les sliders — blocs vifs par axe, curseur sombre."""
        # Nettoyer les traces Tcl avant de détruire les vars
        for var in self._detail_slider_vars.values():
            for tid in var.trace_info():
                try:
                    var.trace_remove(tid[0], tid[1])
                except Exception:
                    pass
        for w in self._detail_sliders_frame.winfo_children():
            w.destroy()
        self._detail_slider_vars.clear()
        self._detail_slider_data.clear()

        ctrl = _active_ctrl()
        profile = ctrl.profile if ctrl else None

        # Couleur du robot actif
        rid = _active_rid()
        robot_clr = registry.color_for(rid) if rid else T.C_AMB
        rt = T.robot_theme(robot_clr)
        frame_bg = rt["bg"]
        self._detail_sliders_frame.config(bg=frame_bg)
        self._update_robot_bar_color()

        for mid in MOTOR_IDS:
            if mid in self._HIDDEN_AXES:
                continue
            lo, hi = (0, 4095)
            if profile:
                lo, hi = profile.soft_limits.get(mid, (0, 4095))

            # ── Bloc visuel par axe (fond coloré vif, bordure arrondie) ──
            block_bg = rt["bg_med"]
            block = tk.Frame(self._detail_sliders_frame, bg=block_bg,
                             highlightbackground=rt["border"],
                             highlightthickness=1, padx=6, pady=2)
            block.pack(fill="both", expand=True, padx=6, pady=1)

            var = tk.IntVar(value=2048)
            self._detail_slider_vars[mid] = var

            cvs_h = 28 if mid == PINCE_AXIS else 20
            cvs = tk.Canvas(block, height=cvs_h, bg=block_bg,
                            highlightthickness=0, bd=0)

            cd = {
                "canvas": cvs, "motor_id": mid,
                "lo": lo, "hi": hi, "pos": 2048, "dragging": None,
            }
            self._detail_slider_data[mid] = cd

            # Ligne 1 : nom d'axe + valeur humaine + ticks
            info_row = tk.Frame(block, bg=block_bg)
            info_row.pack(fill="x", pady=(0, 1))

            aname = _get_axis_names().get(mid, f"A{mid}")
            name_lbl = tk.Label(info_row, text=aname, bg=block_bg,
                                fg=robot_clr, font=(T.FONT_UI, 12, "bold"),
                                anchor="w", cursor="hand2")
            name_lbl.pack(side="left")
            cd["name_lbl"] = name_lbl
            name_lbl.bind("<Double-1>",
                          lambda e, m=mid, l=name_lbl: self._edit_axis_name(m, l))

            is_pince = (mid == PINCE_AXIS)
            if is_pince:
                init_text = f"{_ticks_to_cm(2048, lo, hi):.1f} cm"
            else:
                init_text = f"{_ticks_to_deg(2048):.1f}°"
            hint_fg = T.blend_color("#ffffff", block_bg, 0.45)
            val_lbl = tk.Label(info_row, text=init_text, bg=block_bg,
                               fg=hint_fg, font=T.F_MONO_MD, anchor="e",
                               cursor="hand2")
            val_lbl.pack(side="right")
            cd["val_lbl"] = val_lbl
            cd["is_pince"] = is_pince
            val_lbl.bind("<Double-1>",
                         lambda e, d=cd, v=var: self._edit_axis_value(d, v))

            ticks_lbl = tk.Label(info_row, text="2048", bg=block_bg,
                                 fg=hint_fg, font=T.F_CAPTION, anchor="e")
            ticks_lbl.pack(side="right", padx=(0, 10))
            cd["ticks_lbl"] = ticks_lbl

            # Ligne 2 : canvas slider
            cvs.pack(fill="both", expand=True)

            # Ligne 3 : hints gauche / droite sous le slider (éditables)
            hints = _get_axis_hints().get(mid, ("", ""))
            hint_row = tk.Frame(block, bg=block_bg)
            hint_row.pack(fill="x", pady=(0, 0))
            hint_color = "#ffffff60" if T.BG.startswith("#") else T.TEXT_MED
            # Approximation : Tkinter ne supporte pas l'alpha, on blend manuellement
            hint_fg = T.blend_color("#ffffff", block_bg, 0.45)
            lbl_left = tk.Label(hint_row, text=hints[0] or "…", bg=block_bg,
                                fg=hint_fg, font=(T.FONT_UI, 9),
                                anchor="w", cursor="hand2")
            lbl_left.pack(side="left")
            lbl_left.bind("<Button-1>",
                          lambda e, m=mid, lbl=lbl_left: self._edit_hint(m, "left", lbl))
            lbl_right = tk.Label(hint_row, text=hints[1] or "…", bg=block_bg,
                                 fg=hint_fg, font=(T.FONT_UI, 9),
                                 anchor="e", cursor="hand2")
            lbl_right.pack(side="right")
            lbl_right.bind("<Button-1>",
                           lambda e, m=mid, lbl=lbl_right: self._edit_hint(m, "right", lbl))

            cvs.bind("<Configure>", lambda e, d=cd: self._dt_draw(d))
            cvs.bind("<Button-1>", lambda e, d=cd: self._dt_press(e, d))
            cvs.bind("<B1-Motion>", lambda e, d=cd: self._dt_drag(e, d))
            cvs.bind("<ButtonRelease-1>",
                     lambda e, d=cd: self._dt_release(e, d))

            def _update_val(d=cd, v=var):
                ticks = v.get()
                if d["is_pince"]:
                    cm = _ticks_to_cm(ticks, d["lo"], d["hi"])
                    d["val_lbl"].config(text=f"{cm:.1f} cm")
                else:
                    d["val_lbl"].config(text=f"{_ticks_to_deg(ticks):.1f}°")
                d["ticks_lbl"].config(text=str(ticks))

            var.trace_add("write",
                          lambda *_, d=cd, v=var: (self._dt_var_changed(d, v),
                                                    _update_val(d, v)))

    def _edit_axis_value(self, cd: dict, var: tk.IntVar) -> None:
        """Édition clavier de la valeur d'un axe (degrés ou cm)."""
        lbl = cd["val_lbl"]
        is_pince = cd.get("is_pince", False)
        ticks = var.get()

        if is_pince:
            current = f"{_ticks_to_cm(ticks, cd['lo'], cd['hi']):.1f}"
            suffix = " cm"
            lo_val, hi_val = 0.0, _PINCE_CM_MAX
            inc = 0.1
        else:
            current = f"{_ticks_to_deg(ticks):.1f}"
            suffix = "°"
            lo_val = _ticks_to_deg(cd["lo"])
            hi_val = _ticks_to_deg(cd["hi"])
            inc = 0.5

        entry = tk.Spinbox(lbl.master, from_=lo_val, to=hi_val,
                           increment=inc, width=7,
                           font=T.F_MONO_SM, bg=T.BG, fg=T.TEXT,
                           buttonbackground=T.SURFACE)
        entry.delete(0, tk.END)
        entry.insert(0, current)
        entry.selection_range(0, tk.END)
        entry.place(x=lbl.winfo_x(), y=lbl.winfo_y(),
                    width=lbl.winfo_width() + 20,
                    height=lbl.winfo_height())
        entry.focus_set()

        def _commit(_e=None):
            try:
                val = float(entry.get().replace(",", "."))
            except ValueError:
                entry.destroy()
                return
            entry.destroy()
            if is_pince:
                new_ticks = _cm_to_ticks(val, cd["lo"], cd["hi"])
            else:
                new_ticks = _deg_to_ticks(val)
            new_ticks = max(cd["lo"], min(cd["hi"], new_ticks))
            var.set(new_ticks)
            cd["pos"] = new_ticks
            self._dt_draw(cd, pos_only=True)
            if self._detail_direct_var.get():
                self._detail_direct_write(cd["motor_id"], new_ticks)

        def _cancel(_e=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<Tab>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", _cancel)

    def _edit_axis_name(self, mid: int, lbl: tk.Label) -> None:
        """Édition in-place du nom d'un axe par double-clic."""
        current = lbl.cget("text")
        # Créer un Entry par-dessus le label
        entry = tk.Entry(lbl.master, font=T.F_MONO_SM, bg=T.BG,
                         fg=T.TEXT, insertbackground=T.C_AMB, width=9)
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.place(x=lbl.winfo_x(), y=lbl.winfo_y(),
                    width=lbl.winfo_width(), height=lbl.winfo_height())
        entry.focus_set()

        def _commit(_e=None):
            new_name = entry.get().strip()
            entry.destroy()
            if new_name and new_name != current:
                lbl.config(text=new_name)
                _save_axis_name(mid, new_name)
                _LOG.info("Axe %d renommé : '%s' → '%s'", mid, current, new_name)

        def _cancel(_e=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<Tab>", _commit)
        entry.bind("<FocusOut>", _commit)
        entry.bind("<Escape>", _cancel)

    def _dt_pos_to_x(self, cd: dict, pos: int) -> int:
        w = cd["canvas"].winfo_width()
        pad = self._DT_TRACK_PAD
        usable = w - 2 * pad
        if usable <= 0:
            return pad
        lo, hi = cd["lo"], cd["hi"]
        if hi <= lo:
            return pad
        ratio = max(0.0, min(1.0, (pos - lo) / (hi - lo)))
        return int(pad + ratio * usable)

    def _dt_x_to_pos(self, cd: dict, x: int) -> int:
        w = cd["canvas"].winfo_width()
        pad = self._DT_TRACK_PAD
        usable = w - 2 * pad
        if usable <= 0:
            return cd["lo"]
        ratio = max(0.0, min(1.0, (x - pad) / usable))
        return int(cd["lo"] + ratio * (cd["hi"] - cd["lo"]))

    def _dt_draw(self, cd: dict, pos_only: bool = False) -> None:
        cvs = cd["canvas"]
        w = cvs.winfo_width()
        h = cd.get("canvas").winfo_height() or self._DT_TRACK_H
        pad = self._DT_TRACK_PAD
        if w < 20:
            return
        mid_y = h // 2
        r = self._DT_SLIDER_R
        x_pos = self._dt_pos_to_x(cd, cd["pos"])

        if pos_only and cvs.find_withtag("pos"):
            cvs.coords("pos", x_pos - r, mid_y - r, x_pos + r, mid_y + r)
            gp = cd.get("ghost_pos")
            if gp is not None and cvs.find_withtag("ghost"):
                gx = self._dt_pos_to_x(cd, gp)
                gr = r - 2
                cvs.coords("ghost", gx - gr, mid_y - gr, gx + gr, mid_y + gr)
            return

        cvs.delete("all")
        x_lo = pad
        x_hi = w - pad
        # Couleur piste : robot actif, bande vive
        _rclr = registry.color_for(_active_rid()) if _active_rid() else T.C_AMB
        rt = T.robot_theme(_rclr)
        # Piste : bande colorée épaisse (4px)
        cvs.create_rectangle(x_lo, mid_y - 3, x_hi, mid_y + 3,
                             fill=rt["bg_vif"], outline="")
        # Marqueur centre
        x_mid = (x_lo + x_hi) // 2
        cvs.create_line(x_mid, mid_y - 5, x_mid, mid_y + 5,
                        fill=T.TEXT_DIM, width=1)
        # Graduations pour la pince (chaque mm de 0 à 50 mm = 5 cm)
        if cd.get("is_pince"):
            track_w = x_hi - x_lo
            total_mm = int(_PINCE_CM_MAX * 10)  # 50 mm
            for mm in range(1, total_mm + 1):
                ratio = mm / total_mm
                gx = x_lo + int(ratio * track_w)
                is_cm = mm % 10 == 0       # 10, 20, 30, 40, 50
                is_half = mm % 5 == 0      # 5, 15, 25, 35, 45
                if is_cm:
                    tick_h, tick_w, color = 10, 2, "#ffffff"
                elif is_half:
                    tick_h, tick_w, color = 6, 1, T.TEXT_MED
                else:
                    tick_h, tick_w, color = 3, 1, T.TEXT_DIM
                cvs.create_line(gx, mid_y + 3, gx, mid_y + 3 + tick_h,
                                fill=color, width=tick_w)
                if is_cm:
                    cvs.create_text(gx, mid_y + 16, text=str(mm // 10),
                                    fill="#ffffff",
                                    font=(T.FONT_MONO, 10, "bold"),
                                    anchor="center")
            # Indicateur "cm" à droite
            cvs.create_text(x_hi + 4, mid_y + 16, text="cm",
                            fill=T.TEXT_MED, font=(T.FONT_MONO, 9),
                            anchor="w")
        # Curseur fantôme (position live hardware — gris, non cliquable)
        gp = cd.get("ghost_pos")
        if gp is not None:
            gx = self._dt_pos_to_x(cd, gp)
            gr = r - 1
            cvs.create_oval(gx - gr, mid_y - gr, gx + gr, mid_y + gr,
                            fill=T.TEXT_DIM, outline=T.BORDER_HI, width=1,
                            tags="ghost")
        # Curseur position (sombre sur piste vive — plus gros, contrasté)
        cvs.create_oval(x_pos - r, mid_y - r, x_pos + r, mid_y + r,
                        fill="#1a1a2e", outline=_rclr, width=2, tags="pos")

    def _dt_press(self, event, cd):
        cd["dragging"] = "pos"
        self._dt_move_to(cd, event.x)

    def _dt_drag(self, event, cd):
        if cd.get("dragging"):
            self._dt_move_to(cd, event.x)

    def _dt_release(self, event, cd):
        cd["dragging"] = None

    def _edit_hint(self, motor_id: int, side: str, lbl: tk.Label) -> None:
        """Édition inline d'un hint (gauche ou droite)."""
        old_text = lbl.cget("text")
        if old_text == "…":
            old_text = ""
        bg = lbl.cget("bg")
        fg = lbl.cget("fg")
        entry = tk.Entry(lbl.master, bg=bg, fg="#ffffff",
                         insertbackground="#ffffff",
                         font=(T.FONT_UI, 9), width=10,
                         relief="flat", highlightthickness=1,
                         highlightcolor=T.C_AMB)
        entry.insert(0, old_text)
        entry.select_range(0, "end")
        if side == "left":
            entry.place(x=lbl.winfo_x(), y=lbl.winfo_y(),
                        width=lbl.winfo_width() + 30, height=lbl.winfo_height())
        else:
            entry.place(x=lbl.winfo_x() - 30, y=lbl.winfo_y(),
                        width=lbl.winfo_width() + 30, height=lbl.winfo_height())
        entry.focus_set()

        def _commit(_event=None):
            new_text = entry.get().strip()
            entry.destroy()
            lbl.config(text=new_text or "…")
            _save_axis_hint(motor_id, side, new_text)

        def _cancel(_event=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<Escape>", _cancel)
        entry.bind("<FocusOut>", _commit)

    def _dt_move_to(self, cd: dict, x: int) -> None:
        pos = self._dt_x_to_pos(cd, x)
        pos = max(cd["lo"], min(cd["hi"], pos))
        cd["pos"] = pos
        mid = cd["motor_id"]
        if not self._detail_slider_updating:
            self._detail_slider_updating = True
            self._detail_slider_vars[mid].set(pos)
            self._detail_slider_updating = False
        self._dt_draw(cd, pos_only=True)
        # Compensation assiette sur slider aussi (même sans mode direct)
        if self._assiette_locked and mid in (1, 2, 3):
            self._compute_assiette_compensation()
        if self._detail_direct_var.get():
            self._direct_request(mid, pos)

    def _dt_var_changed(self, cd: dict, var: tk.IntVar) -> None:
        if self._detail_slider_updating:
            return
        try:
            cd["pos"] = var.get()
            self._dt_draw(cd, pos_only=True)
            # Compensation assiette
            if self._assiette_locked and cd.get("motor_id") in (1, 2, 3):
                self._compute_assiette_compensation()
        except tk.TclError:
            pass

    def _detail_toggle_direct(self) -> None:
        if self._detail_direct_var.get():
            ctrl = _active_ctrl()
            if not ctrl or not ctrl.is_connected:
                self._detail_direct_var.set(False)
                messagebox.showwarning("Direct", MSG_ROBOT_NON_CONNECTE)
                return
            if not messagebox.askyesno(
                    "Contrôle Direct",
                    "Chaque mouvement de slider sera envoyé\n"
                    "IMMÉDIATEMENT au robot.\n\nActiver ?"):
                self._detail_direct_var.set(False)
                return
            self._detail_direct_warn.config(
                text="⚠️ Direct actif")
            # Sync depuis hardware + reset throttle
            self._detail_read_hw_silent()
            self._direct_last_sent.clear()
            self._direct_pending = None
            _LOG.warning("Détail : mode direct ACTIVÉ")
        else:
            self._detail_direct_warn.config(text="")
            _LOG.info("Détail : mode direct désactivé")

    def _direct_request(self, motor_id: int, pos: int) -> None:
        """Enregistre une demande et programme l'envoi throttlé."""
        self._direct_pending = (motor_id, pos)
        if self._direct_throttle_id is None:
            self._direct_flush()

    def _direct_flush(self) -> None:
        """Envoie la commande pendante avec clamp de delta max."""
        self._direct_throttle_id = None
        if self._direct_pending is None:
            return
        motor_id, target = self._direct_pending
        self._direct_pending = None

        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            return

        # Clamp : pas plus de _DIRECT_MAX_DELTA ticks par commande
        final_target = target
        last = self._direct_last_sent.get(motor_id)
        if last is not None:
            delta = target - last
            if abs(delta) > self._DIRECT_MAX_DELTA:
                target = last + (self._DIRECT_MAX_DELTA if delta > 0
                                 else -self._DIRECT_MAX_DELTA)
                # Re-programmer pour continuer vers la cible finale
                self._direct_pending = (motor_id, final_target)

        # Positions depuis le store (pas de lecture série)
        rid = _active_rid()
        snap = store.get_robot(rid) if rid else None
        current = dict(snap.positions) if snap and snap.positions else {}

        # Compensation assiette
        if self._assiette_locked and motor_id in (1, 2, 3):
            comp = self._compute_assiette_compensation()
            if comp:
                cmd = {motor_id: target}
                cmd.update({k: v for k, v in comp.items() if k != motor_id})
                dur = max(0.25, calculate_auto_duration(cmd, current))
                try:
                    ctrl.move(cmd, dur)
                    self._direct_last_sent[motor_id] = target
                except Exception as exc:
                    _LOG.error("Direct write erreur : %s", exc)
                self._direct_schedule_next()
                return

        cmd = {motor_id: target}
        dur = max(0.25, calculate_auto_duration(cmd, current))
        try:
            ctrl.move(cmd, dur)
            self._direct_last_sent[motor_id] = target
        except Exception as exc:
            _LOG.error("Direct write erreur : %s", exc)
        self._direct_schedule_next()

    def _direct_schedule_next(self) -> None:
        """Programme le prochain flush si une commande est en attente."""
        if self._direct_pending is not None:
            self._direct_throttle_id = self.after(
                self._DIRECT_INTERVAL_MS, self._direct_flush)

    def _detail_direct_write(self, motor_id: int, pos: int) -> None:
        """Compat — redirige vers le système throttlé."""
        self._direct_request(motor_id, pos)

    # ── Verrouillage assiette (compensation axe 5) ──────────────

    def _tick_to_rad(self, tick: int) -> float:
        return math.radians((tick - 2048) * 300.0 / 4096.0)

    def _rad_to_tick(self, rad: float) -> int:
        deg = math.degrees(rad)
        tick = int(2048 + deg * 4096.0 / 300.0)
        return max(0, min(4095, tick))

    def _show_assiette_menu(self) -> None:
        """Affiche le menu de sélection d'assiette avec choix d'axes."""
        from xrv22.library.models import AssettePreset
        menu = tk.Menu(self, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)

        # ── Sous-menu : Axe 5 — Tangage (a2+a3+a5) ──
        m5 = tk.Menu(menu, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)
        m5.add_command(label="▼  Vers le bas (180°)",
                       command=lambda: self._set_assiette(180.0, 0.0, [5]))
        m5.add_command(label="►  Horizontal (90°)",
                       command=lambda: self._set_assiette(90.0, 0.0, [5]))
        m5.add_command(label="▲  Vers le haut (0°)",
                       command=lambda: self._set_assiette(0.0, 0.0, [5]))
        m5.add_command(label="◢  Incliné (135°)",
                       command=lambda: self._set_assiette(135.0, 0.0, [5]))
        m5.add_command(label="🎯  Angle actuel",
                       command=lambda: self._lock_current_assiette([5]))
        m5.add_command(label="✏️  Personnalisé…",
                       command=lambda: self._ask_custom_assiette([5]))
        menu.add_cascade(label="Axe 5 — Tangage (orientation outil)", menu=m5)

        # ── Sous-menu : Axe 4 — Roulis ──
        m4 = tk.Menu(menu, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)
        m4.add_command(label="Neutre (0°)",
                       command=lambda: self._set_assiette(0.0, 0.0, [4]))
        m4.add_command(label="🎯  Angle actuel",
                       command=lambda: self._lock_current_assiette([4]))
        m4.add_command(label="✏️  Personnalisé…",
                       command=lambda: self._ask_custom_assiette([4]))
        menu.add_cascade(label="Axe 4 — Roulis (rotation outil)", menu=m4)

        # ── Sous-menu : Axes 4+5 — Les deux ──
        m45 = tk.Menu(menu, tearoff=0, bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL)
        m45.add_command(label="▼  Bas + Neutre (180° / 0°)",
                        command=lambda: self._set_assiette(180.0, 0.0, [4, 5]))
        m45.add_command(label="►  Horizontal + Neutre (90° / 0°)",
                        command=lambda: self._set_assiette(90.0, 0.0, [4, 5]))
        m45.add_command(label="🎯  Angles actuels",
                        command=lambda: self._lock_current_assiette([4, 5]))
        menu.add_cascade(label="Axes 4+5 — Tangage + Roulis", menu=m45)

        menu.add_separator()

        # ── Presets sauvegardés ──
        presets = library.list_assiettes()
        if presets:
            for p in sorted(presets, key=lambda x: x.name):
                axes_txt = "+".join(str(a) for a in p.locked_axes)
                lbl = f"⭐ {p.name} (ax{axes_txt}"
                if 5 in p.locked_axes:
                    lbl += f" tang={p.angle_deg:.0f}°"
                if 4 in p.locked_axes:
                    lbl += f" roul={p.roll_deg:.0f}°"
                lbl += ")"
                menu.add_command(
                    label=lbl,
                    command=lambda pr=p: self._set_assiette(
                        pr.angle_deg, pr.roll_deg, pr.locked_axes))
            menu.add_separator()

        menu.add_command(label="💾  Sauvegarder l'assiette actuelle…",
                         command=self._save_current_assiette)
        if presets:
            del_menu = tk.Menu(menu, tearoff=0, bg=T.SURFACE, fg=T.TEXT,
                               font=T.F_CONTROL)
            for p in sorted(presets, key=lambda x: x.name):
                del_menu.add_command(
                    label=f"❌ {p.name}",
                    command=lambda pid=p.id: self._delete_assiette(pid))
            menu.add_cascade(label="🗑  Supprimer un preset…", menu=del_menu)

        menu.add_separator()
        if self._assiette_locked:
            menu.add_command(label="🔓  Déverrouiller",
                             command=self._unlock_assiette)

        try:
            menu.tk_popup(self._assiette_btn.winfo_rootx(),
                          self._assiette_btn.winfo_rooty() + 25)
        finally:
            menu.grab_release()

    def _set_assiette(self, angle_deg: float, roll_deg: float,
                       locked: List[int]) -> None:
        """Verrouille l'assiette sur les axes sélectionnés."""
        self._assiette_locked = list(locked)
        self._assiette_var.set(True)
        if 5 in locked:
            self._assiette_target = math.radians(angle_deg)
        else:
            self._assiette_target = None
        if 4 in locked:
            self._assiette_roll = math.radians(roll_deg)
        else:
            self._assiette_roll = None
        # Label descriptif
        parts = []
        if 5 in locked:
            parts.append(f"T{angle_deg:.0f}°")
        if 4 in locked:
            parts.append(f"R{roll_deg:.0f}°")
        self._assiette_lbl.config(text=f"({' '.join(parts)})")
        self._assiette_btn.config(bg=T.C_INFO, fg="#000000")
        self._compute_assiette_compensation()
        axes_txt = "+".join(str(a) for a in locked)
        _LOG.info("Assiette verrouillée axes %s : tang=%.0f° roul=%.0f°",
                  axes_txt, angle_deg, roll_deg)

    def _lock_current_assiette(self, locked: List[int]) -> None:
        """Verrouille sur les angles courants."""
        a2 = self._tick_to_rad(self._detail_slider_vars.get(2, tk.IntVar(value=2048)).get())
        a3 = self._tick_to_rad(self._detail_slider_vars.get(3, tk.IntVar(value=2048)).get())
        a4 = self._tick_to_rad(self._detail_slider_vars.get(4, tk.IntVar(value=2048)).get())
        a5 = self._tick_to_rad(self._detail_slider_vars.get(5, tk.IntVar(value=2048)).get())
        angle_deg = math.degrees(a2 + a3 + a5)
        roll_deg = math.degrees(a4)
        self._set_assiette(angle_deg, roll_deg, locked)

    def _ask_custom_assiette(self, locked: List[int]) -> None:
        """Demande un/des angle(s) personnalisé(s)."""
        angle_deg = 180.0
        roll_deg = 0.0
        if 5 in locked:
            val = simpledialog.askfloat("Tangage (axe 5)",
                                         "Angle outil (°) :\n"
                                         "180° = vers le bas\n"
                                         "90° = horizontal\n"
                                         "0° = vers le haut",
                                         initialvalue=180.0,
                                         minvalue=-180.0, maxvalue=360.0,
                                         parent=self)
            if val is None:
                return
            angle_deg = val
        if 4 in locked:
            val = simpledialog.askfloat("Roulis (axe 4)",
                                         "Angle roulis (°) :\n"
                                         "0° = neutre",
                                         initialvalue=0.0,
                                         minvalue=-180.0, maxvalue=180.0,
                                         parent=self)
            if val is None:
                return
            roll_deg = val
        self._set_assiette(angle_deg, roll_deg, locked)

    def _unlock_assiette(self) -> None:
        """Déverrouille l'assiette."""
        self._assiette_target = None
        self._assiette_roll = None
        self._assiette_locked.clear()
        self._assiette_var.set(False)
        self._assiette_lbl.config(text="")
        self._assiette_btn.config(bg=T.SURFACE, fg=T.C_INFO)
        _LOG.info("Assiette déverrouillée")

    def _save_current_assiette(self) -> None:
        """Sauvegarde l'assiette actuelle comme preset."""
        from xrv22.library.models import AssettePreset
        if not self._assiette_locked:
            messagebox.showinfo("Assiette",
                                "Aucune assiette active.\n"
                                "Verrouille d'abord une assiette.",
                                parent=self)
            return
        angle_deg = math.degrees(self._assiette_target) if self._assiette_target else 0.0
        roll_deg = math.degrees(self._assiette_roll) if self._assiette_roll else 0.0
        axes_txt = "+".join(str(a) for a in self._assiette_locked)
        name = simpledialog.askstring("Sauvegarder assiette",
                                       f"Nom du preset (axes {axes_txt}) :",
                                       parent=self)
        if not name:
            return
        preset = AssettePreset(
            name=name,
            angle_deg=round(angle_deg, 1),
            roll_deg=round(roll_deg, 1),
            locked_axes=list(self._assiette_locked),
        )
        library.save_assiette(preset)
        _LOG.info("Preset assiette sauvegardé : '%s' axes %s", name, axes_txt)

    def _delete_assiette(self, preset_id: str) -> None:
        """Supprime un preset d'assiette."""
        library.delete_assiette(preset_id)
        _LOG.info("Preset assiette supprimé : %s", preset_id)

    def _compute_assiette_compensation(self) -> dict | None:
        """Recalcule les axes verrouillés pour maintenir l'assiette."""
        if not self._assiette_locked:
            return None
        result = {}
        limit = math.radians(150)

        # Compensation tangage (axe 5)
        if 5 in self._assiette_locked and self._assiette_target is not None:
            a2 = self._tick_to_rad(self._detail_slider_vars.get(2, tk.IntVar(value=2048)).get())
            a3 = self._tick_to_rad(self._detail_slider_vars.get(3, tk.IntVar(value=2048)).get())
            a5_needed = self._assiette_target - a2 - a3
            if abs(a5_needed) <= limit:
                tick5 = self._rad_to_tick(a5_needed)
                result[5] = tick5
                self._update_slider_visual(5, tick5)

        # Compensation roulis (axe 4)
        if 4 in self._assiette_locked and self._assiette_roll is not None:
            tick4 = self._rad_to_tick(self._assiette_roll)
            result[4] = tick4
            self._update_slider_visual(4, tick4)

        return result if result else None

    def _update_slider_visual(self, mid: int, tick: int) -> None:
        """Met à jour un slider visuellement sans déclencher de boucle."""
        if mid in self._detail_slider_vars:
            self._detail_slider_updating = True
            self._detail_slider_vars[mid].set(tick)
            self._detail_slider_updating = False
            if mid in self._detail_slider_data:
                self._detail_slider_data[mid]["pos"] = tick
                self._dt_draw(self._detail_slider_data[mid], pos_only=True)

    def _detail_read_hw(self) -> None:
        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            messagebox.showwarning("Lire", MSG_ROBOT_NON_CONNECTE)
            return
        positions = ctrl.read_positions()
        if positions:
            self._detail_apply_positions(positions)

    def _detail_read_hw_silent(self) -> None:
        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            return
        positions = ctrl.read_positions()
        if positions:
            self._detail_apply_positions(positions)

    def _detail_apply_positions(self, positions: dict) -> None:
        self._detail_slider_updating = True
        for mid, var in self._detail_slider_vars.items():
            val = int(positions.get(mid, var.get()))
            var.set(val)
            if mid in self._detail_slider_data:
                self._detail_slider_data[mid]["pos"] = val
                self._dt_draw(self._detail_slider_data[mid], pos_only=True)
        self._detail_slider_updating = False

    # ── Curseurs fantômes (position live hardware) ──────────────

    def _ghost_live_loop(self) -> None:
        """CC=4 — Boucle périodique : lit les positions hardware en thread bg
        et met à jour les fantômes. Skip si un read est déjà en cours
        (évite blocage UI quand plusieurs robots sont sur le même bus USB)."""
        if not self._ghost_live:
            return
        ctrl = _active_ctrl()
        if ctrl and ctrl.is_connected and not self._ghost_busy:
            self._ghost_busy = True

            def _bg_read() -> None:
                try:
                    positions = ctrl.read_positions()
                    if positions:
                        self.after(0, lambda: self._update_ghosts(positions))
                except Exception:
                    pass
                finally:
                    self._ghost_busy = False

            threading.Thread(target=_bg_read, daemon=True).start()
        self.after(200, self._ghost_live_loop)

    def _update_ghosts(self, positions: dict) -> None:
        """CC=3 — Repositionne les curseurs fantômes sur chaque slider."""
        for mid, cd in self._detail_slider_data.items():
            val = int(positions.get(mid, cd.get("ghost_pos", cd["pos"])))
            cd["ghost_pos"] = val
            cvs = cd["canvas"]
            r = self._DT_SLIDER_R - 1
            h = cvs.winfo_height() or self._DT_TRACK_H
            mid_y = h // 2
            gx = self._dt_pos_to_x(cd, val)
            if cvs.find_withtag("ghost"):
                cvs.coords("ghost", gx - r, mid_y - r, gx + r, mid_y + r)
            else:
                cvs.create_oval(gx - r, mid_y - r, gx + r, mid_y + r,
                                fill=T.TEXT_DIM, outline=T.BORDER_HI,
                                width=1, tags="ghost")
                # Le fantôme doit être sous le curseur principal
                if cvs.find_withtag("pos"):
                    cvs.tag_raise("pos", "ghost")

    def _detail_goto_sliders(self) -> None:
        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            messagebox.showwarning("Go", MSG_ROBOT_NON_CONNECTE)
            return
        targets = {mid: var.get()
                   for mid, var in self._detail_slider_vars.items()}
        current = ctrl.read_positions()
        duration = calculate_auto_duration(targets, current, speed_ratio=0.5)
        ctrl.move(targets, duration)
        _LOG.info("Détail Go sliders (durée auto: %.2fs)", duration)

    def _detail_save_pose(self) -> None:
        """Enregistre les valeurs des sliders dans la position sélectionnée."""
        pname = self._detail_selected_pose
        if not pname:
            messagebox.showwarning("Sauvegarder",
                                   "Sélectionnez une position d'abord.")
            return
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return
        pos_model.positions = {mid: var.get()
                               for mid, var in self._detail_slider_vars.items()}
        library.save_position(pos_model)
        self.refresh()
        _LOG.info("Position '%s' mise à jour depuis sliders détail", pname)

    # ── Affichage détail ─────────────────────────────────────────────────────

    def _show_detail(self, pname: str) -> None:
        """CC=5 — Remplit le panneau détail avec sliders."""
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return
        pose = self._pos_model_to_str_dict(pos_model)
        color = self._get_color(pname)
        group = self._get_group(pname)

        self._detail_name.config(text=pname)
        self._detail_selected_pose = pname
        if group == UNGROUPED_KEY:
            path_text = f"📂 Sans suite  ›  {pname}"
        else:
            path_text = f"📁 {group}  ›  {pname}"
        self._path_label.config(text=path_text)

        # Mettre à jour les sliders avec les valeurs de la position
        self._detail_slider_updating = True
        for mid, var in self._detail_slider_vars.items():
            val = int(pose.get(str(mid), 2048))
            var.set(val)
            if mid in self._detail_slider_data:
                self._detail_slider_data[mid]["pos"] = val
                self._dt_draw(self._detail_slider_data[mid])
        self._detail_slider_updating = False

        self._refresh_rule_badges(pose)

    # ── Règles conditionnelles (panneau inline V17) ────────────────────────

    @staticmethod
    def _rule_suffix(pose: dict) -> str:
        """CC=2 — Suffixe textuel de la première règle matchée pour le treeview."""
        m = eval_first_rule(pose)
        return f"  [{m['label']}]" if m else ""

    def _refresh_rule_badges(self, pose: dict) -> None:
        """CC=3 — Affiche les badges des règles satisfaites."""
        for w in self._rules_badges_frame.winfo_children():
            w.destroy()
        matches = evaluate_rules(pose)
        if not matches:
            return
        for m in matches:
            color = m["color"] or T.C_AMB
            badge = tk.Label(self._rules_badges_frame,
                             text=f"  {m['label']}  ",
                             bg=color, fg="white",
                             font=T.F_CONTROL, padx=6, pady=2)
            badge.pack(side="left", padx=2, pady=2)

    def _on_rules_click(self, event) -> str:
        """CC=1 — Handler clic avec break pour éviter double-propagation."""
        self._toggle_rules_panel()
        return "break"

    def _toggle_rules_panel(self) -> None:
        """CC=2 — Ouvre/ferme le panneau de règles (hauteur dynamique)."""
        self._rules_collapsed = not self._rules_collapsed
        if self._rules_collapsed:
            self._rules_body.pack_forget()
            self._rules_toggle_lbl.config(text="▶  Règles couleurs")
        else:
            self._rules_body.pack(fill="x", padx=10, pady=(0, 4),
                                  after=self._rules_header)
            self._rules_toggle_lbl.config(text="▼  Règles couleurs")
            self._refresh_rules_tree()
            # Hauteur dynamique : ajuster le treeview au nombre de règles
            n_rules = len(self._rules_tree.get_children())
            self._rules_tree.config(height=max(1, min(n_rules + 1, 6)))
        # Forcer le recalcul de géométrie du parent
        self._detail_parent.update_idletasks()

    def _build_rules_panel(self, parent: tk.Widget) -> None:
        """CC=2 — Construit le treeview + boutons des règles inline."""
        cols = ("en", "axe", "op", "seuil", "couleur", "label")
        self._rules_tree = ttk.Treeview(
            parent, columns=cols, show="headings",
            selectmode="browse", height=5)
        self._rules_tree.heading("en",      text="✓",   anchor="center")
        self._rules_tree.heading("axe",     text="Axe",  anchor="center")
        self._rules_tree.heading("op",      text="Op",   anchor="center")
        self._rules_tree.heading("seuil",   text="Seuil", anchor="center")
        self._rules_tree.heading("couleur", text="Couleur", anchor="center")
        self._rules_tree.heading("label",   text="Description")
        self._rules_tree.column("en",      width=30,  minwidth=28,  stretch=False)
        self._rules_tree.column("axe",     width=40,  minwidth=35,  stretch=False)
        self._rules_tree.column("op",      width=40,  minwidth=35,  stretch=False)
        self._rules_tree.column("seuil",   width=55,  minwidth=45,  stretch=False)
        self._rules_tree.column("couleur", width=70,  minwidth=60,  stretch=False)
        self._rules_tree.column("label",   width=160, minwidth=100)
        self._rules_tree.pack(fill="x", pady=(4, 0))
        self._rules_tree.bind("<Double-1>", self._rules_cell_edit)

        # Boutons
        brow = ttk.Frame(parent)
        brow.pack(fill="x", pady=(4, 2))
        def _edit_selected_rule():
            sel = self._rules_tree.selection()
            if sel:
                self._rules_edit_dialog(int(sel[0]))

        for txt, cmd in [
            ("➕ Ajouter",   self._rules_add),
            ("✏ Éditer",     _edit_selected_rule),
            ("⬤/☐ Activer", self._rules_toggle_enabled),
            ("🗑",          self._rules_delete),
            ("⬆",           lambda: self._rules_move(-1)),
            ("⬇",           lambda: self._rules_move(1)),
        ]:
            ttk.Button(brow, text=txt, command=cmd).pack(side="left", padx=2)
        ttk.Label(brow, text="  Double-clic pour modifier",
                  font=T.F_CAPTION, foreground=T.TEXT_DIM).pack(side="left", padx=8)

    def _refresh_rules_tree(self) -> None:
        """CC=3 — Rafraîchit le treeview des règles."""
        tree = self._rules_tree
        tree.delete(*tree.get_children())
        for i, r in enumerate(_rules()):
            en = "✅" if r.get("enabled", True) else "☐"
            color = r.get("color", "")
            tree.insert("", "end", iid=str(i), values=(
                en,
                r.get("axis", "7"),
                r.get("op", ">="),
                r.get("threshold", r.get("value", 0)),
                color,
                r.get("label", ""),
            ))
            if color:
                tag = f"rc_{color.lstrip('#')}"
                tree.tag_configure(tag, foreground=color)
                tree.item(str(i), tags=(tag,))

    def _rules_add(self) -> None:
        """CC=2 — Ajoute une règle par défaut."""
        rules = _rules()
        rules.append({
            "enabled": True, "axis": 7, "op": ">=",
            "threshold": 2048, "color": "#2ecc71",
            "label": "Pince ouverte",
        })
        _save_rules(rules)
        self._refresh_rules_tree()
        self.refresh()

    def _rules_toggle_enabled(self) -> None:
        """CC=3 — Active/désactive la règle sélectionnée."""
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        rules = _rules()
        if 0 <= idx < len(rules):
            rules[idx]["enabled"] = not rules[idx].get("enabled", True)
            _save_rules(rules)
            self._refresh_rules_tree()
            self.refresh()

    def _rules_delete(self) -> None:
        """CC=3 — Supprime la règle sélectionnée."""
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        rules = _rules()
        if 0 <= idx < len(rules):
            rules.pop(idx)
            _save_rules(rules)
            self._refresh_rules_tree()
            self.refresh()

    def _rules_move(self, direction: int) -> None:
        """CC=4 — Monte/descend la règle sélectionnée."""
        sel = self._rules_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        rules = _rules()
        new_idx = idx + direction
        if not (0 <= new_idx < len(rules)):
            return
        rules[idx], rules[new_idx] = rules[new_idx], rules[idx]
        _save_rules(rules)
        self._refresh_rules_tree()
        self._rules_tree.selection_set(str(new_idx))
        self.refresh()

    def _rules_cell_edit(self, event: tk.Event) -> None:
        """CC=2 — Double-clic sur une règle → ouvre le dialogue d'édition complet."""
        item = self._rules_tree.identify_row(event.y)
        if not item:
            return
        self._rules_edit_dialog(int(item))

    def _rules_edit_dialog(self, idx: int) -> None:
        """CC=7 — Dialogue d'édition complet d'une règle conditionnelle."""
        rules = _rules()
        if idx < 0 or idx >= len(rules):
            return
        rule = rules[idx]

        dlg = tk.Toplevel(self)
        dlg.title(f"Éditer règle #{idx + 1}")
        dlg.geometry("420x360")
        dlg.configure(bg=T.BG)
        dlg.transient(self); dlg.resizable(False, False)

        # ── En-tête ──
        tk.Label(dlg, text="Règle de couleur conditionnelle", bg=T.BG,
                 fg=T.TEXT, font=T.F_SECTION).pack(anchor="w", padx=14, pady=(12, 4))

        form = tk.Frame(dlg, bg=T.BG, padx=14, pady=4)
        form.pack(fill="x")

        # ── Activée ──
        enabled_var = tk.BooleanVar(value=rule.get("enabled", True))
        tk.Checkbutton(form, text="Règle activée", variable=enabled_var,
                       bg=T.BG, fg=T.TEXT, selectcolor=T.SURFACE,
                       activebackground=T.BG, font=T.F_CONTROL
                       ).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)

        # ── Axe ──
        tk.Label(form, text="Axe :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).grid(row=1, column=0, sticky="w", pady=4)
        axis_var = tk.IntVar(value=int(rule.get("axis", 7)))
        axis_names = _get_axis_names()
        axis_frame = tk.Frame(form, bg=T.BG)
        axis_frame.grid(row=1, column=1, sticky="w", pady=4)
        tk.Spinbox(axis_frame, textvariable=axis_var, from_=1, to=7, width=3,
                   bg=T.SURFACE, fg=T.TEXT, font=T.F_MONO_SM,
                   buttonbackground=T.SURFACE).pack(side="left")
        axis_name_lbl = tk.Label(axis_frame, text="", bg=T.BG, fg=T.C_AMB,
                                 font=T.F_CAPTION)
        axis_name_lbl.pack(side="left", padx=6)

        def _update_axis_name(*_args):
            n = axis_names.get(axis_var.get(), "")
            axis_name_lbl.config(text=f"({n})" if n else "")
        axis_var.trace_add("write", _update_axis_name)
        _update_axis_name()

        # ── Opérateur ──
        tk.Label(form, text="Condition :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).grid(row=2, column=0, sticky="w", pady=4)
        op_var = tk.StringVar(value=rule.get("op", ">="))
        cond_frame = tk.Frame(form, bg=T.BG)
        cond_frame.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Combobox(cond_frame, textvariable=op_var,
                     values=[">", ">=", "<", "<=", "=="],
                     state="readonly", width=4).pack(side="left")

        # ── Seuil ──
        tk.Label(cond_frame, text="  Seuil :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).pack(side="left")
        threshold_var = tk.IntVar(value=int(rule.get("threshold",
                                                      rule.get("value", 2048))))
        tk.Spinbox(cond_frame, textvariable=threshold_var, from_=0, to=4095,
                   increment=50, width=6, bg=T.SURFACE, fg=T.TEXT,
                   font=T.F_MONO_SM, buttonbackground=T.SURFACE
                   ).pack(side="left", padx=4)

        # ── Résumé condition ──
        cond_summary = tk.Label(form, text="", bg=T.BG, fg=T.TEXT_DIM,
                                font=T.F_CAPTION)
        cond_summary.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))

        def _update_summary(*_args):
            ax = axis_var.get()
            aname = axis_names.get(ax, f"Axe {ax}")
            cond_summary.config(
                text=f"→ Si {aname} (axe {ax}) {op_var.get()} {threshold_var.get()}")
        op_var.trace_add("write", _update_summary)
        threshold_var.trace_add("write", _update_summary)
        axis_var.trace_add("write", _update_summary)
        _update_summary()

        # ── Description / Label ──
        tk.Label(form, text="Description :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).grid(row=4, column=0, sticky="nw", pady=4)
        label_entry = tk.Entry(form, font=T.F_CONTROL, bg=T.SURFACE,
                               fg=T.TEXT, width=28,
                               insertbackground=T.C_AMB)
        label_entry.grid(row=4, column=1, sticky="w", pady=4)
        label_entry.insert(0, rule.get("label", ""))
        label_entry.select_range(0, tk.END)

        tk.Label(form, text="Ex : Pince ouverte, Pince fermée, Bras levé…",
                 bg=T.BG, fg=T.TEXT_DIM, font=T.F_CAPTION
                 ).grid(row=5, column=0, columnspan=2, sticky="w")

        # ── Couleur ──
        tk.Label(form, text="Couleur :", bg=T.BG, fg=T.TEXT_MED,
                 font=T.F_CONTROL).grid(row=6, column=0, sticky="w", pady=(8, 4))
        color_frame = tk.Frame(form, bg=T.BG)
        color_frame.grid(row=6, column=1, sticky="w", pady=(8, 4))
        color_var = tk.StringVar(value=rule.get("color", "#2ecc71"))
        color_preview = tk.Label(color_frame, text="  ⬤  ", bg=T.BG,
                                 fg=color_var.get(), font=("", 16))
        color_preview.pack(side="left")
        color_name_lbl = tk.Label(color_frame, text="", bg=T.BG,
                                  fg=T.TEXT_MED, font=T.F_CONTROL)
        color_name_lbl.pack(side="left", padx=4)

        def _update_color_preview(*_args):
            c = color_var.get()
            color_preview.config(fg=c if c else T.TEXT_DIM)
            # Trouver le nom de la couleur
            for cname, chex in _RULE_COLORS:
                if chex == c:
                    color_name_lbl.config(text=cname)
                    return
            color_name_lbl.config(text=c)
        _update_color_preview()

        # Palette de couleurs
        pal_frame = tk.Frame(form, bg=T.BG)
        pal_frame.grid(row=7, column=0, columnspan=2, sticky="w", pady=4)
        for cname, chex in _RULE_COLORS:
            bg = chex if chex else T.TEXT_DIM
            btn = tk.Label(pal_frame, bg=bg, width=3, height=1,
                           relief="raised", bd=2, cursor="hand2")
            btn.pack(side="left", padx=2, pady=2)

            def _pick(_e, h=chex):
                color_var.set(h)
                _update_color_preview()
            btn.bind("<Button-1>", _pick)

        # ── Boutons ──
        btn_frame = tk.Frame(dlg, bg=T.BG, padx=14, pady=10)
        btn_frame.pack(fill="x")

        def _save():
            rules[idx] = {
                "enabled": enabled_var.get(),
                "axis": axis_var.get(),
                "op": op_var.get(),
                "threshold": threshold_var.get(),
                "color": color_var.get(),
                "label": label_entry.get().strip(),
            }
            _save_rules(rules)
            self._refresh_rules_tree()
            self.refresh()
            dlg.destroy()

        ttk.Button(btn_frame, text=DLG_SAUVEGARDER, command=_save).pack(
            side="right", padx=(4, 0))
        ttk.Button(btn_frame, text=DLG_ANNULER, command=dlg.destroy).pack(
            side="right")

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        label_entry.focus_set()
        dlg.wait_window()

    # ── Helpers sélection ────────────────────────────────────────────────────

    def _selected_pose(self) -> Optional[str]:
        sel = self._tree.selection()
        if not sel:
            return None
        focused = self._tree.focus()
        iid = (focused if (focused and focused in sel
                            and focused.startswith("pose:")) else None)
        if iid is None:
            poses = [i for i in sel if i.startswith("pose:")]
            iid = poses[0] if poses else None
        return iid[5:] if iid else None

    def _selected_poses(self) -> List[str]:
        return [i[5:] for i in self._tree.selection()
                if i.startswith("pose:")]

    def _selected_group(self) -> Optional[str]:
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        return iid[4:] if iid.startswith("grp:") else None

    # ── Helpers couleur / groupe ─────────────────────────────────────────────

    def _get_color(self, pname: str) -> str:
        """Retourne la couleur d'une position depuis le champ meta du PositionModel."""
        pos = library.get_position_by_name(pname)
        if pos and pos.meta:
            return pos.meta.get("color", "")
        return ""

    def _get_group(self, pname: str) -> str:
        """Retourne le nom de la suite contenant cette position."""
        for suite in library.list_suites():
            for step in suite.steps:
                if step.get("position_name") == pname:
                    return suite.name
        return UNGROUPED_KEY

    # ── Actions positions ────────────────────────────────────────────────────

    def _save_current_pose(self) -> None:
        """CC=6 — Enregistre la position courante du robot actif (lecture hardware)."""
        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            messagebox.showwarning("Enregistrer", MSG_ROBOT_NON_CONNECTE)
            return
        name = simpledialog.askstring("Enregistrer position",
                                      "Nom de la position :")
        if not name or not name.strip():
            return
        name = name.strip()
        positions = ctrl.read_positions()
        if not positions:
            messagebox.showwarning("Enregistrer",
                                   "Impossible de lire la position du robot.")
            return

        # Vérifier si une position avec ce nom existe déjà
        existing = library.get_position_by_name(name)
        if existing:
            # Mise à jour de la position existante
            existing.positions = {int(k): int(v) for k, v in positions.items()}
            library.save_position(existing)
        else:
            # Nouvelle position
            pos_model = PositionModel(
                name=name,
                positions={int(k): int(v) for k, v in positions.items()},
            )
            library.save_position(pos_model)

        self.refresh()
        _LOG.info("Position '%s' enregistrée", name)

    def _goto_selected(self, _event: Optional[tk.Event] = None) -> None:
        """CC=5 — Envoie le robot vers la position sélectionnée (durée auto)."""
        pname = self._selected_pose()
        if not pname:
            return
        ctrl = _active_ctrl()
        if not ctrl or not ctrl.is_connected:
            messagebox.showwarning("Aller", MSG_ROBOT_NON_CONNECTE)
            return
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return
        targets = {int(k): int(v) for k, v in pos_model.positions.items()}
        current = ctrl.read_positions()
        duration = calculate_auto_duration(targets, current, speed_ratio=0.5)
        ctrl.move(targets, duration)
        _LOG.info("Aller à '%s' (durée auto: %.2fs)", pname, duration)

    def _edit_position_dialog(self) -> None:
        """CC=7 — Ouvre un dialog pour éditer tous les axes d'une position."""
        pname = self._selected_pose()
        if not pname:
            return
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return
        axis_names = _get_axis_names()
        rid = _active_rid()
        profile = None
        if rid:
            from xrv22.robots.robot_profiles import profile_registry
            profile = profile_registry.get(rid)

        dlg = tk.Toplevel(self)
        dlg.title(f"Éditer — {pname}")
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg=T.BG)
        dlg.resizable(False, False)

        tk.Label(dlg, text=f"Position : {pname}", bg=T.BG, fg=T.TEXT,
                 font=T.F_TITLE_SM).pack(padx=20, pady=(15, 10))

        spins = {}
        frame = tk.Frame(dlg, bg=T.BG)
        frame.pack(padx=20, pady=5)

        for mid in MOTOR_IDS:
            lo, hi = 0, MOTOR_RANGE_MAX
            if profile and hasattr(profile, 'soft_limits'):
                lo, hi = profile.soft_limits.get(mid, (0, MOTOR_RANGE_MAX))
            name = axis_names.get(mid, f"Axe {mid}")
            val = pos_model.positions.get(mid, MOTOR_CENTER)
            is_pince = (mid == PINCE_AXIS)

            row = tk.Frame(frame, bg=T.BG)
            row.pack(fill="x", pady=2)

            tk.Label(row, text=f"{name} ({mid})", bg=T.BG, fg=T.TEXT_DIM,
                     font=T.F_CONTROL, width=14, anchor="w").pack(side="left")

            if is_pince:
                cm_val = _ticks_to_cm(val, lo, hi)
                sp = tk.Spinbox(row, from_=0.0, to=_PINCE_CM_MAX,
                                increment=0.1, width=8,
                                font=T.F_MONO_SM, bg=T.SURFACE, fg=T.TEXT)
                sp.delete(0, tk.END)
                sp.insert(0, f"{cm_val:.1f}")
                sp.pack(side="left", padx=5)
                tk.Label(row, text="cm", bg=T.BG, fg=T.TEXT_DIM,
                         font=T.F_CAPTION).pack(side="left")
            else:
                deg_val = _ticks_to_deg(val)
                lo_deg = _ticks_to_deg(lo)
                hi_deg = _ticks_to_deg(hi)
                sp = tk.Spinbox(row, from_=lo_deg, to=hi_deg,
                                increment=0.5, width=8,
                                font=T.F_MONO_SM, bg=T.SURFACE, fg=T.TEXT)
                sp.delete(0, tk.END)
                sp.insert(0, f"{deg_val:.1f}")
                sp.pack(side="left", padx=5)
                tk.Label(row, text="°", bg=T.BG, fg=T.TEXT_DIM,
                         font=T.F_CAPTION).pack(side="left")

            spins[mid] = (sp, is_pince, lo, hi)

        # Boutons
        btn_f = tk.Frame(dlg, bg=T.BG)
        btn_f.pack(pady=(10, 15))

        def _save():
            new_pos = {}
            for mid, (sp, is_pince, lo, hi) in spins.items():
                try:
                    val = float(sp.get().replace(",", "."))
                except ValueError:
                    continue
                if is_pince:
                    ticks = _cm_to_ticks(val, lo, hi)
                else:
                    ticks = _deg_to_ticks(val)
                new_pos[mid] = max(lo, min(hi, ticks))
            pos_model.positions = new_pos
            pos_model.modified_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            library.save_position(pos_model)
            dlg.destroy()
            self.refresh()
            _LOG.info("Position '%s' éditée", pname)

        ttk.Button(btn_f, text=DLG_ANNULER,
                   command=dlg.destroy).pack(side="left", padx=5)
        ttk.Button(btn_f, text=DLG_SAUVEGARDER,
                   command=_save).pack(side="left", padx=5)

        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_rootx() + 200}+{self.winfo_rooty() + 100}")

    def _duplicate_selected(self) -> None:
        """CC=6 — Duplique une ou plusieurs poses."""
        names = self._selected_poses()
        if not names:
            return
        all_pos = _positions_dict()
        for name in names:
            src_model = all_pos.get(name)
            if not src_model:
                continue
            base = f"{name}_copie"
            new_name = base
            n = 1
            while new_name in all_pos or library.get_position_by_name(new_name):
                new_name = f"{base}_{n}"; n += 1
            new_model = PositionModel(
                name=new_name,
                positions=dict(src_model.positions),
                meta=dict(src_model.meta) if src_model.meta else {},
            )
            library.save_position(new_model)
            # Si la source est dans une suite, ajouter le duplicata à la même suite
            group = self._get_group(name)
            if group != UNGROUPED_KEY:
                suite = _get_suite_by_name(group)
                if suite:
                    suite.steps.append({
                        "position_id": new_model.id,
                        "position_name": new_name,
                        "duration_s": 2.0,
                        "pause_s": 0.0,
                    })
                    library.save_suite(suite)
        self.refresh()

    def _delete_selected(self) -> None:
        """CC=6 — Supprime les poses sélectionnées."""
        names = self._selected_poses()
        if not names:
            return
        msg = (f"Supprimer '{names[0]}' ?" if len(names) == 1
               else f"Supprimer {len(names)} positions ?")
        if not messagebox.askyesno("Supprimer", msg):
            return
        for name in names:
            pos_model = library.get_position_by_name(name)
            if not pos_model:
                continue
            ok, err_msg = library.delete_position(pos_model.id)
            if not ok:
                # Position dans une suite — la retirer d'abord
                for suite in library.list_suites():
                    old_len = len(suite.steps)
                    suite.steps = [s for s in suite.steps
                                   if s.get("position_id") != pos_model.id]
                    if len(suite.steps) != old_len:
                        library.save_suite(suite)
                # Réessayer la suppression
                library.delete_position(pos_model.id)
        self.refresh()

    def _apply_color(self, hex_color: str) -> None:
        """CC=4 — Applique une couleur à la pose sélectionnée."""
        name = self._selected_pose()
        if not name:
            return
        pos_model = library.get_position_by_name(name)
        if not pos_model:
            return
        if not pos_model.meta:
            pos_model.meta = {}
        pos_model.meta["color"] = hex_color
        library.save_position(pos_model)
        self.refresh()
        try:
            self._tree.selection_set(f"pose:{name}")
            self._tree.see(f"pose:{name}")
        except Exception:
            pass
        self._show_detail(name)

    def _remove_from_suite(self) -> None:
        """CC=5 — Retire les positions sélectionnées de leur suite (sans supprimer la position)."""
        names = self._selected_poses()
        if not names:
            messagebox.showwarning("Retirer",
                                   "Sélectionnez une ou plusieurs positions.")
            return
        # Vérifier que les positions sont bien dans une suite
        removed_any = False
        for name in names:
            pos_model = library.get_position_by_name(name)
            if not pos_model:
                continue
            for suite in library.list_suites():
                old_len = len(suite.steps)
                suite.steps = [s for s in suite.steps
                               if s.get("position_id") != pos_model.id]
                if len(suite.steps) != old_len:
                    library.save_suite(suite)
                    removed_any = True
                    _LOG.info("Position '%s' retirée de la suite '%s'",
                              name, suite.name)
        if not removed_any:
            messagebox.showinfo("Retirer",
                                "Les positions sélectionnées ne sont dans aucune suite.")
            return
        self.refresh()

    def _move_to_suite(self) -> None:
        """CC=8 — Déplace les poses sélectionnées vers une suite."""
        names = self._selected_poses()
        if not names:
            messagebox.showwarning("Déplacer",
                                   "Sélectionnez une ou plusieurs positions.")
            return
        suites = library.list_suites()
        suite_names = [s.name for s in suites]
        choices = [POS_SANS_SUITE] + [f"{POS_SUITE_PREFIX}{s}"
                                       for s in suite_names]

        dlg = tk.Toplevel(self)
        dlg.title("Déplacer dans une suite")
        dlg.geometry("320x220")
        dlg.transient(self); dlg.grab_set()

        lbl_txt = (f"Déplacer '{names[0]}' vers :" if len(names) == 1
                   else f"Déplacer {len(names)} positions vers :")
        ttk.Label(dlg, text=lbl_txt,
                  font=T.F_SECTION).pack(pady=(10, 5))
        lb = tk.Listbox(dlg, font=T.F_CONTROL, height=6)
        lb.pack(fill="both", expand=True, padx=10)
        for c in choices:
            lb.insert(tk.END, c)

        def do_move() -> None:
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]

            # Retirer des suites actuelles
            for n in names:
                pos_model = library.get_position_by_name(n)
                if not pos_model:
                    continue
                for suite in library.list_suites():
                    old_len = len(suite.steps)
                    suite.steps = [s for s in suite.steps
                                   if s.get("position_id") != pos_model.id]
                    if len(suite.steps) != old_len:
                        library.save_suite(suite)

            # Ajouter à la suite cible (sauf si "sans suite")
            if idx > 0:
                tgt_suite_name = suite_names[idx - 1]
                tgt_suite = _get_suite_by_name(tgt_suite_name)
                if tgt_suite:
                    for n in names:
                        pos_model = library.get_position_by_name(n)
                        if pos_model:
                            tgt_suite.steps.append({
                                "position_id": pos_model.id,
                                "position_name": n,
                                "duration_s": 2.0,
                                "pause_s": 0.0,
                            })
                    library.save_suite(tgt_suite)

            self.refresh()
            dlg.destroy()

        btn_f = ttk.Frame(dlg)
        btn_f.pack(pady=5)
        ttk.Button(btn_f, text=DLG_DEPLACER, command=do_move).pack(
            side="left", padx=5)
        ttk.Button(btn_f, text=DLG_ANNULER, command=dlg.destroy).pack(
            side="left")

    # ── Suites ───────────────────────────────────────────────────────────────

    def _add_suite(self) -> None:
        """CC=5."""
        name = simpledialog.askstring("Nouvelle suite", "Nom de la suite :")
        if not name or not name.strip():
            return
        name = name.strip()
        existing = _get_suite_by_name(name)
        if existing:
            messagebox.showwarning("Suite",
                                   MSG_SUITE_EXISTE.format(name=name))
            return
        new_suite = SuiteModel(name=name, steps=[])
        library.save_suite(new_suite)
        self.refresh()

    def _add_folder(self) -> None:
        """CC=3 — Crée un dossier (suite avec meta.is_folder=True)."""
        name = simpledialog.askstring("Nouveau dossier",
                                      "Nom du dossier :")
        if not name or not name.strip():
            return
        name = name.strip()
        existing = _get_suite_by_name(name)
        if existing:
            messagebox.showwarning("Dossier",
                                   MSG_SUITE_EXISTE.format(name=name))
            return
        folder = SuiteModel(name=name, steps=[],
                            meta={"is_folder": True})
        library.save_suite(folder)
        self.refresh()

    def _rename_suite(self) -> None:
        """CC=3 — Déclenche l'édition in-place de la suite sélectionnée."""
        grp = self._selected_group()
        if not grp or grp == UNGROUPED_KEY:
            messagebox.showwarning("Renommer", "Sélectionnez une suite à renommer.")
            return
        iid = f"grp:{grp}"
        self._tree.see(iid)
        self._inline_rename_suite(iid)

    def _duplicate_suite(self) -> None:
        """CC=6."""
        grp = self._selected_group()
        if not grp or grp == UNGROUPED_KEY:
            return
        suite = _get_suite_by_name(grp)
        if not suite:
            return
        # Générer un nom unique pour la copie
        new_name = f"{grp}_copie"
        n = 1
        while _get_suite_by_name(new_name):
            new_name = f"{grp}_copie_{n}"; n += 1

        # Dupliquer les positions et la suite
        new_steps = []
        for step in suite.steps:
            old_pname = step.get("position_name", "")
            old_pos = library.get_position_by_name(old_pname)
            if not old_pos:
                continue
            # Créer une copie de la position
            new_pname = f"{old_pname}_copie"
            k = 1
            while library.get_position_by_name(new_pname):
                new_pname = f"{old_pname}_copie_{k}"; k += 1
            new_pos = PositionModel(
                name=new_pname,
                positions=dict(old_pos.positions),
                meta=dict(old_pos.meta) if old_pos.meta else {},
            )
            library.save_position(new_pos)
            new_steps.append({
                "position_id": new_pos.id,
                "position_name": new_pname,
                "duration_s": step.get("duration_s", 2.0),
                "pause_s": step.get("pause_s", 0.0),
            })

        new_suite = SuiteModel(name=new_name, steps=new_steps)
        library.save_suite(new_suite)
        self.refresh()

    def _delete_suite(self) -> None:
        """CC=5."""
        grp = self._selected_group()
        if not grp or grp == UNGROUPED_KEY:
            messagebox.showwarning("Suite", "Sélectionnez une suite à supprimer.")
            return
        if not messagebox.askyesno(
                "Supprimer suite",
                f"Supprimer la suite '{grp}' ?\n"
                "(les positions reviennent sans suite)"):
            return
        suite = _get_suite_by_name(grp)
        if suite:
            library.delete_suite(suite.id)
        # Les positions existent toujours dans la library, elles seront
        # simplement affichées dans "Sans suite" au prochain refresh
        self.refresh()

    # ── Wizard suite pas à pas ────────────────────────────────────────────────

    def _suite_wizard(self) -> None:
        """CC=10 — Wizard de création de suite."""
        _LOG.info("=== Wizard suite : ouverture ===")
        existing_suites = {s.name for s in library.list_suites()}
        suite_name = self._wizard_ask_name(existing_suites)
        if not suite_name:
            return

        captured: list = []
        live = {"on": True}

        dlg = tk.Toplevel(self)
        dlg.title(f"Créer suite : {suite_name}")
        dlg.geometry("520x600")
        dlg.transient(self)

        mf = ttk.Frame(dlg, padding=14)
        mf.pack(fill="both", expand=True)
        ttk.Label(mf, text=f"Suite : {suite_name}",
                  font=T.F_SECTION).pack(anchor="w")
        ttk.Label(mf,
                  text="Positionnez le robot puis cliquez 📸 ou appuyez sur Espace.",
                  font=T.F_CAPTION, foreground="gray").pack(anchor="w",
                                                             pady=(2, 8))

        # Sélection robot
        robot_f = ttk.LabelFrame(mf, text="Robot", padding=8)
        robot_f.pack(fill="x", pady=(0, 8))
        robot_names = sorted(registry.ids()) or ["robot_1"]
        robot_var   = tk.StringVar(value=_active_rid() or robot_names[0])
        rrow = ttk.Frame(robot_f)
        rrow.pack(fill="x")
        ttk.Label(rrow, text="Robot actif :").pack(side="left")
        robot_combo = ttk.Combobox(rrow, textvariable=robot_var,
                                   values=robot_names,
                                   state="readonly", width=18)
        robot_combo.pack(side="left", padx=8)
        lock_lbl = ttk.Label(rrow, text="", foreground="gray")
        lock_lbl.pack(side="left", padx=8)

        def _get_s():
            return registry.get(robot_var.get())

        def _update_lock() -> None:
            c = _get_s()
            if c and c.is_connected:
                if c.torque_enabled:
                    lock_lbl.config(text="🟢 Torque ON",
                                    foreground=T.C_OK)
                else:
                    lock_lbl.config(text="🟡 Torque OFF",
                                    foreground=T.C_AMB)
            else:
                lock_lbl.config(text="⚪ Non connecté",
                                foreground=T.TEXT_DIM)

        def _torque_on() -> None:
            c = _get_s()
            if c:
                c.set_torque(True)
                _LOG.info("Wizard : Torque ON (%s)", robot_var.get())
            _update_lock()
            dlg.focus_set()

        def _torque_off() -> None:
            c = _get_s()
            if c:
                c.set_torque(False)
                _LOG.info("Wizard : Torque OFF (%s)", robot_var.get())
            _update_lock()
            dlg.focus_set()

        brow = ttk.Frame(robot_f)
        brow.pack(fill="x", pady=(6, 0))
        ttk.Button(brow, text="🔒 Torque ON",
                   command=_torque_on).pack(side="left", padx=(0, 6))
        ttk.Button(brow, text="🔓 Torque OFF",
                   command=_torque_off).pack(side="left", padx=(0, 6))

        # --- Mode Teach (enregistrement continu) ---
        teach_state = {"active": False, "timer_id": None}
        TEACH_INTERVAL_MS = 200      # intervalle de capture
        TEACH_THRESHOLD   = 30       # seuil minimal en ticks pour capturer

        def _teach_should_capture(pos: Dict[int, int]) -> bool:
            """Vérifie si la position a suffisamment bougé."""
            if not captured:
                return True
            last = captured[-1][1]
            return any(abs(pos.get(m, 2048) - last.get(m, 2048))
                       > TEACH_THRESHOLD for m in MOTOR_IDS)

        def _teach_tick() -> None:
            """Timer de capture en mode teach."""
            if not teach_state["active"] or not live["on"]:
                return
            pos = _read_current_positions()
            if pos and _teach_should_capture(pos) and len(captured) < 500:
                pname = _unique_name(len(captured) + 1)
                captured.append((pname, dict(pos)))
                _refresh_wiz_list()
                _LOG.debug("Teach capture #%d : %s", len(captured), pname)
            teach_state["timer_id"] = dlg.after(TEACH_INTERVAL_MS, _teach_tick)

        def _toggle_teach() -> None:
            if teach_state["active"]:
                # Arrêt du mode teach
                teach_state["active"] = False
                if teach_state["timer_id"]:
                    dlg.after_cancel(teach_state["timer_id"])
                    teach_state["timer_id"] = None
                teach_btn.config(text="🎓 Teach")
                _LOG.info("Teach : arrêt (%d poses)", len(captured))
            else:
                # Démarrage du mode teach — torque off auto
                c = _get_s()
                if not c or not c.is_connected:
                    messagebox.showwarning("Teach",
                                           "Robot non connecté.",
                                           parent=dlg)
                    return
                c.set_torque(False)
                _update_lock()
                teach_state["active"] = True
                teach_btn.config(text="⏹ Stop Teach")
                _LOG.info("Teach : démarrage (torque off, seuil=%d)",
                          TEACH_THRESHOLD)
                _teach_tick()
            dlg.focus_set()

        teach_btn = ttk.Button(brow, text="🎓 Teach",
                               command=_toggle_teach)
        teach_btn.pack(side="left")
        robot_combo.bind("<<ComboboxSelected>>",
                         lambda e: _update_lock())
        _update_lock()

        # Position live
        lf = ttk.LabelFrame(mf, text="Position actuelle du robot",
                             padding=8)
        lf.pack(fill="x", pady=(0, 8))
        ag = ttk.Frame(lf)
        ag.pack(fill="x")
        axis_lbls_wiz: Dict[int, ttk.Label] = {}
        for i, mid in enumerate(MOTOR_IDS):
            col = ttk.Frame(ag)
            col.grid(row=i // 4, column=i % 4, padx=6, pady=2, sticky="w")
            ttk.Label(col, text=f"A{mid}:", font=T.F_MONO_SM).pack(
                side="left")
            lbl = ttk.Label(col, text="—", font=T.F_MONO_SM,
                            foreground=T.C_AMB, width=5)
            lbl.pack(side="left")
            axis_lbls_wiz[mid] = lbl

        # Poses capturées
        pf = ttk.LabelFrame(mf, text="Poses capturées", padding=6)
        pf.pack(fill="both", expand=True, pady=(0, 8))
        plb = tk.Listbox(pf, height=8, font=T.F_MONO_SM,
                         selectmode="browse", activestyle="none")
        plb.pack(fill="both", expand=True)
        cnt_lbl = ttk.Label(mf, text="0 pose(s) capturée(s)",
                            font=T.F_CAPTION, foreground="gray")
        cnt_lbl.pack(anchor="w", pady=(0, 6))

        def _refresh_wiz_list() -> None:
            plb.delete(0, tk.END)
            for pn, _ in captured:
                plb.insert(tk.END, f"  {pn}")
            if captured:
                plb.see(tk.END)
            n = len(captured)
            cnt_lbl.config(text=f"{n} pose(s) capturée(s)")

        def _read_current_positions() -> Dict[int, int]:
            """Lit les positions : hardware si connecté, sinon store."""
            rid = robot_var.get()
            c = _get_s()
            # Tentative lecture hardware directe
            if c and c.is_connected:
                try:
                    pos = c.read_positions()
                    if pos:
                        return pos
                except Exception as exc:
                    _LOG.debug("Wizard live — lecture hardware échouée : %s", exc)
            # Fallback : positions depuis le store (dernière lecture connue)
            snap = store.get_robot(rid)
            if snap and snap.positions:
                return dict(snap.positions)
            return {}

        def _update_live() -> None:
            """Rafraîchissement live des positions affichées."""
            if not live["on"]:
                return
            try:
                pos = _read_current_positions()
                for mid, lbl in axis_lbls_wiz.items():
                    val = pos.get(mid)
                    lbl.config(text=str(val) if val is not None else "—")
            except Exception as exc:
                _LOG.debug("Wizard live — erreur refresh : %s", exc)
            dlg.after(300, _update_live)

        _LOG.info("Wizard suite : démarrage refresh live (robot=%s)",
                  robot_var.get())
        dlg.after(100, _update_live)

        def _unique_name(n: int) -> str:
            existing_pos = _positions_dict()
            base = f"{suite_name}_{n:03d}"
            name = base; suf = 1
            while (name in existing_pos
                   or any(p == name for p, _ in captured)):
                name = f"{base}_{suf}"; suf += 1
            return name

        def _capture() -> None:
            """Capture la position réelle courante du robot."""
            rid = robot_var.get()
            c = _get_s()
            # Lecture hardware directe
            positions = {}
            if c and c.is_connected:
                positions = c.read_positions()
            # Fallback store si hardware échoue
            if not positions:
                snap = store.get_robot(rid)
                if snap and snap.positions:
                    positions = dict(snap.positions)
                    _LOG.warning("Wizard capture — fallback store pour %s", rid)
            if not positions:
                messagebox.showwarning("Capture",
                                       "Impossible de lire la position.\n"
                                       "Vérifiez la connexion du robot.",
                                       parent=dlg)
                return
            pname = _unique_name(len(captured) + 1)
            captured.append((pname, dict(positions)))
            _LOG.info("Wizard capture #%d : %s -> %s",
                      len(captured), pname, positions)
            _refresh_wiz_list()
            # Redonner le focus au dialogue pour que Espace continue de marcher
            dlg.focus_set()

        def _undo() -> None:
            if captured:
                removed = captured.pop()
                _LOG.info("Wizard undo : %s retirée", removed[0])
                _refresh_wiz_list()
            dlg.focus_set()

        def _validate() -> None:
            if not captured:
                messagebox.showwarning("Suite vide",
                                       "Capturez au moins une pose.",
                                       parent=dlg)
                return
            _stop_teach_if_active()
            live["on"] = False
            _LOG.info("Wizard suite : sauvegarde '%s' avec %d poses",
                      suite_name, len(captured))
            self._wizard_save(suite_name, captured)
            dlg.destroy()

        def _stop_teach_if_active() -> None:
            """Arrête proprement le mode teach."""
            if teach_state["active"]:
                teach_state["active"] = False
                if teach_state["timer_id"]:
                    dlg.after_cancel(teach_state["timer_id"])
                    teach_state["timer_id"] = None

        def _cancel() -> None:
            _stop_teach_if_active()
            live["on"] = False
            if captured and not messagebox.askyesno(
                    "Annuler ?",
                    f"{len(captured)} pose(s) non sauvegardée(s). Annuler ?",
                    parent=dlg):
                live["on"] = True
                return
            _LOG.info("Wizard suite : annulé")
            dlg.destroy()

        def _on_space(event: tk.Event) -> Optional[str]:
            # Ne pas capturer si le focus est dans un champ de saisie
            w = dlg.focus_get()
            if isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox,
                               tk.Spinbox, ttk.Spinbox)):
                return None
            _LOG.debug("Wizard : barre d'espace -> capture")
            _capture()
            return "break"

        # Boutons d'action — créés AVANT le binding pour que focus_set() passe après
        bf = ttk.Frame(mf)
        bf.pack(fill="x")
        ttk.Button(bf, text=WIZ_CAPTURER,
                   command=_capture).pack(side="left", padx=(0, 6))
        ttk.Button(bf, text=WIZ_ANNULER_LAST,
                   command=_undo).pack(side="left", padx=(0, 6))
        ttk.Button(bf, text=WIZ_ANNULER_TOUT,
                   command=_cancel).pack(side="left")
        ttk.Button(bf, text=WIZ_ENREGISTRER,
                   command=_validate).pack(side="right")

        def _stabilize_assiette() -> None:
            """Post-corrige l'axe 5 de chaque pose pour fixer l'assiette."""
            if len(captured) < 2:
                messagebox.showinfo("Assiette",
                                     "Il faut au moins 2 poses.",
                                     parent=dlg)
                return
            # Angle cible = assiette de la 1ère pose
            first = captured[0][1]
            a2_0 = math.radians((first.get(2, 2048) - 2048) * 300.0 / 4096.0)
            a3_0 = math.radians((first.get(3, 2048) - 2048) * 300.0 / 4096.0)
            a5_0 = math.radians((first.get(5, 2048) - 2048) * 300.0 / 4096.0)
            target = a2_0 + a3_0 + a5_0
            corrected = 0
            for i, (pname, pdata) in enumerate(captured[1:], 1):
                a2 = math.radians((pdata.get(2, 2048) - 2048) * 300.0 / 4096.0)
                a3 = math.radians((pdata.get(3, 2048) - 2048) * 300.0 / 4096.0)
                a5_new = target - a2 - a3
                if abs(a5_new) <= math.radians(150):
                    tick5 = int(2048 + math.degrees(a5_new) * 4096.0 / 300.0)
                    tick5 = max(0, min(4095, tick5))
                    pdata[5] = tick5
                    corrected += 1
            messagebox.showinfo("Assiette",
                                f"{corrected} pose(s) corrigée(s)\n"
                                f"Angle cible : {math.degrees(target):.0f}°",
                                parent=dlg)
            _refresh_wiz_list()
            _LOG.info("Assiette stabilisée : %d poses, cible %.0f°",
                      corrected, math.degrees(target))

        ttk.Button(bf, text="🔒 Stabiliser assiette",
                   command=_stabilize_assiette).pack(side="right", padx=(0, 6))

        # Binding barre d'espace — interception au niveau du Toplevel
        # bind_all intercepte AVANT les widgets enfants (ttk.Button inclus)
        dlg.bind_all("<KeyPress-space>", _on_space)
        dlg.protocol("WM_DELETE_WINDOW", _cancel)

        # Focus sur le dialogue (pas sur un bouton) pour que Espace fonctionne
        dlg.after(50, dlg.focus_set)

        def _on_wizard_close() -> None:
            """Nettoyage du bind_all à la fermeture."""
            try:
                dlg.unbind_all("<KeyPress-space>")
            except Exception:
                pass

        dlg.bind("<Destroy>", lambda e: _on_wizard_close()
                 if e.widget is dlg else None)

        dlg.wait_window()

    def _wizard_ask_name(self, existing_names) -> Optional[str]:
        """CC=5 — Dialogue demande du nom de suite."""
        n = 1
        while f"Suite_{n:03d}" in existing_names:
            n += 1
        default = f"Suite_{n:03d}"
        result = {"name": None}
        dlg = tk.Toplevel(self)
        dlg.title("Nouvelle suite — Nom")
        dlg.geometry("360x130")
        dlg.transient(self); dlg.grab_set(); dlg.resizable(False, False)
        f = ttk.Frame(dlg, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Nom de la suite :", font=T.F_SECTION).pack(anchor="w")
        ttk.Label(f, text="Les poses seront nommées : Nom_001, Nom_002…",
                  font=T.F_CAPTION, foreground="gray").pack(anchor="w",
                                                             pady=(2, 6))
        var = tk.StringVar(value=default)
        e = ttk.Entry(f, textvariable=var, width=30, font=T.F_CONTROL)
        e.pack(fill="x"); e.select_range(0, tk.END); e.focus_set()

        def _confirm() -> None:
            v = var.get().strip()
            if not v:
                return
            if v in existing_names:
                messagebox.showwarning(
                    "Suite", MSG_SUITE_EXISTE.format(name=v), parent=dlg)
                return
            result["name"] = v
            dlg.destroy()

        br = ttk.Frame(f)
        br.pack(fill="x", pady=(8, 0))
        ttk.Button(br, text=DLG_ANNULER, command=dlg.destroy).pack(
            side="left")
        ttk.Button(br, text=DLG_SUIVANT, command=_confirm).pack(
            side="right")
        dlg.bind("<Return>", lambda e: _confirm())
        dlg.wait_window()
        return result["name"]

    def _wizard_save(self, suite_name: str,
                     captured_poses: list) -> None:
        """CC=4 — Sauvegarde les poses et la suite via library."""
        steps = []
        for pname, pdata in captured_poses:
            pos_model = PositionModel(
                name=pname,
                positions={int(k): int(v) for k, v in pdata.items()},
                meta={"color": ""},
            )
            library.save_position(pos_model)
            steps.append({
                "position_id": pos_model.id,
                "position_name": pname,
                "duration_s": 2.0,
                "pause_s": 0.0,
            })
        new_suite = SuiteModel(name=suite_name, steps=steps)
        library.save_suite(new_suite)
        self.refresh()
        _LOG.info("Suite '%s' créée — %d pose(s)", suite_name, len(steps))

    # ── Drag & Drop ──────────────────────────────────────────────────────────

    # ── Drag & Drop amélioré ─────────────────────────────────────────────────

    _DND_SCROLL_ZONE = 30   # pixels du bord pour auto-scroll
    _DND_SCROLL_SPEED = 2   # unités de scroll

    def _dnd_start(self, event: tk.Event) -> None:
        """CC=3 — Démarre le drag & drop."""
        iid = self._tree.identify_row(event.y)
        if not iid or not (iid.startswith("pose:") or iid.startswith("grp:")):
            self._dnd_item = None
            return
        self._dnd_item = iid
        self._dnd_start_y = event.y
        self._dnd_active = False  # pas encore en drag (seuil de distance)
        self._dnd_ghost = None
        self._dnd_indicator = None
        self._dnd_last_target = None

    def _dnd_ensure_widgets(self) -> None:
        """Crée le ghost label et l'indicateur de drop si nécessaire."""
        if self._dnd_ghost is None:
            self._dnd_ghost = tk.Label(
                self._tree, bg=T.C_MAG_DIM2, fg=T.C_AMB,
                font=T.F_CONTROL, padx=8, pady=3,
                relief="solid", bd=1)
        if self._dnd_indicator is None:
            self._dnd_indicator = tk.Canvas(
                self._tree, height=3, bg=T.C_MAG,
                highlightthickness=0, bd=0)

    def _dnd_motion(self, event: tk.Event) -> None:
        """CC=6 — Mouvement pendant le drag : ghost, indicateur, auto-scroll."""
        if not self._dnd_item:
            return
        # Seuil de distance pour activer le drag (évite les clics accidentels)
        if not self._dnd_active:
            if abs(event.y - self._dnd_start_y) < 6:
                return
            self._dnd_active = True
            self._dnd_ensure_widgets()
            # Texte du ghost
            src = self._dnd_item
            if src.startswith("pose:"):
                name = src[5:]
            else:
                name = src[4:]
            self._dnd_ghost.config(text=f"  ≡  {name}")
            self._tree.config(cursor="fleur")

        # Positionner le ghost sous le curseur
        try:
            self._dnd_ghost.place(x=event.x + 16, y=event.y - 10)
            self._dnd_ghost.lift()
        except tk.TclError:
            pass

        # Auto-scroll près des bords
        tree_h = self._tree.winfo_height()
        if event.y < self._DND_SCROLL_ZONE:
            self._tree.yview_scroll(-self._DND_SCROLL_SPEED, "units")
            self._pince_tree.yview_scroll(-self._DND_SCROLL_SPEED, "units")
        elif event.y > tree_h - self._DND_SCROLL_ZONE:
            self._tree.yview_scroll(self._DND_SCROLL_SPEED, "units")
            self._pince_tree.yview_scroll(self._DND_SCROLL_SPEED, "units")

        # Indicateur de drop
        target = self._tree.identify_row(event.y)
        self._dnd_show_indicator(target, event.y)

    def _dnd_show_indicator(self, target: str, mouse_y: int) -> None:
        """CC=5 — Affiche l'indicateur de drop (ligne + highlight groupe)."""
        try:
            # Reset le highlight précédent
            if self._dnd_last_target and self._dnd_last_target.startswith("grp:"):
                self._tree.tag_configure("dnd_hover", background="")
                try:
                    old_tags = list(self._tree.item(self._dnd_last_target, "tags"))
                    if "dnd_hover" in old_tags:
                        old_tags.remove("dnd_hover")
                        self._tree.item(self._dnd_last_target, tags=old_tags)
                except tk.TclError:
                    pass

            if not target or target == self._dnd_item:
                self._dnd_indicator.place_forget()
                self._dnd_last_target = None
                return

            bbox = self._tree.bbox(target)
            if not bbox:
                self._dnd_indicator.place_forget()
                self._dnd_last_target = target
                return

            x, y, w, h = bbox

            if target.startswith("grp:"):
                # Survol d'un groupe → highlight fond
                self._tree.tag_configure("dnd_hover", background=T.C_MAG_DIM2)
                tags = list(self._tree.item(target, "tags"))
                if "dnd_hover" not in tags:
                    tags.append("dnd_hover")
                    self._tree.item(target, tags=tags)
                self._dnd_indicator.place_forget()
            else:
                # Survol d'une position → ligne d'insertion avant/après
                mid_y = y + h // 2
                if mouse_y < mid_y:
                    line_y = y  # avant
                else:
                    line_y = y + h  # après
                self._dnd_indicator.place(x=x + 16, y=line_y - 1,
                                          width=w - 16, height=3)
                self._dnd_indicator.lift()

            self._dnd_last_target = target
        except tk.TclError:
            pass

    def _dnd_drop(self, event: tk.Event) -> None:
        """CC=6 — Gestion du drop."""
        self._tree.config(cursor="")
        # Nettoyer les widgets visuels
        if self._dnd_ghost:
            try:
                self._dnd_ghost.place_forget()
            except tk.TclError:
                pass
        if self._dnd_indicator:
            try:
                self._dnd_indicator.place_forget()
            except tk.TclError:
                pass
        # Reset highlight
        if self._dnd_last_target and self._dnd_last_target.startswith("grp:"):
            self._tree.tag_configure("dnd_hover", background="")
            try:
                old_tags = list(self._tree.item(self._dnd_last_target, "tags"))
                if "dnd_hover" in old_tags:
                    old_tags.remove("dnd_hover")
                    self._tree.item(self._dnd_last_target, tags=old_tags)
            except tk.TclError:
                pass
        self._dnd_last_target = None

        if not self._dnd_item or not self._dnd_active:
            self._dnd_item = None
            return
        src = self._dnd_item
        self._dnd_item = None
        tgt = self._tree.identify_row(event.y)
        if not tgt or tgt == src:
            return

        if src.startswith("pose:"):
            self._dnd_move_pose(src, tgt, event.y)
        elif src.startswith("grp:"):
            self._dnd_move_suite(src, tgt)

    def _resolve_target_group(self, tgt_iid: str) -> Optional[str]:
        """CC=4 — Résout le groupe cible d'un drag & drop."""
        if tgt_iid.startswith("grp:"):
            return tgt_iid[4:]
        if tgt_iid.startswith("pose:"):
            parent = self._tree.parent(tgt_iid)
            return parent[4:] if parent.startswith("grp:") else None
        return None

    def _dnd_move_pose(self, src_iid: str, tgt_iid: str,
                       mouse_y: int) -> None:
        """CC=8 — Déplace une pose par drag & drop (entre groupes ou réordonne)."""
        pname = src_iid[5:]
        pos_model = library.get_position_by_name(pname)
        if not pos_model:
            return

        tgt_grp = self._resolve_target_group(tgt_iid)
        if tgt_grp is None:
            tgt_grp = UNGROUPED_KEY
        src_grp = self._get_group(pname)

        # Calculer la position d'insertion (avant/après la cible)
        insert_before = True
        tgt_pose = None
        if tgt_iid.startswith("pose:"):
            tgt_pose = tgt_iid[5:]
            bbox = self._tree.bbox(tgt_iid)
            if bbox:
                _, y, _, h = bbox
                insert_before = mouse_y < y + h // 2

        # Retirer de la suite actuelle
        for suite in library.list_suites():
            old_len = len(suite.steps)
            suite.steps = [s for s in suite.steps
                           if s.get("position_id") != pos_model.id]
            if len(suite.steps) != old_len:
                library.save_suite(suite)

        # Ajouter dans la suite cible
        if tgt_grp != UNGROUPED_KEY:
            tgt_suite = _get_suite_by_name(tgt_grp)
            if tgt_suite:
                new_step = {
                    "position_id": pos_model.id,
                    "position_name": pname,
                    "duration_s": 2.0,
                    "pause_s": 0.0,
                }
                if tgt_pose:
                    # Insérer avant ou après la pose cible
                    insert_idx = len(tgt_suite.steps)
                    for idx, step in enumerate(tgt_suite.steps):
                        if step.get("position_name") == tgt_pose:
                            insert_idx = idx if insert_before else idx + 1
                            break
                    tgt_suite.steps.insert(insert_idx, new_step)
                else:
                    tgt_suite.steps.append(new_step)
                library.save_suite(tgt_suite)

        self.refresh()
        try:
            self._tree.selection_set(src_iid)
            self._tree.see(src_iid)
        except tk.TclError:
            pass

    def _dnd_move_suite(self, src_iid: str, tgt_iid: str) -> None:
        """CC=5 — Déplace une suite dans/hors d'un dossier par drag & drop."""
        suite_name = src_iid[4:]
        suite = _get_suite_by_name(suite_name)
        if not suite or suite.meta.get("is_folder"):
            return  # pas de drag de dossier dans un dossier

        # Déterminer le dossier cible
        tgt_name = ""
        if tgt_iid.startswith("grp:"):
            tgt_name = tgt_iid[4:]
        elif tgt_iid.startswith("pose:"):
            parent = self._tree.parent(tgt_iid)
            if parent.startswith("grp:"):
                tgt_name = parent[4:]

        tgt_suite = _get_suite_by_name(tgt_name) if tgt_name else None
        is_tgt_folder = tgt_suite and tgt_suite.meta.get("is_folder", False)

        if is_tgt_folder and tgt_name != suite_name:
            suite.meta["parent_folder"] = tgt_name
        else:
            suite.meta.pop("parent_folder", None)

        library.save_suite(suite)
        self.refresh()
        try:
            self._tree.selection_set(src_iid)
            self._tree.see(src_iid)
        except tk.TclError:
            pass

    # ── Bus ──────────────────────────────────────────────────────────────────

    def _subscribe(self) -> None:
        self._bus_cb_loaded = lambda _: self.after(0, self.refresh)
        self._bus_cb_new = lambda _: self.after(0, self.refresh)
        self._bus_cb_robot = lambda d: self.after(0, self._sync_robot_selector)
        bus.subscribe("project.loaded", self._bus_cb_loaded)
        bus.subscribe("project.new", self._bus_cb_new)
        bus.subscribe("ui.active_robot_changed", self._bus_cb_robot)
        bus.subscribe("robot.added", self._bus_cb_robot)

    def _sync_robot_selector(self) -> None:
        """Synchronise le sélecteur robot quand le robot actif change."""
        rid = _active_rid()
        if hasattr(self, "_robot_selector_var") and rid:
            self._robot_selector_var.set(rid)
            self._update_robot_bar_color()
            self._build_detail_sliders()

    def destroy(self) -> None:
        bus.unsubscribe("project.loaded", self._bus_cb_loaded)
        bus.unsubscribe("project.new", self._bus_cb_new)
        bus.unsubscribe("ui.active_robot_changed", self._bus_cb_robot)
        bus.unsubscribe("robot.added", self._bus_cb_robot)
        super().destroy()
