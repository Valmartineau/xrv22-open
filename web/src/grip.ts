// ── Calibration de l'écart de la pince (axe 7) ───────────────────────────
// Source de vérité unique pour convertir la position brute Dynamixel (ticks)
// de l'axe 7 en écart réel entre les doigts, en millimètres.
//
// Modèle : linéaire. Deux ancres mesurées en live sur robot_1 le 2026-06-15 :
//   - contact (doigts joints)     : tick 1649  → 0 mm
//   - butée d'ouverture (soft-max): tick 2860  → 46 mm
// La pente (mm/tick) est une propriété géométrique de la pince, quasi identique
// d'un robot à l'autre (robot_2 : 2780→45 mm ≈ même pente). Seule la butée haute
// varie selon le soft-limit propre à chaque robot — d'où un modèle ancré sur le
// contact + pente constante, valable quel que soit le robot.

export const GRIP_CLOSE_TICK = 1649; // doigts au contact → écart 0 mm
export const GRIP_OPEN_TICK = 2860;  // butée d'ouverture robot_1 → 46 mm
export const GRIP_SPAN_MM = 46.0;    // écart réel total à GRIP_OPEN_TICK

// Pente géométrique : mm d'écart par tick moteur.
export const GRIP_MM_PER_TICK = GRIP_SPAN_MM / (GRIP_OPEN_TICK - GRIP_CLOSE_TICK);

// Demi-écartement par doigt (les 2 doigts s'écartent symétriquement) — pour le mesh 3D.
export const GRIP_HALF_SPAN_MM = GRIP_SPAN_MM / 2;

/** Écart réel entre les doigts (mm) pour une position brute `tick` de l'axe 7. */
export function gripMm(tick: number): number {
  return Math.max(0, (tick - GRIP_CLOSE_TICK) * GRIP_MM_PER_TICK);
}
