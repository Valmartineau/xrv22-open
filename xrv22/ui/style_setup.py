"""
xr200/ui/style_setup.py
────────────────────────
Configuration du style ttk global.
Appelé une seule fois au démarrage de la MainWindow.

Toutes les couleurs proviennent de theme/theme.py.
Aucune couleur codée en dur ici.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from xrv22.theme import theme as T


def setup_styles(root: tk.Tk) -> ttk.Style:
    """CC=6 — Configure tous les styles ttk. Retourne le Style object."""
    style = ttk.Style(root)
    style.theme_use("clam")

    _setup_base(style)
    _setup_treeview(style)
    _setup_combobox(style)
    _setup_notebook(style)
    _setup_buttons(style)
    _setup_entry(style)
    _setup_scrollbar(style)
    _setup_separator(style)
    _setup_labelframe(style)
    _setup_checkbutton(style)
    _setup_spinbox(style)
    _setup_scale(style)
    _setup_progressbar(style)
    _setup_menus(root)
    return style


def _setup_base(s: ttk.Style) -> None:
    """CC=2 — Styles de base (thème clam, coins arrondis natifs)."""
    s.configure(".",
        font=(*T.F_LABEL,),
        background=T.BG,
        foreground=T.TEXT,
        borderwidth=2,
        bordercolor=T.BORDER,
        darkcolor=T.BORDER,
        lightcolor=T.BORDER,
        relief="flat",
        troughcolor=T.SURFACE,
        fieldbackground=T.SURFACE,
        focuscolor=T.C_MAG,
        insertcolor=T.C_AMB,
    )
    s.configure("TFrame", background=T.BG, borderwidth=0)
    s.configure("TLabel", background=T.BG, borderwidth=0)
    s.configure("TPanedwindow", background=T.BG)


def _setup_treeview(s: ttk.Style) -> None:
    """CC=2 — Treeview dark avec fond sombre et sélection magenta."""
    s.configure("Treeview",
        background=T.SURFACE,
        foreground=T.TEXT,
        fieldbackground=T.SURFACE,
        bordercolor=T.BORDER_HI,
        lightcolor=T.BORDER,
        darkcolor=T.BORDER,
        borderwidth=2,
        relief="flat",
        rowheight=34,
        font=(*T.F_CONTROL,),
    )
    s.map("Treeview",
        background=[("selected", T.C_MAG_DIM2)],
        foreground=[("selected", T.C_AMB)],
    )
    s.configure("Treeview.Heading",
        background=T.SURFACE_HI,
        foreground=T.TEXT_MED,
        bordercolor=T.BORDER,
        lightcolor=T.BORDER,
        darkcolor=T.BORDER,
        borderwidth=1,
        relief="flat",
        font=(*T.F_CAPTION,),
        padding=[8, 6],
    )
    s.map("Treeview.Heading",
        background=[("active", T.SURFACE_HI)],
    )


def _setup_combobox(s: ttk.Style) -> None:
    """CC=2 — Combobox dark."""
    s.configure("TCombobox",
        fieldbackground=T.SURFACE,
        background=T.SURFACE_HI,
        foreground=T.TEXT,
        selectbackground=T.C_MAG_DIM2,
        selectforeground=T.C_AMB,
        arrowcolor=T.C_MAG_2,
        bordercolor=T.BORDER_HI,
        lightcolor=T.BORDER,
        darkcolor=T.BORDER,
        borderwidth=2,
        padding=[8, 5],
    )
    s.map("TCombobox",
        fieldbackground=[("focus", T.SURFACE_HI)],
        bordercolor=[("focus", T.C_MAG_2)],
    )


def _setup_notebook(s: ttk.Style) -> None:
    """CC=3 — Notebook dark avec onglets aux coins arrondis (clam)."""
    s.configure("TNotebook",
        background=T.BG,
        bordercolor=T.BORDER_HI,
        darkcolor=T.BORDER,
        lightcolor=T.BORDER,
        borderwidth=3,
        tabmargins=[8, 8, 8, 0],
        padding=[8, 8],
    )
    # Layout custom avec coins arrondis en haut
    s.element_create("Round.tab", "from", "clam")
    s.layout("TNotebook.Tab", [
        ("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""})
            ]})
        ]})
    ])
    s.configure("TNotebook.Tab",
        background=T.SURFACE,
        foreground=T.TEXT_MED,
        bordercolor=T.BORDER_HI,
        darkcolor=T.BORDER,
        lightcolor=T.SURFACE,
        padding=[20, 10],
        font=(*T.F_CONTROL,),
        borderwidth=3,
    )
    s.map("TNotebook.Tab",
        background=[("selected", T.SURFACE_HI), ("active", T.SURFACE_HI)],
        foreground=[("selected", T.TEXT), ("active", T.TEXT)],
        lightcolor=[("selected", T.SURFACE_HI), ("active", T.SURFACE_HI)],
        bordercolor=[("selected", T.C_MAG), ("active", T.BORDER_HI)],
    )
    # Panneau de contenu du notebook — bordure arrondie
    s.configure("TNotebook.Pane",
        bordercolor=T.BORDER_HI,
        borderwidth=3,
    )


def _setup_buttons(s: ttk.Style) -> None:
    """CC=2 — Boutons dark avec bordures arrondies (clam)."""
    s.configure("TButton",
        background=T.SURFACE_HI,
        foreground=T.TEXT,
        bordercolor=T.BORDER_HI,
        darkcolor=T.BORDER,
        lightcolor=T.BORDER_HI,
        padding=[14, 7],
        borderwidth=2,
        font=(*T.F_CONTROL,),
    )
    s.map("TButton",
        background=[("active", T.C_MAG_DIM2), ("pressed", T.C_MAG)],
        foreground=[("active", T.C_AMB)],
        bordercolor=[("active", T.C_MAG)],
    )

    # Bouton accentué
    s.configure("Accent.TButton",
        background=T.C_MAG,
        foreground=T.TEXT,
        bordercolor=T.C_MAG,
    )
    s.map("Accent.TButton",
        background=[("active", T.C_MAG_2), ("pressed", T.C_MAG_2)],
    )

    # Bouton danger (E-STOP)
    s.configure("Danger.TButton",
        background=T.C_ERR_DIM,
        foreground=T.C_ERR,
        bordercolor=T.C_ERR_DEEP,
        font=(*T.F_SECTION,),
    )
    s.map("Danger.TButton",
        background=[("active", T.C_ERR_DEEP), ("pressed", T.C_ERR_DEEP)],
        foreground=[("active", "#ff6b6b")],
    )


def _setup_entry(s: ttk.Style) -> None:
    """CC=2 — Entry dark."""
    s.configure("TEntry",
        fieldbackground=T.SURFACE,
        foreground=T.TEXT,
        insertcolor=T.C_AMB,
        bordercolor=T.BORDER_HI,
        lightcolor=T.BORDER,
        darkcolor=T.BORDER,
        borderwidth=2,
        padding=[8, 5],
    )
    s.map("TEntry",
        fieldbackground=[("focus", T.SURFACE_HI)],
        bordercolor=[("focus", T.C_MAG_2)],
    )


def _setup_scrollbar(s: ttk.Style) -> None:
    """CC=2 — Scrollbar discrète."""
    s.configure("TScrollbar",
        background=T.SURFACE_HI,
        troughcolor=T.BG_DEEP,
        arrowcolor=T.TEXT_DIM,
        borderwidth=0,
        relief="flat",
        width=12,
    )
    s.map("TScrollbar",
        background=[("active", T.C_MAG_DIM2)],
    )


def _setup_separator(s: ttk.Style) -> None:
    """CC=1 — Séparateur."""
    s.configure("TSeparator", background=T.BORDER)


def _setup_labelframe(s: ttk.Style) -> None:
    """CC=1 — LabelFrame dark avec bordure arrondie (clam)."""
    s.configure("TLabelframe",
        background=T.BG,
        foreground=T.TEXT,
        bordercolor=T.BORDER_HI,
        darkcolor=T.BORDER,
        lightcolor=T.BORDER,
        borderwidth=2,
        relief="groove",
    )
    s.configure("TLabelframe.Label",
        background=T.BG,
        foreground=T.TEXT_MED,
        font=(*T.F_CAPTION,),
    )


def _setup_checkbutton(s: ttk.Style) -> None:
    """CC=1 — Checkbutton dark."""
    s.configure("TCheckbutton",
        background=T.BG,
        foreground=T.TEXT,
        indicatorbackground=T.SURFACE,
        indicatorforeground=T.C_AMB,
        font=(*T.F_CONTROL,),
    )
    s.map("TCheckbutton",
        background=[("active", T.BG)],
        foreground=[("active", T.C_AMB)],
        indicatorbackground=[("selected", T.C_MAG_DIM2)],
    )


def _setup_spinbox(s: ttk.Style) -> None:
    """CC=1 — Spinbox dark."""
    s.configure("TSpinbox",
        fieldbackground=T.SURFACE,
        background=T.SURFACE_HI,
        foreground=T.TEXT,
        arrowcolor=T.TEXT_MED,
        borderwidth=2,
        relief="flat",
    )
    s.map("TSpinbox",
        fieldbackground=[("focus", T.SURFACE_HI)],
        bordercolor=[("focus", T.C_MAG)],
    )


def _setup_scale(s: ttk.Style) -> None:
    """CC=1 — Scale dark."""
    s.configure("TScale",
        background=T.BG,
        troughcolor=T.SURFACE,
        sliderrelief="flat",
        borderwidth=0,
    )
    s.configure("Horizontal.TScale",
        sliderthickness=18,
    )


def _setup_progressbar(s: ttk.Style) -> None:
    """CC=1 — Progressbar dark."""
    s.configure("TProgressbar",
        background=T.C_MAG,
        troughcolor=T.SURFACE,
        borderwidth=0,
        relief="flat",
    )


def _setup_menus(root: tk.Tk) -> None:
    """CC=2 — Widgets tk natifs : menus, listbox, labelframe, etc."""
    # Combobox dropdown
    root.option_add("*TCombobox*Listbox.background",         T.SURFACE)
    root.option_add("*TCombobox*Listbox.foreground",         T.TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground",   T.C_MAG_DIM2)
    root.option_add("*TCombobox*Listbox.selectForeground",   T.C_AMB)
    root.option_add("*TCombobox*Listbox.font",               f"{{{T.FONT_UI}}} 11")
    root.option_add("*TCombobox*Listbox.relief",             "flat")
    root.option_add("*TCombobox*Listbox.borderwidth",        "0")

    # Menus
    root.option_add("*Menu.background",       T.SURFACE)
    root.option_add("*Menu.foreground",       T.TEXT)
    root.option_add("*Menu.activeBackground", T.C_MAG_DIM2)
    root.option_add("*Menu.activeForeground", T.C_AMB)
    root.option_add("*Menu.font",             f"{{{T.FONT_UI}}} 11")
    root.option_add("*Menu.relief",           "flat")
    root.option_add("*Menu.tearOff",          "0")
    root.option_add("*Menu.selectColor",      T.C_MAG)

    # Listbox globales — fond sombre, sélection magenta
    root.option_add("*Listbox.background",         T.SURFACE)
    root.option_add("*Listbox.foreground",         T.TEXT)
    root.option_add("*Listbox.selectBackground",   T.C_MAG_DIM2)
    root.option_add("*Listbox.selectForeground",   T.C_AMB)
    root.option_add("*Listbox.relief",             "flat")
    root.option_add("*Listbox.borderWidth",        "0")
    root.option_add("*Listbox.highlightThickness", "0")

    # tk.LabelFrame — fond et texte sombres
    root.option_add("*Labelframe.background",          T.BG)
    root.option_add("*Labelframe.foreground",          T.TEXT_MED)

    # tk.Entry — fond sombre
    root.option_add("*Entry.background",           T.SURFACE)
    root.option_add("*Entry.foreground",           T.TEXT)
    root.option_add("*Entry.insertBackground",     T.C_AMB)
    root.option_add("*Entry.highlightThickness",   "0")
    root.option_add("*Entry.relief",               "flat")

    # tk.Spinbox — fond sombre
    root.option_add("*Spinbox.background",         T.SURFACE)
    root.option_add("*Spinbox.foreground",         T.TEXT)
    root.option_add("*Spinbox.buttonBackground",   T.SURFACE_HI)
    root.option_add("*Spinbox.insertBackground",   T.C_AMB)
    root.option_add("*Spinbox.relief",             "flat")
    root.option_add("*Spinbox.highlightThickness", "0")
