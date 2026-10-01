"""
xrv22/ui_pi/main_window.py
───────────────────────────
Fenetre principale UI Pi — layout "telecommande" a 2 onglets permanents.

Layout (800 x 480) :
  Header 40     (titre + horloge)
  Content 384   (ScreenPilotage ou ScreenExecution selon onglet)
  TabBar 56     (2 onglets : PILOTAGE / EXECUTION)
"""
from __future__ import annotations

import platform
import time
import tkinter as tk

from xrv22.services.logger import get_logger
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.screen_dessin import ScreenDessin
from xrv22.ui_pi.screen_execution import ScreenExecution
from xrv22.ui_pi.screen_home import ScreenHome
from xrv22.ui_pi.screen_pilotage import ScreenPilotage
from xrv22.ui_pi.widgets_pi import BottomTabBar, HeaderBar

_LOG = get_logger("UI_PI")


class MainWindowPi(tk.Tk):
    """Fenetre root : header + content (onglets) + tabbar."""

    HEADER_H = 0       # header masque (onglets en haut suffisent)
    TABBAR_H = 40
    CONTENT_H = P.SCREEN_H - TABBAR_H  # 440 (header retire)

    def __init__(self, *, fullscreen: bool = False):
        super().__init__()
        self.title("XRV22 PRO — Telecommande Pi")
        self.configure(bg=T.BG)
        self.geometry(f"{P.SCREEN_W}x{P.SCREEN_H}")
        self.resizable(False, False)
        if fullscreen or platform.system() == "Linux":
            try:
                self.attributes("-fullscreen", True)
                self.config(cursor="none")
            except Exception:
                pass
            # Sous Linux/labwc, la barre de titre Tk reste visible meme en
            # fullscreen — overrideredirect la supprime pour un kiosque propre.
            if platform.system() == "Linux":
                try:
                    self.overrideredirect(True)
                    self.geometry(f"{P.SCREEN_W}x{P.SCREEN_H}+0+0")
                except Exception:
                    pass
        self.bind("<Escape>", self._toggle_fullscreen)
        # Raccourcis sortie clavier (utile si clavier branche)
        for seq in ("<Control-q>", "<Control-Q>", "<Control-w>",
                    "<Control-W>", "<F10>"):
            self.bind(seq, lambda _e: self._request_quit())
        self.protocol("WM_DELETE_WINDOW", self._request_quit)

        # ── Header masque (titre redondant avec les onglets) ──────
        self._header = HeaderBar(self, title="XRV22 PRO", show_back=False)
        # Pas de pack : le header existe (pour que set_title ne crashe pas)
        # mais n'est pas affiche.

        # Bouton Quitter : init ici (avant la tabbar) mais cree-place apres
        # pour garantir le z-order top.
        self._quit_state = "idle"  # idle | armed
        self._quit_armed_after_id: str | None = None
        self._quit_btn = None  # cree apres la tabbar (cf bloc plus bas)

        # ── Content (avec placement fixe) ─────────────────────────
        self._container = tk.Frame(self, bg=T.BG,
                                   width=P.SCREEN_W, height=self.CONTENT_H)
        self._container.pack(side="top", fill="both", expand=False)
        self._container.pack_propagate(False)

        self._home = ScreenHome(self._container)
        self._pilotage = ScreenPilotage(self._container, on_back=lambda: None)
        self._execution = ScreenExecution(self._container)
        self._dessin = ScreenDessin(self._container)
        for s in (self._home, self._pilotage, self._execution, self._dessin):
            s.place(x=0, y=0, width=P.SCREEN_W, height=self.CONTENT_H)

        # ── TabBar 56 ─────────────────────────────────────────────
        self._tabbar = BottomTabBar(
            self,
            tabs=[
                ("home",      "HOME",      "\u2302"),    # maison
                ("pilotage",  "PILOTAGE",  "\u2630"),    # 3 lignes
                ("execution", "EXECUTION", "\u25B6"),    # play
                ("dessin",    "DESSIN",    "\u270F"),    # crayon
            ],
            on_tab_change=self._switch_tab,
        )
        # TabBar en haut (header masque, donc tabbar tout en haut)
        self._tabbar.pack(side="top", fill="x", before=self._container)

        # Croix d'arret CREE APRES la tabbar -> z-order top par defaut
        self._quit_btn = tk.Canvas(self, width=40, height=32,
                                   bg=T.SIDEBAR, highlightthickness=0, bd=0)
        self._quit_btn.place(x=P.SCREEN_W - 42, y=2)
        self._draw_quit_btn()
        self._quit_btn.bind("<ButtonRelease-1>", lambda _e: self._on_quit_tap())

        # Init
        self._switch_tab("home")
        self._tick_clock()

    # ── Navigation ────────────────────────────────────────────────
    def _switch_tab(self, tab_id: str) -> None:
        if tab_id == "home":
            self._home.refresh()
            self._home.lift()
            self._header.set_title("HOME")
        elif tab_id == "pilotage":
            self._pilotage.load_project("")  # rafraichit robots
            self._pilotage.lift()
            self._header.set_title("PILOTAGE")
        elif tab_id == "dessin":
            self._dessin.lift()
            self._header.set_title("DESSIN")
        else:
            self._execution.refresh()
            self._execution.lift()
            self._header.set_title("EXECUTION")

    # ── Horloge ───────────────────────────────────────────────────
    def _tick_clock(self) -> None:
        self._header.set_clock(time.strftime("%H:%M"))
        self.after(10_000, self._tick_clock)

    def _toggle_fullscreen(self, _evt=None) -> None:
        current = bool(self.attributes("-fullscreen"))
        self.attributes("-fullscreen", not current)
        self.config(cursor="" if current else "none")

    # ── Sortie tactile (double-tap pour confirmer) ────────────────
    def _draw_quit_btn(self) -> None:
        c = self._quit_btn
        c.delete("all")
        if self._quit_state == "armed":
            c.create_rectangle(0, 0, 40, 32, fill=T.C_ERR_DIM, outline="")
            c.create_text(20, 16, text="✓?", fill=T.C_ERR,
                          font=(T.FONT_DISPLAY, 14, "bold"))
        else:
            c.create_rectangle(0, 0, 40, 32, fill=T.SIDEBAR, outline="")
            c.create_text(20, 16, text="✕", fill=T.C_ERR,
                          font=(T.FONT_DISPLAY, 16, "bold"))

    def _on_quit_tap(self) -> None:
        if self._quit_state == "idle":
            self._quit_state = "armed"
            self._draw_quit_btn()
            self._quit_armed_after_id = self.after(2500, self._reset_quit_btn)
        else:
            self._request_quit()

    def _reset_quit_btn(self) -> None:
        self._quit_state = "idle"
        self._quit_armed_after_id = None
        try:
            self._draw_quit_btn()
        except tk.TclError:
            pass

    def _request_quit(self) -> None:
        _LOG.info("Sortie demandee — fermeture UI Pi")
        try:
            self.destroy()
        except tk.TclError:
            pass
