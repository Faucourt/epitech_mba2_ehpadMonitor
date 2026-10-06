# Bilan Wokwi — 6 octobre 2026

Les **45 projets collectifs corrigés sont sauvegardés sur Wokwi et leurs sources
ont été vérifiées après téléchargement** : 25 résidents et 20 zones, représentant
437 points d'acquisition. Aucun projet ne reste à publier ni à contrôler dans
l'[index de publication](../output/wokwi-transfert/pages-corrigees.json).

## Réalisation

- Regroupement des capteurs sur un ESP32 par résident ou zone, avec identifiants,
  broches et état d'acquisition propres à chaque composant. Les 437 configurations
  individuelles restent disponibles pour les essais par famille.
- Intégration des capteurs natifs et personnalisés : optique, mouvement,
  température, SOS, ECG, respiration, tension artérielle, présence, lit/sol,
  portes, CO₂, COV, gaz, CO, son, thermique, GPS, RFID et fixture BLE.
- Correction du MAX30102 : FIFO de 32 échantillons, gestion du débordement,
  lecture stable des paires rouge/infrarouge, détection des transferts I²C
  incomplets, réinitialisation et abandon des fenêtres de calcul discontinues.
  La correction est propagée aux 26 cartes concernées : 25 résidents et
  kinésithérapie. Une absence de mesure ne produit pas de valeur de remplacement.
- Adaptations de simulation déjà intégrées : conversion ADC virtuelle pour
  ECG/respiration/son, câblage MQ-2 propre à Wokwi, contrôle des valeurs DHT22
  compatible avec le moteur web observé et reprise de l'horloge HX711.
- Création des copies corrigées sur le site, ajout des composants nécessaires,
  adaptation des configurations et câblages, enregistrement puis téléchargement
  de chaque projet. Les [45 liens finaux](../output/wokwi-transfert/LIENS-WOKWI.txt)
  identifient les copies à utiliser ; les anciennes démonstrations restent datées.

## Contrôles de cette livraison

Les [45 rapports de comparaison](../output/wokwi-transfert/verified/) sont tous
réussis. Ils couvrent **733 fichiers sources attendus** : 688 identiques octet
pour octet, 44 diagrammes acceptés après normalisation CRLF/LF et une exception
visuelle documentée pour le placement de l'ESP32 de R001. Aucun fichier source
manquant, inattendu ou différent hors de ces exceptions n'est accepté. Les
métadonnées natives des ZIP relient les archives aux URL publiées.

Quatre modèles ont été observés dans le navigateur pendant cette intervention :

| Modèle | Identifiants de capteurs observés | Preuve |
|---|---:|---|
| R001, avec HX711 | 11 | [325 trames archivées](../output/wokwi-transfert/R001-browser-simulation.json) |
| R002, avec radar | 10 | [102 trames archivées](../output/wokwi-transfert/R002-browser-simulation.json) |
| R009, avec PIR | 10 | [44 trames archivées](../output/wokwi-transfert/R009-browser-simulation.json) |
| Entrée | 10 | [192 trames archivées](../output/wokwi-transfert/entree-browser-simulation.json) |

R001 a été observé avec ses corrections avant sauvegarde de la copie finale ;
celle-ci a ensuite été vérifiée par téléchargement. Les observations sont des
trames UART, comprenant aussi les états sans mesure attendus, par exemple un
RFID sans badge. Elles ne prouvent ni l'exécution des 45 projets simultanément,
ni la réception dans le dashboard de chacun des projets nouvellement publiés.

Le [rapport local du 5 octobre](../output/max30102-fleet-validation/fleet.json)
conserve les empreintes des 45 firmwares recompilés, le contrôle du lanceur,
29 tests Python et 20 tests Node réussis. Le test C++ natif a été ignoré sous
Windows faute de compilateur ; ses six cas ont été exécutés séparément dans
le conteneur. Le [contrôle du composant](../output/max30102-fleet-validation/custom-chip-check.json)
confirme la propagation de la correction aux 26 cartes utilisant le MAX30102.

## Essais antérieurs et limites

Les preuves historiques couvrent [21 familles et 62 scénarios](../firmware/all_sensors/validation/WOKWI.md),
ainsi que [23 cartes / 214 capteurs](../firmware/all_sensors/validation/collective/README.md).
Une [preuve CLI du 3 octobre](../firmware/all_sensors/validation/collective/cli-recovery-2026-10-03.json)
porte sur leur réception simultanée pendant au moins 30 secondes. Ces essais
précèdent la correction optique et ne valident pas les 45 projets corrigés.

Le refus de quota Wokwi CI du 5 octobre est conservé dans les preuves. La
publication par navigateur a ensuite été terminée. La stabilité prolongée,
la reprise optique après interruptions et l'exécution complète de cette version
restent à éprouver. Les [limites observées](../firmware/all_sensors/validation/collective/LIMITES_EXECUTION.md)
conservent les incidents mémoire et l'anomalie optique de l'ancien essai R001.
Aucun essai physique ni validation clinique n'est établi. La fixture BLE ne
valide pas la radio et le custom tensiomètre ne simule pas la pneumatique.

## Acheminement vers le dashboard

Les projets collectifs lisent leurs composants et émettent des trames `SAMPLE`.
La passerelle locale transmet ces trames UART vers MQTT, puis le backend les
affiche dans le dashboard. Elle reste nécessaire ; ouvrir les liens Wokwi ne
démarre pas à lui seul toute cette chaîne. Les identifiants sont vérifiés, les
mesures absentes restent absentes et les anciennes trames ne sont pas rejouées.
Voir les [instructions d'exécution collective](../firmware/all_sensors/COLLECTIVE.md).

## Sauvegarde et reprise

- [État final de reprise](../output/wokwi-transfert/REPRISE-WOKWI.txt) et
  [état structuré](../output/wokwi-transfert/REPRISE-WOKWI.json).
- [Historique horodaté](../output/wokwi-transfert/HISTORIQUE-WOKWI.jsonl).
- [Sources préparées](../output/wokwi-transfert/upload/) et
  [rapports/archives vérifiés](../output/wokwi-transfert/verified/).
- [Sauvegarde complète](../output/sauvegardes-wokwi/WOKWI-REPRISE-DERNIERE.zip).

Ces fichiers permettent de retrouver les copies terminées et leurs preuves
après un arrêt du PC, sans recréer les projets déjà vérifiés.
