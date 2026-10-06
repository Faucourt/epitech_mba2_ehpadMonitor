# Limites observées pendant les essais prolongés

Mise à jour du 5 octobre 2026 : le modèle MAX30102 et l'acquisition partagée
ont été corrigés pour les débordements FIFO et les transferts I²C incomplets.
Des tests locaux couvrent ces défauts ; ils ne démontrent pas encore la cause
de l'anomalie R001 ci-dessous ni sa disparition dans Wokwi. Les exports sources
ont été régénérés et les 45 binaires collectifs recompilés et contrôlés. La
nouvelle tentative Wokwi CI a été refusée pour quota mensuel épuisé. Le [bilan de flotte](../../../max30102_custom/FLOTTE.md)
précise les contrôles locaux et les essais restant à faire. Un [banc autonome compilé et son bilan](../../../max30102_custom/README.md)
permettent de vérifier la correction sur une seule carte.

Mise à jour du 6 octobre 2026 : les 45 copies collectives corrigées ont ensuite
été sauvegardées sur Wokwi et leurs 733 fichiers contrôlés par téléchargement.
Quatre modèles ont été observés : R001, R002, R009 et l'entrée. Ces observations
ne valident pas la stabilité prolongée ni l'exécution simultanée de la flotte.
Le [bilan de publication](../../../../docs/BILAN-WOKWI-2026-10-06.md) donne les
liens, rapports et sauvegardes ; les incidents historiques ci-dessous restent
des limites à investiguer.

Les preuves de ce dossier valident les champs effectivement observés et leur
réception. Elles ne constituent pas une validation de fonctionnement continu.

Lors de la session Firefox du 3 octobre 2026 :

- Windows a signalé un manque de mémoire (`OutOfMemoryException`, fichier de
  pagination insuffisant) avec plusieurs simulations ouvertes. Des pages Wokwi
  ont planté ou cessé d'avancer. Deux résidents et l'entrée ont été conservés pour
  le contrôle final ; la troisième carte a été arrêtée pour libérer de la mémoire.
- Après une exécution prolongée de R001, le MAX30102 a fourni `red_raw=156672` et
  `ir_raw=89856`, hors de la plage nominale du signal produit par ce modèle.
  FC et SpO₂ étaient nulles ; le dashboard les a affichées « non mesuré ».
  La cause de cette anomalie de lecture n'est pas encore isolée. Une relance de
  simulation ne constitue pas une correction démontrée du problème.
- Le redémarrage de la stack efface son historique d'acquisition en mémoire.
  Les traces archivées ici restent des preuves datées, indépendantes de cet état.

À vérifier ensuite : stabilité des lectures optiques après interruptions, reprise
des simulations, puis fonctionnement de la version corrigée du pilote de
23 cartes et de la flotte complète de 45 cartes avec le lanceur Wokwi CI.
Le jeton personnel nécessaire n'était pas configuré lors de l'essai navigateur
initial ; une preuve CLI datée du 3 octobre existe pour la version antérieure,
et la tentative du 5 octobre a été refusée pour quota épuisé.
Les mesures absentes ne doivent pas être remplacées par des valeurs plausibles.

[Retour aux preuves des essais](README.md)
