# Du simulateur d'origine à l'acquisition matérielle

Référence : `simulator/main.py`, méthodes `ResidentSimulator.tick`,
`AmbientSensorSimulator.tick`, `EHPADSimulator._publish_resident` et `_publish_ambient`.
L'inventaire charge réellement `simulator/profiles.py` ; ses identifiants ne sont pas
recopiés manuellement. Un test échoue si un rôle de capteur n'est pas mappé.

## Topics d'origine

| Topic | Contenu observé dans le code du simulateur |
|---|---|
| `ehpad/residents/<Rxxx>/vitals` | état résident complet, vitaux, mouvement, contexte |
| `ehpad/residents/<Rxxx>/movement` | mouvement et événements de chambre (option legacy) |
| `ehpad/residents/<Rxxx>/location` | position et activité synthétiques (option legacy) |
| `ehpad/residents/<Rxxx>/critical` | événement de chute synthétique |
| `ehpad/<chambre>/<Rxxx>/vitals`, `/motion`, `/bp_temp` | doublons historiques optionnels |
| `ehpad/<chambre>/<Rxxx>/sos` | bouton SOS |
| `ehpad/zones/<zone>/ambient` | environnement et événements de zone ou de chambre |
| `ehpad/<zone>/ambient/env`, `ehpad/<zone>/door/ambient` | variantes historiques |
| `ehpad/summary` | agrégation des états simulés |

Le simulateur émet température, humidité, CO₂, COV, fumée, CO et son **dans chacune
des 20 zones**, même lorsqu'ils ne figurent pas dans `zone.sensors`. Les exports
ajoutent les interfaces correspondantes dans toutes ces zones. `declared_sensors`
conserve la liste initiale ; `sensors` décrit la couverture étendue.

## Topics d'acquisition

- Wokwi : `ehpad/lab/lebretyves-all/v1/<device_id>/telemetry`
- Matériel : `ehpad/hardware/v1/<device_id>/telemetry`
- Disponibilité MQTT : même base, suffixe `/status` ; LWT retained `online:false`.

Exemple de mesure, sans nom, pathologie ni donnée issue du dossier patient :

```json
{
  "schema": 1,
  "device_id": "R001-wearable-max30102",
  "entity_id": "R001",
  "kind": "max30102",
  "source": "wokwi",
  "boot": "a4c72e",
  "seq": 51,
  "uptime_ms": 102000,
  "available": true,
  "sample_age_ms": 10,
  "values": {"heart_rate": 75, "spo2": 93, "red_raw": 55000, "ir_raw": 60000}
}
```

PubSubClient publie les télémesures en QoS 0, non retained, toutes les 2 secondes.
Le SOS et l'impact sont maintenus 3 secondes pour être visibles sur au moins une
publication lorsque la connexion fonctionne. **Ce protocole de démonstration ne
garantit pas la remise d'une alarme pendant une coupure réseau** : une file persistante
avec acquittements doit être ajoutée avant tout déploiement d'alerte opérationnel.

Le backend valide topic, appareil, affectation, modèle, source, types, bornes,
séquence et session de démarrage. Il refuse les télémesures retained, les NaN,
les champs inconnus, les booléens numériques et les messages rejoués de sessions
récentes. À 15 secondes de péremption, les valeurs ne sont plus présentées comme
actuelles. L'âge déclaré de l'échantillon est ajouté au temps écoulé depuis réception.
Les appareils sans message restent présents dans le dashboard.

## Correspondance des valeurs

L'objet `contract` de `/api/hardware/snapshot` expose les noms historiques lorsque
leur sens correspond à une acquisition. **Il n'est pas injecté dans le moteur
clinique d'origine**, qui suppose des valeurs complètes et utilise des défauts
normaux. Les cartes de l'écran d'acquisition utilisent les mesures brutes et leur
provenance. Les identités R001–R025 sont conservées, sans patient artificiel P001.

| Champs du simulateur | Acquisition / traitement |
|---|---|
| `heart_rate`, `spo2` | calcul SparkFun/Maxim sur FIFO MAX30102 ; null sans doigt ou fenêtre valide |
| `blood_pressure_sys`, `blood_pressure_dia` | pilote PAR NIBP2010 / NIBP2020 UP sans SpO2 ; résultat valide d'un cycle demandé |
| `temperature` | null : le TMP117 fournit `contact_temperature_c`, pas automatiquement une température centrale |
| `respiratory_rate` | estimation sur le signal d'une ceinture analogique, seuils à calibrer |
| `ecg_rhythm` | null : signal AD8232 brut ne suffit pas à annoncer sinus ou fibrillation |
| `accel_magnitude`, `gyro_magnitude_dps` | norme en g et norme gyroscope ; **la norme g inclut la gravité**, contrairement à certains scénarios synthétiques proches de 0 au repos |
| `altitude_drop_cm` | null : double intégration de l'accélération non ajoutée sans méthode fiable |
| `is_fall_detected`, `ambient_fall_confirmed` | null ; un impact est fourni séparément comme événement à vérifier |
| `is_sleeping`, `activity`, `last_movement_ago_s` | null : fonctions d'inférence et de suivi non assimilées à un signal brut |
| `sos_pressed` | bouton GPIO débouncé |
| `room_pir_motion`, `bathroom_motion` | deux affectations PIR distinctes |
| `room_radar_presence` | sortie présence LD2410 |
| `door_open` | contact NC ; fil ouvert a le même état électrique que porte ouverte |
| `bed_occupied`, `mattress_exit`, `floor_pressure_event` | charge HX711 disponible ; seuils/chronologie métier à calibrer avant inférence |
| `fall_confirmed_by_room_sensor`, `radar_immobile_low`, `fall_confirmed` | null : le LD2410 OUT n'identifie pas une personne au sol |
| `temperature_c`, `humidity_pct` | DHT22/SCD41 |
| `co2_ppm` | SCD41, avec CRC ; différent de l'eCO₂ du SGP30 optionnel |
| `voc_index` | SGP40 + algorithme constructeur ; null pendant initialisation |
| `co_ppm` | ZE07‑CO, checksum et unités validés |
| `smoke_ppm` | null : cette unité synthétique n'est pas déduite d'un MQ‑2 ; `gas_adc` disponible |
| `sound_db` | SEN0232, transfert 50 dBA/V du constructeur |
| `occupancy`, `resident_ids`, `ble_seen` | null ; PIR, UID ou RSSI seuls ne donnent pas un comptage fiable ni une identité |
| `position`, `current_zone`, `location`, `target_zone` | position GNSS disponible séparément ; repérage intérieur et association des badges restent à configurer |
| `sensor_health` | réception, âge, indisponibilité observée ; batterie et qualité radio non inventées |
| `timestamp_simulated`, `scenario_active`, `routine_context`, calendrier | propres au simulateur, aucune fausse mesure matérielle |
| profils, pathologies, proches, personnel | restent dans le backend d'origine, ne transitent pas par le broker public Wokwi |

Les capteurs thermiques publient en plus 64 températures réelles du protocole AMG8833,
alors que le simulateur d'origine n'émettait pas de matrice thermique.
Les fonctions `dashboard`, `alertes_5_niveaux`, `dashboard_central`,
`surveillance_etage`, `alerte_fugue` sont répertoriées comme fonctions logicielles,
pas comme composants électroniques.

## Tensiomètre : protocole constructeur PAR

Référence choisie : **PAR NIBP2010 / NIBP2020 UP sans SpO2**, protocole standard de
la [documentation constructeur, révision 2.12, sections 10–13](https://www.par-berlin.com/fileadmin/documents/produktdatenblaetter/NIBP_module-Tech.Descr._Doc.-Rev._2.12_-signed.pdf).
UART 4800 transporte des trames ASCII STX/ETX avec une somme modulo 256 en
hexadécimal. Les réponses se terminent par CR. Les commandes 24, 03, 01 et 18
sélectionnent adulte, manuel, démarrage, puis lecture du résultat. `X` annule.
Un intervalle supérieur à une seconde sépare les commandes ordinaires.

L'exemple chiffré de la section 13.5 affiche `D2`, mais la somme des octets de
cette trame selon la section 11.3 vaut `40`. Le pilote applique la règle de somme ;
le test C++ vérifie aussi l'exemple d'erreur de la section 13.6, dont `FC` est cohérent.

Le pilote attend la fin de cycle `999` avant de demander le résultat. Il contrôle
longueur, structure, somme, état, erreur et cohérence des pressions. Il refuse les
anciennes valeurs présentes dans une réponse d'erreur. Un nouveau démarrage
efface les constantes précédentes. Les valeurs périmées restent dans l'historique,
jamais présentées comme fraîches.

START (GPIO27) déclenche un cycle, STOP (GPIO26) l'annule. Le custom `par-nibp`
expose des curseurs systolique, diastolique, erreur, déconnexion et corruption de
somme. Il termine un cycle pédagogique en cinq secondes, sans modéliser la
pneumatique. Le code ESP32 est commun à Wokwi et au matériel.

La variante TTL du module utilise 5 V : adapter les niveaux vers l'ESP32 3,3 V.
La variante RS232 nécessite un transceiver. Aucune commande de calibration, de
manomètre ou de garrot n'est implémentée. Vérifier module, alimentation, brassard
et câblage physiques lors de l'intégration sur table.

## BLE et identification

L'ESP32 physique utilise `BLEDevice` et publie l'adresse/RSSI du périphérique le
plus puissant du scan. Cela n'associe pas automatiquement un résident et ne mesure
pas sa distance. En Wokwi, `ble-fixture` injecte une observation via I²C0x30 puisque
le simulateur ne fournit pas de radio BLE. Ce changement d'adaptateur est isolé par
`WOKWI_BUILD`; il est explicitement une exception au portage sans modification.

## Portée des tests

Les tests MQTT de masse envoient des jeux synthétiques identifiés comme tels pour
vérifier l'affectation et l'API. Ils ne prétendent pas avoir exécuté437 ESP32 dans
Wokwi. Les tests WebAssembly invoquent les véritables callbacks compilés des
customs. Les essais Firefox/ESP32 sont consignés séparément dans
`firmware/all_sensors/VALIDATION.md`.
