// Barre d'onglets fidele a ttk.Notebook (xrv22/ui/main_window.py:_build_notebook).
// 8 onglets dans l'ordre exact, avec emojis (cf i18n.py).
// L'onglet actif a un fond plus clair + accent visuel (bordure haute ambre).

import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/",           emoji: "📡", label: "Connexion" },
  { to: "/positions",  emoji: "📌", label: "Positions & Suites" },
  { to: "/timeline",   emoji: "⏱",  label: "Timeline" },
  { to: "/capteurs",   emoji: "📊", label: "Capteurs" },
  { to: "/librairie",  emoji: "📚", label: "Librairie" },
  { to: "/visu",       emoji: "🤖", label: "Visualisation 3D" },
  { to: "/regles",     emoji: "⚙️", label: "Règles" },
  { to: "/logs",       emoji: "📝", label: "Logs & Diagnostics" },
  { to: "/ia",         emoji: "🧠", label: "IA" },
  { to: "/dessin",     emoji: "✏️", label: "Dessin" },
];

export default function Tabs() {
  return (
    <nav className="bg-bg flex items-end gap-px border-b border-border px-2 pt-2">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.to === "/"}
          className={({ isActive }) =>
            `relative px-4 py-2 font-ui text-control transition select-none ${
              isActive
                ? "bg-surface text-text border-t border-x border-border rounded-t-sm"
                : "text-text_med hover:text-text"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <span className="mr-2">{t.emoji}</span>
              {t.label}
              {isActive && (
                <span className="absolute -top-px left-0 right-0 h-px bg-mag" />
              )}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
