// Sidebar fidele a xrv22/ui/sidebar.py.
// Largeur 252px, fond BG_DEEP, bande magenta gauche 3px.
// Sections : Logo XR200 / ROBOTS / ETAT / COMMANDES / STATUT / version.

import { useState } from "react";
import { useStore } from "../store";
import { useActiveRobot } from "../liveAxes";
import { colorForRobot, STATE_LABEL_FR } from "../theme";
import {
  cmdConnect, cmdHome, cmdStop, cmdAddRobot, cmdRemoveRobot, cmdMaster,
} from "../commands";
import { Modal, ModalBtn } from "./Modal";

// ── Sous-composants ──────────────────────────────────────────────

function SectionLabel({ children }: { children: string }) {
  // Style "R O B O T S" : caps, espacees, dim. Le code Tk laisse les
  // espaces dans la chaine source (cf i18n.py SB_ROBOTS = "R O B O T S")
  return (
    <div className="text-text_dim text-caption font-ui px-pmd pt-psm pb-pxs tracking-[0.15em]">
      {children}
    </div>
  );
}

function Sep() {
  return <div className="h-px bg-text_dim mx-3 my-1" />;
}

// Carte robot : fond pleine couleur saturee, etat textuel a droite
function RobotCard({
  rid, isMaster, connected, state, color, active, onClick,
}: {
  rid: string; isMaster: boolean; connected: boolean; state: string;
  color: string; active: boolean; onClick: () => void;
}) {
  const stateLabel = connected
    ? (STATE_LABEL_FR[state] || state)
    : "Déconnecté";
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full flex items-center px-3 py-2 mb-1 rounded-md text-left transition border ${
        active ? "border-amb/60" : "border-transparent hover:border-white/10"
      }`}
      style={{ background: color }}
    >
      <span className="w-3 h-3 rounded-full bg-white/95 mr-2 shrink-0" />
      <span className="font-ui text-control text-white truncate flex-1">
        {rid}
        {isMaster && <span className="ml-1 text-white">★</span>}
      </span>
      <span className="font-ui text-caption text-white/85 ml-2">
        {stateLabel}
      </span>
    </button>
  );
}

function MiniBtn({
  children, onClick, fg = "#e6e6e6", disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  fg?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="bg-surface_hi hover:bg-surface text-caption font-ui py-1.5 rounded-pill border border-border_hi/40 transition disabled:opacity-40"
      style={{ color: fg }}
    >
      {children}
    </button>
  );
}

// Pill horizontale gradient (gauche -> droite) avec triangle play droit
function Pill({
  text, onClick, gl, gr, disabled,
}: {
  text: string;
  onClick: () => void;
  gl: string;
  gr: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="w-[218px] h-[38px] rounded-pill flex items-center px-3 mx-auto transition hover:brightness-90 disabled:opacity-40 disabled:cursor-not-allowed"
      style={{ background: `linear-gradient(to right, ${gl}, ${gr})` }}
    >
      <span className="text-white font-ui text-control flex-1 text-left">
        {text}
      </span>
      <svg width="14" height="14" viewBox="0 0 14 14" className="shrink-0">
        <polygon points="2,1 12,7 2,13" fill={gl} stroke={gl} strokeWidth="1" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

// ── Sidebar principal ────────────────────────────────────────────

// Dialog Synchro : choisit une "source" et propage sa config aux autres
function SynchroDialog({ robots, onClose, onError }: {
  robots: ReturnType<typeof useStore>["robots"];
  onClose: () => void;
  onError: (msg: string) => void;
}) {
  const [sourceRid, setSourceRid] = useState<string>(
    robots.find((r) => r.is_master)?.id ?? robots[0]?.id ?? ""
  );
  const [busy, setBusy] = useState(false);

  const onApply = async () => {
    if (!sourceRid) return;
    setBusy(true);
    try {
      await cmdMaster(sourceRid);
      onClose();
    } catch (e) {
      onError(`synchro: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="🔗 Synchroniser maître → esclaves" onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!sourceRid || busy} onClick={onApply}>
               {busy ? "Propagation…" : "✓ Synchroniser"}
             </ModalBtn>
           </>}>
      <p className="font-ui text-control text-text_med mb-3">
        Définit le robot source comme maître ★ et propage sa config (home machine,
        home travail, soft_limits, motion_params) aux autres robots.
      </p>
      <label className="font-ui text-control text-text_med block mb-1">
        Robot source :
      </label>
      <select value={sourceRid} onChange={(e) => setSourceRid(e.target.value)}
              className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-ui text-control text-text focus:outline-none focus:border-amb">
        {robots.map((r) => (
          <option key={r.id} value={r.id}>
            {r.id}{r.is_master ? " ★ (maître actuel)" : ""}
          </option>
        ))}
      </select>
    </Modal>
  );
}

// Dialog Ajouter robot
function AddRobotDialog({ existing, onClose, onAdded, onError }: {
  existing: string[];
  onClose: () => void;
  onAdded: () => void;
  onError: (msg: string) => void;
}) {
  // Suggestion : prochain robot_N libre
  const suggested = (() => {
    for (let i = 1; i <= 8; i++) {
      const id = `robot_${i}`;
      if (!existing.includes(id)) return id;
    }
    return "robot_99";
  })();
  const [rid, setRid] = useState(suggested);
  const [busy, setBusy] = useState(false);

  const onAdd = async () => {
    const r = rid.trim();
    if (!r) return;
    setBusy(true);
    try {
      await cmdAddRobot(r);
      onAdded();
      onClose();
    } catch (e) {
      onError(`add: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="＋ Ajouter un robot" onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn primary disabled={!rid.trim() || busy} onClick={onAdd}>
               {busy ? "Ajout…" : "✓ Ajouter"}
             </ModalBtn>
           </>}>
      <label className="font-ui text-control text-text_med block mb-1">
        ID du robot (ex. robot_4) :
      </label>
      <input type="text" autoFocus value={rid}
             onChange={(e) => setRid(e.target.value)}
             onKeyDown={(e) => e.key === "Enter" && onAdd()}
             className="w-full bg-bg border border-border rounded-sm px-3 py-2 font-mono text-mono_md text-text focus:outline-none focus:border-amb" />
      <p className="font-mono text-mono_sm text-text_dim mt-2">
        Sera créé avec motor_ids 1-7 par défaut. Existants : {existing.join(", ")}
      </p>
    </Modal>
  );
}

// Dialog Retirer robot
function RemoveRobotDialog({ robots, onClose, onRemoved, onError }: {
  robots: ReturnType<typeof useStore>["robots"];
  onClose: () => void;
  onRemoved: () => void;
  onError: (msg: string) => void;
}) {
  const [rid, setRid] = useState(robots[robots.length - 1]?.id ?? "");
  const [busy, setBusy] = useState(false);

  const onRemove = async () => {
    if (!rid) return;
    if (!window.confirm(`Vraiment supprimer ${rid} du registry ?`)) return;
    setBusy(true);
    try {
      await cmdRemoveRobot(rid);
      onRemoved();
      onClose();
    } catch (e) {
      onError(`remove: ${e instanceof Error ? e.message : String(e)}`);
    } finally { setBusy(false); }
  };

  return (
    <Modal title="✕ Retirer un robot" onClose={onClose} width={460}
           footer={<>
             <ModalBtn onClick={onClose}>Annuler</ModalBtn>
             <ModalBtn danger disabled={!rid || busy} onClick={onRemove}>
               {busy ? "Suppression…" : "✓ Retirer"}
             </ModalBtn>
           </>}>
      <p className="font-ui text-control text-text_med mb-3">
        Le robot sera retiré du registry mais la config disque (`robots/{rid}.robot.json`)
        reste. Le dernier robot ne peut pas être supprimé.
      </p>
      <select value={rid} onChange={(e) => setRid(e.target.value)}
              className="w-full bg-bg border border-border rounded-sm px-3 py-1.5 font-mono text-mono_md text-text focus:outline-none focus:border-amb">
        {robots.map((r) => (
          <option key={r.id} value={r.id}>{r.id}{r.is_master ? " ★ (maître)" : ""}</option>
        ))}
      </select>
    </Modal>
  );
}

export default function Sidebar() {
  const { robots, setActionError, refetchRobots } = useStore();
  const { activeRid, setActiveRid } = useActiveRobot();
  const [dlg, setDlg] = useState<"" | "add" | "remove" | "synchro">("");

  const run = async (fn: () => Promise<unknown>, label: string) => {
    try { await fn(); } catch (e) {
      setActionError(`${label}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const allConnect = () => robots.forEach((r) => {
    if (!r.connected) run(() => cmdConnect(r.id), `connect ${r.id}`);
  });
  const allHome = (kind: "machine" | "work") =>
    robots.forEach((r) => r.connected
      && run(() => cmdHome(r.id, kind), `home ${r.id}`));
  const allStop = () => robots.forEach((r) =>
    r.connected && run(() => cmdStop(r.id), `stop ${r.id}`));

  // ÉTAT pill global : connecté si au moins 1 robot connecté
  const anyConnected = robots.some((r) => r.connected);

  return (
    <aside className="w-sidebar_w shrink-0 bg-bg_deep flex relative border-r border-text_dim">
      {/* Bande magenta verticale 3px */}
      <div className="w-[3px] bg-mag" />

      <div className="flex-1 flex flex-col min-h-0">
        {/* ── Logo ── */}
        <div className="px-4 pt-5 pb-2">
          <div className="font-display text-display text-text">XR200</div>
          <div className="font-ui text-caption text-text_dim mt-0.5 tracking-wide">
            ROBOT CONTROL STATION
          </div>
        </div>

        <Sep />

        {/* ── ROBOTS ── */}
        <SectionLabel>R O B O T S</SectionLabel>
        <div className="px-2.5">
          {robots.length === 0 && (
            <div className="text-text_dim text-caption font-ui px-2 py-3">…</div>
          )}
          {robots.map((r) => (
            <RobotCard
              key={r.id}
              rid={r.id}
              isMaster={r.is_master}
              connected={r.connected}
              state={r.state}
              color={colorForRobot(r.id)}
              active={activeRid === r.id}
              onClick={() => setActiveRid(r.id)}
            />
          ))}
        </div>

        {/* Grille 2x2 boutons */}
        <div className="grid grid-cols-2 gap-1.5 px-3 pt-2">
          <MiniBtn onClick={() => setDlg("add")} fg="#2a9d5c">+ Ajouter</MiniBtn>
          <MiniBtn onClick={() => setDlg("remove")} fg="#b83248" disabled={robots.length <= 1}>
            × Retirer
          </MiniBtn>
          <MiniBtn onClick={allConnect} fg="#c4820f">🔌 ALL CO.</MiniBtn>
          <MiniBtn onClick={() => setDlg("synchro")} fg="#38bdf8">🔗 Synchro</MiniBtn>
        </div>

        <Sep />

        {/* ── ÉTAT ── */}
        <SectionLabel>É T A T</SectionLabel>
        <div className="px-3.5 pb-1">
          <Pill
            text={anyConnected ? "Connecté" : "Non connecté"}
            onClick={() => {}}
            gl="#252836"
            gr="#2c303e"
          />
        </div>

        <Sep />

        {/* ── COMMANDES ── */}
        <SectionLabel>C O M M A N D E S</SectionLabel>
        <div className="space-y-0.5 pb-1">
          <Pill text="🔓  Déverrouiller tous" onClick={() => {}} gl="#4a1060" gr="#80276c" />
          <Pill text="🔒  Verrouiller tous"   onClick={() => {}} gl="#0e0a1e" gr="#80276c" />
        </div>

        <div className="h-px bg-text_dim mx-3 my-1" />

        <div className="space-y-0.5 pb-1">
          <Pill text="🔧  Pos. travail" onClick={() => allHome("work")}    gl="#0e2a18" gr="#4ade80" />
          <Pill text="🏠  Pos. machine" onClick={() => allHome("machine")} gl="#3a1e04" gr="#f6a117" />
        </div>

        <div className="h-px bg-text_dim mx-3 my-1" />

        <Pill text="⏹  STOP doux" onClick={allStop} gl="#5c2010" gr="#f6a117" />

        <div className="h-px bg-text_dim mx-3 my-1" />

        <Pill
          text="🛑  STOP URGENCE"
          onClick={() => {
            if (window.confirm("Arret d'urgence sur TOUS les robots connectes ?")) {
              allStop();
            }
          }}
          gl="#7a0c0c"
          gr="#c0392b"
        />

        {/* ── STATUT (pousse en bas via flex-1 du conteneur parent) ── */}
        <div className="flex-1" />
        <Sep />
        <SectionLabel>S T A T U T</SectionLabel>
        <div className="px-4 pb-2 space-y-0.5 text-text_med font-ui text-caption">
          <div>⚙  Pos. machine : —</div>
          <div>🔧 Pos. travail : —</div>
          <div>📡 0 capteur</div>
        </div>

        {/* Footer version */}
        <div className="h-px bg-text_dim mx-3" />
        <div className="text-center font-mono text-mono_sm text-text_dim py-2">
          V22  ·  XRV22 PRO
        </div>
      </div>

      {/* Workaround Tailwind JIT pour les classes calculees dynamiquement */}
      <div className="hidden bg-amb bg-cyan-400 bg-fuchsia-500" />

      {/* Dialogs */}
      {dlg === "add" && (
        <AddRobotDialog existing={robots.map((r) => r.id)}
                        onClose={() => setDlg("")}
                        onAdded={refetchRobots}
                        onError={setActionError} />
      )}
      {dlg === "remove" && (
        <RemoveRobotDialog robots={robots}
                           onClose={() => setDlg("")}
                           onRemoved={refetchRobots}
                           onError={setActionError} />
      )}
      {dlg === "synchro" && (
        <SynchroDialog robots={robots}
                       onClose={() => setDlg("")}
                       onError={setActionError} />
      )}
    </aside>
  );
}

// Marqueur factice : si Tailwind ne pre-genere pas certaines classes
// referencees uniquement via style="background:..." (cas TRACK_COLORS),
// il les injecterait via le purge. Inutile : on utilise style={{}} donc
// Tailwind ne purge pas. Mais on garde le marqueur ci-dessus pour eviter
// les regressions si quelqu'un convertit en classes.
