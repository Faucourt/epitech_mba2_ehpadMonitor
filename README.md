# EHPAD Monitor - Detection de malaise intelligente

Systeme IoT/IA de detection et prediction de malaises pour EHPAD.

**20 residents simules - Plan RDC + 1er etage - Alertes 5 niveaux - Prediction ML - Dashboard temps reel - Demo R005 declenchable**

---

## Demarrage rapide

```powershell
docker compose up --build -d
docker compose ps
```

Services exposes sur la machine hote :

| Service | URL |
|---|---|
| Dashboard | http://localhost:3002 |
| Backend API | http://localhost:8001 |
| Healthcheck API | http://localhost:8001/health |
| Metriques ML | http://localhost:8001/api/ml/metrics |
| InfluxDB | http://localhost:8086 |
| MQTT | localhost:1883 |

Arret :

```powershell
docker compose down
```

---

## Scenario demo garanti

Le mode demo est active dans `docker-compose.yml` :

```yaml
DEMO_RESIDENT=R005
```

Effet attendu :

1. Le simulateur force le scenario `hypoxie` sur R005.
2. Les constantes de R005 se degradent progressivement.
3. Le backend force un risque ML visible (`0.72`) pour illustrer "ML signale le risque 30 min avant".
4. Le dashboard affiche un bouton `Demo R005`, un bandeau de suivi, le scenario actif, le niveau d'alerte et un scope clinique live.

Pour la presentation :

1. Ouvrir http://localhost:3002.
2. Cliquer sur `Demo R005`.
3. Montrer `ML 72% signale 30 min avant`.
4. Montrer `scenario_active: hypoxie` via http://localhost:8001/api/residents/R005.
5. Montrer les alertes et l'escalade si elles ne sont pas acquittees.

---

## Architecture

```text
Simulateur Python
  - 20 residents sur 2 niveaux
  - constantes vitales
  - accelerometre
  - capteurs ambiants
  - scenario demo R005
        |
        v MQTT
Mosquitto
        |
        v
Backend FastAPI
  - prediction ML
  - moteur alertes 5 niveaux
  - escalade automatique
  - stockage Redis
  - historique InfluxDB
  - WebSocket dashboard
        |
        v
Dashboard HTML/JS
  - grille residents
  - detail resident
  - plan EHPAD
  - sparklines multi-metriques
  - scope clinique live inspire d'un moniteur patient
  - toasts et annonce vocale
```

---

## Fonctionnalites couvertes

### Must have

| Critere | Implementation |
|---|---|
| Simulateur 20 residents | 20 residents avec profils cliniques alignes sur le plan Word |
| Capteurs ambiants | Zones RDC + 1er etage : entree, patio, couloirs, salles, cuisine, soins |
| Communication MQTT | Mosquitto, mapping `ehpad/{zone}/{resident_id}/{type_capteur}` + compatibilite dashboard |
| Dashboard multi-residents | Grille, detail, plan, alertes |
| Alertes 5 niveaux | Information, Attention, Alerte, Urgence, Danger vital |
| Docker Compose | Stack complete avec healthchecks |
| Documentation | README, architecture, script demo |

### Should have

| Critere | Implementation |
|---|---|
| Prediction ML | GradientBoostingClassifier scikit-learn |
| Metriques ML | Endpoint `/api/ml/metrics` |
| Plan etablissement | SVG interactif RDC + 1er etage |
| Historique comportemental | Buffer 60s et sparklines |
| Escalade automatique | Niveau 2 -> 3 -> 4 -> 5 |
| Gestion personnel | Soignant assigne par resident |

### Could have

| Critere | Implementation |
|---|---|
| Detection fugue | Alerte entree hors horaires |
| Rapport resident | Endpoint `/api/llm/report/{id}` |
| Interface famille | Detail resident filtre via API |
| Tests automatises | 25 tests pytest dont tests API httpx |

---

## API REST

| Endpoint | Description |
|---|---|
| `GET /health` | Etat backend + Redis |
| `GET /api/residents` | Tous les residents + etat courant |
| `GET /api/residents/{id}` | Detail d'un resident |
| `GET /api/residents/{id}/history?minutes=60` | Historique InfluxDB |
| `GET /api/alerts` | Alertes actives + historique |
| `POST /api/alerts/{id}/acknowledge?by=nom` | Acquitter une alerte |
| `GET /api/zones` | Etat des zones ambiantes |
| `GET /api/summary` | Resume global EHPAD |
| `GET /api/ml/metrics` | Accuracy, AUC, F1 et features ML |
| `GET /api/llm/report/{id}` | Rapport quotidien resident |
| `WS /ws` | Flux temps reel dashboard |

Exemples :

```powershell
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8001/api/ml/metrics
Invoke-RestMethod http://localhost:8001/api/residents/R005
```

---

## Alertes

| Niveau | Nom | Declencheurs principaux | Escalade |
|---|---|---|---|
| 1 | Information | Inactivite | - |
| 2 | Attention | SpO2 < 95, FC > 100, ML > 50% | vers 3 en 10 min |
| 3 | Alerte | SpO2 < 93, FC > 120, ML > 75% | vers 4 en 5 min |
| 4 | Urgence | Chute, SpO2 < 88, FC > 140 | vers 5 en 3 min |
| 5 | Danger vital | SpO2 < 85 + FC > 130, PA critique | notification maximale |

---

## Modele ML

- Algorithme : `GradientBoostingClassifier` — choisi pour sa robustesse sur données tabulaires médicales hétérogènes, sa résistance aux outliers et l'interprétabilité via feature importance (vs. SVM ou réseau de neurones).
- Pipeline : `StandardScaler` → classifieur (100 estimateurs, lr=0.1, max_depth=4).
- Données : 5000 exemples synthétiques générés au premier démarrage.
- Features (9) : FC, SpO2, PA systolique, température, inactivité, tendances FC/SpO2 sur 10 min, facteur âge, facteur risque pathologies.
- Métriques exposées : accuracy, AUC-ROC, F1, **sensibilité** (recall classe 1 — faux négatif = malaise manqué), **spécificité** (recall classe 0 — faux positif = fatigue du personnel), matrice de confusion, importance des features.
- Persistance : `/app/ml_model.joblib`.
- Endpoint : `GET /api/ml/metrics`.
- Note split : entraînement sur données i.i.d. synthétiques → split aléatoire acceptable. Sur données réelles, un **split temporel** serait obligatoire pour éviter le data leakage.

---

## Redis et persistance

Redis est configure avec AOF :

```yaml
command: redis-server --appendonly yes --appendfsync everysec
volumes:
  - redis_data:/data
```

Objectif : conserver les donnees importantes et les alertes actives malgre un redemarrage de conteneur.

---

## Tests

Installation locale si besoin :

```powershell
py -m pip install -r backend/requirements.txt
py -m pip install pytest httpx
```

Execution :

```powershell
py -m pytest .\tests -q
```

Etat actuel valide :

```text
Non relance ici : Python indisponible dans le shell courant.
```

Couverture :

- moteur d'alertes,
- prediction ML,
- simulateur,
- tests d'integration API avec `httpx`.

---

## Structure

```text
.
|-- docker-compose.yml
|-- backend/
|   |-- main.py
|   |-- alert_engine.py
|   |-- ml_model.py
|   |-- ws_manager.py
|   `-- requirements.txt
|-- simulator/
|   |-- main.py
|   |-- profiles.py
|   |-- patients.json
|   `-- requirements.txt
|-- dashboard/
|   `-- public/index.html
|-- mosquitto/config/
|-- docs/
|   |-- architecture.md
|   `-- demo.md
`-- tests/test_ehpad.py
```

---

## Rapport LLM quotidien (C2)

L'endpoint `GET /api/llm/report/{id}` appelle **Meditron:7b via Ollama** (local), un LLM open-source fine-tuné sur PubMed et des guidelines médicales. Aucune donnée patient ne quitte le système — conformité RGPD. Si Ollama n'est pas joignable, un résumé textuel de secours est retourné.

Prérequis : Ollama doit tourner sur la machine hôte (`ollama serve`) avant `docker compose up`.

---

## Securite — Note importante

> **Configuration développement uniquement.**
> Les credentials suivants sont intentionnellement simplifiés pour faciliter le démarrage :
> - Token InfluxDB : `ehpad-super-secret-token`
> - Redis : sans mot de passe
> - MQTT : sans authentification
>
> En production : activer TLS sur MQTT (port 8883), configurer `requirepass` Redis, remplacer le token InfluxDB par une variable d'environnement injectée via un secret manager (Vault, Docker Secrets).

---

## Verification avant rendu

```powershell
docker compose down
docker compose up --build -d
docker compose ps
py -m pytest .\tests -q
Invoke-RestMethod http://localhost:8001/api/ml/metrics
Invoke-RestMethod http://localhost:8001/api/residents/R005
```

Tout doit montrer :

- services Docker `healthy`,
- tests pytest a relancer des que Python est disponible,
- metriques ML disponibles,
- R005 avec `scenario_active = hypoxie` et `ml_risk = 0.72`.
