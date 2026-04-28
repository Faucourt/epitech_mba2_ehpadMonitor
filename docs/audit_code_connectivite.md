# Audit connectivite code - 2026-04-28

## Etat global

Le projet est fonctionnel et les services Docker principaux sont connectes :

- `ehpad_backend` : API, WebSocket, MQTT, alertes temps reel.
- `ehpad_llm_worker` : generation quotidienne des rapports LLM.
- `ehpad_dashboard` : interface principale.
- `ehpad_simulator` : simulation MQTT.
- `redis`, `influxdb`, `mosquitto` : stockage/cache/transport.

Le worker LLM est bien separe du backend et genere les rapports quotidiens.

## Bien connecte

- Dashboard principal `index.html` vers :
  - `/api/residents`
  - `/api/alerts`
  - `/api/residents/{id}/history?minutes=30`
  - `/api/reports/daily/{date}`
  - `/api/reports/daily/generate`
  - `/api/residents/{id}/dpi`
  - `/api/llm/report/{id}`
  - `/api/llm/daily/{date}`
  - `/api/staff`
  - `/api/notifications/*`
  - `/api/simulator/*`
  - `/api/project/readiness`
  - `/api/scenarios/life-plan`
  - `/api/a2a/predictions`
  - `/api/sensors/health`
  - `/api/ops/scalability`

- Pages dediees :
  - `/soignant` et `/soignant/{id}` -> `soignant.html`
  - `/resident/{id}` -> `resident.html`
  - `/mobile/resident/{id}` -> `mobile_resident.html`
  - `/simulateur/config` -> `simulateur_config.html`
  - `/famille.html` -> espace famille
  - `/admin_famille.html` -> administration comptes famille

## Connecte mais plutot debug/API technique

Ces endpoints sont utiles pour verification, documentation ou debug, mais ne sont pas integres dans un ecran metier principal :

- `/api/kb/scenarios`
- `/api/kb/scenarios/{scenario_id}`
- `/api/kb/archetypes`
- `/api/kb/residents`
- `/api/ml/metrics`
- `/api/a2a/agents`
- `/api/summary`
- `/api/reports/today`
- `/api/alerts/elopement`
- `/api/residents/{id}/routine`
- `/api/residents/{id}/dossier/history`
- `/api/llm/audit`

Recommandation : creer une page "Validation technique" plus claire ou documenter qu'ils sont volontairement API/debug.

## Partiellement connecte

- `/api/llm/report/{id}/start` et `/api/llm/result/{job_id}`
  - Le backend les expose.
  - Le frontend utilise plutot `/api/llm/report/{id}` synchrone/cache.
  - A garder si on veut un vrai mode asynchrone plus tard, sinon c'est redondant.

- `/api/alerts/{resident_id}/acknowledge`
  - Le dashboard acquitte surtout via WebSocket.
  - La route REST reste utile pour mobile/API, mais elle n'est pas le chemin principal.

## Points a surveiller

- `backend/worker.py` importe `main.py`, ce qui initialise aussi certains objets lourds du backend.
  - Fonctionnel aujourd'hui.
  - Plus propre a terme : extraire les fonctions partagees dans un module `services/` pour eviter les effets de bord.

- `predictive_analysis_loop()` calcule deux fois la prediction A2A pour un resident :
  - une fois avant `_remember_prediction`
  - une fois apres
  - Ce n'est pas mort, mais c'est un petit gaspillage CPU.

- Plusieurs endpoints renvoient 404 de facon normale quand il n'y a pas d'alerte active :
- `/api/alerts/explain/{resident_id}`
  - Corrige : retourne maintenant `200` avec `alert: null` quand aucune alerte n'est connue.
  - Cela evite les faux signaux 404 dans les logs.

## Mort probable / a nettoyer prudemment

Rien de critique a supprimer immediatement.

Les candidats a clarification ou suppression apres validation :

- Le mode LLM async `/start` + `/result` si on garde uniquement le cache quotidien.
- Les endpoints KB/ML/A2A debug si le rendu final ne doit pas exposer d'API technique.
- Les anciennes donnees de demo non utilisees hors `data/patients/*` si elles ne sont plus referencees.

## Recommandation prioritaire

1. Ne rien supprimer maintenant.
2. Ajouter une page "Technique / Validation" qui expose clairement :
   - metriques ML,
   - audit LLM,
   - scenarios KB,
   - agents A2A,
   - sante capteurs,
   - scalabilite.
3. Fait : les 404 attendus d'`alerts/explain` ont ete remplaces par une reponse vide en 200.
4. Plus tard, extraire le code partage backend/worker pour rendre l'architecture plus propre.
