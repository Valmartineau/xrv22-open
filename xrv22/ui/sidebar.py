"""
xr200/ui/sidebar.py  — V21
Corrections :
  - _refresh_list() : icônes d'état complètes (🟢🔵🔴🛑🟡⚪)
  - _on_select() : publie ui.active_robot_changed
  - _subscribe() : abonné à robot.state_changed
  - _add_robot() / _remove_robot() : publient ui.active_robot_changed
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import simpledialog, messagebox
from typing import Callable, Optional

from xrv22.theme import theme as T
from xrv22.ui.widgets import RoundedFrame
from xrv22.ui.i18n import (
    APP_VERSION, APP_SUBTITLE,
    SB_ROBOTS, SB_BTN_AJOUTER, SB_BTN_RETIRER, SB_DECONNECTE,
    SB_COMMANDES, SB_CONNECTER_TOUS, SB_DEVERROUILLER, SB_VERROUILLER,
    SB_POS_TRAVAIL, SB_POS_MACHINE, SB_STOP_DOUX, SB_STOP_URGENCE,
    SB_STATUT,
    BADGE_POS_MACHINE, BADGE_POS_TRAVAIL, BADGE_CAPTEURS,
    MSG_ROBOT_DERNIER,
)
from xrv22.robots.robot_registry import registry
from xrv22.core.state_store import store
from xrv22.core.safety_manager import safety
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger
from xrv22.library.library_manager import library

_LOG = get_logger("XR200.Sidebar")

SIDEBAR_W = 252

# Mapping état → icône (identique à V17)
_STATE_ICON = {
    "IDLE":           "🟢",
    "READY":          "🟢",
    "RUNNING":        "🔵",
    "PAUSED":         "⏸",
    "SOFT_STOP":      "🟡",
    "COMM_LOST":      "🔶",
    "ERROR":          "🔴",
    "EMERGENCY_STOP": "🛑",
    "LOCKED":         "🔒",
    "TORQUE_OFF":     "🟡",
    "CONNECTING":     "🔶",
    "DISCONNECTED":   "⚪",
}

_STATE_COLOR = {
    "IDLE":           "#39d353",
    "READY":          "#39d353",
    "RUNNING":        "#00d2e6",
    "PAUSED":         "#ffb347",
    "SOFT_STOP":      "#ffb347",
    "COMM_LOST":      "#ffb347",
    "ERROR":          "#ff4757",
    "EMERGENCY_STOP": "#ff4757",
    "LOCKED":         "#ffb347",
    "TORQUE_OFF":     "#ffb347",
    "CONNECTING":     "#ffb347",
    "DISCONNECTED":   "#4a5568",
}


_STATE_LABEL_FR = {
    "IDLE":           "Prêt",
    "READY":          "Prêt",
    "RUNNING":        "En mouvement",
    "PAUSED":         "En pause",
    "SOFT_STOP":      "Arrêt doux",
    "COMM_LOST":      "Liaison perdue",
    "ERROR":          "Erreur",
    "EMERGENCY_STOP": "E-STOP",
    "LOCKED":         "Verrouillé",
    "TORQUE_OFF":     "Torque OFF",
    "DISCONNECTED":   "Déconnecté",
}


class Sidebar(tk.Frame):
    """CC=8 — Panneau latéral gauche complet."""

    def __init__(self, parent: tk.Widget,
                 on_stop_soft: Callable,
                 on_estop: Callable) -> None:
        super().__init__(parent, bg=T.BG_DEEP, width=SIDEBAR_W,
                         highlightbackground=T.TEXT_DIM,
                         highlightthickness=1)
        self.pack_propagate(False)
        self._on_stop_soft = on_stop_soft
        self._on_estop     = on_estop
        self._active_id: str = ""
        self._refresh_pending = False

        self._build()
        self._subscribe()
        self._refresh_list()
        self._start_poll()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        tk.Frame(self, bg=T.C_MAG, width=3).pack(side="left", fill="y")
        inner = tk.Frame(self, bg=T.BG_DEEP)
        inner.pack(side="left", fill="both", expand=True)

        self._build_logo(inner)
        self._sep(inner)
        self._build_robots(inner)
        self._sep(inner)
        self._build_commands(inner)
        self._sep(inner)
        self._build_status(inner)

        # ── Bas de sidebar : projet + version ──
        tk.Frame(inner, bg=T.TEXT_DIM, height=1).pack(fill="x", padx=12, side="bottom", pady=(6, 0))
        tk.Label(inner, text=f"{APP_VERSION}  ·  XR200 Pro",
                 bg=T.BG_DEEP, fg=T.TEXT_DIM,
                 font=T.F_MONO_SM).pack(side="bottom", pady=8)
    def _sep(self, parent: tk.Widget) -> None:
        tk.Frame(parent, bg=T.TEXT_DIM, height=1).pack(fill="x", padx=12, pady=5)

    # ── Logo ──────────────────────────────────────────────────────────────────

    def _build_logo(self, parent: tk.Widget) -> None:
        f = tk.Frame(parent, bg=T.BG_DEEP)
        f.pack(fill="x", padx=16, pady=(20, 8))
        tk.Label(f, text="XR200", bg=T.BG_DEEP, fg=T.TEXT, font=T.F_DISPLAY).pack(anchor="w")
        tk.Label(f, text=APP_SUBTITLE, bg=T.BG_DEEP, fg=T.TEXT_DIM, font=T.F_CAPTION).pack(anchor="w", pady=(2, 0))

    # ── Robots ────────────────────────────────────────────────────────────────

    def _build_robots(self, parent: tk.Widget) -> None:
        tk.Label(parent, text=SB_ROBOTS, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                 font=T.F_CAPTION).pack(anchor="w", padx=16, pady=(4, 4))

        # Conteneur des cartes robots (remplace la Listbox)
        self._robot_cards_frame = tk.Frame(parent, bg=T.BG_DEEP)
        self._robot_cards_frame.pack(fill="x", padx=10, pady=(0, 2))
        self._robot_cards: list = []  # liste de {frame, rid, ...}

        rb = tk.Frame(parent, bg=T.BG_DEEP)
        rb.pack(fill="x", padx=12, pady=(3, 0))
        rb.columnconfigure(0, weight=1, uniform="rb")
        rb.columnconfigure(1, weight=1, uniform="rb")
        # Ligne 1 : Ajouter + Retirer
        self._rounded_btn(rb, "＋ Ajouter", self._add_robot, "#2a9d5c").grid(
            row=0, column=0, sticky="ew", padx=2, pady=2)
        self._rounded_btn(rb, "✕ Retirer", self._remove_robot, "#b83248").grid(
            row=0, column=1, sticky="ew", padx=2, pady=2)
        # Ligne 2 : ALL CO. + Synchro
        self._rounded_btn(rb, "🔌 ALL CO.", self._all_connect, "#c4820f").grid(
            row=1, column=0, sticky="ew", padx=2, pady=2)
        self._rounded_btn(rb, "🔗 Synchro", self._open_sync_dialog, T.C_INFO).grid(
            row=1, column=1, sticky="ew", padx=2, pady=2)

        # Labels statut fantômes (gardés pour compatibilité API mais masqués)
        self._robot_status_lbl = tk.Label(parent, text="", bg=T.BG_DEEP)
        self._robot_name_lbl = tk.Label(parent, text="", bg=T.BG_DEEP)
        self._robot_port_lbl = tk.Label(parent, text="", bg=T.BG_DEEP)

    # ── Commandes (pills) ─────────────────────────────────────────────────────

    def _build_commands(self, parent: tk.Widget) -> None:
        GRAD = [
            (T.C_MAG,   T.C_AMB),
            ("#4a1060", T.C_MAG),
            ("#0e0a1e", T.C_MAG),
            ("#0e2a18", T.C_OK),
            ("#3a1e04", T.C_AMB),
            ("#5c2010", T.C_AMB),
        ]

        # ── Section ÉTAT ──
        tk.Label(parent, text="É T A T", bg=T.BG_DEEP, fg=T.TEXT_DIM,
                 font=T.F_CAPTION).pack(anchor="w", padx=16, pady=(4, 4))
        self._torque_pill = self._build_torque_pill(parent)

        self._sep(parent)

        # ── Section COMMANDES ──
        tk.Label(parent, text=SB_COMMANDES, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                 font=T.F_CAPTION).pack(anchor="w", padx=16, pady=(4, 4))

        pills = [
            (SB_DEVERROUILLER,  self._all_unlock,     GRAD[1]),
            (SB_VERROUILLER,    self._all_lock,       GRAD[2]),
        ]
        for txt, cmd, (gl, gr) in pills:
            self._pill(parent, txt, cmd, gl, gr)

        tk.Frame(parent, bg=T.TEXT_DIM, height=1).pack(fill="x", padx=14, pady=3)

        for txt, cmd, (gl, gr) in [
            (SB_POS_TRAVAIL, self._all_goto_work,    GRAD[3]),
            (SB_POS_MACHINE, self._all_goto_machine, GRAD[4]),
        ]:
            self._pill(parent, txt, cmd, gl, gr)

        tk.Frame(parent, bg=T.TEXT_DIM, height=1).pack(fill="x", padx=14, pady=3)

        self._pill(parent, SB_STOP_DOUX, self._on_stop_soft, GRAD[5][0], GRAD[5][1])

        tk.Frame(parent, bg=T.TEXT_DIM, height=1).pack(fill="x", padx=14, pady=3)
        self._pill(parent,
                   f"🛑  {SB_STOP_URGENCE}",
                   self._on_estop,
                   "#7a0c0c",
                   "#c0392b")

    def _rounded_btn(self, parent: tk.Widget, text: str,
                     cmd: Callable, fg: str) -> tk.Canvas:
        """CC=4 — Petit bouton Canvas avec rectangle arrondi."""
        h = 28
        r = 12  # rayon des coins
        bg_n = T.SURFACE_HI
        bg_h = T.SURFACE

        cvs = tk.Canvas(parent, height=h, bg=T.BG_DEEP,
                        highlightthickness=0, bd=0, cursor="hand2")

        def _draw(event=None):
            w = cvs.winfo_width()
            if w < 10:
                return
            cvs.delete("all")
            # Rectangle arrondi (fond normal)
            cvs.create_arc(0, 0, 2 * r, 2 * r,
                           start=90, extent=90, fill=bg_n, outline="")
            cvs.create_arc(w - 2 * r, 0, w, 2 * r,
                           start=0, extent=90, fill=bg_n, outline="")
            cvs.create_arc(0, h - 2 * r, 2 * r, h,
                           start=180, extent=90, fill=bg_n, outline="")
            cvs.create_arc(w - 2 * r, h - 2 * r, w, h,
                           start=270, extent=90, fill=bg_n, outline="")
            cvs.create_rectangle(r, 0, w - r, h, fill=bg_n, outline="")
            cvs.create_rectangle(0, r, w, h - r, fill=bg_n, outline="")
            # Texte centré
            cvs.create_text(w // 2, h // 2, text=text,
                            fill=fg, font=T.F_CAPTION, anchor="center")

        def _enter(_e):
            w = cvs.winfo_width()
            if w < 10:
                return
            cvs.delete("all")
            cvs.create_arc(0, 0, 2 * r, 2 * r,
                           start=90, extent=90, fill=bg_h, outline="")
            cvs.create_arc(w - 2 * r, 0, w, 2 * r,
                           start=0, extent=90, fill=bg_h, outline="")
            cvs.create_arc(0, h - 2 * r, 2 * r, h,
                           start=180, extent=90, fill=bg_h, outline="")
            cvs.create_arc(w - 2 * r, h - 2 * r, w, h,
                           start=270, extent=90, fill=bg_h, outline="")
            cvs.create_rectangle(r, 0, w - r, h, fill=bg_h, outline="")
            cvs.create_rectangle(0, r, w, h - r, fill=bg_h, outline="")
            cvs.create_text(w // 2, h // 2, text=text,
                            fill=fg, font=T.F_CAPTION, anchor="center")

        cvs.bind("<Configure>", _draw)
        cvs.bind("<Enter>", _enter)
        cvs.bind("<Leave>", lambda _e: _draw())
        cvs.bind("<Button-1>", lambda _e: cmd())
        return cvs

    def _pill(self, parent: tk.Widget, text: str,
              cmd: Callable, gl: str, gr: str) -> None:
        """CC=3 — Bouton pill gradient. Pré-rendu via PhotoImage (pas de lag)."""
        w, h = 218, 38
        img_normal = self._render_pill_image(w, h, gl, gr, 1.0)
        img_hover  = self._render_pill_image(w, h, gl, gr, 0.80)

        cvs = tk.Canvas(parent, width=w, height=h,
                        bg=T.BG_DEEP, highlightthickness=0, bd=0, cursor="hand2")
        cvs.pack(padx=14, pady=2)

        # Garder une référence pour éviter le garbage collection
        cvs._img_normal = img_normal
        cvs._img_hover = img_hover

        img_id = cvs.create_image(0, 0, anchor="nw", image=img_normal)

        # Triangle play
        cy = h // 2
        cx = w - 22
        sz = 7  # demi-taille du triangle
        cvs.create_polygon(
            cx - sz + 1, cy - sz,
            cx + sz, cy,
            cx - sz + 1, cy + sz,
            fill=gl, outline=gl, width=2,
            joinstyle="round", smooth=False)
        cvs.create_text(14, h // 2, text=text, anchor="w",
                        fill="white", font=T.F_CONTROL)

        cvs.bind("<Enter>", lambda e: cvs.itemconfig(img_id, image=img_hover))
        cvs.bind("<Leave>", lambda e: cvs.itemconfig(img_id, image=img_normal))
        cvs.bind("<Button-1>", lambda e: cmd())

    @staticmethod
    def _render_pill_image(w: int, h: int, gl: str, gr: str,
                           brightness: float) -> tk.PhotoImage:
        """CC=5 — Génère une PhotoImage gradient pill (pré-rendu, pas de lag)."""
        img = tk.PhotoImage(width=w, height=h)
        r1, g1, b1 = int(gl[1:3], 16), int(gl[3:5], 16), int(gl[5:7], 16)
        r2, g2, b2 = int(gr[1:3], 16), int(gr[3:5], 16), int(gr[5:7], 16)
        bg_r, bg_g, bg_b = int(T.BG_DEEP[1:3], 16), int(T.BG_DEEP[3:5], 16), int(T.BG_DEEP[5:7], 16)
        R = 10  # rayon de congé (coins arrondis modérés)
        f = brightness

        # Construit ligne par ligne en PPM
        row_data = []
        for y in range(h):
            row = []
            for x in range(w):
                t = x / max(w - 1, 1)
                cr = int((r1 + (r2 - r1) * t) * f)
                cg = int((g1 + (g2 - g1) * t) * f)
                cb = int((b1 + (b2 - b1) * t) * f)
                # Coins arrondis (4 coins)
                corner = False
                if x < R and y < R:
                    dx, dy = R - x, R - y
                    corner = (dx * dx + dy * dy) > R * R
                elif x > w - R - 1 and y < R:
                    dx, dy = x - (w - R - 1), R - y
                    corner = (dx * dx + dy * dy) > R * R
                elif x < R and y > h - R - 1:
                    dx, dy = R - x, y - (h - R - 1)
                    corner = (dx * dx + dy * dy) > R * R
                elif x > w - R - 1 and y > h - R - 1:
                    dx, dy = x - (w - R - 1), y - (h - R - 1)
                    corner = (dx * dx + dy * dy) > R * R
                if corner:
                    cr, cg, cb = bg_r, bg_g, bg_b
                row.append(f"#{cr:02x}{cg:02x}{cb:02x}")
            row_data.append("{" + " ".join(row) + "}")

        img.put(" ".join(row_data))
        return img

    # ── Statut ────────────────────────────────────────────────────────────────

    def _build_status(self, parent: tk.Widget) -> None:
        tk.Label(parent, text=SB_STATUT, bg=T.BG_DEEP, fg=T.TEXT_DIM,
                 font=T.F_CAPTION).pack(anchor="w", padx=16, pady=(4, 4))

        def _badge(text: str, attr: str) -> None:
            rf = RoundedFrame(parent, bg=T.SURFACE, border_color=T.BORDER,
                              radius=12, padding=2)
            rf.pack(fill="x", padx=12, pady=2)
            rf.configure(height=32)
            lbl = tk.Label(rf.inner, text=text, bg=T.SURFACE, fg=T.TEXT_MED,
                           font=T.F_CAPTION, anchor="w", padx=8, pady=4)
            lbl.pack(fill="x")
            setattr(self, attr, lbl)

        _badge(BADGE_POS_MACHINE, "_badge_machine")
        _badge(BADGE_POS_TRAVAIL, "_badge_travail")
        _badge(BADGE_CAPTEURS,    "_badge_capteurs")

    # ── Logique robots ────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        """CC=4 — Reconstruit les cartes robots avec couleurs vives."""
        if not hasattr(self, "_robot_cards_frame"):
            return
        for w in self._robot_cards_frame.winfo_children():
            w.destroy()
        self._robot_cards.clear()

        ids = sorted(registry.ids())
        if not self._active_id and ids:
            self._active_id = ids[0]

        self._cached_ids = ids
        for rid in ids:
            if registry.get(rid) is None:
                continue
            self._build_robot_card(rid)

        self._refresh_status_labels()

    def _build_robot_card(self, rid: str) -> None:
        """CC=3 — Carte compacte : bande couleur + icône + nom + état sur une ligne."""
        color = registry.color_for(rid)
        rt = T.robot_theme(color)
        is_active = (rid == self._active_id)
        bg = rt["bg_vif"] if is_active else rt["bg"]

        card = tk.Frame(self._robot_cards_frame, bg=bg,
                        highlightbackground=color if is_active else T.BORDER,
                        highlightthickness=2 if is_active else 1,
                        cursor="hand2")
        card.pack(fill="x", pady=1)

        # Bande colorée à gauche
        tk.Frame(card, bg=color, width=4).pack(side="left", fill="y")

        # Contenu compact : icône + nom + ★ + état à droite
        icon = self._robot_icon(rid)
        master_mark = " ★" if rid == registry.master_id else ""
        display = self._robot_display_name(rid)
        state_lbl = self._robot_state_label(rid)

        name_l = tk.Label(card, text=f"{icon} {display}{master_mark}",
                          bg=bg, fg=color, font=T.F_CONTROL,
                          anchor="w", padx=6, pady=4)
        name_l.pack(side="left")

        state_l = tk.Label(card, text=state_lbl, bg=bg, fg=T.TEXT_DIM,
                           font=T.F_CAPTION, anchor="e", padx=6)
        state_l.pack(side="right")

        # Bindings — simple clic = sélection (différée), double-clic = renommer
        for widget in [card, name_l, state_l]:
            widget.bind("<Button-1>", lambda _e, r=rid: self._schedule_select(r))
            widget.bind("<Double-1>", lambda _e, r=rid: self._on_double_click(r))

        self._robot_cards.append({
            "frame": card, "rid": rid, "color": color,
            "name_l": name_l, "state_l": state_l, "bg": bg,
        })

    def _schedule_select(self, rid: str) -> None:
        """Diffère la sélection pour laisser le double-clic annuler."""
        self._pending_select = rid
        self.after(250, self._do_pending_select)

    def _do_pending_select(self) -> None:
        """Exécute la sélection si pas annulée par un double-clic."""
        rid = getattr(self, "_pending_select", None)
        if rid is None or rid == self._active_id:
            return
        self._active_id = rid
        store.set_system(active_robot_id=rid)
        self._refresh_list()
        bus.publish("ui.active_robot_changed", {"robot_id": rid})

    def _on_double_click(self, rid: str) -> None:
        """Double-clic : annule la sélection pendante et ouvre le renommage."""
        self._pending_select = None
        self._rename_robot_by_id(rid)

    def _update_icons_only(self) -> None:
        """CC=4 — Update in-place des labels icone/etat — ZERO rebuild = zero clignotement.

        Rebuild complet uniquement si la structure a change (ajout/suppr robot).
        """
        ids = sorted(registry.ids())
        if ids != getattr(self, "_cached_ids", []):
            self._refresh_list()
            return
        # Update in-place : modifie juste le texte des labels existants
        for card in self._robot_cards:
            rid = card["rid"]
            icon = self._robot_icon(rid)
            master_mark = " ★" if rid == registry.master_id else ""
            display = self._robot_display_name(rid)
            new_name = f"{icon} {display}{master_mark}"
            new_state = self._robot_state_label(rid)
            name_l = card.get("name_l")
            state_l = card.get("state_l")
            if name_l is not None and str(name_l.cget("text")) != new_name:
                name_l.config(text=new_name)
            if state_l is not None and str(state_l.cget("text")) != new_state:
                state_l.config(text=new_state)
        self._refresh_status_labels()

    @staticmethod
    def _robot_icon(rid: str) -> str:
        """CC=4 — Détermine l'icône d'état d'un robot."""
        snap = store.get_robot(rid)
        if snap is None:
            return "⚪"
        if not snap.connected:
            return "⚪"
        return _STATE_ICON.get(snap.state, "🟢")

    @staticmethod
    def _robot_state_label(rid: str) -> str:
        """Retourne le label d'état FR d'un robot."""
        snap = store.get_robot(rid)
        if snap is None or not snap.connected:
            return _STATE_LABEL_FR.get("DISCONNECTED", "Déconnecté")
        return _STATE_LABEL_FR.get(snap.state, snap.state)

    @staticmethod
    def _robot_display_name(rid: str) -> str:
        """Retourne le nom d'affichage : name si défini, sinon robot_id."""
        from xrv22.library.library_manager import library
        rcfg = library.get_robot(rid)
        if rcfg and rcfg.name:
            return rcfg.name
        return rid

    def _rename_robot_by_id(self, rid: str) -> None:
        """CC=3 — Double-clic sur une carte robot → renommer."""
        from xrv22.library.library_manager import library
        rcfg = library.get_robot(rid)
        current_name = (rcfg.name if rcfg and rcfg.name else rid)

        new_name = simpledialog.askstring(
            "Renommer robot",
            f"Nouveau nom pour {rid} :",
            initialvalue=current_name,
            parent=self)
        if not new_name or new_name.strip() == current_name:
            return
        new_name = new_name.strip()

        if rcfg:
            rcfg.name = new_name
            library.save_robot(rcfg)
        self._refresh_list()

    def _rename_robot(self, _event: Optional[tk.Event] = None) -> None:
        """Compat : renomme le robot actif."""
        if self._active_id:
            self._rename_robot_by_id(self._active_id)

    def _refresh_status_labels(self) -> None:
        """CC=5 — Labels statut robot actif (état, nom, port)."""
        rid = self._active_id
        ctrl = registry.get(rid) if rid else None
        if ctrl is None:
            self._robot_status_lbl.config(text=SB_DECONNECTE, fg=T.TEXT_DIM)
            self._robot_name_lbl.config(text="")
            self._robot_port_lbl.config(text="")
            return

        snap = store.get_robot(rid)
        connected = snap.connected if snap else False
        state = snap.state if snap else "DISCONNECTED"
        icon  = _STATE_ICON.get(state, "⚪")
        color = _STATE_COLOR.get(state, T.TEXT_DIM)

        # Texte lisible en français (comme V17)
        state_text = _STATE_LABEL_FR.get(state, state)
        if connected:
            self._robot_status_lbl.config(text=f"{icon}  {state_text}", fg=color)
        else:
            self._robot_status_lbl.config(text="⚪  Déconnecté", fg=T.TEXT_DIM)
        display = self._robot_display_name(rid)
        robot_color = registry.color_for(rid)
        self._robot_name_lbl.config(text=f"▶ {display}", fg=robot_color)
        port = (snap.port if snap else "") or "— non connecté —"
        self._robot_port_lbl.config(text=port)

    def _on_select(self, _event: Optional[tk.Event] = None) -> None:
        """Compat — la sélection passe maintenant par _select_robot()."""
        pass

    def active_robot_id(self) -> str:
        """Retourne l'ID du robot actif (méthode appelée avec parenthèses)."""
        if not self._active_id:
            ids = sorted(registry.ids())
            if ids:
                self._active_id = ids[0]
        return self._active_id

    def _add_robot(self) -> None:
        """CC=6 — Ajoute un nouveau robot."""
        n = len(registry.ids()) + 1
        name = simpledialog.askstring(
            "Nouveau robot", "Nom du robot (ex: robot_2) :",
            initialvalue=f"robot_{n}")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in registry.ids():
            messagebox.showwarning("Nouveau robot", f"Le robot '{name}' existe déjà.")
            return
        registry.add(name, list(range(1, 7)))
        self._active_id = name
        store.set_system(active_robot_id=name)
        self._refresh_list()
        bus.publish("ui.active_robot_changed", {"robot_id": name})
        _LOG.info("Robot '%s' ajouté", name)

    def _remove_robot(self) -> None:
        """CC=6 — Supprime le robot actif."""
        rid = self.active_robot_id()
        if not rid:
            return
        if len(registry.ids()) <= 1:
            messagebox.showwarning("Supprimer robot", MSG_ROBOT_DERNIER)
            return
        if not messagebox.askyesno("Supprimer robot", f"Supprimer le robot '{rid}' ?"):
            return
        ctrl = registry.get(rid)
        if ctrl:
            ctrl.disconnect()
        registry.remove(rid)
        ids = registry.ids()
        self._active_id = ids[0] if ids else ""
        if self._active_id:
            store.set_system(active_robot_id=self._active_id)
        self._refresh_list()
        if self._active_id:
            bus.publish("ui.active_robot_changed", {"robot_id": self._active_id})
        _LOG.info("Robot '%s' supprimé", rid)

    # ── Commandes globales ────────────────────────────────────────────────────

    def _build_torque_pill(self, parent: tk.Widget) -> dict:
        """CC=4 — Construit le pill gradient toggle Torque ON/OFF."""
        w, h = 218, 38
        # Pré-rendre les 3 états : OFF (ambre), ON (vert), déconnecté (gris)
        img_off      = self._render_pill_image(w, h, "#3a1e04", T.C_AMB, 1.0)
        img_off_h    = self._render_pill_image(w, h, "#3a1e04", T.C_AMB, 0.80)
        img_on       = self._render_pill_image(w, h, "#0e2a18", T.C_OK, 1.0)
        img_on_h     = self._render_pill_image(w, h, "#0e2a18", T.C_OK, 0.80)
        img_disc     = self._render_pill_image(w, h, "#2a2a2a", "#4a5568", 1.0)

        cvs = tk.Canvas(parent, width=w, height=h,
                        bg=T.BG_DEEP, highlightthickness=0, bd=0, cursor="hand2")
        cvs.pack(padx=14, pady=2)

        data = {
            "canvas": cvs,
            "img_off": img_off, "img_off_h": img_off_h,
            "img_on": img_on, "img_on_h": img_on_h,
            "img_disc": img_disc,
            "state": "off",  # "off", "on", "disc"
        }

        img_id = cvs.create_image(0, 0, anchor="nw", image=img_off)
        data["img_id"] = img_id

        # Triangle play (même style que les autres pills)
        cy = h // 2
        cx = w - 22
        sz = 7
        cvs.create_polygon(
            cx - sz + 1, cy - sz,
            cx + sz, cy,
            cx - sz + 1, cy + sz,
            fill="#3a1e04", outline="#3a1e04", width=2,
            joinstyle="round", smooth=False)

        txt_id = cvs.create_text(14, h // 2,
                                 text="🟡  Torque OFF  →  ON",
                                 anchor="w", fill="white", font=T.F_CONTROL)
        data["txt_id"] = txt_id

        def _enter(_e):
            s = data["state"]
            if s == "on":
                cvs.itemconfig(img_id, image=img_on_h)
            elif s == "off":
                cvs.itemconfig(img_id, image=img_off_h)

        def _leave(_e):
            s = data["state"]
            if s == "on":
                cvs.itemconfig(img_id, image=img_on)
            elif s == "off":
                cvs.itemconfig(img_id, image=img_off)
            else:
                cvs.itemconfig(img_id, image=img_disc)

        cvs.bind("<Enter>", _enter)
        cvs.bind("<Leave>", _leave)
        cvs.bind("<Button-1>", lambda _e: self._toggle_torque())

        return data

    def _toggle_torque(self) -> None:
        """CC=4 — Toggle torque du robot actif : OFF → ON, ON → OFF."""
        rid = self.active_robot_id()
        ctrl = registry.get(rid) if rid else None
        if not ctrl or not ctrl.is_connected:
            return
        if ctrl.torque_enabled:
            ctrl.set_torque(False)
            _LOG.info("Sidebar : Torque OFF (%s)", rid)
        else:
            ctrl.set_torque(True)
            _LOG.info("Sidebar : Torque ON (%s)", rid)
        self._update_torque_btn()

    def _update_torque_btn(self) -> None:
        """CC=4 — Met à jour le pill toggle torque (gradient + texte)."""
        d = self._torque_pill
        cvs = d["canvas"]
        rid = self.active_robot_id()
        ctrl = registry.get(rid) if rid else None

        if not ctrl or not ctrl.is_connected:
            if d["state"] != "disc":
                d["state"] = "disc"
                cvs.itemconfig(d["img_id"], image=d["img_disc"])
                cvs.itemconfig(d["txt_id"], text="⚪  Non connecté")
            return

        if ctrl.torque_enabled:
            if d["state"] != "on":
                d["state"] = "on"
                cvs.itemconfig(d["img_id"], image=d["img_on"])
                cvs.itemconfig(d["txt_id"], text="🟢  Torque ON  →  OFF")
        else:
            if d["state"] != "off":
                d["state"] = "off"
                cvs.itemconfig(d["img_id"], image=d["img_off"])
                cvs.itemconfig(d["txt_id"], text="🟡  Torque OFF  →  ON")

    def _all_connect(self) -> None:
        """CC=7 — Double protocole ALL CO. :
        - Robots non connectés → connexion
        - Robots déjà connectés → torque ON + déconnexion + reconnexion (reboot)
        """
        from xrv22.library.library_manager import library
        robots_cfg = library.list_robots()
        to_connect = {}   # rid → (port, baud) — pas encore connectés
        to_reboot = {}    # rid → (port, baud) — déjà connectés → reboot

        for rcfg in robots_cfg:
            rid = rcfg.robot_id
            port = (rcfg.port or "").strip()
            if rid and port and rid in registry.ids():
                snap = store.get_robot(rid)
                if snap and snap.connected:
                    to_reboot[rid] = (port, rcfg.baud)
                else:
                    to_connect[rid] = (port, rcfg.baud)

        if not to_connect and not to_reboot:
            messagebox.showinfo("Connexion",
                                "Aucun robot avec port sauvegardé à connecter.")
            return

        _LOG.info("ALL CO. : %d à connecter, %d à reboot — %s",
                  len(to_connect), len(to_reboot),
                  list(to_connect.keys()) + list(to_reboot.keys()))

        def _worker():
            results = {}
            # — Reboot : torque ON → déconnexion → reconnexion
            for rid, (port, baud) in to_reboot.items():
                ctrl = registry.get(rid)
                if ctrl is None:
                    results[rid] = False
                    continue
                try:
                    ctrl.set_torque(True)
                    time.sleep(0.1)
                    ctrl.disconnect()
                    time.sleep(0.3)
                    ok = ctrl.connect(port, baud)
                    results[rid] = ok
                except Exception as exc:
                    _LOG.error("Reboot %s échoué : %s", rid, exc)
                    results[rid] = False
            # — Connexion simple
            for rid, (port, baud) in to_connect.items():
                ctrl = registry.get(rid)
                if ctrl is None:
                    results[rid] = False
                    continue
                try:
                    ok = ctrl.connect(port, baud)
                    results[rid] = ok
                except Exception as exc:
                    _LOG.error("Connexion %s échouée : %s", rid, exc)
                    results[rid] = False
            self.after(0, lambda: self._all_connect_done(results))

        threading.Thread(target=_worker, daemon=True).start()

    def _all_connect_done(self, results: dict) -> None:
        """CC=4 — Affiche le résultat de l'auto-connexion / reboot."""
        ok_list = [r for r, ok in results.items() if ok]
        fail_list = [r for r, ok in results.items() if not ok]
        self._refresh_list()
        if fail_list:
            messagebox.showwarning(
                "Connexion",
                f"✅ {len(ok_list)} connecté(s)\n❌ {len(fail_list)} échoué(s) : "
                + ", ".join(fail_list))
        else:
            _LOG.info("Tous les robots connectés : %s", ok_list)

    def _all_unlock(self) -> None:
        registry.unlock_all()

    def _all_lock(self) -> None:
        registry.lock_all()

    def _all_goto_work(self) -> None:
        registry.go_home_work_all()

    def _all_goto_machine(self) -> None:
        registry.safe_home_all()

    # ── Synchronisation multi-robot ──────────────────────────────────────────

    def _open_sync_dialog(self) -> None:
        """CC=5 — Ouvre la fenêtre de synchronisation parent/enfant."""
        ids = sorted(registry.ids())
        if len(ids) < 2:
            messagebox.showinfo("Synchronisation",
                                "Il faut au moins 2 robots pour synchroniser.",
                                parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("🔗  Synchronisation robots")
        dlg.geometry("440x480")
        dlg.minsize(420, 420)
        dlg.transient(self.winfo_toplevel())
        dlg.configure(bg=T.BG)

        # En-tête
        hdr = tk.Frame(dlg, bg=T.SURFACE_HI, pady=8)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text="Synchronisation multi-robot",
                 bg=T.SURFACE_HI, fg=T.TEXT, font=T.F_SECTION).pack(padx=12)
        tk.Label(hdr, text="Le robot parent sert de référence (calibrage).\n"
                 "Les enfants suivront ses mouvements.",
                 bg=T.SURFACE_HI, fg=T.TEXT_MED, font=T.F_CAPTION
                 ).pack(padx=12, pady=(2, 0))

        # Footer packé en premier (réserve l'espace en bas avant le body expand)
        btn_frame = tk.Frame(dlg, bg=T.SURFACE_HI, pady=10)
        btn_frame.pack(fill="x", side="bottom")

        body = tk.Frame(dlg, bg=T.BG, pady=12)
        body.pack(fill="both", expand=True, padx=20, side="top")

        # ── Sélecteur Parent ──
        tk.Label(body, text="Robot parent (référence) :", bg=T.BG,
                 fg=T.TEXT, font=T.F_CONTROL).pack(anchor="w", pady=(0, 4))
        parent_var = tk.StringVar(value=registry.master_id or ids[0])
        parent_frame = tk.Frame(body, bg=T.BG)
        parent_frame.pack(fill="x", pady=(0, 12))

        for rid in ids:
            color = registry.color_for(rid)
            display = self._robot_display_name(rid)
            rb = tk.Radiobutton(
                parent_frame, text=f"  {display}", variable=parent_var,
                value=rid, bg=T.BG, fg=color, activebackground=T.BG,
                activeforeground=color, selectcolor=T.SURFACE,
                font=T.F_CONTROL, anchor="w", indicatoron=True)
            rb.pack(fill="x", padx=4, pady=1)

        # ── Sélecteur Enfants ──
        tk.Label(body, text="Robots enfants (suivent le parent) :", bg=T.BG,
                 fg=T.TEXT, font=T.F_CONTROL).pack(anchor="w", pady=(0, 4))
        child_vars: dict[str, tk.BooleanVar] = {}
        children_frame = tk.Frame(body, bg=T.BG)
        children_frame.pack(fill="x", pady=(0, 8))

        for rid in ids:
            color = registry.color_for(rid)
            display = self._robot_display_name(rid)
            bvar = tk.BooleanVar(value=(rid != (registry.master_id or ids[0])))
            child_vars[rid] = bvar
            cb = tk.Checkbutton(
                children_frame, text=f"  {display}", variable=bvar,
                bg=T.BG, fg=color, activebackground=T.BG,
                activeforeground=color, selectcolor=T.SURFACE,
                font=T.F_CONTROL, anchor="w")
            cb.pack(fill="x", padx=4, pady=1)

        # ── Boutons (le frame a déjà été packé en haut, on remplit ici) ──
        def _cancel():
            dlg.destroy()

        def _sync():
            parent_id = parent_var.get()
            children = [rid for rid, bv in child_vars.items()
                        if bv.get() and rid != parent_id]
            if not children:
                messagebox.showwarning("Synchronisation",
                                       "Sélectionnez au moins un robot enfant.",
                                       parent=dlg)
                return
            # Parent devient le maître (robot de calibrage)
            registry.set_master(parent_id)

            # ── Propagation presets parent → enfants ──
            parent_ctrl = registry.get(parent_id)
            report = []
            if parent_ctrl:
                for cid in children:
                    child_ctrl = registry.get(cid)
                    if child_ctrl is None:
                        continue
                    # Home machine
                    if parent_ctrl.home_machine:
                        child_ctrl.set_home_machine(dict(parent_ctrl.home_machine))
                        report.append(f"  {cid} ← home machine")
                    # Home travail
                    if parent_ctrl.home_work:
                        child_ctrl.set_home_work(dict(parent_ctrl.home_work))
                        report.append(f"  {cid} ← home travail")
                    # Limites de sécurité
                    for mid, (lo, hi) in parent_ctrl.profile.soft_limits.items():
                        child_ctrl.profile.soft_limits[mid] = (lo, hi)
                        child_ctrl.set_motor_limit(mid, lo, hi)
                    report.append(f"  {cid} ← limites sécurité")
                    # Paramètres mouvement
                    child_ctrl.set_motion_params(
                        parent_ctrl.smooth_hz,
                        parent_ctrl.comfort_vel,
                        parent_ctrl.comfort_acc,
                        home_duration=parent_ctrl.home_duration)
                    report.append(f"  {cid} ← paramètres mouvement")

            self._active_id = parent_id
            store.set_system(active_robot_id=parent_id)
            self._refresh_list()
            bus.publish("ui.active_robot_changed", {"robot_id": parent_id})
            bus.publish("sync.configured", {
                "parent": parent_id,
                "children": children,
            })
            _LOG.info("Synchro configurée : parent=%s, enfants=%s\n%s",
                      parent_id, children, "\n".join(report))
            dlg.destroy()

            details = "\n".join([
                f"  • {self._robot_display_name(c)}" for c in children])
            messagebox.showinfo("Synchronisation",
                                f"Parent : {self._robot_display_name(parent_id)}\n\n"
                                f"Enfants synchronisés :\n{details}\n\n"
                                "Propagé :\n"
                                "  ✓ Position initiale machine\n"
                                "  ✓ Position initiale travail\n"
                                "  ✓ Limites de sécurité\n"
                                "  ✓ Paramètres mouvement",
                                parent=self)

        ttk.Button(btn_frame, text="Annuler",
                   command=_cancel).pack(side="left", padx=12)
        ttk.Button(btn_frame, text="✅ Synchroniser",
                   command=_sync).pack(side="right", padx=12)
        dlg.bind("<Escape>", lambda _: _cancel())

    # ── Polling périodique (filet de sécurité) ────────────────────────────────

    def _start_poll(self) -> None:
        """Rafraîchit la sidebar toutes les 150ms (refresh rapide icônes + état)."""
        self._update_icons_only()
        self._update_torque_btn()
        self.after(150, self._start_poll)

    # ── Bus ───────────────────────────────────────────────────────────────────

    def _subscribe(self) -> None:
        bus.subscribe("robot.connected",       self._on_bus_state)
        bus.subscribe("robot.disconnected",    self._on_bus_state)
        bus.subscribe("robot.state_changed",   self._on_bus_state)
        bus.subscribe("robot.added",           self._on_bus_structure)
        bus.subscribe("robot.removed",         self._on_bus_structure)
        bus.subscribe("state.refresh",         self._on_bus_state)
        bus.subscribe("sensor.reading",        self._on_sensor)
        bus.subscribe("ui.active_robot_changed", self._on_bus_active_robot)

    def _on_bus_state(self, _payload: dict) -> None:
        """Changement d'état : refresh léger immédiat (icônes + labels)."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self.after(30, self._debounced_state_refresh)

    def _debounced_state_refresh(self) -> None:
        self._refresh_pending = False
        self._update_icons_only()

    def _on_bus_structure(self, _payload: dict) -> None:
        """Ajout/suppression robot : rebuild complet."""
        self.after(50, self._refresh_list)

    def _on_bus_active_robot(self, payload: dict) -> None:
        """Synchronise la sélection listbox quand un autre onglet change de robot."""
        rid = payload.get("robot_id", "")
        if not rid or rid == self._active_id:
            return
        self._active_id = rid
        self.after(0, self._sync_listbox_selection)

    def _sync_listbox_selection(self) -> None:
        """Met à jour la sélection visuelle sans re-publier l'événement."""
        self._refresh_list()

    def _on_sensor(self, payload: dict) -> None:
        device = payload.get("device", "")
        n = payload.get("channel_count", 1)
        self.after(0, lambda: self._badge_capteurs.config(
            text=f"📡 {n} capteur(s)  [{device}]"))

    def destroy(self) -> None:
        """Nettoyage des souscriptions bus avant destruction."""
        bus.unsubscribe_object(self)
        super().destroy()

    def update_badge_machine(self, defined: bool) -> None:
        t = "⚙  Pos. machine : ✓" if defined else BADGE_POS_MACHINE
        self._badge_machine.config(text=t, fg=T.C_OK if defined else T.TEXT_MED)

    def update_badge_travail(self, defined: bool) -> None:
        t = "🔧 Pos. travail : ✓" if defined else BADGE_POS_TRAVAIL
        self._badge_travail.config(text=t, fg=T.C_OK if defined else T.TEXT_MED)
