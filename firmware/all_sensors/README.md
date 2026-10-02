# Acquisition ESP32 et Wokwi

Projet d'origine : https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD

Cette extension reprend les identifiants R001–R025, les 25 chambres et les 20 zones
de `simulator/profiles.py`, ainsi que les canaux émis par `simulator/main.py`.
Elle fournit **437 bancs logiques indépendants**, générés à partir de 21 familles de
pilotes actives. Un banc associe un ESP32 et un capteur afin de tester son interface
sans conflit de broches. Ce nombre décrit les points d'acquisition du prototype,
pas une recommandation d'achat de 437 microcontrôleurs. Le regroupement de plusieurs
capteurs sur une carte, l'alimentation d'un bracelet et son autonomie relèvent du
dimensionnement du matériel final.

Le firmware ne boucle pas sur 25 résidents pour leur inventer des constantes :
chaque banc lit ses broches/bus, publie sous son propre identifiant et alimente
uniquement le résident ou la zone auquel il est affecté. Plusieurs bancs peuvent
fonctionner simultanément. Les équipements non lancés restent « en attente ».

## Démarrage du dashboard isolé

Depuis la racine du dépôt, avec Docker :

```powershell
$env:WOKWI_LAB_HOST = 'test.mosquitto.org'
docker compose -p ehpad-hardware -f docker-compose.hardware-lab.yml up -d --build
```

Ouvrir http://localhost:3005/hardware.html. Les 25 résidents et 20 zones sont présents
même sans simulation active. Le backend est sur http://localhost:8005.
Le service de simulation Python n'est pas lancé dans cette configuration.
Le dashboard historique reste accessible ; ses fonctions de simulation clinique
ne consomment pas les mesures partielles de cette extension.

Dans la stack principale, activer `WOKWI_LAB_ENABLED=true`, puis reconstruire le
backend et le dashboard. L'entrée d'acquisition se trouve dans le dashboard.
Le broker public ne sert qu'aux données synthétiques Wokwi. Le mode matériel
utilise le broker privé et exige une session soignant pour consulter l'API.

## Lancer un banc Wokwi

[Ouvrir les 21 projets vérifiés dans Firefox](validation/WOKWI.md) : un banc par
famille, 62 scénarios avec réception MQTT. Cliquer sur ▶ dans Wokwi pour démarrer
un banc ; le laisser ouvert pour conserver ses mesures dans le dashboard.

Exemple : `projects/R001-wearable-max30102/`. Chaque dossier contient :

- `sketch.ino`, les pilotes `sensors.h` et `protocols.h` ;
- `device_config.h` : identité, famille de capteur, réseau et provenance ;
- `diagram.json` et `libraries.txt` ;
- pour un custom, ses `.chip.c`, `.chip.json` et `.wasm` ;
- `wokwi.toml` pour l'extension Wokwi de VS Code.

Dans Wokwi web, créer un projet ESP32, puis importer les fichiers texte du dossier
avec le menu des fichiers → **Upload file(s)**. Pour un custom, le menu **+ → Custom
Chip** permet aussi de créer les deux fichiers avant d'y coller leur contenu.
Importer les bibliothèques de `libraries.txt`, puis lancer. Modifier les contrôles
du composant : le pilote reçoit les réponses du bus, pas une valeur MQTT injectée.

La simulation web peut subir une attente de compilation. Alternative : compiler
localement avec Arduino CLI, puis importer le firmware fusionné via F1 →
`Upload Firmware and Start Simulation`. Il faut toujours conserver le diagramme et
les fichiers custom dans le projet web.

## Compilation reproductible

Installer Arduino CLI, le core `esp32:esp32@2.0.17` et les versions de bibliothèques
déclarées dans `libraries.txt` (dont PubSubClient 2.8 et ArduinoJson 7.4.2).

```powershell
$esp32Index = 'https://espressif.github.io/arduino-esp32/package_esp32_index.json'
arduino-cli core update-index --additional-urls $esp32Index
arduino-cli core install esp32:esp32@2.0.17 --additional-urls $esp32Index
Get-Content firmware/all_sensors/projects/R001-wearable-max30102/libraries.txt |
  ForEach-Object { arduino-cli lib install $_ }
python firmware/all_sensors/tools/build.py firmware/all_sensors/projects/R001-wearable-max30102
```

`build.py` utilise la partition `huge_app`, nécessaire notamment au scanner BLE,
et place le binaire et l'ELF dans `build/` du banc. Ces fichiers sont ignorés par Git.
Le script contourne la contrainte Arduino du nom du dossier sans renommer le
`sketch.ino` attendu par Wokwi.

Les customs précompilés sont fournis. Pour les reconstruire :

```powershell
docker build -f firmware/all_sensors/tools/Dockerfile.chips -t ehpad-custom-chips .
$chipsPath = (Resolve-Path firmware/all_sensors).Path
docker run --rm -v "${chipsPath}:/work" ehpad-custom-chips
python firmware/all_sensors/tools/export_projects.py
```

Modifier `src/`, `catalog.py`, `chips/model.h` ou les générateurs, puis régénérer.
Les copies dans `projects/` sont des exports ; ne pas les modifier individuellement.
`make_chips.py` régénère les définitions de customs et leurs contrôles.

L'adaptateur `adcMillivolts` tient compte de la référence virtuelle 5 V de Wokwi.
Sur une vraie carte il utilise `analogReadMilliVolts` et la calibration ESP32.
Les pilotes ECG, respiration et sonomètre consomment des millivolts dans les deux
cas ; aucun facteur de correction Wokwi n'est appliqué au matériel.
Référence : [API analogique Wokwi](https://docs.wokwi.com/chips-api/analog).

## Passer au matériel

```powershell
python firmware/all_sensors/tools/export_projects.py --device R001-wearable-max30102 --hardware --out firmware/all_sensors/hardware-private
```

Dans le dossier privé généré, renseigner SSID, mot de passe Wi-Fi, adresse du broker
local et mot de passe MQTT. Le nom du compte MQTT est l'identifiant du dispositif.
Créer ce compte dans le fichier de mots de passe Mosquitto avec `mosquitto_passwd`,
en saisie interactive. L'ACL autorise uniquement
`ehpad/hardware/v1/<nom-du-compte>/telemetry` et `/status`.
Ne pas publier ce dossier privé ni les identifiants réseau. La simulation emploie
un autre préfixe et une autre provenance.

Le code de lecture I2C/SPI/UART/GPIO est le même pour les références documentées.
Le mode matériel change la configuration et active le scanner BLE réel. Il met
`LOAD_SCALE=0` : la masse demeure absente tant que la cellule de charge n'est pas
étalonnée. L'échelle420 de la simulation est propre au modèle HX711 Wokwi 50 kg.
Ne pas tarer automatiquement un lit occupé. Vérifier les niveaux logiques 3,3 V ; le
diagramme MQ‑2 comprend un diviseur 10kΩ/20kΩ pour son signal analogique 5 V.

## Capteurs disponibles et customs

Les bancs `*-wearable-nibp` utilisent maintenant le protocole PAR NIBP2010 /
NIBP2020 UP sans SpO2. START lance un cycle adulte manuel ; STOP l'annule.
Aucun gonflage n'est lancé au démarrage. Le custom simule les échanges série,
pas la pneumatique. Le pilote est identique en simulation et en mode matériel.
Voir le [protocole et le raccordement physique](../../docs/contrat_capteurs_materiels.md#tensiomètre--protocole-constructeur-par).

| Fonction | Référence / simulation | Données fournies |
|---|---|---|
| Mouvement bracelet | MPU6050 natif | norme accélération en g, rotation, impact |
| FC / SpO₂ | MAX30102 custom I²C0x57 | FIFO rouge/IR → algorithme SparkFun/Maxim |
| Température de contact | TMP117 custom I²C0x48 | température signée, distincte de température centrale |
| SOS / porte | bouton / contact natifs | état débouncé, SOS maintenu 3 s pour publication |
| Présence / salle de bain | PIR natif | mouvement, séparé par emplacement |
| Lit / sol | HX711 natif | compte brut, masse après calibration |
| Radar | custom sortie OUT du LD2410 | présence seule |
| CO₂ | SCD41 custom I²C0x62 | CO₂, température, humidité, CRC |
| Température / humidité | DHT22 natif | °C et humidité relative |
| COV | SGP40 custom I²C0x59 | signal brut et indice Sensirion à 1 Hz |
| Gaz / fumée | MQ‑2 natif | ADC brut ; pas de concentration de fumée inventée |
| CO | ZE07‑CO custom UART | concentration avec contrôle de checksum |
| Niveau sonore | SEN0232 custom analogique | conversion constructeur 50 dBA/V |
| Thermique | AMG8833 custom I²C0x69 | 64 pixels et maximum |
| GPS | custom NMEA RMC | position seulement avec fix valide et trame valide |
| Badge / RFID | MFRC522 natif SPI | UID du badge, pas une identité déduite |
| BLE | scanner ESP32 réel / fixture I²C Wokwi | adresse et RSSI ; pas de radio simulée |
| ECG | AD8232 / custom analogique | échantillon brut et électrodes débranchées |
| Respiration | entrée analogique conditionnée / custom | signal et estimation par seuils |
| Tension artérielle | PAR NIBP2010 / NIBP2020 UP sans SpO2, custom UART 4800 | protocole constructeur, cycle manuel START/STOP, erreurs et checksum |

Le modèle SGP30 est également fourni comme variante de test, avec eCO₂/TVOC bien
distincts du CO₂/indice COV. Il n'est pas utilisé par les 437 bancs de l'inventaire.

## Comment créer un custom absent de Wokwi

**MQ-2 et ADC :** Wokwi ne résout pas le pont diviseur à résistances : le premier
banc renvoyait toujours zéro. Le diagramme simulé raccorde AO directement à
l'ADC virtuel (référence 5 V). Ce raccordement est réservé à la simulation et
signalé dans le dessin. L'export `--hardware` conserve un pont 10 kΩ / 18 kΩ
(5 V vers 3,21 V) pour le véritable ESP32. Le pilote conserve `analogRead` ;
le signal brut doit être calibré sur le montage final.
Voir les [limites des résistances Wokwi](https://docs.wokwi.com/parts/wokwi-resistor).

**Compteur du dashboard :** 437 est le nombre de configurations disponibles.
Seules les simulations Wokwi démarrées publient des mesures. Ouvrir le dashboard
ne lance pas ces simulations. Un arrêt entraîne l'expiration des mesures après
15 secondes ; `0 / 437` signifie donc aucune mesure actuelle, pas 437 tests échoués.

1. Choisir la référence matérielle, puis lire son protocole constructeur.
2. Déclarer ses broches et ses curseurs dans `nom.chip.json`.
3. Dans `nom.chip.c`, initialiser les callbacks I²C/SPI/UART, ou les sorties GPIO/ADC.
4. Reproduire les adresses, registres, ordre des octets, délais, CRC et erreurs
   réellement utilisés par le pilote. Par exemple, le TMP117 expose une valeur
   signée sur 16 bits à0,0078125 °C/bit et son identifiant dans le registre 0x0F.
5. Injecter les valeurs via les attributs du custom ; le firmware conserve son
   pilote matériel. Tester une valeur nominale, ses limites et une déconnexion.
6. Compiler en WebAssembly, tester les callbacks, puis faire un essai ESP32 dans
   Wokwi. Le succès de compilation seul ne valide pas un capteur simulé.

Un custom n'est pas une preuve de fidélité électrique, radio, physiologique ou
clinique. Le modèle MAX30102 reproduit le sous-ensemble FIFO configuré ici
(100 Hz / moyenne 4 = 25 Hz), pas tous ses modes. Les modèles ont des limites explicites
dans le catalogue et dans [VALIDATION.md](VALIDATION.md).

Sources techniques : [installation ESP32](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html), [API Custom Chips](https://docs.wokwi.com/chips-api/getting-started),
[MPU6050](https://docs.wokwi.com/parts/wokwi-mpu6050),
[MAX3010x SparkFun](https://github.com/sparkfun/SparkFun_MAX3010x_Sensor_Library),
[TMP117 Adafruit](https://github.com/adafruit/Adafruit_TMP117),
[SCD4x Sensirion](https://github.com/Sensirion/arduino-i2c-scd4x),
[SGP40 Sensirion](https://github.com/Sensirion/arduino-i2c-sgp40),
[indice COV](https://github.com/Sensirion/arduino-gas-index-algorithm),
[AMG8833 Adafruit](https://github.com/adafruit/Adafruit_AMG88xx),
[ZE07‑CO constructeur](https://www.cnwinsen.com/wp-content/uploads/2021/08/ZE07-CO-Module-1.7.pdf),
[SEN0232 constructeur](https://wiki.dfrobot.com/sen0232/docs/18853),
[MFRC522 Wokwi](https://docs.wokwi.com/parts/board-mfrc522),
[limites BLE Wokwi](https://docs.wokwi.com/guides/esp32).
