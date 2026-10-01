// Wrapper mediapipe HandLandmarker. Charge le modèle vendoré (offline) et
// expose une détection frame-par-frame renvoyant le centre de la main.
import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

export type HandSample = {
  cx: number; cy: number;   // centre paume (repère 9), coords normalisées 0..1
  pinch: number;            // écart pouce(4)-index(8) normalisé par dist(0,9)
  roll: number;             // angle main dans l'image (rad) — rotation poignet (fiable)
  pitch: number;            // proxy d'inclinaison via z — flexion poignet (approx)
  points: { x: number; y: number }[];  // les 21 repères (overlay), normalisés 0..1
};

export type HandTracker = {
  // Renvoie l'échantillon main ou null si absente.
  detect: (video: HTMLVideoElement, tMs: number) => HandSample | null;
  close: () => void;
};

// Repères mediapipe : 0=poignet, 4=bout pouce, 8=bout index, 9=base majeur.
const PALM_LANDMARK = 9;

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export async function createHandTracker(): Promise<HandTracker> {
  const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
  const landmarker = await HandLandmarker.createFromOptions(fileset, {
    baseOptions: {
      modelAssetPath: "/mediapipe/hand_landmarker.task",
      delegate: "GPU",
    },
    numHands: 1,
    runningMode: "VIDEO",
  });
  return {
    detect(video, tMs) {
      const res = landmarker.detectForVideo(video, tMs);
      const hand = res.landmarks?.[0];
      if (!hand || hand.length <= PALM_LANDMARK) return null;
      const p = hand[PALM_LANDMARK];
      // Taille de la main (poignet→base majeur) pour normaliser l'écart pince.
      const scale = dist(hand[0], hand[PALM_LANDMARK]) || 1e-6;
      const pinch = dist(hand[4], hand[8]) / scale;
      // Rotation = angle du vecteur poignet→base-majeur dans l'image (fiable).
      const roll = Math.atan2(hand[9].y - hand[0].y, hand[9].x - hand[0].x);
      // Flexion = proxy via la profondeur z mediapipe (approximatif en 2D).
      const pitch = (hand[0].z - hand[9].z) / scale;
      const points = hand.map((lm) => ({ x: lm.x, y: lm.y }));
      return { cx: p.x, cy: p.y, pinch, roll, pitch, points };
    },
    close() {
      landmarker.close();
    },
  };
}
