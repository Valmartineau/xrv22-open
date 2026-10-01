// Wizard "Créer suite pas à pas" — fidele a tab_positions.py wizard.
// Workflow :
//   1. Selectionner le robot actif
//   2. Capture position par bouton OU barre espace
//   3. Voir live la position courante (refresh 300ms)
//   4. Annuler la derniere capture, ou tout
//   5. Enregistrer la suite avec un nom

import { useEffect, useRef, useState } from "react";
import { Modal, ModalBtn } from "../components/Modal";
import { useStore } from "../store";
import { cmdCreateSuite, cmdCapture, cmdTorque, cmdCheckPosition, cmdGetTcp, type PositionConflict } from "../commands";
import { limitConflicts, formatConflicts } from "../timeline/eventEdit";
import { colorForRobot } from "../theme";

const AXIS_LABELS = ["Base", "Épaule", "Coude", "Poignet", "Tangage", "Roulis", "Pince"];

type CapturedPos = {
  id: string;        // uuid temporaire (avant save library)
  name: string;
  positions: Record<string, number>;
};

export default function WizardSuite({
  onClose, onSuiteCreated,
}: {
  onClose: () => void;
  onSuiteCreated: () => void;
}) {
  const { robots, positions, setActionError, refetchLibrary } = useStore();
  const [activeRid, setActiveRid] = useState<string>(() => {
    const m = robots.find((r) => r.is_master) || robots[0];
    return m?.id ?? "";
  });
  const [suiteName, setSuiteName] = useState(`Suite_${new Date().toISOString().slice(11, 19).replace(/:/g, "")}`);
  const [captured, setCaptured] = useState<CapturedPos[]>([]);
  // Capture en attente de décision quand la position est hors limites sliders.
  const [pendingCapture, setPendingCapture] = useState<{
    name: string; positions: Record<string, number>; conflicts: PositionConflict[];
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const robot = robots.find((r) => r.id === activeRid);
  const color = robot ? colorForRobot(robot.id) : "#f6a117";
  // Position live : lue activement sur le hardware (~300ms) tant que l'assistant
  // est ouvert. Sinon le store n'est rafraîchi que sur commande (write direct) :
  // en torque OFF, bouger le bras à la main ne mettrait rien à jour → captures
  // figées. cmdGetTcp() appelle ctrl.read_positions() (lecture HW réelle).
  const [livePos, setLivePos] = useState<Record<string, number> | undefined>(undefined);
  const connected = !!robot?.connected;
  useEffect(() => {
    if (!connected || !activeRid) { setLivePos(undefined); return; }
    let cancelled = false;
    let timer: number | null = null;
    // Boucle auto-replanifiée : on relance une lecture ~40ms après la fin de la
    // précédente (lecture HW ~115ms). Cadence ~150ms, sans empilement de requêtes
    // ni latence fixe de 300ms. La lecture série n'est faite que pour le robot
    // actif tant que l'assistant est ouvert (positionnement à la main, torque OFF).
    const loop = async () => {
      try {
        const r = await cmdGetTcp(activeRid);
        if (!cancelled) setLivePos(r.positions);
      } catch { /* lecture indisponible : on garde la dernière valeur */ }
      if (!cancelled) timer = window.setTimeout(() => void loop(), 40);
    };
    void loop();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [connected, activeRid]);

  const hw = livePos ?? positions[activeRid];

  const addCapture = (name: string, pos: Record<string, number>) => {
    const id = `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    setCaptured((cur) => [...cur, { id, name, positions: pos }]);
  };

  const onCapture = async () => {
    if (pendingCapture) return;              // décision en attente : 📸 neutralisé
    if (!robot?.connected) {
      setActionError("Robot non connecte"); return;
    }
    if (!hw) { setActionError("Pas de position live"); return; }
    const pos = { ...hw };
    const name = `${suiteName}_${String(captured.length + 1).padStart(3, "0")}`;
    // Contrôle des limites sliders (soft limits) ; collisions/plans ignorées ici.
    let limits: PositionConflict[] = [];
    try {
      const res = await cmdCheckPosition(activeRid, pos);
      limits = limitConflicts(res.conflicts);
    } catch {
      limits = [];                            // check indisponible → on n'empêche pas la capture
    }
    if (limits.length > 0) {
      setPendingCapture({ name, positions: pos, conflicts: limits });
    } else {
      addCapture(name, pos);
    }
  };

  const onValidatePending = () => {
    if (!pendingCapture) return;
    addCapture(pendingCapture.name, pendingCapture.positions);
    setPendingCapture(null);
  };
  const onDiscardPending = () => setPendingCapture(null);

  const onUndo = () => setCaptured((cur) => cur.slice(0, -1));
  const onClearAll = () => {
    if (captured.length === 0) return;
    if (window.confirm("Annuler toutes les captures ?")) setCaptured([]);
  };

  // Raccourci : barre espace = capture (si pas dans un input)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" || tgt.tagName === "SELECT") return;
      if (pendingCapture) return;            // décision en attente : espace neutralisé
      if (e.code === "Space") { e.preventDefault(); void onCapture(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [captured, robot, hw, suiteName, pendingCapture, activeRid]);

  const onSave = async () => {
    const name = suiteName.trim();
    if (!name) { setActionError("Nom de suite requis"); return; }
    if (captured.length === 0) { setActionError("Aucune position capturee"); return; }
    setBusy(true);
    try {
      // 1. Sauve chaque position dans la library
      const ids: { position_id: string; position_name: string }[] = [];
      for (const c of captured) {
        // c.positions = snapshot figé au 📸. On l'envoie explicitement, sinon
        // le backend relirait la position COURANTE → toutes les étapes
        // finiraient identiques (= position au moment du clic Enregistrer).
        const res = await cmdCapture(activeRid, c.name, "sauvegardees", c.positions);
        ids.push({ position_id: res.id, position_name: res.name });
      }
      // 2. Cree la suite avec ces positions comme steps
      const steps = ids.map((p) => ({
        position_id: p.position_id,
        position_name: p.position_name,
        duration_s: 2.0,
        pause_s: 0.0,
      }));
      await cmdCreateSuite(name, steps);
      refetchLibrary();
      onSuiteCreated();
      onClose();
    } catch (e) {
      setActionError(`wizard: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="🎬 Créer une suite pas à pas" onClose={onClose} width={720}
           footer={<>
             <ModalBtn onClick={onClearAll} disabled={captured.length === 0}>
               ❌ Annuler tout
             </ModalBtn>
             <ModalBtn onClick={onUndo} disabled={captured.length === 0}>
               ↩ Annuler dernière
             </ModalBtn>
             <div className="flex-1" />
             <ModalBtn onClick={onClose}>Fermer</ModalBtn>
             <ModalBtn primary onClick={onSave} disabled={captured.length === 0 || busy}>
               {busy ? "Sauvegarde…" : `✅ Enregistrer suite (${captured.length} étapes)`}
             </ModalBtn>
           </>}>
      {/* Header : robot + nom */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Robot :</label>
          <select value={activeRid} onChange={(e) => setActiveRid(e.target.value)}
                  className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb">
            {robots.map((r) => (
              <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Nom de la suite :</label>
          <input ref={inputRef} type="text" value={suiteName}
                 onChange={(e) => setSuiteName(e.target.value)}
                 className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
        </div>
      </div>

      {/* Live position robot */}
      <div className="bg-bg border border-border rounded-sm p-3 mb-3"
           style={{ borderColor: `${color}66` }}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-ui text-section text-amb">Position live</span>
          <span className={`font-ui text-caption ${robot?.connected ? "text-ok" : "text-err"}`}>
            {robot?.connected ? "● Connecté" : "● Déconnecté"}
            {robot?.torque_enabled === false && " · Torque OFF (libre)"}
          </span>
        </div>
        <div className="grid grid-cols-7 gap-1 mb-3">
          {AXIS_LABELS.map((label, i) => {
            const v = hw?.[String(i + 1)];
            return (
              <div key={i} className="text-center">
                <div className="font-ui text-caption text-text_med">{label}</div>
                <div className="font-mono text-mono_md text-text">{v ?? "—"}</div>
              </div>
            );
          })}
        </div>
        <div className="flex gap-2 items-center">
          <button type="button" onClick={() => void onCapture()}
                  disabled={!robot?.connected || !!pendingCapture}
                  className="px-4 py-2 rounded-sm bg-mag_dim2 text-amb border border-mag/50 hover:bg-mag font-ui text-control disabled:opacity-30">
            📸 Capturer (ou barre espace)
          </button>
          <button type="button"
                  disabled={!robot?.connected}
                  onClick={() => robot && cmdTorque(robot.id, !robot.torque_enabled)
                    .catch((e) => setActionError(`torque: ${e instanceof Error ? e.message : String(e)}`))}
                  className="px-3 py-2 rounded-sm bg-surface_hi text-text border border-border_hi hover:bg-mag_dim2 font-ui text-control disabled:opacity-30">
            Torque {robot?.torque_enabled ? "OFF" : "ON"}
          </button>
          <span className="font-ui text-caption text-text_dim ml-2">
            Astuce : torque OFF → bouge le bras à la main, puis Espace pour capturer
          </span>
        </div>
      </div>

      {/* Capture hors limites : décision Valider / Ré-enregistrer */}
      {pendingCapture && (
        <div className="bg-err_dim border border-err rounded-sm p-3 mb-3">
          <div className="flex items-start gap-2 mb-2">
            <span className="text-err font-bold text-section">!</span>
            <div className="flex-1">
              <div className="font-ui text-control text-err">
                Position hors des limites autorisées (sliders)
              </div>
              <div className="font-mono text-mono_sm text-err mt-1">
                {formatConflicts(pendingCapture.conflicts)}
              </div>
            </div>
          </div>
          <div className="flex gap-2 justify-end">
            <button type="button" onClick={onDiscardPending}
                    className="px-3 py-1.5 rounded-sm bg-surface_hi text-text border border-border_hi hover:bg-mag_dim2 font-ui text-control">
              ↩ Ré-enregistrer
            </button>
            <button type="button" onClick={onValidatePending}
                    className="px-3 py-1.5 rounded-sm bg-err text-white border border-err hover:opacity-80 font-ui text-control">
              ✓ Valider quand même
            </button>
          </div>
        </div>
      )}

      {/* Liste des positions capturees */}
      <div className="bg-bg border border-border rounded-sm max-h-48 overflow-auto">
        <div className="px-3 py-1.5 bg-surface_hi border-b border-border font-ui text-caption text-text_med flex items-center justify-between">
          <span>Étapes capturées</span>
          <span className="font-mono">{captured.length}</span>
        </div>
        {captured.length === 0 ? (
          <div className="text-text_dim text-center py-6 font-ui text-control">
            Aucune capture — appuie sur Espace ou clique 📸
          </div>
        ) : captured.map((c, i) => (
          <div key={c.id} className="flex items-center gap-3 px-3 py-1 border-b border-border/30">
            <span className="font-mono text-mono_sm text-amb w-8">{i + 1}.</span>
            <span className="font-ui text-control text-text flex-1">{c.name}</span>
            <span className="font-mono text-mono_sm text-text_dim">
              {Object.entries(c.positions).map(([k, v]) => `${k}:${v}`).join(" ")}
            </span>
          </div>
        ))}
      </div>
    </Modal>
  );
}
