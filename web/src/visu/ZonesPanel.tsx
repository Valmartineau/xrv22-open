import { useState, useEffect } from "react";
import { useStore } from "../store";
import { cmdUpdateZone, cmdCreateZone, cmdGetTcp, cmdDeleteZone } from "../commands";
import { ZONE_TYPE_META, type ZoneType } from "../zoneTypes";
import { extendPlanePoints } from "./geometry";

interface ZonesPanelProps {
  focusedId: string | null;
  onFocus: (zid: string | null) => void;
  activeRid: string;
  extendedIds: Set<string>;
  setExtendedIds: React.Dispatch<React.SetStateAction<Set<string>>>;
}

type Mode = { kind: "list" } | { kind: "create" };

export function ZonesPanel({ focusedId, onFocus, activeRid, extendedIds, setExtendedIds }: ZonesPanelProps) {
  const { zones, refetchZones } = useStore();
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [editingNameId, setEditingNameId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);

  // Cycle 3 états : caché (C) -> visible normal (A) -> visible étendu (B) -> caché
  // On déduit l'état courant à partir de (zone.visible, extendedIds.has(zone.id)).
  const onCycleEye = async (zid: string, visible: boolean) => {
    const isExtended = extendedIds.has(zid);
    try {
      if (!visible) {
        // C -> A : on rend visible, sans extension
        setExtendedIds(prev => { const next = new Set(prev); next.delete(zid); return next; });
        await cmdUpdateZone(zid, { visible: true });
      } else if (!isExtended) {
        // A -> B : on garde visible, on ajoute à extendedIds
        setExtendedIds(prev => { const next = new Set(prev); next.add(zid); return next; });
      } else {
        // B -> C : on cache et on retire de extendedIds
        setExtendedIds(prev => { const next = new Set(prev); next.delete(zid); return next; });
        await cmdUpdateZone(zid, { visible: false });
      }
      await refetchZones();
    } catch (e) {
      console.error("[zones] cycle eye:", e);
    }
  };

  const onRename = async (zid: string) => {
    if (!editingName.trim()) { setEditingNameId(null); return; }
    try {
      await cmdUpdateZone(zid, { name: editingName.trim() });
      await refetchZones();
    } catch (e) { console.error("[zones] rename:", e); }
    setEditingNameId(null);
  };

  const onChangeType = async (zid: string, t: ZoneType) => {
    try {
      await cmdUpdateZone(zid, { zone_type: t, color: ZONE_TYPE_META[t].color });
      await refetchZones();
    } catch (e) { console.error("[zones] change type:", e); }
    setMenuOpenId(null);
  };

  const onDelete = async (zid: string) => {
    try {
      await cmdDeleteZone(zid);
      await refetchZones();
      if (focusedId === zid) onFocus(null);
    } catch (e) { console.error("[zones] delete:", e); }
    setConfirmingDelete(null);
    setMenuOpenId(null);
  };

  return (
    <section className="border-t border-border pt-3 mt-3">
      <header className="flex items-center justify-between mb-2">
        <button onClick={() => setCollapsed(c => !c)}
                className="font-ui text-control text-text_med flex items-center gap-2">
          <span>{collapsed ? "▸" : "▾"}</span>
          <span>Zones & Plans</span>
          <span className="text-text_dim">({zones.length})</span>
        </button>
        {!collapsed && mode.kind === "list" && (
          <button onClick={() => setMode({ kind: "create" })}
                  className="px-2 py-1 text-control bg-mag_dim2 text-amb border border-mag/50 rounded-sm hover:bg-mag">
            + Surface
          </button>
        )}
      </header>

      {!collapsed && mode.kind === "list" && (
        <ul className="space-y-1 max-h-64 overflow-y-auto">
          {zones.length === 0 && (
            <li className="text-text_dim text-control py-2 text-center">
              Aucune surface — clique "+ Surface" pour en créer une
            </li>
          )}
          {zones.map(z => {
            const meta = ZONE_TYPE_META[z.zone_type as ZoneType] ?? ZONE_TYPE_META.warning;
            const isFocused = focusedId === z.id;
            return (
              <li key={z.id} className={`relative flex flex-col gap-1 px-2 py-1 rounded-sm border ${
                isFocused ? "bg-mag_dim2 border-mag/50" : "border-transparent hover:bg-surface_hi"
              }`}>
                <div className="flex items-center gap-2">
                  <span style={{ color: meta.color }}>{meta.icon}</span>
                  {editingNameId === z.id ? (
                    <input autoFocus value={editingName}
                           onChange={e => setEditingName(e.target.value)}
                           onKeyDown={e => {
                             if (e.key === "Enter") void onRename(z.id);
                             if (e.key === "Escape") setEditingNameId(null);
                           }}
                           onBlur={() => onRename(z.id)}
                           className="flex-1 bg-bg border border-border rounded-sm px-1 font-mono text-mono_sm text-text" />
                  ) : (
                    <button onClick={() => onFocus(isFocused ? null : z.id)}
                            className="flex-1 text-left font-mono text-mono_sm text-text truncate">
                      {z.name}
                    </button>
                  )}
                  <span className="font-mono text-caption text-text_dim">
                    {z.points.length}pts {z.plane_axis ? `· ${z.plane_axis}` : ""}
                  </span>
                  {(() => {
                    const isExtended = extendedIds.has(z.id);
                    let icon: string, title: string;
                    if (!z.visible)         { icon = "👁‍🗨"; title = "Masqué — cliquer pour afficher"; }
                    else if (!isExtended)   { icon = "👁";   title = "Affichage normal — cliquer pour étendre"; }
                    else                    { icon = "🌐";  title = "Affichage étendu — cliquer pour masquer"; }
                    return (
                      <button onClick={() => onCycleEye(z.id, z.visible)}
                              className="text-text_med hover:text-amb"
                              title={title}>
                        {icon}
                      </button>
                    );
                  })()}
                  <button onClick={() => setMenuOpenId(menuOpenId === z.id ? null : z.id)}
                          className="text-text_med hover:text-amb px-1" title="Actions">⋮</button>
                </div>

                {menuOpenId === z.id && (
                  <div className="flex flex-col gap-1 pl-6 pb-1">
                    <button onClick={() => {
                              setEditingName(z.name); setEditingNameId(z.id); setMenuOpenId(null);
                            }}
                            className="text-left text-caption text-text hover:text-amb">
                      ✏️ Renommer
                    </button>
                    <div className="flex gap-1">
                      <span className="text-caption text-text_dim">Type:</span>
                      {(["plane", "warning", "exclusion"] as ZoneType[]).map(t => (
                        <button key={t} onClick={() => void onChangeType(z.id, t)}
                                className={`text-caption px-1 ${z.zone_type === t ? "text-amb font-bold" : "text-text_med hover:text-amb"}`}
                                title={ZONE_TYPE_META[t].label}>
                          {ZONE_TYPE_META[t].icon}
                        </button>
                      ))}
                    </div>
                    {confirmingDelete === z.id ? (
                      <div className="flex gap-1 text-caption">
                        <span className="text-err">Supprimer ?</span>
                        <button onClick={() => void onDelete(z.id)} className="text-err font-bold">Oui</button>
                        <button onClick={() => setConfirmingDelete(null)} className="text-text_med">Non</button>
                      </div>
                    ) : (
                      <button onClick={() => setConfirmingDelete(z.id)}
                              className="text-left text-caption text-err hover:text-err">
                        🗑 Supprimer
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {!collapsed && mode.kind === "create" && (
        <CreateForm
          activeRid={activeRid}
          onDone={() => setMode({ kind: "list" })}
          onCancel={() => setMode({ kind: "list" })}
        />
      )}
    </section>
  );
}

function CreateForm({ activeRid, onDone, onCancel }: {
  activeRid: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { robots, refetchZones, setActionError } = useStore();
  const [type, setType] = useState<ZoneType>("plane");
  const [target, setTarget] = useState<3 | 4>(3);
  const [robotId, setRobotId] = useState(activeRid || robots[0]?.id || "");
  const [name, setName] = useState(() => {
    const t = new Date().toISOString().slice(11, 16).replace(":", "");
    return `surface_${t}`;
  });
  const [points, setPoints] = useState<{ x: number; y: number; z: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [extend, setExtend] = useState(false);

  const onCapture = async () => {
    if (points.length >= target) return;
    if (!robotId) { setActionError("Aucun robot selectionne"); return; }
    try {
      const tcp = await cmdGetTcp(robotId);
      setPoints(cur => [...cur, { x: tcp.x, y: tcp.y, z: tcp.z }]);
    } catch (e) {
      setActionError(`tcp: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // Raccourci barre espace (désactivé si focus dans input/select)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement;
      if (tgt.tagName === "INPUT" || tgt.tagName === "SELECT" || tgt.tagName === "TEXTAREA") return;
      if (e.code === "Space") { e.preventDefault(); void onCapture(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [robotId, points.length, target]);

  const onSave = async () => {
    if (points.length < target) return;
    setBusy(true);
    try {
      const meta = ZONE_TYPE_META[type];
      const rawPoints = points.map(p => [p.x, p.y, p.z]);
      const finalPoints = extend ? extendPlanePoints(rawPoints) : rawPoints;
      await cmdCreateZone({
        name, zone_type: type, color: meta.color, visible: true,
        points: finalPoints,
        source_robot_id: robotId,
      });
      await refetchZones();
      onDone();
    } catch (e) {
      setActionError(`zone: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-2 bg-bg border border-border rounded-sm p-2">
      <div className="flex items-center justify-between">
        <span className="font-ui text-control text-amb">+ Nouvelle surface</span>
        <button onClick={onCancel} className="text-text_dim hover:text-text">✕</button>
      </div>

      {/* Type */}
      <div>
        <label className="font-ui text-caption text-text_med block mb-1">Type :</label>
        <div className="flex gap-1">
          {(["plane", "warning", "exclusion"] as ZoneType[]).map(t => {
            const m = ZONE_TYPE_META[t];
            const sel = type === t;
            return (
              <button key={t} type="button" onClick={() => setType(t)}
                      className={`flex-1 px-2 py-1 rounded-sm border text-control transition ${
                        sel ? "text-amb" : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2"
                      }`}
                      style={sel ? { background: m.color + "33", borderColor: m.color + "80" } : {}}>
                {m.icon} {m.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Points */}
      <div className="flex gap-2 items-center">
        <label className="font-ui text-caption text-text_med">Points :</label>
        {[3, 4].map(n => (
          <button key={n} type="button" onClick={() => setTarget(n as 3 | 4)}
                  className={`px-2 py-1 rounded-sm border text-control ${
                    target === n ? "bg-mag_dim2 text-amb border-mag/50" : "bg-surface_hi text-text border-border_hi"
                  }`}>
            {n}
          </button>
        ))}
      </div>

      {/* Étendre */}
      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" className="accent-amb" checked={extend}
               onChange={e => setExtend(e.target.checked)} />
        <span className="font-ui text-caption text-text_med">
          🌐 Étendre (affichage illimité dans la 3D)
        </span>
      </label>

      {/* Robot source */}
      <div>
        <label className="font-ui text-caption text-text_med block mb-1">Robot source :</label>
        <select value={robotId} onChange={e => setRobotId(e.target.value)}
                className="w-full bg-bg border border-border rounded-sm px-2 py-1 font-ui text-control text-text">
          {robots.map(r => <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★" : ""}</option>)}
        </select>
      </div>

      {/* Nom */}
      <div>
        <label className="font-ui text-caption text-text_med block mb-1">Nom :</label>
        <input type="text" value={name} onChange={e => setName(e.target.value)}
               className="w-full bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_sm text-text" />
      </div>

      {/* Capture */}
      <div>
        <button type="button" onClick={() => void onCapture()}
                disabled={points.length >= target}
                className="w-full px-2 py-1 rounded-sm bg-mag_dim2 text-amb border border-mag/50 hover:bg-mag text-control disabled:opacity-30">
          📸 Capturer ({points.length}/{target}) <span className="text-text_dim">ou barre espace</span>
        </button>
        {points.length > 0 && (
          <ul className="font-mono text-caption text-text mt-1 space-y-0.5">
            {points.map((p, i) => (
              <li key={i}>
                <span className="text-amb">{i + 1}.</span> X={p.x} Y={p.y} Z={p.z}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-1">
        <button onClick={() => setPoints(cur => cur.slice(0, -1))} disabled={points.length === 0}
                className="flex-1 px-2 py-1 text-caption rounded-sm bg-surface_hi text-text border border-border_hi disabled:opacity-30">
          ↩ Annuler dernier
        </button>
        <button onClick={() => setPoints([])} disabled={points.length === 0}
                className="flex-1 px-2 py-1 text-caption rounded-sm bg-surface_hi text-text border border-border_hi disabled:opacity-30">
          ❌ Effacer
        </button>
      </div>

      <div className="flex gap-1">
        <button onClick={onCancel}
                className="flex-1 px-2 py-1 text-control rounded-sm bg-surface_hi text-text border border-border_hi">
          Annuler
        </button>
        <button onClick={() => void onSave()} disabled={points.length < target || busy}
                className="flex-1 px-2 py-1 text-control rounded-sm bg-amb_dim2 text-amb border border-amb/50 disabled:opacity-30">
          {busy ? "Sauvegarde…" : "Enregistrer"}
        </button>
      </div>
    </div>
  );
}
