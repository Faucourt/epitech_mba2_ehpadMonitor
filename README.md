# TP M1 — Wokwi intégré au dashboard Digi4

## Origine du projet

Ce dépôt reprend le frontend du [projet complet Détection de malaise en EHPAD](https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD) et y intègre le flux ESP32 Wokwi. La note de cadrage existante est conservée.

## Démonstration corrigée

Le **dashboard principal** (/, dashboard/public/index.html) affiche les 25 résidents historiques fournis par le backend et **P001 Wokwi** dans la même grille. Cliquer sur la carte P001 ou le bouton Wokwi ouvre sa fiche : fréquence cardiaque, courbe, SOS, chute et état du dispositif. La page /m1.html reste disponible pour le diagnostic ; elle n'est plus le livrable principal.

- [Nouvelle vidéo du dashboard Digi4 + Wokwi — 59 secondes](firmware/m1_wokwi/livrables/demo-digi4-wokwi-firefox.webm)
- [Capture du dashboard principal et des alertes](firmware/m1_wokwi/livrables/dashboard-digi4-alertes.png)
- [Capture après arrêt du dispositif](firmware/m1_wokwi/livrables/dashboard-digi4-offline.png)
- [Validation de session](firmware/m1_wokwi/livrables/validation-digi4.json)
- [Projet Wokwi](https://wokwi.com/projects/476777815517850625)
- [Firmware et méthode de chargement](firmware/m1_wokwi/README.md)
- [Contrat MQTT](docs/contrat_mqtt.md)

## Démarrer

Pour retrouver les 25 résidents historiques, démarrer la pile du **dépôt d'origine** : backend sur http://localhost:8001, Redis, InfluxDB, Mosquitto et simulateur. Le présent dépôt fournit le frontend intégré et les livrables ; il ne duplique pas ces services backend.

Dans ce dépôt, avec Node.js et npm : lancer **cd dashboard**, puis **npm ci**, puis **npm start**.

Ouvrir **http://localhost:3003/**. Le serveur utilise le backend local sur le port 8001 ; PORT permet de changer le port du frontend. Sans backend, seule la fiche Wokwi est disponible et les fonctions historiques sont indisponibles.

Ouvrir le projet Wokwi puis démarrer la simulation. En cas de « Build Servers Busy », placer le focus dans l'éditeur, appuyer sur F1 et choisir **Upload Firmware and Start Simulation…**, puis charger [m1-full.bin](firmware/m1_wokwi/livrables/m1-full.bin). Ne garder qu'une simulation active pour ce dispositif.

## Validation et périmètre

Vérifié dans Firefox le 2 octobre 2026 : 26 fiches (25 historiques + P001), FC normale puis warning/danger, SOS, chute à 2,83 g, état offline et masquage de la FC ; reconnexion du WebSocket backend sans perte de P001 ni de ses événements. Quatre tests du contrat et de la fraîcheur : **node --test tests/wokwi-feed.test.cjs**.

Un seul ESP32 est simulé : il alimente P001, sans remplacer les autres résidents. SpO₂, température, pression artérielle et respiration restent non mesurées. Aucun score clinique n'est calculé pour P001 ; ses événements pédagogiques restent dans sa fiche et ne déclenchent pas les notifications soignants. Courbe et événements sont gardés en mémoire dans la session navigateur, sans archivage backend.

La vidéo juxtapose des captures réelles des deux vues Firefox à une image par seconde, sans son ; les pauses entre opérations sont coupées. La passerelle publique Wokwi a nécessité une relance pendant les essais. Aucun message MQTT artificiel n'a été injecté. Le son du buzzer n'a pas été validé. L'ancienne vidéo de la page M1 est conservée comme archive.
