import type { WsMsg } from "../types";

// Un pas d'Eddy tel que publié par le run (cf payload_du_pas, schéma spec §4).
export type EddyStep = {
  pas: number;
  positions: Record<string, number>;
  manettes: number[];
  signaux: number[];
  pression: number;
  plafond: number;
  manette_active: number;
  delta: number;
  pensee: string;
  note: string;
  bloque: boolean;
  // Dialogue-en-mouvement : ce que la personne a dit à ce pas et la réponse
  // d'Eddy (vides en run isolé ; publiés par le run dans le payload eddy.step).
  message_humain?: string;
  reponse?: string;
  ts?: number;
};

// Une ligne du fil de conversation : qui parle, et quoi.
export type DialogueLine = { qui: "humain" | "eddy"; texte: string; pas?: number };

// État d'affichage du moniteur : le dernier pas reçu (cognition + perception),
// les positions LIVE du vrai bras (flux robot.positions_tick, comme l'onglet Visu),
// et le fil de conversation accumulé (echo humain immédiat + réponses d'Eddy).
export type EddyView = {
  step: EddyStep;
  live: Record<string, number>;
  dialogue: DialogueLine[];
};

export const EDDY_VIDE: EddyStep = {
  pas: 0, positions: {}, manettes: [], signaux: [],
  pression: 0, plafond: 0, manette_active: -1, delta: 0,
  pensee: "", note: "", bloque: false, message_humain: "", reponse: "",
};

export const VIEW_VIDE: EddyView = { step: EDDY_VIDE, live: {}, dialogue: [] };

// Dernier texte dit par la personne dans le fil (pour dédoublonner l'echo).
function dernierHumain(dialogue: DialogueLine[]): string | undefined {
  for (let i = dialogue.length - 1; i >= 0; i--) {
    if (dialogue[i].qui === "humain") return dialogue[i].texte;
  }
  return undefined;
}

// Robot suivi par le moniteur (défaut du run incarné).
const ROBOT_EDDY = "robot_1";

// Réduit les messages du bus :
//  • eddy.say  → echo immédiat de ce que la personne vient de dire (avant même
//    qu'Eddy ait fait son pas), ajouté au fil ;
//  • eddy.step → pas courant ; si le pas porte une réponse d'Eddy, on l'ajoute
//    au fil. Le message humain du pas a déjà été affiché via eddy.say, sauf si
//    cet echo a été manqué (reconnexion) — dans ce cas on le rattrape ;
//  • robot.positions_tick → positions live du robot suivi ;
//  • tout autre topic → inchangé.
export function reduceEddy(prev: EddyView, msg: WsMsg): EddyView {
  if (msg.topic === "eddy.say") {
    const m = (msg.data as { message?: string }).message?.trim();
    if (!m) return prev;
    return { ...prev, dialogue: [...prev.dialogue, { qui: "humain", texte: m }] };
  }
  if (msg.topic === "eddy.step") {
    const step = msg.data as EddyStep;
    const ajouts: DialogueLine[] = [];
    const mh = step.message_humain?.trim();
    // Rattrapage : si l'echo eddy.say a été manqué, on remet le message humain.
    if (mh && dernierHumain(prev.dialogue) !== mh) {
      ajouts.push({ qui: "humain", texte: mh, pas: step.pas });
    }
    const rep = step.reponse?.trim();
    if (rep) ajouts.push({ qui: "eddy", texte: rep, pas: step.pas });
    return {
      ...prev,
      step,
      dialogue: ajouts.length ? [...prev.dialogue, ...ajouts] : prev.dialogue,
    };
  }
  if (msg.topic === "robot.positions_tick") {
    const tick = msg.data as Record<string, Record<string, number>>;
    const live = tick[ROBOT_EDDY] ?? Object.values(tick)[0] ?? prev.live;
    return { ...prev, live };
  }
  return prev;
}

// Positions à afficher en 3D : celles du pas si présentes (run/replay fidèle),
// sinon le vrai bras live (repos / avant le 1er pas).
export function ticksAffichees(view: EddyView): Record<string, number> {
  const p = view.step.positions;
  return p && Object.keys(p).length > 0 ? p : view.live;
}
