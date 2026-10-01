// Page Logs & Diagnostics — equivalent xrv22/ui/diagnostics_panel.py.
// Console temps reel : tous les events broadcastes via WS bus.
// Filtres par topic + recherche texte + auto-scroll.

import { useEffect, useMemo, useRef, useState } from "react";
import { useLiveBus } from "../useLiveBus";
import type { WsMsg } from "../types";

type LogEntry = {
  ts: number;
  topic: string;
  data: unknown;
};

const MAX_ENTRIES = 1000;

const TOPIC_FILTERS = [
  { key: "robot",    label: "Robot",    color: "#f6a117" },
  { key: "safety",   label: "Safety",   color: "#f43f5e" },
  { key: "sensor",   label: "Capteur",  color: "#4ade80" },
  { key: "timeline", label: "Timeline", color: "#80276c" },
  { key: "ui",       label: "UI",       color: "#38bdf8" },
];

function topicFamily(topic: string): string {
  return topic.split(".")[0];
}

function topicColor(topic: string): string {
  const fam = topicFamily(topic);
  return TOPIC_FILTERS.find((f) => f.key === fam)?.color ?? "#8a8f98";
}

export default function Logs() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [enabledFamilies, setEnabledFamilies] = useState<Set<string>>(
    () => new Set(TOPIC_FILTERS.map((f) => f.key))
  );
  const [search, setSearch] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const consoleRef = useRef<HTMLDivElement>(null);

  useLiveBus((msg: WsMsg) => {
    // Ne loggue pas les ticks positions (sinon spam 5Hz)
    if (msg.topic === "robot.positions_tick" || paused) return;
    setEntries((cur) => {
      const next = [...cur, { ts: msg.ts, topic: msg.topic, data: msg.data }];
      if (next.length > MAX_ENTRIES) next.splice(0, next.length - MAX_ENTRIES);
      return next;
    });
  });

  useEffect(() => {
    if (!autoScroll || !consoleRef.current) return;
    consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
  }, [entries, autoScroll]);

  const filtered = useMemo(() => {
    return entries.filter((e) => {
      if (!enabledFamilies.has(topicFamily(e.topic))) return false;
      if (search && !e.topic.includes(search) && !JSON.stringify(e.data).includes(search))
        return false;
      return true;
    });
  }, [entries, enabledFamilies, search]);

  const fmtTs = (ts: number) => {
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}.${String(d.getMilliseconds()).padStart(3, "0")}`;
  };

  return (
    <div className="h-full flex flex-col gap-2">
      {/* Toolbar : filtres + actions */}
      <div className="bg-surface_hi border border-border rounded-sm p-2 flex items-center gap-3 flex-wrap">
        <span className="font-ui text-control text-text_med">Filtres :</span>
        {TOPIC_FILTERS.map((f) => {
          const on = enabledFamilies.has(f.key);
          return (
            <label key={f.key} className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={on}
                onChange={() => {
                  const next = new Set(enabledFamilies);
                  on ? next.delete(f.key) : next.add(f.key);
                  setEnabledFamilies(next);
                }}
                className="accent-amb"
              />
              <span className="font-ui text-control" style={{ color: f.color }}>
                {f.label}
              </span>
            </label>
          );
        })}
        <input
          type="text" value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Recherche texte…"
          className="bg-bg border border-border rounded-sm px-2 py-1 font-mono text-mono_sm text-text w-48 focus:outline-none focus:border-amb"
        />
        <div className="flex-1" />
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)}
                 className="accent-amb" />
          <span className="font-ui text-control text-text">Auto-scroll</span>
        </label>
        <button type="button" onClick={() => setPaused(!paused)}
                className={`px-3 py-1 rounded-sm border font-ui text-control transition ${
                  paused ? "bg-amb text-bg border-amb" : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2"
                }`}>
          {paused ? "▶ Reprendre" : "⏸ Pause"}
        </button>
        <button type="button" onClick={() => setEntries([])}
                className="px-3 py-1 rounded-sm border bg-err_dim text-err border-err/40 hover:bg-err_deep font-ui text-control">
          🗑 Vider
        </button>
      </div>

      {/* Console */}
      <div ref={consoleRef}
           className="flex-1 bg-bg_deep border border-border rounded-sm overflow-auto p-2 font-mono text-mono_sm">
        {filtered.length === 0 ? (
          <div className="text-text_dim text-center py-8">
            Aucun event {paused ? "(pause active)" : "— attente du bus..."}
          </div>
        ) : (
          filtered.map((e, i) => (
            <div key={i} className="flex gap-2 py-px hover:bg-surface/30">
              <span className="text-text_dim shrink-0">{fmtTs(e.ts)}</span>
              <span className="shrink-0 px-1.5 rounded text-[10px] font-bold"
                    style={{ background: `${topicColor(e.topic)}33`, color: topicColor(e.topic) }}>
                {e.topic}
              </span>
              <span className="text-text_med truncate">
                {JSON.stringify(e.data)}
              </span>
            </div>
          ))
        )}
      </div>

      {/* Footer : compteur */}
      <div className="font-mono text-mono_sm text-text_dim text-right px-1">
        {filtered.length} events affichés / {entries.length} en mémoire (max {MAX_ENTRIES})
      </div>
    </div>
  );
}
