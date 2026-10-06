# Contrat MQTT — EHPAD / Digi5 M1

Option B : le dashboard Digi4 principal (`/`, `dashboard/public/index.html`) reçoit directement le flux Digi5 en MQTT over WebSocket via `wokwi-feed.js` et `wokwi-dashboard.js`. P001 rejoint la grille multi-résidents et son panneau de détail affiche la FC, la courbe, SOS, chute et l'état du dispositif. Les 25 résidents historiques restent alimentés par leur backend. La page `/m1.html` est conservée comme outil de diagnostic.

P001 est un patient fictif distinct de R001 : aucune donnée des résidents historiques n'est écrasée. Les événements pédagogiques restent dans sa fiche, avec leurs niveaux `info` / `warning` / `danger` ; ils ne déclenchent pas le moteur clinique, les notifications soignants ni un score IA. La FC courante est masquée dès la déconnexion du broker, l'état offline, ou après 15 secondes sans mesure. La courbe et les événements sont conservés en mémoire pendant la session navigateur. Le bouton Wokwi dans la grille ouvre la fiche P001.

| Élément | Digi4 existant | Digi5 M1 retenu |
|---|---|---|
| Racine | `ehpad` | `digi5/lebretyves-ehpad-m1` |
| Mesures | `ehpad/residents/{resident_id}/vitals` | `digi5/lebretyves-ehpad-m1/patient/P001/vitals` |
| Événements | `ehpad/residents/{resident_id}/critical`, alertes calculées backend | `digi5/lebretyves-ehpad-m1/patient/P001/alerts` |
| État device | pas de topic équivalent dans le simulateur | `digi5/lebretyves-ehpad-m1/device/esp32-01/status` |
| Identifiant | `resident_id` | `patient_id`, normalisé en `resident_id` |
| FC | `vitals.heart_rate` | `heart_rate`, normalisé en `vitals.heart_rate` |
| Horodatage | `timestamp` / `timestamp_real` | `timestamp`, ISO 8601 UTC ; vide avant NTP, heure de réception utilisée pour l'affichage |
| Alertes | moteur 1 info, 2 attention, 3 alerte, 4 urgence, 5 danger vital | `info`, `warning`, `danger`, conservés comme niveaux pédagogiques ; pas d'équivalence clinique automatique |
| Broker | variables MQTT_HOST / MQTT_PORT, défaut localhost:1883, Mosquitto dans Compose | `broker.hivemq.com:1883`, TCP public sans authentification pour ESP32 |
| Navigateur | API/backend existant | MQTT.js sur `wss://broker.hivemq.com:8884/mqtt`, intégré au dashboard principal en parallèle du backend |

## Messages

Mesures toutes les 2 secondes, QoS 0, non retenues. Champs : `patient_id`, `device_id`, `source: esp32`, `seq`, `timestamp`, `heart_rate`, `accel_g: {x,y,z}`, `accel_peak_g`, `imu_ok`, `alert_level`. La FC est un substitut fourni par un potentiomètre (30–180 bpm), les accélérations proviennent du MPU-6050 simulé.

Alertes événementielles : `patient_id`, `device_id`, `type`, `level`, `value`, `timestamp`. Types `sos`, `fall_suspected`, `hr_out_of_range`. FC warning si <50 ou >110, danger si <40 ou >130 ; limites strictes. Alerte FC au changement de niveau vers warning/danger. Chute suspectée si norme >2,5 g, au maximum une alerte par 10 s. Buzzer 3 s sur SOS, chute et FC danger.

État retenu : `{"state":"online","device_id":"esp32-01"}`. Last Will retenu QoS 1 : `{"state":"offline"}`. Keep-alive 30 s, détection de disparition typiquement sous 45 s. PubSubClient publie les mesures/alertes en QoS 0 : pas de garantie de réception ni de stockage hors ligne.

Le dashboard distingue le broker connecté, l'état du device et la fraîcheur des mesures. Il masque la valeur courante lorsque le flux devient ancien. Les anciennes valeurs restent dans l'historique.

SpO2, température, pression artérielle et respiration ne sont pas mesurées : `null` et « Non mesuré ». Aucun score médical ne doit être déduit de valeurs par défaut.

Uniquement des identifiants et données fictifs. Aucun identifiant HiveMQ Cloud ni mot de passe dans le firmware partagé.
