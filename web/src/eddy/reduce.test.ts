import { describe, it, expect } from "vitest";
import {
  reduceEddy, ticksAffichees, VIEW_VIDE, type EddyView, type EddyStep,
} from "./reduce";

const PAS: EddyStep = {
  pas: 5, positions: { "5": 2079 }, manettes: [2048, 2079],
  signaux: [8412, 5310, 47], pression: 47, plafond: 500,
  manette_active: 4, delta: -2, pensee: "p", note: "n", bloque: false,
};

describe("reduceEddy", () => {
  it("met à jour le pas courant sur un message eddy.step", () => {
    const next = reduceEddy(VIEW_VIDE, { topic: "eddy.step", data: PAS, ts: 1 });
    expect(next.step.pas).toBe(5);
    expect(next.step.pression).toBe(47);
  });

  it("met à jour les positions live du robot_1 sur robot.positions_tick", () => {
    const tick = { robot_1: { "1": 2048, "5": 2083 }, robot_3: { "1": 999 } };
    const next = reduceEddy(VIEW_VIDE, { topic: "robot.positions_tick", data: tick, ts: 2 });
    expect(next.live).toEqual({ "1": 2048, "5": 2083 });  // robot_1 retenu
  });

  it("ignore les autres topics (garde l'état précédent)", () => {
    const prev: EddyView = { step: PAS, live: { "1": 1 }, dialogue: [] };
    const next = reduceEddy(prev, { topic: "engine.tick", data: {}, ts: 3 });
    expect(next).toBe(prev);
  });
});

describe("reduceEddy — dialogue-en-mouvement", () => {
  it("eddy.say ajoute un echo immédiat de la personne dans le fil", () => {
    const next = reduceEddy(VIEW_VIDE,
      { topic: "eddy.say", data: { message: "  bonjour Eddy  " }, ts: 1 });
    expect(next.dialogue).toEqual([{ qui: "humain", texte: "bonjour Eddy" }]);
  });

  it("eddy.say ignore un message vide", () => {
    const next = reduceEddy(VIEW_VIDE, { topic: "eddy.say", data: { message: "   " }, ts: 1 });
    expect(next.dialogue).toEqual([]);
  });

  it("eddy.step ajoute la réponse d'Eddy sans dupliquer le message déjà echoé", () => {
    const apresEcho = reduceEddy(VIEW_VIDE,
      { topic: "eddy.say", data: { message: "tu fais quoi ?" }, ts: 1 });
    const step: EddyStep = { ...PAS, message_humain: "tu fais quoi ?", reponse: "je cherche" };
    const next = reduceEddy(apresEcho, { topic: "eddy.step", data: step, ts: 2 });
    expect(next.dialogue).toEqual([
      { qui: "humain", texte: "tu fais quoi ?" },
      { qui: "eddy", texte: "je cherche", pas: 5 },
    ]);
  });

  it("eddy.step rattrape le message humain si l'echo eddy.say a été manqué", () => {
    const step: EddyStep = { ...PAS, message_humain: "coucou", reponse: "oui" };
    const next = reduceEddy(VIEW_VIDE, { topic: "eddy.step", data: step, ts: 2 });
    expect(next.dialogue).toEqual([
      { qui: "humain", texte: "coucou", pas: 5 },
      { qui: "eddy", texte: "oui", pas: 5 },
    ]);
  });

  it("eddy.step sans dialogue ne touche pas le fil (run isolé)", () => {
    const next = reduceEddy(VIEW_VIDE, { topic: "eddy.step", data: PAS, ts: 2 });
    expect(next.dialogue).toEqual([]);
    expect(next.step.pas).toBe(5);
  });
});

describe("ticksAffichees", () => {
  it("utilise le live tant qu'aucun pas n'a de positions (vrai bras au repos)", () => {
    const view: EddyView = { step: VIEW_VIDE.step, live: { "5": 2083 }, dialogue: [] };
    expect(ticksAffichees(view)).toEqual({ "5": 2083 });
  });

  it("préfère les positions du pas quand elles existent (run/replay fidèle)", () => {
    const view: EddyView = { step: PAS, live: { "5": 2083 }, dialogue: [] };
    expect(ticksAffichees(view)).toEqual({ "5": 2079 });  // celles du pas
  });
});
