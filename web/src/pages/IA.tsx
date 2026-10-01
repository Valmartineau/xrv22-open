// Onglet IA — Jalon 1 : "le bras suit ma main".
// Webcam (du navigateur) → mediapipe HandLandmarker → offset → boucle vitesse
// (servoLoop) → écriture Direct REST. Ouvrir DEPUIS LE MAC (pas l'écran du Pi).
// Spec : docs/superpowers/specs/2026-06-09-ia-suivi-main-webcam-design.md
import { useCallback, useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { useActiveRobot } from "../liveAxes";
import { cmdWriteDirect, cmdDirectMode } from "../commands";
import { useLiveBus } from "../useLiveBus";
import type { WsMsg } from "../types";
import { createHandTracker, type HandTracker } from "../ia/handTracker";
import {
  computeOffset, ema, createServoState, stepServo, pinchToAxis7, mapLinear, DEADZONE,
  type ServoState,
} from "../ia/servoLoop";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import { RobotMeshSTL } from "../visu/RobotMeshSTL";
import { colorForRobot } from "../theme";
import {
  worldBoxes, boxCollisionPairs, boxGroundHit, sweepContacts, restGroundBoxes,
  type BoxPose,
} from "../visu/boxCollision";
import { type CalibData } from "../visu/calibKinematics";
import { CollisionBoxes } from "../visu/CollisionBoxes";
import { REF_UP } from "../visu/fk";
import { robotOffsetX } from "../visu/placement";

const LOOP_HZ = 15;
const PRESENT_TIMEOUT_MS = 300;
// Limiteur de vitesse de l'axe 5 (flexion) : signal z bruité → on borne le
// déplacement par tick (≈ MAX_STEP_5 × LOOP_HZ ticks/s) pour lisser les à-coups.
const MAX_STEP_5 = 20;
// Marge de sécurité (mm) ajoutée aux rayons de capsule dérivés du STL (tunable).
const COLLISION_MARGIN = 10;
const SPACING_DEFAULT = 350; // doit matcher Visu (xrv22.visu.spacing*Mm)
// Noms des maillons (cf. boxes de calibration.json) pour nommer les collisions.
const LINK_NAMES = ["Base", "Shoulder", "UA", "Forearm", "Wrist", "Pince"];

// Évalue le garde-fou anti-collision pour une pose candidate (boîtes
// d'encombrement par pièce STL).
// Partagé par le mode webcam (gel) et le mode sliders (indicateur).
function evalGuard(
  candidateTicks: Record<string, number>, rid: string, cal: CalibData | null,
  selfExclude: Set<string>, groundIdx: number[], groundOn: boolean,
  robots: { id: string }[], pos: Record<string, Record<string, number>>,
  selfMargin: number,
): { blocked: boolean; reason: string; hitIdx: number[] } {
  if (!cal?.boxes?.length) return { blocked: false, reason: "", hitIdx: [] };
  const sr = Number(localStorage.getItem("xrv22.visu.spacingRightMm")) || SPACING_DEFAULT;
  const sl = Number(localStorage.getItem("xrv22.visu.spacingLeftMm")) || SPACING_DEFAULT;
  const selfBoxes = worldBoxes(candidateTicks, robotOffsetX(rid, sr, sl), cal);
  const poses: BoxPose[] = [{ id: rid, boxes: selfBoxes }];
  for (const r of robots) {
    if (r.id === rid) continue;
    const hwOther = pos[r.id];
    if (!hwOther) continue;
    poses.push({ id: r.id, boxes: worldBoxes(hwOther, robotOffsetX(r.id, sr, sl), cal) });
  }
  // Marge auto-collision réglable ; sol/inter-robots gardent la marge de base.
  const hits = boxCollisionPairs(poses, selfMargin, selfExclude);
  const onGround = groundOn &&
    boxGroundHit(selfBoxes, cal.refSurfaceZ ?? 0, COLLISION_MARGIN, groundIdx);
  // Boîtes fautives du robot actif (paires en collision + contact sol) — pour
  // les surligner en rouge dans l'affichage debug.
  const hitIdx = new Set<number>();
  const pairLabels = new Set<string>();
  for (const h of hits) {
    if (h.a === rid) hitIdx.add(h.ai);
    if (h.b === rid) hitIdx.add(h.bi);
    if (h.a === h.b) {
      const la = LINK_NAMES[cal.boxes[h.ai].link] ?? "?";
      const lb = LINK_NAMES[cal.boxes[h.bi].link] ?? "?";
      pairLabels.add(`${la}×${lb}`);
    }
  }
  if (onGround) {
    for (const i of groundIdx) {
      if (boxGroundHit(selfBoxes, cal.refSurfaceZ ?? 0, COLLISION_MARGIN, [i])) hitIdx.add(i);
    }
  }
  if (hits.length > 0) {
    const auto = hits.some((h) => h.a === h.b);
    const detail = auto ? ` ${[...pairLabels].join(", ")} · marge ${selfMargin}` : "";
    return { blocked: true, hitIdx: [...hitIdx],
             reason: auto ? `auto-collision${detail}` : "robot voisin" };
  }
  if (onGround) return { blocked: true, reason: "sol", hitIdx: [...hitIdx] };
  return { blocked: false, reason: "", hitIdx: [] };
}

// Topologie main mediapipe (21 repères) pour dessiner le squelette.
const HAND_CONNECTIONS: [number, number][] = [
  [0, 1], [1, 2], [2, 3], [3, 4],          // pouce
  [0, 5], [5, 6], [6, 7], [7, 8],          // index
  [5, 9], [9, 10], [10, 11], [11, 12],     // majeur
  [9, 13], [13, 14], [14, 15], [15, 16],   // annulaire
  [13, 17], [0, 17], [17, 18], [18, 19], [19, 20], // auriculaire
];

// Calibration miroir poignet : deux repères (signal capté → ticks axe).
type CalPair = { s: number; t: number };
type Cal = { a: CalPair | null; b: CalPair | null };

export default function IA() {
  const { positions, robots } = useStore();
  const { activeRid } = useActiveRobot();

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const trackerRef = useRef<HandTracker | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const servoRef = useRef<ServoState>(createServoState());
  const offsetRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const lastDetectRef = useRef<number>(0);
  const armedRef = useRef<boolean>(false);
  const ridRef = useRef<string>(activeRid);
  const posRef = useRef(positions);
  const softLimitsRef = useRef<Record<string, [number, number]>>({});
  const robotsRef = useRef(robots);

  const [ready, setReady] = useState(false);
  const [armed, setArmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [collision, setCollision] = useState(false);
  const [collisionReason, setCollisionReason] = useState("");
  const [hitBoxes, setHitBoxes] = useState<number[]>([]); // boîtes fautives (debug rouge)
  const [calib, setCalib] = useState<CalibData | null>(null);
  const calibRef = useRef<CalibData | null>(null);
  const [groundGuard, setGroundGuard] = useState<boolean>(
    () => localStorage.getItem("ia.groundGuard") !== "0", // ON par défaut
  );
  const groundRef = useRef<boolean>(true);
  // Exclusions calculées une fois à la pose de repos : paires de boîtes déjà en
  // contact (auto) + boîtes à surveiller au sol (les autres reposent au plancher).
  const selfExcludeRef = useRef<Set<string>>(new Set());
  const groundSegsRef = useRef<number[]>([]);
  // Mode sliders : piloter la sim 3D axe par axe sans webcam (test du garde-fou).
  // Indicateur : le STL suit toujours, le badge rouge signale la collision.
  const [sliderMode, setSliderMode] = useState(false);
  const [showCapsules, setShowCapsules] = useState(false);
  const sliderModeRef = useRef(false);
  const [sliderTicks, setSliderTicks] = useState<Record<string, number>>(
    () => ({ "1": 2048, "2": 2048, "4": 2048, "5": 2048, "6": 2048, "7": 2048 }),
  );
  const sliderTicksRef = useRef(sliderTicks);
  // Marge auto-collision réglable en direct (mm). Mémorisée.
  const [selfMargin, setSelfMargin] = useState<number>(
    () => { const v = localStorage.getItem("ia.selfMargin"); return v === null ? 10 : Number(v); },
  );
  const selfMarginRef = useRef(selfMargin);
  useEffect(() => { sliderModeRef.current = sliderMode; }, [sliderMode]);
  useEffect(() => { sliderTicksRef.current = sliderTicks; }, [sliderTicks]);
  useEffect(() => {
    selfMarginRef.current = selfMargin;
    localStorage.setItem("ia.selfMargin", String(selfMargin));
  }, [selfMargin]);
  const [debug, setDebug] = useState<{ x: number; y: number; present: boolean }>(
    { x: 0, y: 0, present: false },
  );
  // Sens d'inversion par axe — dépend de la position du PC face au robot.
  // Mémorisé dans le navigateur ; défaut inversé (config validée 2026-06-09).
  const [invertX, setInvertX] = useState<boolean>(() => {
    const v = localStorage.getItem("ia.invertX"); return v === null ? true : v === "1";
  });
  const [invertY, setInvertY] = useState<boolean>(() => {
    const v = localStorage.getItem("ia.invertY"); return v === null ? true : v === "1";
  });
  const signRef = useRef<Record<number, number>>({ 1: -1, 2: 1, 4: -1 });

  // Vitesses de suivi (ticks/s) réglables en direct, mémorisées.
  const [speedX, setSpeedX] = useState<number>(() => {
    const v = localStorage.getItem("ia.speedX"); return v === null ? 400 : Number(v);
  });
  const [speedShoulder, setSpeedShoulder] = useState<number>(() => {
    const v = localStorage.getItem("ia.speedShoulder"); return v === null ? 250 : Number(v);
  });
  const [speedElbow, setSpeedElbow] = useState<number>(() => {
    const v = localStorage.getItem("ia.speedElbow"); return v === null ? 400 : Number(v);
  });
  const vmaxRef = useRef<Record<number, number>>({ 1: 400, 2: 250, 4: 400 });
  // Sens de l'épaule (axe 2) sur le vertical — indépendant du coude. Défaut non inversé.
  const [invertShoulder, setInvertShoulder] = useState<boolean>(
    () => localStorage.getItem("ia.invertShoulder") === "1",
  );
  // Activation par axe (panneau unifié « Axes actifs »). Une clé localStorage / axe.
  const [axisEnabled, setAxisEnabled] = useState<Record<number, boolean>>(() => {
    const get = (k: string, d: boolean) => {
      const v = localStorage.getItem(k); return v === null ? d : v === "1";
    };
    return {
      1: get("ia.axis1Enabled", true), 2: get("ia.axis2Enabled", true),
      4: get("ia.axis4Enabled", true), 5: get("ia.axis5Enabled", false),
      6: get("ia.axis6Enabled", false), 7: get("ia.axis7Enabled", true),
    };
  });
  const axisEnabledRef = useRef(axisEnabled);

  // Pince (axe 7) : écart pouce-index lissé + calibration ouvert/fermé mémorisée.
  const pinchRef = useRef<number>(0);
  const [openTicks7, setOpenTicks7] = useState<number | null>(() => {
    const v = localStorage.getItem("ia.openTicks7"); return v === null ? null : Number(v);
  });
  const [closedTicks7, setClosedTicks7] = useState<number | null>(() => {
    const v = localStorage.getItem("ia.closedTicks7"); return v === null ? null : Number(v);
  });
  const pinchCfgRef = useRef<{ open: number | null; closed: number | null }>(
    { open: null, closed: null },
  );
  const [pinchDebug, setPinchDebug] = useState<number>(0);

  // Poignet (axe 5 flexion / axe 6 rotation) — miroir 1:1, 2 repères/axe.
  const rollRef = useRef<number>(0);
  const pitchRef = useRef<number>(0);
  const last5Ref = useRef<number | null>(null); // dernière cible axe 5 (slew-limiter)
  const loadCal = (k: string): Cal => {
    try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : { a: null, b: null }; }
    catch { return { a: null, b: null }; }
  };
  const [rotCal, setRotCal] = useState<Cal>(() => loadCal("ia.rotCal"));
  const [flexCal, setFlexCal] = useState<Cal>(() => loadCal("ia.flexCal"));
  const wristCfgRef = useRef<{ rot: Cal; flex: Cal }>(
    { rot: { a: null, b: null }, flex: { a: null, b: null } },
  );
  const [wristDebug, setWristDebug] = useState<{ roll: number; pitch: number }>(
    { roll: 0, pitch: 0 },
  );

  // Simulateur STL : positions affichées dans la scène 3D + mode "sim only".
  const [simTicks, setSimTicks] = useState<Record<string, number>>({});
  const [simOnly, setSimOnly] = useState<boolean>(
    () => localStorage.getItem("ia.simOnly") === "1",
  );
  const simOnlyRef = useRef<boolean>(false);
  useEffect(() => {
    localStorage.setItem("ia.simOnly", simOnly ? "1" : "0");
    simOnlyRef.current = simOnly;
  }, [simOnly]);
  // Calibration STL (axes + pièces + boîtes d'encombrement) chargée une fois.
  useEffect(() => {
    fetch("/calibration.json").then((r) => r.json())
      .then((d: CalibData) => { setCalib(d); calibRef.current = d; })
      .catch(() => { /* pas de calibration servie */ });
  }, []);
  // Exclusions structurelles, recalculées avec la MÊME marge que le runtime
  // (sinon une marge large crée un blocage permanent dès l'ouverture) : paires
  // en contact dans l'enveloppe de mouvement normale (balayage mono-axe ±70°),
  // y compris entre maillons voisins — les vrais replis (poignet ~±90°) restent
  // détectés. Sol : boîtes qui dégagent le plancher à la pose de repos.
  useEffect(() => {
    const d = calib;
    if (!d?.boxes?.length) return;
    const refTicks: Record<string, number> = {
      "1": REF_UP[1], "2": REF_UP[2], "4": REF_UP[4], "5": REF_UP[5], "6": REF_UP[6],
    };
    selfExcludeRef.current = sweepContacts(d, selfMargin);
    groundSegsRef.current =
      restGroundBoxes(worldBoxes(refTicks, 0, d), d.refSurfaceZ ?? 0, COLLISION_MARGIN);
  }, [calib, selfMargin]);
  useEffect(() => {
    localStorage.setItem("ia.groundGuard", groundGuard ? "1" : "0");
    groundRef.current = groundGuard;
  }, [groundGuard]);

  // Refs à jour pour les boucles (qui ne re-souscrivent pas à chaque render).
  useEffect(() => { ridRef.current = activeRid; }, [activeRid]);
  useEffect(() => { posRef.current = positions; }, [positions]);
  useEffect(() => { armedRef.current = armed; }, [armed]);
  // Soft-limits de l'axe (du robot actif) lues par la boucle pour clamper la sim.
  useEffect(() => {
    softLimitsRef.current = robots.find((r) => r.id === activeRid)?.soft_limits ?? {};
  }, [robots, activeRid]);
  useEffect(() => { robotsRef.current = robots; }, [robots]);
  // Persiste les inversions + met à jour le sens lu par la boucle de contrôle.
  useEffect(() => {
    localStorage.setItem("ia.invertX", invertX ? "1" : "0");
    localStorage.setItem("ia.invertY", invertY ? "1" : "0");
    localStorage.setItem("ia.invertShoulder", invertShoulder ? "1" : "0");
    signRef.current = {
      1: invertX ? -1 : 1, 2: invertShoulder ? -1 : 1, 4: invertY ? -1 : 1,
    };
  }, [invertX, invertY, invertShoulder]);
  // Persiste les vitesses + les rend lisibles par la boucle de contrôle.
  useEffect(() => {
    localStorage.setItem("ia.speedX", String(speedX));
    localStorage.setItem("ia.speedShoulder", String(speedShoulder));
    localStorage.setItem("ia.speedElbow", String(speedElbow));
    vmaxRef.current = { 1: speedX, 2: speedShoulder, 4: speedElbow };
  }, [speedX, speedShoulder, speedElbow]);
  // Persiste l'activation par axe + la rend lisible par la boucle de contrôle.
  useEffect(() => {
    for (const ax of [1, 2, 4, 5, 6, 7]) {
      localStorage.setItem(`ia.axis${ax}Enabled`, axisEnabled[ax] ? "1" : "0");
    }
    axisEnabledRef.current = axisEnabled;
  }, [axisEnabled]);
  // Persiste la calibration pince + la rend lisible par la boucle de contrôle.
  useEffect(() => {
    if (openTicks7 !== null) localStorage.setItem("ia.openTicks7", String(openTicks7));
    if (closedTicks7 !== null) localStorage.setItem("ia.closedTicks7", String(closedTicks7));
    pinchCfgRef.current = { open: openTicks7, closed: closedTicks7 };
  }, [openTicks7, closedTicks7]);
  // Persiste la calibration poignet + la rend lisible par la boucle de contrôle.
  useEffect(() => {
    localStorage.setItem("ia.rotCal", JSON.stringify(rotCal));
    localStorage.setItem("ia.flexCal", JSON.stringify(flexCal));
    wristCfgRef.current = { rot: rotCal, flex: flexCal };
  }, [rotCal, flexCal]);

  // Démarrage webcam + tracker (une fois).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: 640, height: 480 },
        });
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        const tracker = await createHandTracker();
        if (cancelled) { tracker.close(); return; }
        trackerRef.current = tracker;
        setReady(true);
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      trackerRef.current?.close();
    };
  }, []);

  // Boucle détection (rAF) : tourne toujours, met à jour offsetRef + overlay.
  useEffect(() => {
    if (!ready) return;
    let raf = 0;
    const tick = () => {
      const video = videoRef.current;
      const tracker = trackerRef.current;
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d") ?? null;
      if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
      // Repère de commande (toujours visible) : croix fixe + zone morte + sens
      // courant (selon inversions), et point live suivant la main.
      if (ctx && canvas) {
        const W = canvas.width, H = canvas.height;
        const mx = W / 2, my = H / 2;
        const dzx = (DEADZONE / 2) * W, dzy = (DEADZONE / 2) * H;
        ctx.strokeStyle = "rgba(255,255,255,0.22)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(mx, 0); ctx.lineTo(mx, H);
        ctx.moveTo(0, my); ctx.lineTo(W, my);
        ctx.stroke();
        ctx.strokeRect(mx - dzx, my - dzy, dzx * 2, dzy * 2); // zone morte
        // Sens courant (signe -1 = inversé) lu dans signRef.
        const sgnX = signRef.current[1] ?? 1; // gauche/droite → axe 1
        const sgnY = signRef.current[4] ?? 1; // haut/bas → épaule (2) + coude (4)
        ctx.fillStyle = "rgba(232,185,35,0.95)";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(sgnX < 0 ? "→ 1" : "← 1", 24, my - 6);
        ctx.fillText(sgnX < 0 ? "← 1" : "→ 1", W - 24, my - 6);
        ctx.fillText(sgnY < 0 ? "▼ 2+4" : "▲ 2+4", mx, 14);
        ctx.fillText(sgnY < 0 ? "▲ 2+4" : "▼ 2+4", mx, H - 6);
        // Point live : main détectée → vecteur de commande depuis le centre.
        const present = performance.now() - lastDetectRef.current < PRESENT_TIMEOUT_MS;
        if (present) {
          const ox = Math.max(-1, Math.min(1, offsetRef.current.x));
          const oy = Math.max(-1, Math.min(1, offsetRef.current.y));
          const px = mx + ox * (W / 2), py = my + oy * (H / 2);
          const inDz = Math.abs(ox) < DEADZONE && Math.abs(oy) < DEADZONE;
          ctx.strokeStyle = inDz ? "rgba(255,255,255,0.4)" : "#ff4dd2";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(mx, my); ctx.lineTo(px, py);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(px, py, 8, 0, Math.PI * 2);
          ctx.fillStyle = inDz ? "rgba(255,255,255,0.5)" : "#ff4dd2";
          ctx.fill();
        }
      }
      if (video && tracker && video.readyState >= 2) {
        const res = tracker.detect(video, performance.now());
        if (res) {
          const off = computeOffset(res.cx, res.cy);
          offsetRef.current = {
            x: ema(offsetRef.current.x, off.x),
            y: ema(offsetRef.current.y, off.y),
          };
          pinchRef.current = ema(pinchRef.current, res.pinch);
          rollRef.current = ema(rollRef.current, res.roll);
          pitchRef.current = ema(pitchRef.current, res.pitch);
          lastDetectRef.current = performance.now();
          if (ctx && canvas) {
            const W = canvas.width, H = canvas.height;
            const pts = res.points;
            // Squelette de la main.
            ctx.strokeStyle = "rgba(232,185,35,0.6)";
            ctx.lineWidth = 2;
            for (const [a, b] of HAND_CONNECTIONS) {
              if (!pts[a] || !pts[b]) continue;
              ctx.beginPath();
              ctx.moveTo(pts[a].x * W, pts[a].y * H);
              ctx.lineTo(pts[b].x * W, pts[b].y * H);
              ctx.stroke();
            }
            // Les 21 repères ; bouts pouce(4)/index(8) en magenta (pince).
            pts.forEach((pt, i) => {
              const tip = i === 4 || i === 8;
              ctx.fillStyle = tip ? "#ff4dd2" : "#e8b923";
              ctx.beginPath();
              ctx.arc(pt.x * W, pt.y * H, tip ? 7 : 4, 0, Math.PI * 2);
              ctx.fill();
            });
          }
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [ready]);

  // Boucle de contrôle (15 Hz) : intègre + écrit en Direct quand armé.
  useEffect(() => {
    const dt = 1 / LOOP_HZ;
    const id = setInterval(() => {
      const now = performance.now();
      const present = now - lastDetectRef.current < PRESENT_TIMEOUT_MS;
      const offset = offsetRef.current;
      setDebug({ x: offset.x, y: offset.y, present });
      setPinchDebug(pinchRef.current);
      setWristDebug({ roll: rollRef.current, pitch: pitchRef.current });
      // En "Simulation uniquement", aucun robot connecté n'est requis : on pilote
      // le STL avec un robot par défaut (utile pour tester hors ligne, Pi éteint).
      const rid = ridRef.current || ((simOnlyRef.current || sliderModeRef.current) ? "robot_1" : "");
      const hw = (rid && posRef.current[rid]) ? posRef.current[rid] : {};
      // Base de la sim 3D : pose live (ou 2048 par défaut) sur les 7 axes.
      const baseSim: Record<string, number> = {};
      for (const ax of [1, 2, 3, 4, 5, 6, 7]) baseSim[String(ax)] = hw[String(ax)] ?? 2048;
      // Mode sliders (sans webcam) : le STL suit les sliders ; le garde-fou ne fait
      // qu'INDIQUER la collision (badge rouge), sans geler → on entre/ressort librement.
      if (sliderModeRef.current) {
        const candidateTicks = { ...baseSim, ...sliderTicksRef.current };
        const guard = evalGuard(candidateTicks, rid, calibRef.current, selfExcludeRef.current,
          groundSegsRef.current, groundRef.current, robotsRef.current, posRef.current, selfMarginRef.current);
        setCollision(guard.blocked); setCollisionReason(guard.reason);
        setHitBoxes(guard.hitIdx);
        setSimTicks(candidateTicks); // suit toujours, pas de gel
        return;                      // sim pure : pas d'écriture robot
      }
      if (!armedRef.current || !rid) { setSimTicks(baseSim); return; }
      const current: Record<number, number> = {};
      for (const k of Object.keys(hw)) current[Number(k)] = hw[k];
      if (current[1] === undefined) current[1] = 2048; // défauts sim (sans retour robot)
      if (current[2] === undefined) current[2] = 2048;
      if (current[4] === undefined) current[4] = 2048;
      // Snapshot de l'état d'asservissement AVANT d'intégrer ce tick : si la pose
      // candidate collisionne, on y revient (le bras colle à la surface au lieu de
      // sauter en haut).
      const servoSnapshot: ServoState = {
        target: { ...servoRef.current.target }, ramp: { ...servoRef.current.ramp },
      };
      const targets = stepServo(servoRef.current, {
        offset, present, armed: true, dt, current,
        sign: signRef.current, vmax: vmaxRef.current, enabled: axisEnabledRef.current,
      });
      // PositionsTick est à clés string → reconstruire un body à clés string
      // (cmdWriteDirect attend Record<string, number>).
      const body: Record<string, number> = {};
      for (const k of Object.keys(targets)) body[k] = targets[Number(k)];
      // Pince (axe 7) — proportionnel, si axe actif + calibré + main détectée.
      const pc = pinchCfgRef.current;
      if (present && axisEnabledRef.current[7] && pc.open !== null && pc.closed !== null) {
        body["7"] = pinchToAxis7(pinchRef.current, pc.open, pc.closed);
      }
      // Poignet (axes 5/6) — miroir 1:1, activation indépendante par axe.
      const wc = wristCfgRef.current;
      if (present && axisEnabledRef.current[6] && wc.rot.a && wc.rot.b) {
        body["6"] = mapLinear(rollRef.current, wc.rot.a.s, wc.rot.a.t, wc.rot.b.s, wc.rot.b.t);
      }
      if (present && axisEnabledRef.current[5] && wc.flex.a && wc.flex.b) {
        const target5 = mapLinear(pitchRef.current, wc.flex.a.s, wc.flex.a.t, wc.flex.b.s, wc.flex.b.t);
        const prev5 = last5Ref.current ?? (current[5] ?? target5);
        const step = Math.max(-MAX_STEP_5, Math.min(MAX_STEP_5, target5 - prev5));
        const limited5 = Math.round(prev5 + step);
        last5Ref.current = limited5;
        body["5"] = limited5;
      }
      // Limites de déplacement (soft-limits robot) appliquées à la sim ET au robot.
      const lims = softLimitsRef.current;
      for (const k of Object.keys(body)) {
        const lim = lims[k];
        if (lim) body[k] = Math.max(lim[0], Math.min(lim[1], body[k]));
      }
      // Garde-fou anti-collision : capsules placées par la calibration STL.
      const candidateTicks = { ...baseSim, ...body };
      const guard = evalGuard(candidateTicks, rid, calibRef.current, selfExcludeRef.current,
        groundSegsRef.current, groundRef.current, robotsRef.current, posRef.current, selfMarginRef.current);
      if (guard.blocked) {
        setCollision(true); setCollisionReason(guard.reason);
        setHitBoxes(guard.hitIdx);
        servoRef.current = servoSnapshot;      // revert : reste collé à la surface, pas de saut
        return;                                // gel : ni sim ni robot ne vont vers la pose fautive
      }
      setCollision(false);
      setHitBoxes([]);
      setSimTicks(candidateTicks); // la sim 3D reflète l'intention IA (sûre)
      if (!simOnlyRef.current && Object.keys(body).length > 0) {
        cmdWriteDirect(rid, body).catch((e) => setError(String(e)));
      }
    }, 1000 / LOOP_HZ);
    return () => clearInterval(id);
  }, []);

  const arm = useCallback(async () => {
    const rid = ridRef.current;
    const sim = simOnlyRef.current;
    if (!rid && !sim) { setError("Aucun robot actif"); return; }
    try {
      if (!sim && rid) await cmdDirectMode(rid, true); // sim only → ne prend pas le vrai robot
      servoRef.current = createServoState(); // seed propre au prochain tick
      last5Ref.current = null;               // re-seed du limiteur axe 5
      armedRef.current = true;               // évite le délai d'un render sur le 1er tick
      setArmed(true);
      setError(null);
    } catch (e) { setError(String(e)); }
  }, []);

  const disarm = useCallback(async () => {
    setArmed(false);
    last5Ref.current = null;
    const rid = ridRef.current;
    try { if (rid && !simOnlyRef.current) await cmdDirectMode(rid, false); } catch { /* ignore */ }
  }, []);

  // Calibration pince : capture la position live de l'axe 7 comme repère.
  const captureAxis7 = useCallback((which: "open" | "closed") => {
    const rid = ridRef.current;
    const hw = posRef.current[rid] ?? {};
    const v = hw["7"];
    if (v === undefined) { setError("Axe 7 introuvable (robot connecté ?)"); return; }
    if (which === "open") setOpenTicks7(Math.round(v));
    else setClosedTicks7(Math.round(v));
    setError(null);
  }, []);

  // Calibration poignet : capture (signal courant, position live de l'axe) = repère.
  const captureWrist = useCallback((axis: 5 | 6, slot: "a" | "b") => {
    const rid = ridRef.current;
    const hw = posRef.current[rid] ?? {};
    const t = hw[String(axis)];
    if (t === undefined) { setError(`Axe ${axis} introuvable (robot connecté ?)`); return; }
    const pair = { s: axis === 6 ? rollRef.current : pitchRef.current, t: Math.round(t) };
    if (axis === 6) setRotCal((c) => ({ ...c, [slot]: pair }));
    else setFlexCal((c) => ({ ...c, [slot]: pair }));
    setError(null);
  }, []);

  // Réinitialise les 2 repères d'un axe poignet (pour recalibrer de zéro).
  const clearWrist = useCallback((axis: 5 | 6) => {
    if (axis === 6) setRotCal({ a: null, b: null });
    else setFlexCal({ a: null, b: null });
  }, []);

  // Auto-désarmement si le Pi (ou un autre client) reprend la main (arbitrage).
  useLiveBus((msg: WsMsg) => {
    if (msg.topic === "robot.control_changed") {
      const owner = (msg.data as { owner?: string | null }).owner;
      if (owner !== "web" && armedRef.current) void disarm();
    }
  });

  // Sécurité : désarmer si on quitte la page alors qu'elle est armée.
  useEffect(() => {
    return () => { if (armedRef.current) { void disarm(); } };
  }, [disarm]);

  return (
    <div className="p-4 space-y-4">
      <h1 className="font-ui text-lg text-text">IA — Suivi de la main (Jalon 1)</h1>
      {error && <div className="text-red-400 font-mono text-sm">⛔ {error}</div>}
      <div className="flex flex-wrap gap-4">
        <div className="relative w-[640px] max-w-full">
          <video ref={videoRef} width={640} height={480} muted playsInline
                 className="rounded border border-border w-full" />
          <canvas ref={canvasRef} width={640} height={480}
                  className="absolute inset-0 w-full h-full pointer-events-none" />
        </div>
        <div className={`relative w-[420px] h-[480px] max-w-full bg-bg_deep rounded-sm overflow-hidden border ${collision ? "border-red-500" : "border-border"}`}>
          {collision && (
            <div className="absolute top-2 left-2 z-10 px-2 py-1 rounded bg-red-700 text-white text-xs font-ui">
              ⚠ Collision{collisionReason ? ` (${collisionReason})` : ""} — mouvement bloqué
            </div>
          )}
          <Canvas camera={{ position: [400, 500, 600], fov: 45, near: 1, far: 5000 }}>
            <ambientLight intensity={0.4} />
            <directionalLight position={[200, 400, 300]} intensity={0.8} />
            <Grid args={[1000, 1000]} cellColor="#2a2e40" sectionColor="#3a3e52"
                  position={[0, 0, 0]} />
            <group rotation={[-Math.PI / 2, 0, 0]}>
              <RobotMeshSTL ticks={simTicks} color={colorForRobot(activeRid) || "#e8b923"} />
              {(showCapsules || collision) && calib &&
                <CollisionBoxes ticks={simTicks} calib={calib} hitIdx={hitBoxes} />}
              {groundGuard && calib && (
                <mesh position={[0, 0, (calib.refSurfaceZ ?? 0) + 150]}>
                  <planeGeometry args={[900, 900]} />
                  <meshStandardMaterial color="#c0392b" transparent opacity={0.18} side={2} />
                </mesh>
              )}
            </group>
            <OrbitControls />
          </Canvas>
        </div>
      </div>
      <div className="flex items-center gap-4">
        {!armed ? (
          <button onClick={arm} disabled={!ready}
            className="px-4 py-2 rounded bg-green-700 text-white disabled:opacity-40">
            ▶ Armer le suivi
          </button>
        ) : (
          <button onClick={disarm}
            className="px-4 py-2 rounded bg-red-700 text-white">
            ■ Désarmer
          </button>
        )}
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-text">
          <input type="checkbox" checked={simOnly}
                 onChange={(e) => setSimOnly(e.target.checked)} />
          Simulation uniquement (ne bouge pas le robot)
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-text">
          <input type="checkbox" checked={groundGuard}
                 onChange={(e) => setGroundGuard(e.target.checked)} />
          Sol (anti-collision)
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-text">
          <input type="checkbox" checked={sliderMode}
                 onChange={(e) => setSliderMode(e.target.checked)} />
          Piloter aux sliders (sans webcam)
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none text-sm text-text">
          <input type="checkbox" checked={showCapsules}
                 onChange={(e) => setShowCapsules(e.target.checked)} />
          Afficher les boîtes (debug)
        </label>
        <span className="font-mono text-sm text-text_med">
          robot {activeRid || "—"} · main {debug.present ? "détectée" : "perdue"} ·
          offset x={debug.x.toFixed(2)} y={debug.y.toFixed(2)}
        </span>
      </div>
      {sliderMode && (
        <div className="flex flex-col gap-2 p-3 rounded bg-bg_deep border border-border max-w-[640px]">
          <div className="text-xs text-text_med">
            Pilotage manuel de la sim (ticks 0–4095) — le badge rouge signale la collision, sans bloquer.
          </div>
          <label className="flex items-center gap-3 text-xs text-amber-300 border-b border-border pb-2 mb-1">
            <span className="w-40">Marge auto-collision (mm)</span>
            <input type="range" min={-100} max={30} step={1}
                   value={selfMargin}
                   onChange={(e) => setSelfMargin(Number(e.target.value))}
                   className="flex-1" />
            <span className="w-12 text-right font-mono">{selfMargin}</span>
          </label>
          {([["1", "Base (axe 1)"], ["2", "Épaule (axe 2)"], ["4", "Coude (axe 4)"],
             ["5", "Poignet flexion (axe 5)"], ["6", "Poignet rotation (axe 6)"], ["7", "Pince (axe 7)"]] as [string, string][])
            .map(([ax, label]) => (
            <label key={ax} className="flex items-center gap-3 text-xs text-text">
              <span className="w-40">{label}</span>
              <input type="range" min={0} max={4095} step={1}
                     value={sliderTicks[ax] ?? 2048}
                     onChange={(e) => setSliderTicks((s) => ({ ...s, [ax]: Number(e.target.value) }))}
                     className="flex-1" />
              <span className="w-12 text-right font-mono">{sliderTicks[ax] ?? 2048}</span>
            </label>
          ))}
          <button onClick={() => setSliderTicks({ "1": 2048, "2": 2048, "4": 2048, "5": 2048, "6": 2048, "7": 2048 })}
                  className="self-start mt-1 px-2 py-1 rounded bg-bg border border-border text-xs">
            Réinitialiser (2048)
          </button>
        </div>
      )}
      <div className="flex flex-col gap-2 p-3 rounded bg-bg_deep border border-border max-w-[640px]">
        <div className="text-xs text-text_med">
          Axes actifs — coche/décoche pour piloter ou figer chaque axe (mémorisé).
        </div>
        <div className="flex flex-col gap-1.5 text-sm text-text">
          {([[1, "Gauche/droite (axe 1)"], [2, "Épaule (axe 2)"], [4, "Coude (axe 4)"],
             [5, "Poignet flexion (axe 5)"], [6, "Poignet rotation (axe 6)"], [7, "Pince (axe 7)"]] as [number, string][])
            .map(([ax, label]) => (
            <label key={ax} className="flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={axisEnabled[ax] ?? false}
                     onChange={(e) => setAxisEnabled((s) => ({ ...s, [ax]: e.target.checked }))} />
              {label}
            </label>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2 p-3 rounded bg-bg_deep border border-border max-w-[640px]">
        <div className="text-xs text-text_med">
          Vitesses de suivi (ticks/s) — réglables en direct, mémorisées.
        </div>
        <label className="flex items-center gap-3 text-xs text-text">
          <span className="w-56">Vitesse gauche/droite (axe 1)</span>
          <input type="range" min={100} max={750} step={10}
                 value={speedX} onChange={(e) => setSpeedX(Number(e.target.value))}
                 className="flex-1" />
          <span className="w-12 text-right font-mono">{speedX}</span>
        </label>
        <label className="flex items-center gap-3 text-xs text-text">
          <span className="w-56">Vitesse haut/bas — épaule (axe 2)</span>
          <input type="range" min={50} max={600} step={10}
                 value={speedShoulder} onChange={(e) => setSpeedShoulder(Number(e.target.value))}
                 className="flex-1" />
          <span className="w-12 text-right font-mono">{speedShoulder}</span>
        </label>
        <label className="flex items-center gap-3 text-xs text-text">
          <span className="w-56">Vitesse haut/bas — coude (axe 4)</span>
          <input type="range" min={100} max={600} step={10}
                 value={speedElbow} onChange={(e) => setSpeedElbow(Number(e.target.value))}
                 className="flex-1" />
          <span className="w-12 text-right font-mono">{speedElbow}</span>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-6 text-sm text-text">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={invertX}
                 onChange={(e) => setInvertX(e.target.checked)} />
          Inverser gauche/droite (axe 1)
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={invertY}
                 onChange={(e) => setInvertY(e.target.checked)} />
          Inverser haut/bas (axe 4)
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input type="checkbox" checked={invertShoulder}
                 onChange={(e) => setInvertShoulder(e.target.checked)} />
          Inverser haut/bas — épaule (axe 2)
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm text-text">
        <button onClick={() => captureAxis7("open")}
          className="px-3 py-1 rounded bg-surface border border-border">
          Définir « ouvert »{openTicks7 !== null ? ` (${openTicks7})` : ""}
        </button>
        <button onClick={() => captureAxis7("closed")}
          className="px-3 py-1 rounded bg-surface border border-border">
          Définir « fermé »{closedTicks7 !== null ? ` (${closedTicks7})` : ""}
        </button>
        <span className="font-mono text-text_med">pince={pinchDebug.toFixed(2)}</span>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-text">
        <span className="text-text_med">Rotation (6) :</span>
        <button onClick={() => captureWrist(6, "a")}
          className="px-2 py-1 rounded bg-surface border border-border">
          Repère 1{rotCal.a ? " ✓" : ""}
        </button>
        <button onClick={() => captureWrist(6, "b")}
          className="px-2 py-1 rounded bg-surface border border-border">
          Repère 2{rotCal.b ? " ✓" : ""}
        </button>
        <button onClick={() => clearWrist(6)}
          className="px-2 py-1 rounded bg-surface border border-border text-text_med">
          Effacer
        </button>
        <span className="text-text_med">Flexion (5) :</span>
        <button onClick={() => captureWrist(5, "a")}
          className="px-2 py-1 rounded bg-surface border border-border">
          Repère 1{flexCal.a ? " ✓" : ""}
        </button>
        <button onClick={() => captureWrist(5, "b")}
          className="px-2 py-1 rounded bg-surface border border-border">
          Repère 2{flexCal.b ? " ✓" : ""}
        </button>
        <button onClick={() => clearWrist(5)}
          className="px-2 py-1 rounded bg-surface border border-border text-text_med">
          Effacer
        </button>
        <span className="font-mono text-text_med">
          roll={wristDebug.roll.toFixed(2)} pitch={wristDebug.pitch.toFixed(2)}
        </span>
      </div>
      <p className="text-text_med text-sm max-w-xl">
        Ouvre cette page <b>depuis ton Mac</b> (pas l'écran du Pi). Arme, puis bouge
        ta main : gauche/droite → axe 1, haut/bas → épaule (axe 2) + coude (axe 4). Si un sens est à
        l'envers, coche la case correspondante (mémorisé, sans redéployer). Pour la
        pince : place l'axe 7 ouvert puis clique « Définir ouvert », idem fermé ;
        ensuite l'écart pouce-index pilote l'ouverture en proportionnel. Poignet
        1:1 : pour chaque axe, place la main + l'axe à une 1re pose → « Repère 1 »,
        à une 2e pose → « Repère 2 » ; ta main pilote alors l'axe en miroir.
        (Rotation = fiable ; flexion = via la profondeur, plus approximative.)
      </p>
    </div>
  );
}
