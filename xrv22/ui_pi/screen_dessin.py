"""
xrv22/ui_pi/screen_dessin.py
────────────────────────────
Écran DESSIN — tracé live de la tablette Wacom sur l'écran tactile du Pi.

S'abonne en mémoire (même process que le serveur) au topic bus `stylet.tick`
publié par `run_incarne` pendant un run : chaque tick {x, y, p, etat} prolonge le
tracé tant qu'il y a contact (p>0). Permet d'OBSERVER ce qu'Eddy trace.

Boutons :
  - « Effacer » : vide le canvas.
  - « Position initiale de dessin » : amène le robot EN DOUCEUR à la pose de
    départ (position_protocole.json), en 2 paliers (position de travail puis
    dessin) via move()/profil temporel — go-to en thread (non bloquant).

Note sécurité : le go-to est un VRAI mouvement (Valentin présent, arrêt d'urgence).
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path

from xrv22.robots.robot_registry import registry
from xrv22.services.event_bus import bus
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.dessin_trace import ajoute_tick
from xrv22.ui_pi.widgets_pi import TouchButton

# Bornes tablette observées (Wacom CTH-461) — plage brute x/y.
_TX = (0, 14720)
_TY = (0, 9200)
_CANVAS_W = 784
_CANVAS_H = 340
_TRACE = "#C47832"  # cuivre signature OVNI


class ScreenDessin(tk.Frame):
    """Canvas de tracé live alimenté par le bus `stylet.tick`."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.BG)
        self.pack_propagate(False)
        self._strokes = []

        # Barre d'actions (haut)
        bar = tk.Frame(self, bg=T.BG)
        bar.pack(side="top", fill="x", padx=P.PAD_MD, pady=P.PAD_SM)
        self._readout = tk.Label(bar, text="HORS-PORTEE · p=0", bg=T.BG,
                                 fg=T.TEXT_DIM, font=P.F_MONO, anchor="w")
        self._readout.pack(side="left", padx=(2, 0))
        TouchButton(bar, text="Position initiale\nde dessin",
                    command=self._go_depart, width=160, height=P.TOUCH_MD
                    ).pack(side="right", padx=P.PAD_SM)
        # Torque OFF/ON : pour un run d'OBSERVATION, on coupe le torque et on bouge
        # le bras à la main (⚠ tenir le bras avant de couper — il devient mou).
        self._btn_torque = TouchButton(bar, text="Torque ?", command=self._toggle_torque,
                                       width=120, height=P.TOUCH_MD)
        self._btn_torque.pack(side="right", padx=P.PAD_SM)
        TouchButton(bar, text="Effacer", command=self._effacer,
                    width=100, height=P.TOUCH_MD).pack(side="right", padx=P.PAD_SM)
        bus.subscribe_ui("robot.torque_changed", lambda _: self._refresh_torque(), self)
        self._refresh_torque()

        # Canvas de tracé
        self._canvas = tk.Canvas(self, width=_CANVAS_W, height=_CANVAS_H,
                                 bg="#0d0518", highlightthickness=1,
                                 highlightbackground=T.BORDER)
        self._canvas.pack(side="top", padx=P.PAD_MD, pady=P.PAD_SM)

        # Bus : subscribe_ui marshale vers le mainloop Tk (tick publié depuis le
        # thread serveur). subscribe_object → nettoyage auto à la destruction.
        bus.subscribe_ui("stylet.tick", self._on_tick, self)

    def _mx(self, x: int) -> float:
        return (x - _TX[0]) / (_TX[1] - _TX[0]) * _CANVAS_W

    def _my(self, y: int) -> float:
        return (y - _TY[0]) / (_TY[1] - _TY[0]) * _CANVAS_H

    def _on_tick(self, data: dict) -> None:
        p = int(data.get("p") or 0)
        etat = data.get("etat", "HORS-PORTEE")
        self._readout.config(text=f"{etat} · p={p}")
        self._strokes = ajoute_tick(self._strokes, data)
        # Dessine le dernier segment (2 derniers points du dernier trait).
        if self._strokes and len(self._strokes[-1]) >= 2:
            (x0, y0, _), (x1, y1, p1) = self._strokes[-1][-2], self._strokes[-1][-1]
            self._canvas.create_line(self._mx(x0), self._my(y0),
                                     self._mx(x1), self._my(y1),
                                     fill=_TRACE, width=1 + (p1 / 1023) * 5,
                                     capstyle="round", tags="trace")

    def _effacer(self) -> None:
        self._canvas.delete("trace")
        self._strokes = []

    def _refresh_torque(self) -> None:
        """Met le libellé du bouton selon l'état torque courant de robot_1."""
        ctrl = registry.get("robot_1")
        on = bool(ctrl and getattr(ctrl, "torque_enabled", False))
        self._btn_torque.set_text("Torque OFF" if on else "Torque ON")

    def _toggle_torque(self) -> None:
        """Bascule le torque de robot_1. ⚠ OFF = bras mou (le tenir avant !).
        Sert au run d'observation : torque OFF puis on bouge le bras à la main."""
        ctrl = registry.get("robot_1")
        if ctrl is None or not ctrl.is_connected:
            self._readout.config(text="torque : robot non connecté")
            return
        new_state = not bool(getattr(ctrl, "torque_enabled", False))

        def _worker():
            ok = ctrl.set_torque(new_state)
            bus.publish("robot.torque_changed",
                        {"robot_id": "robot_1", "enabled": new_state, "ok": ok})

        threading.Thread(target=_worker, daemon=True).start()
        self._readout.config(text=("torque OFF — TIENS LE BRAS" if not new_state
                                   else "torque ON"))

    def _go_depart(self) -> None:
        """Amène le robot à la pose de dessin EN DOUCEUR (en thread).

        Deux paliers temporisés via `goto_dessin_doux` : position de travail
        (`home_work`) puis pose de départ dessin. On passe par `move()` (profil
        temporel Dynamixel = mouvement lissé) et NON `write_positions_direct`
        (goal posé d'un coup = à-coup brutal). L'axe 7 (stylet) n'est jamais bougé.

        On prend d'abord la main en mode CIBLE (`jog_engine.acquire(rid, "web")`)
        pour couper un éventuel pilotage Direct concurrent."""
        try:
            from incarne.run_incarne import charger_position_protocole
            from incarne.goto_doux import goto_dessin_doux
            from xrv22.core.jog_engine import jog_engine
            fichier = Path.home() / "xrv22" / "incarne" / "position_protocole.json"
            rid, targets = charger_position_protocole(fichier)
        except Exception as e:
            self._readout.config(text=f"départ illisible : {e}")
            return
        ctrl = registry.get(rid)
        if not (ctrl and ctrl.is_connected and getattr(ctrl, "torque_enabled", False)):
            self._readout.config(text="départ : robot non prêt (connecté + torque)")
            return

        def _run():
            jog_engine.acquire(rid, "web")   # coupe un pilotage Direct concurrent
            ok, msg = goto_dessin_doux(ctrl, targets)
            txt = "✓ position de dessin atteinte" if ok else f"départ : {msg}"
            self.after(0, lambda: self._readout.config(text=txt))

        threading.Thread(target=_run, daemon=True).start()
        self._readout.config(text="→ travail puis dessin (doux)…")

    def refresh(self) -> None:
        """Appelé au changement d'onglet (rien à recharger ici)."""
        pass
