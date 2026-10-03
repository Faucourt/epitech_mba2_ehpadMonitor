# Fonctionnement collectif

Le générateur regroupe les 437 points d'acquisition sur 45 ESP32 : une carte par
résident (25) et par zone (20). Chaque composant reste distinct ; chaque pilote
possède son état, ses broches et son identifiant. Aucune mesure d'un résident
n'est recopiée chez un autre.

## Exécution

Le 3 octobre 2026, le lancement Wokwi CLI des **23 cartes / 214 capteurs** a
été vérifié simultanément pendant au moins 30 secondes, avec réception MQTT
dans le backend : [preuve enregistrée](validation/collective/cli-recovery-2026-10-03.json).
Cette preuve est datée ; l'état actuel se lit dans `build/collective-runtime/status.json`.
La communication ne garantit pas une mesure pour les appareils attendant une
action (par exemple START du tensiomètre ou présentation d'un badge).

Le lanceur Windows exporte les autorités racines déjà approuvées pour TLS dans
`build/collective-runtime/windows-ca.pem`, puis les fournit au CLI via
`NODE_EXTRA_CA_CERTS`. La vérification TLS reste activée. Une configuration
`NODE_EXTRA_CA_CERTS` existante est conservée. Le démarrage cloud dispose de
300 secondes avant la première trame ; ensuite le délai série habituel s'applique.

Depuis la racine, `./Start-Wokwi.ps1` démarre une acquisition continue. Avec le
jeton Wokwi CI configuré, il utilise les 23 cartes du pilote. Sans jeton, il
ouvre quatre simulations Chromium : R001, R002, R003 et l'entrée (42 capteurs).
**Ce mode navigateur ne lance pas les 19 autres zones.** Le dashboard est
http://localhost:3005/?source=wokwi ; l'environnement est visible dans
http://localhost:3005/hardware.html, onglet Environnement.

`./Start-Wokwi.ps1 -Check` vérifie les prérequis compilés sans lancer de
simulation. `-Full` exige le jeton avant le lancement des 23 cartes. Le mode
navigateur installe Playwright 1.58.2 dans `build/browser-deps` si nécessaire,
utilise Python/paho pour transmettre les trames UART courantes et conserve son
état dans `build/browser-pilot/status.json`. Garder son processus et Chromium
ouverts ; fermer les simulations arrête les mesures. Les boutons START des
tensiomètres et la présentation des badges sont actionnés une fois au démarrage.
Les valeurs restent celles des composants Wokwi. Une erreur de lecture est
signalée, sans rejeu des anciennes trames. Une page bloquée est recréée, avec
arrêt après trois échecs consécutifs. Les pages sont renouvelées toutes les
30 minutes pour libérer la mémoire de la simulation et du moniteur série ;
les mesures peuvent être brièvement indisponibles pendant leur redémarrage.

`./Start-Wokwi.ps1 -Browser` force ce mode limité même si un jeton est enregistré,
notamment quand Wokwi refuse le lancement CI pour quota mensuel épuisé. Ce refus
arrête les tentatives automatiques ; les 19 autres zones restent hors ligne.
La preuve CLI ci-dessus décrit un essai antérieur, pas une disponibilité permanente.
Le lanceur complet démarre Docker Desktop si son moteur est arrêté.

Priorité de validation : **R001, R002 et R003 complets, plus les 20 zones**,
soit **23 ESP32 / 214 points d'acquisition**. Le mode `-Pilot` sélectionne
exactement ce périmètre, sans publier à la place des 22 autres résidents.

Les [projets et traces des essais collectifs](validation/collective/README.md)
séparent les essais successifs de chaque zone de l'observation simultanée limitée
aux trois résidents et à l'entrée. Une validation successive ne signifie pas
que les vingt zones sont actuellement actives ensemble.

```powershell
python firmware/all_sensors/tools/build_collective.py --pilot --cli arduino-cli
python firmware/all_sensors/tools/run_collective.py --pilot --check
./firmware/all_sensors/Start-Collective.ps1 -Pilot -Seconds 120
```

Cette préparation ne constitue pas une preuve d'exécution simultanée. Consulter
`build/collective-runtime/verification.json` pour une validation effective ; les
capteurs non lancés restent déconnectés sur http://localhost:3005/.

Prérequis : Docker, Python avec `requirements-collective.txt`, Arduino CLI et les
bibliothèques du projet, Wokwi CLI, et un jeton Wokwi CI dans la variable utilisateur
`WOKWI_CLI_TOKEN`. Le jeton n'est ni un argument de commande ni un fichier du dépôt.

Depuis la racine du dépôt :

```powershell
python -m pip install -r firmware/all_sensors/requirements-collective.txt
python firmware/all_sensors/tools/export_collective.py
python firmware/all_sensors/tools/build_collective.py --cli arduino-cli
python firmware/all_sensors/tools/run_collective.py --check
./firmware/all_sensors/Start-Collective.ps1 -Seconds 120 -VerifySeconds 30
```

Pour une exécution continue, passer explicitement `-Seconds 0`.
Pour un seul résident, utiliser `-Entity R001`. `-Build` régénère et compile les
projets avant leur lancement ; `-ArduinoCli` permet de choisir le chemin du CLI.
Les exports et empreintes sont dans `collective/`. Les fichiers binaires sont
compilés localement dans les sous-dossiers `build/`, exclus de Git.

La durée Wokwi CI est cumulée entre les cartes : 45 cartes pendant une minute
simulée consomment 45 minutes de simulation. Le quota du compte doit couvrir
l'essai. Le superviseur arrête les relances automatiques lorsque Wokwi refuse
l'accès ou le quota ; il ne souscrit aucun abonnement.

## Acquisition et réseau

La simulation collective utilise une passerelle UART vers MQTT local. Le firmware
ESP32 lit les composants Wokwi et écrit les trames `SAMPLE`. Le superviseur vérifie
l'identité de chaque trame puis transmet son contenu inchangé au broker local
`127.0.0.1:1887`, sans rétention. Il ne calcule aucune valeur de capteur et ne
rejoue aucune trace. La communication réseau ne bloque ainsi pas l'acquisition
dans le microcontrôleur simulé. Le backend écoute le broker Docker `mqtt`.

Le code exporté avec `--hardware` conserve le transport WiFi/MQTT direct.
L'export matériel utilise par défaut `hardware-private/collective/`, exclu de Git,
et laisse les projets Wokwi existants en place :

```powershell
python firmware/all_sensors/tools/export_collective.py --hardware --entity R001
```

Le contrôle des valeurs finies du DHT22 utilise les bits IEEE-754 du `float`
ESP32 pour éviter l'instruction `ULT.S` non prise en charge dans le moteur web
observé. Le HX711 réinitialise son horloge par `power_down` / `power_up` lors de
l'initialisation et de la reprise après absence de mesure. Ces deux adaptations
s'appliquent aussi à l'export matériel ; aucune valeur de remplacement n'est créée.
Configurer ses identifiants réseau et calibrations dans un dossier privé.
Le BLE simulé conserve sa limite de test I²C ; la radio reste un essai matériel.
Les niveaux 5 V / 3,3 V et les interfaces physiques doivent être adaptés.

## Vérification et supervision

`build/collective-runtime/status.json` rapporte les cartes démarrées, redémarrages,
erreurs et capteurs effectivement reçus dans le backend. La preuve de couverture
exige un message récent pour chaque identifiant et le même `boot` que le firmware
de cette exécution. Une ancienne simulation ou un message synthétique ne peut
donc pas compléter le compteur de vérification.

`verification.json` n'est produit avec `result: passed` qu'après la durée de
couverture complète demandée. Une compilation seule n'est pas cette preuve.
Les logs sont limités par rotation et les jetons sont masqués. Ctrl+C arrête les
processus Wokwi lancés par le superviseur ; la stack Docker reste disponible.

Le dashboard distingue **capteurs qui publient** et **mesures récentes**. Un
tensiomètre peut communiquer tout en attendant START ; un lecteur RFID peut
communiquer sans badge. Cela ne doit jamais devenir une fausse mesure normale.
L'arrêt des messages fait expirer la communication au bout de 15 secondes.

## Synchronisation GitHub

Les trois dépôts de livraison sont :

- https://github.com/lebretyves/D-tection-de-malaise-en-EHPAD
- https://github.com/lebretyves/epitech_mba2_ehpadMonitor
- https://github.com/Faucourt/epitech_mba2_ehpadMonitor

Après publication du nouveau commit sur l'un des dépôts :

```powershell
python scripts/sync_repositories.py --apply
```

Le script compare toutes les branches, ajoute celles qui manquent et avance les
branches compatibles. Il vérifie ensuite l'égalité des commits sur les trois
dépôts. Une divergence interrompt la synchronisation ; aucun push forcé ni aucune
suppression de branche ne sont effectués.

Sources : [Wokwi CLI](https://docs.wokwi.com/wokwi-ci/cli-usage),
[temps et quotas](https://docs.wokwi.com/wokwi-ci/getting-started).
