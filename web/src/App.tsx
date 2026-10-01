// App orchestrateur : gate token -> StoreProvider -> Router -> Layout + 8 pages.

import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { getToken } from "./auth";
import { StoreProvider } from "./store";
import { LiveAxesProvider } from "./liveAxes";
import Layout from "./Layout";
import TokenGate from "./pages/TokenGate";
import Connexion from "./pages/Connexion";
import Positions from "./pages/Positions";
import Timeline from "./pages/Timeline";
import Capteurs from "./pages/Capteurs";
import Librairie from "./pages/Librairie";
import Visu from "./pages/Visu";
import Regles from "./pages/Regles";
import Logs from "./pages/Logs";
import IA from "./pages/IA";
// Import statique (pas lazy) : les deps three/fiber/drei sont déjà chargées par
// Visu, donc aucun gain au lazy — et l'import dynamique était instable en dev
// (échec "Importing a module script failed" → écran noir muet).
import CalibratePage from "./calibrate/CalibratePage";
import EddyPage from "./eddy/EddyPage";
import DessinPage from "./dessin/DessinPage";

export default function App() {
  const [hasToken, setHasToken] = useState<boolean>(() => !!getToken());

  if (!hasToken) {
    return <TokenGate onSubmit={() => setHasToken(true)} />;
  }

  return (
    <StoreProvider>
      <LiveAxesProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index             element={<Connexion />} />
            <Route path="positions"  element={<Positions />} />
            <Route path="timeline"   element={<Timeline />} />
            <Route path="capteurs"   element={<Capteurs />} />
            <Route path="librairie"  element={<Librairie />} />
            <Route path="visu"       element={<Visu />} />
            <Route path="regles"     element={<Regles />} />
            <Route path="logs"       element={<Logs />} />
            <Route path="ia"         element={<IA />} />
            <Route path="dessin"     element={<DessinPage />} />
          </Route>
          <Route path="calibrate"  element={<CalibratePage />} />
          <Route path="eddy"       element={<EddyPage />} />
          <Route path="*"          element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      </LiveAxesProvider>
    </StoreProvider>
  );
}
