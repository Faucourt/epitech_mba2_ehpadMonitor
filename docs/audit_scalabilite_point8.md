# Point 8 - Scalabilite

Date audit: 2026-04-28

## Valide

- Simulateur parametrable via `NUM_RESIDENTS` dans `docker-compose.yml`.
- Configuration actuelle : 25 residents, soit 25 x 6 constantes = 150 constantes/s theoriques.
- Cible sujet 20 x 6 = 120 messages/s exposee dans `/api/ops/scalability`.
- Cible extension 50 x 6 = 300 constantes/s exposee.
- MQTT separe le flux temps reel du stockage et du dashboard.
- Redis stocke l'etat courant des residents et les caches courts.
- InfluxDB stocke les series temporelles avec echantillonnage controle.
- WebSocket est limite par resident pour eviter de pousser chaque message brut au navigateur.
- ML/A2A est hors boucle seconde : relance toutes les 5 minutes, cache 10 minutes.
- LLM est hors boucle temps reel : utilise pour transmission/rapport, pas pour chaque mesure.
- L'onglet Validation affiche maintenant le debit MQTT moyen, le debit MQTT 60s, la cible 20 residents, la cible 50 residents, l'age des etats Redis, l'estimation Influx et l'estimation WebSocket.

## Verification

- `GET /api/ops/scalability`: OK.
- Champs ajoutes : `scale_targets`, `messages_per_second_60s`, `window_60s_total`, `estimated_influx_points_per_second`, `estimated_ws_states_per_second`, `state_age_avg_s`, `state_age_max_s`.
- Dashboard `/`: OK, champs scalabilite affiches.
- Test cible `pytest tests/test_ehpad.py -k scalability`: OK.

## Reste a industrialiser

- Benchmark reel `NUM_RESIDENTS=50` puis `NUM_RESIDENTS=100`.
- Mesure p95/p99 latence API et WebSocket.
- Monitoring Prometheus/Grafana.
- Alertes d'exploitation si `last_message_age_s` ou `state_age_max_s` depassent un seuil.
- Politique de retention InfluxDB par bucket et downsampling mensuel/annuel.
