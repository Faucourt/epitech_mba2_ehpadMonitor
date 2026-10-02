# TP M1 — ESP32 Wokwi → MQTT → EHPAD

Firmware adapté du TP fourni, avec une seule bibliothèque externe `PubSubClient@2.8`. Identifiants fictifs : équipe `lebretyves-ehpad-m1`, patient `P001`, device `esp32-01`.

## Démarrage

1. Depuis la racine : `cd dashboard`, `npm ci`, puis en PowerShell `$env:PORT=3003; npm start`.
2. Ouvrir http://localhost:3003/m1.html à gauche de l'écran.
3. Créer un projet https://wokwi.com/projects/new/esp32 et copier les trois fichiers de ce dossier dans les onglets correspondants : `sketch.ino`, `diagram.json`, `libraries.txt`.
4. Enregistrer avec un compte Wokwi, puis démarrer la simulation à droite de l'écran.
5. Attendre `MPU-6050 détecté`, `Wi-Fi OK`, `MQTT ... OK`, puis les publications et la courbe de FC.

**Lien Wokwi enregistré : à renseigner après création dans Wokwi.** Le lien ci-dessus ouvre un nouveau projet vierge, pas le projet réalisé.

## Livrable demandé : vidéo de l'écran

Le dashboard doit être à gauche, le simulateur Wokwi à droite, simultanément visibles. Utiliser le bouton d'enregistrement du dashboard, choisir l'écran entier (et non seulement l'onglet), puis arrêter et télécharger le fichier `.webm`. La sélection d'écran exige un geste et une autorisation du navigateur.

Scénario conseillé (environ 90 s) :

- 0–15 s : connexions et FC de repos, publications toutes les 2 s.
- 15–35 s : tourner le potentiomètre, dépasser 110 puis 130 bpm ; montrer courbe et alertes.
- 35–45 s : appuyer sur SOS et montrer l'événement reçu.
- 45–60 s : régler deux axes du MPU-6050 à 2 g (norme >2,5 g), montrer l'alerte de chute.
- Arrêter Wokwi et attendre jusqu'à 45 s pour montrer le Last Will offline.

Déposer la vidéo finale dans `livrables/` ou comme fichier de release GitHub si elle est volumineuse. Une capture artificielle ou un flux injecté de test ne remplace pas la preuve Wokwi.

## Validation et état

Le contrat exact est dans [docs/contrat_mqtt.md](../../docs/contrat_mqtt.md).

- Fichiers du TP extraits, identifiants adaptés, montage JSON vérifié.
- Compilation et exécution Wokwi : à valider dans le simulateur.
- Vidéo finale : pas encore enregistrée.

## Passage au matériel

GPIO : MPU SDA 21 / SCL 22 ; bouton SOS 18 vers GND ; buzzer 19 ; potentiomètre ADC1 34. Alimentation capteurs 3,3 V. Sur la carte réelle : changer le Wi-Fi (canal 0), remplacer le potentiomètre par le MAX30102 et son traitement PPG, sortir les secrets dans un fichier ignoré par Git. Détection de chute par seuil pédagogique, sans finalité diagnostique.

### Vérifications exécutées le 2 octobre 2026

- Page `/m1.html`, JS, CSS et MQTT.js : HTTP 200 sur `localhost:3003`.
- Syntaxe `node --check dashboard/public/m1.js` valide.
- Tests isolés des handlers : normalisation, absence de mesures non disponibles, rejet JSON/identifiants invalides, SOS, statut offline, mesure périmée et masquage après 7 s.
- Connexion réelle WSS HiveMQ et SUBACK QoS 1 sur les trois topics du contrat, sans aucune publication de données artificielles.
- Sauvegarde du dashboard existant dans `backup_avant_m1/` (exclue de Git), empreinte de la page d'origine inchangée.

Limites : aucune compilation ESP32 ni simulation Wokwi validée dans cette session. Contrôle navigateur indisponible (erreur ACL de l'environnement) ; pas de capture visuelle ni de vidéo finale. La pile historique Docker du projet source a été rétablie après sauvegarde et réparation de Redis ; elle ne fait pas partie de cette copie autonome.

