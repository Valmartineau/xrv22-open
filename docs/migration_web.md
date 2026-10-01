# Migration XRV22 vers Pi-first + UI Web

> Decision actee : **2026-05-04**
> Source : rapport de faisabilite "UI web servie par Raspberry"

---

## 1. Vision cible

Le **Raspberry Pi** devient le coeur du systeme :
- execution des robots (deja le cas)
- stockage SSOT (XRV22_LIBRARY/)
- interface tactile locale autonome (ui_pi/, deja fait)
- **+ serveur web HTTP + UI web React** servie a tout client navigateur
  sur le LAN (Mac, PC, tablette, phone)

Le **Mac/PC** redevient un simple client navigateur. Plus de Tk a installer,
plus de sync filesystem, plus de duplication de logique UI.

```
Pi (master)                                  Client (Mac/PC/...)
├── UI Tk tactile (ui_pi/)                   └── Navigateur web
│       ▲                                          ▲
│       │ event_bus in-process                     │ HTTP/WS
│       ▼                                          │
├── Backend (core/ robots/ services/ library/)     │
│       ▲                                          │
│       │ (memes objets en memoire)                │
│       ▼                                          │
├── FastAPI server                                 │
│   ├─ REST  /api/...                              │
│   ├─ WS    /ws       (events bus)                │
│   └─ Static  /       (build React SPA) ◄─────────┘
│
└── XRV22_LIBRARY/  (SSOT JSON)
```

---

## 2. Stack technique

### Backend
- **FastAPI** + **Uvicorn** (async, OpenAPI auto, types Pydantic)
- **WebSocket** integre FastAPI
- Lance **dans le meme process** que `main_pi.py` (thread Uvicorn)
  → backend partage in-process (pas d'IPC, pas de duplication)

### Frontend
- **React 18** + **Vite** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui**
- **TanStack Query** pour les appels API (cache, retry)
- **Zustand** ou **Jotai** pour le state global
- **react-three-fiber** + STL existants pour le 3D viewer (plus tard)
- Build statique → servi par FastAPI a `/` ; pas de Node sur Pi en prod

### Reseau
- Wi-Fi LAN + mDNS Avahi (deja actif) → `http://xrv22.local`
- Option : USB-C gadget Ethernet (g_ether) pour zero-config Mac<>Pi

### Service
- systemd `xrv22.service` au boot Pi (remplace/etend `run-xrv22.sh`)

### Securite (MVP)
- Token genere au 1er run, stocke dans `~/.xrv22-token`
- Affiche en QR code sur l'ecran tactile (Settings → Token)
- Header `X-XRV22-Token` requis sur les routes mutation

---

## 3. Plan d'execution incremental

> Regle d'or : **chaque etape laisse le systeme dans un etat coherent**.
> Si tu t'arretes apres l'etape N, l'app fonctionne toujours.

### Etape 0 — Audit (0,5 jour)
- [ ] Lister les methodes publiques de `library_manager` (~30-40)
- [ ] Lister les events bus a propager (~10-15)
- [ ] Definir le schema OpenAPI cible
- [ ] Choix front confirme (React/Vite/TS/Tailwind/shadcn)

### Etape 1 — Serveur API en lecture seule (1 jour)
- [ ] Creer `xrv22/server/api.py` (FastAPI)
- [ ] Endpoints GET seulement :
  - `GET /api/projects`
  - `GET /api/projects/{name}`
  - `GET /api/robots/state`
  - `GET /api/hardware`
  - `GET /api/health`
- [ ] Lancer Uvicorn dans un thread depuis `main_pi.run()`
- [ ] Test : `curl http://xrv22.local:8080/api/projects` → JSON
- [ ] **Aucun changement UI** ; **zero regression**

### Etape 2 — WebSocket events (0,5 jour)
- [ ] `/ws` : connection persistante, broadcast des events bus
- [ ] Format : `{event: "robot.connected", payload: {...}, ts: ...}`
- [ ] Test avec `wscat -c ws://xrv22.local:8080/ws` → voir events live

### Etape 3 — Frontend React minimal (2 jours)
- [ ] Setup `web/` : Vite + TS + Tailwind + shadcn
- [ ] Pages :
  - **Home** : 3 cards robots avec etats live (connected, torque, port)
  - **Pilotage** : sliders simples par axe
  - **Positions** : liste + visualisation
- [ ] Hook `useWebSocket()` → store Zustand
- [ ] Build → `web/dist/` ; FastAPI sert `/` depuis ce dossier

### Etape 4 — Ecriture API (1 jour)
- [ ] Endpoints mutation :
  - `POST /api/projects/{p}/positions`
  - `PUT  /api/projects/{p}/robots/{rid}`
  - `DELETE /api/projects/{p}/positions/{name}`
  - `POST /api/robots/{rid}/connect`
  - `POST /api/robots/{rid}/torque` (true/false)
  - `POST /api/emergency_stop` (prioritaire, sans auth required)
- [ ] Validation Pydantic stricte
- [ ] Test : sauvegarder position depuis web → fichier sur Pi + UI tactile voit

### Etape 5 — Auth + boot auto (0,5 jour)
- [ ] Generation token au 1er run
- [ ] QR code sur l'ecran tactile (Settings)
- [ ] Middleware FastAPI verifie `X-XRV22-Token`
- [ ] `xrv22.service` systemd, `WantedBy=multi-user.target`

### Etape 6 — Parite progressive (2-3 semaines, etale)
A migrer ecran par ecran depuis `ui/` Tk Mac :
- [ ] Onglet Connexion / calibrations
- [ ] Onglet Positions (CRUD complet)
- [ ] Onglet Suites
- [ ] Onglet Timeline (drag-and-drop)
- [ ] Onglet Library (motion profiles, scenarios)
- [ ] Onglet Capteurs (Arduino bridge)
- [ ] Onglet Simulation (3D viewer si pertinent)
- [ ] Diagnostics panel

A chaque migration, la version Tk Mac reste fonctionnelle ; on dépreciera
en bloc une fois la parite atteinte.

---

## 4. Points critiques a preserver

### Mode autonome Pi
- Si pas de Wi-Fi : serveur tourne sur 127.0.0.1, sans clients ; UI tactile OK
- Le boot Pi ne depend d'aucun service Mac
- Format `XRV22_LIBRARY/` JSON inchange

### Threading / event loop
- Uvicorn dans un thread, **jamais** dans le thread Tk
- Le bus reste in-process ; la couche WS est un **observateur**
- Aucun blocage I/O dans le main loop Tk

### Securite robot
- Arret d'urgence physique (bouton ✕ tactile) reste prioritaire absolu
- `/api/emergency_stop` sans auth requis, mais rate-limit autres endpoints
- **Toujours** valider cote backend (soft-limits, vitesse max) — ne pas
  faire confiance au front
- Watchdog : si client web perd la connexion WS pendant un mouvement →
  arret defensif (sauf scenario explicite "fire-and-forget")

### Concurrence
- MVP : "derniere ecriture gagne" + toast d'avertissement
- Plus tard : optimistic locking via etag/version

---

## 5. Estimation effort

| Etape | Effort | Risque |
|-------|--------|--------|
| 0 — Audit | 0,5 j | 🟢 |
| 1 — API lecture | 1 j | 🟢 |
| 2 — WebSocket | 0,5 j | 🟢 |
| 3 — Front MVP | 2 j | 🟡 |
| 4 — API ecriture | 1 j | 🟡 |
| 5 — Auth + boot | 0,5 j | 🟢 |
| **MVP utilisable** | **5,5 j** | |
| 6 — Parite Tk Mac | +10 j etales | 🟡 |
| Production-ready (HTTPS, auth solide, tests) | +5 j | 🟡 |

---

## 6. A eviter

- ❌ **2 apps Python separees** (Tk Mac + serveur web Pi) = duplication
- ❌ **Sync filesystem Mac↔Pi** comme architecture finale (a degager
  des que UI web prete)
- ❌ **Stockage cote Mac** (Mac devient SSOT par accident)
- ❌ **Web UI dans process separe sur Pi** parlant via IPC = sur-ingenierie
- ❌ Gerer auth/HTTPS avant d'avoir un MVP qui marche

---

## 7. Refactors prerequis (FAITS — 2026-05-04)

Avant de partir sur le web, on a deplace dans le backend :
- ✅ **Couplage 2-3** → `RobotController._apply_coupling`
- ✅ **Propagation master** → `RobotRegistry.propagate_from_master` + hooks
  dans `set_home_machine/work/motor_limit/motion_params`
- ✅ **Profil vitesse uniforme** → `RobotController.connect` applique
  `set_profile(comfort_vel, comfort_acc)`
- ✅ **Auto-connect deterministe** + sanitize ports + verrou
- ✅ **Auto-reboot moteurs en erreur HW** lors du torque
- ✅ **Robot 1 force master** sur Pi

→ Le backend est maintenant **assez SSOT** pour qu'une UI web le consomme
proprement, sans avoir a re-coder de la logique cote front.

---

## 8. Prochain incrément recommandé

**Etape 1 seule : serveur FastAPI lecture seule, 1 jour, zero risque.**

Resultat concret : `curl http://xrv22.local:8080/api/projects` retourne
le JSON des projets stockes sur le Pi. Aucun fichier Python existant
modifie de facon breaking. Si la voie te plait, on enchaine. Sinon,
le code peut etre simplement supprime.
