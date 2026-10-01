// Page Positions & Suites — fidele a xrv22/ui/tab_positions.py.
// Layout :
//   Toolbar haute droite : Rafraichir + Creer suite pas a pas + Suite + Dossier + Enregistrer position
//   2 colonnes :
//     gauche : Suites et Positions (arborescence) + boutons Dupliquer/Supprimer/etc.
//     droite : panneau robot (selecteur + Direct/Assiette + sliders miroir live + Aller a/Enregistrer)

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import {
  cmdCapture, cmdDeletePosition, cmdDeleteSuite,
  cmdCreateSuite, cmdGotoPosition, cmdUpdateSuite,
  cmdCheckPosition, type PositionConflict,
} from "../commands";
import { colorForRobot } from "../theme";
import type { PositionRec, SuiteRec } from "../types";
import WizardSuite from "./WizardSuite";
import { useActiveRobot, useLiveAxesShared } from "../liveAxes";
import { gripMm, GRIP_CLOSE_TICK, GRIP_MM_PER_TICK } from "../grip";
import { PositionEditorModal } from "../components/PositionEditorModal";
import { formatConflicts } from "../timeline/eventEdit";

const AXIS_LABELS = [
  "Base", "Épaule", "Coude", "Poignet", "Tangage", "Roulis", "Pince",
];

// ── Toolbar haute (droite) ───────────────────────────────────────

function ToolbarBtn({
  children, onClick, primary, busy, disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  busy?: boolean;
  disabled?: boolean;
}) {
  const tone = primary
    ? "bg-mag_dim2 text-amb border-mag/50 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={busy || disabled}
            className={`px-3 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30 ${tone}`}>
      {busy ? "…" : children}
    </button>
  );
}

// ── Arborescence Suites + Positions ──────────────────────────────

const SuiteNode = memo(function SuiteNode({
  suite, positionsById, expanded, onToggle, selected, onSelect, onDeleteSuite,
  onSuiteDragStart,
}: {
  suite: SuiteRec;
  positionsById: Map<string, PositionRec>;
  expanded: boolean;
  onToggle: () => void;
  selected: string | null;
  onSelect: (posId: string) => void;
  onDeleteSuite: () => void;
  onSuiteDragStart?: (e: React.DragEvent) => void;
}) {
  return (
    <div>
      <div
        draggable={!!onSuiteDragStart}
        onDragStart={onSuiteDragStart}
        className="flex items-center gap-1 px-2 py-1 hover:bg-surface_hi cursor-grab active:cursor-grabbing group"
        onClick={onToggle}
      >
        <span className="text-text_med w-3">{expanded ? "▼" : "▶"}</span>
        <span className="font-ui text-control text-text flex-1">📁 {suite.name}</span>
        <span className="font-mono text-mono_sm text-text_dim mr-2">
          {suite.steps?.length ?? 0} étapes
        </span>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDeleteSuite(); }}
          className="opacity-0 group-hover:opacity-100 text-err hover:text-err_deep px-1 transition"
          title="Supprimer la suite"
        >🗑</button>
      </div>
      {expanded && (suite.steps ?? []).map((step, i) => {
        const pos = positionsById.get(step.position_id);
        const pince = pos?.positions?.["7"];
        const isSel = selected === step.position_id;
        return (
          <div
            key={`${suite.id}-${i}-${step.position_id}`}
            draggable={false}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(step.position_id);
            }}
            onMouseDown={(e) => e.stopPropagation()}
            className={`flex items-center gap-2 pl-8 pr-3 py-0.5 cursor-pointer select-none ${
              isSel ? "bg-amb_dim2/40 border-l-2 border-amb" : "hover:bg-surface_hi/60"
            }`}
          >
            <span className="text-text_dim">●</span>
            <span className="font-ui text-control text-text flex-1 truncate">
              {step.position_name || pos?.name || step.position_id}
            </span>
            <span className="font-mono text-mono_sm text-text_med tabular-nums">
              {pince ?? "—"}
            </span>
          </div>
        );
      })}
    </div>
  );
});

function PositionsTree({
  suites, positionsLib, selected, onSelect, onDeleteSuite, onMoveSuiteToFolder,
  conflictsByPos, onDoubleClickPos,
}: {
  suites: SuiteRec[];
  positionsLib: PositionRec[];
  selected: string | null;
  onSelect: (id: string) => void;
  onDeleteSuite: (id: string) => void;
  onMoveSuiteToFolder: (suiteId: string, folderName: string | null) => void;
  conflictsByPos: Record<string, PositionConflict[]>;
  onDoubleClickPos: (p: PositionRec) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [dragOver, setDragOver] = useState<string | null>(null);
  const positionsById = useMemo(
    () => new Map(positionsLib.map((p) => [p.id, p])),
    [positionsLib]
  );

  const toggle = (sid: string) => {
    const next = new Set(expanded);
    next.has(sid) ? next.delete(sid) : next.add(sid);
    setExpanded(next);
  };

  // Separe folders / regular suites / orphan suites
  const folders = useMemo(
    () => suites.filter((s) => (s.meta as { is_folder?: boolean })?.is_folder),
    [suites]
  );
  const regulars = useMemo(
    () => suites.filter((s) => !(s.meta as { is_folder?: boolean })?.is_folder),
    [suites]
  );
  const inFolder = (folderName: string) =>
    regulars.filter((s) => (s.meta as { parent_folder?: string })?.parent_folder === folderName);
  const rootSuites = regulars.filter(
    (s) => !(s.meta as { parent_folder?: string })?.parent_folder
  );

  useEffect(() => {
    if (expanded.size === 0) {
      const first = folders[0]?.id || rootSuites[0]?.id;
      if (first) setExpanded(new Set([first]));
    }
  }, [suites]);

  // Positions orphelines (pas dans une suite)
  const usedIds = useMemo(() => {
    const s = new Set<string>();
    for (const su of suites) for (const st of su.steps ?? []) s.add(st.position_id);
    return s;
  }, [suites]);
  const orphans = positionsLib.filter((p) => !usedIds.has(p.id));

  const renderSuite = (s: SuiteRec, indent = 0) => (
    <div key={s.id} style={{ marginLeft: indent }}>
      <SuiteNode
        suite={s}
        positionsById={positionsById}
        expanded={expanded.has(s.id)}
        onToggle={() => toggle(s.id)}
        selected={selected}
        onSelect={onSelect}
        onDeleteSuite={() => onDeleteSuite(s.id)}
        onSuiteDragStart={(e) => {
          e.dataTransfer.setData("text/x-suite-id", s.id);
          e.dataTransfer.effectAllowed = "move";
        }}
      />
    </div>
  );

  // Scroll preservation : evite que la liste "saute en haut" quand le store
  // change (ui.refresh, refetch, etc.) ou que selectedPosId change.
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollTopRef = useRef(0);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => { scrollTopRef.current = el.scrollTop; };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);
  // Apres chaque render (changement suites/positionsLib/selected) -> restaure
  useEffect(() => {
    const el = scrollRef.current;
    if (el && el.scrollTop !== scrollTopRef.current) {
      el.scrollTop = scrollTopRef.current;
    }
  });

  return (
    <div ref={scrollRef} className="bg-bg border border-border rounded-sm h-full overflow-auto">
      <div className="flex items-center px-3 py-1.5 bg-surface_hi border-b border-border sticky top-0 z-10">
        <span className="font-ui text-caption text-text_med flex-1">Position</span>
        <span className="font-ui text-caption text-text_med w-16 text-right">Pince</span>
      </div>
      <div className="py-1">
        {suites.length === 0 && positionsLib.length === 0 && (
          <div className="text-text_dim text-center py-8 font-ui text-control">
            Aucune suite — clique sur "Suite" ou "Dossier" pour commencer
          </div>
        )}

        {/* Dossiers + leur contenu */}
        {folders.map((f) => (
          <div key={f.id}
               onDragOver={(e) => {
                 if (e.dataTransfer.types.includes("text/x-suite-id")) {
                   e.preventDefault();
                   setDragOver(f.name);
                 }
               }}
               onDragLeave={() => setDragOver(null)}
               onDrop={(e) => {
                 const sid = e.dataTransfer.getData("text/x-suite-id");
                 if (sid && sid !== f.id) onMoveSuiteToFolder(sid, f.name);
                 setDragOver(null);
               }}
               className={dragOver === f.name ? "bg-amb_dim2/30 border-y border-amb/40" : ""}>
            <div className="flex items-center gap-1 px-2 py-1 hover:bg-surface_hi cursor-pointer"
                 onClick={() => toggle(f.id)}>
              <span className="text-text_med w-3">{expanded.has(f.id) ? "▼" : "▶"}</span>
              <span className="font-ui text-control text-amb flex-1">📁 {f.name}</span>
              <span className="font-mono text-mono_sm text-text_dim mr-2">
                {inFolder(f.name).length} suites
              </span>
            </div>
            {expanded.has(f.id) && inFolder(f.name).map((s) => renderSuite(s, 16))}
          </div>
        ))}

        {/* Suites a la racine (pas dans un dossier) */}
        {folders.length > 0 && rootSuites.length > 0 && (
          <div className="border-t border-border my-2" />
        )}
        <div onDragOver={(e) => {
               if (e.dataTransfer.types.includes("text/x-suite-id")) {
                 e.preventDefault();
                 setDragOver("__root");
               }
             }}
             onDragLeave={() => setDragOver(null)}
             onDrop={(e) => {
               const sid = e.dataTransfer.getData("text/x-suite-id");
               if (sid) onMoveSuiteToFolder(sid, null);
               setDragOver(null);
             }}
             className={dragOver === "__root" ? "bg-info/10 border-y border-info/30" : ""}>
          {rootSuites.map((s) => renderSuite(s))}
        </div>

        {orphans.length > 0 && (
          <div className="mt-3 border-t border-border pt-2">
            <div className="px-3 py-1 font-ui text-caption text-text_med">
              📂 Positions sans suite ({orphans.length})
            </div>
            {orphans.map((p) => {
              const pince = p.positions?.["7"];
              const isSel = selected === p.id;
              const posConflicts = conflictsByPos[p.id] ?? [];
              return (
                <div
                  key={p.id}
                  onClick={() => onSelect(p.id)}
                  onDoubleClick={() => onDoubleClickPos(p)}
                  className={`flex items-center gap-2 pl-6 pr-3 py-0.5 cursor-pointer ${
                    isSel ? "bg-amb_dim2/40 border-l-2 border-amb" : "hover:bg-surface_hi/60"
                  }`}
                >
                  <span className="text-text_dim">●</span>
                  {posConflicts.length > 0 && (
                    <span className="text-err font-bold mr-1" title={formatConflicts(posConflicts)}>!</span>
                  )}
                  <span className="font-ui text-control text-text flex-1 truncate">
                    {p.name}
                  </span>
                  <span className="font-mono text-mono_sm text-text_med tabular-nums">
                    {pince ?? "—"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Slider d'axe (panneau droit) — miroir live, fond robot brun saturé ──

function PositionSlider({
  axis, label, color, value, locked, ghost, hwLive,
  onPointerDown, onPointerUp, onChange,
}: {
  axis: number;
  label: string;
  color: string;
  value: number;
  locked?: { reason: string };
  ghost: number | undefined;       // valeur de la position sélectionnée
  hwLive: number | undefined;
  onPointerDown: () => void;
  onPointerUp: () => void;
  onChange: (v: number) => void;
}) {
  const isPince = axis === 7;
  const fmt = (t: number) =>
    isPince
      ? `${gripMm(t).toFixed(1)} mm`
      : `${(((t - 2048) / 4095) * 360).toFixed(1)}°`;
  const pct = (v: number) => (v / 4095) * 100;

  return (
    <div className={`mb-3 ${locked ? "opacity-40" : ""}`}>
      <div className="flex items-baseline mb-1 px-1">
        <span className={`font-ui text-control flex-1 ${locked ? "text-text_dim" : "text-amb"}`}>
          {label}
        </span>
        <span className="font-mono text-mono_md text-text mr-3 tabular-nums">{value}</span>
        <span className="font-ui text-control text-text w-20 text-right">{fmt(value)}</span>
      </div>
      <div
        className="relative h-7 rounded-sm flex items-center"
        style={{ background: locked ? "#2a2e40" : `${color}55` }}
      >
        {/* Marqueur fantôme : position sélectionnée (cyan, distinct du fantôme HW) */}
        {ghost !== undefined && (
          <div className="absolute top-0 bottom-0 w-0.5 bg-info pointer-events-none"
               style={{ left: `${pct(ghost)}%` }}
               title={`Position sélectionnée : ${ghost}`} />
        )}
        {/* Curseur fantôme HW (blanc) */}
        {hwLive !== undefined && Math.abs(hwLive - value) > 5 && (
          <div className="absolute top-1 bottom-1 w-px bg-white/40 pointer-events-none"
               style={{ left: `${pct(hwLive)}%` }} />
        )}
        {/* Pouce marine bordure ambre */}
        <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-5 h-5 rounded-full pointer-events-none z-20"
             style={{
               left: `${pct(value)}%`,
               background: "#1e2944",
               border: locked ? "2px solid #4a5061" : "2px solid #f6a117",
             }} />
        <input
          type="range" min={0} max={4095} step={1} value={value}
          disabled={!!locked}
          title={locked?.reason}
          onPointerDown={locked ? undefined : onPointerDown}
          onPointerUp={locked ? undefined : onPointerUp}
          onPointerCancel={locked ? undefined : onPointerUp}
          onChange={(e) => { if (!locked) onChange(Number(e.target.value)); }}
          className={`absolute inset-0 w-full opacity-0 z-10 ${locked ? "cursor-not-allowed" : "cursor-pointer"}`}
        />
        {/* Regle pince (axe 7) : marqueurs mm reels positionnes sur la course calibree */}
        {isPince && (
          <div className="absolute -bottom-2 left-0 right-0 h-2 pointer-events-none">
            {[10, 20, 30, 40].map((mm) => {
              const tick = GRIP_CLOSE_TICK + mm / GRIP_MM_PER_TICK;
              return (
                <span key={mm}
                      className="absolute font-mono text-[8px] text-text_dim -translate-x-1/2"
                      style={{ left: `${(tick / 4095) * 100}%` }}>
                  |{mm}
                </span>
              );
            })}
          </div>
        )}
      </div>
      {/* Hints (Gauche/Droite) */}
      <div className="flex justify-between mt-1 px-1">
        <span className="font-ui text-caption text-text_dim">
          {axis === 1 ? "Gauche" : axis === 2 ? "Lever" : axis === 3 ? "Fermer" :
           axis === 4 ? "Baisser" : axis === 5 ? "Horaire" : axis === 6 ? "" :
           isPince ? "Fermée" : ""}
        </span>
        <span className="font-ui text-caption text-text_dim">
          {axis === 1 ? "Droite" : axis === 2 ? "Baisser" : axis === 3 ? "Ouvrir" :
           axis === 4 ? "Lever" : axis === 5 ? "Anti-H" : axis === 6 ? "" :
           isPince ? "Ouverte" : ""}
        </span>
      </div>
    </div>
  );
}

// ── Panneau droit (robot + position sélectionnée) ────────────────

function PositionPanel({
  selectedPosition, robots, activeRid, onSetRid, onSavePosition,
}: {
  selectedPosition: PositionRec | null;
  robots: ReturnType<typeof useStore>["robots"];
  activeRid: string;
  onSetRid: (id: string) => void;
  onSavePosition: () => void;
}) {
  const { positions: hwPositions, setActionError, direct, setDirect } = useStore();
  const robot = robots.find((r) => r.id === activeRid);
  const color = robot ? colorForRobot(robot.id) : "#f6a117";
  const hw = hwPositions[activeRid];

  // Slider d'axe : instance partagee montee au-dessus du routeur.
  const liveAxes = useLiveAxesShared();

  // Envoie le robot vers la position sélectionnée (mouvement géré backend).
  const goPosition = () => {
    if (!selectedPosition || !robot?.connected || !robot.torque_enabled) {
      setActionError("Robot non connecté ou torque OFF"); return;
    }
    cmdGotoPosition(selectedPosition.id, activeRid).catch((e) =>
      setActionError(`go: ${e instanceof Error ? e.message : String(e)}`));
  };

  return (
    <div
      className="rounded-sm border h-full flex flex-col overflow-hidden"
      style={{ background: `${color}1a`, borderColor: `${color}66` }}
    >
      {/* Header : selecteur robot + Direct + Assiette */}
      <div
        className="flex items-center gap-3 px-3 py-2 border-b"
        style={{ background: `${color}33`, borderColor: `${color}66` }}
      >
        <select
          value={activeRid}
          onChange={(e) => onSetRid(e.target.value)}
          className="bg-bg border border-border_hi rounded-sm px-2 py-1 font-ui text-control text-text focus:outline-none focus:border-amb"
        >
          {robots.map((r) => (
            <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
          ))}
        </select>
        <span className="font-display text-section text-amb">{activeRid}</span>
        <div className="flex-1" />
        <label className="flex items-center gap-2 cursor-pointer text-control font-ui text-text">
          <input type="checkbox" className="accent-amb" checked={direct}
                 onChange={(e) => setDirect(e.target.checked)}
                 disabled={!robot?.connected || !robot.torque_enabled} />
          🎮 Direct
        </label>
        <label className="flex items-center gap-2 cursor-pointer text-control font-ui text-text">
          <input type="checkbox" className="accent-amb" disabled />
          🔒 Assiette
        </label>
      </div>

      {/* Titre position selectionnee + aide contextuelle */}
      <div className="px-3 py-2">
        <div className="font-ui text-section text-text">
          {selectedPosition ? selectedPosition.name : "Sélectionnez une position"}
        </div>
        <div className="font-ui text-caption text-text_dim">
          {direct
            ? "Mode Direct : glisse les sliders pour piloter le robot."
            : "Sliders verrouillés — active Direct pour piloter, ou enregistre la position courante."}
        </div>
      </div>

      {/* Sliders miroir live */}
      <div className="flex-1 overflow-auto px-3 py-2">
        {AXIS_LABELS.map((label, i) => {
          const axis = i + 1;
          return (
            <PositionSlider
              key={axis}
              axis={axis}
              label={label}
              color={color}
              value={liveAxes.value(axis)}
              locked={liveAxes.locked(axis)}
              ghost={selectedPosition?.positions?.[String(axis)]}
              hwLive={hw?.[String(axis)]}
              onPointerDown={() => liveAxes.onPointerDown(axis)}
              onPointerUp={() => liveAxes.onPointerUp(axis)}
              onChange={(v) => liveAxes.onChange(axis, v)}
            />
          );
        })}
      </div>

      {/* Boutons bas : Aller à / Enregistrer */}
      <div className="px-3 py-2 border-t flex gap-2"
           style={{ borderColor: `${color}66` }}>
        <ToolbarBtn primary onClick={goPosition}
                    disabled={!robot?.connected || !robot.torque_enabled || !selectedPosition}>
          🎯 Aller à
        </ToolbarBtn>
        <div className="flex-1" />
        <ToolbarBtn primary onClick={onSavePosition} disabled={!robot?.connected}>
          💾 Enregistrer
        </ToolbarBtn>
      </div>
    </div>
  );
}

// ── Page principale ──────────────────────────────────────────────

export default function Positions() {
  const { robots, positionsLib, suites, setActionError, refetchLibrary } = useStore();
  const { activeRid, setActiveRid } = useActiveRobot();
  const [selectedPosId, setSelectedPosId] = useState<string | null>(null);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [editingPos, setEditingPos] = useState<PositionRec | null>(null);
  const [conflictsByPos, setConflictsByPos] = useState<Record<string, PositionConflict[]>>({});
  const activeRobot = robots.find((r) => r.id === activeRid);

  useEffect(() => {
    if (!activeRid) { setConflictsByPos({}); return; }
    let cancelled = false;
    Promise.all(positionsLib.map((p) =>
      cmdCheckPosition(activeRid, p.positions as Record<string, number>)
        .then((r) => [p.id, r.conflicts] as const).catch(() => [p.id, [] as PositionConflict[]] as const)
    )).then((pairs) => { if (!cancelled) setConflictsByPos(Object.fromEntries(pairs)); });
    return () => { cancelled = true; };
  }, [positionsLib, activeRid]);

  const selectedPosition = useMemo(
    () => positionsLib.find((p) => p.id === selectedPosId) ?? null,
    [positionsLib, selectedPosId]
  );

  const onCreateSuite = async () => {
    const name = window.prompt("Nom de la nouvelle suite :", `Suite_${suites.length + 1}`);
    if (!name) return;
    try {
      await cmdCreateSuite(name);
      refetchLibrary();
    } catch (e) {
      setActionError(`suite: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onCreateFolder = async () => {
    const name = window.prompt("Nom du dossier :", `Dossier_${suites.filter((s) => (s.meta as { is_folder?: boolean })?.is_folder).length + 1}`);
    if (!name) return;
    try {
      await cmdCreateSuite(name, [], { is_folder: true });
      refetchLibrary();
    } catch (e) {
      setActionError(`folder: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onMoveSuiteToFolder = async (suiteId: string, folderName: string | null) => {
    const suite = suites.find((s) => s.id === suiteId);
    if (!suite) return;
    const newMeta = { ...(suite.meta || {}) };
    if (folderName) (newMeta as { parent_folder?: string }).parent_folder = folderName;
    else delete (newMeta as { parent_folder?: string }).parent_folder;
    try {
      await cmdUpdateSuite(suiteId, { meta: newMeta });
      refetchLibrary();
    } catch (e) {
      setActionError(`move: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onSavePosition = async () => {
    if (!activeRid) return;
    const robot = robots.find((r) => r.id === activeRid);
    if (!robot?.connected) {
      setActionError("Robot non connecte"); return;
    }
    const name = window.prompt(
      `Nom de la position depuis ${activeRid} :`,
      `pos_${new Date().toISOString().slice(11, 19).replace(/:/g, "")}`
    );
    if (!name) return;
    try {
      await cmdCapture(activeRid, name);
      refetchLibrary();
    } catch (e) {
      setActionError(`capture: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onDeleteSuite = async (sid: string) => {
    if (!window.confirm("Supprimer cette suite ? (les positions ne sont pas supprimées)")) return;
    try {
      await cmdDeleteSuite(sid);
      refetchLibrary();
    } catch (e) {
      setActionError(`delete suite: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const onDeletePos = async () => {
    if (!selectedPosId) return;
    if (!window.confirm("Supprimer la position selectionnee ?")) return;
    try {
      await cmdDeletePosition(selectedPosId);
      setSelectedPosId(null);
      refetchLibrary();
    } catch (e) {
      setActionError(`delete pos: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Toolbar haute */}
      <div className="flex items-center justify-end gap-2 flex-wrap">
        <ToolbarBtn onClick={refetchLibrary}>🔄 Rafraîchir</ToolbarBtn>
        <ToolbarBtn onClick={() => setWizardOpen(true)}>
          🎬 Créer suite pas à pas
        </ToolbarBtn>
        <ToolbarBtn onClick={onCreateSuite}>➕ Suite</ToolbarBtn>
        <ToolbarBtn onClick={onCreateFolder}>
          📁 Dossier
        </ToolbarBtn>
        <ToolbarBtn primary onClick={onSavePosition}>
          💾 Enregistrer position
        </ToolbarBtn>
      </div>

      {/* 2 colonnes : arborescence | panneau robot */}
      <div className="grid grid-cols-2 gap-3 flex-1 min-h-0">
        <div className="flex flex-col min-h-0">
          <div className="font-ui text-section text-text mb-1">Suites et Positions</div>
          <div className="flex-1 min-h-0">
            <PositionsTree
              suites={suites}
              positionsLib={positionsLib}
              selected={selectedPosId}
              onSelect={setSelectedPosId}
              onDeleteSuite={onDeleteSuite}
              onMoveSuiteToFolder={onMoveSuiteToFolder}
              conflictsByPos={conflictsByPos}
              onDoubleClickPos={setEditingPos}
            />
          </div>
          {/* Boutons bas (Dupliquer / Supprimer pose / Dupliquer suite / Supprimer suite) */}
          <div className="flex gap-2 mt-2">
            <ToolbarBtn onClick={() => setActionError("Dupliquer position : à porter")}
                        disabled={!selectedPosId}>
              📋 Dupliquer
            </ToolbarBtn>
            <ToolbarBtn onClick={onDeletePos} disabled={!selectedPosId}>
              🗑
            </ToolbarBtn>
          </div>
        </div>

        <div className="min-h-0">
          <PositionPanel
            selectedPosition={selectedPosition}
            robots={robots}
            activeRid={activeRid}
            onSetRid={setActiveRid}
            onSavePosition={onSavePosition}
          />
        </div>
      </div>

      {/* Wizard pas a pas */}
      {wizardOpen && (
        <WizardSuite
          onClose={() => setWizardOpen(false)}
          onSuiteCreated={refetchLibrary}
        />
      )}

      {/* Modal édition position */}
      {editingPos && (
        <PositionEditorModal
          positionId={editingPos.id}
          name={editingPos.name}
          robot={activeRobot}
          initial={editingPos.positions as Record<string, number>}
          onClose={() => setEditingPos(null)}
          onSaved={() => { refetchLibrary(); }}
        />
      )}
    </div>
  );
}
