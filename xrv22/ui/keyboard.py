"""
xr200/ui/keyboard.py  — V22
─────────────────────────────
Gestion centralisée clavier, focus et tooltips.

Fournit :
  - ShortcutRegistry : registre global des raccourcis avec aide
  - Tooltip          : infobulle au survol
  - setup_focus_style: style focus ring ttk
  - setup_tab_nav    : navigation onglets Ctrl+Tab
  - show_shortcuts_dialog : popup liste raccourcis

CC max : 10 par méthode.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

from xrv22.theme import theme as T


# ══════════════════════════════════════════════════════════════════
# Registre centralisé des raccourcis
# ══════════════════════════════════════════════════════════════════

class _Shortcut:
    __slots__ = ("key", "label", "category", "callback")

    def __init__(self, key: str, label: str, category: str,
                 callback: Callable) -> None:
        self.key = key
        self.label = label
        self.category = category
        self.callback = callback


class ShortcutRegistry:
    """Registre unique de raccourcis. CC max : 5."""

    def __init__(self) -> None:
        self._shortcuts: List[_Shortcut] = []
        self._bound_root: Optional[tk.Tk] = None

    def register(self, key: str, label: str, category: str,
                 callback: Callable) -> None:
        """Enregistre un raccourci (ne le bind pas encore)."""
        self._shortcuts.append(_Shortcut(key, label, category, callback))

    def bind_all(self, root: tk.Tk) -> None:
        """CC=3 — Bind tous les raccourcis enregistrés sur root."""
        self._bound_root = root
        for sc in self._shortcuts:
            root.bind(sc.key, lambda e, cb=sc.callback: cb())

    def grouped(self) -> Dict[str, List[Tuple[str, str]]]:
        """Retourne {catégorie: [(touche, label), ...]}."""
        out: Dict[str, List[Tuple[str, str]]] = {}
        for sc in self._shortcuts:
            out.setdefault(sc.category, []).append(
                (_format_key(sc.key), sc.label))
        return out


# Singleton
shortcuts = ShortcutRegistry()


def _format_key(tk_key: str) -> str:
    """CC=4 — Convertit <Control-s> → Ctrl+S pour affichage."""
    k = tk_key.strip("<>")
    parts = k.split("-")
    mapped = []
    for p in parts:
        if p == "Control":
            mapped.append("Ctrl")
        elif p == "Shift":
            mapped.append("Maj")
        elif p == "space":
            mapped.append("Espace")
        elif p == "Escape":
            mapped.append("Échap")
        elif p == "Delete":
            mapped.append("Suppr")
        elif p == "Return":
            mapped.append("Entrée")
        elif p == "F2":
            mapped.append("F2")
        else:
            mapped.append(p.upper() if len(p) == 1 else p)
    return "+".join(mapped)


# ══════════════════════════════════════════════════════════════════
# Tooltip
# ══════════════════════════════════════════════════════════════════

class Tooltip:
    """Infobulle simple au survol. CC max : 4."""

    _active: Optional["Tooltip"] = None

    def __init__(self, widget: tk.Widget, text: str,
                 delay_ms: int = 500) -> None:
        self._widget = widget
        self._text = text
        self._delay = delay_ms
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event: tk.Event) -> None:
        self._cancel()
        self._after_id = self._widget.after(self._delay, self._show)

    def _show(self) -> None:
        if Tooltip._active and Tooltip._active is not self:
            Tooltip._active._hide()
        x = self._widget.winfo_rootx() + 10
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(self._tip, text=self._text,
                       bg=T.SURFACE_HI, fg=T.TEXT,
                       font=T.F_CAPTION, padx=8, pady=4,
                       relief="solid", borderwidth=1)
        lbl.pack()
        Tooltip._active = self

    def _hide(self, _event: tk.Event = None) -> None:
        self._cancel()
        if self._tip:
            self._tip.destroy()
            self._tip = None
        if Tooltip._active is self:
            Tooltip._active = None

    def _cancel(self) -> None:
        if self._after_id:
            self._widget.after_cancel(self._after_id)
            self._after_id = None


def tooltip(widget: tk.Widget, text: str) -> Tooltip:
    """Factory raccourcie pour ajouter un tooltip."""
    return Tooltip(widget, text)


# ══════════════════════════════════════════════════════════════════
# Focus ring (style ttk)
# ══════════════════════════════════════════════════════════════════

FOCUS_COLOR = T.C_AMB


def setup_focus_style(root: tk.Tk) -> None:
    """CC=2 — Configure le style focus ring pour ttk widgets."""
    style = ttk.Style(root)
    # Bordure focus visible sur les boutons ttk
    style.configure("TButton", focuscolor=FOCUS_COLOR)
    style.configure("TEntry", focuscolor=FOCUS_COLOR)
    style.configure("TCombobox", focuscolor=FOCUS_COLOR)
    style.configure("TSpinbox", focuscolor=FOCUS_COLOR)

    # Highlight focus sur tk widgets standard
    root.option_add("*highlightColor", FOCUS_COLOR)
    root.option_add("*insertBackground", T.C_AMB)


# ══════════════════════════════════════════════════════════════════
# Navigation onglets (Ctrl+Tab / Ctrl+Shift+Tab)
# ══════════════════════════════════════════════════════════════════

def setup_tab_navigation(root: tk.Tk, notebook: ttk.Notebook) -> None:
    """CC=4 — Ctrl+Tab / Ctrl+Shift+Tab pour naviguer entre onglets."""

    def _next_tab() -> None:
        n = notebook.index("end")
        if n < 2:
            return
        cur = notebook.index("current")
        notebook.select((cur + 1) % n)

    def _prev_tab() -> None:
        n = notebook.index("end")
        if n < 2:
            return
        cur = notebook.index("current")
        notebook.select((cur - 1) % n)

    root.bind("<Control-Tab>", lambda e: _next_tab())
    root.bind("<Control-Shift-Tab>", lambda e: _prev_tab())
    # macOS : Command key
    root.bind("<Command-Tab>", lambda e: _next_tab())
    root.bind("<Command-Shift-Tab>", lambda e: _prev_tab())

    shortcuts.register("<Control-Tab>", "Onglet suivant", "Navigation",
                       _next_tab)
    shortcuts.register("<Control-Shift-Tab>", "Onglet précédent", "Navigation",
                       _prev_tab)


# ══════════════════════════════════════════════════════════════════
# Dialog raccourcis clavier
# ══════════════════════════════════════════════════════════════════

def show_shortcuts_dialog(parent: tk.Widget) -> None:
    """CC=5 — Affiche la liste des raccourcis dans un dialog."""
    dlg = tk.Toplevel(parent)
    dlg.title("Raccourcis clavier — XR200 Pro")
    dlg.configure(bg=T.BG)
    dlg.resizable(False, False)
    dlg.transient(parent)
    dlg.grab_set()
    dlg.geometry("420x520")

    tk.Label(dlg, text="⌨  Raccourcis clavier",
             bg=T.BG, fg=T.C_AMB, font=T.F_TITLE
             ).pack(pady=(T.PAD_MD, T.PAD_SM))

    frame = tk.Frame(dlg, bg=T.BG)
    frame.pack(fill="both", expand=True, padx=T.PAD_LG, pady=T.PAD_SM)

    groups = shortcuts.grouped()
    for cat, items in groups.items():
        tk.Label(frame, text=cat, bg=T.BG, fg=T.C_MAG_2,
                 font=T.F_SECTION).pack(anchor="w", pady=(T.PAD_SM, 2))
        for key_str, desc in items:
            row = tk.Frame(frame, bg=T.BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=key_str, bg=T.SURFACE, fg=T.C_AMB,
                     font=T.F_MONO_SM, width=18, anchor="w",
                     padx=6, pady=2).pack(side="left", padx=(0, T.PAD_SM))
            tk.Label(row, text=desc, bg=T.BG, fg=T.TEXT,
                     font=T.F_CONTROL, anchor="w").pack(side="left")

    ttk.Button(dlg, text="Fermer",
               command=dlg.destroy).pack(pady=T.PAD_MD)
    dlg.bind("<Escape>", lambda e: dlg.destroy())
    dlg.focus_set()


# ══════════════════════════════════════════════════════════════════
# Helpers Delete / F2 pour Treeview
# ══════════════════════════════════════════════════════════════════

def bind_treeview_keys(tree: ttk.Treeview,
                       on_delete: Optional[Callable] = None,
                       on_edit: Optional[Callable] = None) -> None:
    """CC=4 — Bind Delete et F2 sur un Treeview."""
    if on_delete:
        tree.bind("<Delete>", lambda e: _tree_action(tree, on_delete))
        tree.bind("<BackSpace>", lambda e: _tree_action(tree, on_delete))
    if on_edit:
        tree.bind("<Return>", lambda e: _tree_action(tree, on_edit))
        tree.bind("<F2>", lambda e: _tree_action(tree, on_edit))


def _tree_action(tree: ttk.Treeview, callback: Callable) -> None:
    """CC=2 — Exécute callback si un item est sélectionné."""
    sel = tree.selection()
    if sel:
        callback()
