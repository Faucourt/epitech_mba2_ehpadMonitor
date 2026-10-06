# MAX30102 personnalisé — banc ESP32

Ce banc reprend le composant développé dans `firmware/all_sensors` et
renforce la lecture de sa mémoire FIFO. Il remplace la simulation par
potentiomètre pour le test du MAX30102. L'ancien projet M1 reste une démonstration
datée. Les 45 copies collectives corrigées ont été publiées et vérifiées le
6 octobre 2026 : voir le [bilan Wokwi](../../docs/BILAN-WOKWI-2026-10-06.md).

## Contenu

- `simulation/` : montage ESP32 + MAX30102 custom, source C du composant,
  binaire WebAssembly, firmware Arduino et configuration Wokwi.
- `materiel/` : même acquisition I²C et même calcul optique, configuration
  réseau à renseigner avant flashage. Aucun composant custom n'est à charger
  dans l'ESP32 physique : il est remplacé par le module MAX30102 réel.
- `tests/` : tests du WebAssembly et des erreurs d'acquisition C++.
- `tools/build.py` : compilation Arduino CLI locale.

Le programme utilise SparkFun MAX3010x 1.1.2 pour identifier/configurer le
MAX30102 à l'adresse `0x57`, puis lit des paires rouge/infrarouge de six octets.
La configuration est 100 mesures/s avec moyenne sur quatre mesures, soit
25 échantillons/s dans la FIFO. L'algorithme Maxim travaille sur 100 échantillons.
Les mêmes fichiers `sensors.h`, `protocols.h`, `nibp.h` et `sketch.ino` sont
utilisés dans les deux versions ; seul `device_config.h` change.

## Corrections apportées le 5 octobre 2026

- FIFO custom de 32 échantillons, compteur de débordement saturé à 31,
  conservation des données non lues quand le remplacement est désactivé.
- Copie stable d'une paire optique pendant sa lecture ; le pointeur avance au
  premier octet, conformément à la fiche technique.
- Vérification du nombre d'octets reçus sur I²C : un transfert incomplet invalide
  les mesures et demande une réinitialisation lors de la prochaine tentative
  périodique du programme (jusqu'à environ 15 secondes).
- Acquisition directe de toutes les paires disponibles, évitant la perte
  d'échantillons liée au tampon logiciel de quatre places du pilote SparkFun.
- Abandon de la fenêtre de calcul après débordement ou interruption prolongée.
  Retirer le doigt laisse FC et SpO₂ non mesurées.

Ces corrections couvrent des défauts reproductibles en tests. Elles ne prouvent
pas à elles seules la cause de l'anomalie observée lors de l'ancien essai prolongé
de R001, ni sa résolution dans le navigateur.

## Utiliser dans Wokwi

Ouvrir le dossier `simulation/` dans VS Code et utiliser sa configuration
`wokwi.toml`, après compilation. Le binaire custom est déjà fourni.

Sur le site Wokwi, créer un projet ESP32 et un Custom Chip nommé `max30102`,
puis y transférer les fichiers de `simulation/` : sketch, en-têtes, bibliothèques,
diagramme et fichiers `max30102.chip.c` / `max30102.chip.json`. Le modèle C est
autonome : aucun `model.h` externe n'est nécessaire. Les curseurs `bpm`,
`redRatio`, `finger` et `connected` règlent le signal fictif et les défauts.
Le curseur hérité `corrupt` n'est pas implémenté pour ce modèle.

Ne pas lancer ce banc avec un autre émetteur portant la même identité
`R001-wearable-max30102`. Il publie sur le contrat de l'extension d'acquisition
`ehpad/lab/lebretyves-all/v1/R001-wearable-max30102/telemetry`, et non sur
le contrat P001 de l'ancienne démonstration M1. L'intégration correspondante
est dans ce dépôt, avec les sources de flotte dans `firmware/all_sensors`
(dashboard de laboratoire sur le port 3005).

## Compiler et tester

Depuis la racine du dépôt, avec Arduino CLI, le core ESP32 2.0.17 et les
bibliothèques de `simulation/libraries.txt` installés :

```powershell
python firmware/max30102_custom/tools/build.py firmware/max30102_custom/simulation
python firmware/max30102_custom/tools/build.py firmware/max30102_custom/materiel
node --test firmware/max30102_custom/tests/max30102.test.cjs
python firmware/max30102_custom/tests/test_optical_acquisition.py
```

Le test C++ nécessite `g++` ou `CXX=clang++` ; sans compilateur il est signalé
comme ignoré, pas réussi. Il a été exécuté dans le conteneur de compilation local.
Pour recompiler le composant : `wokwi-cli chip compile max30102.chip.c -o
max30102.chip.wasm` depuis `simulation/`.

## Vérifications locales du 5 octobre 2026

- Compilation ESP32 simulation : réussie, 789 817 octets de programme et
  47 540 octets de RAM statique.
- Compilation ESP32 matériel : réussie, 1 574 757 octets de programme et
  60 404 octets de RAM statique (partition `huge_app`).
- Trois tests du composant WebAssembly : réussis.
- Six cas C++ d'acquisition : réussis dans le conteneur local.
- Extension existante : 12 tests WebAssembly réussis ; 29 tests Python réussis,
  un test C++ ignoré sous Windows puis exécuté séparément avec succès.

Les compilations ont émis un avertissement Unicode dans `gen_esp32part.py`,
sans échec de compilation. Les empreintes des livrables sont dans `validation.json`.

Les journaux de préparation contiennent le refus de quota mensuel Wokwi CI.
Lors de cette étape locale du 5 octobre, le banc autonome n'avait pas été
exécuté dans Wokwi ni sur un ESP32 physique. Des modèles collectifs corrigés
ont ensuite été observés dans le navigateur ; ces observations ne constituent
pas un essai de ce banc autonome ni une validation physique.

## Passage au matériel et limites

Renseigner le Wi-Fi, le broker et les identifiants dans
`materiel/device_config.h`. SDA = GPIO21, SCL = GPIO22, masse commune.
Utiliser un **module MAX30102 avec alimentation et adaptation logique compatibles
ESP32** ; la puce nue demande une alimentation 1,8 V distincte de celle des LED.
Vérifier le schéma du module avant de reproduire le branchement 3,3 V simulé.

Le modèle représente le sous-ensemble utilisé ici (mode rouge + IR, 25 Hz FIFO).
Il ne simule pas l'optique réelle, les interruptions électriques ni tous les modes
et réglages du composant. Le portage de l'acquisition est préparé ; les seuils,
le contact du doigt, la qualité du signal et les résultats FC/SpO₂ devront être
validés sur le matériel. Les valeurs simulées ne valident pas une mesure clinique.

Les sources partagées de l'extension ont également été corrigées. Les exports
locaux (437 configurations et 45 groupes) ont été régénérés pour rester cohérents
avec les sources. **Les 45 firmwares collectifs sont désormais recompilés** :
25 résidents et 20 zones, soit 437 capteurs déclarés. Le contrôle du lanceur
confirme que chaque binaire correspond à ses sources. Les 26 cartes intégrant
un MAX30102 (25 résidents et kinésithérapie) utilisent le composant corrigé.

La tentative Wokwi CI du 5 octobre a été refusée pour quota mensuel épuisé.
La publication par navigateur a ensuite été terminée le 6 octobre :
[45 liens corrigés](../../output/wokwi-transfert/LIENS-WOKWI.txt),
[index de publication](../../output/wokwi-transfert/pages-corrigees.json) et
[733 fichiers vérifiés](../../output/wokwi-transfert/verified/).
Quatre modèles collectifs ont été observés : R001, R002, R009 et l'entrée.
R001 a été observé avant sauvegarde de sa copie finale, puis celle-ci a été
contrôlée par téléchargement. La flotte complète et la stabilité prolongée
ne sont pas validées par ces observations ; aucun essai physique n'a eu lieu.
Voir le [bilan de flotte](FLOTTE.md) et la
[sauvegarde complète](../../output/sauvegardes-wokwi/WOKWI-REPRISE-DERNIERE.zip).

## Références

- [MAX30102 — fiche technique constructeur, FIFO pages 13–16](https://www.analog.com/media/en/technical-documentation/data-sheets/max30102.pdf)
- [Wokwi — composants personnalisés](https://docs.wokwi.com/chips-api/getting-started)
- [Wokwi — API I²C](https://docs.wokwi.com/chips-api/i2c)
- [Wokwi — compilation WebAssembly](https://docs.wokwi.com/guides/custom-chips-to-wasm)
