# TP M1 — EHPAD / Wokwi / MQTT

Ajout du TP au dépôt de l'équipe, sans modifier la note de cadrage existante.

## Origine du projet

Ce TP s'appuie sur le projet EHPAD d'origine : **[Détection de malaise en EHPAD — dépôt complet](https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD)**.

Le dépôt d'origine contient l'application EHPAD multi-patients. Ce dépôt regroupe l'adaptation du TP M1 : firmware ESP32 Wokwi, dashboard MQTT dédié au patient fictif P001 et livrables de démonstration.

## Lancer le dashboard

Prérequis : Node.js et npm.

```sh
cd dashboard
npm ci
npm start
```

Ouvrir http://localhost:3003/m1.html. Si le port est occupé, définir `PORT` avant de lancer le serveur. Ce dashboard du TP est autonome ; il ne contient pas l'application historique des 25 résidents.

## Firmware et démonstration

- [Firmware ESP32, câblage et guide vidéo](firmware/m1_wokwi/README.md)
- [Contrat MQTT](docs/contrat_mqtt.md)
- [Projet Wokwi réalisé](https://wokwi.com/projects/476777815517850625)
- [Vidéo Firefox — 1 min 50 s](firmware/m1_wokwi/livrables/demo-wokwi-firefox.webm)

Les fichiers sont déjà chargés dans le projet Wokwi. La page reçoit les publications du firmware via HiveMQ ; aucune donnée ne s'affiche avant de lancer le simulateur. Si les serveurs Wokwi affichent « Build Servers Busy », charger [m1-full.bin](firmware/m1_wokwi/livrables/m1-full.bin) depuis l'éditeur avec F1 → Upload Firmware and Start Simulation.

La vidéo fournie juxtapose des captures réelles des deux vues Firefox, à une image par seconde, sans son. Les pauses entre opérations sont coupées ; ce n'est pas une capture continue du bureau. Les données viennent réellement de l'ESP32 Wokwi, sans messages de test injectés.

**État du rendu :** compilation locale ESP32 validée ([preuve](firmware/m1_wokwi/livrables/compilation.md)), simulation exécutée dans Firefox avec le binaire local, réception de la FC, des alertes de fréquence, SOS et chute, puis de l'état hors ligne. Vidéo relue dans Firefox et captures incluses. La compilation en ligne était saturée ; le son du buzzer n'a pas été validé.

**Périmètre : un patient fictif P001**, FC simulée par potentiomètre, chute par MPU-6050 et bouton SOS. SpO₂ et température non mesurées. L'intégration à l'application historique multi-patients n'est pas incluse.

Les informations Digi4 dans le contrat décrivent le [projet source](https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD), dont la page M1 a été extraite. Les données sont fictives et les seuils pédagogiques.
