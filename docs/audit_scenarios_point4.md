# Audit point 4 - Scenarios de vie et mouvements

Date audit: 2026-04-28

## Deja present

- Journee type simulee: lever, toilette, petit dejeuner, soins, animations, repas, sieste, gouter, diner, coucher, nuit.
- Regroupements repas matin/midi/soir en salle a manger selon autonomie.
- Residents dependants: repas en chambre et faible mobilite.
- Trajets reels par graphe de zones: chambres, couloirs, ascenseur, escalier, salle a manger, patio, jardin, kine, salle repos.
- Scenarios existants: chute couloir/chambre/jardin/trajet repas, malaise repas, errance nuit, fugue, isolement, fatigue kine, promenade jardin.

## Ajouts faits

- Nouveaux scenarios salle de bain:
  - `chute_salle_bain`
  - `toilette_matinale_fatigue`
- Nouveaux scenarios patio/jardin:
  - `desorientation_patio`
  - `regroupement_patio_fatigue`
  - `retour_jardin_fatigue`
- Le capteur `sdb_pir` est active pendant les episodes toilette/salle de bain.
- Les residents fragiles peuvent maintenant avoir des episodes de fatigue au patio/jardin.
- Le patio devient une vraie destination d'animation de groupe.
- Les scenarios sont exposes dans `/api/simulator/config`.

## Verification

- `/api/simulator/config` contient les nouveaux scenarios.
- `/api/residents` montre des residents en salle a manger pendant le petit dejeuner et des residents dependants en chambre.
- `/api/sensors/health` remonte les capteurs `sdb_pir` et les capteurs patio.

## A renforcer plus tard

- Ajouter une vue chronologique par resident: prochaine destination, trajet prevu, duree estimee.
- Afficher explicitement les scenarios actifs sur le plan 2D/3D avec une ligne de trajet.
- Ajouter des scenarios de visite famille, coiffeur, douche aidee, medecin, urgence collective.
