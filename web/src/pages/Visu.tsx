// Page Visualisation 3D — fidele a xrv22/ui/tab_visu.py.
// Layout :
//   Header : Visualisation 3D + selecteur robot + Direct + boutons Zone/Plan/DXF/G-code/Preview
//   3 colonnes :
//     gauche : sliders axes (Base / Epaule / Coude / Poignet / Rot tete / Pince)
//     centre : scene 3D Three.js (mesh STL calibre + grille)
//     droite : jauges circulaires par axe + coordonnees TCP X/Y/Z

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";
import { fk } from "../visu/fk";
import { useStore } from "../store";
import { colorForRobot } from "../theme";
import { Modal, ModalBtn } from "../components/Modal";
import { cmdImportDxf, cmdImportGcode, cmdSetSafety } from "../commands";
import { useActiveRobot, useLiveAxesShared } from "../liveAxes";
import { authFetch } from "../auth";
import { Surfaces, centroid } from "../visu/Surfaces";
import { robotOffsetX } from "../visu/placement";
import { ZonesPanel } from "../visu/ZonesPanel";
import { RobotMeshSTL } from "../visu/RobotMeshSTL";
import { gripMm } from "../grip";

type PreviewEvent = {
  start_ms: number; duration_ms: number;
  positions: Record<string, number>;
};

// Slider d'axe gauche (compact)
function AxisSliderLeft({
  label, value, onChange, color, min = 0, max = 4095,
  locked, onPointerDown, onPointerUp,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  color: string;
  min?: number;
  max?: number;
  locked?: { reason: string };
  onPointerDown: () => void;
  onPointerUp: () => void;
}) {
  const isPince = label === "Pince";
  // Pince : ecart reel en mm (calibration partagee, ancres mesurees en live).
  const fmt = isPince
    ? `${gripMm(value).toFixed(1)} mm`
    : `${(((value - 2048) / 4095) * 360).toFixed(1)}°`;
  return (
    <div className={`mb-3 ${locked ? "opacity-40" : ""}`}>
      <div className="flex items-baseline mb-1">
        <span className="font-ui text-control text-amb flex-1">{label}</span>
        <span className="font-ui text-control text-text">{fmt}</span>
      </div>
      <input
        type="range" min={min} max={max} value={value}
        disabled={!!locked}
        title={locked?.reason}
        onPointerDown={locked ? undefined : onPointerDown}
        onPointerUp={locked ? undefined : onPointerUp}
        onPointerCancel={locked ? undefined : onPointerUp}
        onChange={(e) => { if (!locked) onChange(Number(e.target.value)); }}
        className={`w-full accent-amb ${locked ? "cursor-not-allowed" : ""}`}
        style={{ accentColor: color }}
      />
    </div>
  );
}

// Jauge circulaire (axe value 0-4095)
function CircularGauge({ axis, label, value, color }: {
  axis: number; label: string; value: number; color: string;
}) {
  // Anglo de progression : ratio 0-360deg
  const ratio = Math.max(0, Math.min(1, value / 4095));
  const deg = ratio * 360;
  const fmt = axis === 7
    ? `${gripMm(value).toFixed(1)} mm`
    : `${(((value - 2048) / 4095) * 360).toFixed(0)}°`;
  return (
    <div className="flex flex-col items-center mb-2">
      <div className="relative w-14 h-14 rounded-full"
           style={{
             background: `conic-gradient(${color} ${deg}deg, #2a2e40 0)`,
           }}>
        <div className="absolute inset-1.5 bg-surface rounded-full flex items-center justify-center">
          <span className="font-mono text-mono_sm text-text">{value}</span>
        </div>
      </div>
      <span className="font-ui text-caption text-text_med mt-1">{label}</span>
      <span className="font-mono text-mono_sm text-amb">{fmt}</span>
    </div>
  );
}

// 7 axes — l'index i de la liste correspond au moteur i+1.
// Mapping reel XRV22 : moteurs 2 et 3 = epaule (couples), 4 = coude,
// 5 = poignet, 6 = rotation poignet, 7 = pince.
const AXES_LEFT = ["Base", "Épaule", "Épaule (couplé)", "Coude", "Poignet", "Rot. poignet", "Pince"];

// L'axe 3 est l'esclave couple de l'axe 2 (epaule) : un seul slider et
// une seule jauge "Epaule" suffisent — on masque l'axe 3.
const HIDDEN_AXES = new Set<number>([3]);
const VISIBLE_AXES = [1, 2, 3, 4, 5, 6, 7].filter((a) => !HIDDEN_AXES.has(a));

// Dialog upload de fichier (DXF / G-code) avec parametres + import reel
function FileImportDialog({
  title, accept, robots, scenarios, onClose, onSuccess, onError,
  paramsHint = "",
  importer,
}: {
  title: string;
  accept: string;
  robots: ReturnType<typeof useStore>["robots"];
  scenarios: ReturnType<typeof useStore>["scenarios"];
  onClose: () => void;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
  paramsHint?: string;
  importer: (file: File, scenarioId: string, robotId: string,
             durS: number, z: number, ang: number) => Promise<{ waypoints: number; duration_total_s: number }>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [robotId, setRobotId] = useState(robots[0]?.id ?? "");
  const [scenarioId, setScenarioId] = useState(scenarios[0]?.id ?? "");
  const [durationS, setDurationS] = useState(2.0);
  const [zHeight, setZHeight] = useState(100);
  const [toolAngle, setToolAngle] = useState(3.14159);  // pi = down
  const [busy, setBusy] = useState(false);

  const onImport = async () => {
    if (!file || !robotId || !scenarioId) return;
    setBusy(true);
    try {
      const res = await importer(file, scenarioId, robotId, durationS, zHeight, toolAngle);
      onSuccess(`${res.waypoints} waypoints ajoutés (${res.duration_total_s.toFixed(1)}s)`);
      onClose();
    } catch (e) {
      onError(`import: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title={title} onClose={onClose} width={520}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!file || !robotId || !scenarioId || busy} onClick={onImport}>
               {busy ? "Import…" : "✓ Importer"}
             </ModalBtn>
           </>}>
      <div className="space-y-3">
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Fichier :</label>
          <input type="file" accept={accept}
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                 className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_sm text-text" />
          {file && (
            <p className="font-mono text-mono_sm text-text_dim mt-1">
              {file.name} · {(file.size / 1024).toFixed(1)} Ko
            </p>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Scénario cible :</label>
            <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}
                    className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-ui text-control text-text focus:outline-none focus:border-amb">
              {scenarios.length === 0 && <option value="">(aucun scénario)</option>}
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name || s.id}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Robot :</label>
            <select value={robotId} onChange={(e) => setRobotId(e.target.value)}
                    className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-ui text-control text-text focus:outline-none focus:border-amb">
              {robots.map((r) => (
                <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Durée/point (s) :</label>
            <input type="number" step="0.1" min="0.1" value={durationS}
                   onChange={(e) => setDurationS(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Hauteur Z (mm) :</label>
            <input type="number" step="1" value={zHeight}
                   onChange={(e) => setZHeight(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>
          <div className="col-span-2">
            <label className="font-ui text-control text-text_med block mb-1">Angle outil (rad) :</label>
            <select value={toolAngle} onChange={(e) => setToolAngle(Number(e.target.value))}
                    className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-ui text-control text-text focus:outline-none focus:border-amb">
              <option value={3.14159}>π — Vers le bas (tool-down)</option>
              <option value={1.5708}>π/2 — Horizontale</option>
              <option value={2.3562}>3π/4 — Inclinée 45°</option>
              <option value={0}>0 — Vers le haut</option>
            </select>
          </div>
        </div>
        {paramsHint && (
          <p className="font-mono text-mono_sm text-text_dim border-t border-border pt-3">
            {paramsHint}
          </p>
        )}
      </div>
    </Modal>
  );
}


// Robot_2 reste au centre (x=0). Ecart droit (robot_1) et gauche (robot_3)
// reglables independamment via badges toolbar (double-clic).
const SPACING_RIGHT_KEY = "xrv22.visu.spacingRightMm";
const SPACING_LEFT_KEY  = "xrv22.visu.spacingLeftMm";
const SPACING_DEFAULT = 350;
const SPACING_MIN = 0;
const SPACING_MAX = 2000;


export default function Visu() {
  const { robots, positions, scenarios, setActionError, direct, setDirect, zones,
          safetyEnabled, setSafetyEnabled, recentlyBlockedZoneId } = useStore();
  const { activeRid, setActiveRid } = useActiveRobot();
  const [focusedZoneId, setFocusedZoneId] = useState<string | null>(null);
  const [extendedZoneIds, setExtendedZoneIds] = useState<Set<string>>(new Set());
  const [surfacesDrawerOpen, setSurfacesDrawerOpen] = useState(false);
  const [spacingRightMm, setSpacingRightMm] = useState<number>(() => {
    const stored = Number(localStorage.getItem(SPACING_RIGHT_KEY));
    return Number.isFinite(stored) && stored >= 0 ? stored : SPACING_DEFAULT;
  });
  const [spacingLeftMm, setSpacingLeftMm] = useState<number>(() => {
    const stored = Number(localStorage.getItem(SPACING_LEFT_KEY));
    return Number.isFinite(stored) && stored >= 0 ? stored : SPACING_DEFAULT;
  });
  const [editingSide, setEditingSide] = useState<"right" | "left" | null>(null);
  const [spacingDraft, setSpacingDraft] = useState("");
  const applySpacing = (side: "right" | "left", v: number) => {
    const clamped = Math.max(SPACING_MIN, Math.min(SPACING_MAX, Math.round(v)));
    if (side === "right") {
      setSpacingRightMm(clamped);
      localStorage.setItem(SPACING_RIGHT_KEY, String(clamped));
    } else {
      setSpacingLeftMm(clamped);
      localStorage.setItem(SPACING_LEFT_KEY, String(clamped));
    }
  };
  const controlsRef = useRef<any>(null);

  // Focus caméra sur le centroïde de la zone focusée (lerp progressif)
  useEffect(() => {
    if (!focusedZoneId) return;
    const z = zones.find(z => z.id === focusedZoneId);
    if (!z || z.points.length < 3) return;
    const [cx, cy, cz] = centroid(z.points);
    if (controlsRef.current) {
      // Conversion Z-up (FK backend) -> Y-up (Three.js world) via la rotation [-π/2, 0, 0]
      const target = new THREE.Vector3(cx, cz, -cy);
      const start = controlsRef.current.target.clone();
      let t = 0;
      const animate = () => {
        t = Math.min(1, t + 0.05);
        controlsRef.current.target.lerpVectors(start, target, t);
        controlsRef.current.update();
        if (t < 1) requestAnimationFrame(animate);
      };
      animate();
    }
  }, [focusedZoneId, zones]);

  const [dxfDlg, setDxfDlg] = useState(false);
  const [gcodeDlg, setGcodeDlg] = useState(false);
  const [preview, setPreview] = useState<{
    sid: string; tickMs: number; running: boolean;
  } | null>(null);

  const robot = robots.find((r) => r.id === activeRid);
  const color = robot ? colorForRobot(robot.id) : "#f6a117";

  // Preview timeline : extrait events MOVE du robot actif
  const [previewEvents, setPreviewEvents] = useState<PreviewEvent[]>([]);

  useEffect(() => {
    if (!preview?.sid || !activeRid) { setPreviewEvents([]); return; }
    authFetch("/api/scenarios").then((r) => r.json()).then((arr: Array<{
      id: string; timeline_data: { tracks?: Array<{
        track_type: string; robot_id: string;
        events?: Array<PreviewEvent & { event_type: string }>;
      }> };
    }>) => {
      const sc = arr.find((s) => s.id === preview.sid);
      if (!sc) return;
      const t = (sc.timeline_data?.tracks ?? []).find(
        (x) => x.track_type === "ROBOT" && x.robot_id === activeRid
      );
      const evts = (t?.events ?? [])
        .filter((e) => e.event_type === "MOVE" && e.positions)
        .map((e) => ({ start_ms: e.start_ms, duration_ms: e.duration_ms, positions: e.positions }))
        .sort((a, b) => a.start_ms - b.start_ms);
      setPreviewEvents(evts);
    }).catch(() => {});
  }, [preview?.sid, activeRid]);

  // Tick d'animation preview (50ms = 20Hz)
  useEffect(() => {
    if (!preview?.running) return;
    const totalMs = previewEvents.length === 0 ? 0
      : Math.max(...previewEvents.map((e) => e.start_ms + e.duration_ms));
    const id = setInterval(() => {
      setPreview((cur) => {
        if (!cur) return cur;
        const next = cur.tickMs + 50;
        if (next > totalMs) return { ...cur, tickMs: 0 };
        return { ...cur, tickMs: next };
      });
    }, 50);
    return () => clearInterval(id);
  }, [preview?.running, previewEvents]);

  // Calcul position interpolee selon tickMs courant
  const previewPos = useMemo<Record<string, number> | null>(() => {
    if (!preview || previewEvents.length === 0) return null;
    const t = preview.tickMs;
    // Trouve l'event en cours ou le dernier passe
    let prevEv: PreviewEvent | null = null;
    let curEv: PreviewEvent | null = null;
    for (const ev of previewEvents) {
      if (ev.start_ms <= t && t < ev.start_ms + ev.duration_ms) { curEv = ev; break; }
      if (ev.start_ms + ev.duration_ms <= t) prevEv = ev;
    }
    if (curEv && prevEv) {
      // Interpolation lineaire entre prev.positions (target final) et cur.positions
      const ratio = (t - curEv.start_ms) / curEv.duration_ms;
      const out: Record<string, number> = {};
      for (const k of Object.keys(curEv.positions)) {
        const a = prevEv.positions[k] ?? curEv.positions[k];
        const b = curEv.positions[k];
        out[k] = Math.round(a + (b - a) * ratio);
      }
      return out;
    }
    if (curEv) return curEv.positions;
    if (prevEv) return prevEv.positions;
    return null;
  }, [preview, previewEvents]);

  // Slider d'axe : instance partagee montee au-dessus du routeur.
  const liveAxes = useLiveAxesShared();

  // Soft-limits [lo, hi] de l'axe (profil robot) — defaut 0-4095.
  const limits = (a: number): [number, number] => {
    const sl = robot?.soft_limits?.[String(a)];
    return sl && sl.length === 2 ? [sl[0], sl[1]] : [0, 4095];
  };

  // Valeur affichée : la preview timeline prime sur le miroir live.
  const displayValue = (a: number): number => {
    if (preview && previewPos) return previewPos[String(a)] ?? 2048;
    return liveAxes.value(a);
  };

  // Verrou : pendant une preview les sliders sont figés ; sinon verrou Direct.
  const axisLock = (a: number): { reason: string } | undefined => {
    if (preview) return { reason: "Preview en cours" };
    return liveAxes.locked(a);
  };

  // La scene 3D affiche TOUJOURS le robot reel (ou la preview timeline),
  // jamais les targets de slider.
  // Si le robot n'est pas connecte : fallback sur home_work (position de travail).
  const meshTickFor = (rid: string, a: number): number => {
    if (rid === activeRid && preview && previewPos) {
      return previewPos[String(a)] ?? 2048;
    }
    const r = robots.find((x) => x.id === rid);
    if (r && !r.connected) {
      return r.home_work?.[String(a)] ?? 2048;
    }
    return positions[rid]?.[String(a)] ?? r?.home_work?.[String(a)] ?? 2048;
  };

  // Coordonnees TCP reelles, derivees de la FK (meme source de ticks que le
  // mesh 3D de l'actif) : le chiffre affiche colle donc au robot dessine.
  const tcpTicks: Record<string, number> = {};
  for (let a = 1; a <= 7; a++) tcpTicks[String(a)] = meshTickFor(activeRid, a);
  const tcpPt = fk(tcpTicks)[6];
  const tcp = {
    x: Math.round(tcpPt[0]),
    y: Math.round(tcpPt[1]),
    z: Math.round(tcpPt[2]),
  };

  return (
    <div className="h-full flex flex-col gap-2">
      {/* Header */}
      <div className="flex items-center gap-3 bg-surface_hi border border-border rounded-sm px-3 py-2 flex-wrap">
        <span className="font-display text-section text-mag">📡 Visualisation 3D</span>
        <span className="font-ui text-control text-text_med">Robot :</span>
        <select value={activeRid} onChange={(e) => setActiveRid(e.target.value)}
                className="bg-bg border border-border rounded-sm px-2 py-1 font-ui text-control text-text focus:outline-none focus:border-amb">
          {robots.map((r) => (
            <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" className="accent-amb" checked={direct}
                 onChange={(e) => setDirect(e.target.checked)} />
          <span className="font-ui text-control text-text">🎮 Direct</span>
        </label>
        <div className="flex-1" />
        <button
          className={`px-3 py-1.5 rounded-sm font-ui text-control border transition ${
            surfacesDrawerOpen
              ? "bg-mag/40 text-amb border-mag"
              : "bg-mag_dim2 text-mag2 border-mag/50 hover:bg-mag"
          }`}
          onClick={() => setSurfacesDrawerOpen(o => !o)}
          title="Zones & Plans"
        >
          📐 Surfaces
        </button>
        {(["right", "left"] as const).map((side) => {
          const val = side === "right" ? spacingRightMm : spacingLeftMm;
          const arrow = side === "right" ? "→" : "←";
          const title = side === "right"
            ? "Ecart droit robot_1 (mm) — double-clic pour modifier"
            : "Ecart gauche robot_3 (mm) — double-clic pour modifier";
          if (editingSide === side) {
            return (
              <input
                key={side}
                autoFocus
                type="number"
                value={spacingDraft}
                min={SPACING_MIN}
                max={SPACING_MAX}
                step={10}
                onChange={(e) => setSpacingDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const v = Number(spacingDraft);
                    if (Number.isFinite(v)) applySpacing(side, v);
                    setEditingSide(null);
                  }
                  if (e.key === "Escape") setEditingSide(null);
                }}
                onBlur={() => {
                  const v = Number(spacingDraft);
                  if (Number.isFinite(v)) applySpacing(side, v);
                  setEditingSide(null);
                }}
                className="w-20 px-2 py-1 bg-bg border border-amb/60 rounded-sm font-mono text-mono_sm text-amb focus:outline-none"
              />
            );
          }
          return (
            <button
              key={side}
              onDoubleClick={() => { setSpacingDraft(String(val)); setEditingSide(side); }}
              title={title}
              className="px-2 py-1.5 rounded-sm bg-bg border border-border text-text_med hover:text-amb hover:border-amb/50 font-mono text-mono_sm"
            >
              {arrow} {val} mm
            </button>
          );
        })}
        <button onClick={async () => {
          if (safetyEnabled) {
            if (!window.confirm("Désactiver la safety collision pour ce projet ?\nLe robot pourra entrer dans les zones d'exclusion.")) return;
          }
          try {
            const r = await cmdSetSafety(!safetyEnabled);
            setSafetyEnabled(r.collision_check_enabled);
          } catch (e) {
            setActionError(`Safety: ${e instanceof Error ? e.message : String(e)}`);
          }
        }}
        title={safetyEnabled ? "Safety collision ACTIVE — cliquer pour désactiver" : "Safety collision DESACTIVEE — cliquer pour réactiver"}
        className={safetyEnabled
          ? "px-3 py-1.5 rounded-sm bg-ok/30 text-ok border border-ok/50 hover:bg-ok/50 font-ui text-control"
          : "px-3 py-1.5 rounded-sm bg-err/30 text-err border border-err/50 animate-pulse font-ui text-control"}>
          {safetyEnabled ? "🛡 Safety ON" : "⚠ SAFETY OFF"}
        </button>
        <button className="px-3 py-1.5 rounded-sm bg-amb_dim2 text-amb border border-amb/50 hover:bg-amb/30 font-ui text-control"
                onClick={() => setDxfDlg(true)}>
          DXF
        </button>
        <button className="px-3 py-1.5 rounded-sm bg-amb/30 text-amb border border-amb/50 hover:bg-amb/50 font-ui text-control"
                onClick={() => setDxfDlg(true)}>
          DXF → Timeline
        </button>
        <button className="px-3 py-1.5 rounded-sm bg-mag_dim2 text-mag2 border border-mag/50 hover:bg-mag font-ui text-control"
                onClick={() => setGcodeDlg(true)}>
          G-code
        </button>
        {!preview ? (
          <button className="px-3 py-1.5 rounded-sm bg-ok/30 text-ok border border-ok/50 hover:bg-ok/50 font-ui text-control"
                  onClick={() => {
                    if (scenarios.length === 0) {
                      setActionError("Aucun scenario disponible"); return;
                    }
                    setPreview({ sid: scenarios[0].id, tickMs: 0, running: true });
                  }}>
            ▶ Preview
          </button>
        ) : (
          <>
            <select value={preview.sid}
                    onChange={(e) => setPreview({ ...preview, sid: e.target.value, tickMs: 0 })}
                    className="px-2 py-1.5 rounded-sm bg-bg border border-border font-ui text-control text-text">
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name || s.id}</option>
              ))}
            </select>
            <button className="px-3 py-1.5 rounded-sm bg-amb/30 text-amb border border-amb/50 hover:bg-amb/50 font-ui text-control"
                    onClick={() => setPreview({ ...preview, running: !preview.running })}>
              {preview.running ? "⏸ Pause" : "▶ Reprendre"}
            </button>
            <button className="px-3 py-1.5 rounded-sm bg-err_dim text-err border border-err/50 hover:bg-err_deep font-ui text-control"
                    onClick={() => setPreview(null)}>
              ■ Stop preview
            </button>
            <span className="font-mono text-mono_sm text-amb">
              t = {(preview.tickMs / 1000).toFixed(1)}s · {previewEvents.length} events
            </span>
          </>
        )}
      </div>

      {/* 3 colonnes */}
      <div className="grid grid-cols-12 gap-2 flex-1 min-h-0">
        {/* Sliders axes gauche */}
        <div className="col-span-3 bg-surface border border-border rounded-sm p-3 overflow-auto">
          <div className="font-ui text-section text-amb mb-3">Axes</div>
          {VISIBLE_AXES.map((a) => {
            const [lo, hi] = limits(a);
            return (
              <AxisSliderLeft
                key={a}
                label={AXES_LEFT[a - 1] ?? `Axe ${a}`}
                value={displayValue(a)}
                onChange={(v) => liveAxes.onChange(a, v)}
                color={color}
                min={lo}
                max={hi}
                locked={axisLock(a)}
                onPointerDown={() => liveAxes.onPointerDown(a)}
                onPointerUp={() => liveAxes.onPointerUp(a)}
              />
            );
          })}
        </div>

        {/* Scene 3D centrale */}
        <div className="col-span-7 bg-bg_deep border border-border rounded-sm overflow-hidden relative">
          <Canvas camera={{ position: [400, 500, 600], fov: 45, near: 1, far: 5000 }}>
            <ambientLight intensity={0.4} />
            <directionalLight position={[200, 400, 300]} intensity={0.8} />
            <Grid args={[1000, 1000]} cellColor="#2a2e40" sectionColor="#3a3e52"
                  position={[0, 0, 0]} />
            {robots.map((r) => {
              const offX = robotOffsetX(r.id, spacingRightMm, spacingLeftMm);
              const rColor = colorForRobot(r.id);
              const ticks = {
                "1": meshTickFor(r.id, 1), "2": meshTickFor(r.id, 2),
                "3": meshTickFor(r.id, 3), "4": meshTickFor(r.id, 4),
                "5": meshTickFor(r.id, 5), "6": meshTickFor(r.id, 6),
                "7": meshTickFor(r.id, 7),
              };
              const isActive = r.id === activeRid;
              return (
                <group key={r.id}
                       position={[offX, 0, 0]}
                       onPointerDown={(e) => {
                         e.stopPropagation();
                         if (!isActive) setActiveRid(r.id);
                       }}
                       onPointerOver={(e) => {
                         e.stopPropagation();
                         document.body.style.cursor = "pointer";
                       }}
                       onPointerOut={() => { document.body.style.cursor = ""; }}>
                  <group rotation={[-Math.PI / 2, 0, 0]}>
                    <RobotMeshSTL ticks={ticks} color={rColor} dimmed={!isActive} />
                  </group>
                </group>
              );
            })}
            <group rotation={[-Math.PI / 2, 0, 0]}>
              <Surfaces
                zones={zones}
                focusedId={focusedZoneId}
                extendedIds={extendedZoneIds}
                flashId={recentlyBlockedZoneId}
                spacingRightMm={spacingRightMm}
                spacingLeftMm={spacingLeftMm}
              />
            </group>
            <OrbitControls ref={controlsRef} enableDamping target={[0, 200, 0]} />
            <axesHelper args={[150]} />
          </Canvas>
          {/* Overlay TCP coordinates */}
          <div className="absolute top-2 left-2 bg-bg/80 rounded px-2 py-1 font-mono text-mono_sm text-amb">
            X={tcp.x} Y={tcp.y} Z={tcp.z}
          </div>
          {surfacesDrawerOpen && (
            <div className="absolute top-2 right-2 bottom-2 w-80 bg-surface border border-border rounded-sm shadow-lg p-3 overflow-y-auto z-10">
              <div className="flex items-center justify-between mb-2">
                <span className="font-display text-section text-amb">📐 Zones & Plans</span>
                <button onClick={() => setSurfacesDrawerOpen(false)}
                        className="text-text_dim hover:text-text">✕</button>
              </div>
              <ZonesPanel
                focusedId={focusedZoneId}
                onFocus={setFocusedZoneId}
                activeRid={activeRid}
                extendedIds={extendedZoneIds}
                setExtendedIds={setExtendedZoneIds}
              />
            </div>
          )}
        </div>

        {/* Jauges circulaires + coords droite */}
        <div className="col-span-2 bg-surface border border-border rounded-sm p-3 overflow-auto">
          {VISIBLE_AXES.map((a) => (
            <CircularGauge key={a} axis={a} label={AXES_LEFT[a - 1] ?? `Axe ${a}`}
                           value={displayValue(a)} color={color} />
          ))}
          <div className="border-t border-border pt-2 mt-2">
            <div className="font-ui text-caption text-text_med mb-1">TCP</div>
            <div className="font-mono text-mono_md text-text">X = {tcp.x}</div>
            <div className="font-mono text-mono_md text-text">Y = {tcp.y}</div>
            <div className="font-mono text-mono_md text-text">Z = {tcp.z}</div>
          </div>
        </div>
      </div>

      {dxfDlg && (
        <FileImportDialog
          title="📐 Importer DXF → Timeline"
          accept=".dxf,.DXF"
          robots={robots}
          scenarios={scenarios}
          importer={cmdImportDxf}
          onClose={() => setDxfDlg(false)}
          onSuccess={setActionError}
          onError={setActionError}
          paramsHint="DXF (LINE/LWPOLYLINE/POLYLINE/3DFACE) → waypoints via IK → events MOVE dans la timeline du scénario."
        />
      )}
      {gcodeDlg && (
        <FileImportDialog
          title="⚙️ Importer G-code → Timeline"
          accept=".gcode,.nc,.g,.tap"
          robots={robots}
          scenarios={scenarios}
          importer={cmdImportGcode}
          onClose={() => setGcodeDlg(false)}
          onSuccess={setActionError}
          onError={setActionError}
          paramsHint="G-code (G0/G1/G2/G3/G28/M3/M5, arcs supportés) → IK → events MOVE."
        />
      )}
    </div>
  );
}
