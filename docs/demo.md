# Script de demonstration - EHPAD Monitor

Objectif de la demo : montrer un resident dont les constantes se degradent, avec une prediction ML visible avant l'alerte clinique forte.

Resident de demo : `R005`  
Scenario force : `hypoxie`  
Dashboard : http://localhost:3002  
Backend : http://localhost:8001

---

## 1. Demarrage propre

```powershell
docker compose down
docker compose up --build -d
docker compose ps
```

Point a montrer :

- tous les services sont `healthy`,
- Redis, Mosquitto, InfluxDB, backend, dashboard et simulateur sont lances,
- le simulateur a `DEMO_RESIDENT=R005`.

Phrase possible :

> La stack est entierement dockerisee. Les services ne demarrent que quand leurs dependances sont healthy.

---

## 2. Verification API

```powershell
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8001/api/ml/metrics
Invoke-RestMethod http://localhost:8001/api/residents/R005
```

Points a montrer :

- `/health` renvoie `status: ok`,
- `/api/ml/metrics` expose `accuracy`, `auc`, `f1`, l'algorithme et les features,
- R005 contient `scenario_active: hypoxie`,
- R005 contient `ml_risk: 0.72`.

Phrase possible :

> Le backend enrichit les donnees IoT avec une prediction ML et evalue ensuite les alertes.

---

## 3. Dashboard temps reel

Ouvrir :

```text
http://localhost:3002
```

Actions :

1. Montrer la grille des 25 residents.
2. Cliquer sur `Demo R005`.
3. Montrer le bandeau de demo.
4. Ouvrir le detail resident.
5. Montrer le scope clinique live, les constantes, le risque ML, les sparklines et l'alerte active.

Points a dire :

- le scenario `hypoxie` fait baisser progressivement la SpO2,
- le risque ML est visible avant l'alerte clinique forte,
- le dashboard recoit les mises a jour en WebSocket,
- le scope clinique live rend la demo plus lisible, comme un moniteur patient,
- les cartes changent de couleur selon le niveau d'alerte.

Phrase possible :

> Ici R005 est en hypoxie forcee. Le ML signale un risque a 72%, ce qui materialise la detection predictive avant la degradation clinique severe.

---

## 4. Alertes et escalade

Points a montrer :

- sidebar des alertes actives,
- niveau d'alerte sur la carte resident,
- bouton d'acquittement,
- historique alertes.

Phrase possible :

> Les alertes sont graduees sur 5 niveaux. Si une alerte n'est pas acquittee, le moteur l'escalade automatiquement.

---

## 5. Architecture technique

Resume a presenter :

```text
Simulateur -> MQTT Mosquitto -> Backend FastAPI -> Redis/InfluxDB -> WebSocket -> Dashboard
```

Points forts :

- MQTT pour le flux IoT,
- Redis pour l'etat courant et les alertes actives,
- InfluxDB pour l'historique temporel,
- WebSocket pour le temps reel,
- Docker Compose avec healthchecks,
- tests unitaires et tests d'integration API.

---

## 6. Tests qualite

Commande :

```powershell
py -m pytest .\tests -q
```

Resultat attendu :

```text
25 passed
```

Phrase possible :

> Les tests couvrent le moteur d'alertes, le modele ML, le simulateur et plusieurs endpoints API avec httpx.

---

## 7. Captures conseillees pour le rendu

Faire une capture de :

- `docker compose ps` avec tous les services healthy,
- dashboard avec le bandeau `Demo R005`,
- detail R005 avec ML et constantes,
- `/api/ml/metrics`,
- `25 passed`,
- extrait `docker-compose.yml` montrant Redis AOF et `DEMO_RESIDENT=R005`.

---

## 8. Plan oral en 2 minutes

1. **Contexte** : detection de malaise en EHPAD, suivi de 25 residents.
2. **Architecture** : simulateur IoT, MQTT, backend, Redis, InfluxDB, dashboard.
3. **Prediction** : ML calcule un risque de malaise 30-60 minutes.
4. **Demo** : R005 en hypoxie, ML a 72%, constantes qui se degradent.
5. **Alertes** : niveaux 1 a 5, escalade, acquittement.
6. **Qualite** : Docker healthchecks, Redis persistant, tests automatises.

Conclusion possible :

> Le projet couvre la chaine complete : simulation de donnees, detection temps reel, prediction, alertes, visualisation et verification technique.
