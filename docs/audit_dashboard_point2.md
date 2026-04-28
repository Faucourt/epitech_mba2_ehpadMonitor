# Audit point 2 - Dashboard central

Date audit: 2026-04-28

## Etat valide

- Dashboard principal accessible sur `http://localhost:3002/`.
- Backend accessible sur `http://localhost:8001/health`.
- WebSocket connecte les residents et les alertes au tableau de bord.
- Vue globale: 25 residents, constantes, risque ML, routine, chambre, profil de vie.
- Onglets presents: grille, plan EHPAD, vue 3D, nuit, transmissions, personnel, validation, historique.
- Date reelle, heure reelle, heure simulee et vitesse sont visibles.
- Les alertes actives indiquent resident, chambre, localisation precise, soignants notifies et capteurs actifs.

## Corrections faites

- La banniere orange `Scenario demo R005` n'est plus affichee en permanence.
- Les scenarios assignes au profil ne sont plus presentes comme des alertes orange.
- Separation visuelle:
  - scenario actif en orange,
  - fugue hors EHPAD en rouge,
  - suivi clinique ou scenario de profil en bleu discret.
- Le panneau resident ne force plus `Scenario demo` pour R005.
- Synchronisation WebSocket corrigee: si le backend dit qu'un resident n'a plus d'alerte active, le front supprime l'ancienne alerte locale.

## Points a ameliorer ensuite

- Ajouter un filtre clair entre `scenario actif`, `scenario profil`, `alerte clinique` et `risque ML`.
- Ajouter un resume compact en haut de la grille: actifs, au lit, repas, jardin, hors EHPAD, alertes N3+.
- Ajouter une vue `demo` globale propre, au lieu de lier la demo par defaut a R005.
- Harmoniser les libelles sans accents casses sur les zones anciennes.
- Verifier par capture navigateur les superpositions responsive sur petit ecran.
