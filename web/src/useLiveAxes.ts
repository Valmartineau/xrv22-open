// Modèle unique des sliders d'axes — useLiveAxes.
//
// Hors mode Direct : le slider est le MIROIR LIVE de la position du robot
// (lecture seule, suit le topic WS robot.positions_tick).
// En mode Direct : un axe que l'utilisateur glisse devient une CONSIGNE — le
// pouce tient sa valeur (pas de rebond), le robot la rejoint via jog.intent WS.
// Les axes NON commandés continuent de suivre le robot (ex. axe 3 couplé qui
// bouge tout seul) — sinon ils afficheraient une valeur périmée.
//
// Ce hook est la source de vérité unique du comportement : Connexion, Visu et
// Positions le consomment tous. Les spécificités d'un onglet (couplage 2-3,
// preview timeline) se composent par-dessus, dans la page.

import { useEffect, useRef, useState } from "react";
import { cmdDirectMode } from "./commands";
import type { Robot } from "./types";

export type AxisLock = { reason: string };

export type LiveAxes = {
  value: (axis: number) => number;
  locked: (axis: number) => AxisLock | undefined;
  onPointerDown: (axis: number) => void;
  onPointerUp: (axis: number) => void;
  onChange: (axis: number, v: number) => void;
};

const LOCK_DIRECT: AxisLock = {
  reason: "Mode Direct requis pour piloter ce slider",
};

// Clampe v aux soft-limits de l'axe (défaut [0, 4095]).
function clampToLimits(robot: Robot | undefined, axis: number, v: number): number {
  const sl = robot?.soft_limits?.[String(axis)];
  const lo = sl ? sl[0] : 0;
  const hi = sl ? sl[1] : 4095;
  return Math.max(lo, Math.min(hi, v));
}

export function useLiveAxes(opts: {
  rid: string;
  robot: Robot | undefined;
  hw: Record<string, number> | undefined;
  direct: boolean;
  wsSend: (obj: unknown) => void;
  onError: (msg: string) => void;
}): LiveAxes {
  const { rid, robot, hw, direct, wsSend, onError: _onError } = opts;

  const [targets, setTargets] = useState<Record<number, number>>({});
  const [draggingAxis, setDraggingAxis] = useState<number | null>(null);
  // Axes que l'utilisateur a glissés dans la session Direct courante : leur
  // consigne est figée (pas de rebond) ; les autres axes suivent le robot.
  const commandedAxes = useRef<Set<number>>(new Set());

  // Reset quand on change de robot actif.
  useEffect(() => {
    setTargets({});
    setDraggingAxis(null);
    commandedAxes.current.clear();
  }, [rid]);

  // Sortie du mode Direct : plus aucune consigne figée, tout suit le robot.
  useEffect(() => {
    if (!direct) commandedAxes.current.clear();
  }, [direct]);

  // Miroir live : les targets suivent la position réelle du robot. En Direct,
  // on EXCLUT les axes commandés par l'utilisateur (leur consigne est figée,
  // sinon le pouce rebondirait au relâchement) ; les axes non commandés, eux,
  // continuent de suivre le robot — ex. axe 3 couplé qui bouge tout seul, qui
  // resterait sinon sur une valeur périmée. L'axe en cours de drag est gelé.
  useEffect(() => {
    if (draggingAxis !== null || !hw) return;
    setTargets((cur) => {
      let changed = false;
      const next = { ...cur };
      for (const k of Object.keys(hw)) {
        const a = Number(k);
        if (direct && commandedAxes.current.has(a)) continue;
        const v = hw[k];
        if (next[a] !== v) { next[a] = v; changed = true; }
      }
      return changed ? next : cur;
    });
  }, [hw, draggingAxis, direct]);

  // Prise de main : acquire/release du mode Direct côté serveur.
  // L'early-return avant le cleanup garantit exactement un appel true à
  // l'activation et un appel false à la désactivation (pas de parasites).
  useEffect(() => {
    if (!robot?.connected || !direct) return;
    cmdDirectMode(rid, true).catch(() => {});
    return () => { cmdDirectMode(rid, false).catch(() => {}); };
  }, [direct, rid, robot?.connected]);

  // Heartbeat jog.alive à 10 Hz tant qu'un axe est en cours de drag.
  useEffect(() => {
    if (draggingAxis === null || !direct) return;
    const id = setInterval(() => wsSend({ type: "jog.alive", rid }), 100);
    return () => clearInterval(id);
  }, [draggingAxis, direct, rid, wsSend]);

  return {
    value: (axis) => targets[axis] ?? hw?.[String(axis)] ?? 2048,
    // Le verrou est global (mode Direct requis). Le type LiveAxes garde un
    // paramètre `axis` pour permettre une granularité par-axe ultérieure sans
    // casser les appelants ; l'implémentation actuelle n'en a pas besoin.
    locked: () => (direct ? undefined : LOCK_DIRECT),
    onPointerDown: (axis) => {
      setDraggingAxis(axis);   // le serveur seed à l'acquire -> pas de reseed client
    },
    onPointerUp: () => setDraggingAxis(null),
    onChange: (axis, v) => {
      const clamped = clampToLimits(robot, axis, v);
      commandedAxes.current.add(axis);
      setTargets((cur) => ({ ...cur, [axis]: clamped }));
      if (direct && robot?.connected && robot.torque_enabled) {
        wsSend({ type: "jog.intent", rid, axis, target: clamped });
      }
    },
  };
}
