// Page Timeline — fidele a xrv22/ui/timeline_panel.py.
// Layout :
//   Bar haute : Scenarios combo + Lecture/Stop (droite)
//   Toolbar evenements : Ajouter Pose / Pause / Capteur Arduino / Action Arduino /
//                        Importer Suite / Modifier / Supprimer / Exporter
//   Body : pistes par robot avec label coloré + zone temporelle
//   Curseur magenta vertical pour position de lecture
//   Footer : zoom

import { memo, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../store";
import { useActiveRobot } from "../liveAxes";
import { authFetch } from "../auth";
import { cmdScenarioPlay, cmdScenarioStop } from "../commands";
import { colorForRobot } from "../theme";
import type { SuiteRec, PositionRec } from "../types";
import { Modal, ModalBtn } from "../components/Modal";
import { EventEditorModal, maybeUpdateLibrary } from "../timeline/EventEditorModal";
import { updateEventPositions } from "../timeline/eventEdit";

type Track = {
  track_id: string;
  track_type: "ROBOT" | "ARDUINO" | "SENSOR" | string;
  label: string;
  color: string;
  robot_id: string;
  visible?: boolean;
  muted?: boolean;
  events: Array<{
    event_id: string;
    event_type: string;
    start_ms: number;
    duration_ms?: number;
    label?: string;
    [k: string]: unknown;
  }>;
};

type ScenarioFull = {
  id: string;
  name: string;
  timeline_data: {
    track_order?: string[];
    tracks?: Track[];
    total_duration_ms?: number | null;
  };
};

function ToolbarBtn({
  children, onClick, primary, danger, disabled, busy, title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
  busy?: boolean;
  title?: string;
}) {
  const tone = danger
    ? "bg-err_dim text-err border-err/40 hover:bg-err_deep"
    : primary
    ? "bg-mag_dim2 text-amb border-mag/50 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={busy || disabled} title={title}
            className={`px-3 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30 ${tone}`}>
      {busy ? "…" : children}
    </button>
  );
}

// Largeur visible de la zone temporelle (px). 1ms = (zoom/100) px.
const TRACK_LABEL_W = 140;
const TRACK_H = 60;
const HEADER_H = 36;

// Compteur temps reel isole pour le footer (sinon le footer + tout son entourage
// re-render a chaque engine.tick 20Hz).
function ElapsedCounter({ totalMs }: { totalMs: number }) {
  const elapsedMs = useStore().engineElapsedMs;
  return (
    <span className="text-amb">
      ⏱ {(elapsedMs / 1000).toFixed(2)}s / {(totalMs / 1000).toFixed(1)}s
    </span>
  );
}

// Playhead isole : seul composant qui re-render a chaque engine.tick (20Hz).
// Le reste de Timeline ne re-render que sur changements de scenarios/tracks.
function Playhead({ pxPerMs, visible }: { pxPerMs: number; visible: boolean }) {
  const elapsedMs = useStore().engineElapsedMs;
  if (!visible) return null;
  return (
    <div className="absolute top-0 bottom-0 pointer-events-none z-30"
         style={{
           left: TRACK_LABEL_W + elapsedMs * pxPerMs,
           width: 2,
           background: "#80276c",
           boxShadow: "0 0 4px #80276c",
         }}>
      <div className="absolute -top-1 -left-1.5 w-4 h-4 rounded-full"
           style={{ background: "#80276c", boxShadow: "0 0 6px #80276c" }} />
      <div className="absolute -top-5 left-3 px-1.5 py-0.5 rounded font-mono text-[10px] text-amb bg-bg/90 border border-mag whitespace-nowrap">
        {(elapsedMs / 1000).toFixed(2)}s
      </div>
    </div>
  );
}

const TrackLabel = memo(function TrackLabel({ track }: { track: Track }) {
  return (
    <div
      className="shrink-0 flex items-center px-3 border-r border-border"
      style={{
        width: TRACK_LABEL_W,
        height: TRACK_H,
        background: `${track.color}22`,
        borderLeft: `4px solid ${track.color}`,
      }}
    >
      <span className="font-ui text-control text-text truncate" style={{ color: track.color }}>
        {track.label}
      </span>
    </div>
  );
});

const TimelineBlock = memo(function TimelineBlock({ event, color, pxPerMs, selected, onClick, onDragMove, onDoubleClick }: {
  event: Track["events"][number];
  color: string;
  pxPerMs: number;
  selected: boolean;
  onClick: (modifiers: { meta: boolean; shift: boolean }) => void;
  onDragMove: (newStartMs: number) => void;
  onDoubleClick: () => void;
}) {
  const w = Math.max(24, (event.duration_ms ?? 1000) * pxPerMs);
  const x = event.start_ms * pxPerMs;
  const [tempStartMs, setTempStartMs] = useState<number | null>(null);
  // Refs pour stabiliser les handlers window (pas de stale closure)
  const onClickRef = useRef(onClick);
  onClickRef.current = onClick;
  const onDragMoveRef = useRef(onDragMove);
  onDragMoveRef.current = onDragMove;
  const tempRef = useRef<number | null>(null);
  tempRef.current = tempStartMs;
  const startMsRef = useRef(event.start_ms);
  startMsRef.current = event.start_ms;

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    const startClientX = e.clientX;
    const startMsCaptured = event.start_ms;
    let moved = false;
    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - startClientX;
      if (Math.abs(dx) < 3) return;  // Seuil 3px : evite drag involontaire au clic
      moved = true;
      const newStart = Math.max(0, Math.round(startMsCaptured + dx / pxPerMs));
      tempRef.current = newStart;
      setTempStartMs(newStart);
    };
    const onUp = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      const finalStart = tempRef.current;
      tempRef.current = null;
      setTempStartMs(null);
      if (moved && finalStart !== null && finalStart !== startMsRef.current) {
        onDragMoveRef.current(finalStart);
      } else {
        // Pas de mouvement = clic avec modifiers
        onClickRef.current({ meta: ev.metaKey || ev.ctrlKey, shift: ev.shiftKey });
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };

  const renderX = tempStartMs !== null ? tempStartMs * pxPerMs : x;
  return (
    <div
      onPointerDown={onPointerDown}
      onDoubleClick={onDoubleClick}
      className={`absolute top-1 bottom-1 rounded border flex items-center px-1.5 text-[10px] font-ui truncate cursor-grab active:cursor-grabbing select-none ${
        selected ? "ring-2 ring-amb z-10" : "hover:brightness-110"
      } ${tempStartMs !== null ? "opacity-80 z-20" : ""}`}
      style={{
        left: renderX, width: w,
        background: `${color}66`,
        borderColor: color,
        color: "#fff",
      }}
      title={`${event.event_type} @ ${event.start_ms}ms · ${event.duration_ms}ms\nClic = sélection · Cmd+clic = multi · Shift+clic = toute la suite · Suppr = supprimer · Drag = déplacer`}
    >
      {(event.label as string) || event.event_type}
    </div>
  );
});

const TrackBody = memo(function TrackBody({ track, durationMs, zoom, selectedIds, onSelectEvent, onDragMoveEvent, onEditEvent }: {
  track: Track; durationMs: number; zoom: number;
  selectedIds: Set<string>;
  onSelectEvent: (id: string, modifiers: { meta: boolean; shift: boolean }) => void;
  onDragMoveEvent: (eventId: string, newStartMs: number) => void;
  onEditEvent: (id: string) => void;
}) {
  const pxPerMs = zoom / 100 * 0.05;  // 100% = 50px/s
  const widthPx = Math.max(800, durationMs * pxPerMs);
  return (
    <div
      className="relative border-b border-border"
      style={{ height: TRACK_H, width: widthPx, background: "#1e2130" }}
    >
      {Array.from({ length: Math.ceil(durationMs / 1000) }, (_, i) => (
        <div key={i} className="absolute top-0 bottom-0 w-px bg-border"
             style={{ left: i * 1000 * pxPerMs }} />
      ))}
      {(track.events ?? []).map((e) => (
        <TimelineBlock key={e.event_id} event={e} color={track.color} pxPerMs={pxPerMs}
                       selected={selectedIds.has(e.event_id)}
                       onClick={(mods) => onSelectEvent(e.event_id, mods)}
                       onDragMove={(newStart) => onDragMoveEvent(e.event_id, newStart)}
                       onDoubleClick={() => onEditEvent(e.event_id)} />
      ))}
    </div>
  );
});

const TimelineHeader = memo(function TimelineHeader({ durationMs, zoom }: { durationMs: number; zoom: number }) {
  const pxPerMs = zoom / 100 * 0.05;
  const widthPx = Math.max(800, durationMs * pxPerMs);
  const stepMs = zoom >= 100 ? 1000 : zoom >= 50 ? 2000 : 5000;
  return (
    <div className="relative border-b border-border" style={{ height: HEADER_H, width: widthPx }}>
      {Array.from({ length: Math.ceil(durationMs / stepMs) + 1 }, (_, i) => {
        const t = i * stepMs;
        return (
          <div key={i} className="absolute top-0 bottom-0 flex items-end pb-1"
               style={{ left: t * pxPerMs }}>
            <span className="text-[10px] font-mono text-text_dim border-l border-border pl-1">
              {(t / 1000).toFixed(0)}s
            </span>
          </div>
        );
      })}
    </div>
  );
});

// ── Dialog Importer Suite ────────────────────────────────────────

function ImportSuiteDialog({
  suites, robots, activeRid, onClose, onImport,
}: {
  suites: SuiteRec[];
  robots: ReturnType<typeof useStore>["robots"];
  activeRid: string;
  onClose: () => void;
  onImport: (suite: SuiteRec, robotId: string, durationS: number) => void;
}) {
  const [selectedSid, setSelectedSid] = useState<string>(suites[0]?.id ?? "");
  const [robotId, setRobotId] = useState<string>(activeRid || robots[0]?.id || "");
  const [durationS, setDurationS] = useState<number>(2.0);

  const selected = suites.find((s) => s.id === selectedSid);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg_deep/80"
         onClick={onClose}>
      <div className="bg-surface border border-border_hi rounded-md w-[640px] max-h-[80vh] flex flex-col shadow-2xl"
           onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="px-4 py-3 border-b border-border bg-surface_hi rounded-t-md flex items-center justify-between">
          <span className="font-display text-section text-amb">📥 Importer une suite</span>
          <button type="button" onClick={onClose}
                  className="text-text_med hover:text-text">✕</button>
        </div>

        {/* Body : liste suites + parametres */}
        <div className="flex-1 overflow-auto p-4 space-y-4">
          {/* Selection robot */}
          <div>
            <label className="font-ui text-control text-text_med block mb-1">
              Robot cible :
            </label>
            <select value={robotId} onChange={(e) => setRobotId(e.target.value)}
                    className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb">
              {robots.map((r) => (
                <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
              ))}
            </select>
            {robotId && (
              <div className="flex items-center gap-2 mt-1.5">
                <span className="w-3 h-3 rounded-full" style={{ background: colorForRobot(robotId) }} />
                <span className="font-ui text-caption text-text_med">
                  Couleur de la piste : {colorForRobot(robotId)}
                </span>
              </div>
            )}
          </div>

          {/* Duree par etape */}
          <div>
            <label className="font-ui text-control text-text_med block mb-1">
              Durée par étape (s) :
            </label>
            <input type="number" step="0.1" min="0.1" max="30" value={durationS}
                   onChange={(e) => setDurationS(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>

          {/* Liste suites */}
          <div>
            <label className="font-ui text-control text-text_med block mb-1">
              Suite à importer ({suites.length} disponibles) :
            </label>
            <div className="bg-bg border border-border rounded-sm max-h-64 overflow-auto">
              {suites.length === 0 ? (
                <div className="text-text_dim text-center py-6 font-ui text-control">
                  Aucune suite — créez-en une depuis l'onglet Positions & Suites
                </div>
              ) : suites.map((s) => (
                <button key={s.id}
                        type="button"
                        onClick={() => setSelectedSid(s.id)}
                        className={`w-full flex items-center gap-3 px-3 py-2 text-left transition ${
                          selectedSid === s.id
                            ? "bg-amb_dim2/40 border-l-2 border-amb"
                            : "hover:bg-surface_hi/60 border-l-2 border-transparent"
                        }`}>
                  <span className="text-text_med">📁</span>
                  <span className="font-ui text-control text-text flex-1 truncate">
                    {s.name}
                  </span>
                  <span className="font-mono text-mono_sm text-text_dim">
                    {s.steps?.length ?? 0} étapes
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Apercu duree totale */}
          {selected && (
            <div className="bg-bg p-3 rounded-sm border border-border">
              <div className="font-ui text-caption text-text_med mb-1">Aperçu :</div>
              <div className="font-mono text-mono_md text-text">
                {selected.name} · {selected.steps?.length ?? 0} étapes
                · ~{((selected.steps?.length ?? 0) * durationS).toFixed(1)}s
              </div>
            </div>
          )}
        </div>

        {/* Footer : actions */}
        <div className="px-4 py-3 border-t border-border bg-surface_hi rounded-b-md flex items-center justify-end gap-2">
          <button type="button" onClick={onClose}
                  className="px-4 py-1.5 rounded-sm border border-border_hi bg-surface_hi hover:bg-mag_dim2 font-ui text-control text-text">
            Annuler
          </button>
          <button type="button"
                  disabled={!selected || !robotId}
                  onClick={() => selected && onImport(selected, robotId, durationS)}
                  className="px-4 py-1.5 rounded-sm border border-mag/50 bg-mag_dim2 hover:bg-mag font-ui text-control text-amb disabled:opacity-30">
            ✓ Importer
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Dialog Ajouter Pose ──────────────────────────────────────────

// IDs reserves pour les positions speciales (home machine/travail du robot actif)
export const SPECIAL_POS_MACHINE = "__home_machine";
export const SPECIAL_POS_TRAVAIL = "__home_work";

function AddPoseDialog({
  positionsLib, robots, activeRid, onClose, onAdd,
}: {
  positionsLib: PositionRec[];
  robots: ReturnType<typeof useStore>["robots"];
  activeRid: string;
  onClose: () => void;
  onAdd: (positionId: string, robotId: string, durationS: number) => void;
}) {
  const [robotId, setRobotId] = useState<string>(activeRid || robots[0]?.id || "");
  const [posId, setPosId] = useState<string>(SPECIAL_POS_TRAVAIL);
  const [durationS, setDurationS] = useState(2.0);
  const [search, setSearch] = useState("");
  const filtered = positionsLib.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );
  const robot = robots.find((r) => r.id === robotId);
  const hasMachine = robot && Object.keys(robot.home_machine ?? {}).length > 0;
  const hasWork = robot && Object.keys(robot.home_work ?? {}).length > 0;

  return (
    <Modal title="➕ Ajouter une pose" onClose={onClose} width={620}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!posId || !robotId}
                       onClick={() => onAdd(posId, robotId, durationS)}>
               ✓ Ajouter
             </ModalBtn>
           </>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Robot :</label>
            <select value={robotId} onChange={(e) => setRobotId(e.target.value)}
                    className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb">
              {robots.map((r) => (
                <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Durée (s) :</label>
            <input type="number" step="0.1" min="0.1" value={durationS}
                   onChange={(e) => setDurationS(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>
        </div>
        <input type="text" value={search} onChange={(e) => setSearch(e.target.value)}
               placeholder="Rechercher une position…"
               className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb" />
        <div className="bg-bg border border-border rounded-sm max-h-64 overflow-auto">
          {/* Positions speciales du robot (en tete, accent ambre) */}
          {hasWork && (
            <button type="button"
                    onClick={() => setPosId(SPECIAL_POS_TRAVAIL)}
                    className={`w-full flex items-center gap-3 px-3 py-1.5 text-left transition border-b border-border ${
                      posId === SPECIAL_POS_TRAVAIL
                        ? "bg-amb_dim2/40 border-l-2 border-l-amb"
                        : "hover:bg-surface_hi/60 border-l-2 border-l-transparent"
                    }`}>
              <span className="text-ok">🔧</span>
              <span className="font-ui text-control text-amb flex-1">Pos. travail</span>
              <span className="font-mono text-mono_sm text-text_dim">{robotId}</span>
            </button>
          )}
          {hasMachine && (
            <button type="button"
                    onClick={() => setPosId(SPECIAL_POS_MACHINE)}
                    className={`w-full flex items-center gap-3 px-3 py-1.5 text-left transition border-b border-border ${
                      posId === SPECIAL_POS_MACHINE
                        ? "bg-amb_dim2/40 border-l-2 border-l-amb"
                        : "hover:bg-surface_hi/60 border-l-2 border-l-transparent"
                    }`}>
              <span className="text-amb">🏠</span>
              <span className="font-ui text-control text-amb flex-1">Pos. machine</span>
              <span className="font-mono text-mono_sm text-text_dim">{robotId}</span>
            </button>
          )}

          {/* Positions library */}
          {filtered.length === 0 ? (
            <div className="text-text_dim text-center py-6 font-ui text-control">Aucune position</div>
          ) : filtered.map((p) => (
            <button key={p.id} type="button"
                    onClick={() => setPosId(p.id)}
                    className={`w-full flex items-center gap-3 px-3 py-1.5 text-left transition ${
                      posId === p.id
                        ? "bg-amb_dim2/40 border-l-2 border-amb"
                        : "hover:bg-surface_hi/60 border-l-2 border-transparent"
                    }`}>
              <span className="text-text_med">●</span>
              <span className="font-ui text-control text-text flex-1 truncate">{p.name}</span>
              <span className="font-mono text-mono_sm text-text_dim">{p.category}</span>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  );
}

// ── Dialog Ajouter Pause / Capteur / Action ──────────────────────

function SimpleEventDialog({
  title, eventType, onClose, onAdd, fields,
}: {
  title: string;
  eventType: string;
  onClose: () => void;
  onAdd: (params: Record<string, unknown>) => void;
  fields: { key: string; label: string; type: "number" | "text"; default: string | number; hint?: string }[];
}) {
  const [values, setValues] = useState<Record<string, string | number>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, f.default]))
  );

  return (
    <Modal title={title} onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary onClick={() => onAdd({ event_type: eventType, ...values })}>
               ✓ Ajouter
             </ModalBtn>
           </>}>
      <div className="space-y-3">
        {fields.map((f) => (
          <div key={f.key}>
            <label className="font-ui text-control text-text_med block mb-1">{f.label} :</label>
            <input type={f.type}
                   value={values[f.key]}
                   onChange={(e) => setValues((v) => ({ ...v, [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value }))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
            {f.hint && <p className="font-mono text-mono_sm text-text_dim mt-1">{f.hint}</p>}
          </div>
        ))}
      </div>
    </Modal>
  );
}

// ── Dialog Modifier event ────────────────────────────────────────

function ModifyEventDialog({
  event, onClose, onUpdate,
}: {
  event: Track["events"][number];
  onClose: () => void;
  onUpdate: (patch: Partial<Track["events"][number]>) => void;
}) {
  const [label, setLabel] = useState((event.label as string) || "");
  const [startMs, setStartMs] = useState(event.start_ms);
  const [durationMs, setDurationMs] = useState(event.duration_ms ?? 1000);

  return (
    <Modal title="✏ Modifier l'événement" onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary onClick={() => onUpdate({ label, start_ms: startMs, duration_ms: durationMs })}>
               ✓ Appliquer
             </ModalBtn>
           </>}>
      <div className="space-y-3">
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Type :</label>
          <input value={event.event_type} disabled
                 className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text_dim" />
        </div>
        <div>
          <label className="font-ui text-control text-text_med block mb-1">Libellé :</label>
          <input type="text" value={label} onChange={(e) => setLabel(e.target.value)}
                 className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Début (ms) :</label>
            <input type="number" min="0" value={startMs}
                   onChange={(e) => setStartMs(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>
          <div>
            <label className="font-ui text-control text-text_med block mb-1">Durée (ms) :</label>
            <input type="number" min="50" value={durationMs}
                   onChange={(e) => setDurationMs(Number(e.target.value))}
                   className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
          </div>
        </div>
      </div>
    </Modal>
  );
}

export default function Timeline() {
  // IMPORTANT : ne PAS lire engineElapsedMs ici — il change a 20Hz pendant la
  // lecture et causerait un re-render complet de la Timeline 20x/seconde.
  // Les composants <Playhead> et <ElapsedCounter> le lisent eux-memes.
  const { scenarios, robots, suites, positionsLib, engineState, setActionError } = useStore();
  const { activeRid } = useActiveRobot();
  const [activeSid, setActiveSid] = useState<string>("");
  const [scenarioFull, setScenarioFull] = useState<ScenarioFull | null>(null);
  const [zoom, setZoom] = useState(100);
  const [busy, setBusy] = useState<string | null>(null);
  const [importDlg, setImportDlg] = useState(false);
  const [addPoseDlg, setAddPoseDlg] = useState(false);
  const [simpleEvtDlg, setSimpleEvtDlg] = useState<null | "pause" | "sensor" | "arduino">(null);
  const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set());
  const [modifyDlg, setModifyDlg] = useState(false);
  const [editingEventId, setEditingEventId] = useState<string | null>(null);
  // Helper retro-compat : 1er event selectionne (utilise par dialog Modifier)
  const selectedEventId = selectedEventIds.size > 0 ? Array.from(selectedEventIds)[0] : null;
  const playing = engineState === "RUNNING" || engineState === "PAUSED";

  useEffect(() => {
    if (!activeSid && scenarios.length > 0) setActiveSid(scenarios[0].id);
  }, [scenarios, activeSid]);

  // Recharge le scenario complet (avec tracks) quand selection change
  useEffect(() => {
    if (!activeSid) { setScenarioFull(null); return; }
    authFetch("/api/scenarios").then((r) => r.json()).then((arr: ScenarioFull[]) => {
      const sf = arr.find((s) => s.id === activeSid) ?? null;
      setScenarioFull(sf);
    }).catch(() => setScenarioFull(null));
  }, [activeSid]);

  // Filtre les pistes ROBOT pour n'afficher que celles dont le robot existe
  // dans le registry. Les scenarios anciens (BRIOCHE par ex.) peuvent contenir
  // des pistes "fantomes" pour des robots qui n'existent plus (robot_4/5).
  // Les pistes ARDUINO/SENSOR sont gardees (pas de robot_id).
  const robotIds = useMemo(() => new Set(robots.map((r) => r.id)), [robots]);
  const tracks = useMemo<Track[]>(() => {
    if (!scenarioFull?.timeline_data?.tracks) return [];
    const order = scenarioFull.timeline_data.track_order ?? [];
    const byId = new Map(scenarioFull.timeline_data.tracks.map((t) => [t.track_id, t]));
    return order
      .map((id) => byId.get(id))
      .filter((t): t is Track => !!t)
      .filter((t) => t.track_type !== "ROBOT" || robotIds.has(t.robot_id));
  }, [scenarioFull, robotIds]);

  const hiddenTracks = useMemo(() => {
    if (!scenarioFull?.timeline_data?.tracks) return [];
    return scenarioFull.timeline_data.tracks.filter(
      (t) => t.track_type === "ROBOT" && !robotIds.has(t.robot_id)
    );
  }, [scenarioFull, robotIds]);

  const durationMs = useMemo(() => {
    let max = 30000;
    for (const t of tracks)
      for (const e of t.events ?? [])
        max = Math.max(max, e.start_ms + (e.duration_ms ?? 0));
    return Math.ceil(max / 1000) * 1000;
  }, [tracks]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try { await fn(); } catch (e) {
      setActionError(`scenario: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(null); }
  };

  const reloadScenario = async () => {
    if (!activeSid) return;
    const arr: ScenarioFull[] = await authFetch("/api/scenarios").then((r) => r.json());
    setScenarioFull(arr.find((s) => s.id === activeSid) ?? null);
  };

  // Persistance helper : POST timeline_data complet
  const persistTimeline = async (td: ScenarioFull["timeline_data"]) => {
    if (!scenarioFull) return;
    const res = await authFetch(`/api/scenarios/${scenarioFull.id}/timeline_data`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timeline_data: td }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    await reloadScenario();
  };

  // Trouve l'event selectionne dans toutes les pistes
  const selectedEvent = useMemo(() => {
    if (!selectedEventId || !scenarioFull) return null;
    for (const t of scenarioFull.timeline_data?.tracks ?? []) {
      const e = (t.events ?? []).find((x) => x.event_id === selectedEventId);
      if (e) return { event: e, track: t };
    }
    return null;
  }, [selectedEventId, scenarioFull]);

  const editingEvent = (scenarioFull?.timeline_data?.tracks ?? [])
    .flatMap((t) => t.events ?? []).find((e) => e.event_id === editingEventId) ?? null;
  const editingTrack = (scenarioFull?.timeline_data?.tracks ?? [])
    .find((t) => (t.events ?? []).some((e) => e.event_id === editingEventId)) ?? null;
  const editingRobot = robots.find((r) => r.id === (editingTrack?.robot_id
    ?? (editingEvent?.parameters as any)?.robot_id));

  const onSaveEvent = async (patch: { positions: Record<string, number>;
    duration_ms: number; speed_pct: number; updateLibrary: boolean; positionId?: string }) => {
    if (!scenarioFull || !editingEventId) return;
    const td = updateEventPositions(scenarioFull.timeline_data, editingEventId, patch) as ScenarioFull["timeline_data"];
    try {
      await persistTimeline(td);
      setScenarioFull({ ...scenarioFull, timeline_data: td });
      await maybeUpdateLibrary(patch);
    } catch (e) {
      setActionError(`édition: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setEditingEventId(null);
    }
  };

  const onAddPose = async (positionId: string, robotId: string, durationS: number) => {
    if (!scenarioFull) return;
    const td = scenarioFull.timeline_data;
    const tracks = (td.tracks ?? []) as Track[];
    const trackId = `track_${robotId}`;
    let track = tracks.find((t) => t.track_id === trackId);
    if (!track) {
      track = { track_id: trackId, track_type: "ROBOT",
                label: `Robot ${robotId}`, color: colorForRobot(robotId),
                robot_id: robotId, events: [] };
      tracks.push(track);
      const order = (td.track_order ?? []).slice();
      if (!order.includes(trackId)) order.push(trackId);
      td.track_order = order;
    }
    let startMs = 0;
    for (const ev of track.events ?? []) {
      const end = ev.start_ms + (ev.duration_ms ?? 0);
      if (end > startMs) startMs = end;
    }
    // Resolution des positions speciales (Pos. machine / travail du robot)
    const robot = robots.find((r) => r.id === robotId);
    let positions: Record<string, number> = {};
    let label = "MOVE";
    let displayId = positionId;
    if (positionId === SPECIAL_POS_MACHINE) {
      positions = robot?.home_machine ?? {};
      label = `🏠 Pos. machine ${robotId}`;
      displayId = "";
    } else if (positionId === SPECIAL_POS_TRAVAIL) {
      positions = robot?.home_work ?? {};
      label = `🔧 Pos. travail ${robotId}`;
      displayId = "";
    } else {
      const pos = positionsLib.find((p) => p.id === positionId);
      positions = pos?.positions ?? {};
      label = pos?.name || "MOVE";
    }
    track.events!.push({
      event_id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      event_type: "MOVE",
      track_id: trackId,
      start_ms: startMs,
      duration_ms: Math.round(durationS * 1000),
      label,
      parameters: {
        positions,
        duration_s: durationS,
        speed_pct: 100,
        robot_id: robotId,
        position_id: displayId,
        position_name: label,
      },
    } as Track["events"][number]);
    td.tracks = tracks;
    try { await persistTimeline(td); setAddPoseDlg(false); }
    catch (e) { setActionError(`add pose: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const onModifyEvent = async (patch: Partial<Track["events"][number]>) => {
    if (!scenarioFull || !selectedEvent) return;
    const td = scenarioFull.timeline_data;
    for (const t of td.tracks ?? []) {
      const idx = (t.events ?? []).findIndex((e) => e.event_id === selectedEvent.event.event_id);
      if (idx >= 0) {
        t.events![idx] = { ...t.events![idx], ...patch };
        break;
      }
    }
    try { await persistTimeline(td); setModifyDlg(false); }
    catch (e) { setActionError(`modify: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const onDragMoveEvent = async (eventId: string, newStartMs: number) => {
    if (!scenarioFull) return;
    const td = scenarioFull.timeline_data;
    let changed = false;
    for (const t of td.tracks ?? []) {
      const idx = (t.events ?? []).findIndex((e) => e.event_id === eventId);
      if (idx >= 0) {
        t.events![idx] = { ...t.events![idx], start_ms: Math.max(0, newStartMs) };
        changed = true; break;
      }
    }
    if (!changed) return;
    try { await persistTimeline(td); }
    catch (e) { setActionError(`drag: ${e instanceof Error ? e.message : String(e)}`); }
  };

  // Selection avec modifiers (Cmd/Ctrl=multi, Shift=toute la suite)
  const onSelectEvent = (eventId: string,
                         modifiers: { meta: boolean; shift: boolean }) => {
    if (modifiers.shift) {
      // Sélectionne tous les events du même groupe (suite_group_id)
      const allEvents = (scenarioFull?.timeline_data?.tracks ?? [])
        .flatMap((t) => t.events ?? []);
      const target = allEvents.find((e) => e.event_id === eventId);
      const groupId = target?.suite_group_id;
      if (groupId) {
        const groupIds = allEvents
          .filter((e) => e.suite_group_id === groupId)
          .map((e) => e.event_id);
        setSelectedEventIds(new Set(groupIds));
      } else {
        setSelectedEventIds(new Set([eventId]));
      }
      return;
    }
    if (modifiers.meta) {
      // Toggle dans la sélection
      setSelectedEventIds((cur) => {
        const next = new Set(cur);
        next.has(eventId) ? next.delete(eventId) : next.add(eventId);
        return next;
      });
      return;
    }
    // Clic simple : sélection unique
    setSelectedEventIds(new Set([eventId]));
  };

  const onDeleteEvent = async () => {
    if (!scenarioFull || selectedEventIds.size === 0) return;
    const n = selectedEventIds.size;
    const msg = n === 1
      ? `Supprimer l'événement sélectionné ?`
      : `Supprimer les ${n} événements sélectionnés ?`;
    if (!window.confirm(msg)) return;
    const td = scenarioFull.timeline_data;
    for (const t of td.tracks ?? []) {
      t.events = (t.events ?? []).filter((e) => !selectedEventIds.has(e.event_id));
    }
    try { await persistTimeline(td); setSelectedEventIds(new Set()); }
    catch (e) { setActionError(`delete: ${e instanceof Error ? e.message : String(e)}`); }
  };

  // Raccourci clavier Suppr/Delete = supprime la sélection
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (tgt.tagName === "INPUT" || tgt.tagName === "TEXTAREA" ||
          tgt.tagName === "SELECT" || tgt.isContentEditable) return;
      if ((e.key === "Delete" || e.key === "Backspace") && selectedEventIds.size > 0) {
        e.preventDefault();
        onDeleteEvent();
      } else if (e.key === "Escape") {
        setSelectedEventIds(new Set());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedEventIds, scenarioFull]);

  const onAddSimpleEvent = async (params: Record<string, unknown>) => {
    if (!scenarioFull) return;
    const td = scenarioFull.timeline_data;
    const tracks = (td.tracks ?? []) as Track[];
    const eventType = params.event_type as string;
    // Trouve la piste cible : ARDUINO/SENSOR pour evenements globaux
    const targetTrackType = (eventType === "PAUSE" || eventType === "WAIT")
      ? "ROBOT" : (eventType === "SENSOR_WAIT" ? "SENSOR" : "ARDUINO");
    let track = tracks.find((t) => t.track_type === targetTrackType);
    if (!track) {
      setActionError(`Aucune piste ${targetTrackType} dans ce scénario`);
      return;
    }
    let startMs = 0;
    for (const ev of track.events ?? []) {
      const end = ev.start_ms + (ev.duration_ms ?? 0);
      if (end > startMs) startMs = end;
    }
    track.events!.push({
      event_id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      event_type: eventType,
      track_id: track.track_id,
      start_ms: startMs,
      duration_ms: Number(params.duration_ms ?? 1000),
      label: String(params.label || eventType),
      ...params,
    } as Track["events"][number]);
    td.tracks = tracks;
    try { await persistTimeline(td); setSimpleEvtDlg(null); }
    catch (e) { setActionError(`add event: ${e instanceof Error ? e.message : String(e)}`); }
  };

  const onExportTimeline = () => {
    if (!scenarioFull) return;
    const blob = new Blob([JSON.stringify(scenarioFull.timeline_data, null, 2)],
                          { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${scenarioFull.name}_timeline.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const onImportSuite = async (suite: SuiteRec, robotId: string, durationS: number) => {
    if (!scenarioFull) {
      setActionError("Selectionne un scenario d'abord"); return;
    }
    const td = scenarioFull.timeline_data;
    const tracks = (td.tracks ?? []) as Track[];
    // Cree la piste robot si elle n'existe pas
    const trackId = `track_${robotId}`;
    let track = tracks.find((t) => t.track_id === trackId);
    if (!track) {
      track = {
        track_id: trackId,
        track_type: "ROBOT",
        label: `Robot ${robotId}`,
        color: colorForRobot(robotId),
        robot_id: robotId,
        events: [],
      };
      tracks.push(track);
      const order = (td.track_order ?? []).slice();
      if (!order.includes(trackId)) order.push(trackId);
      td.track_order = order;
    }
    // Calcul du start_ms : apres le dernier event de cette piste
    let startMs = 0;
    for (const ev of track.events ?? []) {
      const end = ev.start_ms + (ev.duration_ms ?? 0);
      if (end > startMs) startMs = end;
    }
    // Genere un event MOVE par etape de la suite. IMPORTANT : positions/duration_s
    // doivent etre dans `parameters` (lu par _handle_move via evt.get_param()).
    for (const step of suite.steps ?? []) {
      const dur = Math.round((step.duration_s ?? durationS) * 1000);
      const durS = dur / 1000;
      const posRec = positionsLib.find((p) => p.id === step.position_id);
      track.events!.push({
        event_id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        event_type: "MOVE",
        track_id: trackId,
        start_ms: startMs,
        duration_ms: dur,
        label: step.position_name || "MOVE",
        suite_group_id: suite.id,
        parameters: {
          positions: posRec?.positions ?? {},
          duration_s: durS,
          speed_pct: 100,
          robot_id: robotId,
          position_id: step.position_id,
          position_name: step.position_name,
        },
      } as Track["events"][number]);
      startMs += dur + Math.round((step.pause_s ?? 0) * 1000);
    }
    td.tracks = tracks;

    // Persist via PUT scenario timeline_data
    try {
      const res = await authFetch(`/api/scenarios/${scenarioFull.id}/timeline_data`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timeline_data: td }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      setImportDlg(false);
      await reloadScenario();
    } catch (e) {
      setActionError(`import: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="h-full flex flex-col gap-2">
      {/* Bar haute : Scenarios + Lecture */}
      <div className="flex items-center gap-3 bg-surface_hi border border-border rounded-sm px-3 py-2">
        <span className="font-ui text-control text-text_med">Scénario :</span>
        <select
          value={activeSid}
          onChange={(e) => setActiveSid(e.target.value)}
          className="bg-bg border border-border rounded-sm px-3 py-1 font-ui text-control text-text focus:outline-none focus:border-amb"
        >
          {scenarios.length === 0 && <option value="">(aucun)</option>}
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>{s.name || s.id}</option>
          ))}
        </select>
        <div className="flex-1" />
        <ToolbarBtn primary disabled={!activeSid || playing} busy={busy === "play"}
                    onClick={() => run("play", async () => {
                      // Le play renvoie HTTP 200 avec {ok:false} si un robot
                      // n'est pas pret : sans ce garde, le bouton semblait
                      // "ne rien faire". Le detail (quel robot/etat) arrive en
                      // parallele via le bus engine.error (cf. store.tsx).
                      const r = await cmdScenarioPlay(activeSid);
                      if (!r.ok) throw new Error(`Lecture refusée (engine ${r.state}) — voir l'onglet Logs`);
                    })}>
          ▶ Lecture
        </ToolbarBtn>
        <ToolbarBtn danger disabled={!activeSid || !playing} busy={busy === "stop"}
                    onClick={() => run("stop", () => cmdScenarioStop(activeSid))}>
          ■ Stop
        </ToolbarBtn>
        <span className="font-mono text-mono_sm text-text_dim ml-2">
          engine: <span className={playing ? "text-amb" : "text-text_dim"}>{engineState}</span>
        </span>
      </div>

      {/* Toolbar evenements */}
      <div className="flex items-center gap-2 bg-surface_hi border border-border rounded-sm px-2 py-2 flex-wrap">
        <ToolbarBtn primary onClick={() => setAddPoseDlg(true)} disabled={!activeSid}>
          ➕ Ajouter Pose
        </ToolbarBtn>
        <ToolbarBtn onClick={() => setSimpleEvtDlg("pause")} disabled={!activeSid}>
          ⏸ Ajouter Pause
        </ToolbarBtn>
        <ToolbarBtn onClick={() => setSimpleEvtDlg("sensor")} disabled={!activeSid}>
          📊 Capteur Arduino
        </ToolbarBtn>
        <ToolbarBtn onClick={() => setSimpleEvtDlg("arduino")} disabled={!activeSid}>
          ⚡ Action Arduino
        </ToolbarBtn>
        <ToolbarBtn onClick={() => setImportDlg(true)} disabled={!activeSid}>
          📥 Importer Suite
        </ToolbarBtn>
        <div className="flex-1" />
        {selectedEventIds.size > 0 && (
          <span className="font-mono text-mono_sm text-amb mr-2">
            {selectedEventIds.size} selection(s)
          </span>
        )}
        <ToolbarBtn onClick={() => setModifyDlg(true)} disabled={selectedEventIds.size !== 1}>
          ✏ Modifier
        </ToolbarBtn>
        <ToolbarBtn danger onClick={onDeleteEvent} disabled={selectedEventIds.size === 0}
                    title="Supprimer (touche Suppr)">
          🗑 Supprimer
        </ToolbarBtn>
        <ToolbarBtn onClick={onExportTimeline} disabled={!scenarioFull}>
          📤 Exporter
        </ToolbarBtn>
      </div>

      {/* Bandeau pistes fantomes (robots disparus du registry) */}
      {hiddenTracks.length > 0 && (
        <div className="bg-amb_dim2 border border-amb/40 rounded-sm px-3 py-1.5 font-ui text-caption text-amb flex items-center gap-2">
          <span>⚠ {hiddenTracks.length} piste(s) fantôme(s) masquée(s) :</span>
          <span className="font-mono text-mono_sm">
            {hiddenTracks.map((t) => t.robot_id).join(", ")}
          </span>
          <span className="text-text_dim">— robots inexistants dans ce projet</span>
        </div>
      )}

      {/* Body : timeline (label fixe + zone scrollable) */}
      <div className="flex-1 bg-bg border border-border rounded-sm overflow-hidden flex flex-col min-h-0">
        {tracks.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-text_dim font-ui text-control">
            {activeSid ? "Aucune piste dans ce scénario" : "Sélectionnez un scénario"}
          </div>
        ) : (
          <div className="flex-1 overflow-auto relative">
            {/* En-tete temporel sticky */}
            <div className="flex sticky top-0 z-20 bg-surface_hi border-b border-border">
              <div className="shrink-0 border-r border-border bg-surface_hi"
                   style={{ width: TRACK_LABEL_W, height: HEADER_H }} />
              <TimelineHeader durationMs={durationMs} zoom={zoom} />
            </div>
            {/* Conteneur relatif pour le playhead overlay */}
            <div className="relative">
              {/* Pistes */}
              {tracks.map((t) => (
                <div key={t.track_id} className="flex">
                  <TrackLabel track={t} />
                  <TrackBody track={t} durationMs={durationMs} zoom={zoom}
                             selectedIds={selectedEventIds}
                             onSelectEvent={onSelectEvent}
                             onDragMoveEvent={onDragMoveEvent}
                             onEditEvent={setEditingEventId} />
                </div>
              ))}
              {/* Playhead isole — seul composant qui re-render a chaque tick */}
              <Playhead pxPerMs={zoom / 100 * 0.05}
                        visible={engineState === "RUNNING" || engineState === "PAUSED"} />
            </div>
          </div>
        )}
      </div>

      {/* Footer : zoom + position lecture */}
      <div className="flex items-center gap-3 px-2 text-text_med font-mono text-mono_sm">
        <button type="button" onClick={() => setZoom(Math.max(25, zoom - 25))}
                className="px-2 py-0.5 bg-surface_hi rounded hover:bg-surface">−</button>
        <span>Zoom: {zoom}%</span>
        <button type="button" onClick={() => setZoom(Math.min(400, zoom + 25))}
                className="px-2 py-0.5 bg-surface_hi rounded hover:bg-surface">+</button>
        <div className="flex-1" />
        {(engineState === "RUNNING" || engineState === "PAUSED") && (
          <ElapsedCounter totalMs={durationMs} />
        )}
        <span>durée totale : {(durationMs / 1000).toFixed(1)}s</span>
      </div>

      {/* Dialogs */}
      {importDlg && (
        <ImportSuiteDialog suites={suites} robots={robots} activeRid={activeRid}
                           onClose={() => setImportDlg(false)} onImport={onImportSuite} />
      )}
      {addPoseDlg && (
        <AddPoseDialog positionsLib={positionsLib} robots={robots} activeRid={activeRid}
                       onClose={() => setAddPoseDlg(false)} onAdd={onAddPose} />
      )}
      {modifyDlg && selectedEvent && (
        <ModifyEventDialog event={selectedEvent.event}
                           onClose={() => setModifyDlg(false)}
                           onUpdate={onModifyEvent} />
      )}
      {simpleEvtDlg === "pause" && (
        <SimpleEventDialog title="⏸ Ajouter une pause" eventType="PAUSE"
          onClose={() => setSimpleEvtDlg(null)} onAdd={onAddSimpleEvent}
          fields={[
            { key: "label", label: "Libellé", type: "text", default: "Pause" },
            { key: "duration_ms", label: "Durée (ms)", type: "number", default: 1000,
              hint: "1000 ms = 1 seconde" },
          ]} />
      )}
      {simpleEvtDlg === "sensor" && (
        <SimpleEventDialog title="📊 Ajouter un capteur Arduino" eventType="SENSOR_WAIT"
          onClose={() => setSimpleEvtDlg(null)} onAdd={onAddSimpleEvent}
          fields={[
            { key: "label", label: "Libellé", type: "text", default: "Attendre capteur" },
            { key: "sensor_id", label: "ID capteur", type: "text", default: "sensor_1" },
            { key: "duration_ms", label: "Timeout (ms)", type: "number", default: 5000 },
          ]} />
      )}
      {simpleEvtDlg === "arduino" && (
        <SimpleEventDialog title="⚡ Ajouter une action Arduino" eventType="ARDUINO_ACTION"
          onClose={() => setSimpleEvtDlg(null)} onAdd={onAddSimpleEvent}
          fields={[
            { key: "label", label: "Libellé", type: "text", default: "Action" },
            { key: "device_id", label: "ID appareil", type: "text", default: "Arduino_1" },
            { key: "command", label: "Commande", type: "text", default: "" },
            { key: "duration_ms", label: "Durée (ms)", type: "number", default: 500 },
          ]} />
      )}
      {editingEvent && (
        <EventEditorModal event={editingEvent} robot={editingRobot}
          onCancel={() => setEditingEventId(null)} onSave={onSaveEvent} />
      )}
    </div>
  );
}
