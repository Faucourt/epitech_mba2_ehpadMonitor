# Validation de l'extension d'acquisition

Les résultats ci-dessous distinguent compilation, tests de protocole, intégration
MQTT et simulation ESP32. Aucun essai sur capteurs physiques et aucune vidéo n'ont
été réalisés pour cette extension.

## Vérifications réalisées

- **12 tests Python** : couverture des 25 résidents et 20 zones, chaque rôle du
  simulateur, 437 identifiants distincts, correspondance des exports, refus des
  identités incohérentes, NaN, champs inconnus, messages retained/rejoués,
  redémarrage, péremption, LWT et absence de fausses valeurs normales.
- **10 tests Node/WebAssembly** sur les 13 modèles custom compilés : transactions
  I²C, registres, température négative, FIFO MAX30102, cycle SCD41, CRC, trames
  ZE07‑CO/NMEA/passerelle tension, 64 pixels AMG8833, GPIO et signaux analogiques.
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
node --test tests/hardware/chips.test.cjs
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

### MAX30102

Banc sauvegardé : https://wokwi.com/projects/476785728510969857

Le custom fournit une FIFO I²C rouge/IR. Le firmware utilise la bibliothèque
SparkFun et l'algorithme Maxim ; la FC n'est pas injectée directement dans MQTT.

- Consigne 75 bpm : mesures observées 75–78 bpm après stabilisation.
- Consigne 120 bpm : mesure observée 125 bpm. La quantification de l'algorithme à 25 Hz
  et ses fenêtres limitent la précision ; aucune précision clinique n'est revendiquée.
- Retrait du doigt : signaux rouge/IR à 0, `heart_rate` et `spo2` à null.
- Retour du doigt : nouvelle fenêtre nécessaire avant retour des constantes.
- Réception du résident R001 confirmée dans le nouveau dashboard.

L'essai a révélé puis permis de corriger l'utilisation des accès « dernière valeur »
au lieu des accès FIFO appariés. Le firmware final invalide également la fenêtre
si le tampon logiciel déborde à la suite d'un blocage réseau.
Les traces de la session ayant trouvé et vérifié la correction FIFO sont dans
[validation/max30102-browser.jsonl](validation/max30102-browser.jsonl).
Le firmware final a ensuite été rejoué : valeur nominale, retrait du doigt
(valeurs null), puis retour du signal. Cette seconde trace figure dans
[validation/max30102-final-browser.jsonl](validation/max30102-final-browser.jsonl).

### SCD41

Essai du vrai pilote ESP32 avec le custom dans un nouveau projet Wokwi :

- Mesure nominale : 600 ppm, environ 22°C et 45 % HR.
- Modification des commandes : 2000 ppm, environ 30°C et 70 % HR reçus par MQTT.
- Alerte de démonstration CO₂ visible dans l'état de la salle commune.
- Activation de `corrupt` : CRC invalide, aucune nouvelle mesure validée ;
  publications sans valeurs après expiration de la dernière acquisition valide.
- Arrêt de la simulation : état hors ligne observé par le backend.

L'historique réellement reçu est conservé dans
[validation/scd41-mqtt-history.json](validation/scd41-mqtt-history.json).
Les autres customs sont testés au niveau WebAssembly et compilés avec le firmware ;
ils ne sont pas présentés comme ayant tous fait l'objet d'un essai visuel individuel.

## Ce qui reste à vérifier ou décider sur le matériel final

- Référence du tensiomètre : la fixture UART est un **contrat de passerelle du
  projet**, pas le pilote d'un brassard constructeur. Son adaptateur reste à écrire
  une fois le modèle retenu.
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
