"""
xrv22/core/jog_engine.py
────────────────────────
Orchestrateur du jog côté serveur. Héberge un JogIntegrator par robot piloté,
l'avance à 20 Hz dans un thread dédié, et écrit via write_positions_direct.
Les producteurs (Pi tactile en J2 ; web en J4) ne font que pousser des intentions.

Vit dans le même process que l'UI Tk du Pi : `set_velocity` est appelée depuis le
thread Tk, `_thread_loop` tourne dans un thread dédié ->
l'état partagé (_integrators) est protégé par un lock.

Spec : docs/superpowers/specs/2026-06-10-jog-engine-j3-design.md (jalon J3).
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

from xrv22.core.jog_integrator import JogIntegrator

_LOG = logging.getLogger(__name__)

_TICK_S = 0.03                 # ~33 Hz (cale sur l'ancienne rampe client useDirectRamp
                               # 30 ms) — goals moteur plus fins => jog web (mode cible)
                               # plus fluide ; jog Pi (vélocité) reste cohérent (dt suit)
_PROFILE_JOG = (60, 25)        # profil court (Time-based) — posé au DÉBUT du jog
_DEAD_MAN_S = 0.25             # intention non rafraîchie au-delà -> vel 0


def _publish_control_changed(rid: str, owner: Optional[str]) -> None:
    """Notifie l'arbitrage (best-effort : ne casse pas les tests sans bus)."""
    try:
        from xrv22.services.event_bus import bus
        bus.publish("robot.control_changed", {"robot_id": rid, "owner": owner})
    except Exception:
        pass


class JogEngine:
    def __init__(self, registry=None, store=None) -> None:
        self._registry = registry          # None -> singleton résolu paresseusement
        self._store = store
        self._integrators: Dict[str, JogIntegrator] = {}   # rid actif -> integrator
        self._was_active: Dict[str, bool] = {}             # rid -> jog en cours au tick préc.
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._diag_force_now: Optional[float] = None       # tests : force l'horloge

    # --- résolution paresseuse des singletons (prod) ou injection (tests) ---
    @property
    def registry(self):
        if self._registry is None:
            from xrv22.robots.robot_registry import registry
            self._registry = registry
        return self._registry

    @property
    def store(self):
        if self._store is None:
            from xrv22.core.state_store import store
            self._store = store
        return self._store

    def _now(self) -> float:
        return self._diag_force_now if self._diag_force_now is not None else time.monotonic()

    # --- contrôle (appelé depuis le thread Tk Pi) ---
    def acquire(self, rid: str, owner: str = "pi") -> None:
        """Prise de main : intégrateur neuf (seed propre au 1er tick) + arbitrage
        owner. On NE pose PAS le profil court ici : set_torque (appelé juste avant
        par le Pi) a déjà mis le profil confort + Goal=Present -> maintien FERME
        tant qu'on ne jogge pas. Le profil court est posé au DÉBUT du jog
        (cf. _tick_once) ; le poser dès la prise de main ramollit le maintien des
        axes lourds tenus (épaule/coude) qui s'affaissent alors. Cf. bug J2."""
        ctrl = self.registry.get(rid)
        if ctrl is None:
            return
        with self._lock:
            self._integrators[rid] = JogIntegrator()
            self._was_active[rid] = False
        ctrl.control_owner = owner
        # Maintien « teach-pendant » : fige tous les axes sur le présent dès la
        # prise de main (le grip Goal=Present de set_torque a déjà rafraîchi le
        # cache get_positions). Ainsi un axe jamais joggé reste verrouillé quand
        # on en bouge un autre, au lieu de fluer sous gravité. Réservé au Pi
        # (joystick / mode vélocité) : le web (mode cible) tient déjà ses axes
        # via les réécritures de cible et n'a pas ce décrochage.
        if owner == "pi":
            try:
                # Lecture FRAÎCHE + re-ancrage réf de couplage/cache (évite saut
                # axe 3 sur réf périmée et seed sur cache obsolète à chaud).
                if hasattr(ctrl, "arm_hold_reference"):
                    present = ctrl.arm_hold_reference() or {}
                else:
                    present = ctrl.get_positions() or {}
                if present:
                    with self._lock:
                        jog = self._integrators.get(rid)
                        if jog is not None:
                            jog.prime_hold(present, self._now())
            except Exception:
                pass
        _publish_control_changed(rid, owner)

    def release(self, rid: str) -> None:
        """Lâcher : retire l'intégrateur, restaure le profil confort, libère.

        On restaure le profil SANS réécrire Goal=present (pas de set_direct_mode) :
        le maintien teach-pendant a laissé le Goal sur la pose commandée ; réécrire
        le present (sous le Goal de l'erreur de poursuite gravitaire) ferait
        re-droober le servo au lâcher (même ratchet que la prise de main). Le servo
        conserve donc sa consigne et ne bouge pas."""
        with self._lock:
            self._integrators.pop(rid, None)
            self._was_active.pop(rid, None)
        ctrl = self.registry.get(rid)
        if ctrl is None:
            return
        if hasattr(ctrl, "apply_motion_profile"):
            ctrl.apply_motion_profile()          # profil confort, AUCUN write Goal
        else:
            ctrl.set_direct_mode(ctrl.comfort_vel, ctrl.comfort_acc)
        ctrl.control_owner = None
        _publish_control_changed(rid, None)

    def abandon(self, rid: str) -> None:
        """Cesse de piloter `rid` SANS toucher au profil moteur ni à
        l'arbitrage control_owner : pour le cas où un AUTRE canal (web) a déjà
        pris la main. On retire juste l'intégrateur — l'autre canal possède
        désormais le profil et l'owner, on ne doit pas les écraser."""
        with self._lock:
            self._integrators.pop(rid, None)
            self._was_active.pop(rid, None)

    def active_rids(self) -> List[str]:
        with self._lock:
            return list(self._integrators.keys())

    # --- intention (thread Tk) ---
    def set_velocity(self, rid: str, vels: Dict[int, float]) -> None:
        """Pousse l'intention de vélocité (-1..+1 par axe), horodatée pour le
        dead-man. Sans effet si le robot n'a pas été acquis."""
        now = self._now()
        with self._lock:
            jog = self._integrators.get(rid)
            if jog is None:
                return
            for axis, v in vels.items():
                jog.set_velocity(axis, v, now)

    def set_target(self, rid: str, targets: Dict[int, int]) -> None:
        """Intention de POSITION (slider web). Sans effet si rid non acquis."""
        now = self._now()
        with self._lock:
            jog = self._integrators.get(rid)
            if jog is None:
                return
            for axis, pos in targets.items():
                jog.set_target(axis, pos, now)

    def heartbeat(self, rid: str) -> None:
        """Nourrit le dead-man : rafraichit l'horodatage de tous les axes actifs
        du rid (heartbeat web entre deux mouvements de slider)."""
        now = self._now()
        with self._lock:
            jog = self._integrators.get(rid)
            if jog is None:
                return
            jog.refresh_seen(now)

    # --- tick (synchrone : appelé via to_thread depuis l'event loop) ---
    @staticmethod
    def _soft_limits(ctrl) -> Dict[int, tuple]:
        prof = getattr(ctrl, "_profile", None)
        return dict(getattr(prof, "soft_limits", {})) if prof else {}

    def _tick_once(self, dt: float) -> None:
        with self._lock:
            rids = list(self._integrators.keys())
        for rid in rids:
            ctrl = self.registry.get(rid)
            if ctrl is None:
                continue
            with self._lock:
                jog = self._integrators.get(rid)
                if jog is None:
                    continue
                active_now = jog.has_intent()
                # _was_active partage le lock de acquire/release (cohérence) :
                # on détecte le front ici, sous lock ; l'I/O série reste dehors.
                is_front = active_now and not self._was_active.get(rid, False)
                self._was_active[rid] = active_now
            # Début d'un jog (front repos -> actif) : on pose le profil court ET
            # on ré-ancre Goal=Present sur TOUS les axes (set_direct_mode). C'est
            # ce que faisait l'ancien _tick_jog via _sync_direct_profile. Sans ce
            # ré-agrippage au moment où le mouvement commence, les axes lourds
            # tenus (épaule/coude) ramollissent sous le profil court et
            # s'affaissent. set_direct_mode rafraîchit aussi le cache -> seed propre.
            if is_front:
                try:
                    ctrl.set_direct_mode(*_PROFILE_JOG)
                except Exception:
                    pass
            # Source positions : get_positions() (cache), rafraîchi par
            # set_direct_mode ci-dessus au début du jog.
            current = ctrl.get_positions() or {}
            # step()/mirror() touchent l'état interne de l'intégrateur (_vel),
            # aussi muté par set_velocity (thread Tk) sous le même lock -> on tient
            # le lock pendant ce calcul pur (rapide) pour exclure toute course
            # "dict changed size during iteration". L'I/O série reste HORS lock.
            with self._lock:
                jog = self._integrators.get(rid)
                if jog is None:
                    continue
                jog.expire(self._now(), _DEAD_MAN_S)   # dead-man avant intégration
                # baseline = pose PRÉCÉDENTE commandée (avant ce step) : sert de
                # référence au garde-fou retreat_aware (le cache ctrl n'est pas
                # rafraîchi par tick → inutilisable comme référence).
                baseline = jog.mirror(current)
                snap = jog.snapshot()                  # pour annuler si rejet
                targets = jog.step(dt, current, self._soft_limits(ctrl))
            accepted = True
            if targets:
                accepted = ctrl.write_positions_direct(targets, baseline=baseline)
            with self._lock:
                jog = self._integrators.get(rid)
                if jog is None:
                    continue
                # Écriture REJETÉE (garde-fou) : on annule l'avance du step → la
                # cible interne reste sur la dernière position acceptée (pile au
                # contact), pas de fuite ni de saut au recul. cf. restore().
                if accepted is False:
                    jog.restore(snap)
                mirror = jog.mirror(current)
            # miroir store : intention (sans lead) fusionnée sur les axes réels
            self.store.set_positions(rid, mirror)

    # --- thread dédié (driver) ---
    def _thread_loop(self) -> None:
        next_t = time.monotonic()
        while self._running:
            with self._lock:
                idle = not self._integrators
            if not idle:
                try:
                    self._tick_once(_TICK_S)
                except Exception:
                    _LOG.exception("[jog] tick")
            next_t += _TICK_S
            dt_sleep = next_t - time.monotonic()
            if dt_sleep > 0:
                time.sleep(dt_sleep)
            else:
                next_t = time.monotonic()           # tick long (front) -> resync

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._thread_loop,
                                        name="jog-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout=1.0)
        self._thread = None


# Singleton partagé : importé par le serveur (attach_loop) et par l'UI Pi
# (set_velocity / acquire / release).
jog_engine = JogEngine()
