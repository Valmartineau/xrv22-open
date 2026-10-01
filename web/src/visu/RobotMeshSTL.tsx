// Rendu STL réel du robot RXA-200-M, piloté par la calibration faite à la main
// dans l'outil /calibrate.
//
// La calibration est chargée DYNAMIQUEMENT (fetch /calibration.json) — pas
// bundlée — pour pouvoir itérer sans rebuild : on remplace le fichier servi et
// un simple reload suffit.
//
// Repère Z-up (le parent dans Visu applique -90° X vers Y-up). Chaque pièce est
// placée à sa pose calibrée ; les articulations sont chaînées hiérarchiquement
// (cumul naturel par imbrication).

import { Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLoader } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { Vector3, Quaternion, Euler, DoubleSide, type BufferGeometry } from "three";
import { jointAngle } from "./fk";
import { PARTS } from "../calibrate/parts";
import { gripMm, GRIP_CLOSE_TICK } from "../grip";

type Vec3 = [number, number, number];
type CalibAxis = { pos: number[]; rotDeg: number[] };
type CalibPiece = {
  offset: number[]; rotDeg: number[]; axisLocal: number[] | null; joint: number | null;
};
type CalibData = {
  axes: Record<string, CalibAxis>;
  pieces: Record<string, CalibPiece>;
  refSurfaceZ?: number; // hauteur du sol dans le repère calibré (le robot repose dessus)
};

const DEG = Math.PI / 180;

// Pince (axe 7) : écartement des doigts via la calibration partagée (grip.ts).
// GRIP_CLOSE_TICK = contact (écart 0) ; gripMm() donne l'écart réel total en mm.

// Décalage vertical (mm) du robot pour le poser sur le sol Z=0 (calé visuellement).
const GROUND_OFFSET_Z = 150;

const URL_BY_NAME: Record<string, string> = Object.fromEntries(
  PARTS.map((p) => [p.name, p.url]),
);
const partUrl = (name: string) => URL_BY_NAME[name.split("#")[0]] ?? "";

function axisDir(axes: CalibData["axes"], label: string): Vector3 {
  const e = axes[label]?.rotDeg ?? [0, 0, 0];
  return new Vector3(1, 0, 0)
    .applyEuler(new Euler(e[0] * DEG, e[1] * DEG, e[2] * DEG))
    .normalize();
}
const axisPos = (axes: CalibData["axes"], label: string): Vec3 =>
  (axes[label]?.pos ?? [0, 0, 0]) as Vec3;

interface RobotMeshSTLProps {
  ticks: Record<string, number> | undefined;
  color: string;
  dimmed?: boolean;
}

// Groupe d'articulation : rotation `angle` autour de l'axe `label` (direction
// calibrée passant par sa position).
function Pivot({ axes, label, angle, children }: {
  axes: CalibData["axes"]; label: string; angle: number; children: ReactNode;
}) {
  const pos = axisPos(axes, label);
  const quat = useMemo(
    () => new Quaternion().setFromAxisAngle(axisDir(axes, label), angle).toArray() as
      [number, number, number, number],
    [axes, label, angle],
  );
  return (
    <group position={pos}>
      <group quaternion={quat}>
        <group position={[-pos[0], -pos[1], -pos[2]]}>
          {children}
        </group>
      </group>
    </group>
  );
}

// Pièce STL à sa pose calibrée (offset monde + rotation autour de son axe local).
// `slide` = translation supplémentaire (utilisée pour l'ouverture des doigts).
function StaticPart({ piece, name, color, opacity, emissive, slide }: {
  piece: CalibPiece | undefined; name: string; color: string; opacity: number;
  emissive: number; slide?: Vec3;
}) {
  const geom = useLoader(STLLoader, partUrl(name)) as BufferGeometry;
  if (!piece) return null;
  const s = slide ?? [0, 0, 0];
  const off: Vec3 = [
    piece.offset[0] + s[0], piece.offset[1] + s[1], piece.offset[2] + s[2],
  ];
  const piv = (piece.axisLocal ?? [0, 0, 0]) as Vec3;
  const rot = piece.rotDeg.map((d) => d * DEG) as Vec3;
  return (
    <group position={off}>
      <group position={piv}>
        <group rotation={rot}>
          <group position={[-piv[0], -piv[1], -piv[2]]}>
            <mesh geometry={geom}>
              <meshStandardMaterial color={color} transparent opacity={opacity}
                                    emissive={color} emissiveIntensity={emissive}
                                    roughness={0.6} metalness={0.2} side={DoubleSide} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}

export function RobotMeshSTL({ ticks, color, dimmed = false }: RobotMeshSTLProps) {
  const [calib, setCalib] = useState<CalibData | null>(null);
  useEffect(() => {
    let ok = true;
    fetch("/calibration.json")
      .then((r) => r.json())
      .then((d) => { if (ok) setCalib(d as CalibData); })
      .catch(() => { /* pas de calibration servie */ });
    return () => { ok = false; };
  }, []);

  const a1 = useMemo(() => jointAngle(ticks, 1), [ticks]);
  const a2 = useMemo(() => jointAngle(ticks, 2), [ticks]); // épaule (2·3)
  const a4 = useMemo(() => jointAngle(ticks, 4), [ticks]); // coude
  const a5 = useMemo(() => jointAngle(ticks, 5), [ticks]); // poignet
  const a6 = useMemo(() => jointAngle(ticks, 6), [ticks]); // roll tête

  // Pince (axe 7) : TRANSLATION des doigts (rapprochement de 2 plans), pas une
  // rotation. Ouverture normalisée 0..1 depuis le tick 7 (repris du wireframe).
  const tick7 = ticks?.["7"] ?? GRIP_CLOSE_TICK;
  // Demi-écartement par doigt : les 2 doigts s'écartent symétriquement.
  const slideMm = gripMm(tick7) / 2; // écartement le long de X local de la pince

  if (!calib) return null;
  const { axes, pieces } = calib;
  // Décalage vertical pour poser le robot sur le sol (Z=0). Calé visuellement.
  const groundOffset = GROUND_OFFSET_Z;
  // Actif : couleur vive du robot + leger glow emissif. Non actif : meme
  // couleur (identite du robot conservee) mais transparence legere.
  const c = color || "#b08bd0";
  const op = dimmed ? 0.55 : 1.0;
  const emi = dimmed ? 0 : 0.25;
  const part = (name: string, slide?: Vec3) =>
    <StaticPart piece={pieces[name]} name={name} color={c} opacity={op}
                emissive={emi} slide={slide} />;

  return (
    <Suspense fallback={null}>
    <group position={[0, 0, groundOffset]}>
      {part("Base")}
      {/* axe 1 (rotation base) : sens inversé vs ticks */}
      <Pivot axes={axes} label="1" angle={-a1}>
        {part("Shoulder")}
        <Pivot axes={axes} label="2·3" angle={a2}>
          {part("UA")}
          {/* coude : sens inversé (-a4) — l'axe 4 tournait à l'envers vs wireframe */}
          <Pivot axes={axes} label="4" angle={-a4}>
            {part("Forearm")}
            <Pivot axes={axes} label="5" angle={a5}>
              {part("Wrist")}
              <Pivot axes={axes} label="6" angle={a6}>
                {part("Gripper")}
                {part("Gripper-Prop")}
                {part("Gripper-Bar")}
                {/* pince : les 2 doigts s'écartent symétriquement le long de X */}
                {part("Finger", [-slideMm, 0, 0])}
                {part("Finger#2", [slideMm, 0, 0])}
              </Pivot>
            </Pivot>
          </Pivot>
        </Pivot>
      </Pivot>
    </group>
    </Suspense>
  );
}
