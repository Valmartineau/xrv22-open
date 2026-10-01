"""
xrv22/ui_pi/screen_pilotage.py
───────────────────────────────
Ecran Pilotage tactile : controle direct des 7 axes d'un robot via sliders.

Layout (800 x 480) :
  Header 52       (retour + titre projet + horloge)
  Robot bar 48    (selecteur robot + torque + mode direct)
  Sliders 316     (7 axes, 44px chacun + separateurs)
  Action bar 64   (LIRE / GO / STOP / SAUVEGARDER)

Comportement :
  - Torque ON  : moteurs rigides, mouvements possibles
  - Torque OFF : moteurs libres (positionnement manuel), sliders bloques en commande
  - Mode direct ON : le relachement du slider envoie le move automatiquement
  - Mode direct OFF : il faut taper GO pour envoyer les positions des sliders
  - Ghost (petit point gris) : position hardware live (mise a jour 300ms)
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Dict, List, Optional

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None  # pyserial absent — pas de scan

from xrv22.config import gripper_mm
from xrv22.core.jog_engine import jog_engine
from xrv22.core.state_store import store
from xrv22.library.library_manager import library
from xrv22.library.models import PositionModel
from xrv22.robots.robot_controller import RobotController
from xrv22.robots.robot_profiles import profiles
from xrv22.robots.robot_registry import registry
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger
from xrv22.theme import theme as T
from xrv22.ui_pi import theme_pi as P
from xrv22.ui_pi.multitouch import MultiTouchDispatcher
from xrv22.ui_pi.widgets_pi import (HoldButton, Joystick2D, JoystickStick,
                                     TouchButton, TouchSlider, draw_neu_rect)

# Noms d'axes lisibles (UI Pi : axe 3 cache, axe 2 controle 2+3 couples)
AXIS_NAMES = {
    1: "Base",
    2: "Epaule",   # pilote aussi axe 3 via couplage
    4: "Coude",
    5: "Tangage",
    6: "Poignet",
    7: "Pince",
}

# Axes affiches dans l'UI Pi (axe 3 est masque — couple a l'axe 2)
# Le couplage est applique cote backend (RobotController._apply_coupling)
# via la config persistee dans library.hardware.coupling.
VISIBLE_AXES = (1, 2, 4, 5, 6, 7)


def _calculate_auto_duration(target: Dict[int, int],
                             current: Dict[int, int],
                             max_speed: int = 1000) -> float:
    """Duree auto basee sur le plus grand delta (+50% marge)."""
    if not target or not current:
        return 1.0
    max_delta = 0
    for mid, tpos in target.items():
        delta = abs(tpos - current.get(mid, tpos))
        max_delta = max(max_delta, delta)
    dur = (max_delta / max_speed) * 1.5
    return max(0.3, min(dur, 15.0))


def _gripper_fmt(v: int) -> str:
    """Conversion ticks Dynamixel → écart réel mm pour l'axe 7 (pince),
    via la calibration centralisée (xrv22.config.gripper_mm)."""
    return f"{gripper_mm(v):.1f} mm"


def _make_gripper_fmt(lo: int, hi: int):
    """value_fmt pince : écart réel en mm (calibration partagée, indépendante
    des soft-limits). lo/hi conservés pour compat de signature."""
    return _gripper_fmt


class ScreenPilotage(tk.Frame):
    """Pilotage direct d'un robot via sliders tactiles."""

    def __init__(self, parent, on_back: Callable[[], None] = lambda: None):
        super().__init__(parent, bg=T.BG, width=P.SCREEN_W, height=P.SCREEN_H)
        self.pack_propagate(False)
        self._on_back = on_back
        self._active_rid: str = ""
        self._sliders: Dict[int, TouchSlider] = {}
        self._torque_on = False
        # Le pilotage direct n'est JAMAIS actif par defaut : il faut prendre
        # la main explicitement (bouton "Prendre la main" -> torque + direct +
        # control_owner=pi). Sinon on pourrait jogger des le torque ON, sans
        # geste delibere ni revendication du controle (double-pilote possible).
        self._direct_mode = False
        # Axes actifs au tick precedent — sert (1) a detecter le DEBUT d'un
        # jog pour re-synchroniser le profil moteur, (2) a n'ecrire un axe
        # relache qu'UNE fois (sinon on combattrait un Home / scenario).
        self._jog_active_axes = set()
        # Modificateurs (touches "L1"/"R1") : changent les axes pilotes
        self._mod_left = False    # joy gauche Y : Coude au lieu d'Epaule
        self._mod_right = False   # joy droit X : Pince au lieu de Poignet

        # Mode joystick : vitesse normalisee -1..+1 par moteur (drag actif)
        self._joystick_v: Dict[int, float] = {}
        # Cible en attente (utilisee par _stop_jog_for_current_robot)
        self._pending_target: Dict[int, int] = {}
        self._tick_jog_id: Optional[str] = None
        self._jog_period_ms = 50         # 20 Hz d'envoi
        self._jog_deadband = 0.06        # zone morte au centre du joystick
        # Note : toute l'integration du jog (rampe soft-start, lead feed-forward,
        # vitesses max par axe, profil moteur) vit desormais dans JogIntegrator /
        # JogEngine cote serveur (chantier JogEngine J1-J4). Le Pi tactile ne fait
        # que PRODUIRE la velocite (cf _tick_jog -> jog_engine.set_velocity).

        # Dispatcher multi-touch (Tk ne route qu'un doigt par defaut). On
        # bypasse Tk pour les joysticks 2D et sticks 1D.
        self._mt = MultiTouchDispatcher(self.winfo_toplevel())
        self._mt.start()

        # ── Robot bar (selection + torque + direct) ───────────────
        self._robot_bar = tk.Frame(self, bg=T.SIDEBAR, height=36)
        self._robot_bar.pack(side="top", fill="x")
        self._robot_bar.pack_propagate(False)
        self._tabs_robot: Dict[str, TouchButton] = {}
        self._build_robot_tabs()

        # Bouton "Prendre la main" deplace sous les sticks centraux
        # (cree dans _rebuild_sliders avec largeur center_w pour stack
        # avec Position travail + STOP URGENCE).

        # ── Sliders ───────────────────────────────────────────────
        self._sliders_frame = tk.Frame(self, bg=T.BG)
        self._sliders_frame.pack(side="top", fill="both", expand=True,
                                 padx=P.PAD_SM, pady=0)

        # ── Actions bar (cachee — actions deplacees dans onglet HOME) ──
        self._act_bar = tk.Frame(self, bg=T.BG, height=0)

        # Boutons hors ecran (instancies pour preserver l'API mais non places)
        btn_w, btn_h = 1, 1
        gap = 0
        x0 = -1000  # hors-ecran
        self._btn_read = TouchButton(
            self._act_bar, text="LIRE", icon="\u21BB",
            width=btn_w, height=btn_h,
            accent=T.SURFACE_HI, fg=T.C_AMB, font=P.F_BTN,
            command=self._read_positions)
        self._btn_read.place(x=x0, y=2)
        self._btn_go = TouchButton(
            self._act_bar, text="GO", icon="\u25B6",
            width=btn_w, height=btn_h,
            accent=T.C_OK_DIM, fg=T.C_OK, font=P.F_BTN_LG,
            command=self._goto_sliders)
        self._btn_go.place(x=x0 + (btn_w + gap), y=2)
        self._btn_stop = TouchButton(
            self._act_bar, text="STOP", icon="\u25A0",
            width=btn_w, height=btn_h,
            accent=T.C_ERR_DIM, fg=T.C_ERR, font=P.F_BTN,
            command=self._stop_motion)
        self._btn_stop.place(x=x0 + (btn_w + gap) * 2, y=2)
        self._btn_save = TouchButton(
            self._act_bar, text="SAUVEGARDER", icon="\u2714",
            width=btn_w, height=btn_h,
            accent=T.C_MAG_DIM2, fg=T.C_MAG_4, font=P.F_BTN,
            command=self._save_position)
        self._btn_save.place(x=x0 + (btn_w + gap) * 3, y=2)

        # Bus
        bus.subscribe("robot.added",          lambda _: self._refresh_robots())
        bus.subscribe("robot.removed",        lambda _: self._refresh_robots())
        bus.subscribe("robot.connected",      self._on_connection_change)
        bus.subscribe("robot.disconnected",   self._on_connection_change)
        bus.subscribe("robot.master_changed", self._on_master_changed)
        # Sync robot actif depuis le web (ou autre UI)
        bus.subscribe_ui("system.active_robot_changed", self._on_active_robot_changed, self)

        # Thread daemon : lit positions HW (600ms) sans bloquer le tick jog
        import threading as _threading
        _threading.Thread(target=self._read_positions_loop, daemon=True).start()
        # Tick ghost positions (300ms : refresh visuel depuis le store)
        self.after(300, self._tick_ghost)
        # Tick jog (50ms : envoi continu de la commande joystick)
        self.after(self._jog_period_ms, self._tick_jog)

    # ── Chargement projet ─────────────────────────────────────────
    def load_project(self, project_name: str = "") -> None:
        """Refresh robots (appele au switch d'onglet ou chargement projet)."""
        self._refresh_robots()

    def refresh(self) -> None:
        """Alias pratique pour tab switch."""
        self._refresh_robots()

    # ── Selection robot ───────────────────────────────────────────
    def _refresh_robots(self) -> None:
        # On limite aux robots actifs (memes que la page HOME : Robot 1/2/3)
        from xrv22.ui_pi.screen_home import ALLOWED_ROBOTS
        all_ids = registry.ids()
        ids = [r for r in ALLOWED_ROBOTS if r in all_ids]
        if not ids:
            self._active_rid = ""
            self._update_robot_tabs()
            self._clear_sliders()
            return
        # Source de verite = master du registry (synchronise avec HOME)
        master = registry.master_id
        target = master if master in ids else ids[0]
        if self._active_rid != target:
            self._active_rid = target
        self._update_robot_tabs()
        self._rebuild_sliders()

    def _build_robot_tabs(self) -> None:
        """Cree les sous-onglets robot_1/2/3 dans la robot_bar
        avec la couleur du profile de chaque robot."""
        from xrv22.ui_pi.screen_home import ALLOWED_ROBOTS
        for w in self._robot_bar.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        self._tabs_robot.clear()
        margin, gap, h = 5, 5, 32
        n = len(ALLOWED_ROBOTS)
        if n == 0:
            return
        btn_w = (P.SCREEN_W - margin * 2 - gap * (n - 1)) // n
        for i, rid in enumerate(ALLOWED_ROBOTS):
            profile = profiles.get(rid)
            color = profile.color if profile else T.C_AMB
            raw = profile.name if profile else rid
            label = raw.replace("XRV22", "").strip().replace("robot_", "Robot ")
            btn = TouchButton(
                self._robot_bar, text=label, width=btn_w, height=h,
                accent=T.SURFACE_HI, fg=color, font=P.F_BTN,
                command=lambda r=rid: self._select_robot_tab(r))
            btn.place(x=margin + i * (btn_w + gap), y=2)
            self._tabs_robot[rid] = btn
        self._update_robot_tabs()

    def _update_robot_tabs(self) -> None:
        """Met a jour les couleurs des onglets : actif = fond couleur
        profile + texte BG ; inactif = fond neutre + texte couleur profile."""
        for rid, btn in self._tabs_robot.items():
            profile = profiles.get(rid)
            color = profile.color if profile else T.C_AMB
            if rid == self._active_rid:
                btn.set_accent(color)
                btn.set_fg(T.BG)
            else:
                btn.set_accent(T.SURFACE_HI)
                btn.set_fg(color)

    def _select_robot_tab(self, rid: str) -> None:
        """Switch vers le robot rid (clic onglet)."""
        from xrv22.ui_pi.screen_home import ALLOWED_ROBOTS
        ids = [r for r in ALLOWED_ROBOTS if r in registry.ids()]
        if rid not in ids or rid == self._active_rid:
            return
        if self._active_rid not in ids:
            delta = ids.index(rid)
        else:
            delta = ids.index(rid) - ids.index(self._active_rid)
        self._cycle_robot(delta)

    def _on_connection_change(self, payload: dict) -> None:
        if payload.get("robot_id") == self._active_rid:
            # Rafraichit les sliders quand la connexion change
            self._rebuild_sliders()
            self._update_torque_btn()

    def _on_master_changed(self, _payload: dict) -> None:
        # Synchronisation avec HOME : on suit le master du registry
        self._refresh_robots()

    def _on_active_robot_changed(self, payload: dict) -> None:
        """Sync UI quand le robot actif change depuis le web (ou autre source).
        Appele via subscribe_ui => execute dans le main thread Tk."""
        rid = payload.get("robot_id")
        if not rid or rid == self._active_rid:
            return
        self._select_robot_tab(rid)

    def _cycle_robot(self, delta: int) -> None:
        from xrv22.ui_pi.screen_home import ALLOWED_ROBOTS
        ids = [r for r in ALLOWED_ROBOTS if r in registry.ids()]
        if not ids:
            return
        if self._active_rid not in ids:
            new_rid = ids[0]
        else:
            idx = (ids.index(self._active_rid) + delta) % len(ids)
            new_rid = ids[idx]
        if new_rid == self._active_rid:
            return  # rien a faire

        # 1) Arret immediat de tout mouvement en cours sur l'ancien robot
        self._stop_jog_for_current_robot()

        # 2) Sortie du mode pilotage direct (mais on garde le TORQUE ON sur
        #    l'ancien robot pour qu'il maintienne sa position).
        if self._direct_mode:
            self._direct_mode = False
            self._update_takeover_btn()

        # 3) Switch master (synchronise HOME)
        registry.set_master(new_rid)
        bus.publish("robot.master_changed", {"robot_id": new_rid})
        self._active_rid = new_rid
        # Propager le changement au backend (store SSOT) -> web + autres UIs
        # set_active_robot est idempotent (guard interne) : pas de loop.
        store.set_active_robot(new_rid)
        self._update_robot_tabs()
        self._rebuild_sliders()
        # 4) Force re-application du profile vitesse pour uniformiser la
        #    sensation entre robots (set_profile vel/acc identiques au boot).
        new_ctrl = registry.get(new_rid)
        if new_ctrl is not None and getattr(new_ctrl, "is_connected", False):
            try:
                new_ctrl.apply_motion_profile()
            except Exception:
                pass

    def _stop_jog_for_current_robot(self) -> None:
        """Arret propre : vide les joysticks + envoie la position
        courante comme cible figee pour eviter une derive.
        Utilise read_positions() (lecture HW fraiche) plutot que
        get_positions() (cache 600ms) : sinon le write_positions_direct
        envoie une cible decalee et le robot saute au switch d'onglet."""
        self._joystick_v.clear()
        self._pending_target.clear()
        jog_engine.release(self._active_rid)
        ctrl = self._active_ctrl()
        if ctrl is not None and getattr(ctrl, "is_connected", False):
            try:
                if hasattr(ctrl, "read_positions"):
                    cur = ctrl.read_positions()
                elif hasattr(ctrl, "get_positions"):
                    cur = ctrl.get_positions()
                else:
                    cur = {}
                if cur:
                    ctrl.write_positions_direct(cur)
            except Exception:
                pass
        # Reset visuel des joysticks
        for sl in self._sliders.values():
            stop = getattr(sl, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass

    def _prev_robot(self) -> None:
        self._cycle_robot(-1)

    def _next_robot(self) -> None:
        self._cycle_robot(+1)

    @staticmethod
    def _unbind_tk(widget) -> None:
        """Desactive les bindings souris Tk sur ce widget pour
        laisser le dispatcher multi-touch les gerer (et eviter les
        doubles dispatch single-touch via Tk + multi-touch via evdev)."""
        for seq in ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>", "<Leave>"):
            try:
                widget.unbind(seq)
            except Exception:
                pass

    # ── Sliders ───────────────────────────────────────────────────
    def _clear_sliders(self) -> None:
        for w in self._sliders_frame.winfo_children():
            w.destroy()
        self._sliders.clear()

    def _rebuild_sliders(self) -> None:
        """Recree les 7 sliders pour le robot actif."""
        self._clear_sliders()
        # Reset du routing multi-touch (les anciens widgets sont morts)
        try:
            self._mt.clear()
        except Exception:
            pass
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        profile = profiles.get(self._active_rid)
        accent = profile.color if profile else T.C_AMB
        snap = store.get_robot(self._active_rid)
        positions = snap.positions if snap and snap.positions else {}

        # Layout "manette" :
        #   [JOYSTICK 2D 1+2]  [Coude]   [JOYSTICK 2D 5+6]
        #                      [Pince]
        #
        # axes 1+2 : joystick gauche (1=X gauche-droite, 2=Y haut-bas)
        # axes 5+6 : joystick droit  (6=X gauche-droite, 5=Y haut-bas)
        # axe 4 (Coude) + axe 7 (Pince) : sticks 1D au centre

        joy_size = 220
        cx_left = 16 + joy_size // 2
        cx_right = P.SCREEN_W - 16 - joy_size // 2
        joy_y = 12

        # Joystick gauche : X = motor 1 (Base), Y = motor 2 (Epaule)
        joy_left = Joystick2D(
            self._sliders_frame,
            label_x=AXIS_NAMES[1], motor_id_x=1,
            label_y=AXIS_NAMES[2], motor_id_y=2,
            accent=accent, size=joy_size,
            on_velocity=self._on_joystick_left)
        joy_left.place(x=16, y=joy_y)
        self._sliders[1] = joy_left  # ref pour stop() au switch
        # On enregistre le meme widget pour mid=2 (les vels arrivent ensemble)
        self._unbind_tk(joy_left)
        self.after_idle(lambda w=joy_left: self._mt.register(w))

        # Bouton "Mode Pince" sous le joystick GAUCHE (modifie le joy droit)
        mod_pince_btn = HoldButton(
            self._sliders_frame, text="Mode Pince",
            accent=accent,
            on_state_change=self._set_mod_right,
            width=joy_size, height=44)
        mod_pince_btn.place(x=16, y=joy_y + joy_size + 6)
        self._sliders["mod_pince"] = mod_pince_btn
        self._unbind_tk(mod_pince_btn)
        self.after_idle(lambda w=mod_pince_btn: self._mt.register(w))

        # Joystick droit : X = motor 6 (Poignet), Y = motor 5 (Tangage)
        joy_right = Joystick2D(
            self._sliders_frame,
            label_x=AXIS_NAMES[6], motor_id_x=6,
            label_y=AXIS_NAMES[5], motor_id_y=5,
            accent=accent, size=joy_size,
            on_velocity=self._on_joystick_right)
        joy_right.place(x=P.SCREEN_W - 16 - joy_size, y=joy_y)
        self._sliders[5] = joy_right
        self._sliders[6] = joy_right
        self._unbind_tk(joy_right)
        self.after_idle(lambda w=joy_right: self._mt.register(w))

        # Bouton "Mode Coude" sous le joystick DROIT (modifie le joy gauche)
        mod_coude_btn = HoldButton(
            self._sliders_frame, text="Mode Coude",
            accent=accent,
            on_state_change=self._set_mod_left,
            width=joy_size, height=44)
        mod_coude_btn.place(x=P.SCREEN_W - 16 - joy_size, y=joy_y + joy_size + 6)
        self._sliders["mod_coude"] = mod_coude_btn
        self._unbind_tk(mod_coude_btn)
        self.after_idle(lambda w=mod_coude_btn: self._mt.register(w))

        # Sticks 1D centraux : Coude (axe 4) et Pince (axe 7)
        center_x = joy_size + 32
        center_w = P.SCREEN_W - 2 * (joy_size + 32) + 16
        for i, mid in enumerate([4, 7]):
            lo, hi = (profile.soft_limits.get(mid, (0, 4095))
                      if profile else (0, 4095))
            val = positions.get(mid, (lo + hi) // 2)
            label = AXIS_NAMES.get(mid, f"Axe {mid}")
            if mid == 7:
                fmt = _make_gripper_fmt(lo, hi)
            else:
                fmt = lambda v: str(v)
            # Axe 4 (Coude) inverse : pousse a droite = coude descend
            sign = -1.0 if mid == 4 else 1.0
            sl = JoystickStick(
                self._sliders_frame, label=label, motor_id=mid,
                value=val, accent=accent,
                on_velocity=lambda v, m=mid, s=sign: self._on_joystick(m, s * v),
                value_fmt=fmt,
                width=center_w, height=56)
            sl.place(x=center_x, y=20 + i * 70)
            self._sliders[mid] = sl
            self._unbind_tk(sl)
            self.after_idle(lambda w=sl: self._mt.register(w))

        # 4 boutons empiles sous les sticks centraux Coude/Pince :
        #   1) Prendre la main      (haut)
        #   2) Position travail
        #   3) Torque ON/OFF
        #   4) STOP URGENCE         (bas)
        btn_y = 20 + 2 * 70   # juste sous les sticks (Pince finit ~y=146)
        self._btn_takeover = TouchButton(
            self._sliders_frame, text="Prendre la main",
            width=center_w, height=48,
            accent=T.SURFACE_HI, fg=T.TEXT_MED, font=P.F_BTN,
            command=self._toggle_takeover)
        self._btn_takeover.place(x=center_x, y=btn_y)
        self._sliders["takeover"] = self._btn_takeover

        btn_work = TouchButton(
            self._sliders_frame, text="Position travail",
            width=center_w, height=48,
            accent=T.C_AMB_DIM2, fg=T.C_AMB, font=P.F_BTN,
            command=self._goto_work_position)
        btn_work.place(x=center_x, y=btn_y + 56)
        self._sliders["pos_travail"] = btn_work

        self._btn_torque = TouchButton(
            self._sliders_frame, text="TORQUE ON",
            width=center_w, height=48,
            accent=T.C_OK_DIM, fg=T.C_OK, font=P.F_BTN,
            command=self._toggle_torque)
        self._btn_torque.place(x=center_x, y=btn_y + 2 * 56)
        self._sliders["torque"] = self._btn_torque
        self._update_torque_btn()

        stop_btn = TouchButton(
            self._sliders_frame, text="STOP URGENCE",
            width=center_w, height=64,
            accent=T.C_ERR_DIM, fg=T.C_ERR, font=P.F_BTN,
            command=self._emergency_stop)
        stop_btn.place(x=center_x, y=btn_y + 3 * 56)
        self._sliders["stop_urg"] = stop_btn

    def _goto_work_position(self) -> None:
        """Lance le retour position travail sur le robot actif."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            bus.publish("ui.toast",
                        {"level": "warn", "message": "Aucun robot actif"})
            return
        if not getattr(ctrl, "is_connected", False):
            bus.publish("ui.toast",
                        {"level": "warn", "message": "Robot non connecte"})
            return
        bus.publish("ui.toast",
                    {"level": "info",
                     "message": f"Position travail — {self._active_rid}"})
        import threading
        def _worker():
            try:
                ctrl.go_home_work()
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _emergency_stop(self) -> None:
        """Arret urgence du robot actif depuis l'ecran PILOTAGE.
        Met aussi torque OFF cote UI et sort du mode 'Prendre la main' pour
        eviter le spam tick jog (torque=False direct=True)."""
        if not self._active_rid:
            return
        ctrl = registry.get(self._active_rid)
        if ctrl is None:
            return
        try:
            ctrl.emergency_stop()
        except Exception:
            pass
        # Sync etats locaux : emergency_stop force torque OFF cote HW.
        self._torque_on = False
        self._direct_mode = False
        self._update_takeover_btn()
        bus.publish("ui.toast",
                    {"level": "warn",
                     "message": f"STOP URGENCE — {self._active_rid}"})
        self._stop_jog_for_current_robot()

    def _set_mod_left(self, held: bool) -> None:
        """Etat du modificateur gauche (Coude)."""
        self._mod_left = held
        # Au changement de mode, on stoppe l'axe sortant pour eviter qu'il
        # continue a bouger en residuel.
        if held:
            self._joystick_v[2] = 0.0
        else:
            self._joystick_v[4] = 0.0

    def _set_mod_right(self, held: bool) -> None:
        """Etat du modificateur droit (Pince)."""
        self._mod_right = held
        if held:
            self._joystick_v[6] = 0.0
        else:
            self._joystick_v[7] = 0.0

    def _on_joystick_left(self, vx: float, vy: float) -> None:
        """Joystick 2D gauche : X = Base (inverse), Y = Epaule
        ou Coude si modificateur gauche tenu."""
        # Base : inversion gauche-droite
        self._on_joystick(1, -vx)
        # Y : Epaule par defaut, Coude si modificateur enfonce.
        # Coude aligne sur Epaule (meme sens vertical).
        if self._mod_left:
            self._on_joystick(4, vy)
            self._joystick_v[2] = 0.0
        else:
            self._on_joystick(2, vy)
            self._joystick_v[4] = 0.0

    def _on_joystick_right(self, vx: float, vy: float) -> None:
        """Joystick 2D droit : X = Poignet ou Pince (modificateur),
        Y = Tangage (inverse)."""
        if self._mod_right:
            self._on_joystick(7, vx)
            self._joystick_v[6] = 0.0
        else:
            self._on_joystick(6, vx)
            self._joystick_v[7] = 0.0
        # Tangage : inversion haut-bas
        self._on_joystick(5, -vy)

    def _on_joystick(self, motor_id: int, vel_norm: float) -> None:
        """Recoit la vitesse normalisee (-1..+1) du stick.

        Pilotage actif UNIQUEMENT apres prise de main explicite : tant que
        (direct + torque) n'est pas armé via le bouton "Prendre la main", on
        ignore les sticks (aucun jog, aucune cible accumulée). Plus d'auto-
        takeover : bouger un robot exige une demande délibérée de l'opérateur.
        """
        if not (self._direct_mode and self._torque_on):
            self._joystick_v[motor_id] = 0.0
            return

        if abs(vel_norm) < self._jog_deadband:
            self._joystick_v[motor_id] = 0.0
            return
        sign = 1.0 if vel_norm > 0 else -1.0
        a = (abs(vel_norm) - self._jog_deadband) / max(0.01, 1.0 - self._jog_deadband)
        self._joystick_v[motor_id] = sign * a * a  # easing quadratique

    def _tick_jog(self) -> None:
        """CC=8 — Tick periodique : envoi continu pendant le drag.

        Pour chaque moteur avec vitesse non nulle, calcule new_target =
        position_actuelle + vel * MAX_SPEED * dt, clamp aux soft-limits,
        applique le couplage axe 2 -> axe 3 et envoie via direct write.
        """
        # Reschedule
        try:
            self._tick_jog_id = self.after(self._jog_period_ms, self._tick_jog)
        except tk.TclError:
            return

        # Arbitrage : si le web a pris la main pendant qu'on pilotait en Pi, on
        # cesse de piloter (abandon : on retire notre intégrateur SANS toucher
        # au profil ni à l'owner — le web les possède) et on quitte le direct.
        if self._direct_mode:
            _arb_ctrl = self._active_ctrl()
            if (_arb_ctrl is not None
                    and getattr(_arb_ctrl, "control_owner", None) == "web"):
                jog_engine.abandon(self._active_rid)
                self._direct_mode = False
                self._joystick_v.clear()
                self._pending_target.clear()
                for _sl in self._sliders.values():
                    _stop_fn = getattr(_sl, "stop", None)
                    if callable(_stop_fn):
                        try:
                            _stop_fn()
                        except Exception:
                            pass
                try:
                    self.after(0, self._update_takeover_btn)
                except Exception:
                    pass
                return

        # Hors mode pilotage : rien à produire.
        if not (self._torque_on and self._direct_mode):
            self._jog_active_axes = set()
            return
        rid = self._active_rid
        if not rid:
            self._jog_active_axes = set()
            return

        # PRODUCTEUR : on pousse l'intention de vélocité (tous axes, y compris
        # les 0.0 des axes relâchés → le JogEngine écrit une dernière fois puis
        # s'arrête pile). L'intégration (rampe+lead+clamp), l'écriture série et
        # le miroir store sont faits par le JogEngine. Plus de duplication ici.
        # Spec : docs/superpowers/specs/2026-06-09-xrv22-jog-engine-design.md (J2).
        jog_engine.set_velocity(rid, dict(self._joystick_v))
        self._jog_active_axes = {
            m for m, v in self._joystick_v.items() if abs(v) >= 0.001
        }

    # ── Actions ───────────────────────────────────────────────────
    def _active_ctrl(self) -> Optional[RobotController]:
        return registry.get(self._active_rid) if self._active_rid else None

    def _read_positions(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl is None:
            return
        try:
            positions = ctrl.read_positions()
        except Exception:
            return
        for mid, pos in positions.items():
            sl = self._sliders.get(mid)
            if sl:
                sl.set_value(pos)

    def _goto_sliders(self) -> None:
        """Envoie les positions de tous les sliders au robot."""
        ctrl = self._active_ctrl()
        if ctrl is None or not self._torque_on:
            return
        self._release_jog_for_motion()
        target = {mid: sl.get_value() for mid, sl in self._sliders.items()}
        current = ctrl.get_positions() if hasattr(ctrl, "get_positions") else {}
        duration = _calculate_auto_duration(target, current)
        ok, msg = ctrl.move(target, duration_s=duration)
        if not ok:
            bus.publish("ui.toast", {"level": "warn", "message": msg})

    def _stop_motion(self) -> None:
        ctrl = self._active_ctrl()
        if ctrl and hasattr(ctrl, "soft_stop"):
            ctrl.soft_stop()

    def _release_jog_for_motion(self) -> None:
        """Arbitrage : sortir du jog (maintien teach-pendant) avant un mouvement
        commandé (Home, suite…). Sinon les réécritures de maintien à 33Hz
        combattraient le mouvement. Le torque RESTE on (le robot tient sa pose),
        on quitte juste le mode pilotage direct."""
        if self._direct_mode:
            self._stop_jog_for_current_robot()
            self._direct_mode = False
            self._update_takeover_btn()

    def _goto_home_work(self) -> None:
        """Va a la position de travail du robot actif."""
        ctrl = self._active_ctrl()
        if ctrl is None or not self._torque_on:
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Active le torque avant de bouger"})
            return
        self._release_jog_for_motion()
        ok, msg = ctrl.go_home_work()
        if not ok:
            bus.publish("ui.toast", {"level": "warn", "message": msg})

    def _goto_home_machine(self) -> None:
        """Va a la position machine via safe_home (passe par travail)."""
        ctrl = self._active_ctrl()
        if ctrl is None or not self._torque_on:
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Active le torque avant de bouger"})
            return
        self._release_jog_for_motion()
        ok, msg = ctrl.safe_home()
        if not ok:
            bus.publish("ui.toast", {"level": "warn", "message": msg})

    def _save_position(self) -> None:
        """Sauvegarde la position courante (sliders) dans la library."""
        if not self._sliders:
            return
        name = f"pos_{time.strftime('%H%M%S')}"
        positions = {mid: sl.get_value() for mid, sl in self._sliders.items()}
        model = PositionModel(
            name=name, robot_id=self._active_rid, positions=positions)
        library.save_position(model)
        bus.publish("ui.toast",
                    {"level": "info", "message": f"Position '{name}' enregistree"})

    # ── Prendre la main ───────────────────────────────────────────
    def _toggle_takeover(self) -> None:
        """Active/desactive Torque + Direct ensemble (async non-bloquant).

        L'appel set_torque() peut prendre 200-500ms (7 moteurs) ;
        on l'execute dans un thread pour ne pas figer l'UI Tk.
        """
        ctrl = self._active_ctrl()
        if ctrl is None:
            bus.publish("ui.toast",
                        {"level": "warn", "message": "Aucun robot actif"})
            return
        if not getattr(ctrl, "is_connected", False):
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Connecte le robot avant"})
            return

        currently_active = self._torque_on and self._direct_mode
        new_active = not currently_active

        # Lacher la main : on quitte juste le mode pilotage direct ;
        # le TORQUE reste ON pour que les moteurs maintiennent leur position.
        if not new_active:
            self._direct_mode = False
            self._joystick_v.clear()
            self._pending_target.clear()
            for sl in self._sliders.values():
                stop = getattr(sl, "stop", None)
                if callable(stop):
                    try:
                        stop()
                    except Exception:
                        pass
            # Release JogEngine : profil confort restauré + control_owner None
            # + publish robot.control_changed (porté par release).
            jog_engine.release(self._active_rid)
            self._update_takeover_btn()
            return

        # Prendre la main : torque ON + direct ON, en thread (set_torque
        # peut prendre 200-500ms a cause des 7 moteurs). Si echec partiel
        # (erreur HW moteur), on reboot les moteurs et on retry.
        self._btn_takeover.set_text("...")
        self._btn_takeover.set_accent(T.SURFACE_HI)

        import threading
        rid = self._active_rid

        def _worker():
            try:
                from xrv22.main_pi import _safe_torque_with_reboot
                _safe_torque_with_reboot(ctrl, rid)
            except Exception:
                pass
            ok = bool(getattr(ctrl, "torque_enabled", False))

            def _finish():
                if not ok:
                    bus.publish("ui.toast",
                                {"level": "warn",
                                 "message": "Torque non actif (voir logs)"})
                    self._update_takeover_btn()
                    return
                self._torque_on = True
                self._direct_mode = True
                # Acquire JogEngine : profil court (aligne Goal=Present →
                # anti-à-coup), intégrateur neuf (seed propre), control_owner="pi"
                # + prime_hold (fige tous les axes sur le présent) + publish
                # robot.control_changed (porté par acquire).
                jog_engine.acquire(rid, "pi")
                # Maintien teach-pendant : on déclare une vélocité 0 pour tous
                # les axes visibles → le tick jog les renvoie en continu, ce qui
                # rafraîchit le dead-man et garde chaque axe verrouillé tant
                # qu'on ne le jogge pas (l'axe 3 suit l'axe 2 par couplage).
                self._joystick_v = {a: 0.0 for a in VISIBLE_AXES}
                self._update_takeover_btn()

            try:
                self.after(0, _finish)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _update_takeover_btn(self) -> None:
        active = self._torque_on and self._direct_mode
        if active:
            self._btn_takeover.set_text("Lacher la main")
            self._btn_takeover.set_accent(T.C_OK_DIM)
            self._btn_takeover.set_fg(T.C_OK)
        else:
            self._btn_takeover.set_text("Prendre la main")
            self._btn_takeover.set_accent(T.SURFACE_HI)
            self._btn_takeover.set_fg(T.TEXT_MED)
        self._update_torque_btn()

    def _toggle_torque(self) -> None:
        """Toggle torque on/off sur le robot actif.
        Si torque OFF : sort du mode pilotage direct + clear l'etat jog
        (sinon le tick continuerait a envoyer des cibles inutiles).
        Si torque ON : active uniquement le couple — le pilotage direct
        s'active separement via 'Prendre la main'."""
        ctrl = self._active_ctrl()
        if ctrl is None:
            bus.publish("ui.toast",
                        {"level": "warn", "message": "Aucun robot actif"})
            return
        if not getattr(ctrl, "is_connected", False):
            bus.publish("ui.toast",
                        {"level": "warn",
                         "message": "Connecte le robot avant"})
            return
        currently_on = bool(getattr(ctrl, "torque_enabled", False))
        if currently_on:
            self._direct_mode = False
            self._joystick_v.clear()
            self._pending_target.clear()
            # Retire l'intégrateur du JogEngine (sinon la boucle 20 Hz
            # continuerait d'écrire Goal sur le robot hors couple -> runaway +
            # à-coup au prochain TORQUE ON). release réaligne aussi Goal=Present
            # AVANT la coupure couple. Cf. revue J2.
            jog_engine.release(self._active_rid)
            try:
                ctrl.set_torque(False)
            except Exception:
                pass
            self._torque_on = False
        else:
            try:
                ok = ctrl.set_torque(True)
            except Exception:
                ok = False
            if not ok:
                bus.publish("ui.toast",
                            {"level": "warn",
                             "message": "Torque non actif (voir logs)"})
                return
            self._torque_on = True
        self._update_takeover_btn()

    def _update_torque_btn(self) -> None:
        """Reflete l'etat torque reel du ctrl sur le bouton."""
        if not hasattr(self, "_btn_torque"):
            return
        ctrl = self._active_ctrl()
        on = bool(ctrl and getattr(ctrl, "torque_enabled", False))
        if on:
            self._btn_torque.set_text("TORQUE OFF")
            self._btn_torque.set_accent(T.C_ERR_DIM)
            self._btn_torque.set_fg(T.C_ERR)
        else:
            self._btn_torque.set_text("TORQUE ON")
            self._btn_torque.set_accent(T.C_OK_DIM)
            self._btn_torque.set_fg(T.C_OK)

    # ── Tick ghost (position hardware live) ───────────────────────
    def _tick_ghost(self) -> None:
        """Rafraichit l'affichage des positions live depuis le store.
        Le read_positions HW se fait dans un thread daemon separe (cf
        _read_positions_loop) pour ne pas bloquer le bus serial pendant
        le tick jog (saccades a 50ms vs lock serial)."""
        snap = store.get_robot(self._active_rid) if self._active_rid else None
        if snap and snap.positions:
            for mid, pos in snap.positions.items():
                sl = self._sliders.get(mid)
                if sl is None:
                    continue
                if hasattr(sl, "set_ghost"):
                    sl.set_ghost(pos)
                elif hasattr(sl, "set_value"):
                    sl.set_value(pos)
        # Synchro periodique du bouton torque avec l'etat reel du ctrl
        # (au cas ou le torque change hors de cette UI : reboot moteur,
        # ESTOP, autre client API).
        self._update_torque_btn()
        self.after(300, self._tick_ghost)

    def _read_positions_loop(self) -> None:
        """Thread daemon : lit les positions HW toutes les 600ms.
        Evite de bloquer le bus serial pendant le tick jog (50ms)."""
        import time as _time
        while True:
            _time.sleep(0.6)
            try:
                rid = self._active_rid
                if not rid:
                    continue
                ctrl = registry.get(rid)
                if ctrl is None or not getattr(ctrl, "is_connected", False):
                    continue
                # Saute le read si jog en cours (priorite au pilotage)
                if any(abs(v) > 0.01 for v in self._joystick_v.values()):
                    continue
                ctrl.read_positions()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# ConnectionBadge — pastille etat + port
# ═══════════════════════════════════════════════════════════════

class ConnectionBadge(tk.Canvas):
    """Pastille cliquable : vert=connecte, rouge=deconnecte, gris=—.

    Affiche l'etat de connexion du robot actif et, si connecte, le port serie.
    Un tap ouvre le popup de connexion.
    """

    BADGE_W = 160
    BADGE_H = 32

    def __init__(self, parent, *, on_tap: Callable):
        super().__init__(parent, width=self.BADGE_W, height=self.BADGE_H,
                         bg=T.SIDEBAR, highlightthickness=0, bd=0)
        self._state = "none"
        self._port = ""
        self._on_tap = on_tap
        self._redraw()
        self.bind("<ButtonRelease-1>", lambda _: self._on_tap())

    def _redraw(self) -> None:
        self.delete("all")
        if self._state == "connected":
            dot_fill, dot_out, fg = T.C_OK, T.C_OK_DIM, T.C_OK
            txt = self._port.replace("/dev/", "") if self._port else "OK"
        elif self._state == "disconnected":
            dot_fill, dot_out, fg = T.C_ERR, T.C_ERR_DIM, T.C_ERR
            txt = "DECONNECTE"
        else:
            dot_fill, dot_out, fg = T.TEXT_DIM, T.BORDER, T.TEXT_DIM
            txt = "—"
        # pastille
        self.create_oval(6, self.BADGE_H // 2 - 7,
                         20, self.BADGE_H // 2 + 7,
                         fill=dot_fill, outline=dot_out, width=1)
        # texte
        self.create_text(28, self.BADGE_H // 2, text=txt,
                         fill=fg, font=P.F_MONO, anchor="w")
        # icone engrenage a droite (indique que c'est cliquable)
        self.create_text(self.BADGE_W - 10, self.BADGE_H // 2,
                         text="\u2699", fill=T.C_AMB,
                         font=(T.FONT_MONO, 16), anchor="e")

    def set_state(self, state: str, port: str = "") -> None:
        self._state = state
        self._port = port
        self._redraw()


# ═══════════════════════════════════════════════════════════════
# ConnectionPopup — Toplevel selection port + connecter/deconnecter
# ═══════════════════════════════════════════════════════════════

class ConnectionPopup(tk.Toplevel):
    """Popup plein ecran : ports disponibles + actions connexion.

    Affiche les ports /dev/tty* detectes, met le port courant en surbrillance,
    propose CONNECTER / DECONNECTER / RAFRAICHIR / FERMER.
    """

    def __init__(self, parent, *, robot_id: str, on_changed: Callable):
        super().__init__(parent)
        self._robot_id = robot_id
        self._on_changed = on_changed
        self.overrideredirect(True)
        self.configure(bg=T.BG)
        # Modale plein ecran (800x480) — fond opaque, masque l'ecran derriere
        w, h = P.SCREEN_W, P.SCREEN_H
        x = parent.winfo_rootx()
        y = parent.winfo_rooty()
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.transient(parent)
        self.grab_set()

        # Header
        head = tk.Frame(self, bg=T.SIDEBAR, height=48)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=f"Connexion — {robot_id}",
                 bg=T.SIDEBAR, fg=T.C_AMB, font=P.F_H1
                 ).pack(side="left", padx=P.PAD_LG, pady=P.PAD_SM)
        TouchButton(head, text="X", width=40, height=36,
                    accent=T.SURFACE_HI, fg=T.C_ERR, font=P.F_H2,
                    command=self.destroy
                    ).pack(side="right", padx=P.PAD_SM, pady=6)

        # Liste ports
        self._list_frame = tk.Frame(self, bg=T.BG)
        self._list_frame.pack(fill="both", expand=True,
                              padx=P.PAD_MD, pady=P.PAD_SM)
        self._selected_port: Optional[str] = None

        # Barre actions
        act = tk.Frame(self, bg=T.SIDEBAR, height=64)
        act.pack(side="bottom", fill="x")
        act.pack_propagate(False)
        TouchButton(act, text="RAFRAICHIR", icon="\u21BB",
                    width=180, height=52, accent=T.SURFACE_HI,
                    fg=T.C_AMB, font=P.F_BTN,
                    command=self._refresh_ports
                    ).pack(side="left", padx=P.PAD_SM, pady=6)
        TouchButton(act, text="DECONNECTER", icon="\u2715",
                    width=180, height=52, accent=T.C_ERR_DIM,
                    fg=T.C_ERR, font=P.F_BTN,
                    command=self._disconnect
                    ).pack(side="left", padx=P.PAD_SM, pady=6)
        TouchButton(act, text="CONNECTER", icon="\u2713",
                    width=180, height=52, accent=T.C_OK_DIM,
                    fg=T.C_OK, font=P.F_BTN_LG,
                    command=self._connect
                    ).pack(side="right", padx=P.PAD_SM, pady=6)

        self._refresh_ports()

    def _refresh_ports(self) -> None:
        """Liste les ports serie et les affiche."""
        for w in self._list_frame.winfo_children():
            w.destroy()
        ports = []
        if list_ports is not None:
            try:
                ports = [p.device for p in list_ports.comports()]
            except Exception:
                ports = []
        snap = store.get_robot(self._robot_id)
        current_port = snap.port if snap else ""

        if not ports:
            tk.Label(self._list_frame, text="Aucun port serie detecte",
                     bg=T.BG, fg=T.TEXT_DIM, font=P.F_H2, pady=30).pack()
            tk.Label(self._list_frame,
                     text="(verifier U2D2 branche et pyserial installe)",
                     bg=T.BG, fg=T.TEXT_DIM, font=P.F_LABEL).pack()
            return
        for port in ports:
            is_current = (port == current_port)
            row = _PortRow(self._list_frame, port=port,
                           is_current=is_current,
                           on_tap=lambda p=port: self._select(p))
            row.pack(fill="x", padx=P.PAD_SM, pady=2)
        # pre-selection du port actuel
        if current_port in ports:
            self._selected_port = current_port

    def _select(self, port: str) -> None:
        self._selected_port = port
        self._refresh_ports()  # redraw avec la nouvelle selection
        # remet la selection en memoire (refresh l'a effacee)
        self._selected_port = port

    def _connect(self) -> None:
        if not self._selected_port:
            return
        ctrl = registry.get(self._robot_id)
        if ctrl is None:
            return
        ok = ctrl.connect(self._selected_port)
        if ok:
            self._on_changed()
            self.destroy()

    def _disconnect(self) -> None:
        ctrl = registry.get(self._robot_id)
        if ctrl:
            ctrl.disconnect()
        self._on_changed()
        self.destroy()


class _PortRow(tk.Canvas):
    """Une ligne port : nom + coche si actuel."""
    ROW_H = 56
    ROW_W = 760

    def __init__(self, parent, *, port: str, is_current: bool,
                 on_tap: Callable):
        super().__init__(parent, width=self.ROW_W, height=self.ROW_H,
                         bg=T.BG, highlightthickness=0, bd=0)
        self._port = port
        self._is_current = is_current
        self._on_tap = on_tap
        self._redraw()
        self.bind("<ButtonRelease-1>", lambda _: self._on_tap())

    def _redraw(self) -> None:
        self.delete("all")
        bg = T.C_OK_DIM if self._is_current else T.SURFACE_HI
        fg = T.C_OK if self._is_current else T.C_AMB
        draw_neu_rect(self, 2, 2, self.ROW_W - 2, self.ROW_H - 2, fill=bg)
        self.create_text(20, self.ROW_H // 2, text=self._port,
                         fill=fg, font=P.F_MONO_LG, anchor="w")
        if self._is_current:
            self.create_text(self.ROW_W - 20, self.ROW_H // 2,
                             text="\u2713 actuel",
                             fill=T.C_OK, font=P.F_BTN, anchor="e")
