# Expliquer les 45 pages Wokwi du projet EHPAD

Guide de présentation construit à partir des sources du dépôt et de l’index des pages corrigées du 6 octobre 2026. Il décrit ce qui a été implémenté, sans présenter une simulation pédagogique comme une validation médicale. Les noms de résidents sont les profils fictifs du projet.

## Présentation en une minute

« Nous avons construit 45 montages virtuels : 25 pour les résidents et 20 pour les zones de l’établissement. Chaque montage regroupe plusieurs composants autour d’un ESP32. Chaque capteur garde son identifiant et son état. On peut faire varier les commandes du composant et vérifier la lecture par le programme. Les capteurs disponibles dans Wokwi sont utilisés directement ; les autres sont représentés par des modèles logiciels qui reproduisent la partie de leur interface utilisée par notre pilote. Les données de ces modèles sont synthétiques. »

## Ce que fait chaque page

Le montage `diagram.json` décrit les composants, leurs paramètres et les connexions. `device_config.h` définit l’identité du résident ou de la zone. `endpoints.h` regroupe les pilotes et leurs affectations. `sketch.ino` initialise les composants puis les lit et émet des messages `SAMPLE` contenant leur identifiant, disponibilité et valeurs.

Pour les pages collectives, le trajet est **composant → ESP32 simulé → UART → passerelle locale → MQTT → backend → dashboard**. Ouvrir une page Wokwi seule ne démarre pas la passerelle ni le dashboard. L’export matériel dispose d’un transport Wi-Fi/MQTT direct. La première démo M1 avec potentiomètre est un autre montage : ses boutons, son buzzer et sa liaison MQTT ne doivent pas être attribués automatiquement à toutes les pages collectives.

Les commandes à tester ci-dessous sont tirées des composants et des pilotes ; elles ne signifient pas qu’un nouvel essai de chaque page a été effectué pendant la rédaction de ce guide.

## Comment les capteurs personnalisés ont été créés

1. Choisir la référence et l’interface attendue par le pilote : I²C, UART, signal analogique ou sortie logique.
2. Définir les broches et les contrôles visibles dans un fichier `.chip.json` : température, fréquence, présence, etc.
3. Implémenter dans `.chip.c` les réponses que le pilote utilise : registres, octets, temporisation, checksum ou CRC. Dans les sources communes, les modèles s’appuient sur `chips/model.h` ; les exports web embarquent leur code.
4. Lire les valeurs des contrôles avec l’API Wokwi et produire un signal sur le bus ou les broches. On fournit donc au pilote un périphérique virtuel, pas simplement une valeur directement écrite dans le dashboard.
5. Compiler le modèle en WebAssembly pour l’exécution locale avec `build_chips.sh` (Clang/WASI), ou importer les sources du custom dans le projet web. Ajouter le composant au diagramme et connecter les broches.
6. Tester la lecture du pilote et les erreurs réellement prises en charge. Le curseur `connected` contrôle la participation du modèle ; selon le bus, un arrêt peut laisser la dernière tension/valeur sur une broche. `corrupt` est exposé dans les définitions mais n’agit pas pour tous les modèles : ce n’est pas une garantie universelle de simulation de panne.

**Exemple MAX30102 :** le contrôle `bpm` règle la fréquence d’une onde synthétique ; `redRatio` modifie l’amplitude rouge relativement à l’infrarouge. Le modèle remplit une FIFO à 25 échantillons/s dans la configuration utilisée (100 Hz avec moyenne de 4). Le pilote lit les paires rouge/IR par I²C et lance son algorithme de calcul. Les corrections apportées gèrent notamment les 32 places de la FIFO, le débordement et la stabilité de lecture des paires. On teste une chaîne logicielle d’acquisition, pas une mesure optique réelle sur un patient.

## Les familles de capteurs et leurs limites

### mpu6050 — Mouvement et rotation

**Référence :** MPU-6050. **Réalisation :** natif `wokwi-mpu6050`.

Composant natif. Le firmware lit les axes et calcule une norme et un indicateur d’impact ; cela ne valide pas une chute humaine.

**Manipulation :** Modifier les axes d’accélération et de rotation du MPU6050.

### max30102 — Signal optique, fréquence cardiaque et SpO₂

**Référence :** MAX30102. **Réalisation :** custom `max30102`.

Modèle I²C à 0x57. Il génère des échantillons rouge/infrarouge synthétiques dans une FIFO de 32 échantillons. Le pilote et son algorithme calculent les résultats : redRatio n’est pas un réglage direct du pourcentage SpO₂. Le modèle couvre le mode utilisé ici, pas toute la physiologie ni tous les modes du composant.

**Manipulation :** Modifier bpm, redRatio ou finger ; laisser le temps de remplir la fenêtre de calcul.

**Contrôles déclarés :** `bpm` (30 à 220), `redRatio` (0.1 à 2), `finger` (0 à 1), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/max30102.chip.json).

### tmp117 — Température de contact

**Référence :** TMP117. **Réalisation :** custom `tmp117`.

Modèle I²C à 0x48 : conversion signée sur 16 bits, 128 unités par degré, avec identifiant du composant. Il représente une température de contact, pas une température centrale.

**Manipulation :** Modifier temperature.

**Contrôles déclarés :** `temperature` (-40 à 125), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/tmp117.chip.json).

### sos — Appel volontaire

**Référence :** Bouton SOS NO. **Réalisation :** natif `wokwi-pushbutton`.

Bouton natif, filtrage des rebonds et maintien dans le pilote. Le bouton ne détecte pas automatiquement un malaise.

**Manipulation :** Maintenir le bouton SOS environ 3 secondes.

### pir — Mouvement dans une pièce

**Référence :** HC-SR501. **Réalisation :** natif `wokwi-pir-motion-sensor`.

PIR natif. Il indique du mouvement ; une personne immobile peut ne pas être détectée.

**Manipulation :** Déclencher le mouvement sur le PIR.

### door — État d’ouverture

**Référence :** Contact sec NC / reed. **Réalisation :** natif `wokwi-slide-switch`.

Interrupteur natif utilisé pour représenter un contact de porte. Ce n’est pas une serrure commandée.

**Manipulation :** Basculer l’interrupteur de porte.

### hx711 — Charge de lit ou de sol

**Référence :** HX711 + cellule de charge. **Réalisation :** natif `wokwi-hx711`.

HX711 natif ; compte brut et conversion en masse selon calibration. Le rôle matelas/sol dépend de l’affectation. Un capteur de charge unique ne crée pas une cartographie de pression.

**Manipulation :** Faire varier la charge du composant HX711.

### radar — Présence

**Référence :** HLK-LD2410 OUT. **Réalisation :** custom `digital-presence`.

digital-presence reproduit uniquement la sortie logique OUT du LD2410. Il ne simule ni les ondes radar, ni la distance, ni la détection de chute.

**Manipulation :** Basculer presence entre 0 et 1.

**Contrôles déclarés :** `presence` (0 à 1), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/digital-presence.chip.json).

### scd41 — CO₂, température et humidité

**Référence :** SCD41. **Réalisation :** custom `scd41`.

Modèle I²C à 0x62 : commandes, disponibilité temporisée et réponses avec CRC. Il ne simule pas la physique du gaz.

**Manipulation :** Modifier co2, temperature et humidity ; attendre un cycle de mesure.

**Contrôles déclarés :** `co2` (400 à 5000), `temperature` (-10 à 60), `humidity` (0 à 100), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/scd41.chip.json).

### dht22 — Température et humidité ambiantes

**Référence :** DHT22. **Réalisation :** natif `wokwi-dht22`.

Composant natif. Le firmware collectif contient une adaptation de contrôle des nombres flottants pour le moteur web observé.

**Manipulation :** Modifier la température et l’humidité du DHT22.

### sgp40 — Indice de composés organiques volatils

**Référence :** SGP40 + algorithme Sensirion. **Réalisation :** custom `sgp40`.

Modèle I²C à 0x59 : signal brut transmis avec CRC. Le pilote applique l’algorithme Sensirion à 1 Hz ; l’indice n’est pas disponible immédiatement et la compensation est nominale.

**Manipulation :** Modifier vocRaw et laisser l’algorithme se stabiliser.

**Contrôles déclarés :** `vocRaw` (10000 à 50000), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/sgp40.chip.json).

### mq2 — Signal de gaz/fumée

**Référence :** MQ-2. **Réalisation :** natif `wokwi-gas-sensor`.

MQ-2 natif, lecture ADC brute : aucune concentration de fumée ou de CO n’est déduite. Le câblage virtuel ne doit pas être copié tel quel sur un ESP32 réel ; il faut adapter les niveaux électriques.

**Manipulation :** Faire varier le réglage du capteur de gaz natif.

### ze07co — Monoxyde de carbone

**Référence :** ZE07-CO. **Réalisation :** custom `ze07co`.

Modèle UART à 9600 bauds avec trames de concentration et checksum. La chimie du capteur n’est pas reproduite.

**Manipulation :** Modifier co.

**Contrôles déclarés :** `co` (0 à 500), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/ze07co.chip.json).

### sound — Niveau sonore

**Référence :** DFRobot SEN0232. **Réalisation :** custom `sound-level`.

sound-level produit une tension analogique selon V = dBA/50 ; le pilote reconvertit la tension. Il ne simule ni microphone acoustique ni reconnaissance de sons.

**Manipulation :** Modifier decibels.

**Contrôles déclarés :** `decibels` (30 à 130), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/sound-level.chip.json).

### ecg — Signal analogique de test ECG

**Référence :** AD8232. **Réalisation :** custom `analog-signal`.

analog-signal génère une sinusoïde bornée de 0 à 3,3 V et des états d’électrodes. Ce n’est pas un tracé ECG physiologique P-QRS-T ni un diagnostic de rythme.

**Manipulation :** Modifier amplitude, offset, frequency ; essayer leadsOff.

**Contrôles déclarés :** `amplitude` (0 à 1.5), `offset` (0 à 3.3), `frequency` (0.05 à 1000), `leadsOff` (0 à 1), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/analog-signal.chip.json).

### respiration — Signal respiratoire de test

**Référence :** Ceinture analogique conditionnée 0–3,3 V. **Réalisation :** custom `analog-signal`.

Même modèle analog-signal, dans une instance distincte. Le pilote estime une fréquence par franchissements avec hystérésis. Ici ce n’est pas une mesure respiratoire par IMU.

**Manipulation :** Modifier frequency et amplitude du composant analogique affecté à la respiration.

**Contrôles déclarés :** `amplitude` (0 à 1.5), `offset` (0 à 3.3), `frequency` (0.05 à 1000), `leadsOff` (0 à 1), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/analog-signal.chip.json).

### nibp — Cycle de tension artérielle

**Référence :** PAR NIBP2010 / NIBP2020 UP sans SpO2. **Réalisation :** custom `par-nibp`.

par-nibp simule une partie du protocole PAR NIBP2010/NIBP2020 UP, UART 4800, erreurs et checksum. Le résultat est produit après un cycle simulé. Aucun brassard, gonflage ni procédé oscillométrique n’est simulé.

**Manipulation :** Régler systolic/diastolic puis appuyer sur START ; STOP annule le cycle.

**Contrôles déclarés :** `systolic` (40 à 300), `diastolic` (20 à 200), `error` (0 à 15), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/par-nibp.chip.json).

### amg8833 — Matrice thermique 8 × 8

**Référence :** AMG8833. **Réalisation :** custom `amg8833`.

Modèle I²C à 0x69 : 64 pixels, une température ambiante et un point chaud configurable. Ce n’est pas une image réaliste d’une personne.

**Manipulation :** Modifier ambient, hotspot et pixel.

**Contrôles déclarés :** `ambient` (-20 à 80), `hotspot` (-20 à 80), `pixel` (0 à 63), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/amg8833.chip.json).

### gps — Position géographique

**Référence :** GNSS NMEA 0183 (NEO-6M). **Réalisation :** custom `gps-nmea`.

gps-nmea émet des trames NMEA RMC avec checksum à 9600 bauds. La date/heure contenue dans le modèle est fixe ; ne pas l’utiliser comme horodatage réel. Pas de satellites simulés.

**Manipulation :** Modifier latitude/longitude et activer ou désactiver fix.

**Contrôles déclarés :** `latitude` (-90 à 90), `longitude` (-180 à 180), `fix` (0 à 1), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/gps-nmea.chip.json).

### rfid — Lecture de badge

**Référence :** MFRC522. **Réalisation :** natif `wokwi-mfrc522`.

Lecteur natif SPI. Le firmware remonte l’UID ; la correspondance avec une personne doit être gérée ailleurs.

**Manipulation :** Présenter un badge dans le composant MFRC522.

### ble — Test du traitement BLE

**Référence :** ESP32 BLE scanner. **Réalisation :** custom `ble-fixture`.

Adaptateur de test I²C fournissant une adresse fixe de test et un RSSI. Aucune radio BLE n’est simulée ; le mode matériel utilise le scanner BLE de l’ESP32.

**Manipulation :** Modifier rssi ou connected sur ble-fixture.

**Contrôles déclarés :** `rssi` (-100 à -20), `connected` (0 à 1), `corrupt` (0 à 1).

[Définition du composant](../firmware/all_sensors/chips/ble-fixture.chip.json).

Le SGP30 existe également dans les sources comme variante de test, mais n’appartient pas aux 437 points d’acquisition actifs. Les numéros de GPIO des bancs individuels ne sont pas tous ceux des pages collectives : consulter le `diagram.json` et `endpoints.h` de la page concernée.

## Les 45 pages, une par une

Le groupe wearable commun comporte sept fonctions : MPU6050, MAX30102, TMP117, SOS, ECG analogique, respiration analogique et tensiomètre. Le nom « wearable » est un regroupement logiciel, pas la preuve que tous ces appareils tiennent dans un bracelet.

### R001 — Marie Curie — chambre 101

[Ouvrir la page Wokwi](https://wokwi.com/projects/477043203503950849) · **11 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R001, un PIR de chambre et une mesure de charge du matelas, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R001, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; HX711 + cellule de charge; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis faire varier la charge du HX711. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; simulation de ce modèle observée dans le navigateur lors de la livraison du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R001/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R001/endpoints.h).

### R002 — Louis Pasteur — chambre 102

[Ouvrir la page Wokwi](https://wokwi.com/projects/477043364101807105) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R002, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R002, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; simulation de ce modèle observée dans le navigateur lors de la livraison du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R002/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R002/endpoints.h).

### R003 — Simone Veil — chambre 103

[Ouvrir la page Wokwi](https://wokwi.com/projects/477052131126243329) · **11 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R003, un PIR de chambre et une mesure de charge du matelas, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R003, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; HX711 + cellule de charge; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis faire varier la charge du HX711. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R003/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R003/endpoints.h).

### R004 — Pierre de Coubertin — chambre 104

[Ouvrir la page Wokwi](https://wokwi.com/projects/477047596125723649) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R004, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R004, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R004/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R004/endpoints.h).

### R005 — Edith Piaf — chambre 105

[Ouvrir la page Wokwi](https://wokwi.com/projects/477052321758466049) · **11 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R005, un PIR de chambre et une mesure de charge du matelas, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R005, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; HX711 + cellule de charge; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis faire varier la charge du HX711. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R005/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R005/endpoints.h).

### R006 — Jean Gabin — chambre 106

[Ouvrir la page Wokwi](https://wokwi.com/projects/477047809903190017) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R006, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R006, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R006/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R006/endpoints.h).

### R007 — Annie Girardot — chambre 107

[Ouvrir la page Wokwi](https://wokwi.com/projects/477052529753013249) · **11 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R007, un PIR de chambre et une mesure de charge du matelas, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R007, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; HX711 + cellule de charge; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis faire varier la charge du HX711. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R007/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R007/endpoints.h).

### R008 — Bourvil — chambre 108

[Ouvrir la page Wokwi](https://wokwi.com/projects/477048018029860865) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R008, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R008, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R008/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R008/endpoints.h).

### R009 — Coco Chanel — chambre 201

[Ouvrir la page Wokwi](https://wokwi.com/projects/477047195350368257) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R009, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R009, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; simulation de ce modèle observée dans le navigateur lors de la livraison du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R009/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R009/endpoints.h).

### R010 — Yves Montand — chambre 202

[Ouvrir la page Wokwi](https://wokwi.com/projects/477048198376615937) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R010, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R010, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R010/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R010/endpoints.h).

### R011 — Jeanne Moreau — chambre 203

[Ouvrir la page Wokwi](https://wokwi.com/projects/477050554101999617) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R011, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R011, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R011/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R011/endpoints.h).

### R012 — Charles Aznavour — chambre 204

[Ouvrir la page Wokwi](https://wokwi.com/projects/477048429265795073) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R012, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R012, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R012/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R012/endpoints.h).

### R013 — Brigitte Bardot — chambre 208

[Ouvrir la page Wokwi](https://wokwi.com/projects/477050736208257025) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R013, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R013, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R013/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R013/endpoints.h).

### R014 — Gerard Depardieu — chambre 209

[Ouvrir la page Wokwi](https://wokwi.com/projects/477048730515462145) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R014, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R014, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R014/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R014/endpoints.h).

### R015 — Mireille Mathieu — chambre 210

[Ouvrir la page Wokwi](https://wokwi.com/projects/477050909537929217) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R015, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R015, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R015/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R015/endpoints.h).

### R016 — Claude Francois — chambre 211

[Ouvrir la page Wokwi](https://wokwi.com/projects/477048889165057025) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R016, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R016, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R016/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R016/endpoints.h).

### R017 — Josephine Baker — chambre 212

[Ouvrir la page Wokwi](https://wokwi.com/projects/477051094264617985) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R017, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R017, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R017/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R017/endpoints.h).

### R018 — Fernandel — chambre 213

[Ouvrir la page Wokwi](https://wokwi.com/projects/477049088829739009) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R018, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R018, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R018/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R018/endpoints.h).

### R019 — Dalida — chambre 214

[Ouvrir la page Wokwi](https://wokwi.com/projects/477051272171323393) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R019, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R019, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R019/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R019/endpoints.h).

### R020 — Lino Ventura — chambre 215

[Ouvrir la page Wokwi](https://wokwi.com/projects/477049308233861121) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R020, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R020, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R020/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R020/endpoints.h).

### R021 — Romy Schneider — chambre 216

[Ouvrir la page Wokwi](https://wokwi.com/projects/477051478006847489) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R021, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R021, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R021/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R021/endpoints.h).

### R022 — Jean-Paul Belmondo — chambre 217

[Ouvrir la page Wokwi](https://wokwi.com/projects/477049763255211009) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R022, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R022, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R022/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R022/endpoints.h).

### R023 — Sophie Marceau — chambre 218

[Ouvrir la page Wokwi](https://wokwi.com/projects/477051668860320769) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R023, un PIR de chambre, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R023, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis déclencher le PIR de chambre. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R023/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R023/endpoints.h).

### R024 — Michel Sardou — chambre 219

[Ouvrir la page Wokwi](https://wokwi.com/projects/477050223850765313) · **10 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R024, un radar de présence, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R024, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HLK-LD2410 OUT; Contact sec NC / reed; HC-SR501.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `digital-presence`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis basculer `presence` sur le radar. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R024/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R024/endpoints.h).

### R025 — Isabelle Adjani — chambre 220

[Ouvrir la page Wokwi](https://wokwi.com/projects/477136860304458753) · **11 points d’acquisition**.

**À expliquer :** Cette page réunit les sept fonctions wearable de R025, un PIR de chambre et une mesure de charge du matelas, un contact de porte et un PIR de salle de bain. Chaque message porte les identifiants de R025, sans recopier ses valeurs sur les autres résidents.

**Équipements exacts :** MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; HC-SR501 × 2; HX711 + cellule de charge; Contact sec NC / reed.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier `bpm` sur le MAX30102, maintenir SOS, puis faire varier la charge du HX711. Vérifier les identifiants dans les trames `SAMPLE` ; avec la passerelle active, suivre la fiche du résident.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/R025/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/R025/endpoints.h).

### entree — Entree / Accueil

[Ouvrir la page Wokwi](https://wokwi.com/projects/477137163174193153) · **10 points d’acquisition**.

**À expliquer :** Observer les passages à l’accueil avec deux lecteurs RFID distincts, le mouvement, la porte et les conditions ambiantes. Un badge fournit un UID ; il ne prouve pas à lui seul l’identité d’une personne.

**Équipements exacts :** MFRC522 × 2; HC-SR501; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Présenter un badge dans le composant MFRC522. Déclencher le mouvement sur le PIR. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; simulation de ce modèle observée dans le navigateur lors de la livraison du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/entree/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/entree/endpoints.h).

### hors_ehpad — Sortie hors EHPAD

[Ouvrir la page Wokwi](https://wokwi.com/projects/477141241091889153) · **8 points d’acquisition**.

**À expliquer :** Tester une position GPS et une lecture de badge associées à une sortie. L’alerte de fugue est une fonction logicielle ; un fix GPS ne prouve pas une fugue.

**Équipements exacts :** GNSS NMEA 0183 (NEO-6M); MFRC522; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `gps-nmea`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier latitude/longitude et activer ou désactiver fix. Présenter un badge dans le composant MFRC522. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/hors_ehpad/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/hors_ehpad/endpoints.h).

### infirmerie_rdc — Infirmerie

[Ouvrir la page Wokwi](https://wokwi.com/projects/477139012535715841) · **7 points d’acquisition**.

**À expliquer :** Surveiller la porte et l’environnement de l’infirmerie. Le dashboard et les niveaux d’alerte sont logiciels, pas des capteurs ajoutés au montage.

**Équipements exacts :** Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/infirmerie_rdc/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/infirmerie_rdc/endpoints.h).

### pharmacie_admin — Pharmacie / Admin

[Ouvrir la page Wokwi](https://wokwi.com/projects/477139355746276353) · **7 points d’acquisition**.

**À expliquer :** Observer l’ouverture de la porte et l’environnement de la pharmacie/administration. La centralisation du dashboard reste une fonction de l’application.

**Équipements exacts :** Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/pharmacie_admin/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/pharmacie_admin/endpoints.h).

### couloir_principal — Couloir principal

[Ouvrir la page Wokwi](https://wokwi.com/projects/477143403102265345) · **9 points d’acquisition**.

**À expliquer :** Comparer mouvement PIR, présence radar et charge au sol, en parallèle des mesures ambiantes. La charge au sol ne permet pas à elle seule de conclure à une chute.

**Équipements exacts :** HC-SR501; HLK-LD2410 OUT; HX711 + cellule de charge; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `digital-presence`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Basculer presence entre 0 et 1. Faire varier la charge du composant HX711. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/couloir_principal/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/couloir_principal/endpoints.h).

### salle_commune — Salle commune / TV

[Ouvrir la page Wokwi](https://wokwi.com/projects/477139826201609217) · **8 points d’acquisition**.

**À expliquer :** Observer les mouvements, la porte, le bruit et la qualité de l’air de la salle commune.

**Équipements exacts :** HC-SR501; SCD41; DFRobot SEN0232; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `scd41`, `sound-level`, `sgp40`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/salle_commune/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/salle_commune/endpoints.h).

### patio — Patio couvert

[Ouvrir la page Wokwi](https://wokwi.com/projects/477142104370136065) · **12 points d’acquisition**.

**À expliquer :** Réunir GPS, badge, mouvement, présence radar, charge au sol et matrice thermique dans le patio, avec les mesures ambiantes. La thermique ne reconnaît pas les personnes.

**Équipements exacts :** GNSS NMEA 0183 (NEO-6M); MFRC522; HC-SR501; HLK-LD2410 OUT; HX711 + cellule de charge; SCD41; DFRobot SEN0232; AMG8833; DHT22; SGP40 + algorithme Sensirion; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `gps-nmea`, `digital-presence`, `scd41`, `sound-level`, `amg8833`, `sgp40`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier latitude/longitude et activer ou désactiver fix. Présenter un badge dans le composant MFRC522. Déclencher le mouvement sur le PIR. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/patio/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/patio/endpoints.h).

### jardin — Jardin therapeutique

[Ouvrir la page Wokwi](https://wokwi.com/projects/477141640707493889) · **10 points d’acquisition**.

**À expliquer :** Tester la position GPS, le badge, le mouvement et un point chaud thermique dans le jardin, avec les mesures ambiantes. Aucune liaison satellite réelle n’est simulée.

**Équipements exacts :** GNSS NMEA 0183 (NEO-6M); MFRC522; AMG8833; HC-SR501; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `gps-nmea`, `amg8833`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier latitude/longitude et activer ou désactiver fix. Présenter un badge dans le composant MFRC522. Modifier ambient, hotspot et pixel. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/jardin/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/jardin/endpoints.h).

### salle_activites — Salle d'activites

[Ouvrir la page Wokwi](https://wokwi.com/projects/477140258778152961) · **8 points d’acquisition**.

**À expliquer :** Observer le mouvement, l’ouverture de porte et les conditions ambiantes pendant les activités.

**Équipements exacts :** HC-SR501; DHT22; SGP40 + algorithme Sensirion; Contact sec NC / reed; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/salle_activites/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/salle_activites/endpoints.h).

### salle_manger — Salle a manger

[Ouvrir la page Wokwi](https://wokwi.com/projects/477140496370897921) · **9 points d’acquisition**.

**À expliquer :** Associer mouvement, charge au sol et ouverture de porte aux mesures ambiantes de la salle à manger.

**Équipements exacts :** HC-SR501; HX711 + cellule de charge; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Faire varier la charge du composant HX711. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/salle_manger/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/salle_manger/endpoints.h).

### office_cuisine — Office / Cuisine

[Ouvrir la page Wokwi](https://wokwi.com/projects/477140748600704001) · **8 points d’acquisition**.

**À expliquer :** Surveiller les signaux de gaz, de CO, la porte et l’ambiance de la cuisine. Deux DHT22 distincts sont prévus : un pour le rôle température et un pour l’ambiance.

**Équipements exacts :** MQ-2; DHT22 × 2; ZE07-CO; Contact sec NC / reed; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232.

**Modèles personnalisés présents :** `ze07co`, `sgp40`, `scd41`, `sound-level`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/office_cuisine/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/office_cuisine/endpoints.h).

### couloir_aile_rdc — Couloir Aile RDC

[Ouvrir la page Wokwi](https://wokwi.com/projects/477144441072253953) · **9 points d’acquisition**.

**À expliquer :** Associer un signal de test BLE, le mouvement PIR et une charge au sol aux mesures ambiantes. Le BLE teste ici le traitement des données, pas la propagation radio.

**Équipements exacts :** ESP32 BLE scanner; HC-SR501; HX711 + cellule de charge; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `ble-fixture`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Modifier rssi ou connected sur ble-fixture. Déclencher le mouvement sur le PIR. Faire varier la charge du composant HX711. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/couloir_aile_rdc/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/couloir_aile_rdc/endpoints.h).

### escalier — Escalier securise

[Ouvrir la page Wokwi](https://wokwi.com/projects/477143866834099201) · **9 points d’acquisition**.

**À expliquer :** Croiser mouvement, présence radar et porte dans l’escalier, avec les conditions ambiantes. Ce montage n’est pas une preuve de détection de chute dans l’escalier.

**Équipements exacts :** HC-SR501; HLK-LD2410 OUT; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `digital-presence`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Basculer presence entre 0 et 1. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/escalier/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/escalier/endpoints.h).

### ascenseur — Ascenseur

[Ouvrir la page Wokwi](https://wokwi.com/projects/477140987596428289) · **9 points d’acquisition**.

**À expliquer :** Tester la lecture d’un badge, le mouvement et la porte de l’ascenseur, avec les mesures ambiantes. Aucun contrôle de la motorisation n’est réalisé.

**Équipements exacts :** MFRC522; HC-SR501; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Présenter un badge dans le composant MFRC522. Déclencher le mouvement sur le PIR. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/ascenseur/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/ascenseur/endpoints.h).

### poste_infirmier_etage — Poste infirmier

[Ouvrir la page Wokwi](https://wokwi.com/projects/477139685661966337) · **7 points d’acquisition**.

**À expliquer :** Surveiller la porte et l’environnement du poste infirmier. La surveillance de l’étage est une fonction logicielle du projet.

**Équipements exacts :** Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/poste_infirmier_etage/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/poste_infirmier_etage/endpoints.h).

### kinesitherapie — Kinesitherapie

[Ouvrir la page Wokwi](https://wokwi.com/projects/477145354499705857) · **16 points d’acquisition**.

**À expliquer :** Associer les sept fonctions du groupe wearable à un PIR, une charge au sol, une porte et l’environnement de la salle de kinésithérapie. Cette page contient un seul MPU6050 : elle ne réalise pas encore le cas D à deux IMU.

**Équipements exacts :** HC-SR501; HX711 + cellule de charge; MPU-6050; MAX30102; TMP117; Bouton SOS NO; AD8232; Ceinture analogique conditionnée 0–3,3 V; PAR NIBP2010 / NIBP2020 UP sans SpO2; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `max30102`, `tmp117`, `analog-signal`, `par-nibp`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Faire varier la charge du composant HX711. Modifier les axes d’accélération et de rotation du MPU6050. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/kinesitherapie/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/kinesitherapie/endpoints.h).

### salle_repos — Salle de repos

[Ouvrir la page Wokwi](https://wokwi.com/projects/477140077081891841) · **8 points d’acquisition**.

**À expliquer :** Observer le mouvement, la porte, le bruit et les conditions ambiantes de la salle de repos.

**Équipements exacts :** HC-SR501; SCD41; DFRobot SEN0232; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `scd41`, `sound-level`, `sgp40`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Basculer l’interrupteur de porte. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/salle_repos/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/salle_repos/endpoints.h).

### couloir_aile_a_etage — Couloir Aile A

[Ouvrir la page Wokwi](https://wokwi.com/projects/477144789996536833) · **9 points d’acquisition**.

**À expliquer :** Associer mouvement, signal de test BLE et charge au sol aux mesures ambiantes du couloir de l’aile A.

**Équipements exacts :** HC-SR501; ESP32 BLE scanner; HX711 + cellule de charge; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `ble-fixture`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Modifier rssi ou connected sur ble-fixture. Faire varier la charge du composant HX711. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/couloir_aile_a_etage/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/couloir_aile_a_etage/endpoints.h).

### couloir_aile_b_etage — Couloir Aile B

[Ouvrir la page Wokwi](https://wokwi.com/projects/477144980838476801) · **9 points d’acquisition**.

**À expliquer :** Associer mouvement PIR, signal de test BLE et présence radar aux mesures ambiantes du couloir de l’aile B.

**Équipements exacts :** HC-SR501; ESP32 BLE scanner; HLK-LD2410 OUT; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `ble-fixture`, `digital-presence`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Modifier rssi ou connected sur ble-fixture. Basculer presence entre 0 et 1. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/couloir_aile_b_etage/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/couloir_aile_b_etage/endpoints.h).

### palier_etage — Palier escalier / ascenseur

[Ouvrir la page Wokwi](https://wokwi.com/projects/477144229800873985) · **10 points d’acquisition**.

**À expliquer :** Réunir mouvement, badge, présence radar et porte sur le palier entre escalier et ascenseur, avec les mesures ambiantes.

**Équipements exacts :** HC-SR501; MFRC522; HLK-LD2410 OUT; Contact sec NC / reed; DHT22; SGP40 + algorithme Sensirion; SCD41; DFRobot SEN0232; ZE07-CO; MQ-2.

**Modèles personnalisés présents :** `digital-presence`, `sgp40`, `scd41`, `sound-level`, `ze07co`. Leur fonctionnement est expliqué dans les fiches ci-dessus.

**Démonstration proposée :** Déclencher le mouvement sur le PIR. Présenter un badge dans le composant MFRC522. Basculer presence entre 0 et 1. Modifier aussi `co2` sur le SCD41 pour montrer une mesure ambiante.

**Preuve disponible :** sources publiées et comparées après téléchargement ; pas d’observation individuelle de cette version dans le navigateur établie par le bilan du 6 octobre.

[Montage et connexions](../output/wokwi-transfert/upload/palier_etage/diagram.json) · [Pilotes et identifiants](../output/wokwi-transfert/upload/palier_etage/endpoints.h).

## Ce qu’il faut dire sur les six cas d’usage du cours

- **A — chute et activité :** la brique IMU et le SOS sont présents. Le buzzer appartient notamment à la première démo M1 ; ne pas affirmer qu’il équipe chaque page collective. Phyphox apporte des enregistrements réels complémentaires.
- **B — insuffisance cardiaque :** les briques optiques et de charge existent. Une charge de matelas/sol ne devient pas automatiquement une pesée corporelle validée. Aucun diagnostic d’insuffisance cardiaque n’est établi.
- **C — BPCO :** le groupe possède un signal optique et une respiration analogique simulée. Le cours décrit une fréquence respiratoire par IMU thoracique : ce n’est pas l’implémentation actuelle.
- **D — rééducation post-AVC :** la page kinésithérapie ne comporte pas deux IMU. Le cas complet à deux capteurs synchronisés reste à développer si retenu.
- **E — escarres :** les modèles de charge et de température existants ne sont pas le montage FSR + DS18B20 demandé dans cette proposition.
- **F — pilulier :** aucune des 45 pages n’est un pilulier FSR/ILS avec rappel. La présence d’un contact de porte ailleurs ne suffit pas à réaliser ce cas.

Les six propositions du cours ne sont donc pas six réalisations déjà validées dans le dépôt. Le choix des équipes et des cas est annoncé au module 3 sur la diapositive fournie.

## État de validation à annoncer

Les 45 pages corrigées sont publiées et leurs 733 fichiers ont été comparés aux sources attendues. Les modèles R001, R002, R009 et entrée ont des observations navigateur dans le bilan du 6 octobre. Pour R001, l’observation précède la sauvegarde finale, ensuite vérifiée par téléchargement. Une preuve historique de 23 cartes simultanées concerne une version antérieure : elle ne valide pas toute la flotte corrigée de 45 cartes.

Restent à éprouver : réception de chaque page de cette version dans le dashboard, exécution simultanée complète, stabilité prolongée, reprises après interruptions et matériel réel. Les modèles personnalisés ne valident ni les phénomènes physiques, ni la radio, ni la sécurité électrique, ni une utilisation clinique.

## Sources du dépôt

- [Inventaire des 437 points](../firmware/all_sensors/inventory.json).
- [Catalogue et choix des modèles](../firmware/all_sensors/catalog.py).
- [Code commun des customs](../firmware/all_sensors/chips/model.h).
- [Compilation WebAssembly](../firmware/all_sensors/tools/build_chips.sh).
- [Générateur collectif](../firmware/all_sensors/tools/export_collective.py).
- [Fonctionnement de la passerelle et lancement](../firmware/all_sensors/COLLECTIVE.md).
- [Index des 45 pages corrigées](../output/wokwi-transfert/pages-corrigees.json).
- [Bilan de validation daté](BILAN-WOKWI-2026-10-06.md).
