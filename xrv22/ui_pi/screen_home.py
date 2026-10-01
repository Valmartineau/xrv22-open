"""
xrv22/ui_pi/screen_home.py
───────────────────────────
Ecran HOME — Centre de controle des robots actifs (Robot 1, 2, 3).

Pour chaque robot affiche, une card structuree :
  - Ligne 1 : nom du robot
  - Ligne 2 : etat textuel (connecte / deconnecte + torque)
  - Ligne 3 : 6 boutons d'action :
      1. Connecter / Deconnecter (dynamique)
      2. Reboot
      3. Torque on / Torque off (dynamique)
      4. Position initiale machine
      5. Position de travail
      6. Stop urgence
"""
from __future__ import annotations

import socket
import threading
import time
import tkinter as tk
from typing import Callable, Dict, List, Optional

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None

from xrv22.robots.robot_profiles import profiles
from xrv22.robots.robot_registry import registry
from xrv22.server.auth import get_token
from xrv22.services.event_bus import bus
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.widgets_pi import TouchButton

# Filtrage : on n'affiche QUE ces robots dans HOME
ALLOWED_ROBOTS = ("robot_1", "robot_2", "robot_3")


def _get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "raspberrypi.local"


# ═══════════════════════════════════════════════════════════════
# RobotCard
# ═══════════════════════════════════════════════════════════════

class RobotCard(tk.Frame):
    """Card robot : nom + etat + 6 boutons."""

    CARD_H = 120
    CARD_W = P.SCREEN_W - 16

    BTN_W = 120
    BTN_H = 32
    BTN_GAP = 6

    def __init__(self, parent, *, robot_id: str,
                 on_toggle_connect: Callable[[str], None],
                 on_reboot: Callable[[str], None],
                 on_toggle_torque: Callable[[str], None],
                 on_pos_machine: Callable[[str], None],
                 on_pos_travail: Callable[[str], None],
                 on_stop_urgence: Callable[[str], None]):
        super().__init__(parent, bg=T.SURFACE_HI,
                         width=self.CARD_W, height=self.CARD_H,
                         highlightthickness=1, highlightbackground=T.BORDER)
        self.pack_propagate(False)
        self._robot_id = robot_id

        # Ligne 1 : Nom robot
        self._lbl_name = tk.Label(self, text="—", bg=T.SURFACE_HI,
                                  fg=T.C_AMB, font=P.F_H1, anchor="w")
        self._lbl_name.place(x=14, y=6, width=self.CARD_W - 28, height=22)

        # Ligne 2 : Etat textuel
        self._lbl_state = tk.Label(self, text="—", bg=T.SURFACE_HI,
                                   fg=T.TEXT_MED, font=P.F_BODY, anchor="w")
        self._lbl_state.place(x=14, y=32, width=self.CARD_W - 28, height=18)

        # Ligne 3 : 6 boutons
        total_w = self.BTN_W * 6 + self.BTN_GAP * 5
        x0 = (self.CARD_W - total_w) // 2
        y_btn = 60
        positions = [x0 + i * (self.BTN_W + self.BTN_GAP) for i in range(6)]

        self._btn_connect = TouchButton(
            self, text="Connecter", width=self.BTN_W, height=self.BTN_H,
            accent=T.C_OK_DIM, fg=T.C_OK, font=P.F_BTN,
            command=lambda: on_toggle_connect(self._robot_id))
        self._btn_connect.place(x=positions[0], y=y_btn)

        TouchButton(self, text="Reboot", width=self.BTN_W, height=self.BTN_H,
                    accent=T.C_AMB_DIM2, fg=T.C_AMB, font=P.F_BTN,
                    command=lambda: on_reboot(self._robot_id)
                    ).place(x=positions[1], y=y_btn)

        self._btn_torque = TouchButton(
            self, text="Torque on", width=self.BTN_W, height=self.BTN_H,
            accent=T.SURFACE_HI, fg=T.TEXT_MED, font=P.F_BTN,
            command=lambda: on_toggle_torque(self._robot_id))
        self._btn_torque.place(x=positions[2], y=y_btn)

        TouchButton(self, text="Pos. machine",
                    width=self.BTN_W, height=self.BTN_H,
                    accent=T.SURFACE_HI, fg=T.C_AMB, font=P.F_BTN,
                    command=lambda: on_pos_machine(self._robot_id)
                    ).place(x=positions[3], y=y_btn)

        TouchButton(self, text="Pos. travail",
                    width=self.BTN_W, height=self.BTN_H,
                    accent=T.C_AMB_DIM2, fg=T.C_AMB, font=P.F_BTN,
                    command=lambda: on_pos_travail(self._robot_id)
                    ).place(x=positions[4], y=y_btn)

        TouchButton(self, text="Stop urgence",
                    width=self.BTN_W, height=self.BTN_H,
                    accent=T.C_ERR_DIM, fg=T.C_ERR, font=P.F_BTN,
                    command=lambda: on_stop_urgence(self._robot_id)
                    ).place(x=positions[5], y=y_btn)

        self.refresh()

    def refresh(self) -> None:
        """Met a jour nom + etat + libelle des boutons dynamiques."""
        ctrl = registry.get(self._robot_id)
        connected = bool(ctrl and ctrl.is_connected)
        torque = bool(ctrl and getattr(ctrl, "torque_enabled", False))

        # Nom
        profile = profiles.get(self._robot_id)
        raw = profile.name if profile else self._robot_id
        short = raw.replace("XRV22", "").strip().replace("robot_", "Robot ")
        self._lbl_name.config(text=short,
                              fg=(profile.color if profile else T.C_AMB))

        # Etat textuel
        if connected:
            etat_co = "Robot connecte"
            etat_co_color = T.C_OK
        else:
            etat_co = "Robot deconnecte"
            etat_co_color = T.TEXT_DIM
        etat_tq = "Torque on" if torque else "Torque off"
        self._lbl_state.config(text=f"{etat_co} — {etat_tq}",
                               fg=etat_co_color)

        # Bouton Connecter / Deconnecter
        if connected:
            self._btn_connect.set_text("Deconnecter")
            self._btn_connect.set_accent(T.C_ERR_DIM)
            self._btn_connect.set_fg(T.C_ERR)
        else:
            self._btn_connect.set_text("Connecter")
            self._btn_connect.set_accent(T.C_OK_DIM)
            self._btn_connect.set_fg(T.C_OK)

        # Bouton Torque on / off
        if torque:
            self._btn_torque.set_text("Torque off")
            self._btn_torque.set_accent(T.C_OK_DIM)
            self._btn_torque.set_fg(T.C_OK)
        else:
            self._btn_torque.set_text("Torque on")
            self._btn_torque.set_accent(T.SURFACE_HI)
            self._btn_torque.set_fg(T.TEXT_MED)


# ═══════════════════════════════════════════════════════════════
# ScreenHome
# ═══════════════════════════════════════════════════════════════

class ScreenHome(tk.Frame):
    """Liste des robots actifs (Robot 1/2/3)."""

    def __init__(self, parent):
        super().__init__(parent, bg=T.BG)
        self.pack_propagate(False)
        self._cards: Dict[str, RobotCard] = {}

        # Footer discret : URL d'acces + token (visible sur le LAN)
        # Pack en premier pour qu'il reste en bas meme avec list expand=True.
        self._footer = tk.Frame(self, bg=T.BG, height=16)
        self._footer.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
        self._footer.pack_propagate(False)

        _ip = _get_lan_ip()
        _tok = get_token()
        tk.Label(self._footer,
                 text=f"http://{_ip}:8080/  -  token: {_tok}",
                 bg=T.BG, fg=T.TEXT_DIM,
                 font=(T.FONT_MONO, 7),
                 anchor="w").pack(side="left", fill="x", expand=True)

        # Liste des cards (3 max)
        self._list = tk.Frame(self, bg=T.BG)
        self._list.pack(side="top", fill="both", expand=True,
                        padx=8, pady=6)

        # Bus — subscribe_ui (et non subscribe) : ces topics sont publiés depuis
        # des threads de fond (serial/worker de connexion, torque, poll live).
        # refresh() touche le canvas Tk → DOIT être marshalé vers le mainloop Tk,
        # sinon appel Tk hors thread principal = clignotement + clics perdus/gel.
        bus.subscribe_ui("robot.added",          lambda _: self.refresh(), self)
        bus.subscribe_ui("robot.removed",        lambda _: self.refresh(), self)
        bus.subscribe_ui("robot.connected",      lambda _: self.refresh(), self)
        bus.subscribe_ui("robot.disconnected",   lambda _: self.refresh(), self)
        bus.subscribe_ui("robot.torque_changed", lambda _: self.refresh(), self)
        bus.subscribe_ui("robot.master_changed", lambda _: self.refresh(), self)

        self.refresh()
        self.after(1000, self._tick)
        # Watcher hot-plug : detecte les U2D2 nouvellement branches/debranches
        # toutes les 3s et auto-connecte / auto-deconnecte + torque ON.
        self.after(3000, self._tick_hotplug)

    # ── Refresh ──────────────────────────────────────────────────
    def _allowed_ids(self) -> List[str]:
        return [r for r in ALLOWED_ROBOTS if r in registry.ids()]

    def refresh(self) -> None:
        """Reconstruit la liste de cards si necessaire."""
        ids = self._allowed_ids()
        for rid in list(self._cards.keys()):
            if rid not in ids:
                self._cards[rid].destroy()
                del self._cards[rid]
        for rid in ids:
            if rid not in self._cards:
                card = RobotCard(self._list, robot_id=rid,
                                 on_toggle_connect=self._toggle_connect,
                                 on_reboot=self._reboot_one,
                                 on_toggle_torque=self._toggle_torque,
                                 on_pos_machine=self._pos_machine,
                                 on_pos_travail=self._pos_travail,
                                 on_stop_urgence=self._stop_urgence)
                card.pack(side="top", fill="x", pady=4)
                self._cards[rid] = card
        for card in self._cards.values():
            card.refresh()

    def _tick(self) -> None:
        for card in self._cards.values():
            try:
                card.refresh()
            except tk.TclError:
                pass
        self.after(1000, self._tick)

    def _tick_hotplug(self) -> None:
        """Detecte les U2D2 hot-plug (branches / debranches) :

        - Branche -> connect un robot disponible + torque ON
        - Debranche -> disconnect le robot dont le port n'existe plus
        - Apres chaque cycle : propage la config du master aux autres

        En mode simulation (--sim) il n'y a aucun U2D2 : ce tick
        deconnecterait le robot simule 3 s apres sa connexion. On ne
        le lance pas du tout dans ce mode.
        """
        try:
            from xrv22.core.state_store import store
            if store.get_system().simulation_mode:
                return
        except Exception:
            pass
        try:
            from xrv22.main_pi import (auto_connect_all_u2d2,
                                       ensure_valid_master,
                                       list_u2d2_ports)
        except Exception:
            self.after(3000, self._tick_hotplug)
            return

        try:
            ports = set(list_u2d2_ports())
            # Disconnect des robots dont le port a disparu
            for rid in registry.ids():
                ctrl = registry.get(rid)
                if not (ctrl and ctrl.is_connected):
                    continue
                if ctrl.port_name and ctrl.port_name not in ports:
                    threading.Thread(target=ctrl.disconnect,
                                     daemon=True).start()

            # Note : propagation master deja faite via les hooks backend
            # (set_home_machine/work/motor_limit/motion_params). Pas besoin
            # de la rappeler periodiquement.
            def _worker():
                ensure_valid_master()
                auto_connect_all_u2d2()

            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass
        finally:
            try:
                self.after(3000, self._tick_hotplug)
            except tk.TclError:
                pass

    # ── Helpers ──────────────────────────────────────────────────
    @staticmethod
    def _find_u2d2_ports() -> List[str]:
        if list_ports is None:
            return []
        return [p.device for p in list_ports.comports() if p.vid == 0x0403]

    @classmethod
    def _ports_already_used(cls) -> set:
        used = set()
        for rid in registry.ids():
            ctrl = registry.get(rid)
            if ctrl and ctrl.is_connected and ctrl.port_name:
                used.add(ctrl.port_name)
        return used

    # ── Actions ──────────────────────────────────────────────────
    def _toggle_connect(self, rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None:
            return
        if ctrl.is_connected:
            threading.Thread(target=ctrl.disconnect, daemon=True).start()
            return
        port = ctrl.port_name
        if not port:
            used = self._ports_already_used()
            free = [p for p in self._find_u2d2_ports() if p not in used]
            port = free[0] if free else None
        if not port:
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Aucun port U2D2 libre disponible"})
            return

        def _connect_then_torque():
            try:
                if ctrl.connect(port) and hasattr(ctrl, "set_torque"):
                    ctrl.set_torque(True)
            except Exception:
                pass

        threading.Thread(target=_connect_then_torque, daemon=True).start()

    def _reboot_one(self, rid: str) -> None:
        """Reboot complet : reboot moteurs + disconnect + reconnect
        + torque ON (sequence automatique pour repartir d'un etat propre)."""
        ctrl = registry.get(rid)
        if ctrl is None or not ctrl.is_connected:
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": f"{rid} : connecte le robot d'abord"})
            return
        profile = profiles.get(rid)
        motor_ids = list(profile.motor_ids) if profile else []
        port = ctrl.port_name

        def _worker():
            # 1) Reboot tous les moteurs
            for mid in motor_ids:
                try:
                    ctrl.reboot_motor(mid)
                except Exception:
                    pass
                time.sleep(0.05)
            # 2) Disconnect propre
            try:
                ctrl.disconnect()
            except Exception:
                pass
            # 3) Petit delai pour laisser les moteurs revenir
            time.sleep(0.6)
            # 4) Reconnect sur le meme port
            target_port = port or self._find_u2d2_port()
            if not target_port:
                bus.publish("ui.toast",
                            {"level": "warn",
                             "message": f"{rid} : aucun port U2D2 dispo"})
                return
            try:
                ok = ctrl.connect(target_port)
            except Exception:
                ok = False
            if not ok:
                bus.publish("ui.toast",
                            {"level": "warn",
                             "message": f"Reboot {rid} : reconnexion echouee"})
                return
            # 5) Torque ON (avec retry si erreur HW residuelle)
            try:
                from xrv22.main_pi import _safe_torque_with_reboot
                _safe_torque_with_reboot(ctrl, rid)
            except Exception:
                pass
            bus.publish("ui.toast",
                        {"level": "info",
                         "message": f"Reboot {rid} : OK ({len(motor_ids)} moteurs)"})

        threading.Thread(target=_worker, daemon=True).start()

    def _toggle_torque(self, rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None or not ctrl.is_connected:
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Connecte le robot avant le torque"})
            return
        new_state = not bool(getattr(ctrl, "torque_enabled", False))

        def _worker():
            ok = ctrl.set_torque(new_state)
            bus.publish("robot.torque_changed",
                        {"robot_id": rid, "enabled": new_state, "ok": ok})

        threading.Thread(target=_worker, daemon=True).start()

    def _pos_machine(self, rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None or not ctrl.is_connected:
            return

        def _worker():
            ok, msg = ctrl.safe_home()
            if not ok:
                bus.publish("ui.toast", {"level": "warn", "message": msg})

        threading.Thread(target=_worker, daemon=True).start()

    def _pos_travail(self, rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None or not ctrl.is_connected:
            return

        def _worker():
            ok, msg = ctrl.go_home_work()
            if not ok:
                bus.publish("ui.toast", {"level": "warn", "message": msg})

        threading.Thread(target=_worker, daemon=True).start()

    def _stop_urgence(self, rid: str) -> None:
        ctrl = registry.get(rid)
        if ctrl is None:
            return
        try:
            ctrl.emergency_stop()
        except Exception:
            pass
        bus.publish("ui.toast",
                    {"level": "warn",
                     "message": f"STOP URGENCE — {rid}"})
