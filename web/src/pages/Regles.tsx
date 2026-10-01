// Page Règles — placeholder identique a l'UI Mac (cf main_window.py:_build_tab_regles).
// Dans l'UI Tk c'est aussi un simple placeholder "Fonctionnalité à venir".

export default function Regles() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center">
        <div className="text-6xl mb-4 opacity-30">⚙️</div>
        <div className="font-display text-title text-text">Règles</div>
        <div className="font-ui text-control text-text_med mt-2">
          Fonctionnalité à venir
        </div>
        <div className="font-mono text-mono_sm text-text_dim mt-4">
          Equivalent xrv22/ui/main_window.py:_build_tab_regles
        </div>
      </div>
    </div>
  );
}
