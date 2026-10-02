# TP M1 — EHPAD / Wokwi / MQTT

Ajout du TP au dépôt de l'équipe, sans modifier la note de cadrage existante.

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
- [Nouveau projet ESP32 Wokwi](https://wokwi.com/projects/new/esp32)

Copier `sketch.ino`, `diagram.json` et `libraries.txt` dans Wokwi. La page reçoit les publications du firmware via HiveMQ ; aucune donnée ne s'affiche avant de lancer le simulateur.

Livrable demandé : vidéo de l'écran avec le dashboard à gauche et Wokwi à droite. Le bouton « Enregistrer l'écran » permet une capture réelle au format WebM.

**État du rendu :** code et contrat fournis ; abonnements au broker vérifiés. Compilation locale ESP32 validée ([preuve](firmware/m1_wokwi/livrables/compilation.md)) ; exécution Wokwi à valider, lien du projet Wokwi enregistré à ajouter et vidéo finale à enregistrer. Aucun fichier vidéo n'est inclus à ce stade.

Les informations Digi4 dans le contrat décrivent le projet source `lebretyves/D-tection-de-malaise-en-EHPAD`, dont la page M1 a été extraite. Les données sont fictives et les seuils pédagogiques.
