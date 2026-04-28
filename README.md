# EHPAD Monitor — Detection et prediction de malaise

Systeme IoT/IA de detection et prediction de malaises pour EHPAD.
Projet Epitech MBA1 — 100 points.

**25 residents · 2 niveaux · Alertes 5 niveaux · NEWS2 · ML GradientBoost · KB clinique HAS/RCP · Espace famille · LLM Meditron**

---

## Demarrage rapide

```powershell
ollama serve          # requis pour les rapports LLM (optionnel)
docker compose up --build -d
docker compose ps
```

| Service | URL |
|---|---|
| Dashboard soignant | http://localhost:3002 |
| Espace famille | http://localhost:3002/famille.html |
| Admin comptes famille | http://localhost:3002/admin_famille.html |
| Backend API | http://localhost:8001 |
| API docs (Swagger) | http://localhost:8001/docs |
| InfluxDB | http://localhost:8086 |
| MQTT | localhost:1883 |

## Acces demo prof

Tout est centralise ici pour la soutenance.

| Espace | URL | Identifiant | Mot de passe / token | A montrer |
|---|---|---|---|---|
| Dashboard central | http://localhost:3002 | aucun | aucun | grille, alertes, plan 2D/3D, transmissions |
| Espace soignant | http://localhost:3002/soignant | `soignant_A` | `EHPAD2024!` | residents assignes + prise en charge |
| Espace soignant | http://localhost:3002/soignant | `soignant_B` | `EHPAD2024!` | autre secteur |
| Espace soignant | http://localhost:3002/soignant | `soignant_C` | `EHPAD2024!` | autre secteur |
| Chef de garde | http://localhost:3002/soignant | `chef_garde` | `EHPAD2024!` | acces privilegie + journaux securite |
| Direction | http://localhost:3002/soignant | `direction` | `EHPAD2024!` | acces direction |
| Famille demo | http://localhost:3002/famille.html | `piaf` | `piaf105` | livre famille Edith Piaf |
| Famille demo | http://localhost:3002/famille.html | `curie` | `curie101` | autre famille |
| Admin familles | http://localhost:3002/admin_famille.html | token admin | `ADMIN_EHPAD_2024` | comptes famille |
| API Swagger | http://localhost:8001/docs | aucun | aucun | endpoints backend |

Liens directs utiles :

- Fiche patient complete : http://localhost:3002/resident/R005
- Fiche mobile intervention : http://localhost:3002/mobile/resident/R005
- API alertes : http://localhost:8001/api/alerts
- API personnel : http://localhost:8001/api/staff

Tous les comptes famille sont listes dans [docs/comptes_famille_demo.md](docs/comptes_famille_demo.md).

```powershell
docker compose down   # arret
```

---

## Architecture

```text
Simulateur Python (25 residents)
  - profils cliniques + pathologies
  - rythme circadien (BP/HR/Temp/SpO2 sur 24h)
  - 18 scenarios (chute, hypoxie, fugue, sepsis...)
  - ponderation temporelle des risques de chute
  - capteurs vitaux + ambiants + QoS MQTT
        |
        v MQTT QoS 0/1/2
Mosquitto (broker)
        |
        v
Backend FastAPI
  - moteur d'alertes 5 niveaux + escalade automatique
  - score NEWS2 clinique (HAS/RCP)
  - mode nuit (seuils SpO2 adaptes au sommeil)
  - deviation de routine C4 (Redis, fenetre 100 mesures)
  - prediction ML GradientBoost (30-60 min)
  - KB clinique v2 (15 scenarios HAS, 8 archetypes)
  - authentification famille (comptes Redis, tokens 24h)
  - rapport LLM quotidien (Meditron:7b via Ollama)
  - profils source JSON par resident + Redis live/cache + InfluxDB series capteurs
  - WebSocket dashboard temps reel
        |
        v
Dashboard HTML/JS
  - grille 25 residents avec alertes live
  - detail resident + sparklines + scope clinique
  - plan SVG RDC + 1er etage
  - vue 3D Three.js avec localisation
  - interface famille (acces restreint par compte)
  - interface admin comptes famille
  - panneau transmissions IDE / mini DPI
  - validation pro + scenarios declenchables
```

---

## Fonctionnalites

### Must have

| Critere | Implementation |
|---|---|
| Simulateur 25 residents | Profils cliniques, pathologies, mobilite, facteur risque |
| Capteurs vitaux | FC, SpO2, PA, Temp, FR via MQTT |
| Capteurs ambiants | Temperature, humidite, CO2, mouvement, portes |
| MQTT QoS | Vitaux QoS 1, chutes/SOS QoS 2, ambiants QoS 0 |
| Alertes 5 niveaux | Information → Danger vital, escalade auto |
| Dashboard temps reel | WebSocket, grille, detail, plan, sparklines |
| Docker Compose | 6 services avec healthchecks |
| Documentation | README, architecture, demo, comptes famille |

### Should have

| Critere | Implementation |
|---|---|
| Prediction ML 30-60 min | GradientBoostingClassifier, 9 features, AUC expose |
| Metriques ML medicales | Sensibilite, specificite, matrice confusion, feature importance |
| Score NEWS2 | 6 parametres cliniques, 3 niveaux de risque |
| Mode nuit | Seuils SpO2 adaptes au sommeil (92%/89% vs 95%/93%) |
| Rythme circadien | BP/HR/Temp/SpO2 suivent un cycle physiologique 24h |
| Plan etablissement | SVG interactif + vue 3D Three.js |
| Escalade automatique | Niveau 2→3→4→5 avec delais configures |
| KB clinique v2 | 15 scenarios (HAS, RCP, WHO), 8 archetypes, 13 classes med. |

### Could have

| Critere | Implementation |
|---|---|
| Rapport LLM quotidien (C2) | Meditron:7b via Ollama local, RGPD-compliant |
| Espace famille (C3) | Comptes individuels, token 24h, vue sans donnees medicales |
| Admin comptes famille | Creation / suppression de comptes via interface web |
| Analyse de routine (C4) | Detection deviation >2.5 sigma vs baseline Redis |
| Archetypes KB par resident | Chaque resident lie a un archetype clinique + scenarios preferes |
| Tests automatises | 60+ tests pytest : alertes, ML, NEWS2, auth famille, API |

---

## Espace Famille (C3)

Chaque famille dispose d'un compte individuel donnant acces **uniquement** a son proche.

URL : http://localhost:3002/famille.html

Codes de demonstration (generes au demarrage) :

| Utilisateur | Mot de passe | Resident | Chambre |
|---|---|---|---|
| curie | curie101 | Marie Curie | 101 |
| coubertin | coubertin104 | Pierre de Coubertin | 104 |
| piaf | piaf105 | Edith Piaf | 105 |
| sardou | sardou219 | Michel Sardou | 219 |
| ... | ... | 25 comptes au total | voir docs/comptes_famille_demo.md |

Ce qui est visible : statut general, activite en cours, soignant referent, heure.
Ce qui est masque : FC, SpO2, PA, temperature, scores cliniques, alertes brutes.

### Interface admin

URL : http://localhost:3002/admin_famille.html
Token : `ADMIN_EHPAD_2024` (configurable via env `FAMILLE_ADMIN_TOKEN`)

L'admin peut creer, lister et supprimer des comptes famille.

---

## Base de connaissances clinique (KB v2)

Fichier : `backend/kb/ehpad_watch_kb.json`

| Element | Contenu |
|---|---|
| Sources | HAS, RCP NEWS2, WHO, CDC, Ameli, NCBI, Doloplus, VIDAL |
| Scenarios | 15 scenarios cliniques (SCN001 a SCN015) |
| Archetypes | 8 profils residents (ARCH_ALZ_FALL, ARCH_BPCO, ARCH_CARDIAC...) |
| Medicaments | 13 classes a risque avec facteurs de boost pour le moteur |
| Transmission | Format SBAR pour les transmissions IDE |

Chaque resident est automatiquement associe a un archetype et a ses scenarios preferes au demarrage.

Endpoints KB :

```
GET /api/kb/scenarios         — liste des 15 scenarios
GET /api/kb/scenarios/{id}    — detail complet d'un scenario
GET /api/kb/archetypes         — les 8 archetypes
GET /api/kb/residents          — residents enrichis KB
```

---

## Modele ML

- Algorithme : `GradientBoostingClassifier` (scikit-learn)
- Justification : robustesse sur donnees tabulaires medicales heterogenes, resistance aux outliers, interpretabilite via feature importance (superieur a SVM ou reseau de neurones sur ce volume)
- Pipeline : `StandardScaler` → classifieur (100 estimateurs, lr=0.1, max_depth=4)
- 9 features : FC, SpO2, PA systolique, temperature, inactivite, delta FC/SpO2 sur 10 min, facteur age, facteur risque
- Metriques : accuracy, AUC-ROC, F1, **sensibilite**, **specificite**, matrice de confusion, importance des features
- Endpoint : `GET /api/ml/metrics`
- Note : split aleatoire acceptable sur donnees synthetiques i.i.d. — split temporel obligatoire sur donnees reelles

---

## Score NEWS2

Calcule a chaque evaluation, base sur 6 parametres (FC, FR, SpO2, PA, Temp, conscience).
Seuils d'alerte additionnels : NEWS2 ≥ 3 → L2, ≥ 5 → L3, ≥ 7 → L4, ≥ 9 → L5.
Documente par le Royal College of Physicians (RCP 2017), utilise dans les EHPAD francais.

---

## Rapport LLM quotidien (C2)

Endpoint : `GET /api/llm/report/{resident_id}`

Utilise **Meditron:7b via Ollama** (local), LLM open-source fine-tune sur PubMed et guidelines medicales.
Aucune donnee ne quitte la machine — conformite RGPD.
Repli automatique si Ollama indisponible.

Prerequis : `ollama serve` avant `docker compose up`.

---

## API REST — Endpoints principaux

| Endpoint | Description |
|---|---|
| `GET /health` | Etat backend + Redis |
| `GET /api/residents` | Tous les residents + etat courant |
| `GET /api/residents/{id}` | Detail resident |
| `GET /api/residents/{id}/routine` | Analyse de routine (deviation sigma) |
| `GET /api/alerts` | Alertes actives + historique |
| `POST /api/alerts/{id}/acknowledge` | Acquitter une alerte |
| `GET /api/ml/metrics` | Metriques ML (sensibilite, specificite...) |
| `GET /api/kb/scenarios` | Liste des 15 scenarios KB |
| `GET /api/kb/residents` | Residents enrichis avec archetype KB |
| `POST /api/famille/login` | Connexion espace famille |
| `GET /api/famille/{id}` | Vue famille (token requis) |
| `GET /api/admin/famille/accounts` | Liste comptes famille (admin) |
| `POST /api/admin/famille/accounts` | Creer un compte famille (admin) |
| `GET /api/llm/report/{id}` | Rapport LLM quotidien |
| `WS /ws` | Flux WebSocket temps reel |

---

## Tests

```powershell
py -m pip install pytest httpx
py -m pytest tests/ -v
```

Couverture (60+ tests) :

- `TestAlertEngine` — moteur d'alertes 5 niveaux
- `TestMLModel` — prediction, metriques, features
- `TestAPIIntegration` — endpoints REST
- `TestSimulator` — scenarios, rythme circadien
- `TestNEWSScore` — calcul NEWS2
- `TestNightMode` — seuils SpO2 nuit vs jour
- `TestFamilleAuth` — auth.py avec FakeRedis (25 comptes parametrises)
- `TestFamilleAPI` — endpoints famille et admin

---

## Structure du projet

```text
.
├── docker-compose.yml
├── backend/
│   ├── main.py                  # FastAPI — routes, WebSocket, MQTT
│   ├── alert_engine.py          # Moteur alertes 5 niveaux + NEWS2
│   ├── ml_model.py              # GradientBoost + metriques medicales
│   ├── auth.py                  # Comptes famille (hash SHA-256, tokens Redis)
│   ├── kb_loader.py             # Chargeur KB clinique v2
│   ├── resident_profiles.py     # 25 profils + enrichissement KB
│   ├── ws_manager.py            # Gestionnaire WebSocket
│   ├── kb/
│   │   └── ehpad_watch_kb.json  # KB clinique v2 (15 scenarios, 8 archetypes)
│   └── requirements.txt
├── simulator/
│   ├── main.py                  # Simulateur 25 residents + rythme circadien
│   └── profiles.py
├── dashboard/
│   ├── public/
│   │   ├── index.html           # Dashboard soignant principal
│   │   ├── famille.html         # Espace famille (login par compte)
│   │   └── admin_famille.html   # Administration comptes famille
│   └── server.js
├── mosquitto/config/
├── docs/
│   ├── architecture.md          # Architecture technique detaillee
│   ├── demo.md                  # Guide de demonstration oral
│   └── comptes_famille_demo.md  # Identifiants demo famille
└── tests/
    └── test_ehpad.py            # 60+ tests pytest
```

---

## Securite

Controles integres :

- Sessions famille 24 h et personnel 8 h, stockees dans Redis.
- Roles stricts cote backend : soignant referent, chef de garde, direction.
- Bris de glace trace si un soignant ouvre un DPI hors perimetre pendant une alerte.
- Journal d'acces DPI, actions notification, echecs login et appels SAMU simules.
- CORS limite via `ALLOWED_ORIGINS`, rate limiting sur les logins, headers de securite HTTP.
- Redis protege par mot de passe via `REDIS_PASSWORD`.
- Secrets sortis du code : copier `.env.example` vers `.env` et remplacer les valeurs.

Documentation detaillee : [docs/securite_rgpd.md](docs/securite_rgpd.md)

---

## Verification avant rendu

```powershell
docker compose down
docker compose up --build -d
docker compose ps
py -m pytest tests/ -q
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8001/api/ml/metrics
Invoke-RestMethod http://localhost:8001/api/kb/scenarios
Invoke-RestMethod http://localhost:8001/api/residents/R005
```

Attendu : services `healthy`, 25 residents charges, 15 scenarios KB, metriques ML avec sensibilite/specificite.
