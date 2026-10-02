# Bancs Wokwi vérifiés

21 familles, 62 scénarios réussis avec réception MQTT dans le backend local.
Chaque empreinte du firmware correspond à la matrice de compilation. Les traces série et les échantillons reçus sont conservés dans `wokwi/`.

**Portée :** un banc ESP32 exécuté par famille. Les 437 configurations couvrent les 25 résidents et 20 zones ; elles ne tournent pas simultanément.

Ouvrir un lien puis démarrer la simulation (▶). Le banc publie pour l’identifiant indiqué, pas pour les autres résidents. Le dashboard local doit écouter le même courtier MQTT.

| Famille | Identifiant du banc | Scénarios réussis | Projet |
|---|---|---:|---|
| amg8833 | `patio-camera_thermique-amg8833` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794160713963521) |
| ble | `couloir_aile_rdc-ble_beacon-ble` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794199564766209) |
| dht22 | `entree-ambiant-dht22` | 2 | [Ouvrir Wokwi](https://wokwi.com/projects/476794223981912065) |
| door | `R001-porte-door` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794275606473729) |
| ecg | `R001-wearable-ecg` | 2 | [Ouvrir Wokwi](https://wokwi.com/projects/476793911048984577) |
| gps | `hors_ehpad-gps_bracelet-gps` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794292876527617) |
| hx711 | `R001-matelas-hx711` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794251138992129) |
| max30102 | `R001-wearable-max30102` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794031039670273) |
| mpu6050 | `R001-wearable-mpu6050` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476795053855594497) |
| mq2 | `entree-fumee-mq2` | 2 | [Ouvrir Wokwi](https://wokwi.com/projects/476795116182973441) |
| nibp | `R001-wearable-nibp` | 6 | [Ouvrir Wokwi](https://wokwi.com/projects/476796015218635777) |
| pir | `R001-pir-pir` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794333563386881) |
| radar | `R002-radar-radar` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794056911192065) |
| respiration | `R001-wearable-respiration` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476793774682694657) |
| rfid | `entree-rfid-rfid` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476795205305687041) |
| scd41 | `entree-co2-scd41` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794116085505025) |
| sgp40 | `entree-ambiant-sgp40` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476795239696897025) |
| sos | `R001-wearable-sos` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794303181936641) |
| sound | `entree-son-sound` | 2 | [Ouvrir Wokwi](https://wokwi.com/projects/476794319373004801) |
| tmp117 | `R001-wearable-tmp117` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476793955220259841) |
| ze07co | `entree-co-ze07co` | 3 | [Ouvrir Wokwi](https://wokwi.com/projects/476794248147402753) |

## Commandes particulières

- Tensiomètre PAR : attendre 8 secondes simulées au démarrage, puis presser START. STOP annule le cycle. Les curseurs règlent systolique, diastolique et erreurs. Aucune inflation automatique au démarrage.
- RFID : maintenir la carte avec Hold pour une lecture reproductible. Le bref Tap de 500 ms peut être manqué lorsque le navigateur simule plus lentement que le temps réel. La présence d’un UID signifie une lecture récente, pas une localisation continue.
- SGP40 : attendre la phase de stabilisation de l’algorithme avant l’indice COV. Le signal brut est disponible avant l’indice.
- BLE : ce banc teste un adaptateur I²C de données MAC/RSSI. Wokwi ne valide pas la radio BLE ; le scanner BLE réel a été compilé séparément.
- MQ-2 : le raccordement ADC direct est uniquement simulé. Le montage physique nécessite le pont diviseur décrit dans le README.

Ces essais valident les échanges de données du prototype. Aucun capteur physique, brassard pneumatique ou algorithme clinique n’a été validé par ces simulations.
