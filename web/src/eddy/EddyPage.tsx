import { useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { useLiveBus } from "../useLiveBus";
import { RobotMeshSTL } from "../visu/RobotMeshSTL";
import { cmdEddySay } from "../commands";
import { reduceEddy, ticksAffichees, VIEW_VIDE,
  type EddyView, type EddyStep, type DialogueLine } from "./reduce";

const CUIVRE = "#C47832";

// Fil de conversation : echo immédiat de la personne (eddy.say) puis réponses
// d'Eddy au fil de ses pas. Auto-défilement vers le dernier message.
function Dialogue({ lignes }: { lignes: DialogueLine[] }) {
  const fin = useRef<HTMLDivElement>(null);
  useEffect(() => { fin.current?.scrollIntoView({ block: "end" }); }, [lignes.length]);
  return (
    <div style={{ maxHeight: 132, overflowY: "auto", display: "flex",
      flexDirection: "column", gap: 6, paddingRight: 4 }}>
      {lignes.length === 0 && (
        <div style={{ fontSize: 11, opacity: .45, fontStyle: "italic" }}>
          Parle-lui pendant qu'il bouge…</div>
      )}
      {lignes.map((l, i) => (
        <div key={i} style={{ alignSelf: l.qui === "humain" ? "flex-end" : "flex-start",
          maxWidth: "82%", fontSize: 12.5, lineHeight: 1.34, padding: "6px 10px",
          borderRadius: 11,
          background: l.qui === "humain" ? CUIVRE : "rgba(255,255,255,.07)",
          color: l.qui === "humain" ? "#30001a" : "#fbf9f8",
          fontStyle: l.qui === "eddy" ? "italic" : "normal",
          fontWeight: l.qui === "humain" ? 600 : 400 }}>
          {l.qui === "eddy" && l.pas != null && (
            <small style={{ opacity: .5, fontStyle: "normal", marginRight: 5 }}>pas {l.pas}</small>
          )}
          {l.texte}
        </div>
      ))}
      <div ref={fin} />
    </div>
  );
}

function Manettes({ step }: { step: EddyStep }) {
  const max = Math.max(1, ...step.manettes.map((v) => Math.abs(v)));
  return (
    <div style={{ display: "flex", gap: 5, alignItems: "flex-end", height: 40 }}>
      {step.manettes.map((v, i) => (
        <div key={i} style={{ flex: 1, background: "rgba(255,255,255,.08)",
          borderRadius: 4, position: "relative", height: "100%" }}>
          <i style={{ position: "absolute", bottom: 0, left: 0, right: 0,
            borderRadius: 4, height: `${Math.round((Math.abs(v) / max) * 100)}%`,
            background: "linear-gradient(90deg,#C47832,#8B2252,#573059,#3B2060)",
            boxShadow: i === step.manette_active ? `0 0 10px ${CUIVRE}` : "none" }} />
        </div>
      ))}
    </div>
  );
}

export default function EddyPage() {
  const [view, setView] = useState<EddyView>(VIEW_VIDE);
  useLiveBus((msg) => setView((v) => reduceEddy(v, msg)));

  const [saisie, setSaisie] = useState("");

  const step = view.step;
  const ticks = ticksAffichees(view);  // positions du pas si présentes, sinon vrai bras live
  const pct = step.plafond > 0
    ? Math.min(100, Math.round((step.pression / step.plafond) * 100)) : 0;

  // Envoi d'un message à Eddy : dépôt dans la boîte du run (injecté au prochain
  // pas) ; l'echo immédiat revient par le bus (eddy.say) et s'affiche dans le fil.
  function envoyer() {
    const m = saisie.trim();
    if (!m) return;
    setSaisie("");
    cmdEddySay(m).catch(() => { /* le run vit sa vie : on n'interrompt jamais le bras */ });
  }

  return (
    <div style={{ width: "100vw", height: "100vh", overflow: "hidden",
      background: "linear-gradient(160deg,#30001a 0%,#3b0d2b 55%,#1c1330 100%)",
      color: "#fbf9f8", fontFamily: "Inter, system-ui, sans-serif",
      display: "flex", flexDirection: "column", padding: 16, boxSizing: "border-box" }}>

      <div style={{ fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase",
        color: CUIVRE }}>Boîte blanche</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>Eddy
        <span style={{ fontSize: 12, opacity: .55, fontWeight: 400 }}> · pas {step.pas}</span>
      </div>

      <div style={{ flex: "1 1 auto", minHeight: 0, margin: "12px 0", borderRadius: 14,
        overflow: "hidden", border: "1px solid rgba(196,120,50,.25)",
        background: "radial-gradient(120% 90% at 50% 18%,#241036,#0d0518)" }}>
        <Canvas camera={{ position: [400, 500, 600], fov: 45, near: 1, far: 5000 }}>
          <ambientLight intensity={0.5} />
          <directionalLight position={[200, 400, 300]} intensity={0.9} />
          {/* Modèle Z-up → bascule dans le monde Y-up (comme l'onglet Visu). */}
          <group rotation={[-Math.PI / 2, 0, 0]}>
            <RobotMeshSTL ticks={ticks} color={CUIVRE} />
          </group>
          <OrbitControls enableDamping enablePan={false} target={[0, 200, 0]} />
        </Canvas>
      </div>

      <div style={{ background: "rgba(255,255,255,.055)", borderRadius: 13, padding: "11px 12px" }}>
        <div style={{ fontSize: 9, letterSpacing: ".15em", textTransform: "uppercase",
          color: CUIVRE, marginBottom: 7 }}>Ce qu'il perçoit · corps</div>
        <Manettes step={step} />
        <div style={{ display: "flex", gap: 8, marginTop: 9 }}>
          {step.signaux.map((v, i) => (
            <div key={i} style={{ flex: 1, textAlign: "center",
              background: "rgba(255,255,255,.04)", borderRadius: 7, padding: "5px 0" }}>
              <small style={{ opacity: .5, fontSize: 8, letterSpacing: ".1em" }}>SIG {i + 1}</small>
              <b style={{ display: "block", fontSize: 16 }}>{v}</b>
            </div>
          ))}
        </div>
        <div style={{ height: 11, borderRadius: 7, background: "rgba(255,255,255,.1)",
          marginTop: 10, position: "relative", overflow: "hidden" }}>
          <i style={{ position: "absolute", left: 0, top: 0, bottom: 0, borderRadius: 7,
            width: `${pct}%`, background: "linear-gradient(90deg,#C47832,#8B2252,#573059,#3B2060)" }} />
          <div style={{ position: "absolute", top: -2, bottom: -2, left: "100%",
            width: 2, background: "#ff5d5d" }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9,
          opacity: .6, marginTop: 3 }}>
          <span>pression {step.pression}</span><span>plafond {step.plafond}</span>
        </div>
      </div>

      <div style={{ background: "rgba(255,255,255,.055)", borderRadius: 13,
        padding: "11px 12px", marginTop: 10 }}>
        <div style={{ fontSize: 9, letterSpacing: ".15em", textTransform: "uppercase",
          color: CUIVRE, marginBottom: 7 }}>Ce qu'il pense · cognition</div>
        <div style={{ fontSize: 14, lineHeight: 1.38, fontWeight: 600, fontStyle: "italic" }}>
          « {step.pensee || "…"} »</div>
        <div style={{ fontSize: 11, opacity: .72, marginTop: 6 }}>📓 {step.note}</div>
        <span style={{ display: "inline-block", fontSize: 10, fontWeight: 700,
          padding: "3px 9px", borderRadius: 20, marginTop: 9,
          background: step.bloque ? "#ff5d5d" : CUIVRE, color: "#30001a" }}>
          {step.bloque ? "BLOQUÉ · garde-fou" : `→ manette ${step.manette_active} · delta ${step.delta}`}
        </span>
      </div>

      <div style={{ background: "rgba(255,255,255,.055)", borderRadius: 13,
        padding: "11px 12px", marginTop: 10 }}>
        <div style={{ fontSize: 9, letterSpacing: ".15em", textTransform: "uppercase",
          color: CUIVRE, marginBottom: 8 }}>Dialogue-en-mouvement</div>
        <Dialogue lignes={view.dialogue} />
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <input
            value={saisie}
            onChange={(e) => setSaisie(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") envoyer(); }}
            placeholder="Dis quelque chose à Eddy…"
            style={{ flex: 1, background: "rgba(255,255,255,.06)", color: "#fbf9f8",
              border: "1px solid rgba(196,120,50,.3)", borderRadius: 10,
              padding: "9px 12px", fontSize: 13, outline: "none",
              fontFamily: "inherit" }}
          />
          <button
            onClick={envoyer}
            disabled={!saisie.trim()}
            style={{ background: saisie.trim() ? CUIVRE : "rgba(255,255,255,.1)",
              color: saisie.trim() ? "#30001a" : "rgba(255,255,255,.4)",
              border: "none", borderRadius: 10, padding: "0 16px", fontSize: 13,
              fontWeight: 700, cursor: saisie.trim() ? "pointer" : "default" }}>
            Envoyer
          </button>
        </div>
      </div>
    </div>
  );
}
