// Primitives UI partagees entre les pages.

import type { ReactNode } from "react";

export const AXIS_LABELS = [
  "Base", "Epaule", "Coude", "Poignet", "Tangage", "Roulis", "Pince",
];

export function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-emerald-400" : "bg-rose-500"}`}
      />
      {label}
    </span>
  );
}

export function Btn({
  children, onClick, disabled, danger, primary, busy, title, full,
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
  primary?: boolean;
  busy?: boolean;
  title?: string;
  full?: boolean;
}) {
  const base = "px-3 py-1.5 rounded text-xs font-title tracking-wide transition disabled:opacity-30 disabled:cursor-not-allowed";
  const tone = danger
    ? "bg-rose-700 hover:bg-rose-600"
    : primary
    ? "bg-magenta hover:bg-magenta/80"
    : "bg-white/5 hover:bg-white/10";
  const width = full ? " w-full" : "";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      title={title}
      className={`${base} ${tone}${width}`}
    >
      {busy ? "…" : children}
    </button>
  );
}

export function Card({ children, accent }: { children: ReactNode; accent?: string }) {
  const style = accent
    ? { borderTopColor: accent, borderTopWidth: 3 }
    : undefined;
  return (
    <div
      className="rounded-2xl bg-bg2 p-5 border border-white/5 shadow-xl"
      style={style}
    >
      {children}
    </div>
  );
}

export function PageHeader({
  title, subtitle, right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className="flex items-baseline justify-between mb-6 pb-4 border-b border-white/10">
      <div>
        <h1 className="font-title text-3xl tracking-wider">{title}</h1>
        {subtitle && <p className="text-sm text-white/50 mt-1">{subtitle}</p>}
      </div>
      {right && <div>{right}</div>}
    </header>
  );
}
