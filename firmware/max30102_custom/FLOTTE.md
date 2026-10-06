# Préparation et publication de la flotte — 6 octobre 2026

La correction MAX30102 est intégrée aux sources et aux fichiers locaux de la
flotte. Les **45 firmwares ESP32 ont compilé avec succès** : 25 résidents et
20 zones, représentant 437 capteurs déclarés dans l'inventaire.

Les **45 copies corrigées sont désormais sauvegardées sur Wokwi**, avec
733 fichiers contrôlés dans les archives téléchargées. Consulter les
[liens finaux](../../output/wokwi-transfert/LIENS-WOKWI.txt),
l'[index](../../output/wokwi-transfert/pages-corrigees.json) et les
[rapports de comparaison](../../output/wokwi-transfert/verified/).
Quatre modèles ont été observés dans le navigateur : R001, R002, R009 et
l'entrée. La publication complète ne signifie pas que les 45 simulations
ont été exécutées ensemble. Le [bilan détaillé](../../docs/BILAN-WOKWI-2026-10-06.md)
distingue les sources contrôlées, les essais datés et les limites.

## Vérifications terminées

- Les sources et empreintes des 45 binaires correspondent au rapport de compilation.
- Le contrôle `run_collective.py --check` accepte toute la flotte.
- Les 26 cartes utilisant le MAX30102 possèdent le même composant WebAssembly
  corrigé et la nouvelle acquisition I²C.
- Les 29 tests Python et 20 tests Node relancés passent. Le test natif C++ est
  ignoré sous Windows faute de compilateur ; ses six cas avaient été exécutés
  avec succès dans le conteneur lors de la préparation du banc autonome.

Les [preuves et empreintes par carte](../../output/max30102-fleet-validation/fleet.json)
et le [contrôle du composant](../../output/max30102-fleet-validation/custom-chip-check.json)
sont enregistrés localement.

## Historique des limites et essais restant à faire

Le 5 octobre, une nouvelle tentative Wokwi CI a contacté le service, qui a refusé la simulation
pour dépassement du quota mensuel gratuit. Le [résultat de cette tentative](../../output/max30102-fleet-validation/wokwi-probe.json)
est conservé. Aucun navigateur pilotable n'était connecté lors de cette tentative ;
les observations et publications par navigateur ont été réalisées ensuite.
Aucun port série ESP32 n'a été détecté ; aucun flashage ni essai physique n'a eu lieu.

Les compilations et la publication ne valident pas les 45 simulations simultanées.
La stabilité optique prolongée et la réception MQTT de cette version restent à vérifier.

L'[historique de reprise](../../output/wokwi-transfert/REPRISE-WOKWI.txt) et la
[sauvegarde complète](../../output/sauvegardes-wokwi/WOKWI-REPRISE-DERNIERE.zip)
conservent l'état final de publication.

## Reprendre après rétablissement de l'accès Wokwi

Depuis la racine du dépôt, commencer par une seule carte :

```powershell
python firmware/all_sensors/tools/run_collective.py --entity R001 --seconds 120 --verify-seconds 30 --stop-after-verify --output build/max30102-r001-verification
```

Puis vérifier la flotte complète :

```powershell
python firmware/all_sensors/tools/run_collective.py --seconds 120 --verify-seconds 30 --stop-after-verify --output build/max30102-fleet-verification
```

Le backend de laboratoire sur le port 8005 et le broker local sur le port 1887
doivent être démarrés. Le jeton Wokwi reste dans l'environnement utilisateur.
Le lanceur vérifie les mesures réellement reçues ; il ne remplace pas les
capteurs absents par des données inventées. Le raccourci historique
`Start-Wokwi.ps1 -Full` conserve son périmètre pilote : trois résidents et vingt
zones ; la seconde commande ci-dessus sélectionne les 45 groupes.
