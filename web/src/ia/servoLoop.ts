// Boucle de contrôle "suivi de la main" (Jalon 1), portée en TS depuis
// JogIntegrator (xrv22/core/jog_integrator.py). Pur, testable, sans I/O.
// Spec : docs/superpowers/specs/2026-06-09-ia-suivi-main-webcam-design.md

// Vitesses max par axe (ticks/s) — défauts (surchargés à l'exécution par vmax).
export const VMAX_AXIS: Record<number, number> = { 1: 750, 2: 250, 4: 400 };

// Axes pilotés et la composante d'offset qui les commande.
// L'axe 2 (épaule) rejoint le coude sur le vertical ; l'axe 3 suit par couplage
// mécanique côté backend (jamais écrit ici).
export const AXIS_COMPONENT: Record<number, "x" | "y"> = { 1: "x", 2: "y", 4: "y" };

// Sens de chaque axe (ajusté en validation live).
export const AXIS_SIGN: Record<number, 1 | -1> = { 1: 1, 2: 1, 4: 1 };

export const DEADZONE = 0.12;   // fraction du demi-cadre
export const RAMP_S = 0.18;     // durée rampe soft-start (s)
export const EMA_ALPHA = 0.35;  // lissage de l'offset

// Pince (axe 7) : plage d'écart pouce-index normalisé (doigts joints → écartés).
export const PINCH_MIN = 0.15;  // doigts joints
export const PINCH_MAX = 1.10;  // doigts écartés

// Offset normalisé [-1..1] d'un point (coords normalisées 0..1) vs centre image.
export function computeOffset(cx: number, cy: number): { x: number; y: number } {
  return { x: (cx - 0.5) * 2, y: (cy - 0.5) * 2 };
}

// Zone morte : 0 sous le seuil, valeur inchangée sinon.
export function applyDeadzone(v: number, dz: number = DEADZONE): number {
  return Math.abs(v) < dz ? 0 : v;
}

// Lissage exponentiel.
export function ema(prev: number, next: number, alpha: number = EMA_ALPHA): number {
  return prev + alpha * (next - prev);
}

export interface ServoState {
  target: Record<number, number>;  // cible accumulée par axe
  ramp: Record<number, number>;    // rampe 0..1 par axe
}

export function createServoState(): ServoState {
  return { target: {}, ramp: {} };
}

export interface ServoStep {
  offset: { x: number; y: number };  // offset lissé [-1..1]
  present: boolean;                   // main détectée récemment
  armed: boolean;                    // suivi armé
  dt: number;                        // pas de temps (s)
  current: Record<number, number>;   // positions live (seed)
  sign?: Record<number, number>;     // sens par axe (toggles UI) ; défaut AXIS_SIGN
  vmax?: Record<number, number>;     // vitesse par axe (curseurs UI) ; défaut VMAX_AXIS
  enabled?: Record<number, boolean>; // axe actif/inactif (cases UI) ; défaut tous actifs
}

// Avance la boucle d'un tick. Mute `state` et renvoie les cibles à écrire
// ({} si non armé / aucun axe seedé).
export function stepServo(
  state: ServoState,
  inp: ServoStep,
): Record<number, number> {
  const targets: Record<number, number> = {};
  if (!inp.armed) return targets;
  const sign = inp.sign ?? AXIS_SIGN;
  for (const axisStr of Object.keys(AXIS_COMPONENT)) {
    const axis = Number(axisStr);
    const comp = AXIS_COMPONENT[axis];
    // Axe désactivé (case décochée) : non écrit + état réinitialisé pour
    // re-seeder sans saut à la réactivation.
    if (inp.enabled && inp.enabled[axis] === false) {
      delete state.target[axis];
      state.ramp[axis] = 0;
      continue;
    }
    // Seed lazy : 1re fois, cible = position live (skip si inconnue).
    if (state.target[axis] === undefined) {
      const cur = inp.current[axis];
      if (cur === undefined) continue;
      state.target[axis] = cur;
    }
    // Vitesse intentionnelle (-1..1) : 0 si main perdue ou dans la zone morte.
    const raw = inp.present ? applyDeadzone(inp.offset[comp]) : 0;
    const vel = raw * (sign[axis] ?? 1);
    // Rampe soft-start.
    if (vel === 0) {
      state.ramp[axis] = 0;
    } else {
      state.ramp[axis] = Math.min(1, (state.ramp[axis] ?? 0) + inp.dt / RAMP_S);
    }
    const vEff = vel * (state.ramp[axis] ?? 0);
    // Intégration + clamp anti-windup navigateur (le Pi clampe les vraies butées).
    state.target[axis] += vEff * (inp.vmax?.[axis] ?? VMAX_AXIS[axis]) * inp.dt;
    state.target[axis] = Math.max(0, Math.min(4095, state.target[axis]));
    targets[axis] = Math.round(state.target[axis]);
  }
  return targets;
}

// Mappe l'écart pince [PINCH_MIN..PINCH_MAX] vers la position de l'axe 7,
// entre closedTicks (doigts joints) et openTicks (doigts écartés). Proportionnel.
export function pinchToAxis7(
  pinch: number, openTicks: number, closedTicks: number,
): number {
  const t = Math.max(0, Math.min(1,
    (pinch - PINCH_MIN) / (PINCH_MAX - PINCH_MIN)));
  return Math.round(closedTicks + t * (openTicks - closedTicks));
}

// Miroir 1:1 (poignet) : mappe le signal `v` entre deux repères de calibration
// (signal s→ticks t), clampé à l'intervalle des ticks. Sert axes 5 et 6.
export function mapLinear(
  v: number, s1: number, t1: number, s2: number, t2: number,
): number {
  if (s2 === s1) return Math.round(t1);
  const lo = Math.min(t1, t2), hi = Math.max(t1, t2);
  const out = t1 + ((v - s1) / (s2 - s1)) * (t2 - t1);
  return Math.round(Math.max(lo, Math.min(hi, out)));
}
