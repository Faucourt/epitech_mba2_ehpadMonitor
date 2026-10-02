# Validation de l'extension d'acquisition

Les résultats ci-dessous distinguent compilation, tests de protocole, intégration
MQTT et simulation ESP32. Aucun essai sur capteurs physiques et aucune vidéo n'ont
été réalisés pour cette extension.

## Vérifications réalisées

- **25 tests Python** : couverture des 25 résidents et 20 zones, chaque rôle du
  simulateur, 437 identifiants distincts, correspondance des exports, refus des
  identités incohérentes, NaN, champs inconnus, messages retained/rejoués,
  redémarrage, péremption, LWT et absence de fausses valeurs normales.
  Ils contrôlent aussi les 45 regroupements ESP32, les broches, le périmètre pilote,
  la distinction communication/mesure et le superviseur (processus simulés pour
  ces tests unitaires : ils ne constituent pas des exécutions Wokwi).
- **10 tests Node/WebAssembly** sur les 13 modèles custom compilés : transactions
  I²C, registres, température négative, FIFO MAX30102, cycle SCD41, CRC, trames
  ZE07‑CO/NMEA/PAR NIBP, 64 pixels AMG8833, GPIO et signaux analogiques.
- **8 tests Node de la grille d'acquisition** : affectation des résidents et zones,
  absence de valeurs par défaut, expiration locale et isolement des sources.
- **C++** : parseur PAR sur trames documentées et rejet de NaN/infinis dans le
  contrôle de valeurs DHT22 compatible avec le moteur ESP32 web observé.
- **MQTT → backend réel** dans une stack Docker isolée : 437 messages synthétiques
  répartis sur 45 entités, réception vérifiée, affectation de chaque résident,
  champ absent conservé à null, identité falsifiée refusée et accès au mode
  matériel protégé par session soignant. Ce test **n'exécute pas 437 ESP32**.
- **Firefox** : recherche, filtres, 25 résidents, 20 zones, détails par capteur,
  absence de mesures, changement de source, refus 401, erreur 503, texte injecté
  échappé et thermique 64 pixels. Vérification des petits écrans jusqu'à 320 px,
  correction d'un chevauchement de la matrice thermique. Aucune erreur JavaScript
  relevée lors des tests contrôlés.
- **22 compilations Arduino ESP32 réussies** : 21 familles actives dans Wokwi et
  le scanner BLE matériel. Résultats par configuration et SHA‑256 dans
  [validation/compilation.json](validation/compilation.json). Core 2.0.17,
  partition `huge_app`, bibliothèques verrouillées dans les exports.

Commandes de contrôle :

```powershell
python -m unittest discover -s tests/hardware -p 'test_*.py' -v
node --test tests/hardware/*.test.cjs
node --check dashboard/public/hardware.js
python -m compileall -q backend/hardware_telemetry.py backend/hardware_routes.py backend/main.py
python firmware/all_sensors/tools/build_matrix.py
```

Pour rejouer le test de masse MQTT local, démarrer la stack de laboratoire avec
`WOKWI_LAB_HOST=mqtt`, installer `paho-mqtt==1.6.1`, puis :

```powershell
python tests/hardware/mqtt_integration.py
```

Le test ne contacte que `127.0.0.1:1887` par défaut. `--seconds 60` maintient les
valeurs synthétiques pendant une minute pour inspecter l'interface. Après son
arrêt, les mesures expirent ; ce comportement est attendu.

## Essais ESP32 réels dans Wokwi / Firefox

### Trois résidents complets et tout l'environnement

**23 projets collectifs / 214 capteurs**, correspondant à R001, R002, R003 et aux
20 zones : tous les champs prévus ont été observés dans les trames UART Wokwi,
avec réception des identifiants vérifiée dans le backend. Les essais de zones
ont été successifs. Les [comptes rendus, traces et liens des 23 projets](validation/collective/README.md)
sont contrôlés par `tools/summarize_collective_validation.py`.

Une observation distincte a vérifié les 42 capteurs des trois résidents et de
l'entrée pendant environ deux minutes ensemble. Le fonctionnement continu des
23 cartes simultanées reste à tester avec Wokwi CLI et un jeton disponible.
Les 22 autres résidents ne sont pas couverts par ces essais collectifs.

### Bancs individuels par famille

**21 familles et 62 scénarios réussis**, avec publication du firmware ESP32
simulé, réception MQTT vérifiée dans le backend et sauvegarde des projets.
La [liste des 21 bancs Wokwi](validation/WOKWI.md) donne les liens exécutables.
Les [résultats détaillés](validation/wokwi-results.json) donnent les échantillons,
identifiants et empreintes SHA-256, identiques à la matrice de compilation finale.
Les traces série sont conservées dans `validation/wokwi/`.

Les valeurs nominales, variations et erreurs sont testées selon chaque modèle :
retrait du doigt MAX30102, CRC SCD41/SGP40, déconnexion TMP117/AMG8833, perte de fix
GPS, électrodes ECG, respiration 15 puis 30/min puis signal plat, son 45 puis
80 dBA, UART CO, charge HX711, bouton SOS, porte, présence et accélération MPU6050.
Le RFID a été vérifié avec la commande Hold ; un bref Tap peut être manqué à
faible vitesse de simulation. Le BLE reste un adaptateur de données, sans radio.

Le tensiomètre utilise le protocole PAR NIBP2010 / NIBP2020 UP sans SpO2 :
aucune inflation au démarrage, mesures 120/75 puis 150/95, erreur M07 rejetée,
checksum corrompu rejeté et annulation STOP. Un test C++ du parseur emploie
également des trames littérales du document constructeur ; son exemple §13.5
contient une incohérence de checksum, documentée dans le contrat matériel.

Deux défauts repérés pendant ces essais ont été corrigés : la conversion ADC
virtuelle pour respiration/ECG/son et le pont diviseur MQ-2 non simulé par Wokwi.
Le diagramme MQ-2 direct est réservé à la simulation ; l'export matériel conserve
son atténuation. Les sources et limites sont dans le README.

Les traces MAX30102/SCD41 situées directement dans `validation/` sont des essais
historiques ; les résultats finaux de toutes les familles sont dans `validation/wokwi/`.
Aucun de ces résultats ne signifie 437 ESP32 exécutés simultanément. Le compteur
du dashboard n'inclut que les appareils qui publient des mesures actuelles.

Vérifier la cohérence des preuves et régénérer la liste :

```powershell
python firmware/all_sensors/tools/summarize_validation.py
```

## Ce qui reste à vérifier ou décider sur le matériel final

- Tensiomètre : raccordement au module PAR et au brassard physiques. Le pilote
  utilise désormais son protocole constructeur ; la pneumatique n'est pas simulée.
- Référence et calibration de la ceinture respiratoire ; l'entrée analogique et
  l'estimation sont présentes, mais aucune ceinture physique n'a été validée.
- Câblage, niveaux logiques, alimentation, placement, cellule de charge, seuils
  d'occupation du lit/sol, référence ADC du sonomètre et calibration de chaque unité.
- Validation des algorithmes de constantes vitales, de chute, sommeil et localisation.
  Un impact n'est pas une chute confirmée, une température de contact n'est pas
  automatiquement une température centrale, et un badge ne prouve pas une occupation.
- Radio BLE et association des badges/balises aux résidents : la radio n'existe pas
  dans Wokwi ; le scanner matériel est compilé séparément.
- Regroupement des bancs sur les cartes définitives : les broches de chaque banc
  sont documentées, mais connecter plusieurs bancs ensemble sans réaffectation des
  broches créerait des conflits. Les 437 exports sont des bancs indépendants.
- Garantie de livraison et persistance des alarmes hors connexion ; stockage
  durable des télémesures de cette extension. Son historique en mémoire contient
  au plus 180 publications par équipement et par source, et disparaît au redémarrage.

Ces limites sont aussi visibles dans le catalogue et dans l'interface quand elles
concernent un modèle précis. L'application clinique d'origine conserve son propre
simulateur ; elle n'utilise pas ces mesures partielles pour produire un score ML.
