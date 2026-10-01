// Ecran "Saisir token" : montre quand pas de token en localStorage et
// pas de ?token= dans l'URL.

import { useState } from "react";

export default function TokenGate({ onSubmit }: { onSubmit: () => void }) {
  const [manualToken, setManualToken] = useState("");

  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <form
        className="bg-bg2 rounded-2xl p-8 max-w-md w-full border border-white/5 shadow-xl"
        onSubmit={(e) => {
          e.preventDefault();
          const t = manualToken.trim();
          if (!t) return;
          try { localStorage.setItem("xrv22.token", t); } catch { /* private mode */ }
          onSubmit();
        }}
      >
        <h1 className="font-title text-3xl mb-2">
          XRV22 <span className="text-amber">PRO</span>
        </h1>
        <p className="text-sm text-white/60 mb-6">
          Scanne le QR code affiche sur le Pi (logs ou ecran tactile),
          ou colle le token ci-dessous.
        </p>
        <input
          type="password"
          autoFocus
          value={manualToken}
          onChange={(e) => setManualToken(e.target.value)}
          placeholder="Token (64 caracteres hex)"
          className="w-full bg-bg border border-white/10 rounded px-3 py-2 font-mono text-sm mb-4 focus:outline-none focus:border-amber"
        />
        <button
          type="submit"
          className="w-full bg-magenta hover:bg-magenta/80 transition rounded py-2 font-title tracking-wide"
        >
          Se connecter
        </button>
      </form>
    </div>
  );
}
