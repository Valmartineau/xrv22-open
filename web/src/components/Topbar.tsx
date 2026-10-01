// Topbar fidele a xrv22/ui/main_window.py:_build_topbar.
// Hauteur 52px, fond SURFACE_HI, ligne magenta de 1px en bas.
// Boutons projet 📂➕💾📤 ouvrent des dialogs fonctionnels.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../store";
import { authFetch } from "../auth";
import { cmdProjectNew, cmdProjectLoad, cmdProjectSave, cmdProjectExport } from "../commands";
import { Modal, ModalBtn } from "./Modal";

type ProjectInfo = {
  name: string;
  path: string;
  position_count: number;
  suite_count: number;
  modified_at: string;
};

function ProjectBtn({
  emoji, title, onClick, busy,
}: {
  emoji: string; title: string; onClick: () => void; busy?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={busy}
      className="bg-surface text-text px-2.5 py-1 rounded-sm border border-border hover:bg-mag_dim2 hover:border-mag_dim2 transition text-control font-ui leading-none disabled:opacity-50"
    >
      {busy ? "…" : emoji}
    </button>
  );
}

// ── Dialog Charger projet ────────────────────────────────────────

function LoadDialog({ onClose, onLoaded, onError, currentName }: {
  onClose: () => void;
  onLoaded: () => void;
  onError: (msg: string) => void;
  currentName: string;
}) {
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authFetch("/api/projects")
      .then((r) => r.json())
      .then((p: ProjectInfo[]) => setProjects(p))
      .catch(() => setProjects([]));
  }, []);

  const onLoad = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await cmdProjectLoad(selected);
      onLoaded();
      onClose();
    } catch (e) {
      onError(`load: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="📂 Charger un projet" onClose={onClose} width={560}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!selected || busy} onClick={onLoad}>
               {busy ? "Chargement…" : "✓ Ouvrir"}
             </ModalBtn>
           </>}>
      <p className="font-ui text-control text-text_med mb-3">
        Sélectionnez un projet existant.
      </p>
      <div className="bg-bg border border-border rounded-sm max-h-72 overflow-auto">
        {projects === null ? (
          <div className="text-text_dim text-center py-6 font-ui text-control">
            Chargement…
          </div>
        ) : projects.length === 0 ? (
          <div className="text-text_dim text-center py-6 font-ui text-control">
            Aucun projet
          </div>
        ) : projects.map((p) => (
          <button key={p.path} type="button"
                  onClick={() => setSelected(p.path)}
                  className={`w-full flex items-center gap-3 px-3 py-2 text-left transition ${
                    selected === p.path
                      ? "bg-amb_dim2/40 border-l-2 border-amb"
                      : "hover:bg-surface_hi/60 border-l-2 border-transparent"
                  }`}>
            <span>📁</span>
            <span className="font-ui text-control text-text flex-1 truncate">
              {p.name}
              {p.name === currentName && (
                <span className="ml-2 text-amb text-caption">◄ actuel</span>
              )}
            </span>
            <span className="font-mono text-mono_sm text-text_dim">
              {p.position_count} pos · {p.suite_count} suites
            </span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

// ── Dialog Nouveau projet ────────────────────────────────────────

function NewDialog({ onClose, onCreated, onError }: {
  onClose: () => void;
  onCreated: () => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const onCreate = async () => {
    const n = name.trim();
    if (!n) return;
    setBusy(true);
    try {
      await cmdProjectNew(n);
      onCreated();
      onClose();
    } catch (e) {
      onError(`new: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="➕ Nouveau projet" onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!name.trim() || busy} onClick={onCreate}>
               {busy ? "Création…" : "✓ Créer"}
             </ModalBtn>
           </>}>
      <p className="font-ui text-control text-text_med mb-3">
        Choisissez un nom pour votre projet.
      </p>
      <label className="font-ui text-control text-text_med block mb-1">
        Nom du projet :
      </label>
      <input type="text" autoFocus
             value={name}
             onChange={(e) => setName(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && onCreate()}
             placeholder="mon_projet"
             className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
      <p className="font-mono text-mono_sm text-text_dim mt-2">
        Sera créé dans : XRV22_LIBRARY/projects/{name || "<nom>"}/
      </p>
    </Modal>
  );
}

// ── Dialog Exporter projet ───────────────────────────────────────

function ExportDialog({ onClose, onExported, onError, currentName }: {
  onClose: () => void;
  onExported: (path: string) => void;
  onError: (msg: string) => void;
  currentName: string;
}) {
  const [path, setPath] = useState("/home/amniort/xrv22_export");
  const [busy, setBusy] = useState(false);

  const onExport = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const res = await cmdProjectExport(path);
      onExported(res.destination);
      onClose();
    } catch (e) {
      onError(`export: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="📤 Exporter le projet" onClose={onClose} width={500}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!path.trim() || busy} onClick={onExport}>
               {busy ? "Export…" : "✓ Exporter"}
             </ModalBtn>
           </>}>
      <p className="font-ui text-control text-text_med mb-3">
        Copie le projet courant vers un dossier sur le Pi.
      </p>
      <label className="font-ui text-control text-text_med block mb-1">
        Dossier de destination (sur le Pi) :
      </label>
      <input type="text" autoFocus
             value={path}
             onChange={(e) => setPath(e.target.value)}
             className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
      <p className="font-mono text-mono_sm text-text_dim mt-2">
        Le projet "{currentName}" sera copié dans : {path}/{currentName}/
      </p>
    </Modal>
  );
}

// ── Topbar principal ─────────────────────────────────────────────

export default function Topbar() {
  const { health, refetchRobots, refetchLibrary, refetchScenarios, setActionError } = useStore();
  const [now, setNow] = useState(() => new Date());
  const [busy, setBusy] = useState<string | null>(null);
  const [dlg, setDlg] = useState<"" | "load" | "new" | "export">("");
  const [activeProject, setActiveProject] = useState<string>("…");

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const refetchActiveProject = () => {
    authFetch("/api/projects/active")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setActiveProject(d?.name ?? "—"))
      .catch(() => setActiveProject("—"));
  };
  useEffect(() => { refetchActiveProject(); }, []);

  const onSave = async () => {
    setBusy("save");
    try {
      await cmdProjectSave();
      setActionError(`Projet "${activeProject}" sauvegardé`);
    } catch (e) {
      setActionError(`save: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(null); }
  };

  const onProjectChange = () => {
    refetchActiveProject();
    refetchRobots();
    refetchLibrary();
    refetchScenarios();
  };

  const pad = (n: number) => String(n).padStart(2, "0");
  const time = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  const date = `${pad(now.getDate())}/${pad(now.getMonth() + 1)}/${now.getFullYear()}`;

  return (
    <header className="h-topbar_h bg-surface_hi border-b border-mag relative">
      <div className="h-full flex items-center px-5 gap-2">
        <span className="w-2.5 h-2.5 rounded-full bg-mag2 mr-1" />
        <span className="font-display text-title text-text">XRV22 PRO</span>
        <span className="font-ui text-label text-text_med">
          {"  ·  Robot Control Station"}
        </span>
        <span className="ml-2 px-1.5 py-0.5 bg-mag_dim2 text-mag2 font-mono text-mono_sm rounded-xs">
          V22
        </span>

        <div className="flex-1" />

        {/* Info projet */}
        <div className="text-right pr-2">
          <div className="font-ui text-control text-amb leading-tight">
            📁 {activeProject}
          </div>
          <div className="font-mono text-mono_sm text-text_dim leading-tight">
            API v{health?.version ?? "—"}  ·  Pi
          </div>
        </div>

        {/* Boutons projet */}
        <div className="flex gap-1">
          <ProjectBtn emoji="📂" title="Charger un projet"   onClick={() => setDlg("load")} />
          <ProjectBtn emoji="➕" title="Nouveau projet"       onClick={() => setDlg("new")} />
          <ProjectBtn emoji="💾" title="Sauvegarder le projet" onClick={onSave} busy={busy === "save"} />
          <ProjectBtn emoji="📤" title="Exporter le projet"   onClick={() => setDlg("export")} />
          <Link to="/calibrate" title="Ouvrir l'outil de calibration STL"
                className="bg-surface text-text px-2.5 py-1 rounded-sm border border-border hover:bg-mag_dim2 hover:border-mag_dim2 transition text-control font-ui leading-none">
            🔧 Calibrate
          </Link>
        </div>

        {/* Horloge encadree ambre */}
        <div className="ml-2 bg-surface border border-amb px-3.5 py-1 font-mono text-mono_sm text-amb rounded-xs">
          {time}  ·  {date}
        </div>
      </div>

      {/* Dialogs */}
      {dlg === "load" && (
        <LoadDialog onClose={() => setDlg("")} onLoaded={onProjectChange}
                    onError={setActionError} currentName={activeProject} />
      )}
      {dlg === "new" && (
        <NewDialog onClose={() => setDlg("")} onCreated={onProjectChange}
                   onError={setActionError} />
      )}
      {dlg === "export" && (
        <ExportDialog onClose={() => setDlg("")} currentName={activeProject}
                      onExported={(p) => setActionError(`Projet exporté vers ${p}`)}
                      onError={setActionError} />
      )}
    </header>
  );
}
