# Fonctionnement collectif

Le générateur regroupe les 437 points d'acquisition sur 45 ESP32 : une carte par
résident (25) et par zone (20). Chaque composant reste distinct ; chaque pilote
possède son état, ses broches et son identifiant. Aucune mesure d'un résident
n'est recopiée chez un autre.

## Exécution

Priorité de validation : **R001, R002 et R003 complets, plus les 20 zones**,
soit **23 ESP32 / 214 points d'acquisition**. Le mode `-Pilot` sélectionne
exactement ce périmètre, sans publier à la place des 22 autres résidents.

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
