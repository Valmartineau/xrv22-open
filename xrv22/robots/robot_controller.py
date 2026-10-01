"""
xr200/robots/robot_controller.py
──────────────────────────────────
Contrôleur par robot.

Orchestre :
  - SafetyManager (états, validations)
  - SerialManager (communication Dynamixel SDK)
  - Profil (limites physiques)
  - Positions de référence (home machine / home work)

Règle de safe_home() :
  HOME_MACHINE passe TOUJOURS par HOME_WORK en premier.
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Tuple

from xrv22.config import (
    SMOOTH_HZ_DEFAULT, COMFORT_VEL_DEFAULT, COMFORT_ACC_DEFAULT,
    HOME_DURATION_DEFAULT_S, BAUDRATE_DXL_DEFAULT,
)
from xrv22.core.safety_manager import RobotSafetyManager, RobotState, safety
from xrv22.hardware.serial_manager import SerialManager
from xrv22.robots.robot_profiles import (
    RobotProfile, profiles, make_default_profile,
)
from xrv22.core.state_store import store
from xrv22.services.event_bus import bus
from xrv22.services.logger import get_logger, SAFETY_LEVEL

_LOG = get_logger("RobotController")

Position = Dict[int, int]


def _apply_coupling(positions: Position,
                    ref: Optional[Tuple[int, int]] = None) -> Position:
    """Applique le couplage axe 2→3 configure dans library.hardware.coupling.

    Deux modes :
    - RELATIF (ref fournie = (ref2, ref3) capturée au réveil) : axe3 suit le
      delta de l'axe 2 depuis la pose de référence → pos_3 = ref3 + sign×ratio×
      (pos_2 − ref2). Préserve l'offset mécanique réel des servos solidaires
      (pas d'à-coup du coude quand il a flué sous gravité couple coupé).
    - ABSOLU (ref=None, fallback historique) : pos_3 = center + sign×ratio×
      (pos_2 − center) + offset.
    Si master (axe 2) absent des positions a envoyer, ne touche a rien.
    SSOT backend : appele par write_positions_direct et move.
    """
    try:
        from xrv22.library.library_manager import library
    except ImportError:
        return positions
    try:
        cfg = library.get_hardware().get("coupling", {}) or {}
    except Exception:
        return positions
    if not cfg.get("enabled", False) or 2 not in positions:
        return positions
    sign = -1.0 if cfg.get("invert", False) else 1.0
    ratio = float(cfg.get("ratio", 1.0))
    out = dict(positions)
    if ref is not None and ref[0] is not None and ref[1] is not None:
        ref2, ref3 = ref
        p3 = int(round(ref3 + sign * ratio * (positions[2] - ref2)))
    else:
        offset = int(cfg.get("offset", 0))
        center = int(cfg.get("center", 2048))
        p3 = int(round(center + sign * ratio * (positions[2] - center) + offset))
    out[3] = max(0, min(4095, p3))
    return out


def calculate_auto_duration(
    targets: Dict[int, int],
    current: Dict[int, int],
    speed_ratio: float = 1.0,
) -> float:
    """
    V22 : Calcul automatique de la durée en fonction de la distance.
    ~1000 ticks/s à speed_ratio=1.0, +50% de marge de sécurité, clampé [0.3, 10.0]s.
    """
    max_delta = 0
    for motor_id, target_pos in targets.items():
        if motor_id in current:
            delta = abs(target_pos - current[motor_id])
            max_delta = max(max_delta, delta)
    if max_delta == 0:
        return 0.5
    base_speed = 1000  # ticks par seconde
    duration = (max_delta / base_speed) / speed_ratio
    # +50% de marge pour éviter les rejets safety "trop rapide"
    duration *= 1.5
    return max(0.3, min(duration, 10.0))


class RobotController:
    """
    Interface complète d'un robot.
    """

    def __init__(self, robot_id: str, motor_ids: List[int],
                 simulation: bool = False) -> None:
        self.robot_id = robot_id
        self.motor_ids = motor_ids
        self.simulation = simulation

        # Sous-modules
        self._safety = safety.add_robot(robot_id, motor_ids)
        self._serial = SerialManager(robot_id, motor_ids, simulation=simulation)

        # Profil (défaut si non enregistré)
        if not profiles.get(robot_id):
            profiles.register(make_default_profile(robot_id))
        self._profile: RobotProfile = profiles.get(robot_id)  # type: ignore

        # Synchroniser soft_limits du profil → safety_manager
        self._sync_limits_to_safety()

        # Positions de référence — initialisées à None.
        # Seul le projet (robots.json) les définit via set_home_machine/set_home_work.
        self._home_machine: Optional[Position] = None
        self._home_work: Optional[Position] = None
        self._home_lock = threading.Lock()  # Protège _home_machine / _home_work
        self._current_positions: Position = {}
        self._positions_lock = threading.Lock()

        # Référence de couplage relatif (ref2, ref3) capturée au réveil
        # (set_torque OFF→ON) : axe3 suit le delta de l'axe2 depuis cette pose,
        # ce qui préserve l'offset mécanique réel des servos 2/3 solidaires et
        # évite l'à-coup du coude. None tant qu'aucun réveil n'a eu lieu.
        self._coupling_ref: Optional[Tuple[int, int]] = None

        # Arbitrage contrôle : "web", "pi", ou None (personne)
        self.control_owner: Optional[str] = None

        # Paramètres mouvement (defaults depuis config.py)
        self.smooth_hz: int = SMOOTH_HZ_DEFAULT
        self.comfort_vel: int = COMFORT_VEL_DEFAULT
        self.comfort_acc: int = COMFORT_ACC_DEFAULT
        self.home_duration: float = HOME_DURATION_DEFAULT_S

        # Verrou anti-concurrence mouvement
        self._move_lock = threading.Lock()
        self._homing = False
        self._move_timer: Optional[threading.Timer] = None

        # Abonnements bus
        self._subscribe()

    # ── Propriétés ──────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._safety.state

    @property
    def is_connected(self) -> bool:
        snap = store.get_robot(self.robot_id)
        return snap.connected if snap else False

    @property
    def profile(self):
        return self._profile

    @property
    def home_machine(self) -> dict:
        with self._home_lock:
            return dict(self._home_machine) if self._home_machine else {}

    @property
    def home_work(self) -> dict:
        with self._home_lock:
            return dict(self._home_work) if self._home_work else {}

    @property
    def torque_enabled(self) -> bool:
        return self._serial.torque_enabled

    # ── API publique (façade pour l'UI) ──────────────────────────

    def get_positions(self) -> Position:
        """Retourne une copie thread-safe des positions courantes."""
        return self._get_positions()

    def write_positions_direct(self, targets: Position,
                               baseline: Optional[Position] = None) -> bool:
        """Écriture directe des positions (mode pilotage manuel).

        Le couplage configure dans la library est applique automatiquement
        (ex. axe 2 -> axe 3) → SSOT backend, partage entre toutes les UI.

        Check collision (retreat_aware) : appelle check_collision_only ; on ne
        bloque que si la cible APPROFONDIT la collision vs la pose de référence
        → le bras peut toujours ressortir d'un contact. `baseline` = pose
        précédente RÉELLEMENT commandée (fournie par le jog) ; sinon le cache de
        positions. Le cache n'étant rafraîchi qu'au front du jog, s'en servir
        comme référence fausserait la comparaison et ferait « claquer » le bras
        vers la position de départ au recul — d'où le baseline explicite.
        Si bloqué, le tick est silencieusement rejeté (broadcast bus rate-limité
        à 1×/sec pour notifier l'UI).
        """
        # Défense en profondeur : clamp aux soft-limits du profil (SSOT
        # backend). Les clients (jog Pi, sliders web) clampent déjà, mais le
        # backend ne doit jamais écrire un Goal Position hors limites sur la
        # seule foi du client — c'est le chemin de pilotage le plus utilisé.
        limits = self._profile.soft_limits
        clamped: Position = {}
        for mid, val in targets.items():
            lo, hi = limits.get(mid, (0, 4095))
            clamped[mid] = max(lo, min(hi, int(val)))
        targets = clamped
        # Check collision (rate-limited broadcast pour éviter spam en Direct)
        try:
            current = baseline if baseline else self._get_positions()
            if current:
                ok, _, _, _, _ = self._safety.check_collision_only(
                    targets, current, broadcast=True, retreat_aware=True)
                if not ok:
                    return False
        except Exception:
            pass  # fail-open
        coupled = _apply_coupling(targets, self._coupling_ref)
        ok = self._serial.write_positions(coupled)
        if ok:
            # Tenir le store à jour sur la position commandée. Le poll HW est
            # gaté torque OFF ; torque ON, c'est ce chemin (le plus utilisé) qui
            # doit refléter la commande, sinon la perception reste figée (ex. run
            # incarné : la base d'Eddy n'avance pas → le bras n'accumule rien).
            # Merge (pas remplacement) pour préserver les axes non écrits.
            self.update_positions({**self._get_positions(), **coupled})
        return ok

    def set_motor_limit(self, motor_id: int, lo: int, hi: int,
                        _propagating: bool = False) -> None:
        """Définit les soft-limits d'un moteur (profil + safety).

        Si self est master, propage automatiquement aux esclaves.
        """
        self._profile.soft_limits[motor_id] = (lo, hi)
        self._safety.set_soft_limits(motor_id, lo, hi)
        if not _propagating:
            self._propagate_if_master("soft_limit",
                                      motor_id=motor_id, limits=(lo, hi))

    def sync_hardware_limits(self) -> None:
        """Synchronise les limites logicielles vers le hardware."""
        self._serial.sync_hardware_limits(self._profile.soft_limits)

    def set_direct_mode(self, vel: int = 0, acc: int = 0) -> None:
        """Active le mode pilotage direct (profil court pour réponse immédiate).

        Anti-à-coup au démarrage du jog : on aligne Goal = Present AVANT
        d'appliquer le profil court. Si un écart Goal−Present subsistait (dérive,
        scénario/home antérieur), le profil rapide l'exécuterait d'un coup sur
        les moteurs concernés. En réécrivant la position réelle comme cible sous
        le profil encore lent, le servo reste sur place ; le profil court n'a
        alors plus rien à rattraper. La lecture met aussi à jour le cache pour
        que _jog_pos reparte de la position réelle (pas d'une valeur périmée)."""
        if not self._serial.connected:
            return
        try:
            present = self._serial.read_positions() or {}
            if present:
                self._serial.write_positions(present)
                self.update_positions(present)
        except Exception as exc:
            _LOG.warning("[%s] set_direct_mode: alignement Goal=Present : %s",
                         self.robot_id, exc)
        self._serial.set_profile(vel, acc)

    @property
    def port_name(self) -> str:
        """Retourne le nom du port série."""
        return self._serial.port_name if hasattr(self._serial, 'port_name') else self._serial._port_name

    @property
    def serial_connected(self) -> bool:
        """Retourne l'état brut de la connexion série."""
        return self._serial.connected

    # ── Paramètres mouvement ─────────────────────────────────────

    def set_motion_params(self, hz: int, velocity: int, acceleration: int,
                          home_duration: Optional[float] = None,
                          _propagating: bool = False) -> None:
        """Met à jour les paramètres mouvement et applique au hardware.

        Si self est master, propage automatiquement aux esclaves.
        """
        self.smooth_hz = max(30, min(120, hz))
        self.comfort_vel = max(10, min(500, velocity))
        self.comfort_acc = max(5, min(200, acceleration))
        if home_duration is not None:
            self.home_duration = max(0.5, min(10.0, home_duration))
        if self._serial.connected:
            self._serial.set_profile(self.comfort_vel, self.comfort_acc)
        _LOG.info("[%s] Motion params : Hz=%d  Vel=%d  Acc=%d  HomeDur=%.1fs",
                  self.robot_id, self.smooth_hz, self.comfort_vel,
                  self.comfort_acc, self.home_duration)
        if not _propagating:
            self._propagate_if_master("motion")

    def apply_motion_profile(self) -> None:
        """Réapplique les profils comfort avant un mouvement."""
        if self._serial.connected:
            self._serial.set_profile(self.comfort_vel, self.comfort_acc)

    # ── Connexion ────────────────────────────────────────────────

    def connect(self, port: str, baud: int = BAUDRATE_DXL_DEFAULT) -> bool:
        """Connecte le robot, synchronise limites HW, applique le
        profil de vitesse par defaut (uniforme entre moteurs heterogenes),
        lit les positions initiales."""
        ok = self._serial.connect(port, baud)
        if ok:
            if self._safety.state != RobotState.IDLE:
                self._safety.transition_to(RobotState.IDLE)
            store.set_robot_connected(self.robot_id, True, port)
            # Synchroniser les limites HW avec les soft_limits du profil
            self._serial.sync_hardware_limits(self._profile.soft_limits)
            # Profil de vitesse par defaut (uniformise les moteurs heterogenes :
            # vel=0 fait que chaque moteur va a SA vitesse max, ce qu'on ne
            # veut pas. comfort_vel/acc donnent une cadence uniforme).
            try:
                self._serial.set_profile(self.comfort_vel, self.comfort_acc)
            except Exception as exc:
                _LOG.warning("[%s] set_profile init : %s", self.robot_id, exc)
            # Lecture positions initiales (comme V17)
            positions = self._serial.read_positions()
            if positions:
                self.update_positions(positions)
                _LOG.info("[%s] Positions initiales lues : %s", self.robot_id, positions)
        return ok

    def disconnect(self) -> None:
        """Déconnecte proprement."""
        self._serial.disconnect()
        store.set_robot_connected(self.robot_id, False)

    # ── Torque ON/OFF (V17 compatible) ───────────────────────────

    def set_torque(self, enable: bool) -> bool:
        """Active/désactive le couple. Comme V17.

        Anti-à-coup au réveil (transition OFF→ON) : le servo Dynamixel fonce
        vers son registre Goal Position dès l'armement du couple. Or pendant que
        le couple était coupé le bras s'affaisse sous la gravité (le coude/axe 3
        le plus) ; le Goal résiduel pointe alors loin de la position réelle → le
        servo rush = à-coup, identique sur les 3 robots. On neutralise ça :
        1) profil confort (jamais le profil jog court) → tout rush résiduel reste
           lent ; 2) lecture de la position physique AVANT d'armer ; 3) dès le
        couple activé, on réécrit Goal = position lue → le servo tient sur place.
        Cf. project_xrv22_reveil_coude.
        """
        if not self._serial.connected:
            _LOG.warning("[%s] set_torque(%s) : non connecté", self.robot_id, enable)
            return False
        going_on = enable and not self._serial.torque_enabled
        present: Position = {}
        if going_on:
            try:
                self.apply_motion_profile()  # profil confort, pas le jog court
            except Exception as exc:
                _LOG.warning("[%s] set_torque: profil confort : %s",
                             self.robot_id, exc)
            try:
                present = self._serial.read_positions() or {}
            except Exception as exc:
                _LOG.warning("[%s] set_torque: lecture position : %s",
                             self.robot_id, exc)
                present = {}
        # Anti-affaissement au réveil : on écrit Goal = position réelle AVANT
        # d'armer le couple. Sinon, à l'instant du torque-enable, le servo fonce
        # vers son Goal résiduel (mesuré : coude ~26 ticks SOUS le présent → un
        # affaissement de quelques mm) pendant la fenêtre qui précède la
        # réconciliation. En posant Goal=present d'abord, le couple s'active sur
        # place. La réconciliation ci-dessous reste (rempart si micro-fluage).
        if going_on and present:
            try:
                self._serial.write_positions(present)
            except Exception as exc:
                _LOG.warning("[%s] set_torque: pre-arm Goal=present : %s",
                             self.robot_id, exc)
        ok = self._serial.set_torque(enable)
        if ok:
            if going_on and present:
                # Figer le servo sur sa position réelle → pas de saut vers le
                # Goal résiduel. Si la lecture a échoué (present vide) on ne
                # réécrit rien : retour au comportement historique.
                try:
                    self._serial.write_positions(present)
                    self.update_positions(present)
                except Exception as exc:
                    _LOG.warning("[%s] set_torque: réconciliation Goal : %s",
                                 self.robot_id, exc)
                # Capture la référence de couplage relatif (axes 2 et 3) sur la
                # pose réelle au réveil → le 1er write de jog ne ramène plus le
                # coude sur l'axe 2 (cf. _apply_coupling mode relatif).
                if present.get(2) is not None and present.get(3) is not None:
                    self._coupling_ref = (int(present[2]), int(present[3]))
            elif not enable:
                # Couple coupé → la référence devient caduque (le bras va fluer).
                self._coupling_ref = None
            state = RobotState.READY if enable else RobotState.IDLE
            if self._safety.state != state:
                self._safety.transition_to(state)
            bus.publish("robot.state_changed", {
                "robot_id": self.robot_id,
                "state": state,
                "torque": enable,
            })
        return ok

    def arm_hold_reference(self) -> Position:
        """Prise de main (maintien teach-pendant) : retourne la pose sur laquelle
        figer le maintien = le registre GOAL courant (là où le servo est DÉJÀ
        commandé), PAS le present.

        Pourquoi le goal et pas le present : le present est sous le goal de
        l'erreur de poursuite gravitaire ; semer le maintien sur le present
        ferait re-droober le servo d'un cran à CHAQUE prise de main (ratchet
        cumulatif observé en trace : axe4 +18 ticks/prise). En adoptant le goal
        existant, on réécrit la même consigne → zéro mouvement. Ré-ancre aussi la
        réf de couplage 2→3 et le cache sur cette pose."""
        try:
            goal = self._serial.read_goal_positions() or {}
        except Exception:
            goal = {}
        try:
            present = self._serial.read_positions() or {}
        except Exception:
            present = {}
        seed = goal or present          # fallback present si lecture goal échoue
        if seed.get(2) is not None and seed.get(3) is not None:
            self._coupling_ref = (int(seed[2]), int(seed[3]))
        if present:
            self.update_positions(present)   # cache = réel (affichage/visu)
        return seed

    # ── Lecture positions ─────────────────────────────────────────

    def read_positions(self) -> Position:
        """Lit et met à jour les positions depuis le hardware."""
        positions = self._serial.read_positions()
        if positions:
            self.update_positions(positions)
        return positions

    # ── Mouvement ────────────────────────────────────────────────

    def _validate_positions_and_duration(self, positions: Position,
                                         duration_s: float,
                                         skip_limits: bool) -> Tuple[bool, str]:
        """Valide les positions (sauf si skip_limits) et la durée."""
        if not skip_limits:
            ok, errors = self._profile.validate_positions(positions)
            if not ok:
                msg = "Positions hors limites : " + "; ".join(errors)
                _LOG.error("[%s] %s", self.robot_id, msg)
                return False, msg
        return self._profile.validate_duration(duration_s)

    @staticmethod
    def _classify_violations(violations):
        """Sépare les violations entre vitesse et limites critiques."""
        speed = [v for v in violations if "trop rapide" in v.message]
        limit = [v for v in violations
                 if v.severity in ("error", "critical")
                 and "trop rapide" not in v.message]
        return speed, limit

    def _validate_safety_with_autocorrect(self, positions: Position,
                                          duration_s: float) -> Tuple[bool, str, float]:
        """Valide la safety. Auto-corrige la durée si seule la vitesse pose problème.
        Retourne (ok, message, durée — corrigée le cas échéant)."""
        current = self._get_positions()
        is_safe, violations = self._safety.validate_move(positions, duration_s, current)
        if is_safe:
            return True, "", duration_s
        speed_violations, limit_violations = self._classify_violations(violations)
        if limit_violations:
            return False, "Safety: " + "; ".join(v.message for v in limit_violations), duration_s
        if speed_violations and current:
            new_duration = calculate_auto_duration(positions, current)
            _LOG.warning("[%s] Durée auto-corrigée à %.2fs (+50%% marge)",
                         self.robot_id, new_duration)
            return True, "", new_duration
        return True, "", duration_s

    def move(self, positions: Position, duration_s: float,
             skip_limits: bool = False) -> Tuple[bool, str]:
        """
        Envoie une commande de mouvement.
        Valide profile + safety avant tout envoi.
        Active le torque si nécessaire.
        skip_limits : True pour les mouvements home (positions calibrées hors soft_limits).
        Retourne (ok, message).
        """
        ok, msg = self._validate_positions_and_duration(positions, duration_s, skip_limits)
        if not ok:
            return False, msg

        # Safety (sauf mouvements home — positions calibrées hors limites)
        if not skip_limits:
            ok, msg, duration_s = self._validate_safety_with_autocorrect(
                positions, duration_s)
            if not ok:
                return False, msg

        # Torque ON si nécessaire
        if not self._serial.torque_enabled:
            self._serial.set_torque(True)

        # Couplage (axe 2 -> axe 3) avant envoi
        positions = _apply_coupling(positions, self._coupling_ref)

        # Envoi Dynamixel (Time-based Profile : durée gérée dans send_move)
        duration_ms = int(duration_s * 1000)
        _LOG.info("[%s] move() → cibles=%s  durée=%.2fs  skip_limits=%s",
                  self.robot_id, positions, duration_s, skip_limits)
        self._serial.send_move(positions, duration_ms)
        self._safety.transition_to(RobotState.RUNNING)
        # Mode réel : mettre les positions cibles immédiatement (V17 compat).
        # Mode sim : c'est le SimInterpolator qui met à jour progressivement.
        if not self.simulation:
            self.update_positions(positions)

        # Timer fin de mouvement → repasse en READY
        self._schedule_move_done(duration_s)
        return True, "OK"

    def _cancel_move_timer(self) -> None:
        """Annule le timer de fin de mouvement en cours."""
        if self._move_timer is not None:
            self._move_timer.cancel()
            self._move_timer = None

    def _schedule_move_done(self, duration_s: float) -> None:
        """Repasse l'état à READY après la durée du mouvement."""
        self._cancel_move_timer()

        def _done() -> None:
            self._move_timer = None
            if self._safety.state == RobotState.RUNNING:
                self._safety.transition_to(RobotState.READY)
                bus.publish("robot.state_changed", {
                    "robot_id": self.robot_id,
                    "state": RobotState.READY,
                })
        t = threading.Timer(duration_s + 0.1, _done)
        t.daemon = True
        self._move_timer = t
        t.start()

    # ── Homes ────────────────────────────────────────────────────

    def set_home_machine(self, positions: Position,
                         _propagating: bool = False) -> None:
        """Enregistre la position initiale machine (thread-safe).

        Si self est master, propage automatiquement aux esclaves
        (sauf si appel re-entrant via _propagating=True).
        """
        with self._home_lock:
            self._home_machine = dict(positions)
        store.set_home_machine(self.robot_id, True)
        _LOG.log(SAFETY_LEVEL, "[%s] Home machine défini : %s", self.robot_id, positions)
        if not _propagating:
            self._propagate_if_master("home_machine", positions=dict(positions))

    def set_home_work(self, positions: Position,
                      _propagating: bool = False) -> None:
        """Enregistre la position initiale de travail (thread-safe).

        Si self est master, propage automatiquement aux esclaves.
        """
        with self._home_lock:
            self._home_work = dict(positions)
        store.set_home_work(self.robot_id, True)
        _LOG.log(SAFETY_LEVEL, "[%s] Home work défini", self.robot_id)
        if not _propagating:
            self._propagate_if_master("home_work", positions=dict(positions))

    def _propagate_if_master(self, kind: str, **kwargs) -> None:
        """Si self est master, declenche la propagation aux esclaves."""
        try:
            from xrv22.robots.robot_registry import registry
        except ImportError:
            return
        if registry.master_id != self.robot_id:
            return
        try:
            registry.propagate_from_master(kind=kind, **kwargs)
        except Exception as exc:
            _LOG.warning("[%s] propagate(%s) : %s", self.robot_id, kind, exc)

    def go_home_work(self, duration_s: Optional[float] = None) -> Tuple[bool, str]:
        """Envoie le robot en position de travail (V17: durée auto)."""
        with self._home_lock:
            hw = dict(self._home_work) if self._home_work else None
        if hw is None:
            return False, "Home work non défini"
        if self._homing:
            _LOG.warning("[%s] go_home_work IGNORÉ — safe_home en cours", self.robot_id)
            return False, "safe_home en cours"
        _LOG.info("[%s] go_home_work → cible : %s", self.robot_id, hw)
        if duration_s is None:
            duration_s = self.home_duration
        return self.move(hw, duration_s, skip_limits=True)

    def _is_at_position(self, target: Position, tolerance: int = 30) -> bool:
        """Vérifie si le robot est déjà à la position cible (±tolérance).
        Lit les positions RÉELLES du hardware (pas le cache mémoire)."""
        current = self._serial.read_positions() if self._serial.connected else {}
        if not current:
            return False
        for mid, tpos in target.items():
            if mid not in current:
                return False
            delta = abs(current[mid] - tpos)
            if delta > tolerance:
                _LOG.debug("[%s] _is_at_position : moteur %d delta=%d (pos=%d cible=%d)",
                           self.robot_id, mid, delta, current[mid], tpos)
                return False
        return True

    def safe_home(self, duration_s: Optional[float] = None) -> Tuple[bool, str]:
        """
        Retour sécurisé home machine (V17: durée auto).
        RÈGLE : passe par home_work d'abord, attend la fin, puis va en machine.
        Verrou anti-concurrence : un seul safe_home à la fois par robot.
        """
        with self._home_lock:
            hm = dict(self._home_machine) if self._home_machine else None
            hw = dict(self._home_work) if self._home_work else None
        if hm is None:
            return False, "Home machine non défini"
        if hw is None:
            return False, "Home work non défini (requis pour safe_home)"

        # Verrou anti-concurrence
        if not self._move_lock.acquire(blocking=False):
            _LOG.warning("[%s] safe_home IGNORÉ — déjà en cours", self.robot_id)
            return False, "safe_home déjà en cours"
        self._homing = True
        try:
            return self._safe_home_locked(hm, hw, duration_s)
        finally:
            self._homing = False
            self._move_lock.release()

    def _safe_home_locked(self, hm: Position, hw: Position,
                           duration_s: Optional[float] = None) -> Tuple[bool, str]:
        """Implémentation safe_home protégée par le verrou.
        Reçoit les copies de home machine/work pour éviter les races."""
        # Déjà en position machine → rien à faire
        current = self._serial.read_positions() if self._serial.connected else {}
        if current and self._is_at_position_cached(hm, current):
            _LOG.log(SAFETY_LEVEL, "[%s] safe_home : déjà en position machine, skip", self.robot_id)
            return True, "Déjà en position machine"

        hd = self.home_duration

        # Étape 1 : aller en position travail (sauf si déjà là)
        if current and self._is_at_position_cached(hw, current):
            _LOG.log(SAFETY_LEVEL, "[%s] safe_home : déjà en position travail, skip work", self.robot_id)
        else:
            ok, msg = self.move(hw, hd, skip_limits=True)
            if not ok:
                return False, f"Échec home_work dans safe_home : {msg}"
            _LOG.info("[%s] safe_home : attente fin mouvement work (%.1fs)", self.robot_id, hd)
            # move() est asynchrone : on attend la durée du mouvement avant
            # d'enchaîner (sinon on commanderait machine en plein trajet work).
            time.sleep(hd + 0.2)

        # Étape 2 : aller en position machine
        machine_duration = duration_s or hd
        _LOG.info("[%s] safe_home : envoi vers machine %s (durée=%.2fs)",
                  self.robot_id, hm, machine_duration)
        ok2, msg2 = self.move(hm, machine_duration, skip_limits=True)
        if not ok2:
            return False, f"Échec home_machine dans safe_home : {msg2}"
        # CRITIQUE : attendre la fin du mouvement machine avant de rendre la main
        # sinon le caller (shutdown) va faire torque OFF en plein mouvement.
        _LOG.info("[%s] safe_home : attente fin mouvement machine (%.1fs)",
                  self.robot_id, machine_duration)
        time.sleep(machine_duration + 0.2)
        _LOG.log(SAFETY_LEVEL, "[%s] safe_home : work → machine OK", self.robot_id)
        return True, "OK"

    @staticmethod
    def _is_at_position_cached(target: Position, current: Position,
                                tolerance: int = 30) -> bool:
        """Vérifie si le robot est à la position cible avec des positions pré-lues."""
        for mid, tpos in target.items():
            if mid not in current:
                return False
            if abs(current[mid] - tpos) > tolerance:
                return False
        return True

    # ── Safety commandes ────────────────────────────────────────

    def emergency_stop(self) -> None:
        """Arrêt d'urgence immédiat — torque off."""
        self._cancel_move_timer()
        self._serial.send_estop()
        self._safety.force_emergency_stop("operator")

    def soft_stop(self) -> None:
        """Arrêt propre — torque off."""
        self._cancel_move_timer()
        self._serial.send_stop()
        self._safety.soft_stop()

    def lock(self) -> bool:
        """Verrouille le robot."""
        return self._safety.lock()

    def unlock(self) -> bool:
        """Déverrouille le robot."""
        return self._safety.unlock()

    def reset_emergency(self) -> bool:
        """Reset EMERGENCY_STOP → IDLE (manuel)."""
        return self._safety.reset_emergency()

    def reset_error(self) -> bool:
        """Reset ERROR → IDLE."""
        return self._safety.reset_error()

    def read_hardware_errors(self) -> Dict[int, list]:
        """Lit les erreurs hardware de chaque moteur (registre 70)."""
        return self._serial.read_hardware_errors()

    def reboot_motor(self, motor_id: int) -> bool:
        """Reboot un moteur en securite sans couper l'alimentation.
        Reconfigure le Time-based Profile automatiquement."""
        ok = self._serial.reboot_motor(motor_id)
        if ok:
            _LOG.info("[%s] Moteur %d reboot OK — pret a reactiver torque",
                      self.robot_id, motor_id)
        return ok

    # ── Positions ────────────────────────────────────────────────

    def update_positions(self, positions: Position) -> None:
        """Met à jour les positions courantes."""
        with self._positions_lock:
            self._current_positions = dict(positions)
        store.set_positions(self.robot_id, positions)

    def sync_soft_limits(self) -> None:
        """Synchronise les soft_limits du profil vers le safety_manager."""
        self._sync_limits_to_safety()

    # ── Privé ────────────────────────────────────────────────────

    def _sync_limits_to_safety(self) -> None:
        """Propage toutes les soft_limits du profil vers le safety_manager."""
        for mid, (lo, hi) in self._profile.soft_limits.items():
            self._safety.set_soft_limits(mid, lo, hi)

    def _get_positions(self) -> Position:
        """Retourne une copie thread-safe des positions."""
        with self._positions_lock:
            return dict(self._current_positions)

    def _subscribe(self) -> None:
        """Souscrit aux événements bus pertinents."""
        bus.subscribe("safety.comm_lost", self._on_comm_lost)

    def _on_comm_lost(self, payload: dict) -> None:
        """Réaction COMM_LOST ciblée sur ce robot."""
        if payload.get("robot_id") == self.robot_id:
            self._safety.on_comm_lost()
