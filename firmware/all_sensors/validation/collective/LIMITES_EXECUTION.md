# Limites observées pendant les essais prolongés

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
des simulations, puis fonctionnement des 23 cartes ensemble avec le lanceur
Wokwi CI. Le jeton personnel nécessaire n'était pas configuré lors de la livraison.
Les mesures absentes ne doivent pas être remplacées par des valeurs plausibles.

[Retour aux preuves des essais](README.md)
