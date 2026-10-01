"""
xrv22/core/jog_integrator.py
─────────────────────────────
Integration pure du jog : transforme des intentions de velocite (joystick) en
positions cibles, en reproduisant a l'identique la math de _tick_jog (rampe
soft-start + feed-forward lead + clamp soft-limits). Aucune dependance Tk,
Dynamixel ni asyncio -> 100% testable.
"""
from __future__ import annotations

from typing import Dict, Optional, Set, Tuple


class JogIntegrator:
    # Constantes reprises a l'identique de ScreenPilotage (sensation validee).
    JOG_MAX_SPEED = 750                                  # ticks/s a fond de course
    JOG_MAX_SPEED_PER_AXIS: Dict[int, int] = {2: 400, 4: 400}  # axes lourds
    JOG_LEAD_S = 0.060                                   # feed-forward (profil Time-based)
    JOG_RAMP_S = 0.18                                    # duree rampe soft-start

    def __init__(self) -> None:
        self._jog_pos: Dict[int, float] = {}    # cible interne accumulee par axe
        self._jog_ramp: Dict[int, float] = {}   # etat de rampe 0->1 par axe
        self._active_axes: Set[int] = set()     # axes actifs au tick precedent
        self._vel: Dict[int, float] = {}        # intention de velocite courante
        self._seen: Dict[int, float] = {}       # horodatage de la derniere intention par axe
        self._target: Dict[int, float] = {}     # cible absolue par axe (mode web)

    def set_velocity(self, axis: int, vel: float, now: float) -> None:
        """Intention de velocite d'un axe (-1..+1), horodatee (dead-man)."""
        self._vel[axis] = vel
        self._target.pop(axis, None)            # mode velocite exclut le mode cible
        self._seen[axis] = now

    def prime_hold(self, present: Dict[int, int], now: float) -> None:
        """Maintien « teach-pendant » à la prise de main : fige TOUS les axes
        fournis sur leur position réelle (cible interne = présent, vélocité 0,
        horodatés). step() les réécrit alors à chaque tick → un axe jamais
        joggé reste verrouillé pendant qu'on en bouge un autre, au lieu de
        fluer sous gravité (axes lourds 2/3/4). Le dead-man reste actif : si le
        producteur cesse de rafraîchir l'horodatage, les axes expirent et
        cessent d'être écrits (les servos tiennent alors leur dernier Goal)."""
        for mid, pos in present.items():
            mid = int(mid)
            self._jog_pos[mid] = float(pos)
            self._vel[mid] = 0.0
            self._seen[mid] = now

    def set_target(self, axis: int, pos: int, now: float) -> None:
        """Intention de POSITION absolue (slider web), horodatee. step() rampe
        _jog_pos vers `pos` a vitesse bornee. Exclut le mode velocite sur cet axe."""
        self._target[axis] = float(pos)
        self._vel.pop(axis, None)
        self._seen[axis] = now

    def has_intent(self) -> bool:
        """Intention active sur au moins un axe (velocite Pi OU cible web) ?
        Sert au front profil-court : un axe en mode cible doit le declencher
        aussi (sinon les sliders web bougent sous profil confort)."""
        return (any(abs(v) >= 0.001 for v in self._vel.values())
                or bool(self._target))

    def expire(self, now: float, timeout: float) -> None:
        """Dead-man : tout axe dont l'intention n'a pas ete rafraichie depuis
        plus de `timeout` retombe a vitesse 0 et cesse de ramper vers sa cible."""
        for axis, seen in list(self._seen.items()):
            if now - seen > timeout:
                # Dead-man (comms/producteur perdus) : on RETIRE l'axe de _vel
                # (et non vel=0) pour qu'il cesse d'être écrit — distinct du
                # maintien actif (stick centré, opérateur présent, _seen frais)
                # qui garde vel=0.0 dans _vel et reste tenu. _jog_pos est laissé
                # figé (reprise propre si l'intention revient).
                self._vel.pop(axis, None)
                self._target.pop(axis, None)
                self._seen.pop(axis, None)   # nettoie l'horodatage (anti-accumulation)

    def refresh_seen(self, now: float) -> None:
        """Rafraichit l'horodatage de tous les axes ayant une intention en cours
        (heartbeat web : nourrit le dead-man entre deux mouvements de slider)."""
        for axis in self._seen:
            self._seen[axis] = now

    def step(self, dt: float, current: Dict[int, int],
             soft_limits: Dict[int, Tuple[int, int]]) -> Dict[int, int]:
        """Avance la cible interne d'un tick et retourne les positions cibles
        a ecrire. Pur : ne lit/ecrit aucun hardware."""
        targets: Dict[int, int] = {}
        for mid, vel in self._vel.items():
            held = abs(vel) < 0.001
            # Axe au repos JAMAIS joggé (pas de _jog_pos) : on n'y touche pas
            # (ne pas clamper un axe inerte ni combattre un Home/scénario en
            # cours sur cet axe).
            if held and mid not in self._jog_pos:
                continue
            # Seed lazy : 1er tick de l'axe (vel≠0) -> cible = position reelle.
            if mid not in self._jog_pos:
                cur = current.get(mid)
                if cur is None:
                    continue
                self._jog_pos[mid] = float(cur)
            # Axe au repos mais DÉJÀ joggé cette session : MAINTIEN ACTIF. On
            # continue d'écrire Goal=_jog_pos à chaque tick — exactement comme le
            # mode cible web — sinon le servo cesse d'être réasservi et les axes
            # lourds 2/3/4 back-drivent sous la gravité (décrochage prouvé en
            # trace Pi : present dérive de +140 ticks alors que goal n'est plus
            # écrit). Le couplage 2→3 réécrit l'axe 3 dans write_positions_direct.
            if held and mid not in self._active_axes:
                self._jog_ramp[mid] = 0.0
                lo, hi = soft_limits.get(mid, (0, 4095))
                self._jog_pos[mid] = max(lo, min(hi, self._jog_pos[mid]))
                targets[mid] = int(round(self._jog_pos[mid]))
                continue
            # Vitesse max de cet axe (axes lourds 2/4 plafonnes plus bas).
            max_speed = self.JOG_MAX_SPEED_PER_AXIS.get(mid, self.JOG_MAX_SPEED)
            # Soft-start : rampe 0->1 sur JOG_RAMP_S ; remise a 0 au repos.
            if abs(vel) < 0.001:
                self._jog_ramp[mid] = 0.0
                v_eff = 0.0
            else:
                r = min(1.0, self._jog_ramp.get(mid, 0.0) + dt / self.JOG_RAMP_S)
                self._jog_ramp[mid] = r
                v_eff = vel * r
            # Integrale : la cible avance selon la vitesse effective.
            self._jog_pos[mid] += v_eff * max_speed * dt
            # Clamp aux soft-limits (SSOT backend ; rempart cote integration).
            lo, hi = soft_limits.get(mid, (0, 4095))
            self._jog_pos[mid] = max(lo, min(hi, self._jog_pos[mid]))
            # Feed-forward : sur-pilote la cible ecrite ; v_eff (rampe) evite le
            # saut au demarrage ; a l'arret v_eff=0 -> lead=0 -> arret pile.
            lead = v_eff * max_speed * self.JOG_LEAD_S
            goal = max(lo, min(hi, self._jog_pos[mid] + lead))
            targets[mid] = int(round(goal))
        # Mode cible (web) : rampe _jog_pos vers la cible absolue, vitesse bornee,
        # meme soft-start + lead que le mode velocite (sensation coherente).
        for mid, tgt in list(self._target.items()):
            if mid not in self._jog_pos:
                cur = current.get(mid)
                if cur is None:
                    continue
                self._jog_pos[mid] = float(cur)
            max_speed = self.JOG_MAX_SPEED_PER_AXIS.get(mid, self.JOG_MAX_SPEED)
            r = min(1.0, self._jog_ramp.get(mid, 0.0) + dt / self.JOG_RAMP_S)
            self._jog_ramp[mid] = r
            delta = tgt - self._jog_pos[mid]
            step_max = max_speed * dt * r
            move = max(-step_max, min(step_max, delta))
            self._jog_pos[mid] += move
            lo, hi = soft_limits.get(mid, (0, 4095))
            self._jog_pos[mid] = max(lo, min(hi, self._jog_pos[mid]))
            vel_eff = (move / dt) if dt > 0 else 0.0      # ticks/s effectifs
            lead = vel_eff * self.JOG_LEAD_S
            goal = max(lo, min(hi, self._jog_pos[mid] + lead))
            targets[mid] = int(round(goal))
        self._active_axes = {m for m, v in self._vel.items() if abs(v) >= 0.001}
        return targets

    def mirror(self, current: Dict[int, int]) -> Dict[int, int]:
        """Position commandee a refleter dans le store (Visu 3D + ghost Pi) :
        _jog_pos (l'intention, SANS le lead feed-forward) fusionnee par-dessus
        `current` complet, pour ne pas effacer les axes non joggues."""
        out = {int(k): int(v) for k, v in current.items()}
        for k, p in self._jog_pos.items():
            out[int(k)] = int(round(p))
        return out

    def snapshot(self) -> Dict[int, float]:
        """Copie de la cible interne (_jog_pos) AVANT un step, pour pouvoir
        l'annuler si l'écriture est rejetée par le garde-fou (cf. restore)."""
        return dict(self._jog_pos)

    def restore(self, snap: Dict[int, float]) -> None:
        """Annule l'avance du dernier step : restaure _jog_pos à l'instantané
        `snap` (la DERNIÈRE position acceptée) et remet les rampes à 0. Appelé
        quand l'écriture vient d'être REJETÉE par le garde-fou anti-collision.

        Pourquoi un instantané et pas un re-pin sur la position « réelle » : le
        cache de positions n'est rafraîchi qu'au front du jog, il pointe donc la
        position de DÉPART — s'y caler ferait « claquer » le bras vers le départ
        au recul. En restant sur la dernière position acceptée (= pile au
        contact), le bras se fige net, et le recul repart en douceur (rampe à 0
        → soft-start), sans trajet fantôme ni saut au dégagement."""
        self._jog_pos = dict(snap)
        for mid in self._jog_ramp:
            self._jog_ramp[mid] = 0.0

    def reset(self) -> None:
        """Vide tout l'etat (prise/lache de main) : la prochaine integration
        repart d'un seed sur la position reelle."""
        self._jog_pos.clear()
        self._jog_ramp.clear()
        self._active_axes = set()
        self._vel.clear()
        self._seen.clear()
        self._target.clear()
