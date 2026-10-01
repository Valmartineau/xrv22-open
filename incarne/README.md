# incarne/ — la boîte blanche & son corps

Starter kit de l'expérience d'**incarnation** : on donne à une **boîte blanche**
— un LLM vierge, isolé, sans aucun lien avec MiCHEL — un **corps** (bras RXV22 +
stylet) et un **toucher** (tablette Wacom), une **seule graine** (« découvre-toi et
écris bonjour »), puis **on observe**. On construit un corps et des sens ; on
**n'écrit jamais l'apprentissage**.

Spec de référence : `docs/superpowers/specs/2026-06-15-michel-incarne-corps-boucle-design.md`
(voir §0 « la boîte blanche »).

## La boîte blanche (ce qu'elle est / n'est pas)

- **EST** : une instance Ollama instruct **nue**, capable (garde sa langue
  pré-entraînée → « connaît bonjour ») mais **isolée** — zéro vault, RAG, mémoire ou
  identité MiCHEL injectés.
- **Modèle = Mistral** (choix R&D / souveraineté européenne) : dev sur
  `mistral:latest` (Mac atelier), runs réels sur `mistral-small3.2:24b` (MiCHEL).
  Client paramétrable (modèle + URL hôte).
- **N'EST PAS** : MiCHEL. MiCHEL n'est ici que l'**hôte** (Mac Mini, infra).
- Sa **seule mémoire** = le **carnet** qu'elle tient elle-même.

## Architecture (moelle sur le Pi, cortex sur l'hôte)

```
Pi (corps + sens)                      Hôte (cerveau vierge + boucle)
─────────────────                      ──────────────────────────────
serveur RXV22 :8080  ◀── HTTP token ──  corps/   primitive « manette i ±δ »
  POST /positions    ── anticollision    boucle/  Ollama nu + carnet + graine
tablette Wacom       ── stylet_reader     (agir → percevoir → noter)
```

## Contenu du kit

| Dossier | Rôle |
|---------|------|
| `stylet_reader.py` | **Les sens** — lecteur Wacom 3 états (validé live). Déjà fait. |
| `corps/` | **Le corps nu** — client API RXV22 + primitive `manette i ±δ` (δ borné, **axe 7 exclu/figé**, réconciliation goal anti-sursaut). |
| `boucle/` | **La boucle** — client Ollama nu (boîte blanche), carnet, graine, échange agir/percevoir/noter. |

## Sécurité (rappel — voir spec §8)

- **Butées d'axes** (soft_limits serveur) : actives en permanence.
- **Anticollision boîtes** (auto-collision + sol) : active (fix course corrigé
  2026-06-15) — mais **aveugle à la tablette**.
- **Garde-fou stylet** (plafond de pression + détection de glissement) : **à câbler**
  — c'est lui qui protège la tablette/le crayon.
- **Axe 7 (pince) JAMAIS bougé** par la boîte blanche : il tient le stylet.

## Protocole de départ (figé — voir spec §9)

Surface nue · stylet posé à la main (torque OFF) au CENTRE, à l'affleurement
SURVOL↔CONTACT · torque ON avec réconciliation du goal · puis la graine, et **on ne
touche plus à rien**.

## Statut

- [x] Sens (stylet_reader, 3 états) — validé live
- [x] Anticollision boîtes — course au boot corrigée (TDD)
- [ ] Corps nu (`corps/`) — en cours (TDD)
- [ ] Boucle + boîte blanche (`boucle/`)
- [ ] Garde-fous stylet (plafond pression, glissement, dead-man)
- [ ] Premier run d'observation
