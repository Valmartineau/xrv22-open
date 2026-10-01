// web/src/calibrate/SidePanel.tsx
import { JOINTS } from "./parts";
import { toExportJSON, type CalibState, type PartCalib } from "./store";
import type { Joint } from "./Scene3D";

const DEG = 180 / Math.PI;

export function SidePanel({ state, active, setActive, setTarget,
                            snap, setRot, setOffset, duplicatePart, deletePart,
                            joints, selJoint, setSelJoint, resetJointsStraight,
                            togglePartLock }: {
  state: CalibState;
  active: string | null;
  setActive: (name: string) => void;
  setTarget: (name: string, joint: number) => void;
  snap: (name: string) => void;
  setRot: (name: string, axis: 0 | 1 | 2, deg: number) => void;
  setOffset: (name: string, axis: 0 | 1 | 2, v: number) => void;
  duplicatePart: (name: string) => void;
  deletePart: (name: string) => void;
  joints: Joint[];
  selJoint: number | null;
  setSelJoint: (id: number | null) => void;
  resetJointsStraight: () => void;
  togglePartLock: (name: string) => void;
}) {
  const exportJson = JSON.stringify(toExportJSON(state), null, 2);
  const ap: PartCalib | undefined = state.parts.find((p) => p.name === active);
  const isCopy = (name: string) => name.includes("#");

  return (
    <div style={{ width: 340, padding: 12, overflowY: "auto",
                  background: "#11141d", color: "#dde", fontSize: 13 }}>
      <h3>Axes (sélection)</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 4 }}>
        {joints.map((j) => (
          <button key={j.id}
                  onClick={() => setSelJoint(selJoint === j.id ? null : j.id)}
                  style={{ fontWeight: selJoint === j.id ? 700 : 400,
                           outline: selJoint === j.id ? "1px solid #ffcc00" : "none" }}>
            {j.label}
          </button>
        ))}
      </div>
      <p style={{ opacity: 0.6, fontSize: 11, marginTop: 0 }}>
        Sélectionne ici pour régler un axe sans risquer de le déplacer à la souris.
      </p>
      <button onClick={resetJointsStraight}
              style={{ marginBottom: 8, border: "1px solid #7fd1ff", borderRadius: 6,
                       background: "#16202e", color: "#dde", cursor: "pointer", padding: "5px 8px" }}>
        ↺ Pose droite (REF_UP) — aligne les boules à la verticale
      </button>

      <h3>Pièces ({state.parts.length})</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {state.parts.map((p) => (
          <button key={p.name}
                  onClick={() => setActive(p.name)}
                  style={{ fontWeight: active === p.name ? 700 : 400,
                           outline: active === p.name ? "1px solid #7fd1ff" : "none",
                           opacity: p.locked ? 0.6 : 1 }}>
            {p.locked ? "🔒 " : ""}{p.name}
          </button>
        ))}
      </div>

      {ap && (
        <div style={{ marginTop: 16 }}>
          <h3>Pièce active : {ap.name}</h3>
          <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
            <button onClick={() => togglePartLock(ap.name)}
                    style={{ border: `1px solid ${ap.locked ? "#ff6a6a" : "#3ad17f"}`,
                             background: ap.locked ? "#3a1b1b" : "#1b3a22", color: "#dde" }}>
              {ap.locked ? "🔒 Verrouillée" : "🔓 Verrouiller"}
            </button>
            <button onClick={() => duplicatePart(ap.name)}>⧉ Dupliquer</button>
            {isCopy(ap.name) && (
              <button onClick={() => deletePart(ap.name)}
                      style={{ color: "#ff6a6a" }}>🗑 Supprimer</button>
            )}
          </div>
          <p style={{ opacity: 0.7 }}>
            1. Clique la face d&apos;articulation d&apos;entrée dans la vue.<br />
            2. Choisis le joint cible, puis Snap.<br />
            3. Oriente avec les sliders.
          </p>
          <div>Axe cliqué : {ap.axisLocal
            ? `Y=${ap.axisLocal[1].toFixed(1)} Z=${ap.axisLocal[2].toFixed(1)}`
            : "— (clique une face)"}</div>

          <div style={{ marginTop: 8 }}>
            Joint cible :{" "}
            <select value={ap.targetJoint ?? ""}
                    onChange={(e) => setTarget(ap.name, +e.target.value)}>
              <option value="">—</option>
              {JOINTS.map((j) => <option key={j.index} value={j.index}>{j.label}</option>)}
            </select>{" "}
            <button disabled={!ap.axisLocal || ap.targetJoint == null}
                    onClick={() => snap(ap.name)}>Snap</button>
          </div>

          <h4 style={{ marginTop: 12 }}>Orientation (°)</h4>
          {([0, 1, 2] as const).map((ax) => {
            const deg = Math.round(ap.rot[ax] * DEG);
            return (
              <div key={ax} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 18 }}>{["Rx", "Ry", "Rz"][ax]}</span>
                <button disabled={ap.locked} onClick={() => setRot(ap.name, ax, deg - 90)}>−90°</button>
                <input type="range" min={-180} max={180} step={1} value={deg}
                       disabled={ap.locked}
                       onChange={(e) => setRot(ap.name, ax, +e.target.value)}
                       style={{ flex: 1 }} />
                <button disabled={ap.locked} onClick={() => setRot(ap.name, ax, deg + 90)}>+90°</button>
                <span style={{ width: 38, textAlign: "right" }}>{deg}°</span>
              </div>
            );
          })}

          <h4 style={{ marginTop: 12 }}>Position / Offset (mm)</h4>
          {([0, 1, 2] as const).map((ax) => (
            <div key={ax} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 12 }}>{["X", "Y", "Z"][ax]}</span>
              <input type="range" min={-400} max={900} step={0.5}
                     disabled={ap.locked}
                     value={ap.offset[ax]}
                     onChange={(e) => setOffset(ap.name, ax, +e.target.value)}
                     style={{ flex: 1 }} />
              <span style={{ width: 44, textAlign: "right" }}>{ap.offset[ax].toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}

      <h3 style={{ marginTop: 16 }}>Export</h3>
      <textarea readOnly value={exportJson} style={{ width: "100%", height: 160 }} />
      <button onClick={() => navigator.clipboard.writeText(exportJson)}>Copier</button>
    </div>
  );
}
