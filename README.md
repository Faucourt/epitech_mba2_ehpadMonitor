# EHPAD Monitor - Detection et prediction de malaise

Plateforme IoT/IA de supervision EHPAD : simulation de residents, capteurs MQTT,
dashboard temps reel, alertes graduees, prediction 30-60 minutes, espace soignant
et portail famille.

Projet Epitech MBA1 - 25 residents simules - Docker Compose.

## Demarrage rapide

```powershell
docker compose up --build -d
docker compose ps
```

LLM optionnel :

```powershell
ollama serve
```

Le projet fonctionne sans Ollama : les rapports LLM ont un repli automatique.

## URLs utiles

| Service | URL |
|---|---|
| Dashboard principal | http://localhost:3002 |
| Espace soignant | http://localhost:3002/soignant |
| Fiche resident | http://localhost:3002/resident/R005?from=dashboard&return=/ |
| Fiche mobile intervention | http://localhost:3002/mobile/resident/R005 |
| Espace famille | http://localhost:3002/famille.html |
| Admin familles | http://localhost:3002/admin_famille.html |
| Backend API | http://localhost:8001 |
| Swagger | http://localhost:8001/docs |
| InfluxDB | http://localhost:8086 |
| MQTT | localhost:1883 |

## Comptes de demonstration

| Espace | Identifiant | Mot de passe / token |
|---|---|---|
| Soignant A | `soignant_A` | `EHPAD2024!` |
| Soignant B | `soignant_B` | `EHPAD2024!` |
| Soignant C | `soignant_C` | `EHPAD2024!` |
| Chef de garde | `chef_garde` | `EHPAD2024!` |
| Direction | `direction` | `EHPAD2024!` |
| Famille Edith Piaf | `piaf` | `piaf105` |
| Famille Marie Curie | `curie` | `curie101` |
| Famille Dalida | `dalida` | `dalida214` |
| Admin familles | token admin | `ADMIN_EHPAD_2024` |

La liste complete des comptes famille est dans
`docs/comptes_famille_demo.md`.

## Architecture

```text
Simulateur Python
  - 25 residents
  - constantes vitales
  - capteurs chambre / zone
  - scenarios chute, hypoxie, fugue, danger vital
        |
        v MQTT QoS 0/1/2
Mosquitto
        |
        v
Backend FastAPI
  - moteur d'alertes 5 niveaux
  - NEWS2
  - prediction ML 30-60 min
  - analyse de routine
  - Redis et InfluxDB
  - API REST et WebSocket
        |
        v
Dashboard HTML/JS statique
  - grille 25 residents
  - mini DPI
  - plan 2D et vue 3D
  - espace soignant
  - espace famille
  - scalabilite et transmissions
```

## Services Docker

| Service | Role |
|---|---|
| `mosquitto` | Broker MQTT |
| `redis` | Etat courant, sessions, cache |
| `influxdb` | Historique capteurs |
| `simulator` | Publication capteurs et scenarios |
| `backend` | API, WebSocket, ML, alertes |
| `llm_worker` | Rapports LLM quotidiens optionnels |
| `dashboard` | Serveur HTML statique Express |

## Fonctionnalites principales

| Critere | Etat |
|---|---|
| 20+ residents simules | OK, 25 residents |
| Capteurs vitaux | OK : FC, SpO2, PA, temperature, FR |
| Capteurs ambiants | OK : porte, lit, PIR, radar, sol, salle de bain |
| MQTT QoS | OK : vitaux QoS 1, critiques QoS 2, ambiants QoS 0 |
| Dashboard multi-residents | OK |
| Alertes 5 niveaux | OK : Information a Danger vital |
| Mini DPI resident | OK, acces dashboard sans prompt soignant |
| Personnel / soignant | OK : login, affectations, notifications, audit |
| Famille | OK : vue non medicale, comptes individuels |
| ML prediction | OK : risque 30/60 min + pipeline A2A |
| Plan / capteurs | OK : SVG 2D, Three.js 3D, qualite/batterie |
| Scalabilite | OK : endpoint dedie, stats MQTT/Redis/WebSocket |

## Endpoints importants

| Endpoint | Description |
|---|---|
| `GET /health` | Sante backend et residents charges |
| `GET /api/residents` | Etat live des 25 residents |
| `GET /api/alerts` | Alertes actives et historique |
| `GET /api/alerts/config` | Configuration des 5 niveaux |
| `GET /api/reports/daily/{date}/{resident_id}` | Mini DPI / rapport resident frais |
| `GET /api/a2a/predictions` | Predictions 30/60 min pour tous les residents |
| `GET /api/ml/metrics` | Metriques ML |
| `GET /api/staff` | Personnel, affectations, notifications |
| `POST /api/staff/login` | Connexion soignant |
| `POST /api/famille/login` | Connexion famille |
| `GET /api/famille/{resident_id}` | Vue famille protegee |
| `GET /api/ops/scalability` | Scalabilite MQTT/Redis/WebSocket |
| `WS /ws` | Flux temps reel dashboard |

## ML et limites

Le modele ML est une preuve de concept entrainee sur donnees synthetiques.
Il sert a demontrer une chaine predictive 30-60 minutes, pas a fournir un
diagnostic medical.

Points a expliquer au jury :

- donnees synthetiques, donc validation clinique necessaire avant usage reel ;
- split temporel necessaire sur donnees reelles ;
- le ML n'agit pas seul : il est combine avec NEWS2, routines, capteurs et
  regles metier ;
- le dashboard affiche les signaux et recommandations pour aider le soignant,
  pas pour remplacer une decision medicale.

## Scenario de demonstration conseille

1. Lancer `docker compose up --build -d`.
2. Ouvrir http://localhost:3002.
3. Montrer les 25 residents et les constantes live.
4. Ouvrir le Mini DPI d'un resident depuis le dashboard.
5. Montrer plan 2D / 3D et capteurs actifs.
6. Montrer les alertes 5 niveaux via config et historique.
7. Montrer l'espace soignant avec `chef_garde / EHPAD2024!`.
8. Montrer l'espace famille avec `piaf / piaf105`.
9. Montrer ML/A2A : predictions 30/60 min.
10. Finir par `/api/ops/scalability`.

Guide plus detaille : `docs/demo.md`.

## Tests et verification

```powershell
py -m pytest tests -q
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8001/api/residents
Invoke-RestMethod http://localhost:8001/api/alerts/config
Invoke-RestMethod http://localhost:8001/api/ml/metrics
Invoke-RestMethod http://localhost:8001/api/ops/scalability
```

Attendu :

- backend et dashboard healthy ;
- 25 residents charges ;
- alertes 5 niveaux configurees ;
- predictions ML disponibles ;
- statistiques MQTT recentes.

## Structure actuelle

```text
.
|-- backend/
|   |-- main.py
|   |-- alert_engine.py
|   |-- ml_model.py
|   |-- a2a_agents.py
|   |-- auth.py
|   |-- llm_service.py
|   |-- routine_engine.py
|   |-- kb/
|   `-- requirements.txt
|-- simulator/
|   |-- main.py
|   |-- profiles.py
|   |-- facility_map.py
|   `-- requirements.txt
|-- dashboard/
|   |-- public/
|   |   |-- index.html
|   |   |-- resident.html
|   |   |-- mobile_resident.html
|   |   |-- soignant.html
|   |   |-- famille.html
|   |   `-- admin_famille.html
|   |-- server.js
|   |-- package.json
|   `-- Dockerfile
|-- mosquitto/config/mosquitto.conf
|-- docs/
|-- tests/test_ehpad.py
`-- docker-compose.yml
```

## Securite

- Sessions soignant et famille stockees dans Redis.
- Acces DPI protege pour les pages soignant.
- Acces dashboard au Mini DPI sans prompt, via rapport resident non modifiant.
- Vue famille volontairement limitee : pas de constantes vitales ni scores
  cliniques.
- Logs d'acces, notifications, bris de glace et actions d'alerte.
- Certificats locaux exclus du Git via `.gitignore`.

## Arret

```powershell
docker compose down
```
