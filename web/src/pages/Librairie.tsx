// Page Librairie — fidele a xrv22/ui/tab_library.py.
// Arborescence du projet : default > Positions / Suites / Scenarios / Profils / Robots
// Boutons toolbar : Rafraichir / Nouveau / Modifier / Supprimer
// Panneau droit : details de l'element selectionne

import { useMemo, useState } from "react";
import { useStore } from "../store";

type NodeType = "section" | "category" | "position" | "suite" | "scenario" | "robot" | "profile";

type TreeNode = {
  id: string;
  label: string;
  type: NodeType;
  emoji?: string;
  count?: number;
  children?: TreeNode[];
  data?: unknown;
};

function ToolbarBtn({
  children, onClick, primary, danger, disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  primary?: boolean;
  danger?: boolean;
  disabled?: boolean;
}) {
  const tone = danger
    ? "bg-err_dim text-err border-err/40 hover:bg-err_deep"
    : primary
    ? "bg-mag_dim2 text-amb border-mag/50 hover:bg-mag"
    : "bg-surface_hi text-text border-border_hi hover:bg-mag_dim2";
  return (
    <button type="button" onClick={onClick} disabled={disabled}
            className={`px-3 py-1.5 rounded-sm border font-ui text-control transition disabled:opacity-30 ${tone}`}>
      {children}
    </button>
  );
}

function Node({
  node, depth, expanded, onToggle, selected, onSelect,
}: {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  selected: string | null;
  onSelect: (n: TreeNode) => void;
}) {
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isOpen = expanded.has(node.id);
  const isSel = selected === node.id;

  return (
    <>
      <div
        className={`flex items-center gap-1 py-0.5 cursor-pointer ${
          isSel ? "bg-amb_dim2/40 border-l-2 border-amb" : "hover:bg-surface_hi/60"
        }`}
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={() => {
          onSelect(node);
          if (hasChildren) onToggle(node.id);
        }}
      >
        <span className="text-text_med w-3 text-center font-mono text-mono_sm">
          {hasChildren ? (isOpen ? "▼" : "▶") : ""}
        </span>
        <span className="font-ui text-control text-text flex-1">
          {node.emoji && <span className="mr-1.5">{node.emoji}</span>}
          {node.label}
          {node.count !== undefined && (
            <span className="ml-2 text-text_dim text-caption">
              ({node.count} {node.type === "suite" ? "étapes" : ""})
            </span>
          )}
        </span>
      </div>
      {isOpen && hasChildren && node.children!.map((c) => (
        <Node key={c.id} node={c} depth={depth + 1}
              expanded={expanded} onToggle={onToggle}
              selected={selected} onSelect={onSelect} />
      ))}
    </>
  );
}

export default function Librairie() {
  const { positionsLib, suites, scenarios, robots, refetchLibrary, setActionError } = useStore();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["root", "positions", "suites"]));
  const [selected, setSelected] = useState<TreeNode | null>(null);

  const tree = useMemo<TreeNode>(() => {
    const positionsByCat = positionsLib.reduce((acc, p) => {
      const cat = p.category || "sauvegardees";
      (acc[cat] = acc[cat] || []).push(p);
      return acc;
    }, {} as Record<string, typeof positionsLib>);

    const catLabel = (k: string) => ({
      machine_initiales: "Initiales machine",
      travail: "Positions de travail",
      sauvegardees: "Positions sauvegardées",
    }[k] ?? k);

    return {
      id: "root",
      label: "default",
      type: "section",
      emoji: "📁",
      children: [
        {
          id: "positions",
          label: "Positions",
          type: "section",
          emoji: "📌",
          count: positionsLib.length,
          children: Object.entries(positionsByCat).map(([cat, list]) => ({
            id: `cat-${cat}`,
            label: catLabel(cat),
            type: "category",
            count: list.length,
            children: list.map((p) => ({
              id: `pos-${p.id}`,
              label: p.name,
              type: "position",
              data: p,
            })),
          })),
        },
        {
          id: "suites",
          label: "Suites",
          type: "section",
          emoji: "📚",
          count: suites.length,
          children: suites.map((s) => ({
            id: `suite-${s.id}`,
            label: s.name,
            type: "suite",
            count: s.steps?.length ?? 0,
            data: s,
          })),
        },
        {
          id: "scenarios",
          label: "Scénarios",
          type: "section",
          emoji: "🎬",
          count: scenarios.length,
          children: scenarios.map((s) => ({
            id: `scenario-${s.id}`,
            label: s.name,
            type: "scenario",
            data: s,
          })),
        },
        {
          id: "profiles",
          label: "Profils mouvement",
          type: "section",
          emoji: "⚙️",
        },
        {
          id: "robots",
          label: "Robots",
          type: "section",
          emoji: "🤖",
          count: robots.length,
          children: robots.map((r) => ({
            id: `robot-${r.id}`,
            label: r.id,
            type: "robot",
            data: r,
          })),
        },
      ],
    };
  }, [positionsLib, suites, scenarios, robots]);

  const toggle = (id: string) => {
    const next = new Set(expanded);
    next.has(id) ? next.delete(id) : next.add(id);
    setExpanded(next);
  };

  return (
    <div className="h-full flex flex-col gap-2">
      {/* Header */}
      <div className="bg-surface_hi border border-border rounded-sm px-3 py-2 flex items-center gap-3">
        <span className="font-display text-section text-mag">📚 LIBRAIRIE</span>
        <div className="flex-1" />
        <ToolbarBtn onClick={refetchLibrary}>🔄 Rafraîchir</ToolbarBtn>
        <ToolbarBtn onClick={() => setActionError("Nouveau : selectionne le type a creer")}>
          ➕ Nouveau
        </ToolbarBtn>
        <ToolbarBtn onClick={() => setActionError("Modifier : selectionne un element")} disabled={!selected}>
          ✎ Modifier
        </ToolbarBtn>
        <ToolbarBtn danger onClick={() => setActionError("Supprimer : a porter")} disabled={!selected}>
          🗑 Supprimer
        </ToolbarBtn>
      </div>

      {/* 2 colonnes */}
      <div className="grid grid-cols-2 gap-3 flex-1 min-h-0">
        {/* Arborescence */}
        <div className="bg-bg border border-border rounded-sm overflow-auto py-1">
          <Node node={tree} depth={0}
                expanded={expanded} onToggle={toggle}
                selected={selected?.id ?? null}
                onSelect={setSelected} />
        </div>

        {/* Détails */}
        <div className="bg-surface border border-border rounded-sm p-4 overflow-auto">
          {!selected ? (
            <div className="text-text_dim text-center py-12 font-ui text-control">
              Sélectionnez un élément
            </div>
          ) : (
            <>
              <div className="font-display text-title text-text mb-1">
                {selected.emoji && <span className="mr-2">{selected.emoji}</span>}
                {selected.label}
              </div>
              <div className="font-mono text-mono_sm text-text_dim mb-4">
                Type: {selected.type}  ·  ID: {selected.id}
              </div>
              {selected.data && (
                <pre className="bg-bg p-3 rounded font-mono text-mono_sm text-text_med overflow-auto max-h-96">
                  {JSON.stringify(selected.data, null, 2)}
                </pre>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
