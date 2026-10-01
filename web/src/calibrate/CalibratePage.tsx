// web/src/calibrate/CalibratePage.tsx
import { useState, useEffect } from "react";
import { Scene3D, type Joint } from "./Scene3D";
import { SidePanel } from "./SidePanel";
import { PARTS } from "./parts";
import { lockJoint, type Vec3 } from "./geometry";
import { fk } from "../visu/fk";
import { useCalibStore, type PartCalib } from "./store";
import { useBoxesStore, roundBoxes, newBox, LINK_NAMES } from "./boxStore";
import type { CalibBox } from "../visu/calibKinematics";
import calib from "./calibration.json";

const DEG2RAD = Math.PI / 180;
// Mapping boules fk -> axes moteurs du robot. L'épaule (axes 2 & 3) est un
// double moteur couplé au MÊME point physique -> une seule boule "2·3".
const JOINT_LABELS = ["base", "1", "2·3", "4", "5", "6", "7"];
// Orientation initiale de l'axe de travail (tige // X par défaut) :
//  - axe 1 = rotation verticale  -> tige le long de Z (Ry 90°)
//  - axes 2·3 (épaule) & 4 (coude) = flexion -> axe horizontal // X (défaut)
const INIT_AXIS_ROT: Record<number, Vec3> = { 1: [0, Math.PI / 2, 0] };
const AXIS_NAMES = ["X", "Y", "Z"] as const;

const JOINTS_KEY = "xrv22.calibrate.joints.v1";
type CalibAxis = { pos: number[]; rotDeg: number[] };
type CalibPieceJSON = {
  offset: number[]; rotDeg: number[]; axisLocal: number[] | null; joint: number | null;
};

// État initial des axes : localStorage en priorité, sinon le puzzle sauvegardé
// (calibration.json), sinon la pose neutre FK. Persiste le travail d'axes.
function loadJoints(): Joint[] {
  try {
    const raw = localStorage.getItem(JOINTS_KEY);
    if (raw) {
      const arr = JSON.parse(raw) as (Joint & { refAngle?: number })[];
      return arr.map((j) => ({  // normalise (anciens états sans parent/enfant)
        ...j,
        refParent: j.refParent ?? 0,
        refChild: j.refChild ?? j.refAngle ?? 0,
      }));
    }
  } catch { /* ignore */ }
  const axes = (calib as { axes: Record<string, CalibAxis> }).axes;
  return JOINT_LABELS.map((label, id) => {
    const a = axes?.[label];
    const pos = (a ? a.pos : fk(undefined)[id]) as Vec3;
    const rot = (a ? a.rotDeg.map((d) => d * DEG2RAD)
                   : (INIT_AXIS_ROT[id] ?? [0, 0, 0])) as Vec3;
    return { id, label, pos, rot, refParent: 0, refChild: 0 };
  });
}

export default function CalibratePage() {
  const [state, setState] = useCalibStore();
  const [active, setActive] = useState<string | null>(null);
  const [joints, setJoints] = useState<Joint[]>(loadJoints);
  const [selJoint, setSelJoint] = useState<number | null>(null);
  // Boîtes d'encombrement (anti-collision) éditables par-dessus le puzzle.
  const [boxes, setBoxes, reloadBoxes] = useBoxesStore();
  const [selBox, setSelBox] = useState<number | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [locked, setLocked] = useState(true); // verrou STL + drag (sûr par défaut)
  const [refZ, setRefZ] = useState<number>(() => {
    const v = Number(localStorage.getItem("xrv22.calibrate.refZ"));
    return Number.isFinite(v) ? v : 0; // surface de référence (sol), Z par défaut 0
  });
  useEffect(() => {
    try { localStorage.setItem("xrv22.calibrate.refZ", String(refZ)); } catch { /* */ }
  }, [refZ]);

  // Persiste les positions/orientations d'axes (sinon perdues au reload).
  useEffect(() => {
    try { localStorage.setItem(JOINTS_KEY, JSON.stringify(joints)); }
    catch { /* ignore */ }
  }, [joints]);

  // À l'ouverture : ajouter toutes les pièces MANQUANTES — à leur pose CALIBRÉE
  // (calibration.json) quand elle est connue, sinon à zéro. Le localStorage est
  // propre à chaque origine (port du serveur compris) : s'il revient vide, le
  // puzzle se restaure depuis le fichier au lieu de tout empiler à l'origine.
  // Les pièces encore à l'état "neuf" (jamais placées) sont aussi restaurées.
  useEffect(() => {
    setState((s) => {
      const pristine = (p: PartCalib) => !p.axisLocal && p.targetJoint == null &&
        p.offset.every((v) => v === 0) && p.rot.every((v) => v === 0);
      const kept = s.parts.filter((p) => !pristine(p));
      const have = new Set(kept.map((p) => p.name));
      const pieces = (calib as { pieces?: Record<string, CalibPieceJSON> }).pieces ?? {};
      const urlOf = (name: string) => PARTS.find((d) => d.name === name.split("#")[0])?.url;
      const fromFile = Object.keys(pieces)
        .filter((n) => !have.has(n) && urlOf(n))
        .map((name) => {
          const p = pieces[name];
          return {
            name, url: urlOf(name)!,
            axisLocal: (p.axisLocal ?? null) as Vec3 | null,
            targetJoint: p.joint ?? null,
            offset: p.offset as Vec3,
            rot: p.rotDeg.map((d) => d * DEG2RAD) as Vec3,
          };
        });
      const defaults = PARTS.filter((d) => !have.has(d.name) && !pieces[d.name])
        .map((d) => ({
          name: d.name, url: d.url, axisLocal: null, targetJoint: null,
          offset: [0, 0, 0] as Vec3, rot: [0, 0, 0] as Vec3,
        }));
      if (fromFile.length === 0 && defaults.length === 0 && kept.length === s.parts.length) {
        return s;
      }
      return { ...s, parts: [...kept, ...fromFile, ...defaults] };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const patch = (name: string, fn: (p: PartCalib) => PartCalib) =>
    setState((s) => ({ ...s, parts: s.parts.map((p) => (p.name === name ? fn(p) : p)) }));

  // Duplique une pièce (copie indépendante) — utile pour les pièces symétriques
  // de la pince (2 doigts, 2 barres…). Nom unique "Base#2", "Finger#3"…
  const duplicatePart = (name: string) => {
    setState((s) => {
      const src = s.parts.find((p) => p.name === name);
      if (!src) return s;
      const base = src.name.split("#")[0];
      const n = s.parts.filter((p) => p.name.split("#")[0] === base).length + 1;
      const copyName = `${base}#${n}`;
      const copy: PartCalib = { ...src, name: copyName };
      setActive(copyName);
      return { ...s, parts: [...s.parts, copy] };
    });
  };

  const deletePart = (name: string) =>
    setState((s) => ({ ...s, parts: s.parts.filter((p) => p.name !== name) }));

  const togglePartLock = (name: string) =>
    patch(name, (p) => ({ ...p, locked: !p.locked }));

  const onPick = (partName: string, center: Vec3) => {
    patch(partName, (p) => ({ ...p, axisLocal: center }));
    setActive(partName);
  };

  const setTarget = (name: string, joint: number) =>
    patch(name, (p) => ({ ...p, targetJoint: joint }));

  // Snap : amène le pivot (axisLocal) de la pièce sur la sphère cible (déplaçable).
  const snap = (name: string) =>
    patch(name, (p) => {
      if (!p.axisLocal || p.targetJoint == null) return p;
      const target = joints.find((j) => j.id === p.targetJoint)?.pos;
      if (!target) return p;
      const yz = lockJoint({ y: target[1], z: target[2] },
                           { y: p.axisLocal[1], z: p.axisLocal[2] });
      return { ...p, offset: [target[0] - p.axisLocal[0], yz.dy, yz.dz] };
    });

  const setRot = (name: string, axis: 0 | 1 | 2, deg: number) =>
    patch(name, (p) => {
      const rot = [...p.rot] as Vec3;
      rot[axis] = deg * DEG2RAD;
      return { ...p, rot };
    });

  const setOffset = (name: string, axis: 0 | 1 | 2, v: number) =>
    patch(name, (p) => {
      const offset = [...p.offset] as Vec3;
      offset[axis] = v;
      return { ...p, offset };
    });

  const moveJoint = (id: number, pos: Vec3) =>
    setJoints((js) => js.map((j) => (j.id === id ? { ...j, pos } : j)));

  // Déplace une boule sur un axe (X/Y/Z) via slider.
  const setJointPos = (id: number, axis: 0 | 1 | 2, v: number) =>
    setJoints((js) => js.map((j) => {
      if (j.id !== id) return j;
      const pos = [...j.pos] as Vec3;
      pos[axis] = v;
      return { ...j, pos };
    }));

  // Réinitialise les boules en pose DROITE verticale (REF_UP) : tout sur l'axe Z.
  const resetJointsStraight = () =>
    setJoints(JOINT_LABELS.map((label, id) => ({
      id, label, pos: fk(undefined)[id] as Vec3,
      rot: (INIT_AXIS_ROT[id] ?? [0, 0, 0]) as Vec3, refParent: 0, refChild: 0,
    })));

  // Tourne l'axe de la boule de ±90° autour de X / Y / Z (dir = +1 ou -1).
  const rotateAxis90 = (id: number, axis: 0 | 1 | 2, dir: number) =>
    setJoints((js) => js.map((j) => {
      if (j.id !== id) return j;
      const rot = [...j.rot] as Vec3;
      rot[axis] = rot[axis] + dir * (Math.PI / 2);
      return { ...j, rot };
    }));

  // Oriente l'axe de la boule librement (angle absolu en degrés autour de X/Y/Z).
  const setAxisRot = (id: number, axis: 0 | 1 | 2, deg: number) =>
    setJoints((js) => js.map((j) => {
      if (j.id !== id) return j;
      const rot = [...j.rot] as Vec3;
      rot[axis] = deg * DEG2RAD;
      return { ...j, rot };
    }));

  // Angle d'un membre dans le plan YZ (0° = vertical) — aiguilles parent/enfant.
  const setRefAngle = (id: number, which: "refParent" | "refChild", deg: number) =>
    setJoints((js) => js.map((j) => (j.id === id ? { ...j, [which]: deg } : j)));

  const selJointObj = joints.find((j) => j.id === selJoint);

  // --- Édition des boîtes d'encombrement ---
  const patchBox = (i: number, fn: (b: CalibBox) => CalibBox) =>
    setBoxes((bs) => (bs ? bs.map((b, k) => (k === i ? fn(b) : b)) : bs));

  const setBoxField = (i: number, field: "c" | "rotDeg" | "half", axis: 0 | 1 | 2, v: number) =>
    patchBox(i, (b) => {
      const arr = [...b[field]];
      arr[axis] = v;
      return { ...b, [field]: arr };
    });

  const addBox = () => {
    setBoxes((bs) => [...(bs ?? []), newBox()]);
    setSelBox((boxes?.length ?? 0)); // la nouvelle est en fin de liste
  };

  const duplicateBox = (i: number) => {
    setBoxes((bs) => {
      if (!bs) return bs;
      const copy = { ...bs[i], c: [...bs[i].c], rotDeg: [...bs[i].rotDeg], half: [...bs[i].half] };
      return [...bs, copy];
    });
    setSelBox(boxes?.length ?? 0);
  };

  const deleteBox = (i: number) => {
    setBoxes((bs) => (bs ? bs.filter((_, k) => k !== i) : bs));
    setSelBox(null);
  };

  const copyBoxesJSON = () =>
    navigator.clipboard.writeText(JSON.stringify(roundBoxes(boxes ?? []), null, 1));

  const selBoxObj = selBox != null ? boxes?.[selBox] : undefined;

  // État chiffré complet (axes 1-7 + transforms des pièces + boîtes), au format
  // de calibration.json. Sert à l'export fichier ET à l'application directe.
  const r1 = (n: number) => Math.round(n * 10) / 10;
  const buildData = () => ({
      refSurfaceZ: r1(refZ),
      axes: Object.fromEntries(
        joints.map((j) => [j.label, {
          pos: j.pos.map(r1),
          rotDeg: j.rot.map((r) => r1((r * 180) / Math.PI)),
          parentYZ: r1(j.refParent), // membre entrant / verticale (0=vertical)
          childYZ: r1(j.refChild),   // membre sortant / verticale
        }]),
      ),
      pieces: Object.fromEntries(
        state.parts.map((p) => [p.name, {
          offset: p.offset.map(r1),
          rotDeg: p.rot.map((r) => r1((r * 180) / Math.PI)),
          axisLocal: p.axisLocal ? (p.axisLocal.map(r1) as Vec3) : null,
          joint: p.targetJoint,
        }]),
      ),
      boxes: roundBoxes(boxes ?? []),
  });

  const exportState = () => {
    const blob = new Blob([JSON.stringify(buildData(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "calibrate-etat.json";
    a.click();
  };

  // Applique la calibration DIRECTEMENT : le serveur dev écrit calibration.json
  // (merge + .bak, cf. vite.config). Sur le Pi (statique), l'endpoint n'existe
  // pas → message d'erreur, utiliser Exporter.
  const [applyMsg, setApplyMsg] = useState<string>("");
  const applyCalibration = async () => {
    if (!window.confirm("Écraser calibration.json du serveur (axes + pièces + boîtes) ?")) return;
    try {
      const r = await fetch("/__save-calibration", {
        method: "POST", body: JSON.stringify(buildData()),
      });
      if (!r.ok) throw new Error(await r.text());
      setApplyMsg("✅ appliqué — recharger l'onglet IA");
    } catch (e) {
      setApplyMsg(`❌ ${String(e)} (serveur non inscriptible ? utiliser Exporter)`);
    }
  };

  return (
    <div style={{ display: "flex", width: "100%", height: "100vh" }}>
      <div id="calib-3d" style={{ flex: 1, position: "relative" }}>
        <button onClick={exportState}
                style={{ position: "absolute", top: 10, left: 10, zIndex: 10,
                         padding: "6px 10px", background: "#1b2030", color: "#dde",
                         border: "1px solid #7fd1ff", borderRadius: 6, cursor: "pointer" }}>
          💾 Exporter état
        </button>
        <button onClick={applyCalibration}
                style={{ position: "absolute", top: 10, left: 140, zIndex: 10,
                         padding: "6px 10px", background: "#1b3a22", color: "#dde",
                         border: "1px solid #3ad17f", borderRadius: 6, cursor: "pointer" }}>
          ✅ Appliquer
        </button>
        {applyMsg && (
          <div style={{ position: "absolute", top: 78, left: 10, zIndex: 10,
                        padding: "4px 8px", background: "#11141dcc", color: "#dde",
                        borderRadius: 6, font: "12px sans-serif" }}>
            {applyMsg}
          </div>
        )}
        <button onClick={() => setLocked((v) => !v)}
                style={{ position: "absolute", top: 10, left: 262, zIndex: 10,
                         padding: "6px 10px", cursor: "pointer", borderRadius: 6,
                         background: locked ? "#3a1b1b" : "#1b3a22",
                         color: "#dde", border: `1px solid ${locked ? "#ff6a6a" : "#3ad17f"}` }}>
          {locked ? "🔒 STL verrouillés" : "🔓 STL déverrouillés"}
        </button>
        {/* Boîtes d'encombrement : affichage + actions globales */}
        <div style={{ position: "absolute", top: 10, left: 452, zIndex: 10,
                      display: "flex", gap: 6 }}>
          <button onClick={() => { setShowBoxes((v) => !v); setSelBox(null); }}
                  style={{ padding: "6px 10px", cursor: "pointer", borderRadius: 6,
                           background: showBoxes ? "#13303a" : "#1b2030", color: "#dde",
                           border: `1px solid ${showBoxes ? "#36c5f0" : "#555"}` }}>
            🧊 Boîtes {showBoxes ? "ON" : "OFF"}
          </button>
          {showBoxes && (
            <>
              <button onClick={addBox} title="Ajouter une boîte"
                      style={{ padding: "6px 10px", cursor: "pointer", borderRadius: 6,
                               background: "#1b2030", color: "#dde", border: "1px solid #36c5f0" }}>
                ＋
              </button>
              <button onClick={copyBoxesJSON} title="Copier le JSON des boîtes"
                      style={{ padding: "6px 10px", cursor: "pointer", borderRadius: 6,
                               background: "#1b2030", color: "#dde", border: "1px solid #36c5f0" }}>
                📋
              </button>
              <button onClick={() => { reloadBoxes(); setSelBox(null); }}
                      title="Recharger les boîtes du fichier (écrase l'édition en cours)"
                      style={{ padding: "6px 10px", cursor: "pointer", borderRadius: 6,
                               background: "#1b2030", color: "#dde", border: "1px solid #ffaa44" }}>
                ↺
              </button>
            </>
          )}
        </div>
        {/* Surface de référence (sol) : hauteur Z réglable */}
        <div style={{ position: "absolute", top: 44, left: 10, zIndex: 10,
                      display: "flex", alignItems: "center", gap: 6, padding: "4px 8px",
                      background: "#11141dcc", color: "#dde", borderRadius: 6,
                      border: "1px solid #4aa3ff", font: "12px sans-serif" }}>
          <span style={{ color: "#4aa3ff" }}>Surface réf Z</span>
          <input type="range" min={-200} max={300} step={1} value={refZ}
                 onChange={(e) => setRefZ(+e.target.value)} style={{ width: 140 }} />
          <span style={{ width: 38, textAlign: "right" }}>{refZ}</span>
        </div>

        {/* Contrôle d'orientation de l'axe sélectionné (±90°, angles dynamiques) */}
        {selJointObj && (
          <div style={{ position: "absolute", bottom: 12, left: 12, zIndex: 10,
                        padding: 10, minWidth: 190, background: "#11141dee", color: "#dde",
                        border: "1px solid #ffcc00", borderRadius: 8, font: "13px sans-serif" }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>
              Axe {selJointObj.label}
            </div>
            {/* Position X/Y/Z de la boule */}
            <div style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid #333" }}>
              {([0, 1, 2] as const).map((ax) => (
                <div key={ax} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 14 }}>{AXIS_NAMES[ax]}</span>
                  <input type="range" min={-400} max={900} step={0.5}
                         value={selJointObj.pos[ax]}
                         onChange={(e) => setJointPos(selJointObj.id, ax, +e.target.value)}
                         style={{ flex: 1 }} />
                  <span style={{ width: 44, textAlign: "right" }}>
                    {selJointObj.pos[ax].toFixed(1)}
                  </span>
                </div>
              ))}
            </div>
            {/* Angles des membres dans le plan YZ (0° = vertical) parent/enfant */}
            <div style={{ marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid #333" }}>
              <div style={{ color: "#33aaff" }}>
                Parent (entrant) : <b>{Math.round(selJointObj.refParent)}°</b>
              </div>
              <input type="range" min={-180} max={180} step={1}
                     value={Math.round(selJointObj.refParent)}
                     onChange={(e) => setRefAngle(selJointObj.id, "refParent", +e.target.value)}
                     style={{ width: "100%" }} />
              <div style={{ color: "#7CFC00", marginTop: 4 }}>
                Enfant (sortant) : <b>{Math.round(selJointObj.refChild)}°</b>
              </div>
              <input type="range" min={-180} max={180} step={1}
                     value={Math.round(selJointObj.refChild)}
                     onChange={(e) => setRefAngle(selJointObj.id, "refChild", +e.target.value)}
                     style={{ width: "100%" }} />
            </div>
            <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>axe de rotation :</div>
            {([0, 1, 2] as const).map((ax) => {
              const deg = Math.round((selJointObj.rot[ax] * 180) / Math.PI);
              return (
                <div key={ax} style={{ marginBottom: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 14 }}>{AXIS_NAMES[ax]}</span>
                    <button onClick={() => rotateAxis90(selJointObj.id, ax, -1)}>−90°</button>
                    <span style={{ width: 44, textAlign: "center" }}>{deg}°</span>
                    <button onClick={() => rotateAxis90(selJointObj.id, ax, +1)}>+90°</button>
                  </div>
                  <input type="range" min={-180} max={180} step={1} value={deg}
                         onChange={(e) => setAxisRot(selJointObj.id, ax, +e.target.value)}
                         style={{ width: "100%" }} />
                </div>
              );
            })}
            <div style={{ opacity: 0.6, fontSize: 11, marginTop: 4 }}>
              pos&nbsp;Y={selJointObj.pos[1].toFixed(1)} Z={selJointObj.pos[2].toFixed(1)}
            </div>
          </div>
        )}

        {/* Panneau d'édition de la boîte sélectionnée */}
        {showBoxes && selBox != null && selBoxObj && (
          <div style={{ position: "absolute", bottom: 12, right: 12, zIndex: 10,
                        padding: 10, minWidth: 230, background: "#11141dee", color: "#dde",
                        border: "1px solid #36c5f0", borderRadius: 8, font: "13px sans-serif" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <span style={{ fontWeight: 700 }}>Boîte {selBox + 1}/{boxes?.length}</span>
              <select value={selBoxObj.link}
                      onChange={(e) => patchBox(selBox, (b) => ({ ...b, link: +e.target.value }))}
                      style={{ flex: 1, background: "#1b2030", color: "#dde",
                               border: "1px solid #36c5f0", borderRadius: 4 }}>
                {LINK_NAMES.map((n, i) => <option key={i} value={i}>{i} — {n}</option>)}
              </select>
            </div>
            {([["c", "Centre (mm)", -400, 900, 0.5],
               ["half", "Demi-côtés (mm)", 1, 150, 0.5],
               ["rotDeg", "Rotation (°)", -180, 180, 1]] as const).map(([field, label, min, max, step]) => (
              <div key={field} style={{ marginBottom: 8, paddingBottom: 6,
                                        borderBottom: "1px solid #333" }}>
                <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 2 }}>{label}</div>
                {([0, 1, 2] as const).map((ax) => (
                  <div key={ax} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ width: 14 }}>{AXIS_NAMES[ax]}</span>
                    <input type="range" min={min} max={max} step={step}
                           value={selBoxObj[field][ax]}
                           onChange={(e) => setBoxField(selBox, field, ax, +e.target.value)}
                           style={{ flex: 1 }} />
                    <input type="number" step={step} value={selBoxObj[field][ax]}
                           onChange={(e) => setBoxField(selBox, field, ax, +e.target.value)}
                           style={{ width: 58, background: "#1b2030", color: "#dde",
                                    border: "1px solid #444", borderRadius: 4 }} />
                  </div>
                ))}
              </div>
            ))}
            <div style={{ display: "flex", gap: 6 }}>
              <button onClick={() => duplicateBox(selBox)}
                      style={{ flex: 1, cursor: "pointer" }}>Dupliquer</button>
              <button onClick={() => deleteBox(selBox)}
                      style={{ flex: 1, cursor: "pointer", color: "#ff6a6a" }}>Supprimer</button>
              <button onClick={() => setSelBox(null)} style={{ cursor: "pointer" }}>✕</button>
            </div>
          </div>
        )}

        <Scene3D parts={state.parts} joints={joints} selectedId={selJoint} locked={locked}
                 refZ={refZ} onSelect={setSelJoint} onMoveJoint={moveJoint} onPick={onPick}
                 boxes={showBoxes ? (boxes ?? []) : []} selBox={selBox} onSelectBox={setSelBox} />
      </div>
      <SidePanel
        state={state} active={active} setActive={setActive}
        setTarget={setTarget} snap={snap} setRot={setRot} setOffset={setOffset}
        duplicatePart={duplicatePart} deletePart={deletePart}
        joints={joints} selJoint={selJoint} setSelJoint={setSelJoint}
        resetJointsStraight={resetJointsStraight} togglePartLock={togglePartLock}
      />
    </div>
  );
}
