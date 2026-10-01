// Mirror du xrv22/theme/theme.py — accessible depuis les composants TS.
// La palette de base est dans tailwind.config.js. Ce fichier contient
// les fonctions et constantes qui ne sont pas couvertes par Tailwind.

// TRACK_COLORS — un par robot (theme.py)
export const TRACK_COLORS = [
  "#f6a117",   // Robot 1 — ambre
  "#e040fb",   // Robot 2 — magenta vif
  "#00e5ff",   // Robot 3 — cyan
  "#76ff03",   // Robot 4 — lime
  "#ff6e40",   // Robot 5 — corail
  "#4ade80",   // Robot 6 — vert
  "#448aff",   // Robot 7 — bleu roi
  "#f43f5e",   // Robot 8 — rouge
];

export function trackColor(index: number): string {
  return TRACK_COLORS[index % TRACK_COLORS.length];
}

export function colorForRobot(robotId: string): string {
  // robot_1 -> index 0, robot_2 -> 1, etc.
  const m = robotId.match(/(\d+)$/);
  const idx = m ? parseInt(m[1], 10) - 1 : 0;
  return trackColor(idx);
}

// État robot → couleur fond + texte (mirror STATE_COLORS / STATE_TEXT_COLORS)
export const STATE_BG: Record<string, string> = {
  IDLE:           "#2c303e",   // surface_hi
  READY:          "#0f2d1a",   // ok_dim
  RUNNING:        "#5c3208",   // amb_dim2
  PAUSED:         "#3e2204",   // amb_dim
  SOFT_STOP:      "#3e2204",
  COMM_LOST:      "#3a0a14",   // err_dim
  ERROR:          "#3a0a14",
  EMERGENCY_STOP: "#7f1d2e",   // err_deep
  LOCKED:         "#2e0e26",   // mag_dim
};

export const STATE_TEXT: Record<string, string> = {
  IDLE:           "#6a6e7e",
  READY:          "#4ade80",
  RUNNING:        "#f6a117",
  PAUSED:         "#e6b54a",
  SOFT_STOP:      "#edc57b",
  COMM_LOST:      "#f43f5e",
  ERROR:          "#f43f5e",
  EMERGENCY_STOP: "#ff6b6b",
  LOCKED:         "#a06a8f",
};

// État robot → label FR + icône (mirror sidebar.py _STATE_LABEL_FR + _STATE_ICON)
export const STATE_LABEL_FR: Record<string, string> = {
  IDLE:           "Prêt",
  READY:          "Prêt",
  RUNNING:        "En mouvement",
  PAUSED:         "En pause",
  SOFT_STOP:      "Arrêt doux",
  COMM_LOST:      "Liaison perdue",
  ERROR:          "Erreur",
  EMERGENCY_STOP: "E-STOP",
  LOCKED:         "Verrouillé",
  TORQUE_OFF:     "Torque OFF",
  DISCONNECTED:   "Déconnecté",
};

// Mix de 2 hex avec alpha — pour robot_theme()
function hex(c: string, i: number) { return parseInt(c.slice(1 + i * 2, 3 + i * 2), 16); }

function blend(hexColor: string, bg: string, alpha: number): string {
  const r1 = hex(hexColor, 0), g1 = hex(hexColor, 1), b1 = hex(hexColor, 2);
  const r2 = hex(bg, 0),       g2 = hex(bg, 1),       b2 = hex(bg, 2);
  const r = Math.round(r1 * alpha + r2 * (1 - alpha));
  const g = Math.round(g1 * alpha + g2 * (1 - alpha));
  const b = Math.round(b1 * alpha + b2 * (1 - alpha));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

// Mirror theme.py:robot_theme() — toutes les nuances dérivées d'une couleur robot
export function robotTheme(hexColor: string) {
  return {
    color:  hexColor,
    bg:     blend(hexColor, "#1e2130", 0.08),  // BG
    bg_med: blend(hexColor, "#252836", 0.18),  // SURFACE
    bg_vif: blend(hexColor, "#252836", 0.35),
    border: blend(hexColor, "#3a3e52", 0.30),  // BORDER_HI
    text:   "#1a1a2e",
    dim:    blend(hexColor, "#000000", 0.5),
  };
}
