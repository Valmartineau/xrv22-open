// Layout principal — fidele a xrv22/ui/main_window.py.
// Structure :
//   Sidebar (252px gauche, fond BG_DEEP)
//   |  Topbar (52px, fond SURFACE_HI, ligne magenta)
//   |  Tabs (8 onglets ttk.Notebook style)
//   |  <Outlet> = page courante (fond BG)
//   |  StatusBar (40px bas)

import { Outlet } from "react-router-dom";
import { useStore } from "./store";
import Sidebar from "./components/Sidebar";
import Topbar from "./components/Topbar";
import Tabs from "./components/Tabs";
import StatusBar from "./components/StatusBar";
import ConnectionBanner from "./components/ConnectionBanner";

export default function Layout() {
  const { loadError, actionError } = useStore();
  return (
    <div className="h-full flex bg-bg">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <Tabs />
        <main className="flex-1 overflow-auto p-plg">
          <ConnectionBanner />
          {loadError && (
            <div className="bg-err_dim border border-err/40 rounded-sm p-3 mb-3 text-control text-err">
              {loadError}
            </div>
          )}
          {actionError && (
            <div className="bg-amb_dim2 border border-amb/40 rounded-sm p-3 mb-3 text-control text-amb">
              {actionError}
            </div>
          )}
          <Outlet />
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
