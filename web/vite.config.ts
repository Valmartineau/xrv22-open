import { defineConfig, type Plugin } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { readFileSync, writeFileSync, copyFileSync, existsSync } from "node:fs";

// IP du Pi pour le proxy dev local (depuis n'importe quel poste sur le LAN).
// Override possible via VITE_API_TARGET=http://autre-host:port
const API_TARGET = process.env.VITE_API_TARGET || "http://192.168.2.12:8080";

// Endpoint DEV uniquement : POST /__save-calibration écrit public/calibration.json
// depuis le bouton « Appliquer » de /calibrate (plus de copier-coller). Merge :
// seuls refSurfaceZ/axes/pieces/boxes sont remplacés, le reste (ex. segments)
// est conservé. L'ancien fichier est gardé en calibration.json.bak.
// Chemin hors /api : /api est proxifié vers le Pi (cf. server.proxy).
function calibrationWriter(): Plugin {
  return {
    name: "calibration-writer",
    configureServer(server) {
      server.middlewares.use("/__save-calibration", (req, res, next) => {
        if (req.method !== "POST") return next();
        let body = "";
        req.on("data", (c) => { body += c; });
        req.on("end", () => {
          try {
            const incoming = JSON.parse(body);
            const file = path.resolve(__dirname, "public/calibration.json");
            const current = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
            if (existsSync(file)) copyFileSync(file, file + ".bak");
            for (const k of ["refSurfaceZ", "axes", "pieces", "boxes"]) {
              if (incoming[k] !== undefined) current[k] = incoming[k];
            }
            writeFileSync(file, JSON.stringify(current, null, 2) + "\n");
            res.statusCode = 200;
            res.end(JSON.stringify({ ok: true }));
          } catch (e) {
            res.statusCode = 400;
            res.end(JSON.stringify({ ok: false, error: String(e) }));
          }
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), calibrationWriter()],
  // Build statique servi par FastAPI a la racine (Etape 3) :
  // xrv22/web/dist/  ->  xrv22/server/static/
  build: {
    outDir: path.resolve(__dirname, "../xrv22/server/static"),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // timeout court : si le Pi est injoignable (dev sans robot), le proxy
      // abandonne vite et libère la connexion navigateur, au lieu de saturer le
      // pool (~6 conn/origine) et de bloquer le chargement des STL.
      "/api": { target: API_TARGET, changeOrigin: true, timeout: 2000, proxyTimeout: 2000 },
      "/ws": { target: API_TARGET, ws: true, changeOrigin: true, timeout: 2000, proxyTimeout: 2000 },
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
  },
});
