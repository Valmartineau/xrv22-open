# XRV22 — station de pilotage de bras robotisés

XRV22 pilote un ou plusieurs bras robotisés depuis une interface web
(ordinateur, tablette, écran tactile sur Raspberry Pi 4).
Développé par Valentin Martineau (OVNI) pour ses étudiants d'Arts et Métiers,
au départ pour des bras **ReactorX-200 (Interbotix, servos Dynamixel X)**.

**Ce que fait XRV22**
- Jog axe par axe et capture de positions.
- Suites de positions et timeline multi-robots.
- Garde-fous géométriques et anticollision.
- Interface web (React) servie par un serveur Python (FastAPI), accès protégé par jeton.
- Mode simulation, sans matériel.

**Compatibilité bras MKX3D (moteurs pas-à-pas, Arduino) : chantier en cours.**
XRV22 vise à remplacer l'IHM Scilab du bras MKX3D (IMT Mines Alès)
en parlant son protocole série. Ce n'est pas encore fonctionnel.

## Lancer

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m xrv22.main --sim      # simulation, sans robot
```

Interface web : voir `web/README.md` (`npm install && npm run build`)
et `docs/migration_web.md`.

## Contenu

- `xrv22/` : cœur Python (matériel, timeline, serveur, interfaces).
- `web/` : interface web React.
- `firmware/` : nœud capteur Arduino.
- `eddy/`, `incarne/` : expériences de recherche (bras + LLM local), facultatives.
- `tests/`, `xrv22/tests/` : tests (`pytest`).

## Licence

Code sous **licence MIT** (voir `LICENSE`).
Les maillages 3D du ReactorX-200 (`assets/rx200_meshes`, `web/public/robot`)
viennent d'Interbotix / Trossen Robotics et restent sous leur propre licence (BSD-3-Clause).
Le bras MKX3D (mécanique, firmware, documentation) appartient à ses auteurs,
sous licence CC BY-NC-SA 4.0 ; il n'est pas inclus ici.
