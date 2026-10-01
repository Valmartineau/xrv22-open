// Store des boîtes d'encombrement éditées dans /calibrate : chargées depuis le
// localStorage (travail en cours) sinon depuis /calibration.json (état déployé),
// persistées à chaque édition. La SOURCE DE VÉRITÉ reste public/calibration.json
// — l'export (« Exporter état ») sort les boîtes éditées pour y être intégrées.
import { useCallback, useEffect, useState } from "react";
import type { CalibBox } from "../visu/calibKinematics";

const KEY = "xrv22.calibrate.boxes.v1";

// Maillon suivi par chaque boîte (cf. chaîne de pivots RobotMeshSTL).
export const LINK_NAMES = ["Base", "Shoulder", "UA", "Forearm", "Wrist", "Tête/pince"];

const r1 = (n: number) => Math.round(n * 10) / 10;

// Copie arrondie au 0,1 mm (format du fichier).
export function roundBoxes(boxes: CalibBox[]): CalibBox[] {
  return boxes.map((b) => ({
    link: b.link, c: b.c.map(r1), rotDeg: b.rotDeg.map(r1), half: b.half.map(r1),
  }));
}

// Nouvelle boîte par défaut, posée au niveau du coude pour être visible.
export function newBox(): CalibBox {
  return { link: 0, c: [0, 0, 300], rotDeg: [0, 0, 0], half: [30, 30, 30] };
}

export function useBoxesStore() {
  const [boxes, setBoxes] = useState<CalibBox[] | null>(null);

  // Recharge l'état déployé (public/calibration.json), écrase le travail local.
  const reloadFromFile = useCallback(() => {
    fetch("/calibration.json").then((r) => r.json())
      .then((d: { boxes?: CalibBox[] }) => setBoxes(d.boxes ?? []))
      .catch(() => setBoxes([]));
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) { setBoxes(JSON.parse(raw) as CalibBox[]); return; }
    } catch { /* ignore */ }
    reloadFromFile();
  }, [reloadFromFile]);

  useEffect(() => {
    if (!boxes) return;
    try { localStorage.setItem(KEY, JSON.stringify(boxes)); }
    catch { /* quota / mode privé : ignore */ }
  }, [boxes]);

  return [boxes, setBoxes, reloadFromFile] as const;
}
