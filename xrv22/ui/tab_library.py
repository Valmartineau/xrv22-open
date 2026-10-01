"""
xrv22/ui/tab_library.py — V22
Explorateur de la librairie centralisée.

Navigation arborescente :
  LIBRAIRIE
  ├── Positions
  │   ├── Initiales machine
  │   ├── Positions de travail
  │   └── Positions sauvegardées
  ├── Suites
  ├── Scénarios
  ├── Capteurs Arduino
  ├── Profils de mouvement
  └── Paramètres ouverture

CRUD complet : créer, modifier, supprimer, charger.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import Optional

from xrv22.theme import theme as T
from xrv22.ui.widgets import NeuFrame, NeuButton, SectionHeader
from xrv22.library.library_manager import library
from xrv22.library.models import PositionModel, SuiteModel, ScenarioModel, MotionProfileModel
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger

_LOG = get_logger("UI.Library")

# ── Catégories de l'arbre ──
_CATEGORIES = {
    "positions_machine":   ("Positions", "Initiales machine", "machine_initiales"),
    "positions_travail":   ("Positions", "Positions de travail", "travail"),
    "positions_saved":     ("Positions", "Positions sauvegardées", "sauvegardees"),
    "suites":              ("Suites", None, None),
    "scenarios":           ("Scénarios", None, None),
    "profiles":            ("Profils de mouvement", None, None),
}


class LibraryTab(tk.Frame):
    """Onglet Librairie — Explorateur de la source unique de vérité."""

    def __init__(self, parent: tk.Widget, on_after, active_robot_fn=None) -> None:
        super().__init__(parent, bg=T.BG)
        self._after = on_after
        self._build()
        self._after(500, self._refresh_tree)

    # ── Construction ──────────────────────────────────────────────

    def _build(self) -> None:
        # Barre de titre
        top = tk.Frame(self, bg=T.BG, padx=T.PAD_MD, pady=T.PAD_SM)
        top.pack(fill="x")
        tk.Label(top, text="📚 LIBRAIRIE", bg=T.BG, fg=T.C_MAG,
                 font=T.F_TITLE).pack(side="left")

        # Boutons d'action
        btn_row = tk.Frame(top, bg=T.BG)
        btn_row.pack(side="right")
        for text, cmd in [
            ("Rafraîchir", self._refresh_tree),
            ("Nouveau", self._on_new),
            ("Modifier", self._on_edit),
            ("Supprimer", self._on_delete),
        ]:
            b = tk.Button(btn_row, text=text, command=cmd,
                          bg=T.SURFACE, fg=T.TEXT, font=T.F_CONTROL,
                          relief="flat", padx=8, pady=2)
            b.pack(side="left", padx=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=4)

        # Layout principal : arbre à gauche, détail à droite
        paned = tk.PanedWindow(self, orient="horizontal", bg=T.BG,
                               sashwidth=4, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=T.PAD_MD, pady=T.PAD_SM)

        # ── Arbre (Treeview) ──
        tree_frame = tk.Frame(paned, bg=T.SURFACE)
        self._tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        paned.add(tree_frame, width=320)

        # ── Panneau détail ──
        self._detail_frame = tk.Frame(paned, bg=T.SURFACE, padx=10, pady=10)
        self._detail_label = tk.Label(self._detail_frame,
                                      text="Sélectionnez un élément",
                                      bg=T.SURFACE, fg=T.TEXT_DIM,
                                      font=T.F_SECTION, wraplength=400,
                                      justify="left", anchor="nw")
        self._detail_label.pack(fill="both", expand=True, anchor="nw")
        paned.add(self._detail_frame, width=500)

    # ── Rafraîchir l'arbre ────────────────────────────────────────

    def _refresh_tree(self) -> None:
        """Reconstruit l'arbre depuis la librairie."""
        tree = self._tree
        for item in tree.get_children():
            tree.delete(item)

        if not library.loaded:
            tree.insert("", "end", text="(Aucun projet chargé)")
            return

        # Projet
        proj_node = tree.insert("", "end", text=f"📁 {library.project_name}",
                                open=True, tags=("project",))

        # ── Positions ──
        pos_node = tree.insert(proj_node, "end", text="📍 Positions", open=True,
                               tags=("category",))
        for cat_key, (_, label, cat_filter) in _CATEGORIES.items():
            if not cat_key.startswith("positions_"):
                continue
            cat_node = tree.insert(pos_node, "end", text=f"  {label}",
                                   tags=("subcategory", cat_filter))
            positions = library.list_positions(category=cat_filter)
            for pos in sorted(positions, key=lambda p: p.name):
                tree.insert(cat_node, "end",
                            text=f"    {pos.name}",
                            tags=("position", pos.id))

        # ── Suites ──
        suite_node = tree.insert(proj_node, "end", text="📋 Suites", open=True,
                                 tags=("category",))
        for suite in sorted(library.list_suites(), key=lambda s: s.name):
            tree.insert(suite_node, "end",
                        text=f"  {suite.name} ({len(suite.steps)} étapes)",
                        tags=("suite", suite.id))

        # ── Scénarios ──
        scen_node = tree.insert(proj_node, "end", text="🎬 Scénarios", open=False,
                                tags=("category",))
        for scen in sorted(library.list_scenarios(), key=lambda s: s.name):
            tree.insert(scen_node, "end",
                        text=f"  {scen.name}",
                        tags=("scenario", scen.id))

        # ── Profils mouvement ──
        prof_node = tree.insert(proj_node, "end", text="⚙️ Profils mouvement",
                                open=False, tags=("category",))
        for prof in library.list_motion_profiles():
            tree.insert(prof_node, "end",
                        text=f"  {prof.name} (vel={prof.comfort_vel} acc={prof.comfort_acc})",
                        tags=("profile", prof.id))

        # ── Robots ──
        robot_node = tree.insert(proj_node, "end", text="🤖 Robots", open=False,
                                 tags=("category",))
        for robot in library.list_robots():
            tree.insert(robot_node, "end",
                        text=f"  {robot.robot_id} — {robot.port or '(pas de port)'}",
                        tags=("robot", robot.robot_id))

    # ── Sélection ─────────────────────────────────────────────────

    def _on_select(self, event=None) -> None:
        """Affiche le détail de l'élément sélectionné."""
        sel = self._tree.selection()
        if not sel:
            return
        item = sel[0]
        tags = self._tree.item(item, "tags")
        if not tags:
            return

        kind = tags[0]
        obj_id = tags[1] if len(tags) > 1 else ""

        if kind == "position":
            self._show_position_detail(obj_id)
        elif kind == "suite":
            self._show_suite_detail(obj_id)
        elif kind == "scenario":
            self._show_scenario_detail(obj_id)
        elif kind == "profile":
            self._show_profile_detail(obj_id)
        elif kind == "robot":
            self._show_robot_detail(obj_id)
        else:
            self._detail_label.config(text=self._tree.item(item, "text").strip())

    def _show_position_detail(self, pos_id: str) -> None:
        pos = library.get_position(pos_id)
        if not pos:
            return
        lines = [
            f"Position : {pos.name}",
            f"ID : {pos.id}",
            f"Catégorie : {pos.category}",
            f"Créée : {pos.created_at}",
            f"Modifiée : {pos.modified_at}",
            "",
            "Valeurs moteurs :",
        ]
        for mid in sorted(pos.positions.keys()):
            lines.append(f"  Moteur {mid} : {pos.positions[mid]}")
        if pos.meta:
            lines.append(f"\nMétadonnées : {pos.meta}")
        self._detail_label.config(text="\n".join(lines))

    def _show_suite_detail(self, suite_id: str) -> None:
        suite = library.get_suite(suite_id)
        if not suite:
            return
        lines = [
            f"Suite : {suite.name}",
            f"ID : {suite.id}",
            f"Créée : {suite.created_at}",
            f"Étapes : {len(suite.steps)}",
            "",
        ]
        for i, step in enumerate(suite.steps, 1):
            pname = step.get("position_name", step.get("position_id", "?"))
            dur = step.get("duration_s", "?")
            lines.append(f"  {i}. {pname} (durée: {dur}s)")
        self._detail_label.config(text="\n".join(lines))

    def _show_scenario_detail(self, scen_id: str) -> None:
        scen = library.get_scenario(scen_id)
        if not scen:
            return
        lines = [
            f"Scénario : {scen.name}",
            f"ID : {scen.id}",
            f"Suites liées : {len(scen.suite_ids)}",
            f"Triggers : {len(scen.triggers)}",
        ]
        self._detail_label.config(text="\n".join(lines))

    def _show_profile_detail(self, prof_id: str) -> None:
        prof = library.get_motion_profile(prof_id)
        if not prof:
            return
        lines = [
            f"Profil : {prof.name}",
            f"Hertz : {prof.smooth_hz}",
            f"Vélocité : {prof.comfort_vel}",
            f"Accélération : {prof.comfort_acc}",
            f"Durée home : {prof.home_duration}s",
        ]
        self._detail_label.config(text="\n".join(lines))

    def _show_robot_detail(self, robot_id: str) -> None:
        robot = library.get_robot(robot_id)
        if not robot:
            return
        lines = [
            f"Robot : {robot.robot_id}",
            f"Port : {robot.port or '(non défini)'}",
            f"Baudrate : {robot.baud}",
            f"Moteurs : {robot.motor_ids}",
            "",
            "Home machine :",
        ]
        for mid in sorted(robot.home_machine.keys()):
            lines.append(f"  Moteur {mid} : {robot.home_machine[mid]}")
        lines.append("\nHome travail :")
        for mid in sorted(robot.home_work.keys()):
            lines.append(f"  Moteur {mid} : {robot.home_work[mid]}")
        lines.append(f"\nParamètres mouvement : {robot.motion_params}")
        self._detail_label.config(text="\n".join(lines))

    # ── Actions CRUD ──────────────────────────────────────────────

    def _selected_info(self) -> tuple:
        """Retourne (kind, obj_id) de l'élément sélectionné."""
        sel = self._tree.selection()
        if not sel:
            return ("", "")
        tags = self._tree.item(sel[0], "tags")
        if not tags:
            return ("", "")
        return (tags[0], tags[1] if len(tags) > 1 else "")

    def _on_new(self) -> None:
        """Crée un nouvel élément selon le contexte."""
        kind, _ = self._selected_info()
        if kind in ("position", "subcategory"):
            self._new_position()
        elif kind == "suite":
            self._new_suite()
        elif kind == "profile":
            self._new_profile()
        else:
            messagebox.showinfo("Nouveau",
                                "Sélectionnez une catégorie d'abord.",
                                parent=self)

    def _on_edit(self) -> None:
        """Modifie l'élément sélectionné."""
        kind, obj_id = self._selected_info()
        if kind == "position":
            self._edit_position(obj_id)
        elif kind == "suite":
            self._edit_suite(obj_id)
        else:
            messagebox.showinfo("Modifier",
                                "Sélectionnez un élément à modifier.",
                                parent=self)

    def _on_delete(self) -> None:
        """Supprime l'élément sélectionné."""
        kind, obj_id = self._selected_info()
        if not obj_id:
            return
        name = self._tree.item(self._tree.selection()[0], "text").strip()
        if not messagebox.askyesno("Supprimer",
                                   f"Supprimer '{name}' ?",
                                   parent=self):
            return

        if kind == "position":
            ok, msg = library.delete_position(obj_id)
            if not ok:
                messagebox.showerror("Supprimer", msg, parent=self)
                return
        elif kind == "suite":
            library.delete_suite(obj_id)
        elif kind == "scenario":
            library.delete_scenario(obj_id)
        elif kind == "profile":
            library.delete_motion_profile(obj_id)

        self._refresh_tree()
        bus.publish("library.changed", {"action": "delete", "kind": kind})

    # ── Création ──────────────────────────────────────────────────

    def _new_position(self) -> None:
        """Dialogue de création d'une position."""
        name = simpledialog.askstring("Nouvelle position", "Nom :",
                                      parent=self)
        if not name:
            return

        # Déterminer la catégorie depuis la sélection
        sel = self._tree.selection()
        category = "sauvegardees"
        if sel:
            tags = self._tree.item(sel[0], "tags")
            if len(tags) > 1 and tags[1] in ("machine_initiales", "travail", "sauvegardees"):
                category = tags[1]

        # Lire les positions courantes du robot actif
        positions = {}
        try:
            from xrv22.robots.robot_registry import registry
            for rid in registry.ids():
                ctrl = registry.get(rid)
                if ctrl and ctrl.is_connected:
                    positions = ctrl.read_positions()
                    break
        except Exception as exc:
            _LOG.debug("Lecture positions échouée pour nouvelle position: %s", exc)

        if not positions:
            positions = {i: 2048 for i in range(1, 8)}

        pos = PositionModel(name=name, category=category, positions=positions)
        library.save_position(pos)
        self._refresh_tree()
        bus.publish("library.changed", {"action": "create", "kind": "position"})

    def _new_suite(self) -> None:
        name = simpledialog.askstring("Nouvelle suite", "Nom :",
                                      parent=self)
        if not name:
            return
        suite = SuiteModel(name=name, steps=[])
        library.save_suite(suite)
        self._refresh_tree()
        bus.publish("library.changed", {"action": "create", "kind": "suite"})

    def _new_profile(self) -> None:
        name = simpledialog.askstring("Nouveau profil", "Nom :",
                                      parent=self)
        if not name:
            return
        prof = MotionProfileModel(name=name)
        library.save_motion_profile(prof)
        self._refresh_tree()

    # ── Édition ───────────────────────────────────────────────────

    def _edit_position(self, pos_id: str) -> None:
        pos = library.get_position(pos_id)
        if not pos:
            return
        new_name = simpledialog.askstring("Renommer", "Nouveau nom :",
                                          initialvalue=pos.name,
                                          parent=self)
        if new_name and new_name != pos.name:
            library.rename_position(pos_id, new_name)
            self._refresh_tree()

    def _edit_suite(self, suite_id: str) -> None:
        suite = library.get_suite(suite_id)
        if not suite:
            return
        new_name = simpledialog.askstring("Renommer", "Nouveau nom :",
                                          initialvalue=suite.name,
                                          parent=self)
        if new_name and new_name != suite.name:
            suite.name = new_name
            library.save_suite(suite)
            self._refresh_tree()
