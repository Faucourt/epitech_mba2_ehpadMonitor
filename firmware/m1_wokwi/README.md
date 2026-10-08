# TP M1 — ESP32 Wokwi → MQTT → EHPAD

Projet enregistré : https://wokwi.com/projects/476777815517850625

## Vérification complémentaire du 8 octobre 2026

Le binaire local `livrables/m1-full.bin` a été chargé dans Wokwi et le client
web HiveMQ connecté à `broker.hivemq.com:8884`, avec l'abonnement
`digi5/lebretyves-ehpad-m1/#`. Les messages `vitals` et l'alerte `sos` ont été
reçus dans ce client indépendant : [capture du client MQTT](livrables/hivemq-mesures-2026-10-08.png)
et [texte des messages reçus](livrables/hivemq-messages-2026-10-08.txt).
La [capture d'état](livrables/hivemq-status-2026-10-08.png) conserve les états
online/offline observés au cours de cette session.

Le signal audio du buzzer a été contrôlé au niveau de la sortie Web Audio du
navigateur : silence initial, signal non nul après SOS, puis retour au silence.
Une sonde `AnalyserNode` a mesuré 41 fenêtres non nulles, sans injecter de son
de test. La cadence réelle dépend du navigateur et du temps simulé ; cela ne
mesure pas précisément trois secondes réelles ni le volume des haut-parleurs.
Voir la [preuve audio et son empreinte de firmware](livrables/buzzer-audio-2026-10-08.json)
et la [sonde utilisée](livrables/sonde-audio.js).

L'avertissement `LEDC is not initialized` reste visible au premier déclenchement
dans le [journal série](livrables/serial-revalidation-2026-10-08.txt), mais le signal
audio est produit et les publications continuent après le SOS. Aucune correction
du firmware n'a été nécessaire pour cette vérification. Les constats du 2 octobre
ci-dessous restent historiques ; la vidéo ancienne demeure sans son.

Un onglet Wokwi en arrière-plan peut ralentir fortement la simulation et faire
expirer MQTT : garder cet onglet visible pendant la démonstration. Cette session
ne revalide pas la flotte de 45 projets, les bonus facultatifs ni le dashboard.

## Intégration au dashboard Digi4 principal

Le flux est désormais intégré à la grille et à la fiche P001 du dashboard principal (/). La vérification réelle affiche 25 résidents historiques et P001, soit 26 fiches. FC, niveaux warning/danger, SOS, chute à 2,83 g et état offline ont été testés. Une reconnexion du backend conserve la fiche et ses événements.

[Nouvelle vidéo : dashboard Digi4 + Wokwi, 59 s](livrables/video/demo-digi4-wokwi-firefox.webm) · [Capture des alertes](livrables/dashboard-digi4-alertes.png) · [Capture hors ligne](livrables/dashboard-digi4-offline.png).

Le backend historique doit être actif pour afficher les 25 résidents ; Wokwi rejoint le frontend en MQTT over WebSocket. Ses mesures et événements restent dans la session navigateur et ne déclenchent pas le moteur clinique. Les mesures non disponibles restent nulles. La FC disparaît après 15 secondes sans mesure ou dès une déconnexion/offline.

## Résultat vérifié le 2 octobre 2026

- Firmware, montage et bibliothèque PubSubClient@2.8 chargés dans Firefox.
- Compilation ESP32 locale réussie : 791 241 octets de flash (60 %), 46 968 octets de RAM (14 %). Le source compilé correspond exactement au sketch actuel (SHA-256 : 5CC9CF7907BD7EFF00F5B6DDADA3FD0063AC977F7056BDADBCF19D7B2FD126BC).
- MPU-6050 détecté, Wi-Fi connecté et MQTT connecté à broker.hivemq.com.
- Dashboard : FC normale 83–86 bpm, vigilance vers 120 bpm, danger vers 153–156 bpm ; SOS et chute à 2,83 g reçus.
- Après arrêt : ancienne mesure masquée, puis état offline reçu du broker.
- Page locale et syntaxe JavaScript vérifiées. Nouvelle vidéo relue dans Firefox : 59 s, 1980 × 900, aucune erreur de décodage.

## Livrables

[Archive de la page de diagnostic M1 — 1 min 50 s](livrables/video/demo-wokwi-firefox.webm) : captures réelles des deux vues Firefox côte à côte, échantillonnées à 1 image/s et encodées en WebM, sans son. Les pauses entre opérations sont coupées ; ce n'est pas une capture continue du bureau. Aucune publication MQTT artificielle n'a été ajoutée : les mesures viennent du firmware exécuté dans Wokwi.

- [Dashboard et alertes](livrables/dashboard-alertes.png)
- [Wokwi et messages MQTT](livrables/wokwi-mqtt.png)
- [État hors ligne](livrables/dashboard-offline.png)
- [Journal série](livrables/moniteur-serie.txt)
- [État final du dashboard](livrables/etat-final.txt)
- [Firmware complet compilé](livrables/m1-full.bin)
- [Contrat MQTT](../../docs/contrat_mqtt.md)

## Relancer dans Firefox

1. Depuis la racine, ouvrir le dossier dashboard et lancer npm start avec PORT=3003 (la page était déjà disponible pendant la vérification).
2. Ouvrir http://localhost:3003/ et le projet Wokwi ci-dessus.
3. Démarrer la simulation. Si Wokwi affiche « Build Servers Busy », placer le focus dans l'éditeur, appuyer sur F1, rechercher « Upload Firmware and Start Simulation… », puis sélectionner livrables/m1-full.bin.
4. Attendre MPU-6050 détecté, Wi-Fi OK et MQTT OK, puis manipuler le potentiomètre, SOS et les axes du MPU-6050.

La simulation vérifiée utilise le binaire local : les serveurs gratuits Wokwi ont refusé la compilation pour saturation. Le binaire complet a été assemblé avec esptool (bootloader, partitions, boot_app0, sketch). Il doit être chargé à nouveau lors d'une nouvelle session si la compilation en ligne reste indisponible. Méthode : [documentation officielle Wokwi](https://docs.wokwi.com/guides/esp32).

## Limites et matériel

Le dashboard principal et sa pile Docker ont été vérifiés en fonctionnement ; la page M1 dédiée reste un outil de diagnostic. Le journal série contient un avertissement LEDC lors de la première alarme ; le son du buzzer n'a pas été validé, et la vidéo est muette. Les mesures arrivent toutes les 2 secondes du temps simulé ; la simulation tournait moins vite que le temps réel.

Identifiants fictifs : équipe lebretyves-ehpad-m1, patient P001, device esp32-01. Aucun secret réel dans le firmware. SpO2 et température restent non mesurées.

GPIO : MPU SDA 21 / SCL 22 ; SOS 18 vers GND ; buzzer 19 ; potentiomètre ADC1 34. Alimentation 3,3 V. Sur le matériel réel : adapter le Wi-Fi, remplacer le potentiomètre par le MAX30102 et son traitement PPG, isoler les secrets hors Git. Détection de chute pédagogique, sans finalité diagnostique.
